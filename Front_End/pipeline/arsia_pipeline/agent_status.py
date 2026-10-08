"""Small user-facing progress projection; never serializes model/code bodies."""
from . import store

PHASES = {
    'inspect_task_scope': ('inspecting', 'Checking how these fields relate to this road-safety task'),
    'run_diagnostic': ('researching', 'Running an isolated comparison for the current blocker'),
    'request_engineering_repair': ('needs_input', 'Saving the isolated engineering repair and required checks'),
    "get_workflow_state": ("researching", "Reviewing saved evidence and remaining checks"),
    "submit_workspace": ("preparing", "Checking the proposed transformation and source contract"),
    "codex.command_execution": ("preparing", "Reading task evidence and checking the transformation"),
    "codex.file_change": ("preparing", "Editing the task transformation"),
    "inspect_bundle": ("inspecting", "Inspecting files and available tables"),
    "inspect_capabilities": ("inspecting", "Checking supported source capabilities"),
    "preflight_contract": ("preparing", "Checking source evidence and capabilities before execution"),
    "profile_dataset": ("inspecting", "Measuring source fields and completeness"),
    "inspect_relations": ("inspecting", "Checking relationships across source tables"),
    "read_document": ("researching", "Reading source definitions"),
    "discover_source_docs": ("researching", "Locating official source documentation"),
    "fetch_public_source": ("researching", "Retrieving official source evidence"),
    "fetch_arcgis_layer": ("researching", "Retrieving a complete official data layer"),
    "read_registry": ("preparing", "Checking previously verified source versions"),
    "read_adapter": ("preparing", "Reviewing the transformation"),
    "get_adapter_contract": ("preparing", "Reviewing the canonical data requirements"),
    "set_source_contract": ("preparing", "Checking source meaning and update coverage"),
    "patch_source_contract": ("preparing", "Correcting source meaning while preserving existing evidence"),
    "write_adapter": ("preparing", "Creating a transformation version"),
    "patch_adapter": ("preparing", "Correcting a transformation version"),
    "inspect_run": ("preparing", "Investigating execution diagnostics"),
    "register_adapter": ("registering", "Recording the verified source version"),
    "publish_candidate": ("publishing", "Preparing atomic publication"),
    "request_missing_information": ("needs_input", "Identifying information still needed"),
}


def phase_for(row, mode):
    name = row["name"]
    if name in {"run_python", "run_adapter"}:
        value = (row.get("arguments") or {}).get("mode", "sample")
        return ("full_running", "Executing the complete source bundle") if value == "full" else ("sample_running", "Executing a diagnostic sample")
    if name == "validate_candidate":
        sample = (row.get("result") or {}).get("status") == "sample_only" or mode == "sample"
        return ("sample_qa", "Independently checking the sample") if sample else ("full_qa", "Independently checking the complete candidate")
    if row["kind"] == "model":
        return ("researching", "Reviewing evidence and deciding the next investigation step")
    return PHASES.get(name, ("researching", "Investigating the source"))


def status(job):
    with store.connect() as conn:
        session = conn.execute("SELECT id,status,model_calls,tool_calls,correction_count,checkpoint->'investigation_progress' AS investigation, checkpoint->'runtime_state' AS runtime FROM agent_sessions WHERE job_id=%s", (job["id"],)).fetchone()
        if not session:
            return None
        rows = conn.execute("SELECT kind,name,status,arguments,result,created_at FROM agent_steps WHERE session_id=%s ORDER BY id DESC LIMIT 5", (session["id"],)).fetchall()
        latest_run = conn.execute("SELECT arguments->>'mode' AS mode FROM agent_steps WHERE session_id=%s AND name IN ('run_python','run_adapter') ORDER BY id DESC LIMIT 1", (session["id"],)).fetchone()
        mode = latest_run["mode"] if latest_run else "sample"
        checks = conn.execute("""SELECT count(*) FILTER (WHERE name IN ('run_python','run_adapter') AND result ? 'run_id' AND coalesce(arguments->>'mode','sample')='sample') AS sample_runs,
            count(*) FILTER (WHERE name IN ('run_python','run_adapter') AND result ? 'run_id' AND arguments->>'mode'='full') AS full_runs,
            count(*) FILTER (WHERE name='validate_candidate') AS qa_checks,
            count(*) FILTER (WHERE name='validate_candidate' AND status='succeeded' AND result->'admission'->>'status' IN ('sample_only','admitted')) AS qa_passed,
            count(*) FILTER (WHERE name='validate_candidate' AND status='failed') AS qa_failed,
            count(*) FILTER (WHERE name='validate_candidate' AND status IN ('needs_evidence','paused')) AS qa_blocked,
            count(*) FILTER (WHERE name='validate_candidate' AND status='running') AS qa_running,
            count(*) FILTER (WHERE name='validate_candidate' AND status IN ('cancelled','interrupted')) AS qa_interrupted,
            count(*) FILTER (WHERE name='validate_candidate' AND status NOT IN ('failed','needs_evidence','paused','running','cancelled','interrupted')
                AND NOT coalesce(status='succeeded' AND result->'admission'->>'status' IN ('sample_only','admitted'),false)) AS qa_unclassified
            FROM agent_steps WHERE session_id=%s""", (session["id"],)).fetchone()
    steps = []
    for row in reversed(rows):
        phase, summary = phase_for(row, mode)
        steps.append({"kind": row["kind"], "phase": phase, "status": row["status"], "summary": summary, "at": row["created_at"].isoformat()})
    phase = steps[-1]["phase"] if steps else "inspecting"
    if session["status"] == "waiting_for_model":
        phase = "waiting_for_model"
    if job["status"] in {"needs_input", "succeeded", "no_change", "cancelled", "failed", "publishing"}:
        phase = job["status"]
    elif job["status"] in {"queued", "cancel_requested"}:
        phase = "preparing"
    runtime = session.get('runtime') or {}
    repair = runtime.get('repair') or {}
    goal = runtime.get('original_goal') or {}
    summary = None
    if goal or repair:
        summary = {'original_goal': str(goal.get('task', goal.get('objective', 'Australian road-safety import')))[:1000],
            'requested_context': str((goal.get('user_context') or {}).get('answers') or (goal.get('user_context') or {}).get('source_hint') or '')[:2000],
            'target_satisfied': goal.get('target_satisfied') is True,
            'current_blocker': None if job['status'] in {'succeeded','no_change'} else str(repair.get('message', ''))[:1500],
            'route': repair.get('route'), 'operation': repair.get('operation'),
            'diagnostic_attempts': [{'purpose':r.get('binding',{}).get('purpose'), 'status':r.get('status')}
                                  for r in runtime.get('diagnostic_runs', [])[-8:]],
            'limitations': (job.get('result') or {}).get('limitations', [])[:12]}
    return {"status": job["status"], "phase": phase, "model_calls": session["model_calls"],
            "tool_calls": session["tool_calls"], "correction_count": session["correction_count"], "checks": checks, "latest_steps": steps,
            "investigation": session.get('investigation'), 'repair':summary}
