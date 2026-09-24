"""Role E publication completeness and current-release gate."""
from __future__ import annotations

from typing import Any
from .manifest import REQUIRED_CHECKS
from .models import IntakeError

QA07 = "QA07_LOCATION"

def _fetch(connection, sql, parameters=()):
    with connection.cursor() as cursor:
        cursor.execute(sql, parameters)
        return cursor.fetchall()

def _required_objects(manifest: dict[str, Any]) -> dict[str, set[str]]:
    sources = {x["source_id"] for x in manifest["sources"]}
    resources = {x["resource_id"] for x in manifest["files"]}
    crash_unit = {x["resource_id"] for x in manifest["files"]
                  if x["entity_kind"] in {"crash", "unit"}}
    auxiliary = {x["resource_id"] for x in manifest["files"]
                 if x["entity_kind"] in {"unit", "person_raw", "node_raw"}}
    years = range(manifest["analysis"]["year_from"], manifest["analysis"]["year_to"] + 1)
    source_years = {f"source_year:{source}:{year}" for source in sources for year in years}
    file_objects = {f"file:{x['resource_id']}:{x['file_sha256']}:{x['parser_version']}" for x in manifest["files"]}
    return {
        "QA01_INPUT": file_objects,
        "QA02_RAW": file_objects,
        "QA03_PROJECTED": {f"resource:{x}" for x in crash_unit},
        "QA04_AUXILIARY": {f"resource:{x}" for x in auxiliary},
        "QA05_SEMANTICS": {f"source:{x}" for x in sources},
        "QA06_RECONCILIATION": source_years,
        "QA07_LOCATION": source_years,
    }

def _json_shape(name, value):
    if not isinstance(value, dict) or set(value) != {"evaluated_count", "violation_count", "metrics"}:
        raise IntakeError("PUBLICATION_QA", f"{name} has an invalid shape")
    if type(value["evaluated_count"]) is not int or value["evaluated_count"] < 0:
        raise IntakeError("PUBLICATION_QA", f"{name}.evaluated_count is invalid")
    if type(value["violation_count"]) is not int or value["violation_count"] < 0:
        raise IntakeError("PUBLICATION_QA", f"{name}.violation_count is invalid")
    if not isinstance(value["metrics"], dict):
        raise IntakeError("PUBLICATION_QA", f"{name}.metrics is invalid")

def validate_publication_gate(connection, batch_id: str, manifest: dict[str, Any]):
    if getattr(connection, "autocommit", None) is not False:
        raise IntakeError("PUBLICATION_AUTOCOMMIT", "Publication must run inside the caller transaction")
    batch = _fetch(connection, """SELECT dataset_kind,status,input_fingerprint,manifest
        FROM meta.batch WHERE batch_id=%s::uuid""", (batch_id,))
    if len(batch) != 1 or batch[0][1] != "running":
        raise IntakeError("PUBLICATION_BATCH", "Candidate batch must be running")
    if batch[0][3] != manifest:
        raise IntakeError("PUBLICATION_MANIFEST", "Database candidate does not match frozen manifest")

    required = _required_objects(manifest)
    rows = _fetch(connection, """SELECT rule_id,object_key,result,affected_count,actual,expected,evidence
        FROM qa.check_result WHERE batch_id=%s::uuid ORDER BY rule_id,object_key""", (batch_id,))
    grouped: dict[str, dict[str, tuple]] = {}
    for row in rows:
        grouped.setdefault(row[0], {})
        if row[1] in grouped[row[0]]:
            raise IntakeError("PUBLICATION_QA", "Duplicate QA object", rule_id=row[0], object_key=row[1])
        grouped[row[0]][row[1]] = row

    summaries = {}
    for rule in REQUIRED_CHECKS:
        objects = grouped.get(rule, {})
        missing = required[rule] - (set(objects) - {"batch"})
        extra = (set(objects) - {"batch"}) - required[rule]
        if missing:
            raise IntakeError("PUBLICATION_QA_MISSING", "Required QA objects are missing", rule_id=rule, missing=sorted(missing))
        if extra:
            raise IntakeError("PUBLICATION_QA_EXTRA", "Unexpected QA objects are present", rule_id=rule, extra=sorted(extra))
        summary = objects.get("batch")
        if summary is None:
            raise IntakeError("PUBLICATION_QA_MISSING", "Every required rule needs a batch summary", rule_id=rule)
        for key, row in objects.items():
            _json_shape(f"{rule}:{key}.actual", row[4])
            _json_shape(f"{rule}:{key}.expected", row[5])
            if row[5]["violation_count"] != 0:
                raise IntakeError("PUBLICATION_QA_EXPECTED", "Expected violation count must be zero")
            if row[2] == "block":
                raise IntakeError("PUBLICATION_QA_BLOCK", "A required QA object blocks publication", rule_id=rule, object_key=key)
            if row[2] == "limited" and rule != QA07:
                raise IntakeError("PUBLICATION_QA_LIMITED", "Only QA07 may be limited", rule_id=rule, object_key=key)
            if row[2] not in {"pass", "limited"}:
                raise IntakeError("PUBLICATION_QA_RESULT", "Invalid QA publication result")
            if row[2] == "pass" and row[3] != 0:
                raise IntakeError("PUBLICATION_QA_AFFECTED", "A pass result must have zero affected objects")
            if row[4]["violation_count"] != 0:
                raise IntakeError("PUBLICATION_QA_VIOLATION", "A QA object has a violation", rule_id=rule, object_key=key)

        actual = summary[4]
        if actual["metrics"].get("object_count") != len(required[rule]):
            raise IntakeError("PUBLICATION_QA_SUMMARY", "Summary object_count does not match required coverage", rule_id=rule)
        if actual["metrics"].get("block_count") != 0 or actual["metrics"].get("missing_count") != 0:
            raise IntakeError("PUBLICATION_QA_SUMMARY", "Summary contains block or missing objects", rule_id=rule)
        if summary[2] == "limited" and rule != QA07:
            raise IntakeError("PUBLICATION_QA_SUMMARY", "Only QA07 summary may be limited", rule_id=rule)
        summaries[rule] = {"rule_id": rule, "result": summary[2], "affected_count": summary[3]}

    return summaries

def publish(connection, context):
    manifest = context.manifest.as_dict()
    summaries = validate_publication_gate(connection, context.batch_id, manifest)

    updated = _fetch(connection, """UPDATE meta.batch
        SET status='succeeded', finished_at=clock_timestamp()
        WHERE batch_id=%s::uuid AND status='running'
        RETURNING batch_id,status""", (context.batch_id,))
    if len(updated) != 1 or str(updated[0][0]) != context.batch_id or updated[0][1] != "succeeded":
        raise IntakeError("PUBLICATION_BATCH", "Candidate could not be marked succeeded")

    pointer = _fetch(connection, """INSERT INTO meta.current_release(dataset_kind,batch_id,batch_status)
        VALUES (%s,%s::uuid,'succeeded')
        ON CONFLICT (dataset_kind) DO UPDATE
        SET batch_id=EXCLUDED.batch_id,batch_status='succeeded',switched_at=clock_timestamp()
        RETURNING dataset_kind,batch_id,batch_status""", (manifest["dataset_kind"], context.batch_id))
    if len(pointer) != 1 or str(pointer[0][1]) != context.batch_id:
        raise IntakeError("PUBLICATION_POINTER", "Current release pointer did not switch")
    return {"batch_id": context.batch_id, "dataset_kind": manifest["dataset_kind"], "qa_summary": summaries}
