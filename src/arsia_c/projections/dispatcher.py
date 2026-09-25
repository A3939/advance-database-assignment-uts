"""Run each selected source projection in B's transaction."""

from . import nsw, qld, vic
from arsia_ingest.models import IntakeError


def project(connection, context):
    """Keep the original context and evidence sink for all source modules."""
    if connection.autocommit is not False:
        raise IntakeError("PROJECT_TRANSACTION", "Projection needs a caller-owned transaction")
    manifest = context.manifest.as_dict()
    if context.dataset_kind != manifest["dataset_kind"]:
        raise IntakeError("PROJECT_KIND", "Context and manifest dataset kinds differ")
    callbacks = {"NSW": nsw.project, "VIC": vic.project, "QLD": qld.project}
    selected = {}
    source_ids = set()
    for source in manifest["sources"]:
        state = source["jurisdiction_code"]
        source_id = source["source_id"]
        if state not in callbacks or state in selected or source_id in source_ids:
            raise IntakeError(
                "PROJECT_SOURCE", "Each selected source needs one supported projection",
                source_id=source_id, jurisdiction_code=state,
            )
        selected[state] = source_id
        source_ids.add(source_id)
    if not selected or any(f["source_id"] not in source_ids for f in manifest["files"]):
        raise IntakeError("PROJECT_SOURCE", "Selected files and sources must agree")
    # Reject unsupported source selection before any projection writes.
    for state in callbacks:
        if state in selected:
            callbacks[state](connection, context)
    context.evidence.write_json(
        "project-dispatch.json",
        {"batch_id": str(context.batch_id), "dataset_kind": context.dataset_kind,
         "sources": [{"source_id": selected[state], "jurisdiction_code": state}
                     for state in callbacks if state in selected],
         "scope": "Source projections only; C10 QA and publication are separate"},
    )
    return {"project_source_count": len(selected)}
