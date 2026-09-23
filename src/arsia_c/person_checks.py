"""Person diagnostics on selected Raw snapshots; B owns the transaction."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import re
from uuid import uuid4

from arsia_ingest.manifest import FrozenManifest
from arsia_ingest.models import IntakeError


ROOT = Path(__file__).resolve().parents[2]
SQL_PATH = ROOT / "sql/qa/c06_vic_person_checks.sql"
POLICY_PATH = ROOT / "config/c06-syn-1.json"
VERSION = "c06-person-v0.3"
ROLES = {"accident": "crash", "vehicle": "unit", "person": "person_raw"}
FIELDS = {
    "accident": {"ACCIDENT_NO", "ACCIDENT_DATE", "NO_PERSONS"},
    "vehicle": {"ACCIDENT_NO", "VEHICLE_ID"},
    "person": {"ACCIDENT_NO", "PERSON_ID", "VEHICLE_ID"},
}


def _fail(message, **details):
    raise IntakeError("C06_INPUT", message, **details)


def _selection(files, analysis):
    if (not isinstance(analysis, dict) or set(analysis) != {"year_from", "year_to"}
            or any(type(v) is not int for v in analysis.values())
            or not 1 <= analysis["year_from"] <= analysis["year_to"] <= 9999):
        _fail("C06 needs an inclusive calendar-year interval")
    if not isinstance(files, list) or len(files) != 3:
        _fail("Select one complete Accident, Vehicle and Person snapshot")
    if {f.get("role") for f in files} != set(ROLES):
        _fail("Each C06 input role must occur once")
    if len({f.get("source_id") for f in files}) != 1 or len({f.get("resource_id") for f in files}) != 3:
        _fail("C06 parent and child resources must belong to the same source")
    for file in files:
        for key in ("source_id", "resource_id"):
            if not isinstance(file.get(key), str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", file[key]):
                _fail("Invalid resource or source ID")
        if (not re.fullmatch(r"[0-9a-f]{64}", str(file.get("file_sha256", "")))
                or file.get("parser_version") != "csv-native-v1"
                or file.get("locator_version") != "csv-logical-v1"
                or file.get("format") != "csv"
                or file.get("entity_kind") != ROLES[file["role"]]
                or not FIELDS[file["role"]] <= set(file.get("header", []))
                or type(file.get("raw_count")) is not int or file["raw_count"] < 0):
            _fail("Unsupported or incomplete C06 file declaration", resource_id=file["resource_id"])
    return deepcopy(files)


def _synthetic_selection(value, person_file):
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    contracts = {c["id"]: c for c in value["rules"]["contracts"]}
    mappings = {m["id"]: m for m in value["rules"]["mappings"]}
    files = {f["resource_id"]: f for f in value["files"]}

    def mapping(rid):
        contract = contracts[rid]
        if len(contract["mapping_ids"]) != 1:
            _fail("C06 needs one supported mapping per resource", resource_id=rid)
        entry = mappings[contract["mapping_ids"][0]]
        if entry["version"] != policy["mapping_version"]:
            _fail("C06 mapping version is not implemented", resource_id=rid)
        return deepcopy(entry["content"])

    try:
        pid = person_file["resource_id"]
        person_mapping = mapping(pid)
        aid = contracts[pid]["content"]["identity"]["parent"]["resource_id"]
        vid = person_mapping["vehicle_reference"]["resource_id"]
        ids = {"person": pid, "accident": aid, "vehicle": vid}
        selected = [{**files[rid], "role": role} for role, rid in ids.items()]
        _selection(selected, value["analysis"])
        person_mapping["vehicle_reference"]["resource_id"] = "<vehicle>"
        if person_mapping != policy["person_mapping"]:
            _fail("C06 does not implement this Person definition", resource_id=pid)
        accident_mapping = mapping(aid)
        declared = deepcopy(accident_mapping["declared_person_count"])
        if declared["resource_id"] != pid:
            _fail("The declared count refers to a different Person resource")
        declared["resource_id"] = "<person>"
        if (declared != policy["declared_person_count"]
                or accident_mapping["occurrence_date"] != policy["occurrence_date"]):
            _fail("The Person count or date definition is not implemented")
        mapping(vid)
        for role, rid in ids.items():
            content = contracts[rid]["content"]
            identity = content["identity"]
            common = content["semantics"]["common_rules"]
            expected_parent = None if role == "accident" else {
                "resource_id": aid, "fields": ["ACCIDENT_NO"], "parent_fields": ["ACCIDENT_NO"]}
            if (identity["key"] != policy["keys"][role]
                    or identity["parent"] != expected_parent
                    or identity["scope_filter"] != policy["common_rules"]["scope_filter"]
                    or any(common.get(k) != v for k, v in policy["common_rules"].items())):
                _fail("C06 key, missing-value or scope rules are not implemented", resource_id=rid)
    except (KeyError, TypeError) as exc:
        raise IntakeError("C06_INPUT", "C06 needs complete supported Person and parent definitions") from exc
    return selected


def _run(connection, files, analysis, *, synthetic, restricted=None):
    if connection.autocommit is not False:
        _fail("C06 must use B's active transaction")
    files = _selection(files, analysis)
    request = {"files": files, "analysis": analysis,
               "blank_vehicle_allowed": True if synthetic else None,
               "count_scope_confirmed": synthetic}
    if restricted is not None:
        request["restricted_diagnostics"] = True
    counts, row_counts, reasons = {}, Counter(), Counter()
    diagnostics, affected = [], set()
    seen_raw, seen_locators = set(), set()
    observations = Counter()
    scoped = Counter()
    absolute_delta = 0
    compared = 0
    # Stream the official snapshot within B's transaction.
    cursor_args = {"name": "c06_" + uuid4().hex} if restricted is not None else {}
    with connection.cursor(**cursor_args) as cursor:
        cursor.execute(SQL_PATH.read_text(encoding="utf-8"), (json.dumps(request),))
        for (row,) in cursor:
            if not isinstance(row, dict) or row.get("kind") not in (*ROLES, "file"):
                _fail("Unexpected C06 SQL result")
            if row["kind"] == "file":
                role = row.get("role")
                if role not in ROLES or role in counts:
                    _fail("Duplicate or unknown C06 file result")
                expected = next(f for f in files if f["role"] == role)
                if (any(row.get(k) != expected[k] for k in ("source_id", "resource_id", "file_sha256", "parser_version"))
                        or row.get("expected_count") != expected["raw_count"]
                        or type(row.get("actual_count")) is not int or row["actual_count"] < 0):
                    _fail("C06 file counts do not match the selected manifest")
                counts[role] = row
                if row["actual_count"] != expected["raw_count"]:
                    reasons["selected_raw_count_mismatch"] += 1
                    affected.add(("file", expected["resource_id"]))
                continue
            role = row["kind"]
            expected = next(f for f in files if f["role"] == role)
            if any(row.get(k) != expected[k] for k in ("source_id", "resource_id", "file_sha256", "parser_version")):
                _fail("C06 SQL returned an unselected Raw identity")
            if not row.get("raw_record_id") or not row.get("row_locator") or not isinstance(row.get("issues"), list):
                _fail("C06 SQL result lacks Raw evidence")
            locator = tuple(row[k] for k in ("resource_id", "file_sha256", "parser_version", "row_locator"))
            if row["raw_record_id"] in seen_raw or locator in seen_locators:
                _fail("C06 returned a Raw row more than once")
            seen_raw.add(row["raw_record_id"])
            seen_locators.add(locator)
            row_counts[role] += 1
            if restricted is not None:
                restricted.observe(row)
            issues = row["issues"]
            reasons.update(set(issues))
            if issues:
                affected.add((row["resource_id"], row["raw_record_id"]))
            if role == "person":
                observations[row["vehicle_reference"]] += 1
                scope = "in_scope" if row["in_scope"] is True else "out_of_scope" if row["in_scope"] is False else "unresolved_scope"
                scoped[scope] += 1
            if role == "accident" and row["count_state"] == "compared":
                compared += 1
                absolute_delta += abs(row["count_delta"])
            retain = (issues or row.get("case_evidence") or
                      role == "accident" and row["count_state"] in {"missing", "invalid"})
            if restricted is None:
                retain = (issues or role == "person" and row["vehicle_reference"] != "matched"
                          or role == "accident" and row["count_state"] != "compared")
            if retain:
                diagnostics.append(row)
    if set(counts) != set(ROLES) or any(row_counts[r] != counts[r]["actual_count"] for r in ROLES):
        _fail("C06 did not evaluate every selected Raw row")
    if not synthetic and restricted is None:
        reasons["source_definitions_unconfirmed"] += 1
        affected.add(("source", files[0]["source_id"]))
    report = {
        "producer_version": VERSION, "status": "block" if affected else "pass",
        "scope": "C06 diagnostics only; not a QA04 batch result or publication decision",
        "dataset_kind": "synthetic" if synthetic else "official",
        "definitions_confirmed": synthetic, "analysis": deepcopy(analysis),
        "files": sorted(counts.values(), key=lambda r: r["role"]),
        "selected_files": files, "evaluated_count": sum(row_counts.values()),
        "affected_count": len(affected), "reason_counts": dict(sorted(reasons.items())),
        "person_scope_counts": dict(scoped), "vehicle_reference_counts": dict(observations),
        "person_count_comparisons": compared,
        "declared_count_absolute_delta": absolute_delta if synthetic and compared else None,
        "diagnostics": diagnostics,
    }
    return restricted.finish(report) if restricted is not None else report


def review_manifest(connection, manifest):
    """Evaluate supported Person definitions from B's frozen manifest."""
    if not isinstance(manifest, FrozenManifest):
        _fail("Supply B's FrozenManifest")
    value = manifest.as_dict()
    if value["dataset_kind"] != "synthetic":
        from .restricted_person import review_restricted_manifest
        return [review_restricted_manifest(connection, value)]
    persons = [f for f in value["files"] if f["entity_kind"] == "person_raw"]
    if not persons:
        _fail("This C06 invocation has no Person resource")
    return [_run(connection, _synthetic_selection(value, p), value["analysis"], synthetic=True)
            for p in persons]


def review_official_draft(connection, files, analysis):
    """Inspect pinned official files without approving blank/count definitions."""
    if any(not f.get("source_id", "").startswith("official_")
           or not f.get("resource_id", "").startswith("official_") for f in files):
        _fail("Draft official diagnostics require official input identities")
    return _run(connection, files, analysis, synthetic=False)


def check_person(connection, context):
    """C10 calls this within B's QA stage, then adds the other C checks."""
    if context.dataset_kind != context.manifest.as_dict()["dataset_kind"]:
        _fail("Run context and manifest modes differ")
    reports = review_manifest(connection, context.manifest)
    reference = context.evidence.write_json("c06-person.json", {
        "run_id": context.run_id, "batch_id": context.batch_id, "reports": reports})
    if any(report["status"] == "block" for report in reports):
        raise IntakeError("C06_BLOCK", "Person checks found blocking issues",
                          rule_id="QA04_AUXILIARY", evidence_ref=reference,
                          reason_codes=sorted({r for report in reports for r in report["reason_counts"]}))
    return {"reports": reports, "evidence_ref": reference}
