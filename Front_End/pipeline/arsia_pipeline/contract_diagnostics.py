"""Durable diagnostics: only the appropriate successful gate resolves a failure."""
import json

CONTRACT_TOOLS = {"set_source_contract", "patch_source_contract"}
RUN_TOOLS = {"run_adapter", "run_python"}
TOOLS = CONTRACT_TOOLS | RUN_TOOLS | {"validate_candidate", "write_adapter", "patch_adapter"}
TOOLS.add('preflight_contract')


def unresolved_diagnostics(steps, *, contract_sha256, code_sha256, attempt_id, bounded=True):
    unresolved, runs = {}, {}
    for step in steps:
        name, status, output = step.get("name"), step.get("status"), step.get("result") or {}
        if name not in TOOLS or not isinstance(output, dict):
            continue
        args, context = step.get("arguments") or {}, output.get("host_context") or {}
        preflight = output if name == 'preflight_contract' else output.get('preflight', {}) if name in CONTRACT_TOOLS else {}
        if isinstance(preflight, dict) and 'ok' in preflight:
            if preflight['ok'] is False:
                unresolved['preflight'] = {'step_id': step.get('id'), 'tool': name, 'status': 'blocked',
                    'category': 'preflight', 'attempt_id': str(step.get('attempt_id')),
                    'recorded_contract_sha256': context.get('contract_sha256'),
                    'current_contract_sha256': contract_sha256, 'resolution_state': 'unresolved',
                    'diagnostic': {'blockers': preflight.get('blockers', [])},
                    'read_full': {'tool': 'read_task_state', 'arguments': {'kind': 'tool_result', 'step_id': step.get('id')}}}
            elif str(step.get('attempt_id')) == str(attempt_id) and context.get('contract_sha256') == contract_sha256:
                unresolved.pop('preflight', None)
        if name == 'preflight_contract':
            continue
        if name in RUN_TOOLS and output.get("run_id"):
            runs[output["run_id"]] = args.get("mode", "sample")
        mode = context.get("run_mode") or (args.get("mode", "sample") if name in RUN_TOOLS else runs.get(args.get("run_id")))
        # Historical validations without a run reference are conservatively full.
        if name == "validate_candidate" and not mode:
            mode = "sample" if output.get("status") == "sample_only" else "full"
        category = "contract" if name in CONTRACT_TOOLS else ("execution." if name in RUN_TOOLS else "validation.") + str(mode)
        recorded_contract, recorded_code = context.get("contract_sha256"), context.get("code_sha256")
        same_version = (not recorded_contract or recorded_contract == contract_sha256) and (not recorded_code or recorded_code == code_sha256)
        failed_run = name in RUN_TOOLS and output.get("status") not in {None, "succeeded"}
        if status == "succeeded" and not failed_run:
            if name in CONTRACT_TOOLS and output.get("status") == "proposed":
                unresolved.pop("contract", None)
            if name in CONTRACT_TOOLS | {"write_adapter", "patch_adapter"}:
                for item in unresolved.values():
                    if item['step_id'] != step.get('id'):
                        item["resolution_state"] = "needs_revalidation"
            elif same_version and str(step.get("attempt_id")) == str(attempt_id):
                if name in RUN_TOOLS:
                    unresolved.pop(category, None)
                elif name == "validate_candidate":
                    if output.get("status") == "sample_only":
                        unresolved.pop("validation.sample", None)
                    elif output.get("status") == "validated":
                        for key in list(unresolved):
                            if key.startswith(("execution.", "validation.")):
                                unresolved.pop(key)
            continue
        if name not in CONTRACT_TOOLS | RUN_TOOLS | {"validate_candidate"} or (status not in {"failed", "needs_evidence"} and not failed_run):
            continue
        if category == "contract" and recorded_contract and recorded_contract != contract_sha256:
            continue
        details = {key: output[key] for key in ("type", "message", "error", "details", "qa", "questions", "stderr") if key in output}
        diagnostic = {"step_id": step.get("id"), "tool": name, "status": status, "category": category,
            "attempt_id": str(step.get("attempt_id")) if step.get("attempt_id") else None,
            "attempt_relation": "current" if str(step.get("attempt_id")) == str(attempt_id) else "previous",
            "recorded_contract_sha256": recorded_contract, "recorded_code_sha256": recorded_code,
            "current_contract_sha256": contract_sha256,
            "version_match": ("current" if same_version else "previous") if recorded_contract else "not_recorded_in_historical_step",
            "resolution_state": "unresolved" if same_version else "needs_revalidation",
            "run_id": args.get("run_id") or output.get("run_id"), "diagnostic": details,
            "read_full": {"tool": "read_task_state", "arguments": {"kind": "tool_result", "step_id": step.get("id")}}}
        if bounded and len(json.dumps(diagnostic, ensure_ascii=False, default=str).encode()) > 7000:
            diagnostic["diagnostic"] = {"type": output.get("type"), "message": str(output.get("message", ""))[:1000],
                "bounded": True, "note": "Read the full durable result with read_full; omitted evidence is not resolved."}
        unresolved[category] = diagnostic
    return list(unresolved.values())
