"""QA01 and QA02 evidence from archived files and the caller's Raw transaction."""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from uuid import UUID

from .manifest import validate_manifest
from .models import IntakeError, ParseStats, ResourceSpec
from .readers import iter_native_rows
from .vic_restricted import PROTOCOL, check_profile_evidence, input_expectations


RULE_INPUT = "QA01_INPUT"
RULE_RAW = "QA02_RAW"


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True)


def _now():
    return datetime.now(timezone.utc).isoformat()


def _directory(path):
    path = Path(path)
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise IntakeError("QA_EVIDENCE", "Evidence paths must not contain symlinks")
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_evidence(path, value):
    """Create one JSON evidence file without replacing an earlier result."""
    path = Path(path)
    _directory(path.parent)
    data = (_json(value) + "\n").encode("utf-8")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "row_count": 1}


class _Details:
    def __init__(self, path):
        self.path = Path(path)
        _directory(self.path.parent)
        self.stream = self.path.open("xb")
        self.digest = hashlib.sha256()
        self.count = 0

    def add(self, value):
        encoded = (_json(value) + "\n").encode("utf-8")
        self.stream.write(encoded)
        self.digest.update(encoded)
        self.count += 1

    def close(self):
        if not self.stream.closed:
            self.stream.flush()
            os.fsync(self.stream.fileno())
            self.stream.close()
        return {"path": str(self.path), "sha256": self.digest.hexdigest(), "row_count": self.count}


@dataclass(frozen=True)
class QAReport:
    rows: tuple[dict, ...]

    @property
    def blocked(self):
        return any(row["result"] == "block" for row in self.rows)

    def as_dict(self):
        return {"rows": deepcopy(list(self.rows))}


def _manifest(value, *, drafts=False):
    if not isinstance(value, dict):
        raise IntakeError("QA_MANIFEST", "Supply a manifest object")
    candidate = deepcopy(value)
    if drafts:
        for contract in candidate.get("rules", {}).get("contracts", []):
            if contract.get("status") == "draft":
                status = "confirmed" if candidate.get("dataset_kind") == "official" else "synthetic_defined"
                contract["status"] = status
                contract.get("content", {}).get("confirmation", {})["status"] = status
    validate_manifest(candidate)
    return deepcopy(value)


def _spec(file, root):
    digest = file["file_sha256"]
    kind = "official" if file["source_id"].startswith("official_") else "synthetic"
    root = Path(root).resolve()
    path = root / kind / "archive/sha256" / digest[:2] / digest
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.resolve().is_relative_to(root):
        raise IntakeError("QA_ARCHIVE", "Archive must stay within its input tree")
    spec = ResourceSpec(**{key: file[key] for key in (
        "source_id", "resource_id", "resource_role", "entity_kind", "format", "encoding", "sheet", "header_row"
    )}, path=path, header=tuple(file["header"]), expected_sha256=digest)
    if file["parser_version"] != spec.parser_version or file["locator_version"] != spec.locator_version:
        raise IntakeError("QA_PARSER", "The declared parser/locator version is not available")
    return spec


def _hash(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _native(file, root):
    spec = _spec(file, root)
    if _hash(spec.path) != file["file_sha256"]:
        raise IntakeError("QA_HASH", "Archived bytes differ from the frozen file hash")
    return spec


def _reference(file, **extra):
    return {"resource_id": file["resource_id"], "file_sha256": file["file_sha256"], "row_locator": None, **extra}


def _row(rule, file, *, metrics, expected, evaluated, expected_count, affected, reasons, reference, producer):
    return {
        "rule_id": rule, "object_key": f'file:{file["resource_id"]}:{file["file_sha256"]}:{file["parser_version"]}',
        "result": "block" if reasons else "pass", "affected_count": affected,
        "actual": {"evaluated_count": evaluated, "violation_count": affected, "metrics": metrics},
        "expected": {"evaluated_count": expected_count, "violation_count": 0, "metrics": expected},
        "evidence": {"reason_codes": sorted(set(reasons)), "resolution": "Resolve the recorded differences before publication." if reasons else "Checked against archived native input.",
                     "references": [_reference(file, detail=reference)], "producer_version": producer},
        "raw_record_id": None, "checked_at": _now(),
    }


def _report(rule, rows, producer):
    count = len(rows)
    blocks = sum(r["result"] == "block" for r in rows)
    metrics = {"object_count": count, "pass_count": count - blocks, "limited_count": 0, "block_count": blocks, "missing_count": 0}
    summary = {
        "rule_id": rule, "object_key": "batch", "result": "block" if blocks else "pass",
        "affected_count": sum(r["affected_count"] for r in rows),
        "actual": {"evaluated_count": count, "violation_count": blocks, "metrics": metrics},
        "expected": {"evaluated_count": count, "violation_count": 0, "metrics": {**metrics, "pass_count": count, "block_count": 0}},
        "evidence": {"reason_codes": ["FILE_CHECK_BLOCKED"] if blocks else [],
                     "resolution": "See each file result." if rows else "The required file set is empty.",
                     "references": [ref for row in rows for ref in row["evidence"]["references"]], "producer_version": producer},
        "raw_record_id": None, "checked_at": _now(),
    }
    return QAReport(tuple([*rows, summary]))


def _keys(contract):
    key = contract["content"]["identity"]["key"]
    fields = key.get("fields") if isinstance(key, dict) else key
    if not isinstance(fields, list) or not fields or any(not isinstance(f, str) for f in fields):
        raise IntakeError("QA_HISTORY_KEY", "Native key fields need an explicit ordered list")
    if len(set(fields)) != len(fields) or not set(fields) <= set(contract["content"]["input"]["header"]):
        raise IntakeError("QA_HISTORY_KEY", "Native key fields do not match the source header")
    return fields


def _key(row, fields):
    return _json([row.payload[f] for f in fields])


def _temporal_coverage(value):
    required = {"year_from", "year_to", "months"}
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - (required | {"basis"}):
        return False
    if (type(value["year_from"]) is not int or type(value["year_to"]) is not int
            or not 1 <= value["year_from"] <= value["year_to"] <= 9999):
        return False
    months = value["months"]
    return (isinstance(months, list) and bool(months)
            and all(type(month) is int and 1 <= month <= 12 for month in months)
            and len(months) == len(set(months))
            and ("basis" not in value or isinstance(value["basis"], str) and bool(value["basis"].strip())))


def _explanation(contract, previous_contract, key=None, *, coverage=False):
    change = contract["content"]["snapshot"]["change"]
    if not isinstance(change, dict) or not isinstance(change.get("description"), str) or not change["description"].strip():
        return False
    file = contract["content"]["input"]
    if (change.get("source_id") != file["source_id"]
            or change.get("previous_release_label") != previous_contract["content"]["identity"]["release_label"]
            or change.get("resource_id", file["resource_id"]) != file["resource_id"]):
        return False
    if coverage:
        declared = change.get("coverage")
        before = previous_contract["content"]["identity"]["coverage"]
        after = contract["content"]["identity"]["coverage"]
        return (change.get("kind") in {"coverage_reduction", "replacement"}
                and isinstance(declared, dict) and set(declared) == {"before", "after"}
                and _temporal_coverage(before) and _temporal_coverage(after)
                and _json(declared["before"]) == _json(before)
                and _json(declared["after"]) == _json(after))
    if change.get("kind") not in {"deletion", "replacement"}:
        return False
    keys = change.get("native_keys", [change.get("native_key")])
    return isinstance(keys, list) and json.loads(key) in keys


def _history(db, file, contract, previous, root, details, reasons):
    rid = file["resource_id"]
    old_files = {f["resource_id"]: f for f in previous["files"]}
    if rid not in old_files:
        return
    old = old_files[rid]
    old_contract = next(c for c in previous["rules"]["contracts"] if c["id"] == rid)
    if old["source_id"] != file["source_id"] or _keys(old_contract) != _keys(contract):
        raise IntakeError("QA_HISTORY_KEY", "Historical key/source definition changed; review the comparison")
    spec = _native(old, root)
    stats = ParseStats()
    fields = _keys(old_contract)
    with closing(iter_native_rows(spec.path, spec, stats)) as rows:
        for native in rows:
            key = _key(native, fields)
            found = db.execute("SELECT n FROM native_keys WHERE key = ?", (key,)).fetchone()
            if found is not None and found[0] > 0:
                db.execute("UPDATE native_keys SET n=n-1 WHERE key=?", (key,))
            elif not _explanation(contract, old_contract, key):
                reasons.add("SNAPSHOT_DELETION_UNEXPLAINED")
                details.add(_reference(old, row_locator=native.row_locator, reason_code="SNAPSHOT_DELETION_UNEXPLAINED", native_key=json.loads(key)))
    if stats.raw_count != old["raw_count"] or _hash(spec.path) != old["file_sha256"]:
        raise IntakeError("QA_HISTORY", "Historical native snapshot differs from its manifest")
    before = old_contract["content"]["identity"]["coverage"]
    after = contract["content"]["identity"]["coverage"]
    if _json(before) != _json(after):
        # A temporal expansion cannot explain changed coverage in another dimension.
        expands = (_temporal_coverage(before) and _temporal_coverage(after)
                   and after["year_from"] <= before["year_from"] <= before["year_to"] <= after["year_to"]
                   and set(before["months"]) <= set(after["months"])
                   and _json(before.get("basis")) == _json(after.get("basis")))
        if not expands and not _explanation(contract, old_contract, coverage=True):
            reasons.add("COVERAGE_CHANGE_UNEXPLAINED")
            change = contract["content"]["snapshot"]["change"]
            declared = change.get("coverage") if isinstance(change, dict) else None
            details.add({"reason_code": "COVERAGE_CHANGE_UNEXPLAINED", "actual": after,
                         "expected": before, "declared": declared})


def check_inputs(manifest, archive_root, *, previous_manifest=None, evidence_dir, producer_version,
                 supported_mappings=(), official_reviews=(), policy_evidence_root=None):
    """Check files and supplied source reviews; None means no previous publication."""
    value = _manifest(manifest, drafts=True)
    previous = _manifest(previous_manifest) if previous_manifest is not None else None
    if previous is not None and previous["dataset_kind"] != value["dataset_kind"]:
        raise IntakeError("QA_NAMESPACE", "Previous publication belongs to another dataset kind")
    if not isinstance(producer_version, str) or not producer_version.strip():
        raise IntakeError("QA_VERSION", "An explicit QA producer version is required")
    supported_mappings = tuple(supported_mappings)
    supported = {item["id"]: item for item in supported_mappings}
    if len(supported) != len(supported_mappings):
        raise IntakeError("QA_MAPPING", "Duplicate supported mapping IDs")
    mappings = {m["id"]: m for m in value["rules"]["mappings"]}
    contracts = {c["id"]: c for c in value["rules"]["contracts"]}
    official_reviews = tuple(official_reviews)
    reviews = {r["resource_id"]: r for r in official_reviews}
    if len(reviews) != len(official_reviews):
        raise IntakeError("QA_REVIEW", "Duplicate source review records")
    result = []
    removed_resources = set() if previous is None else {f["resource_id"] for f in previous["files"]} - {f["resource_id"] for f in value["files"]}
    for file in value["files"]:
        contract = contracts[file["resource_id"]]
        reasons = set()
        metrics = {"hash_match": None, "header_match": None, "bundle_confirmed": None, "contract_confirmed": None}
        details = _Details(Path(evidence_dir) / f'{RULE_INPUT}-{file["resource_id"]}.jsonl')
        evaluated = 0
        expected = {key: True for key in metrics}
        try:
            restricted = (value["rules"]["qa_contract"]["version"] == PROTOCOL
                          and file["source_id"] == "official_vic")
            if restricted:
                expected = input_expectations()
                metrics.update({key: None for key in expected})
                # Manifest validation has bound the exact files, scope and adopted decision.
                metrics.update(bundle_confirmed=False, contract_confirmed=False,
                               profile_approved=True, selected_identity_match=True,
                               profile_scope_match=True)
                try:
                    binding = check_profile_evidence(policy_evidence_root)
                except IntakeError:
                    metrics["case_register_match"] = False
                    raise
                metrics["case_register_match"] = True
                details.add({"restricted_profile": binding})
                if reviews.get(file["resource_id"]):
                    reasons.add("RESTRICTED_REVIEW_CONFLICT")
                    details.add({"reason_code": "RESTRICTED_REVIEW_CONFLICT",
                                 "message": "Use the adopted profile; do not attach unrestricted source approval."})
            else:
                expected_status = "confirmed" if value["dataset_kind"] == "official" else "synthetic_defined"
                confirmation = contract["content"]["confirmation"]
                confirmed = contract["status"] == confirmation.get("status") == expected_status
                if value["dataset_kind"] == "official":
                    confirmed = confirmed and not confirmation.get("unresolved")
                    review = reviews.get(file["resource_id"], {})
                    identity = contract["content"]["identity"]
                    supported_review = (
                        review.get("contract_version") == contract["version"]
                        and review.get("file_sha256") == file["file_sha256"]
                        and all(review.get(k) == identity[k] for k in ("release_label", "release_scope"))
                        and review.get("status") == "confirmed" and review.get("bundle_confirmed") is True
                        and isinstance(review.get("reviewed_by"), str) and bool(review["reviewed_by"].strip())
                        and isinstance(review.get("references"), list) and bool(review["references"])
                        and review.get("unresolved") == []
                    )
                    confirmed = confirmed and supported_review
                    details.add({"source_review": review or None})
                metrics["contract_confirmed"] = bool(confirmed)
                if not confirmed:
                    reasons.add("CONTRACT_UNCONFIRMED")
                metrics["bundle_confirmed"] = bool(confirmed and contract["content"]["identity"].get("bundle_basis"))
                if not metrics["bundle_confirmed"]:
                    reasons.add("BUNDLE_UNCONFIRMED")
            for mid in contract["mapping_ids"]:
                if supported.get(mid) != mappings[mid]:
                    reasons.add("MAPPING_UNSUPPORTED")
                    details.add({"reason_code": "MAPPING_UNSUPPORTED", "mapping_id": mid, "version": mappings[mid]["version"]})
            if removed_resources:
                reasons.add("RESOURCE_REMOVAL_UNREVIEWED")
                details.add({"reason_code": "RESOURCE_REMOVAL_UNREVIEWED", "resources": sorted(removed_resources)})
            spec = _spec(file, archive_root)
            metrics["hash_match"] = _hash(spec.path) == file["file_sha256"]
            if not metrics["hash_match"]:
                raise IntakeError("QA_HASH", "Archived bytes differ from the frozen file hash")
            stats = ParseStats()
            with tempfile.TemporaryDirectory(prefix="arsia-qa-history-") as directory, closing(sqlite3.connect(str(Path(directory) / "keys.sqlite"))) as db:
                db.execute("CREATE TABLE native_keys (key TEXT PRIMARY KEY, n INTEGER NOT NULL)")
                fields = _keys(contract)
                with closing(iter_native_rows(spec.path, spec, stats)) as rows:
                    for native in rows:
                        key = _key(native, fields)
                        db.execute("INSERT INTO native_keys VALUES (?, 1) ON CONFLICT(key) DO UPDATE SET n=n+1", (key,))
                metrics["header_match"] = stats.header == file["header"]
                evaluated = 1
                details.add({"native_count": stats.raw_count, "expected_count": file["raw_count"],
                             "observed_header": stats.header, "parser_version": file["parser_version"],
                             "locator_version": file["locator_version"]})
                if not metrics["header_match"]:
                    reasons.add("HEADER_MISMATCH")
                if stats.raw_count != file["raw_count"]:
                    reasons.add("NATIVE_COUNT_MISMATCH")
                    details.add({"reason_code": "NATIVE_COUNT_MISMATCH", "actual": stats.raw_count, "expected": file["raw_count"]})
                if _hash(spec.path) != file["file_sha256"]:
                    metrics["hash_match"] = False
                    raise IntakeError("QA_HASH", "Archived bytes changed during the check")
                if previous is not None:
                    _history(db, file, contract, previous, archive_root, details, reasons)
        except (IntakeError, OSError, ValueError, KeyError) as exc:
            code = exc.code if isinstance(exc, IntakeError) else "INPUT_CHECK_UNAVAILABLE"
            reasons.add(code)
            if code == "HEADER_MISMATCH":
                metrics["header_match"] = False
            details.add({"reason_code": code, "message": str(exc), "details": getattr(exc, "details", {})})
        finally:
            details.add({"metrics": metrics, "evaluated_count": evaluated, "reason_codes": sorted(set(reasons))})
            reference = details.close()
        result.append(_row(RULE_INPUT, file, metrics=metrics, expected=expected, evaluated=evaluated,
                           expected_count=1, affected=int(bool(reasons)), reasons=reasons, reference=reference, producer=producer_version))
    return _report(RULE_INPUT, result, producer_version)


def _connection(connection):
    if getattr(connection, "autocommit", None) is not False:
        raise IntakeError("QA_AUTOCOMMIT", "QA requires the caller's transaction with autocommit disabled")


def check_raw(connection, manifest, archive_root, *, evidence_dir, producer_version):
    """Compare archived records to Raw, using a temporary disk index and UUID pages."""
    _connection(connection)
    value = _manifest(manifest)
    if not isinstance(producer_version, str) or not producer_version.strip():
        raise IntakeError("QA_VERSION", "An explicit QA producer version is required")
    result = []
    for file in value["files"]:
        metrics = {"raw_count": None, "distinct_locator_count": None, "payload_mismatch_count": None}
        reasons = set()
        affected = evaluated = 0
        details = _Details(Path(evidence_dir) / f'{RULE_RAW}-{file["resource_id"]}.jsonl')
        try:
            spec = _native(file, archive_root)
            stats = ParseStats()
            with tempfile.TemporaryDirectory(prefix="arsia-qa-raw-") as directory, closing(sqlite3.connect(str(Path(directory) / "records.sqlite"))) as db:
                db.execute("CREATE TABLE native (locator TEXT PRIMARY KEY, payload TEXT NOT NULL, seen INTEGER DEFAULT 0)")
                db.execute("CREATE TABLE observed (locator TEXT PRIMARY KEY)")
                with closing(iter_native_rows(spec.path, spec, stats)) as rows:
                    for native in rows:
                        db.execute("INSERT INTO native(locator,payload) VALUES (?,?)", (native.row_locator, _json(native.payload)))
                if stats.raw_count != file["raw_count"] or _hash(spec.path) != file["file_sha256"]:
                    raise IntakeError("QA_NATIVE", "Native replay differs from the frozen count or hash")
                raw_count = mismatches = 0
                last_id = None
                with connection.cursor() as cursor:
                    while True:
                        cursor.execute("""SELECT raw_record_id, source_id, resource_id, file_sha256,
                            parser_version, row_locator, payload FROM raw.record
                            WHERE resource_id = %s AND file_sha256 = %s AND parser_version = %s
                              AND (%s::uuid IS NULL OR raw_record_id > %s::uuid)
                            ORDER BY raw_record_id LIMIT 1000""",
                            (file["resource_id"], file["file_sha256"], file["parser_version"], last_id, last_id))
                        page = cursor.fetchmany(1000)
                        if not page:
                            break
                        for record in page:
                            if len(record) != 7:
                                raise IntakeError("QA_RAW_REPLY", "Raw query returned an unexpected row shape")
                            raw_id, source, resource, digest, parser, locator, payload = record
                            current_id = str(UUID(str(raw_id)))
                            if last_id is not None and UUID(current_id).int <= UUID(last_id).int:
                                raise IntakeError("QA_RAW_REPLY", "Raw UUID pages are not strictly increasing")
                            last_id = current_id
                            raw_count += 1
                            locator_key = _json(locator)
                            duplicate = db.execute("SELECT 1 FROM observed WHERE locator=?", (locator_key,)).fetchone() is not None
                            db.execute("INSERT OR IGNORE INTO observed VALUES (?)", (locator_key,))
                            native = db.execute("SELECT payload,seen FROM native WHERE locator=?", (locator,)).fetchone() if isinstance(locator, str) else None
                            payload_valid = isinstance(payload, dict) and set(payload) == set(file["header"]) and all(v is None or isinstance(v, str) for v in payload.values())
                            mismatch = native is not None and (not payload_valid or _json(payload) != native[0])
                            identity_bad = (source, resource, digest, parser) != tuple(file[k] for k in ("source_id", "resource_id", "file_sha256", "parser_version"))
                            row_reasons = []
                            if native is None:
                                row_reasons.append("RAW_EXTRA_LOCATOR")
                            else:
                                if not native[1]:
                                    evaluated += 1
                                db.execute("UPDATE native SET seen=seen+1 WHERE locator=?", (locator,))
                            if duplicate:
                                row_reasons.append("RAW_DUPLICATE_LOCATOR")
                            if mismatch:
                                mismatches += 1
                                row_reasons.append("RAW_PAYLOAD_MISMATCH")
                            if identity_bad:
                                row_reasons.append("RAW_IDENTITY_MISMATCH")
                            if row_reasons:
                                affected += 1
                                reasons.update(row_reasons)
                                details.add(_reference(file, row_locator=locator, raw_record_id=current_id, reason_codes=row_reasons,
                                                       actual={"source_id": source, "resource_id": resource, "file_sha256": digest, "parser_version": parser, "payload": payload},
                                                       expected=None if native is None else json.loads(native[0])))
                        if len(page) < 1000:
                            break
                missing = 0
                for locator, payload in db.execute("SELECT locator,payload FROM native WHERE seen=0"):
                    missing += 1
                    affected += 1
                    details.add(_reference(file, row_locator=locator, reason_code="RAW_MISSING_LOCATOR", expected=json.loads(payload)))
                if missing:
                    reasons.add("RAW_MISSING_LOCATOR")
                metrics = {"raw_count": raw_count, "distinct_locator_count": db.execute("SELECT COUNT(*) FROM observed").fetchone()[0], "payload_mismatch_count": mismatches}
                if raw_count != file["raw_count"]:
                    reasons.add("RAW_COUNT_MISMATCH")
        except Exception as exc:
            code = exc.code if isinstance(exc, IntakeError) else "RAW_CHECK_UNAVAILABLE"
            reasons.add(code)
            affected = max(affected, 1)
            metrics = {key: None for key in metrics}
            details.add({"reason_code": code, "exception_type": type(exc).__name__, "details": getattr(exc, "details", {})})
        finally:
            details.add({"metrics": metrics, "evaluated_count": evaluated, "reason_codes": sorted(set(reasons))})
            reference = details.close()
        expected = {"raw_count": file["raw_count"], "distinct_locator_count": file["raw_count"], "payload_mismatch_count": 0}
        result.append(_row(RULE_RAW, file, metrics=metrics, expected=expected, evaluated=evaluated, expected_count=file["raw_count"],
                           affected=affected, reasons=reasons, reference=reference, producer=producer_version))
    return _report(RULE_RAW, result, producer_version)


def write_results(connection, batch_id, report):
    """Insert checked rows in the build transaction; never update existing QA."""
    _connection(connection)
    batch_id = str(UUID(str(batch_id)))
    if not isinstance(report, QAReport):
        raise IntakeError("QA_REPORT", "Expected a QAReport")
    with connection.cursor() as cursor:
        for row in report.rows:
            cursor.execute("""INSERT INTO qa.check_result
                (batch_id,rule_id,object_key,result,affected_count,actual,expected,evidence,raw_record_id,checked_at)
                VALUES (%s::uuid,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::uuid,%s::timestamptz)""",
                (batch_id, row["rule_id"], row["object_key"], row["result"], row["affected_count"],
                 _json(row["actual"]), _json(row["expected"]), _json(row["evidence"]), row["raw_record_id"], row["checked_at"]))
