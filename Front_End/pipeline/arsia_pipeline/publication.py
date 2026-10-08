"""Trusted v2 database loader and versioned snapshot composition."""
from contextlib import contextmanager, nullcontext
from datetime import date, timedelta
import hashlib
import json
import threading
from pathlib import Path
from uuid import uuid4

from psycopg.types.json import Jsonb
from psycopg.conninfo import make_conninfo
from psycopg.errors import QueryCanceled

from . import registry, store
from .config import inside, read_config
from .errors import ImportCancelled, NeedsInput, ValidationFailure

ARTIFACTS = {
    "crash": ("canonical_crash", "canonical_path", "crashes.jsonl"),
    "unit": ("canonical_unit", "units_path", "units.jsonl"),
    "casualty": ("canonical_casualty", "casualties_path", "casualties.jsonl"),
    "observation": ("canonical_observation", "observations_path", "observations.jsonl"),
}

PUBLICATION_STATEMENT_TIMEOUT_MS = 120_000
CANCEL_POLL_SECONDS = 0.25


@contextmanager
def publication_transaction(conn, job_id, cancel):
    """Bound SQL duration and interrupt this connection on a durable cancellation.

    The watcher has its own bounded connection, never executes SQL on the loader
    connection, and is joined before that connection can be reused for another job.
    """
    cfg = read_config()
    watch_cfg = {**cfg, "dsn": make_conninfo(cfg["dsn"], connect_timeout=3)}
    done = threading.Event()
    failures = []

    def watch():
        try:
            with store.connect(watch_cfg) as monitor:
                monitor.execute("SET statement_timeout='2s'")
                while not done.wait(CANCEL_POLL_SECONDS):
                    state = monitor.execute("SELECT status FROM jobs WHERE id=%s", (job_id,)).fetchone()
                    if not state or state["status"] in {"cancel_requested", "cancelled"}:
                        raise ImportCancelled()
        except Exception as exc:
            if not done.is_set():
                failures.append(exc)
                # libpq cancellation targets this exact backend/session. It does
                # not kill the worker or interrupt another database connection.
                try:
                    conn.cancel_safe(timeout=2)
                except Exception:
                    pass  # The statement timeout remains a second bound.

    cancel()
    try:
        with conn.transaction():
            conn.execute("SELECT set_config('statement_timeout',%s,true)", (str(PUBLICATION_STATEMENT_TIMEOUT_MS),))
            thread = threading.Thread(target=watch, name="publication-cancel", daemon=True)
            thread.start()
            try:
                yield
            finally:
                done.set()
                thread.join()
            if failures:
                raise failures[0]
            cancel()
    except QueryCanceled as exc:
        # The transaction has rolled back before consulting durable job state.
        if failures:
            raise failures[0] from exc
        cancel()
        message = ("Database publication SQL exceeded its time limit; candidate rolled back."
                   if "statement timeout" in str(exc) else
                   "Database publication SQL was cancelled; candidate rolled back.")
        raise ValidationFailure(message, [{"code": "PUBLICATION_SQL_CANCELLED", "status": "block", "message": message}]) from exc


def blocked(message, metrics=None):
    raise ValidationFailure(message, [{"code": "DB_RECONCILIATION", "status": "block", "message": message, "metrics": metrics or {}}])


def admitted_paths(job, result):
    from .trusted_qa import POLICY, trusted_implementation, LOADED_IMPLEMENTATION
    admission = result.get("admission", {})
    contract = result.get("source_contract", {})
    if admission.get("status") != "admitted" or any(q.get("status") == "block" for q in result.get("qa", [])):
        blocked("Only independently admitted full-data candidates may publish")
    if admission.get("source_contract_sha256") != registry.execution_contract_hash(contract):
        blocked("Publication contract changed after QA")
    if (admission.get('policy_version') != POLICY or
            admission.get('trusted_implementation') != trusted_implementation() or
            trusted_implementation() != LOADED_IMPLEMENTATION):
        blocked('Current candidate QA does not match the loaded trusted implementation')
    adapter = registry.read(result.get("adapter_version_id"))
    if adapter["code_sha256"] != admission.get("adapter_sha256") or contract.get("source", {}).get("source_id") != result["source_id"]:
        blocked("Registered adapter or source identity differs from admitted candidate")
    if registry.normalized_contract(adapter['contract']) != registry.normalized_contract(contract):
        blocked('Registered contract differs from the current independently verified candidate')
    paths = {}
    for grain, (_, key, name) in ARTIFACTS.items():
        path = inside(result[key], job["work_dir"])
        if path.is_symlink() or not path.is_file():
            blocked("Admitted artifact is missing or not a regular file")
        expected = admission.get("artifact_hashes", {}).get(name)
        if not expected or sha(path) != expected:
            blocked("Candidate artifacts changed after independent QA")
        paths[grain] = path
    if admission.get('evidence',{}).get('row_preprocessing'):
        lineage=inside(paths['crash'].parent/'row-lineage.jsonl',job['work_dir'])
        if lineage.is_symlink() or not lineage.is_file() or sha(lineage)!=admission.get('artifact_hashes',{}).get('row-lineage.jsonl'):
            blocked('Original row destinations changed after independent QA')
    return paths


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024**2), b""):
            h.update(chunk)
    return h.hexdigest()


def removed_membership(conn, previous, candidate, cancel):
    """Count actual omitted canonical identities, never infer from equal totals."""
    removed = []
    # The new batch has no useful permanent-table statistics yet. Index its
    # narrow keys explicitly rather than repeatedly scanning JSON payloads.
    selects = [f"SELECT '{grain}'::text AS grain,payload->>'canonical_id' AS canonical_id FROM {table} WHERE batch_id=%s"
               for grain, (table, _, _) in ARTIFACTS.items()]
    conn.execute('CREATE TEMP TABLE arsia_snapshot_keys ON COMMIT DROP AS ' + ' UNION ALL '.join(selects), (candidate,) * len(selects))
    conn.execute('CREATE UNIQUE INDEX ON pg_temp.arsia_snapshot_keys(grain,canonical_id)')
    conn.execute('ANALYZE pg_temp.arsia_snapshot_keys')
    for grain, (table, _, _) in ARTIFACTS.items():
        cancel()
        # Names are the fixed trusted table constants. Null old identities
        # cannot be proven retained and therefore need evidence too.
        rows = conn.execute(f"""SELECT old.payload->>'resource_role' AS role,count(*) AS count
            FROM {table} old WHERE old.batch_id=%s AND NOT EXISTS
            (SELECT 1 FROM pg_temp.arsia_snapshot_keys new WHERE new.grain=%s
             AND new.canonical_id=old.payload->>'canonical_id')
            GROUP BY old.payload->>'resource_role'""", (previous, grain)).fetchall()
        removed.extend({'grain': grain, 'role': row['role'], 'count': row['count']} for row in rows)
    conn.execute('DROP TABLE pg_temp.arsia_snapshot_keys')
    return removed


def copy_candidate(conn, batch, paths, result, cancel):
    statements = {
        "crash": "COPY canonical_crash(batch_id,record_id,year,month,severity,fatalities,casualties,payload) FROM STDIN",
        "unit": "COPY canonical_unit(batch_id,ordinal,payload) FROM STDIN",
        "casualty": "COPY canonical_casualty(batch_id,record_id,crash_id,unit_id,payload) FROM STDIN",
        "observation": "COPY canonical_observation(batch_id,record_id,year,month,payload) FROM STDIN",
    }
    for grain, path in paths.items():
        digest = hashlib.sha256()
        with conn.cursor().copy(statements[grain]) as copy, path.open("rb") as handle:
            for index, line in enumerate(handle):
                if index % 1000 == 0:
                    cancel()
                digest.update(line)
                row = json.loads(line)
                key = row["canonical_id"]
                if grain == "crash":
                    values = (batch, key, row["year"], row.get("month"), row.get("severity"), row.get("fatalities"), row.get("casualties"), Jsonb(row))
                elif grain == "unit":
                    values = (batch, index, Jsonb(row))
                elif grain == "casualty":
                    values = (batch, key, row.get("crash_id"), row.get("unit_record_id"), Jsonb(row))
                else:
                    values = (batch, key, row["year"], row.get("month"), Jsonb(row))
                copy.write_row(values)
        if digest.hexdigest() != result["admission"]["artifact_hashes"][ARTIFACTS[grain][2]]:
            blocked("Candidate changed while loading; transaction rolled back")


def counts(conn, batch):
    return {grain: conn.execute("SELECT count(*) AS n FROM " + table + " WHERE batch_id=%s", (batch,)).fetchone()["n"]
            for grain, (table, _, _) in ARTIFACTS.items()}


def all_rows_sql():
    return " UNION ALL ".join("SELECT payload FROM " + table + " WHERE batch_id=%s" for table, _, _ in ARTIFACTS.values())


def verify(conn, batch, result, candidate=True):
    total = counts(conn, batch)
    summary = result["summary"]
    expected = counts_from_result(result)
    if candidate and total != expected:
        blocked("Stored canonical grain counts differ from independently verified candidate", {"expected": expected, "actual": total})
    aggregate = crash_summary(conn, batch)
    if candidate:
        for key in ("crash_count", "fatal_crash_count", "fatalities", "casualties"):
            # Observation candidates have no crash semantics.
            if expected["crash"] or result.get("source", {}).get("grain") == "crash":
                if summary.get(key) != aggregate[key]:
                    blocked("Stored crash metrics differ from independent QA", {"metric": key, "expected": summary.get(key), "actual": aggregate[key]})
    # COPY introduces a new batch not represented in permanent-table statistics.
    # Do not materialize full JSON payloads and rescan them once per child. Build
    # a narrow, transaction-local lookup, index it, and collect actual statistics.
    with conn.transaction():
        conn.execute("""CREATE TEMP TABLE arsia_publication_keys ON COMMIT DROP AS
            SELECT payload->>'source_id' AS source_id,
                   payload->>'canonical_id' AS canonical_id,
                   payload->>'resource_role' AS role,
                   payload->>'record_id' AS record_id,
                   coalesce(payload->'relations','{}') AS relations
            FROM (""" + all_rows_sql() + """) candidate""", (batch,)*4)
        mismatch = conn.execute("""SELECT
            count(*) FILTER (WHERE source_id IS DISTINCT FROM %s) AS wrong_source,
            count(*) FILTER (WHERE nullif(canonical_id,'') IS NULL OR
                nullif(record_id,'') IS NULL OR nullif(role,'') IS NULL) AS missing_keys
            FROM pg_temp.arsia_publication_keys""", (result["source_id"],)).fetchone()
        if mismatch["wrong_source"] or mismatch["missing_keys"]:
            blocked("Stored rows violate source identity or complete-key lineage", mismatch)
        duplicates = conn.execute("""SELECT count(*) AS n FROM (
            SELECT canonical_id FROM pg_temp.arsia_publication_keys
            GROUP BY canonical_id HAVING count(*)>1) d""").fetchone()["n"]
        conn.execute("CREATE INDEX ON pg_temp.arsia_publication_keys(role,record_id)")
        conn.execute("ANALYZE pg_temp.arsia_publication_keys")
        orphans = conn.execute("""WITH links AS MATERIALIZED (
            SELECT l.key AS parent,l.value AS parent_key
            FROM pg_temp.arsia_publication_keys child
            CROSS JOIN LATERAL jsonb_each_text(child.relations) l
            WHERE l.value IS NOT NULL)
            SELECT count(*) AS n FROM links l WHERE NOT EXISTS (
                SELECT 1 FROM pg_temp.arsia_publication_keys parent
                WHERE parent.role=l.parent AND parent.record_id=l.parent_key)""").fetchone()["n"]
        conn.execute("DROP TABLE pg_temp.arsia_publication_keys")
    if duplicates or orphans:
        blocked("Stored canonical identities or role-specific relationships do not reconcile", {"duplicates": duplicates, "orphans": orphans})
    return {"status": "pass", **{"canonical_" + grain + "_count": count for grain, count in total.items()},
            "duplicate_key_count": duplicates, "orphan_count": orphans, "wrong_source_count": mismatch["wrong_source"]}


def crash_summary(conn, batch):
    from .query import aggregate_sql
    return conn.execute("SELECT " + aggregate_sql() + " FROM canonical_crash WHERE batch_id=%s", (batch,)).fetchone()


def merge_intervals(intervals):
    ordered = sorted((date.fromisoformat(v["from"]), date.fromisoformat(v["to"])) for v in intervals)
    merged = []
    for first, last in ordered:
        if merged and first <= merged[-1][1] + timedelta(days=1):
            merged[-1][1] = max(merged[-1][1], last)
        else:
            merged.append([first, last])
    return [{"from": a.isoformat(), "to": b.isoformat()} for a,b in merged]


def preserve_base(conn, batch, base, mode, update, cancel, *, bounded_representation=False):
    """New rows already loaded. Retain old facts according to explicit update."""
    first, last = date.fromisoformat(update["from"]), date.fromisoformat(update["to"])
    if mode == "partition" and (first.day != 1 or last != date(last.year, last.month, 1).replace(day=__import__("calendar").monthrange(last.year,last.month)[1])):
        raise NeedsInput("Partition updates currently require complete calendar months; provide an evidenced monthly interval.")
    lo, hi = first.year*12+first.month, last.year*12+last.month
    if mode == "partition":
        for table in ("canonical_crash", "canonical_observation"):
            invalid = conn.execute("SELECT count(*) AS n FROM " + table + " WHERE batch_id=%s AND (month IS NULL OR year*12+month NOT BETWEEN %s AND %s)", (batch, lo, hi)).fetchone()["n"]
            if invalid:
                raise NeedsInput("Partition rows must all have month precision within the declared replacement interval.")
        incomplete = conn.execute("SELECT count(*) AS n FROM canonical_crash WHERE batch_id=%s AND month IS NULL AND year BETWEEN %s AND %s",
                                  (base, first.year, last.year)).fetchone()["n"]
        if incomplete:
            raise NeedsInput("Existing year-precision rows cannot be safely replaced by this partition.")
    if bounded_representation:
        # A bounded query may upsert inside its declared dates, but a reused key
        # cannot silently move or overwrite a historical record outside them.
        for grain in ('crash','observation'):
            table=ARTIFACTS[grain][0]
            conflict=conn.execute("SELECT count(*) AS n FROM "+table+" o JOIN "+table+
                " n ON n.batch_id=%s AND n.record_id=o.record_id WHERE o.batch_id=%s AND "
                "(coalesce(length(o.payload->>'occurrence_date'),0)<>10 OR "
                "o.payload->>'occurrence_date' NOT BETWEEN %s AND %s)",
                (batch,base,first.isoformat(),last.isoformat())).fetchone()['n']
            if conflict:
                raise NeedsInput('Bounded query collides with historical keys outside its authorized date interval; preserve the existing release.')
    retained = {}
    for grain in ("crash", "observation"):
        table = ARTIFACTS[grain][0]
        cols = "record_id,year,month,severity,fatalities,casualties,payload" if grain == "crash" else "record_id,year,month,payload"
        outside = " AND (o.year*12+o.month NOT BETWEEN %s AND %s OR o.year<%s OR o.year>%s)" if mode == "partition" else ""
        params = (batch, base, batch) + ((lo, hi, first.year, last.year) if mode == "partition" else ())
        retained[grain] = conn.execute("INSERT INTO " + table + "(batch_id," + cols + ") SELECT %s," +
            ",".join("o."+c for c in cols.split(",")) + " FROM " + table + " o WHERE o.batch_id=%s AND NOT EXISTS (SELECT 1 FROM " +
            table + " n WHERE n.batch_id=%s AND n.record_id=o.record_id)" + outside, params).rowcount
        cancel()
    # Children of a replaced partition are replaced together. Incremental upsert
    # retains absent stable child keys; it never interprets absence as deletion.
    for grain in ("unit", "casualty"):
        table = ARTIFACTS[grain][0]
        identity = "payload->>'canonical_id'"
        condition = ""
        params = [batch, base, batch]
        if mode == "partition":
            condition = """ AND EXISTS (SELECT 1 FROM jsonb_each_text(coalesce(o.payload->'relations','{}')) rel
                JOIN canonical_crash p ON p.batch_id=%s AND p.payload->>'resource_role'=rel.key AND p.payload->>'record_id'=rel.value
                WHERE (p.year*12+p.month NOT BETWEEN %s AND %s OR p.year<%s OR p.year>%s))"""
            params += [base, lo, hi, first.year, last.year]
        if grain == "unit":
            offset = conn.execute("SELECT coalesce(max(ordinal)+1,0) AS n FROM canonical_unit WHERE batch_id=%s", (batch,)).fetchone()["n"]
            query = """INSERT INTO canonical_unit(batch_id,ordinal,payload)
                SELECT %s,(row_number() OVER (ORDER BY o.ordinal)-1)+""" + str(offset) + """,o.payload FROM canonical_unit o
                WHERE o.batch_id=%s AND NOT EXISTS (SELECT 1 FROM canonical_unit n WHERE n.batch_id=%s AND n.""" + identity + "=o." + identity + ")" + condition
        else:
            query = """INSERT INTO canonical_casualty(batch_id,record_id,crash_id,unit_id,payload)
                SELECT %s,o.record_id,o.crash_id,o.unit_id,o.payload FROM canonical_casualty o
                WHERE o.batch_id=%s AND NOT EXISTS (SELECT 1 FROM canonical_casualty n WHERE n.batch_id=%s AND n.record_id=o.record_id)""" + condition
        retained[grain] = conn.execute(query, params).rowcount
        cancel()
    return retained


def composed_result(conn, batch, candidate, base_result, retained, mode):
    from .query import aggregate_sql
    result = dict(candidate)
    result["candidate_summary"] = candidate["summary"]
    total = counts(conn, batch)
    summary = dict(candidate["summary"])
    if candidate["source"]["grain"] == "crash":
        summary.update(crash_summary(conn, batch))
    else:
        summary["observation_count"] = total["observation"]
    summary.update(canonical_unit_count=total["unit"], canonical_casualty_count=total["casualty"],
                   unit_count=total["unit"] if candidate["capabilities"].get("units") else None,
                   raw_record_count=sum(total.values()))
    previous = base_result.get("coverage", base_result.get("source", {}).get("coverage"))
    coverage = candidate["coverage"]
    result["coverage"] = {"from": min(previous["from"], coverage["from"]), "to": max(previous["to"], coverage["to"])}
    from .coverage_policy import complete_intervals, VERSION as COVERAGE_VERSION
    previous_intervals = complete_intervals(base_result)
    result["coverage_intervals"] = merge_intervals(previous_intervals + complete_intervals(candidate))
    result["temporal_coverage"] = {"version": COVERAGE_VERSION, "complete_intervals": result["coverage_intervals"], "basis":"verified-composition"}
    summary.update(year_from=int(result["coverage"]["from"][:4]), year_to=int(result["coverage"]["to"][:4]))
    result["summary"] = summary
    result["source"] = {**candidate["source"], "coverage": result["coverage"]}
    result["composition"] = {"mode": mode, "retained_counts": retained, "candidate_counts": counts_from_result(candidate), "final_counts": total}
    result["trend"] = conn.execute("SELECT year," + aggregate_sql() + " FROM canonical_crash WHERE batch_id=%s GROUP BY year ORDER BY year", (batch,)).fetchall()
    result["monthly_trend"] = conn.execute("SELECT year,month," + aggregate_sql() + " FROM canonical_crash WHERE batch_id=%s AND month IS NOT NULL GROUP BY year,month ORDER BY year,month", (batch,)).fetchall()
    result["severity"] = conn.execute("SELECT severity AS code,payload->>'severity_label' AS label,count(*) AS count FROM canonical_crash WHERE batch_id=%s GROUP BY severity,payload->>'severity_label' ORDER BY severity", (batch,)).fetchall()
    if result.get("units", {}).get("status") == "available":
        result["units"] = {**result["units"], "rows": conn.execute("SELECT payload->>'unit_type' AS unit_type,count(*) AS count FROM canonical_unit WHERE batch_id=%s GROUP BY 1 ORDER BY 1", (batch,)).fetchall()}
    return result


def counts_from_result(result):
    summary = result["summary"]
    return {"crash": summary.get("crash_count") or 0, "unit": summary.get("canonical_unit_count") or 0,
            "casualty": summary.get("canonical_casualty_count") or 0,
            "observation": result.get("evidence", {}).get("candidate_counts", {}).get("observation", summary.get("observation_count") or 0)}


def publish(job, result, cancel, lock_conn=None):
    from .agent import safe
    from .publication_identity import identify, legacy_equivalent
    paths = admitted_paths(job, result)
    identity = identify(result, paths, cancel)
    source, candidate_fp = result["source_id"], result["fingerprint"]
    mode = result["update"]["mode"]
    if mode not in {"snapshot", "partition", "incremental"}:
        blocked("Unknown source update mode")
    from .publication_policy import require_active_attempt, require_source_level
    with store.connect() as precheck:
        require_active_attempt(precheck, job)
    store.update_job(job["id"], "publishing", "Loading independently admitted source candidate; existing release remains available")
    with (nullcontext(lock_conn) if lock_conn is not None else store.connect()) as conn, publication_transaction(conn, job["id"], cancel):
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (store.LOCK,))
        require_active_attempt(conn, job)
        current = conn.execute("SELECT r.id,r.sources FROM current_release c JOIN releases r ON r.id=c.release_id").fetchone()
        sources = dict(current["sources"]) if current else {}
        base = conn.execute("SELECT * FROM batches WHERE id=%s", (sources[source],)).fetchone() if source in sources else None
        require_source_level(result, base['result'] if base else None)
        previous = None
        matches = conn.execute("""SELECT id,candidate_fingerprint,result FROM batches WHERE source_id=%s
            AND result->'publication_identity'->>'sha256'=%s ORDER BY created_at DESC""",
            (source, identity['sha256'])).fetchall()
        for match in matches:
            historical_input = identity['input_replay_sha256']
            if (base and match['id'] == base['id'] or match['candidate_fingerprint'] == candidate_fp
                    or historical_input and historical_input == match['result']['publication_identity'].get('input_replay_sha256')):
                previous = match
                break
        if not previous:
            for old in conn.execute("SELECT id,result FROM batches WHERE source_id=%s AND candidate_fingerprint=%s ORDER BY created_at DESC", (source, candidate_fp)):
                if legacy_equivalent(old['result'], result):
                    previous = old
                    break
        unchanged = bool(previous and base)
        if unchanged:
            batch, public = base["id"], dict(base["result"])
            public["database_verification"] = verify(conn, batch, public, candidate=False)
        else:
            if base:
                old_source = base["result"].get("source", {})
                for key in ("publisher", "dataset_url", "grain"):
                    if old_source.get(key) and old_source[key] != result["source"].get(key):
                        raise NeedsInput("A source identity cannot change publisher, official dataset URL or grain. Use a distinct source_id for a different dataset.")
                old_coverage = base["result"].get("coverage", old_source.get("coverage"))
                old_summary = base["result"].get("summary", {})
                if not old_coverage and old_summary.get("year_from") and old_summary.get("year_to"):
                    old_coverage = {"from": str(old_summary["year_from"])+"-01-01", "to": str(old_summary["year_to"])+"-12-31"}
                from .coverage_policy import complete_intervals
                # Observed bounds are not a completeness claim. Actual lost
                # records are checked after COPY for every update mode below.
                # Retain the stricter range guard for proved complete periods.
                if mode == "snapshot" and any(result["coverage"]["from"] > interval["from"] or result["coverage"]["to"] < interval["to"]
                                               for interval in complete_intervals(base['result'])):
                    raise NeedsInput("This snapshot has narrower coverage than the published source. Provide an evidenced partition update to preserve older history.")
                if mode != "snapshot" and not old_source:
                    raise NeedsInput("Combining a v2 partition with an older native adapter requires a complete documented snapshot first.")
                from .update_compatibility import require_compatible_update
                require_compatible_update(base["result"].get("source_contract"), result["source_contract"], mode,
                                          previous_admission=base['result'].get('admission'), candidate_admission=result.get('admission'))
            batch = uuid4()
            fingerprint = registry.digest_json({"candidate": candidate_fp, "publication": identity['sha256'],
                "base": str(base["id"]) if base and mode != "snapshot" else None, "mode": mode})
            public = safe(result)
            from .coverage_policy import complete_intervals
            public["coverage_intervals"] = complete_intervals(result)
            conn.execute("""INSERT INTO batches(id,job_id,source_id,fingerprint,result,source_version_id,adapter_version_id,update_mode,base_batch_id,candidate_fingerprint)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", (batch, job["id"], source, fingerprint, Jsonb(public), result["source_version_id"],
                result["adapter_version_id"], mode, base["id"] if base and mode != "snapshot" else None, candidate_fp))
            copy_candidate(conn, batch, paths, result, cancel)
            candidate_verification = verify(conn, batch, result)
            if base and mode != "snapshot":
                retained = preserve_base(conn, batch, base["id"], mode, result["update"], cancel,
                    bounded_representation=bool(result.get("admission",{}).get("evidence",{}).get("representation_proofs")))
                public = safe(composed_result(conn, batch, result, base["result"], retained, mode))
                for grain, count in counts(conn, batch).items():
                    if count != counts_from_result(result)[grain] + retained[grain]:
                        blocked("Retained history and candidate counts failed composition reconciliation")
            if base:
                from .source_completeness import require_removal_authority
                from .native_membership import transition_plan, removals as legacy_removals
                key_transition = transition_plan(base['result'], result)
                removed = (legacy_removals(conn,base['id'],batch,key_transition,cancel) if key_transition is not None
                           else removed_membership(conn,base['id'],batch,cancel))
                # Check final composed membership for every mode. Switching to
                # partition/incremental must not bypass removal evidence.
                public['update_membership_verification'] = require_removal_authority(
                    base['result'].get('source_contract'), result, removed, previous_published_at=base['created_at'])
                if key_transition is not None: public['update_membership_verification']['native_key_transition']=key_transition
            public["candidate_database_verification"] = candidate_verification
            public['publication_identity'] = identity
            # Snapshot/new-source rows have not changed since candidate verification.
            public["database_verification"] = (verify(conn, batch, public, candidate=False)
                if base and mode != "snapshot" else candidate_verification)
            from .publication_summary import capture
            public['query_facts'] = capture(conn, batch, public)
            conn.execute("UPDATE batches SET result=%s WHERE id=%s", (Jsonb(public), batch))
        cancel()
        state = conn.execute("SELECT status FROM jobs WHERE id=%s FOR UPDATE", (job["id"],)).fetchone()
        if state["status"] == "cancel_requested":
            raise ImportCancelled()
        if unchanged:
            release_id, status = current["id"], "no_change"
        else:
            sources[source] = str(batch)
            release_id, status = uuid4(), "succeeded"
            conn.execute("INSERT INTO releases(id,sources) VALUES(%s,%s)", (release_id, Jsonb(sources)))
            conn.execute("INSERT INTO current_release(release_id) VALUES(%s) ON CONFLICT(singleton) DO UPDATE SET release_id=excluded.release_id", (release_id,))
        public["publication_evidence"] = {"input_fingerprint": candidate_fp, "attempt_id": str(job["attempt_id"]),
            "reason": ('same_publication_content' if str(previous['id']) == str(batch) else 'historical_input_replay') if unchanged else 'new_publication_content',
            "candidate_publication_identity": identity,
            "candidate_validation": safe({"admission": result['admission'], "qa": result['qa'],
                "adapter_version_id": result['adapter_version_id'], "source_version_id": result['source_version_id'],
                "fingerprint": candidate_fp, "evidence": result.get('evidence', {})}),
            "reused_candidate_batch_id": str(previous["id"]) if unchanged else None, "reused_batch_id": str(batch) if unchanged else None,
            "note": "Repeated input retains the current source version and never rolls back later updates."}
        message = "Identical source input was already admitted; current release retained" if unchanged else "Verified source version published atomically; other sources retained"
        conn.execute("""UPDATE jobs SET status=%s,stage=%s,message=%s,source_id=%s,profile_id=%s,batch_id=%s,release_id=%s,
            result=%s,qa=%s,error=NULL,questions=NULL,updated_at=now(),events=events||%s::jsonb WHERE id=%s""",
            (status, status, message, source, result["profile_id"], batch, release_id, Jsonb(public), Jsonb(result["qa"]), Jsonb([store.event(status,message)]), job["id"]))
        conn.execute("UPDATE attempts SET status=%s,finished_at=now() WHERE id=%s", (status, job["attempt_id"]))
        conn.execute("UPDATE agent_sessions SET status=%s,updated_at=now() WHERE job_id=%s", (status, job["id"]))
    return status
