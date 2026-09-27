"""Role E publication completeness and current-release gate."""
from __future__ import annotations

from typing import Any
from .manifest import REQUIRED_CHECKS, validate_manifest
from .publication_checks import Requirements
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

def validate_publication_gate(connection, batch_id: str, manifest: dict[str, Any]):
    if getattr(connection, "autocommit", None) is not False:
        raise IntakeError("PUBLICATION_AUTOCOMMIT", "Publication must run inside the caller transaction")
    validate_manifest(manifest)
    batch = _fetch(connection, """SELECT dataset_kind,status,input_fingerprint,manifest
        FROM meta.batch WHERE batch_id=%s::uuid FOR UPDATE""", (batch_id,))
    if len(batch) != 1 or batch[0][1] != "running":
        raise IntakeError("PUBLICATION_BATCH", "Candidate batch must be running")
    if batch[0][3] != manifest or batch[0][0] != manifest["dataset_kind"]:
        raise IntakeError("PUBLICATION_MANIFEST", "Database candidate does not match frozen manifest")

    required = _required_objects(manifest)
    rows = _fetch(connection, """SELECT rule_id,object_key,result,affected_count,actual,expected,evidence
        FROM qa.check_result WHERE batch_id=%s::uuid ORDER BY rule_id,object_key""", (batch_id,))
    grouped: dict[str, dict[str, tuple]] = {}
    for row in rows:
        # Extra checks can block too, including diagnostics outside the normal object set.
        if row[2] == "block":
            raise IntakeError("PUBLICATION_QA_BLOCK", "A QA object blocks publication", rule_id=row[0], object_key=row[1])
        if row[0] not in required:
            raise IntakeError("PUBLICATION_QA_EXTRA", "Unreviewed QA rule", rule_id=row[0])
        grouped.setdefault(row[0], {})
        if row[1] in grouped[row[0]]:
            raise IntakeError("PUBLICATION_QA", "Duplicate QA object", rule_id=row[0], object_key=row[1])
        grouped[row[0]][row[1]] = row

    checks = Requirements(connection, batch_id, manifest)
    summaries = {}
    for rule in REQUIRED_CHECKS:
        objects = grouped.get(rule, {})
        missing = (required[rule] | {"batch"}) - set(objects)
        extra = set(objects) - (required[rule] | {"batch"})
        if missing:
            raise IntakeError("PUBLICATION_QA_MISSING", "Required QA objects are missing", rule_id=rule, missing=sorted(missing))
        if extra:
            raise IntakeError("PUBLICATION_QA_EXTRA", "Unexpected QA objects are present", rule_id=rule, extra=sorted(extra))
        concrete = [objects[key] for key in sorted(required[rule])]
        for row in concrete:
            checks.check(row)
        summaries[rule] = checks.summary(objects["batch"], concrete)
    return summaries

def publish(connection, context):
    manifest = context.manifest.as_dict()
    identity = _fetch(connection, "SELECT dataset_kind,input_fingerprint FROM meta.batch WHERE batch_id=%s::uuid",
                      (context.batch_id,))
    if identity != [(context.dataset_kind, context.input_fingerprint)] or context.dataset_kind != manifest["dataset_kind"]:
        raise IntakeError("PUBLICATION_CONTEXT", "Run context differs from the candidate batch")
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
