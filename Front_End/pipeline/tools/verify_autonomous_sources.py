"""Read-only acceptance of a completed autonomous source job.

Only GET requests and a REPEATABLE READ, READ ONLY PostgreSQL transaction are
used. This never submits/retries a job, invokes a model, repairs inputs or
registers/publishes an adapter. Reports contain aggregates/hashes, no raw rows.
The independently built oracle is acceptance-only and must not enter the Agent.
"""
from __future__ import annotations

import argparse
from collections import Counter
import calendar
from datetime import datetime, timezone
import hashlib
import http.client
import json
import math
from pathlib import Path
import socket
import sqlite3
import sys
import tempfile
from urllib.parse import urlencode
from uuid import UUID

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "pipeline"))
METRICS = ("crash_count", "fatal_crash_count", "fatalities", "casualties")
TABLES = {"crash": "canonical_crash", "unit": "canonical_unit", "casualty": "canonical_casualty", "observation": "canonical_observation"}


def stable(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


class HashBag:
    """Order-independent content signature; only 32-byte record hashes retained."""
    def __init__(self):
        self.values = []

    def add(self, value):
        self.values.append(hashlib.sha256(stable(value).encode()).digest())

    def result(self):
        digest = hashlib.sha256()
        for value in sorted(self.values):
            digest.update(value)
        return {"rows": len(self.values), "distinct": len(set(self.values)), "sha256": digest.hexdigest()}


class Checks:
    def __init__(self):
        self.rows = []

    def equal(self, label, actual, expected):
        # JSON distinguishes integer 1, float 1.0, boolean true and null. No
        # tolerance, truthiness or missing-to-zero normalization is permitted.
        same = stable(actual) == stable(expected)
        self.rows.append({"check": label, "actual": actual, "expected": expected, "passed": same})

    def report(self):
        return {"passed": sum(c["passed"] for c in self.rows), "failed": sum(not c["passed"] for c in self.rows), "checks": self.rows}


def compare_metrics(checks, prefix, actual, expected):
    for metric in METRICS:
        checks.equal(prefix + "." + metric, actual.get(metric), expected[metric])


def compare_periods(checks, prefix, actual, expected, monthly=False):
    key = lambda r: f"{r['year']:04d}-{r['month']:02d}" if monthly else f"{r['year']:04d}"
    rows = {key(row): row for row in actual}
    checks.equal(prefix + ".unique_periods", len(rows), len(actual))
    checks.equal(prefix + ".periods", sorted(rows), sorted(expected))
    for period, metrics in expected.items():
        compare_metrics(checks, prefix + "." + period, rows.get(period, {}), metrics)


def expected_severity(oracle, contract):
    crash = next(r for r in contract["resources"] if r["grain"] == "crash")
    definitions = crash["mapping"]["severity"]["categories"]
    result = Counter()
    for raw, count in oracle["severity"].items():
        if raw not in definitions:
            raise ValueError("Published contract omits an independently observed source severity")
        result[definitions[raw]["code"]] += count
    return dict(result)


def compare_report(checks, prefix, report, oracle, contract, query=False):
    compare_metrics(checks, prefix + ".summary", report.get("summary", {}), oracle["summary"])
    compare_periods(checks, prefix + ".yearly", report.get("yearly" if query else "trend", []), oracle["yearly"])
    compare_periods(checks, prefix + ".monthly", report.get("monthly" if query else "monthly_trend", []), oracle["monthly"], True)
    severity = {r["code"]: r["count"] for r in report.get("severity", [])}
    wanted = expected_severity(oracle, contract)
    for category in sorted(set(severity) | set(wanted)):
        checks.equal(prefix + ".severity." + category, severity.get(category, 0), wanted.get(category, 0))
    checks.equal(prefix + ".severity.unique_codes", len(severity), len(report.get("severity", [])))
    if oracle.get("oracle_version", 2) >= 3:
        coverage = report.get("coverage") or contract["source"].get("coverage", {})
        first, last = oracle["date_range"]
        checks.equal(prefix + ".coverage_contains_every_input_date",
                     isinstance(coverage.get("from"), str) and isinstance(coverage.get("to"), str)
                     and coverage["from"] <= first and coverage["to"] >= last, True)
    units = report.get("units", {})
    checks.equal(prefix + ".units.status", units.get("status"), "available" if oracle["availability"]["units"] else "unavailable")
    if oracle["availability"]["units"]:
        observed = {r["unit_type"]: r["count"] for r in units.get("rows", [])}
        checks.equal(prefix + ".units.categories", observed, oracle["unit_type"])
    if not query:
        for key, grain in (("canonical_unit_count", "unit"), ("canonical_casualty_count", "casualty")):
            checks.equal(prefix + ".summary." + key, report.get("summary", {}).get(key), oracle["grains"][grain]["keys"]["rows"])
        checks.equal(prefix + ".summary.unit_count", report.get("summary", {}).get("unit_count"), oracle["grains"]["unit"]["keys"]["rows"] if oracle["availability"]["units"] else None)


class GetOnlyAPI:
    def __init__(self, via_website=False):
        self.via_website = via_website

    def get(self, path):
        from arsia_pipeline.config import read_config
        config = read_config()
        if self.via_website:
            connection = http.client.HTTPConnection("127.0.0.1", 3100, timeout=90)
            path = "/api/imports" + path
        else:
            connection = http.client.HTTPConnection("localhost", timeout=90)
            connection.sock = socket.socket(socket.AF_UNIX)
            connection.sock.settimeout(90)
            connection.sock.connect(config["socket_path"])
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            encoded = response.read(16 * 1024**2 + 1)
            if response.status != 200 or len(encoded) > 16 * 1024**2:
                raise RuntimeError(f"Read-only API request failed with HTTP {response.status} or exceeded response bound")
            return json.loads(encoded)
        finally:
            connection.close()


def _canonical_key(resource, raw_key):
    if not isinstance(raw_key, list) or len(raw_key) != len(resource["key"]):
        raise ValueError("Canonical raw key differs from its complete source key definition")
    return dict(zip(resource["key"], raw_key, strict=True))


def _fact(grain, row, resource, roles):
    key = _canonical_key(resource, row["raw_key"])
    result = {"key": key}
    if grain == "crash":
        result.update({k: row.get(k) for k in ("occurrence_date", "date_precision", "raw_severity", "is_fatal_crash", "fatalities", "casualties", "declared_units", "declared_casualties")})
    elif grain == "unit":
        result.update({k: row.get(k) for k in ("unit_type", "count_eligible", "declared_casualties")})
    elif grain == "casualty":
        result.update({k: row.get(k) for k in ("raw_injury", "is_fatal")})
    if grain in {"unit", "casualty"}:
        relations = {}
        for parent_role, encoded in row.get("relations", {}).items():
            parent = roles[parent_role]
            relations[parent["grain"]] = _canonical_key(parent, json.loads(encoded)) if encoded is not None else None
        result["relations"] = relations
    return key, result


class GeographyVerifier:
    """Independent per-key coordinate comparison backed by a local SQLite index.

    Only aggregate mismatches reach the report. Optional unsupported geography
    is explicitly unverified, never silently promoted to geographic success.
    """
    def __init__(self, oracle, oracle_path, contract):
        spec = oracle["geography"]
        path = Path(spec["records_path"])
        if path.is_symlink() or not path.resolve().is_relative_to(Path(oracle_path).resolve().parent):
            raise ValueError("Geographic oracle must remain beside its pinned oracle metadata")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != spec["records_sha256"]:
                raise ValueError("Independent coordinate oracle bytes changed")
        self.temp = tempfile.TemporaryDirectory(prefix="arsia-readonly-oracle-")
        self.db = sqlite3.connect(Path(self.temp.name) / "geo.sqlite")
        self.db.execute("CREATE TABLE expected(key TEXT PRIMARY KEY,payload TEXT NOT NULL,seen INTEGER DEFAULT 0)")
        count = 0
        with path.open() as stream:
            for line in stream:
                value = json.loads(line)
                self.db.execute("INSERT INTO expected(key,payload) VALUES(?,?)", (stable(value["key"]), stable(value)))
                count += 1
        self.db.commit()
        if count != spec["record_count"]:
            self.close()
            raise ValueError("Coordinate oracle row count changed")
        self.mapped = any(r["grain"] == "crash" and all(r.get("mapping", {}).get("geography", {}).get(k)
                          for k in ("x_field", "y_field", "crs")) for r in contract["resources"])
        self.tolerance = spec["tolerance_degrees"]
        if self.tolerance != 1e-7:
            self.close()
            raise ValueError("Acceptance permits only the documented 1e-7-degree transform tolerance")
        self.expected_counts = spec["status_counts"]
        self.actual_counts, self.errors = Counter(), Counter()
        self.max_error = 0.0

    def inspect(self, key, row):
        encoded = stable(key)
        saved = self.db.execute("SELECT payload,seen FROM expected WHERE key=?", (encoded,)).fetchone()
        if saved is None:
            self.errors["unexpected_key"] += 1
            return
        expected = json.loads(saved[0])
        self.errors["duplicate_key"] += bool(saved[1])
        self.db.execute("UPDATE expected SET seen=seen+1 WHERE key=?", (encoded,))
        status = row.get("geography_status")
        self.actual_counts[status or "missing"] += 1
        point = row.get("coordinates")
        if not self.mapped:
            self.errors["unsupported_has_coordinates"] += point is not None
            self.errors["unsupported_status_mismatch"] += status != "unsupported"
            return
        self.errors["status_mismatch"] += status != expected["status"]
        if expected["status"] == "available":
            if not isinstance(point, list) or len(point) != 2 or any(type(v) not in {int, float} or not math.isfinite(v) for v in point):
                self.errors["invalid_coordinate_pair"] += 1
            else:
                error = max(abs(point[i] - expected["coordinates"][i]) for i in (0, 1))
                self.max_error = max(self.max_error, error)
                self.errors["coordinate_difference_exceeds_tolerance"] += error > self.tolerance
            self.errors["coordinate_crs_mismatch"] += row.get("coordinate_crs") != "EPSG:4326"
        else:
            self.errors["missing_source_has_coordinates"] += point is not None

    def result(self):
        missing = self.db.execute("SELECT count(*) FROM expected WHERE seen=0").fetchone()[0]
        return {"status": "verified" if self.mapped else "not_verified",
                "reason": "Independent source-coordinate comparison" if self.mapped else "No admitted geographic mapping; crash/count acceptance does not certify a map.",
                "coordinate_tolerance_degrees": self.tolerance, "max_observed_difference_degrees": self.max_error,
                "actual_status_counts": dict(self.actual_counts), "expected_status_counts": self.expected_counts if self.mapped else {"unsupported": sum(self.expected_counts.values())},
                "errors": {**dict(self.errors), "missing_keys": missing}}

    def close(self):
        self.db.close()
        self.temp.cleanup()


def database_measurements(conn, batch_id, source_id, contract, geography=None):
    """Independent streamed SQL projection; does not call production QA/query."""
    roles = {r["role"]: r for r in contract["resources"]}
    output = {"grains": {}, "severity": Counter(), "unit_type": Counter(), "availability": {}, "structural": Counter(),
              "fatal_flags": Counter({"true": 0, "false": 0, "unknown": 0}), "fatal_flags_by_raw_severity": {}}
    first_date = last_date = None
    periods = {"yearly": {}, "monthly": {}}
    # Track integer sums plus unknown counts, never materialize crash/person rows.
    def aggregate(target, row):
        if not target:
            target.update({"rows": 0, **{key: 0 for key in METRICS[1:]}, **{key + "_unknown": 0 for key in METRICS[1:]}})
        target["rows"] += 1
        for metric, value in (("fatal_crash_count", row.get("is_fatal_crash")), ("fatalities", row.get("fatalities")), ("casualties", row.get("casualties"))):
            if value is None:
                target[metric + "_unknown"] += 1
            else:
                target[metric] += int(value)
    summary = {}
    for grain, table in TABLES.items():
        keys, facts, canonical_ids, locators = HashBag(), HashBag(), HashBag(), HashBag()
        fields = set()
        sql = """SELECT payload->'raw_key' AS raw_key,payload->>'canonical_id' AS canonical_id,
            payload->>'source_id' AS source_id,payload->>'resource_role' AS resource_role,
            payload->>'row_locator' AS row_locator,payload->>'occurrence_date' AS occurrence_date,
            payload->>'date_precision' AS date_precision,payload->'raw_severity' AS raw_severity,
            payload->'is_fatal_crash' AS is_fatal_crash,payload->'fatalities' AS fatalities,
            payload->'casualties' AS casualties,payload->'declared_units' AS declared_units,
            payload->'declared_casualties' AS declared_casualties,payload->'unit_type' AS unit_type,
            payload->'count_eligible' AS count_eligible,payload->'raw_injury' AS raw_injury,
            payload->'is_fatal' AS is_fatal,payload->'relations' AS relations,
            payload->'availability' AS availability,payload->'year' AS year,payload->'month' AS month,
            payload->'coordinates' AS coordinates,payload->>'geography_status' AS geography_status,
            payload->>'coordinate_crs' AS coordinate_crs
            FROM """ + table + " WHERE batch_id=%s"
        with conn.cursor(name="independent_" + grain) as cursor:
            cursor.itersize = 1000
            cursor.execute(sql, (batch_id,))
            for row in cursor:
                resource = roles[row["resource_role"]]
                output["structural"]["wrong_source"] += row["source_id"] != source_id
                output["structural"]["wrong_grain"] += resource["grain"] != grain
                output["structural"]["empty_locator"] += not bool(row["row_locator"])
                output["structural"]["empty_key_component"] += any(v in (None, "") for v in row["raw_key"])
                row["relations"] = row["relations"] or {}
                key, fact = _fact(grain, row, resource, roles)
                fields.update(key)
                keys.add(key); facts.add(fact); canonical_ids.add(row["canonical_id"])
                locators.add([row["resource_role"], row["row_locator"]])
                if grain == "crash":
                    day = row["occurrence_date"]
                    first_date = min(first_date, day) if first_date else day
                    last_date = max(last_date, day) if last_date else day
                    flag = "unknown" if row["is_fatal_crash"] is None else "true" if row["is_fatal_crash"] is True else "false"
                    output["fatal_flags"][flag] += 1
                    output["fatal_flags_by_raw_severity"].setdefault(row["raw_severity"], Counter())[flag] += 1
                    if geography:
                        geography.inspect(key, row)
                    aggregate(summary, row)
                    aggregate(periods["yearly"].setdefault(f"{row['year']:04d}", {}), row)
                    month = row["month"]
                    if month is not None:
                        aggregate(periods["monthly"].setdefault(f"{row['year']:04d}-{month:02d}", {}), row)
                    output["severity"][row["raw_severity"]] += 1
                    for metric in ("fatalities", "casualties"):
                        status = (row["availability"] or {}).get(metric, {}).get("status", "missing")
                        output["availability"].setdefault(metric, Counter())[status] += 1
                elif grain == "unit":
                    output["unit_type"][row["unit_type"]] += 1
        output["grains"][grain] = {"key_fields": sorted(fields), "keys": keys.result(), "facts": facts.result()}
        for label, bag in (("canonical_id", canonical_ids), ("locator", locators)):
            stats = bag.result()
            output["structural"][grain + ".duplicate_" + label] = stats["rows"] - stats["distinct"]
    def finish(value):
        return {"crash_count": value.get("rows", 0), **{k: None if value.get(k + "_unknown") else value.get(k, 0) for k in METRICS[1:]}}
    output["summary"] = finish(summary)
    output["observed_date_range"] = [first_date, last_date]
    if geography:
        output["geography"] = geography.result()
    for period in ("yearly", "monthly"):
        output[period] = {key: finish(value) for key, value in periods[period].items()}
    union = " UNION ALL ".join("SELECT payload FROM " + table + " WHERE batch_id=%s" for table in TABLES.values())
    output["structural"]["orphan_relations"] = conn.execute("""WITH rows AS (""" + union + """), links AS (
        SELECT link.key AS role,link.value AS parent_key FROM rows
        CROSS JOIN LATERAL jsonb_each_text(coalesce(payload->'relations','{}')) link)
        SELECT count(*) AS n FROM links WHERE parent_key IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM rows WHERE payload->>'resource_role'=links.role AND payload->>'record_id'=links.parent_key)""", (batch_id,) * 4).fetchone()["n"]
    return json.loads(json.dumps(output))


def compare_database(checks, actual, oracle):
    compare_metrics(checks, "database.summary", actual["summary"], oracle["summary"])
    for period in ("yearly", "monthly"):
        checks.equal("database." + period + ".periods", sorted(actual[period]), sorted(oracle[period]))
        for key, wanted in oracle[period].items():
            compare_metrics(checks, "database." + period + "." + key, actual[period].get(key, {}), wanted)
    checks.equal("database.raw_severity", actual["severity"], oracle["severity"])
    checks.equal("database.unit_type", actual["unit_type"], oracle["unit_type"])
    if oracle.get("oracle_version", 2) >= 3:
        checks.equal("database.observed_date_range", actual["observed_date_range"], oracle["date_range"])
        checks.equal("database.fatal_flags", actual["fatal_flags"], oracle["fatal_flags"])
        checks.equal("database.fatal_flags_by_raw_severity", actual["fatal_flags_by_raw_severity"], oracle["fatal_flags_by_raw_severity"])
        geo = actual["geography"]
        checks.equal("database.geography.status_counts", geo["actual_status_counts"], geo["expected_status_counts"])
        for name, count in geo["errors"].items():
            checks.equal("database.geography." + name, count, 0)
    for grain, wanted in oracle["grains"].items():
        observed = actual["grains"][grain]
        checks.equal("database." + grain + ".key_fields", observed["key_fields"], wanted["key_fields"])
        for kind in ("keys", "facts"):
            for metric in ("rows", "distinct", "sha256"):
                checks.equal(f"database.{grain}.{kind}.{metric}", observed[kind][metric], wanted[kind][metric])
    for key, value in actual["structural"].items():
        checks.equal("database.structural." + key, value, 0)
    for metric in ("fatalities", "casualties"):
        status = "available" if oracle["availability"][metric] else "unsupported"
        checks.equal("database.availability." + metric, actual["availability"].get(metric), {status: oracle["summary"]["crash_count"]})


def normalized_contract_hash(contract):
    value = json.loads(json.dumps(contract))
    value.pop("documents", None)
    for resource in value.get("resources", []):
        resource.pop("file_id", None)
    return hashlib.sha256(stable(value).encode()).hexdigest()


def verify_blocked(conn, job, oracle, checks, before_release_id=None):
    checks.equal("blocked.terminal_status", job["status"] in {"needs_input", "failed"}, True)
    checks.equal("blocked.batch_id", job.get("batch_id"), None)
    checks.equal("blocked.release_id", job.get("release_id"), None)
    checks.equal("blocked.published_result", job.get("result"), None)
    batches = conn.execute("SELECT count(*) AS n FROM batches WHERE job_id=%s", (job["id"],)).fetchone()["n"]
    checks.equal("blocked.new_batches", batches, 0)
    session = conn.execute("SELECT id,checkpoint FROM agent_sessions WHERE job_id=%s", (job["id"],)).fetchone()
    first = conn.execute("SELECT min(started_at) AS started FROM attempts WHERE job_id=%s", (job["id"],)).fetchone()["started"] or job["created_at"]
    if before_release_id:
        before = conn.execute("SELECT id,sources,created_at FROM releases WHERE id=%s", (before_release_id,)).fetchone()
        if not before:
            raise ValueError("The supplied baseline immutable release does not exist")
        if before and before["created_at"] > first:
            raise ValueError("The supplied baseline release was created after this job started")
    else:
        before = conn.execute("SELECT id,sources FROM releases WHERE created_at<=%s ORDER BY created_at DESC LIMIT 1", (first,)).fetchone()
    current = conn.execute("SELECT r.id,r.sources FROM current_release c JOIN releases r ON r.id=c.release_id").fetchone()
    checks.equal("blocked.current_release", str(current["id"]) if current else None, str(before["id"]) if before else None)
    checks.equal("blocked.retained_source_map", current["sources"] if current else {}, before["sources"] if before else {})
    registrations = []
    steps = []
    if session:
        steps = conn.execute("SELECT name,status,arguments,result FROM agent_steps WHERE session_id=%s AND name IN ('set_source_contract','register_adapter','publish_candidate','validate_candidate')", (session["id"],)).fetchall()
        contracts = [s["arguments"]["contract"] for s in steps if s["name"] == "set_source_contract" and isinstance(s["arguments"].get("contract"), dict)]
        if session["checkpoint"].get("contract"):
            contracts.append(session["checkpoint"]["contract"])
        hashes = list({normalized_contract_hash(contract) for contract in contracts})
        if hashes:
            registrations = conn.execute("""SELECT a.id,a.created_at FROM adapter_versions a JOIN source_versions s ON s.id=a.source_version_id
                WHERE s.contract_sha256=ANY(%s) AND a.created_at BETWEEN %s AND %s""", (hashes, first, job["updated_at"])).fetchall()
    successful_registration = sum(s["name"] == "register_adapter" and s["status"] == "succeeded" and bool((s["result"] or {}).get("adapter_version_id")) for s in steps)
    successful_request = sum(s["name"] == "publish_candidate" and s["status"] == "succeeded" for s in steps)
    admitted = sum(s["name"] == "validate_candidate" and (s["result"] or {}).get("status") == "validated" for s in steps)
    checks.equal("blocked.registered_candidates_created", len(registrations), 0)
    checks.equal("blocked.successful_registration_steps", successful_registration, 0)
    checks.equal("blocked.accepted_publication_requests", successful_request, 0)
    checks.equal("blocked.admitted_full_candidates", admitted, 0)
    return {"baseline_release_id": str(before["id"]) if before else None, "current_release_id": str(current["id"]) if current else None,
            "candidate_registered": bool(registrations or successful_registration), "candidate_published": bool(batches or job.get("batch_id")),
            "verified_scope": "Publication isolation only; a block does not establish that source semantics or data-anomaly diagnostics passed.",
            "observed_terminal_status": job["status"],
            "oracle_anomalies": oracle.get("anomalies", []), "registration_scope": "This job's proposed contracts and successful durable steps; pre-existing unrelated adapters are not counted."}


def verify(args):
    from arsia_pipeline import store
    oracle_path = args.oracle or PROJECT / "artifacts/autonomous-imports/source-downloads" / args.state / "independent-oracle-v3.json"
    oracle_bytes = oracle_path.read_bytes()
    oracle = json.loads(oracle_bytes)
    if oracle.get("oracle_version") not in {2, 3} or oracle.get("state") != args.state:
        raise ValueError("Use an independent complete v2/v3 oracle for the requested state")
    checks = Checks()
    api = GetOnlyAPI(args.via_website)
    api_job = api.get("/jobs/" + str(args.job_id))
    expected_mode = args.expect or ("blocked" if args.state == "tas" else "published")
    with store.connect() as conn, conn.transaction():
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        job = conn.execute("SELECT * FROM jobs WHERE id=%s", (args.job_id,)).fetchone()
        if not job:
            raise ValueError("Job does not exist in this isolated database")
        checks.equal("job.api_database_status", api_job["status"], job["status"])
        uploaded = [f["sha256"] for f in job["files"]]
        checks.equal("job.official_input_hash_present", oracle["input_upload_sha256"] in uploaded, True)
        details = {}
        if expected_mode == "blocked":
            details = verify_blocked(conn, job, oracle, checks, args.before_release_id)
        else:
            checks.equal("job.published_status", job["status"] in {"succeeded", "no_change"}, True)
            if job["status"] in {"succeeded", "no_change"}:
                batch = conn.execute("SELECT * FROM batches WHERE id=%s", (job["batch_id"],)).fetchone()
                release = conn.execute("SELECT id,sources,created_at FROM releases WHERE id=%s", (job["release_id"],)).fetchone()
                if not batch or not release:
                    raise ValueError("Published job points to a missing immutable batch or release")
                checks.equal("release.source_batch", release["sources"].get(job["source_id"]), str(job["batch_id"]))
                result = job["result"]
                contract = result["source_contract"]
                jurisdictions = contract["source"]["jurisdiction"]
                checks.equal("source.jurisdiction", sorted([jurisdictions] if isinstance(jurisdictions, str) else jurisdictions), [args.state.upper()])
                checks.equal("admission.full", result.get("admission", {}).get("status"), "admitted")
                checks.equal("admission.no_block", any(q.get("status") == "block" for q in result.get("qa", [])), False)
                checks.equal("registry.adapter_reference", bool(batch["adapter_version_id"]), True)
                checks.equal("registry.source_reference", bool(batch["source_version_id"]), True)
                compare_report(checks, "job", result, oracle, contract)
                compare_report(checks, "batch", batch["result"], oracle, contract)
                geo = GeographyVerifier(oracle, oracle_path, contract) if oracle["oracle_version"] >= 3 else None
                try:
                    measurements = database_measurements(conn, job["batch_id"], job["source_id"], contract, geo)
                    compare_database(checks, measurements, oracle)
                finally:
                    if geo:
                        geo.close()
                previous = conn.execute("SELECT id,sources FROM releases WHERE created_at<%s ORDER BY created_at DESC LIMIT 1", (release["created_at"],)).fetchone()
                if previous and job["status"] == "succeeded":
                    for source, batch_id in previous["sources"].items():
                        if source != job["source_id"]:
                            checks.equal("retained." + source, release["sources"].get(source), batch_id)
                details = {"release_id": str(job["release_id"]), "batch_id": str(job["batch_id"]), "source_id": job["source_id"],
                           "adapter_version_id": batch["adapter_version_id"], "source_version_id": batch["source_version_id"],
                           "geography_verification": measurements.get("geography", {"status": "not_verified", "reason": "v2 oracle does not verify geography"}),
                           "observed_date_range": measurements["observed_date_range"],
                           "declared_coverage": contract["source"]["coverage"]}
    if expected_mode == "published" and details.get("release_id"):
        first, last = oracle["date_range"]
        start = first[:7] + "-01"
        end = last[:7] + f"-{calendar.monthrange(int(last[:4]), int(last[5:7]))[1]:02d}"
        query = api.get("/query?" + urlencode({"source_id": details["source_id"], "release_id": details["release_id"], "from": start, "to": end}))
        checks.equal("query.release_pinned", query["release_id"], details["release_id"])
        compare_report(checks, "query", query, oracle, contract, True)
    result = checks.report()
    return {"status": "passed" if result["failed"] == 0 else "failed", "read_only": True, "state": args.state, "expected_outcome": expected_mode,
            "job_id": str(args.job_id), "checked_at": datetime.now(timezone.utc).isoformat(), "oracle_path": str(oracle_path),
            "oracle_sha256": hashlib.sha256(oracle_bytes).hexdigest(), "oracle_is_model_evidence": False, **details, **result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", choices=("act", "sa", "tas"), required=True)
    parser.add_argument("--job-id", type=UUID, required=True)
    parser.add_argument("--expect", choices=("published", "blocked"))
    parser.add_argument("--before-release-id", type=UUID, help="Explicit pre-attempt release for blocked-isolation checks")
    parser.add_argument("--oracle", type=Path)
    parser.add_argument("--via-website", action="store_true", help="GET through existing port 3100 instead of the private Unix socket")
    parser.add_argument("--output", type=Path, help="Write the aggregate acceptance report; no application data is changed")
    args = parser.parse_args()
    try:
        report = verify(args)
    except Exception as exc:
        report = {"status": "error", "read_only": True, "error_type": type(exc).__name__, "message": str(exc), "job_id": str(args.job_id)}
    encoded = json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    print(encoded, end="")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
