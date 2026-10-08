"""Progress is new measured evidence or a new QA stage, not edits or rereads."""
import hashlib
import json


def progress_report(steps, settings):
    seen, qa_stages, passed_checks, idle, meaningful = set(), set(), set(), 0, 0
    last = None
    for step in steps:
        name, result = step.get("name"), step.get("result") or {}
        if not isinstance(result, dict):
            result = {}
        idle += 1
        value = None
        if name == "validate_candidate":
            mode = (result.get("host_context") or {}).get("run_mode", "unknown")
            newly_passed = {(mode, check["code"]) for check in result.get("qa", [])
                if isinstance(check, dict) and check.get("status") == "pass" and isinstance(check.get("code"), str)} - passed_checks
            if newly_passed:
                passed_checks.update(newly_passed)
                value = {"newly_passing_qa_checks": sorted(newly_passed)}
        if step.get("status") == "succeeded":
            if name == "profile_dataset" and result.get("complete"):
                value = {k: result.get(k) for k in ("file_id", "table", "row_count", "columns", "unique_column_candidates")}
            elif name == "inspect_relations":
                value = {k: result.get(k) for k in ("child_file_id", "parent_file_id", "child_fields", "parent_fields", "metrics")}
            elif name == "read_document" and result.get("citation_spans"):
                value = {"document_id": result.get("document_id"), "citation_spans": result["citation_spans"]}
            elif name in {"fetch_public_source", "fetch_arcgis_layer"} and result.get("sha256"):
                value = {"sha256": result["sha256"]}
            elif name == "validate_candidate" and result.get("status") in {"sample_only", "validated"}:
                stage = result["status"]
                if stage not in qa_stages:
                    qa_stages.add(stage)
                    value = {"qa_stage": stage}
        if value is not None:
            fingerprint = hashlib.sha256(json.dumps([name, value], sort_keys=True, default=str).encode()).hexdigest()
            if fingerprint not in seen:
                seen.add(fingerprint)
                idle, meaningful, last = 0, meaningful + 1, step.get("id")
    warn, stop = settings.get("warn_after_tools", 0), settings.get("stop_after_tools", 0)
    return {"meaningful_events": meaningful, "last_progress_step_id": last, "tools_without_progress": idle,
            "state": "stalled" if stop and idle >= stop else "replan" if warn and idle >= warn else "continuing",
            "basis": "New complete profiles, relationships, citation spans, source hashes, newly passing QA checks or a first QA stage; edits and identical rereads do not renew allowance."}
