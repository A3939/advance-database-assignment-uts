"""OPT-IN real-model repair acceptance in a newly created TEST database.

No live import jobs, worker interruptions, production publication or oracle input.
The one injected NameError lives only in this process's AgentSession subclass.
Gateway, documentation tools, Docker executor, sample/full QA and publication
are the actual implementations. Running this tool consumes real model calls.
Without --confirm-real-model-recovery, no database or model work is performed.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import UUID, uuid4

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "pipeline"))

from arsia_pipeline import agent, store
from arsia_pipeline.config import CONFIG, ROOT, read_config
from arsia_pipeline.errors import NeedsInput


def sha(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("w") as handle:
        os.chmod(path, 0o600)
        json.dump(value, handle, ensure_ascii=False, indent=2, default=str, allow_nan=False)
        handle.write("\n")


def inject_name_error(code, symbol):
    """Transform syntax only; generated Python is never executed on the host."""
    if not symbol.isidentifier() or symbol in code:
        raise ValueError("Injected symbol must be a fresh valid identifier")
    tree = ast.parse(code)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "adapt"]
    if len(functions) != 1:
        raise ValueError("The recovery test requires exactly one synchronous def adapt(ctx)")
    body = functions[0].body
    index = 1 if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str) else 0
    body.insert(index, ast.Expr(value=ast.Name(id=symbol, ctx=ast.Load())))
    return ast.unparse(ast.fix_missing_locations(tree)) + "\n"


class RecoverySession(agent.AgentSession):
    """Test-only interception; no live worker or shared module is monkeypatched."""
    def __init__(self, *args, **kwargs):
        self.injection = None
        self.model_input_receipts = []
        super().__init__(*args, **kwargs)

    def wire_messages(self):
        value = super().wire_messages()
        failures = {run_id for run_id, run in self.runs.items() if run.get("status") == "failed"
                    and run.get("error", {}).get("type") == "NameError" and self.injection
                    and run.get("code_sha256") == self.injection["injected_sha256"]}
        observed = set()
        def inspect(node):
            if isinstance(node, dict):
                if node.get("run_id") in failures and node.get("status") == "failed" \
                   and isinstance(node.get("error"), dict) and node["error"].get("type") == "NameError":
                    observed.add(node["run_id"])
                for child in node.values():
                    if isinstance(child, (dict, list)):
                        inspect(child)
            elif isinstance(node, list):
                for child in node:
                    inspect(child)
        for item in value:
            if item.get("type") == "function_call_output":
                try:
                    inspect(json.loads(item.get("output", "")))
                except (ValueError, TypeError):
                    pass
        path = self.work_dir / "actual-model-inputs" / (str(self.usage["model_calls"]) + ".json")
        save(path, value)
        self.model_input_receipts.append({"model_call": self.usage["model_calls"], "path": str(path), "sha256": sha(path),
                                          "structured_failed_sample_run_ids": sorted(observed)})
        return value

    def write_code(self, code, reason):
        if self.injection is None:
            symbol = "arsia_recovery_unbound_" + uuid4().hex
            # Preserve the model's original bytes separately from injected code.
            original = code
            code = inject_name_error(code, symbol)
            self.injection = {"count": 1, "kind": "NameError", "symbol": symbol,
                              "original_sha256": hashlib.sha256(original.encode()).hexdigest(),
                              "injected_sha256": hashlib.sha256(code.encode()).hexdigest(),
                              "model_call": self.usage["model_calls"], "tool_call": self.usage["tool_calls"],
                              "notice": "Controlled test fault, not a naturally generated model error."}
            source = self.work_dir / "model-original-before-injection.py"
            source.write_text(original)
            source.chmod(0o400)
            save(self.work_dir / "injection.json", self.injection)
        return super().write_code(code, reason)

    def execute_tool(self, name, args):
        if name == "run_python" and self.injection is None and self.contract:
            # Production run_python keeps a local code variable before calling
            # write_code. Substitute only this test invocation so it cannot run
            # the uninjected original while the checkpoint holds injected code.
            self.write_code(args["code"], "New code supplied to isolated execution")
            args = {**args, "code": self.code}
        return super().execute_tool(name, args)


def evaluate_recovery(steps, injection, admission, model_inputs=None):
    """Independent ordered assertions over saved actual tool/model events."""
    checks = []
    def check(name, value):
        checks.append({"check": name, "passed": bool(value)})
    successful_models = [i for i,s in enumerate(steps) if s["kind"] == "model" and s["status"] == "succeeded"
                         and (s.get("result") or {}).get("id") and (s.get("result") or {}).get("model")]
    check("real_model_response_receipts", len(successful_models) >= 2)
    check("exactly_one_controlled_injection", injection and injection.get("count") == 1)
    failed = [i for i,s in enumerate(steps) if s["name"] in {"run_adapter", "run_python"}
              and (s.get("result") or {}).get("mode") == "sample"
              and (s.get("result") or {}).get("status") == "failed"
              and (s.get("result") or {}).get("error", {}).get("type") == "NameError"
              and injection and (s.get("result") or {}).get("code_sha256") == injection["injected_sha256"]]
    check("injected_version_actually_failed_sample", bool(failed))
    check("failed_version_never_admitted_or_registered", not any(
        s["status"] == "succeeded" and ((s["name"] == "register_adapter"
        and (s.get("result") or {}).get("code_sha256") == (injection or {}).get("injected_sha256"))
        or (s["name"] == "validate_candidate" and (s.get("result") or {}).get("status") == "validated"
        and (s.get("result") or {}).get("admission", {}).get("adapter_sha256") == (injection or {}).get("injected_sha256")))
        for s in steps))
    first = failed[0] if failed else len(steps)
    repaired = [i for i,s in enumerate(steps) if i > first and s["name"] in {"run_adapter", "run_python"}
                and (s.get("result") or {}).get("mode") == "sample"
                and (s.get("result") or {}).get("status") == "succeeded"
                and (s.get("result") or {}).get("code_sha256") != (injection or {}).get("injected_sha256")
                and (not admission.get("adapter_sha256") or (s.get("result") or {}).get("code_sha256") == admission["adapter_sha256"])]
    repair = repaired[0] if repaired else len(steps)
    check("model_received_failure_before_repair", any(first < i < repair for i in successful_models))
    explicit = any(first < i < repair and s["status"] == "succeeded"
                   and s["name"] in {"inspect_run", "read_adapter"} for i,s in enumerate(steps))
    failed_run_ids = {(steps[i].get("result") or {}).get("run_id") for i in failed} - {None}
    consumed_calls = {(steps[i].get("arguments") or {}).get("model_call") for i in successful_models if first < i < repair} - {None}
    structured = any(item["model_call"] in consumed_calls and failed_run_ids.intersection(item.get("structured_failed_sample_run_ids", []))
                     for item in model_inputs or [])
    check("model_consumed_actual_failure_diagnostics", explicit or structured)
    check("corrected_code_version_passed_sample", bool(repaired))
    repaired_hash = (steps[repair].get("result") or {}).get("code_sha256") if repaired else None
    sample_qa = [i for i,s in enumerate(steps) if i > repair and s["name"] == "validate_candidate"
                 and s["status"] == "succeeded" and (s.get("result") or {}).get("status") == "sample_only"
                 and (s.get("result") or {}).get("admission", {}).get("adapter_sha256") == repaired_hash]
    full = [i for i,s in enumerate(steps) if s["name"] in {"run_adapter", "run_python"}
            and (s.get("result") or {}).get("mode") == "full" and (s.get("result") or {}).get("status") == "succeeded"
            and (s.get("result") or {}).get("code_sha256") == repaired_hash and any(q < i for q in sample_qa)]
    check("sample_independent_qa_before_full_same_version", bool(full))
    full_qa = [i for i,s in enumerate(steps) if s["name"] == "validate_candidate" and s["status"] == "succeeded"
               and (s.get("result") or {}).get("status") == "validated" and any(run < i for run in full)
               and (s.get("result") or {}).get("admission", {}).get("adapter_sha256") == repaired_hash]
    check("full_independent_qa_admitted_repaired_version", bool(full_qa) and admission.get("status") == "admitted"
          and admission.get("adapter_sha256") == repaired_hash)
    check("full_admission_uses_actual_executor_image", isinstance(admission.get("image"), str) and admission["image"].startswith("sha256:"))
    check("full_admission_records_trusted_implementation", bool(admission.get("trusted_implementation")))
    registered = [i for i,s in enumerate(steps) if s["name"] == "register_adapter" and s["status"] == "succeeded"
                  and (s.get("result") or {}).get("code_sha256") == repaired_hash and any(q < i for q in full_qa)]
    check("registered_only_after_full_qa", bool(registered))
    check("publication_requested_after_registration", any(s["name"] == "publish_candidate" and s["status"] == "succeeded"
          and any(r < i for r in registered) for i,s in enumerate(steps)))
    return {"passed": all(row["passed"] for row in checks), "checks": checks,
            "successful_model_responses": len(successful_models), "injected_version_failed_samples": len(failed),
            "repaired_code_sha256": repaired_hash,
            "diagnostic_consumption": {"explicit_inspection_tool": explicit, "structured_failure_in_actual_model_input": structured},
            "controlled_error_is_natural_model_error": False}


def live_snapshot(config):
    with store.connect(config) as conn, conn.transaction():
        conn.execute("SET TRANSACTION READ ONLY")
        current = conn.execute("SELECT r.id,r.sources FROM current_release c JOIN releases r ON r.id=c.release_id").fetchone()
        totals = {table: conn.execute("SELECT count(*) AS n FROM " + table).fetchone()["n"]
                  for table in ("jobs", "batches", "releases", "adapter_versions", "source_versions")}
    return {"release": json.loads(json.dumps(current, default=str)), "row_counts": totals}


def admitted_input(config, job_id):
    with store.connect(config) as conn, conn.transaction():
        conn.execute("SET TRANSACTION READ ONLY")
        job = conn.execute("SELECT * FROM jobs WHERE id=%s", (job_id,)).fetchone()
    result = (job or {}).get("result") or {}
    admission = result.get("admission", {})
    if not job or job["status"] not in {"succeeded", "no_change"} or admission.get("status") != "admitted" \
       or not admission.get("policy_version", "").startswith("canonical-v2-auto-admission-") \
       or not result.get("adapter_version_id") or not result.get("source_version_id"):
        raise ValueError("Select an already fully admitted autonomous actual-source job, not a synthetic or pending task")
    from urllib.parse import urlsplit
    documents = admission.get("evidence", {}).get("source_identity", [])
    if not any((urlsplit(doc.get("url", "")).hostname or "").endswith(".gov.au") and len(doc.get("sha256", "")) == 64 for doc in documents):
        raise ValueError("The baseline must have trusted official-source identity evidence")
    for file in job["files"]:
        path = Path(file["path"])
        if path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()) or not path.is_file() \
           or path.stat().st_size != file["size"] or sha(path) != file["sha256"]:
            raise ValueError("Baseline uploaded bytes are missing, changed or outside the private lab")
    return job["files"], {"job_id": str(job_id), "source_id": job["source_id"], "batch_id": str(job["batch_id"]),
                          "release_id": str(job["release_id"]), "input_hashes": [f["sha256"] for f in job["files"]]}


@contextmanager
def test_database(original, receipt):
    """Same isolated-database pattern as tests/test_backend.py; never reuse DBs."""
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    name = "arsia_imports_test_recovery_" + uuid4().hex[:12]
    cfg = {**original, "database": name, "instance_id": uuid4().hex}
    parts = conninfo_to_dict(original["dsn"])
    parts["dbname"] = name
    cfg["dsn"] = make_conninfo(**parts)
    path = ROOT / (name + ".json")
    previous = os.environ.get("ARSIA_IMPORT_CONFIG")
    initialized = created_config = False
    with store.connect(original) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    receipt["test_database"] = {"name": name, "instance_id": cfg["instance_id"], "created": True, "dropped": False}
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created_config = True
        with os.fdopen(fd, "w") as handle:
            json.dump(cfg, handle)
        os.environ["ARSIA_IMPORT_CONFIG"] = str(path)
        store.initialize(cfg)
        initialized = True
        yield cfg
    finally:
        if previous is None:
            os.environ.pop("ARSIA_IMPORT_CONFIG", None)
        else:
            os.environ["ARSIA_IMPORT_CONFIG"] = previous
        # An initialization error is preserved for operator inspection; never
        # drop an unverified database solely because its name resembles ours.
        if initialized:
            with store.connect(cfg):
                pass
            with store.connect(original) as admin:
                admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
            receipt["test_database"]["dropped"] = True
        if created_config:
            path.unlink(missing_ok=True)


def saved_steps(session):
    with store.connect() as conn:
        return conn.execute("SELECT * FROM agent_steps WHERE session_id=%s ORDER BY id", (session.id,)).fetchall()


def evidence(session, directory):
    steps = saved_steps(session)
    with store.connect() as conn:
        checkpoint = conn.execute("SELECT * FROM agent_sessions WHERE id=%s", (session.id,)).fetchone()
        job = conn.execute("SELECT * FROM jobs WHERE id=%s", (session.job["id"],)).fetchone()
        attempts = conn.execute("SELECT * FROM attempts WHERE job_id=%s ORDER BY number", (session.job["id"],)).fetchall()
    save(directory / "durable-evidence.json", agent.safe({"session": checkpoint, "job": job, "attempts": attempts, "steps": steps}))
    versions = [{"name": path.name, "sha256": sha(path), "bytes": path.stat().st_size}
                for path in sorted((session.work_dir / "adapter-versions").glob("*.py"))]
    manifests = [{"path": str(path), "sha256": sha(path)} for path in sorted(session.work_dir.glob("run-*/execution.json"))]
    save(directory / "artifact-index.json", {"work_dir": str(session.work_dir), "versions": versions, "execution_receipts": manifests})
    save(directory / "model-input-receipts.json", session.model_input_receipts)
    return steps


def run(args):
    if not args.confirm_real_model_recovery:
        raise ValueError("Explicit --confirm-real-model-recovery is required")
    from fastapi.testclient import TestClient
    from psycopg.types.json import Jsonb
    from arsia_pipeline import api, worker
    original = read_config()
    if original["database"].startswith("arsia_imports_test_"):
        raise ValueError("Start from the existing local lab configuration, not another test database")
    if not original.get("agent_gateway_token"):
        raise ValueError("The actual model gateway must already be configured")
    with store.connect(original) as conn, conn.transaction():
        conn.execute("SET TRANSACTION READ ONLY")
        if conn.execute("SELECT count(*) AS n FROM jobs WHERE status=ANY(%s)", ([*store.ACTIVE, "queued"],)).fetchone()["n"]:
            raise ValueError("Run the resource-intensive recovery test only while the existing lab queue is idle")
    inputs, baseline = admitted_input(original, args.source_job_id)
    config_hash = sha(CONFIG)
    before = live_snapshot(original)
    evidence_root = PROJECT / "artifacts/autonomous-imports"
    output = args.output.resolve() if args.output else evidence_root / "real-recovery" / uuid4().hex / "report.json"
    if not output.is_relative_to(evidence_root.resolve()) or output.exists():
        raise ValueError("Use a fresh report path below artifacts/autonomous-imports; existing evidence is immutable")
    directory = output.parent / (output.stem + "-evidence-" + uuid4().hex[:12])
    receipt = {"status": "not_completed", "evidence_kind": "real_model_controlled_failure_recovery",
               "started_at": datetime.now(timezone.utc).isoformat(), "baseline": baseline,
               "mocks_used": False, "oracle_used": False, "predefined_mapping_supplied": False,
               "gateway": "existing loopback model gateway", "live_import_api_requests": 0,
               "fault_scope": "Only this command's RecoverySession first write_code; production modules unchanged",
               "tool_sha256": sha(__file__), "live_before": before, "evidence_directory": str(directory),
               "actual_implementation": {name: sha(PROJECT / "pipeline/arsia_pipeline" / name)
                   for name in ("agent.py", "isolated_executor.py", "trusted_qa.py", "registry.py", "publication.py")}}
    session = None
    try:
        with test_database(original, receipt) as cfg:
            with TestClient(api.app) as client:
                response = client.post("/jobs", json={"label": "REAL model controlled NameError recovery", "request_id": str(uuid4())})
                response.raise_for_status()
                job_id = response.json()["id"]
                for file in inputs:
                    with Path(file["path"]).open("rb") as handle:
                        response = client.put(f"/jobs/{job_id}/files", params={"filename": file["name"]}, content=handle,
                                              headers={"content-length": str(file["size"])})
                    response.raise_for_status()
                response = client.post(f"/jobs/{job_id}/submit", json={})
                response.raise_for_status()
            with store.connect() as conn:
                job = worker.claim(conn, cfg)
            if not job or str(job["id"]) != job_id:
                raise RuntimeError("Fresh TEST database did not claim its sole owned job")
            if [f["sha256"] for f in job["files"]] != [f["sha256"] for f in inputs]:
                raise RuntimeError("TEST upload hashes differ from the immutable official input")
            receipt["test_uploads_equal_official_inputs"] = True
            for file in job["files"]:
                Path(file["path"]).chmod(0o400)
            work = job["work_dir"] / "agent"
            work.mkdir()
            receipt.update(test_job_id=job_id, test_attempt_id=str(job["attempt_id"]), work_dir=str(work))
            def progress(stage, message, **details):
                store.update_job(job["id"], "processing", message, stage=stage)
                print(json.dumps({"test_job_id": job_id, "stage": stage, **details}), flush=True)
            session = RecoverySession(job["files"], work, {}, progress, lambda: None, job)
            try:
                ready = session.run()
                receipt["recovery"] = evaluate_recovery(saved_steps(session), session.injection, ready["admission"], session.model_input_receipts)
                if not receipt["recovery"]["passed"]:
                    raise RuntimeError("Controlled recovery ordering checks failed; candidate was not published")
                worker.publish(job, ready, lambda: None)
                published = store.get_job(job["id"], internal=True)
                receipt["test_publication"] = {"status": published["status"], "batch_id": str(published["batch_id"]),
                                               "release_id": str(published["release_id"]),
                                               "database_verification": published["result"].get("database_verification")}
                receipt["status"] = "passed" if published["status"] == "succeeded" and published["result"].get("database_verification", {}).get("status") == "pass" else "failed"
            except BaseException as exc:
                receipt["status"] = "blocked" if isinstance(exc, NeedsInput) else "failed"
                receipt["failure"] = {"type": type(exc).__name__, "message": str(exc)[:1000]}
                store.update_job(job["id"], "needs_input" if isinstance(exc, NeedsInput) else "failed", "Real recovery acceptance stopped; evidence retained",
                                 error=receipt["failure"])
                with store.connect() as conn:
                    conn.execute("UPDATE attempts SET status=%s,finished_at=now(),error=%s WHERE id=%s",
                                 (receipt["status"], Jsonb(receipt["failure"]), job["attempt_id"]))
            finally:
                steps = evidence(session, directory)
                receipt["injection"] = session.injection
                receipt["usage"] = session.usage
                receipt["budget"] = session.budget
                receipt.setdefault("recovery", evaluate_recovery(steps, session.injection, (session.validated or {}).get("admission", {}), session.model_input_receipts))
                receipt["original_inputs_unchanged"] = all(sha(f["path"]) == f["sha256"] for f in inputs)
                receipt["test_uploads_unchanged"] = all(sha(f["path"]) == f["sha256"] for f in job["files"])
    except BaseException as exc:
        receipt["status"] = "failed"
        receipt.setdefault("failure", {"type": type(exc).__name__, "message": str(exc)[:1000]})
    finally:
        try:
            receipt["live_after"] = live_snapshot(original)
            receipt["live_database_unchanged"] = receipt["live_after"] == before
            receipt["live_runtime_config_unchanged"] = sha(CONFIG) == config_hash
        except Exception as exc:
            receipt["isolation_verification_error"] = {"type": type(exc).__name__, "message": str(exc)[:1000]}
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        if not all(receipt.get(k) for k in ("live_database_unchanged", "live_runtime_config_unchanged", "original_inputs_unchanged", "test_uploads_unchanged", "test_uploads_equal_official_inputs")):
            receipt["status"] = "failed"
        save(output, receipt)
    return receipt, output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-real-model-recovery", action="store_true", required=True)
    parser.add_argument("--source-job-id", type=UUID, required=True, help="Already admitted actual-source upload to copy byte-for-byte")
    parser.add_argument("--output", type=Path, help="Acceptance report; durable evidence index is written beside it")
    args = parser.parse_args(argv)
    receipt, output = run(args)
    print(json.dumps({"status": receipt["status"], "report": str(output), "usage": receipt.get("usage"),
                      "real_model_attempted": bool(receipt.get("usage", {}).get("model_calls")),
                      "real_model_response_received": bool(receipt.get("recovery", {}).get("successful_model_responses"))}), flush=True)
    return 0 if receipt["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
