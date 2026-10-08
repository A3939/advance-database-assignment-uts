"""PostgreSQL tests of trusted publication and durable autonomous state.

Synthetic candidates isolate the loader; real executor/QA tests separately
establish admission. The fixture uses a new disposable marked database.
"""
import hashlib
import json
from pathlib import Path
import threading
from uuid import uuid4

import pytest

from test_backend import isolated_database, client, queued, claim_specific, result_for
from arsia_pipeline import agent, api, publication, query, registry, store, worker
from arsia_pipeline.errors import ImportCancelled, NeedsInput, ValidationFailure


def row(source, key, year=2024, month=1, role="crash", grain="crash", **extra):
    rawkey = json.dumps([key], separators=(",", ":"))
    value = {"source_id": source, "record_id": rawkey, "resource_role": role,
             "canonical_id": hashlib.sha256(json.dumps([source,grain,role,rawkey], separators=(",", ":")).encode()).hexdigest(),
             "year": year, "month": month, "severity": "fatal", "severity_label": "Fatal", "is_fatal_crash": True,
             "fatalities": 1, "casualties": 2, "row_locator": key, "relations": {}}
    value.update(extra)
    return value


def candidate(job, source, rows, *, units=None, casualties=None, observations=None, mode="snapshot", first="2024-01-01", last="2024-12-31", version="1", dataset_url=None, completeness=None, source_files=None, native_transition=None, version_scope=None):
    units, casualties, observations = units or [], casualties or [], observations or []
    coverage = {"from": first, "to": last}
    grain = "observation" if observations and not rows else "crash"
    contract = {"contract_version": "canonical-v2", "source": {"source_id": source, "publisher": "Official test publisher",
        "dataset_url": dataset_url or "https://example.gov.au/" + source, "jurisdiction": ["SA"], "title": source, "grain": grain, "coverage": coverage},
        "update": {"mode": mode, **coverage}, "resources": [{"role": "crash" if grain == "crash" else "observation", "file_id": "test", "grain": grain, "key": ["ID"], "mapping": {}, "table": {}}],
        "relations": [], "documents": [], "definitions": {}, "evidence": {}}
    if version_scope:
        contract['version_scope']=version_scope
        contract['update']={'mode':'snapshot'}
    code = "def adapt(ctx):\n    pass\n# " + version
    if native_transition:
        contract['resources'][0]['key']=['Crash_Ref_Number']
        contract['source']['jurisdiction']=['QLD']
    summary = {"crash_count": len(rows), "fatal_crash_count": sum(v["is_fatal_crash"] for v in rows) if all(v["is_fatal_crash"] is not None for v in rows) else None,
               "fatalities": sum(v["fatalities"] for v in rows) if all(v["fatalities"] is not None for v in rows) else None,
               "casualties": sum(v["casualties"] for v in rows) if all(v["casualties"] is not None for v in rows) else None,
               "canonical_unit_count": len(units), "canonical_casualty_count": len(casualties), "unit_count": len(units) if units else None,
               "year_from": int(first[:4]), "year_to": int(last[:4]), "raw_record_count": len(rows)+len(units)+len(casualties)+len(observations)}
    if grain == "observation":
        summary.update({k: None for k in query.METRICS})
        summary["observation_count"] = len(observations)
    result = {"source_id": source, "source": contract["source"], "source_contract": contract, "profile_id": "autonomous:" + source,
              "profile_version": "canonical-v2", "update": contract["update"], "coverage": coverage,
              "summary": summary, "qa": [{"code": "TEST_ADMISSION", "status": "pass"}], "severity": [{"code": "fatal", "label": "Fatal", "count": len(rows)}],
              "units": {"status": "available" if units else "unavailable", "rows": []}, "limitations": ["Synthetic loader boundary test"],
              "capabilities": {"crashes": grain == "crash", "units": bool(units)}, "evidence": {"candidate_counts": {"observation": len(observations)}}, "files": []}
    hashes = {}
    for key, name, records in [("canonical_path", "crashes.jsonl", rows), ("units_path", "units.jsonl", units),
                                ("casualties_path", "casualties.jsonl", casualties), ("observations_path", "observations.jsonl", observations)]:
        path = job["work_dir"] / name
        path.write_text("".join(json.dumps(v) + "\n" for v in records))
        result[key] = str(path)
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    result["fingerprint"] = registry.digest_json({"source": source, "artifacts": hashes, "update": contract["update"], "code": code})
    # This synthetic loader fixture stands in for the upstream QA stage; it
    # records the current policy identity so stale-policy tests exercise the
    # actual final gate. It is not a real-source admission claim.
    from arsia_pipeline.trusted_qa import POLICY, trusted_implementation
    result["admission"] = {"status": "admitted", "policy_version": POLICY, "trusted_implementation": trusted_implementation(), "adapter_sha256": hashlib.sha256(code.encode()).hexdigest(),
        "source_contract_sha256": registry.execution_contract_hash(contract), "artifact_hashes": hashes, "image": "test-only",
        "evidence": {"source_identity": [{"url": contract["source"]["dataset_url"], "sha256": "synthetic-loader-boundary"}]}}
    if completeness is not None:
        result['admission']['evidence']['source_completeness'] = completeness
        result['files'] = source_files or []
    if version_scope:
        result['files']=source_files or []
        result['version_scope']=version_scope
    if native_transition:result['admission']['native_transition']=native_transition
    result.update(registry.register(code, contract, result))
    return result


def published(client, source, rows, **opts):
    job = claim_specific(queued(client)["id"])
    result = candidate(job, source, rows, **opts)
    worker.publish(job, result, lambda: None)
    return store.get_job(job["id"]), result


def test_additive_migrations_preserve_existing_data(isolated_database, client):
    job = queued(client)
    store.initialize(isolated_database)
    store.initialize(isolated_database)
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()["n"] == 3
    assert store.get_job(job["id"])["files"]


def test_v2_four_grains_actual_copy_and_role_identity(client):
    source = "four_grains"
    crashes = [row(source, "same", role="crash"), row(source, "same", role="second_crash")]
    unit = row(source, "u", role="unit", grain="unit", relations={"crash": crashes[0]["record_id"]}, crash_id=crashes[0]["record_id"])
    casualty = row(source, "c", role="casualty", grain="casualty", relations={"crash": crashes[0]["record_id"], "unit": unit["record_id"]},
                   crash_id=crashes[0]["record_id"], unit_record_id=unit["record_id"])
    obs = row(source, "o", role="observations", grain="observation", metrics={"crashes": 2})
    job, result = published(client, source, crashes, units=[unit], casualties=[casualty], observations=[obs])
    with store.connect() as conn:
        assert publication.counts(conn, job["batch_id"]) == {"crash": 2, "unit": 1, "casualty": 1, "observation": 1}
    assert job["result"]["database_verification"]["orphan_count"] == 0


@pytest.mark.parametrize("fault", ["artifact", "sample", "contract", "orphan", "duplicate"])
def test_v2_failed_admission_or_copy_never_changes_release(client, fault):
    source = "fault_" + fault
    job = claim_specific(queued(client)["id"])
    rows = [row(source, "a")]
    if fault == "orphan":
        rows[0]["relations"] = {"absent": '["none"]'}
    if fault == "duplicate":
        rows.append(dict(rows[0]))
    result = candidate(job, source, rows)
    if fault == "artifact":
        Path(result["canonical_path"]).write_text("{}\n")
    elif fault == "sample":
        result["admission"]["status"] = "sample_only"
    elif fault == "contract":
        result["source_contract"]["source"]["title"] = "changed"
    before = query.catalog()
    with pytest.raises(Exception):
        worker.publish(job, result, lambda: None)
    assert query.catalog() == before
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM batches WHERE job_id=%s", (job["id"],)).fetchone()["n"] == 0


def test_partition_retains_outside_year_and_children(client):
    source = "partition_source"
    one, two = row(source, "one", 2023), row(source, "two", 2024)
    unit1 = row(source, "u1", role="unit", grain="unit", relations={"crash": one["record_id"]}, crash_id=one["record_id"])
    unit2 = row(source, "u2", role="unit", grain="unit", relations={"crash": two["record_id"]}, crash_id=two["record_id"])
    first, _ = published(client, source, [one, two], units=[unit1, unit2], first="2023-01-01")
    newer = row(source, "three", 2024, fatalities=2, casualties=3)
    second, _ = published(client, source, [two, newer], units=[unit2], mode="partition")
    assert second["result"]["summary"]["crash_count"] == 3
    assert second["result"]["summary"]["fatalities"] == 4
    assert second["result"]["summary"]["canonical_unit_count"] == 2
    assert second["result"]["coverage"]["from"] == "2023-01-01"
    assert query.query(source, first["release_id"], "2023-01-01", "2024-12-31")["summary"]["fatalities"] == 2
    assert query.query(source, second["release_id"], "2023-01-01", "2024-12-31")["summary"]["fatalities"] == 4


def test_incremental_upsert_and_replay_keeps_later_history(client):
    source = "incremental_source"
    first, original = published(client, source, [row(source, "one"), row(source, "two")])
    second, _ = published(client, source, [row(source, "one", fatalities=3, casualties=4)], mode="incremental")
    assert second["result"]["summary"]["crash_count"] == 2
    assert second["result"]["summary"]["fatalities"] == 4
    third, _ = published(client, source, [row(source, "one"), row(source, "two")])
    assert third["status"] == "no_change"
    assert third["release_id"] == second["release_id"]
    assert third["batch_id"] == second["batch_id"]


def test_narrow_observed_snapshot_cannot_remove_old_records(client):
    source = "narrow_source"
    first, _ = published(client, source, [row(source, "one", 2023)], first="2023-01-01")
    job = claim_specific(queued(client)["id"])
    with pytest.raises(NeedsInput, match="remove published records"):
        worker.publish(job, candidate(job, source, [row(source, "two")]), lambda: None)
    assert query.catalog()["release_id"] == first["release_id"]


@pytest.mark.parametrize('same_total', [False, True])
@pytest.mark.parametrize('mode', ['snapshot', 'partition'])
def test_snapshot_cannot_delete_old_membership_using_declared_coverage_or_total(client, same_total, mode):
    source = 'snapshot_membership_' + str(same_total).lower()
    first, _ = published(client, source, [row(source, 'a'), row(source, 'b')])
    job = claim_specific(queued(client)['id'])
    rows = [row(source, 'a')] + ([row(source, 'c')] if same_total else [])
    result = candidate(job, source, rows, version='new', mode=mode)
    result['complete_snapshot'] = True
    with pytest.raises(NeedsInput) as failure:
        worker.publish(job, result, lambda: None)
    assert failure.value.details['code'] == 'SOURCE_MEMBERSHIP_UNPROVEN'
    assert failure.value.details['removals'] == [{'grain': 'crash', 'role': 'crash', 'count': 1}]
    assert query.catalog()['release_id'] == first['release_id']
    with store.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM batches WHERE job_id=%s', (job['id'],)).fetchone()['n'] == 0


def test_snapshot_that_preserves_membership_can_recompute_and_add_records(client):
    source = 'snapshot_preserves_membership'
    published(client, source, [row(source, 'a')])
    job, _ = published(client, source, [row(source, 'a', fatalities=2), row(source, 'b')], version='new')
    assert job['result']['update_membership_verification']['status'] == 'no_records_removed'
    assert job['result']['summary']['crash_count'] == 2


@pytest.mark.parametrize('mode', ['snapshot', 'partition'])
def test_verified_complete_resource_can_authorize_snapshot_removal(client, tmp_path, mode):
    """Loader fixture with an actually rechecked synthetic export proof."""
    from test_source_completeness import export, verify, URL, VERSION
    source = 'verified_snapshot_removal'
    first, _ = published(client, source, [row(source, str(i)) for i in (1, 2, 3, 4)], dataset_url=URL, version='baseline-' + mode)
    assert first['result']['summary']['crash_count'] == 4
    result, file = export(tmp_path)
    proof = {**verify(result, file, tmp_path), 'role': 'crash', 'grain': 'crash'}
    second, _ = published(client, source, [row(source, str(i)) for i in (1, 2, 3)], dataset_url=URL,
                          completeness={'version': VERSION, 'resources': [proof]}, source_files=[file], mode=mode, version='replacement-' + mode)
    assert second['release_id'] != first['release_id']
    assert second['result']['summary']['crash_count'] == 3
    assert second['result']['update_membership_verification']['removals'] == [{'grain': 'crash', 'role': 'crash', 'count': 1}]


@pytest.mark.parametrize('mode', ['snapshot', 'partition', 'incremental'])
def test_changing_mode_cannot_silently_remove_child_membership(client, mode):
    source = 'child_membership_' + mode
    crash = row(source, 'a'); child = row(source, 'u', role='unit', grain='unit', relations={'crash': crash['record_id']}, crash_id=crash['record_id'])
    first, _ = published(client, source, [crash], units=[child])
    job = claim_specific(queued(client)['id'])
    result = candidate(job, source, [row(source, 'a', fatalities=2)], mode=mode, version='new')
    if mode == 'incremental':
        worker.publish(job, result, lambda: None)
        completed = store.get_job(job['id'])
        assert completed['result']['summary']['canonical_unit_count'] == 1
        assert completed['result']['update_membership_verification']['status'] == 'no_records_removed'
        return
    with pytest.raises(NeedsInput) as failure: worker.publish(job, result, lambda: None)
    assert failure.value.details['code'] == 'SOURCE_MEMBERSHIP_UNPROVEN'
    assert failure.value.details['removals'] == [{'grain': 'unit', 'role': 'unit', 'count': 1}]
    assert query.catalog()['release_id'] == first['release_id']


def test_old_complete_export_cannot_delete_a_later_published_source_version(client, tmp_path):
    from test_source_completeness import export, verify, URL, VERSION
    result, file = export(tmp_path)
    proof = {**verify(result, file, tmp_path), 'role': 'crash', 'grain': 'crash'}
    source = 'verified_snapshot_removal'
    first, _ = published(client, source, [row(source, str(i)) for i in (1, 2, 3, 4)], dataset_url=URL, version='freshness-baseline')
    job = claim_specific(queued(client)['id'])
    replacement = candidate(job, source, [row(source, str(i)) for i in (1, 2, 3)], dataset_url=URL,
                            completeness={'version': VERSION, 'resources': [proof]}, source_files=[file], version='stale-export')
    with pytest.raises(NeedsInput) as failed: worker.publish(job, replacement, lambda: None)
    assert failed.value.details['code'] == 'SOURCE_MEMBERSHIP_UNPROVEN'
    assert query.catalog()['release_id'] == first['release_id']
    with store.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM batches WHERE job_id=%s', (job['id'],)).fetchone()['n'] == 0


def test_v2_cancel_at_publish_retains_release(client):
    first = query.catalog()
    source = "cancel_v2"
    job = claim_specific(queued(client)["id"])
    result = candidate(job, source, [row(source, "a")])
    def cancel():
        with store.connect() as conn:
            conn.execute("UPDATE jobs SET status='cancel_requested' WHERE id=%s", (job["id"],))
        raise ImportCancelled()
    with pytest.raises(ImportCancelled):
        worker.publish(job, result, cancel)
    assert query.catalog() == first


def test_query_months_unknown_zero_and_pinned_source_coverage(client):
    source = "unknown_metrics"
    first, _ = published(client, source, [row(source, "a", fatalities=None, casualties=None)])
    catalog = query.catalog(first["release_id"])
    assert next(s for s in catalog["sources"] if s["source_id"] == source)["capabilities"]["monthly"]
    value = query.query(source, first["release_id"], "2024-02-01", "2024-02-29")
    # The fixture declares an observed extent, without a complete-period proof.
    # Actual rows remain queryable, but an unobserved month cannot become zero.
    assert value["summary"] == {"crash_count": None, "fatal_crash_count": None, "fatalities": None, "casualties": None}
    assert value["coverage"] == {"from": "2024-01-01", "to": "2024-12-31", "complete": False}
    outside = query.query(source, first["release_id"], "2025-01-01", "2025-01-31")
    assert outside["availability"] == "no_results" and all(v is None for v in outside["summary"].values())


def test_annual_observation_rejects_partial_month_and_never_synthesizes_crash(client):
    source = "annual_observations"
    obs = row(source, "o", month=None, grain="observation", role="observation", metrics={"fatalities": 7})
    first, _ = published(client, source, [], observations=[obs])
    partial = query.query(source, first["release_id"], "2024-02-01", "2024-02-29")
    assert partial["availability"] == "unsupported"
    full = query.query(source, first["release_id"], "2024-01-01", "2024-12-31")
    assert full["summary"]["crash_count"] is None and full["summary"]["fatalities"] == 7
    assert len(full["observations"]) == 1
    with store.connect() as conn:
        assert publication.counts(conn, first["batch_id"])["crash"] == 0


def test_registry_rejects_sample_and_changed_code(client):
    source = "registry_guards"
    job = claim_specific(queued(client)["id"])
    value = candidate(job, source, [row(source, "a")])
    with pytest.raises(ValidationFailure):
        registry.register("changed code", value["source_contract"], value)
    value["admission"]["status"] = "sample_only"
    with pytest.raises(ValidationFailure):
        registry.register("def adapt(ctx):\n    pass\n# 1", value["source_contract"], value)


def test_agent_tool_loop_persists_evidence_and_correction_state(client, monkeypatch):
    job = claim_specific(queued(client)["id"])
    work = job["work_dir"] / "agent"
    work.mkdir()
    session = agent.AgentSession(job["files"], work, {}, lambda *a,**k: None, lambda: None, job)
    calls = iter([
        {"model_policy_sha256":"a"*64,"sdk_contract_sha256":"b"*64,"output": [{"type": "function_call", "name": "write_adapter", "call_id": "c1", "arguments": json.dumps({"code": "def adapt(ctx):\n    pass", "reason": "inspect"})}]},
        {"output": [{"type": "function_call", "name": "request_missing_information", "call_id": "c2", "arguments": json.dumps({"message": "No official definition found", "questions": ["Provide official source URL"]})}]},
    ])
    monkeypatch.setattr(agent, "gateway", lambda *args: next(calls))
    with pytest.raises(NeedsInput, match="official"):
        session.run()
    with store.connect() as conn:
        saved = conn.execute("SELECT * FROM agent_sessions WHERE id=%s", (session.id,)).fetchone()
        steps = conn.execute("SELECT * FROM agent_steps WHERE session_id=%s", (session.id,)).fetchall()
    assert saved["model_calls"] == 2 and saved["tool_calls"] == 2
    assert saved["checkpoint"]["code"].startswith("def adapt")
    assert len(steps) == 4
    model_step = next(step for step in steps if step["kind"] == "model" and step["result"].get("model_policy_sha256"))
    assert model_step["result"]["model_policy_sha256"] == "a"*64
    assert model_step["result"]["sdk_contract_sha256"] == "b"*64
    restored = agent.AgentSession(job["files"], work, {"answers": "Official URL supplied"}, lambda *a,**k: None, lambda: None, job)
    assert restored.code == session.code and restored.id == session.id
    assert restored.usage["model_calls"] == 2


def test_test_config_cannot_overwrite_live_runtime(isolated_database):
    from arsia_pipeline.config import CONFIG
    from arsia_pipeline import dev
    before = CONFIG.read_bytes()
    with pytest.raises(RuntimeError, match="alternate"):
        dev.save(isolated_database)
    assert CONFIG.read_bytes() == before


def test_gateway_missing_token_has_no_config_side_effect(monkeypatch):
    from arsia_pipeline.config import CONFIG
    before = CONFIG.read_bytes()
    monkeypatch.setattr(agent, "read_config", lambda: {})
    with pytest.raises(NeedsInput, match="gateway"):
        agent.gateway([], [], lambda: None)
    assert CONFIG.read_bytes() == before


def test_contract_correction_and_full_evidence_hash_used_in_executor(client, monkeypatch):
    from arsia_pipeline import isolated_executor
    from arsia_pipeline import trusted_qa
    monkeypatch.setattr(trusted_qa, "validate_contract", lambda *args, **kwargs: {})
    monkeypatch.setattr(trusted_qa, "_proof", lambda *args, **kwargs: {})
    job = claim_specific(queued(client)["id"])
    work = job["work_dir"] / "agent"; work.mkdir()
    session = agent.AgentSession(job["files"], work, {}, lambda *a,**k: None, lambda: None, job)
    first = {"contract_version": "canonical-v2", "source": {"source_id": "x"}, "resources": []}
    session.execute_tool("set_source_contract", {"contract": first})
    assert session.usage["correction_count"] == 0
    session.execute_tool("set_source_contract", {"contract": {**first, "definitions": {"fatalities": "unsupported"}}})
    assert session.usage["correction_count"] == 1
    session.documents["doc"] = {"document_id": "doc", "text_path": str(work/"text.txt"), "sha256": "a"}
    def executor(code, files, work_dir, **kwargs):
        assert kwargs["source_contract"]["documents"][0]["document_id"] == "doc"
        return {"run_id": "run-1", "status": "succeeded", "code_sha256": hashlib.sha256(code.encode()).hexdigest(),
                "contract_sha256": registry.execution_contract_hash(kwargs["source_contract"]), "usage": {"wall_seconds": 5}}
    monkeypatch.setattr(isolated_executor, "run_python", executor)
    session.execute_tool("run_python", {"code": "def adapt(ctx):\n    pass", "mode": "sample"})
    assert session.usage["compute_seconds"] == 5
    assert session.runs["run-1"]["contract_sha256"] == registry.execution_contract_hash({**session.contract, "documents": list(session.documents.values())})


def session_for(client):
    job = claim_specific(queued(client)["id"])
    work = job["work_dir"] / "agent"; work.mkdir()
    return agent.AgentSession(job["files"], work, {}, lambda *a,**k: None, lambda: None, job)


def test_executor_transform_environment_failure_is_a_system_blocker(client, monkeypatch):
    from arsia_pipeline import isolated_executor, trusted_qa
    from arsia_pipeline.capability_preflight import requires_system_change
    session = session_for(client)
    session.contract = {"contract_version":"canonical-v2", "resources":[]}
    session.write_code("def adapt(ctx):\n    pass", "Test environment failure")
    monkeypatch.setattr(trusted_qa,"validate_contract",lambda *a,**kw:{})
    monkeypatch.setattr(trusted_qa,"_proof",lambda *a,**kw:{})
    result = {"run_id":"environment-failure", "status":"failed", "image":"sha256:test",
        "error":{"type":"TransformError", "kind":"environment_dependency", "code":"TRANSFORM_RUNTIME_MISMATCH",
                 "message":"Host and executor selected different coordinate operations.", "details":{"role":"crash"}}}
    monkeypatch.setattr(isolated_executor,"run_python",lambda *a,**kw:result)
    with pytest.raises(NeedsInput) as error:session.execute_tool("run_adapter",{"mode":"sample"})
    assert requires_system_change(error.value.details)
    assert error.value.questions == []
    assert error.value.details['blockers'][0]['code'] == 'TRANSFORM_RUNTIME_MISMATCH'
    assert session.runs['environment-failure']['status'] == 'failed'
    assert session.validated is None and session.registered is None


def tool_call(name, arguments, number):
    return {"output": [{"type": "function_call", "name": name, "call_id": "call-" + str(number), "arguments": json.dumps(arguments)}]}


def test_model_timeout_is_durable_and_does_not_reexecute_business_attempt(client, monkeypatch):
    session = session_for(client)
    monkeypatch.setattr(session, "transport_backoff", lambda failures: None)
    def timeout(*args):
        raise TimeoutError("Synthetic model transport timeout")
    monkeypatch.setattr(agent, "gateway", timeout)
    with pytest.raises(NeedsInput, match="model service"):
        session.run()
    with store.connect() as conn:
        saved = conn.execute("SELECT * FROM agent_sessions WHERE id=%s", (session.id,)).fetchone()
        attempts = conn.execute("SELECT count(*) AS n FROM attempts WHERE job_id=%s", (session.job["id"],)).fetchone()["n"]
        failed = conn.execute("SELECT count(*) AS n FROM agent_steps WHERE session_id=%s AND status='failed'", (session.id,)).fetchone()["n"]
    assert saved["model_calls"] == 3 and attempts == 1 and failed == 3


def test_cancel_stops_agent_without_further_model_or_tool_calls(client, monkeypatch):
    session = session_for(client)
    calls = []
    def cancelled(input_items, tools, check, settings):
        calls.append(1)
        raise ImportCancelled()
    monkeypatch.setattr(agent, "gateway", cancelled)
    with pytest.raises(ImportCancelled):
        session.run()
    with store.connect() as conn:
        saved = conn.execute("SELECT * FROM agent_sessions WHERE id=%s", (session.id,)).fetchone()
    assert len(calls) == 1 and saved["model_calls"] == 1 and saved["tool_calls"] == 0
    assert saved["status"] == "cancelled"
    assert session.ready is None


def test_adapter_corrections_are_durable_separate_from_worker_attempt(client, monkeypatch):
    session = session_for(client)
    responses = iter([
        tool_call("write_adapter", {"code": "def adapt(ctx):\n    missing()", "reason": "Initial hypothesis"}, 1),
        tool_call("patch_adapter", {"old": "absent", "new": "pass", "reason": "Deliberate unmatched patch diagnostic"}, 2),
        tool_call("patch_adapter", {"old": "missing()", "new": "pass", "reason": "Correct observed implementation error"}, 3),
        tool_call("request_missing_information", {"message": "Official metric definition is not available", "questions": ["Supply the official definition URL"]}, 4),
    ])
    monkeypatch.setattr(agent, "gateway", lambda *args: next(responses))
    with pytest.raises(NeedsInput):
        session.run()
    with store.connect() as conn:
        saved = conn.execute("SELECT * FROM agent_sessions WHERE id=%s", (session.id,)).fetchone()
        failed = conn.execute("SELECT * FROM agent_steps WHERE session_id=%s AND status='failed'", (session.id,)).fetchall()
    assert saved["correction_count"] == 1 and session.job["attempt"] == 1
    assert saved["checkpoint"]["code"] == "def adapt(ctx):\n    pass"
    assert failed[0]["name"] == "patch_adapter"
    assert len(list((session.work_dir/"adapter-versions").glob("*.py"))) == 2


def test_crash_recovery_replays_pending_tool_and_keeps_session_identity(client, monkeypatch):
    session = session_for(client)
    call = tool_call("write_adapter", {"code": "def adapt(ctx):\n    pass", "reason": "Durable pending tool"}, 1)["output"][0]
    session.messages = [call]
    session.pending = [call]
    session.step("tool", "write_adapter", json.loads(call["arguments"]))
    session.persist()
    # Simulate scheduler recovery after lock-owning process loss in this
    # disposable DB. It never touches the running laboratory's jobs.
    with store.connect() as conn:
        worker.recover_abandoned(conn)
    new_job = claim_specific(session.job["id"])
    work = new_job["work_dir"]/"agent"; work.mkdir()
    restored = agent.AgentSession(new_job["files"], work, {}, lambda *a,**k: None, lambda: None, new_job)
    monkeypatch.setattr(agent, "gateway", lambda *args: tool_call("request_missing_information", {"message": "Missing authoritative coverage", "questions": ["Provide coverage evidence"]}, 2))
    with pytest.raises(NeedsInput):
        restored.run()
    assert restored.id == session.id and restored.code == "def adapt(ctx):\n    pass"
    assert new_job["attempt"] == 2 and restored.runs == {}
    outputs = {m.get("call_id") for m in restored.messages if m.get("type") == "function_call_output"}
    assert "call-1" in outputs
    with store.connect() as conn:
        status = conn.execute("SELECT status FROM attempts WHERE id=%s", (session.job["attempt_id"],)).fetchone()["status"]
        old_step = conn.execute("SELECT status FROM agent_steps WHERE attempt_id=%s", (session.job["attempt_id"],)).fetchone()["status"]
    assert status == "interrupted"
    assert old_step == "interrupted"


def test_sample_candidate_runs_independent_qa_but_cannot_register(client, monkeypatch):
    from arsia_pipeline import trusted_qa
    session = session_for(client)
    session.code = "def adapt(ctx):\n    pass"
    session.contract = {"contract_version": "canonical-v2", "source": {"source_id": "sample-source"}}
    contract = {**session.contract, "documents": []}
    session.runs["sample"] = {"run_id": "sample", "mode": "sample", "code_sha256": hashlib.sha256(session.code.encode()).hexdigest(),
                              "contract_sha256": registry.execution_contract_hash(contract)}
    seen = []
    def qa(*args, **kwargs):
        seen.append(True)
        return {"summary": {"crash_count": 1}, "qa": [{"status": "pass"}], "admission": {"status": "sample_only"}}
    monkeypatch.setattr(trusted_qa, "validate_candidate", qa)
    output = session.execute_tool("validate_candidate", {"run_id": "sample"})
    assert seen and output["status"] == "sample_only" and session.validated is None
    with pytest.raises(ValueError, match="full-data QA"):
        session.execute_tool("register_adapter", {})


def test_model_context_compaction_retains_call_output_pairing(client):
    session = session_for(client)
    messages = []
    for number in range(130):
        call = tool_call("inspect_bundle", {}, number)["output"][0]
        messages.extend([call, {"type": "function_call_output", "call_id": call["call_id"], "output": json.dumps({"large_diagnostic": "x"*18000})}])
    session.messages = messages
    wire = session.wire_messages()
    calls = {m["call_id"] for m in wire if m.get("type") == "function_call"}
    outputs = {m["call_id"] for m in wire if m.get("type") == "function_call_output"}
    assert calls == outputs and len(wire) < 175
    assert len(session.messages) == 260
    assert len(json.dumps(wire)) < 1900000


def test_recursive_response_masking_removes_host_locations():
    from arsia_pipeline.config import ROOT
    result = agent.safe({"__documents": [{"path": "secret"}], "evidence": {"receipt_path": "secret", "message": str(ROOT)+"/private.txt"}, "data": [{"code_path": "secret", "n": 3}]})
    assert "__documents" not in result and result["data"] == [{"n": 3}]
    assert str(ROOT) not in json.dumps(result) and "receipt_path" not in json.dumps(result)


def test_repeated_failure_pause_has_no_unpaired_tool_call_on_retry(client, monkeypatch):
    session = session_for(client)
    index = iter(range(1, 10))
    monkeypatch.setattr(agent, "gateway", lambda *args: tool_call("patch_adapter", {"old": "absent", "new": "pass", "reason": "Deliberate repeated diagnostic"}, next(index)))
    with pytest.raises(NeedsInput, match="Repeated adapter"):
        session.run()
    calls = {m["call_id"] for m in session.messages if m.get("type") == "function_call"}
    outputs = {m["call_id"] for m in session.messages if m.get("type") == "function_call_output"}
    assert len(calls) == 4 and calls == outputs and session.pending == []
    with store.connect() as conn:
        saved = conn.execute("SELECT status,checkpoint FROM agent_sessions WHERE id=%s", (session.id,)).fetchone()
    assert saved["status"] == "needs_input" and not saved["checkpoint"]["pending"]


def test_cancel_paused_agent_sets_job_and_session_terminal(client):
    session = session_for(client)
    store.update_job(session.job["id"], "needs_input", "Synthetic missing evidence")
    session.persist("needs_input")
    response = client.post("/jobs/" + str(session.job["id"]) + "/cancel")
    assert response.status_code == 200 and response.json()["status"] == "cancelled"
    with store.connect() as conn:
        assert conn.execute("SELECT status FROM agent_sessions WHERE id=%s", (session.id,)).fetchone()["status"] == "cancelled"


def test_role_specific_unit_query_does_not_duplicate_matching_raw_keys(client):
    source = "query_role_units"
    first, second = row(source, "same", role="first"), row(source, "same", role="second")
    unit = row(source, "unit", role="unit", grain="unit", unit_type="car", relations={"first": first["record_id"]}, crash_id=first["record_id"])
    job, _ = published(client, source, [first, second], units=[unit])
    response = query.query(source, job["release_id"], "2024-01-01", "2024-12-31")
    assert response["units"]["rows"] == [{"unit_type": "car", "count": 1}]
    assert response["summary"]["crash_count"] == 2


def test_adapter_version_changes_with_trusted_sdk_image(client):
    source = "image_version"
    job = claim_specific(queued(client)["id"])
    value = candidate(job, source, [row(source, "a")])
    original = value["adapter_version_id"]
    code = "def adapt(ctx):\n    pass\n# 1"
    value["admission"]["image"] = "sha256:new-trusted-sdk-image"
    newer = registry.register(code, value["source_contract"], value)
    assert newer["adapter_version_id"] != original
    assert newer["source_version_id"] == value["source_version_id"]
    with store.connect() as conn:
        rows = conn.execute("SELECT id,dependency_version FROM adapter_versions WHERE source_id=%s ORDER BY created_at", (source,)).fetchall()
    assert len(rows) == 2
    assert rows[0]["dependency_version"]["image"] == "test-only"
    assert rows[1]["dependency_version"]["image"] == "sha256:new-trusted-sdk-image"


def test_active_wall_budget_persists_across_recovery_without_counting_user_pause(client, monkeypatch):
    now = [100.0]
    monkeypatch.setattr(agent.time, "monotonic", lambda: now[0])
    session = session_for(client)
    session.budget["wall_seconds"] = 10
    now[0] = 106
    session.cancel_check()
    session.persist("needs_input")
    with store.connect() as conn:
        elapsed = conn.execute("SELECT checkpoint->>'active_wall_seconds' AS elapsed FROM agent_sessions WHERE id=%s", (session.id,)).fetchone()["elapsed"]
    assert float(elapsed) == 6
    now[0] = 10000  # User left the paused task for a long time.
    resumed = agent.AgentSession(session.files, session.work_dir, {}, lambda *a,**k: None, lambda: None, session.job)
    resumed.budget["wall_seconds"] = 10
    assert resumed.active_wall_seconds() == 6
    now[0] = 10004
    with pytest.raises(NeedsInput, match="cumulative active-time"):
        resumed.check_budget()
    resumed.persist("needs_input")
    with store.connect() as conn:
        elapsed = conn.execute("SELECT checkpoint->>'active_wall_seconds' AS elapsed FROM agent_sessions WHERE id=%s", (session.id,)).fetchone()["elapsed"]
    assert float(elapsed) == 10


def test_adapter_version_tracks_trusted_validator_implementation(client):
    source = "validator_version"
    job = claim_specific(queued(client)["id"])
    value = candidate(job, source, [row(source, "a")])
    original = value["adapter_version_id"]
    value["admission"]["trusted_implementation"] = {"canonical.py": "one", "trusted_qa.py": "two"}
    newer = registry.register("def adapt(ctx):\n    pass\n# 1", value["source_contract"], value)
    assert newer["adapter_version_id"] != original
    assert newer["source_version_id"] == value["source_version_id"]
    with store.connect() as conn:
        dependency = conn.execute("SELECT dependency_version FROM adapter_versions WHERE id=%s", (newer["adapter_version_id"],)).fetchone()["dependency_version"]
    assert dependency["trusted_implementation"] == value["admission"]["trusted_implementation"]


def test_intermittent_gateway_errors_reset_after_each_success(client, monkeypatch):
    session = session_for(client)
    backoffs = []
    monkeypatch.setattr(session, "transport_backoff", lambda count: backoffs.append(count))
    responses = iter([TimeoutError("synthetic"),
        tool_call("write_adapter", {"code": "def adapt(ctx):\n    pass", "reason": "Initial version"}, 1),
        TimeoutError("synthetic"),
        tool_call("read_adapter", {}, 2),
        TimeoutError("synthetic"),
        tool_call("request_missing_information", {"message": "Expected final evidence question", "questions": ["Provide official evidence"]}, 3)])
    def gateway(*args):
        value = next(responses)
        if isinstance(value, Exception):
            raise value
        return value
    monkeypatch.setattr(agent, "gateway", gateway)
    with pytest.raises(NeedsInput, match="Expected final"):
        session.run()
    assert backoffs == [1, 1, 1] and session.consecutive_gateway_failures == 0
    assert session.usage["model_calls"] == 6


def test_full_execution_requires_sample_qa_and_resets_after_contract_or_code_change(client, monkeypatch):
    from arsia_pipeline import isolated_executor, trusted_qa
    session = session_for(client)
    session.contract = {"contract_version": "canonical-v2", "source": {"source_id": "test"}}
    session.write_code("def adapt(ctx):\n    pass", "Initial version")
    monkeypatch.setattr(trusted_qa, "validate_contract", lambda *args, **kwargs: {})
    proof = []
    monkeypatch.setattr(trusted_qa, "_proof", lambda *args, **kwargs: proof.append(True) or {})
    executions = []
    def run(code, files, work, **kwargs):
        mode = kwargs["mode"]; executions.append(mode)
        return {"run_id": str(len(executions)), "mode": mode, "status": "succeeded", "image": "image",
                "code_sha256": hashlib.sha256(code.encode()).hexdigest(), "contract_sha256": registry.execution_contract_hash(kwargs["source_contract"]), "usage": {}}
    monkeypatch.setattr(isolated_executor, "run_python", run)
    monkeypatch.setattr(trusted_qa, "validate_candidate", lambda *args,**kwargs: {"summary": {}, "qa": [], "admission": {"status": "sample_only"}})
    with pytest.raises(ValueError, match="independently validate a sample"):
        session.execute_tool("run_adapter", {"mode": "full"})
    sample = session.execute_tool("run_adapter", {"mode": "sample"})
    with pytest.raises(ValueError, match="independently validate a sample"):
        session.execute_tool("run_adapter", {"mode": "full"})
    session.execute_tool("validate_candidate", {"run_id": sample["run_id"]})
    session.execute_tool("run_adapter", {"mode": "full"})
    assert executions == ["sample", "full"] and proof == [True, True]
    session.execute_tool("patch_adapter", {"old": "pass", "new": "return None", "reason": "Correct implementation"})
    with pytest.raises(ValueError, match="independently validate a sample"):
        session.execute_tool("run_adapter", {"mode": "full"})


def test_contract_preflight_rejects_invalid_identity_and_unknown_doc_ids(client, monkeypatch):
    from arsia_pipeline import trusted_qa
    session = session_for(client)
    with pytest.raises(ValidationFailure):
        session.execute_tool("set_source_contract", {"contract": {"contract_version":"canonical-v2", "source":{"source_id":"ACT:bad"}}})
    assert session.contract == {}
    monkeypatch.setattr(trusted_qa, "validate_contract", lambda *args: {})
    session.documents = {"document-real-complete-id": {"document_id":"document-real-complete-id"}}
    with pytest.raises(NeedsInput) as error:
        session.execute_tool("set_source_contract", {"contract": {"contract_version":"canonical-v2", "source":{}, "evidence":{"date":[{"document_id":"short-wrong-id", "quote":"some source text"}]}}})
    assert error.value.details["available_document_ids"] == ["document-real-complete-id"]
    assert session.contract == {}


def test_gateway_preserves_only_protocol_diagnostics_and_shutdowns_socket(monkeypatch):
    class Sock:
        closed = False
        def shutdown(self, mode): self.closed = True
    class Response:
        status = 503
        def read(self, size): return b'{"diagnostics":{"type":"APIError","provider_status":503,"code":"overloaded","message":"secret body","param":"bad value with spaces"}}'
    class Connection:
        def __init__(self, *args, **kwargs): self.sock = sock
        def request(self, *args, **kwargs): pass
        def getresponse(self): return Response()
        def close(self): pass
    sock = Sock()
    monkeypatch.setattr(agent, "read_config", lambda: {"agent_gateway_token": "synthetic-non-secret-test-token", "instance_id":"a"*32})
    monkeypatch.setattr(agent.http.client, "HTTPConnection", Connection)
    with pytest.raises(agent.GatewayFailure) as error:
        agent.gateway([], [], lambda: None, {**agent.policy(),"request_task_id":"0c846645-e379-4551-9c16-d102e566227f"})
    assert error.value.diagnostics == {"http_status":503,"type":"APIError","provider_status":503,"code":"overloaded"}
    assert sock.closed


def test_lightweight_progress_has_real_counts_without_code_or_arguments(client):
    session = session_for(client)
    step = session.step("tool", "run_adapter", {"mode":"sample", "code":"SECRET_CODE_NEVER_EXPOSE"})
    session.finish_step(step, {"run_id":"sample-one", "mode":"sample", "status":"succeeded"})
    qa = session.step("tool", "validate_candidate", {"run_id":"sample-one"})
    session.finish_step(qa, {"status":"sample_only", "qa":[{"status":"pass"}], "admission":{"status":"sample_only"}})
    value = client.get("/jobs/"+str(session.job["id"])).json()["agent"]
    assert value["phase"] == "sample_qa"
    assert value["checks"] == {"sample_runs":1,"full_runs":0,"qa_checks":1,
                               'qa_passed':1,'qa_failed':0,'qa_blocked':0,'qa_running':0,'qa_interrupted':0,'qa_unclassified':0}
    assert len(value["latest_steps"]) == 2
    encoded = json.dumps(value)
    assert "SECRET_CODE" not in encoded and "arguments" not in encoded and "run_adapter" not in encoded


def test_progress_counts_blocked_failed_interrupted_and_unverified_qa_attempts(client):
    session = session_for(client)
    for status, result in [('needs_evidence', {'message':'Missing field proof'}), ('paused', {'message':'System capability'}),
                           ('failed', {'message':'Wrong total'}), ('interrupted', {}), ('cancelled', {}),
                           ('succeeded', {'admission':{'status':'admitted'}}), ('succeeded', {'qa':[]})]:
        step = session.step('tool', 'validate_candidate', {'run_id':'fixture'})
        session.finish_step(step, result, status)
    session.step('tool', 'validate_candidate', {'run_id':'still-running'})
    checks = client.get('/jobs/'+str(session.job['id'])).json()['agent']['checks']
    assert checks == {'sample_runs':0, 'full_runs':0, 'qa_checks':8,
                      'qa_passed':1, 'qa_failed':1, 'qa_blocked':2, 'qa_running':1, 'qa_interrupted':2, 'qa_unclassified':1}


def test_single_observation_exposes_its_real_yearly_value(client):
    source = "single_observation_trend"
    value = row(source,"a",grain="observation",role="observation",month=None,metrics={"fatalities":7})
    job, _ = published(client,source,[],observations=[value])
    result = query.query(source,job["release_id"],"2024-01-01","2024-12-31")
    assert result["yearly"] == [{"year":2024,"crash_count":None,"fatal_crash_count":None,"fatalities":7,"casualties":None}]
    assert result["monthly"] == []


def test_gateway_cancel_unblocks_its_http_thread_without_waiting_for_timeout(monkeypatch):
    released, finished = threading.Event(), threading.Event()
    class Sock:
        def shutdown(self, mode): released.set()
    class Connection:
        def __init__(self, *args, **kwargs): self.sock = Sock()
        def request(self, *args, **kwargs): pass
        def getresponse(self):
            try:
                released.wait(3)
                raise RuntimeError("Synthetic cancelled transport")
            finally:
                finished.set()
        def close(self): pass
    monkeypatch.setattr(agent, "read_config", lambda: {"agent_gateway_token":"synthetic-test", "instance_id":"a"*32})
    monkeypatch.setattr(agent.http.client, "HTTPConnection", Connection)
    def cancel():
        raise ImportCancelled()
    with pytest.raises(ImportCancelled):
        agent.gateway([], [], cancel, {**agent.policy(),"request_task_id":"0c846645-e379-4551-9c16-d102e566227f"})
    assert released.is_set() and finished.wait(1)


def test_failed_run_inspection_uses_trusted_projection_diagnostic(client, monkeypatch):
    from arsia_pipeline import source_diagnostics
    session = session_for(client)
    session.contract = {"source":{"source_id":"diagnostic"}}
    session.runs["failed"] = {"run_id":"failed","status":"failed","mode":"sample"}
    seen = []
    def diagnostic(contract, files, **kwargs):
        seen.append((contract,files,kwargs["mode"]))
        return {"status":"mapping_error","diagnostic_only":True,"issue":{"type":"ContractError","message":"Unregistered source severity category"}}
    monkeypatch.setattr(source_diagnostics, "diagnose_projection", diagnostic)
    result = session.execute_tool("inspect_run", {"run_id":"failed"})
    assert seen and result["projection_diagnostic"]["diagnostic_only"] is True
    assert result["projection_diagnostic"]["issue"]["message"] == "Unregistered source severity category"
    assert session.validated is None


def test_official_identity_conflict_returns_existing_source_id_without_duplicate(client):
    first_job = claim_specific(queued(client)["id"])
    first = candidate(first_job,"identity_first",[row("identity_first","a")])
    second_job = claim_specific(queued(client)["id"])
    second = candidate(second_job,"identity_second",[row("identity_second","b")])
    contract = second["source_contract"]
    contract["source"]["dataset_url"] = first["source_contract"]["source"]["dataset_url"]
    second["admission"]["source_contract_sha256"] = registry.execution_contract_hash(contract)
    second["admission"]["evidence"] = first["admission"]["evidence"]
    with pytest.raises(NeedsInput) as error:
        registry.register("def adapt(ctx):\n    pass\n# 1",contract,second)
    assert error.value.details["existing_source_id"] == "identity_first"
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM source_identities WHERE identity_key=%s", (error.value.details["dataset_identity"]["identity_key"],)).fetchone()["n"] == 1


def test_identity_backfill_protects_adapters_registered_before_migration(client):
    from arsia_pipeline.source_identity import backfill_identities, canonical_source_identity
    job = claim_specific(queued(client)["id"])
    value = candidate(job,"legacy_identity_binding",[row("legacy_identity_binding","a")])
    identity = canonical_source_identity(value,value["source_contract"])
    with store.connect() as conn:
        conn.execute("DELETE FROM source_identities WHERE identity_key=%s",(identity["identity_key"],))
        with conn.transaction():
            backfill_identities(conn)
        stored = conn.execute("SELECT source_id FROM source_identities WHERE identity_key=%s",(identity["identity_key"],)).fetchone()
    assert stored["source_id"] == "legacy_identity_binding"


def test_registry_empty_string_search_is_unfiltered(client):
    job = claim_specific(queued(client)["id"])
    value = candidate(job,"blank_registry_query",[row("blank_registry_query","a")])
    assert any(row["source_id"] == "blank_registry_query" for row in registry.search(source_id="  ",jurisdiction=""))


def test_compactor_stays_near_60kb_and_preserves_exact_citation_spans(client):
    session = session_for(client)
    session.code = "def adapt(ctx):\n    pass"
    session.contract = {"source":{"source_id":"document_test"}}
    session.runs = {"sample-a":{"run_id":"sample-a","mode":"sample","status":"succeeded","code_sha256":"code","contract_sha256":"contract"}}
    session.sample_gate = {"code_sha256":"code","contract_sha256":"contract","image":"trusted-image"}
    session.validated = {"summary":{"crash_count":12},"qa":[{"code":"QA01","status":"pass"}],"admission":{"status":"admitted"}}
    session.registered = {"source_version_id":"source-version","adapter_version_id":"adapter-version"}
    session.documents = {"complete-document-id":{"file_id":"public-doc","sha256":"document-sha"}}
    span = {"document_id":"complete-document-id","quote":"Exact official definition for fatalities.","start":120,"end":160}
    session.messages = []
    for index in range(30):
        call = tool_call("read_document",{"file_id":"public-doc","search":"fatalities"},index)["output"][0]
        result = {"document_id":"complete-document-id","citation_spans":[span],"text":"unneeded archived text "*5000}
        session.messages += [call,{"type":"function_call_output","call_id":call["call_id"],"output":json.dumps(result)}]
    wire = session.wire_messages()
    assert len(json.dumps(wire,ensure_ascii=False).encode()) <= 60000
    state = json.loads(wire[0]["content"])
    assert state["recent_runs"][0]["run_id"] == "sample-a"
    assert state["sample_gate"] == session.sample_gate
    assert state["validated_candidate"]["summary"]["crash_count"] == 12
    assert state["registered"]["adapter_version_id"] == "adapter-version"
    assert state["document_index"][0]["file_id"] == "public-doc"
    assert state["next_action"]["tool"] == "publish_candidate"
    assert state["remaining_budget"]["model_calls"] == session.budget["model_calls"]
    calls = [v for v in wire if v.get("type")=="function_call"]
    outputs = [v for v in wire if v.get("type")=="function_call_output"]
    assert len(calls) == len(outputs) <= 8
    assert all(json.loads(v["output"])["citation_spans"] == [span] for v in outputs)
    assert len(session.messages) == 60


def test_rate_limit_backoff_uses_30_to_60_seconds_and_persists_wait_state(client, monkeypatch):
    session = session_for(client)
    session.last_gateway_diagnostics = {"provider_status":429,"retry_after_seconds":40}
    now=[0.]
    monkeypatch.setattr(agent.time,"monotonic",lambda:now[0])
    monkeypatch.setattr(agent.time,"sleep",lambda seconds:now.__setitem__(0,now[0]+seconds))
    monkeypatch.setattr(session,"cancel",lambda:None)
    states=[]
    original=session.persist
    def persist(status="investigating"):
        states.append(status); original(status)
    monkeypatch.setattr(session,"persist",persist)
    session.transport_backoff(1)
    assert round(now[0]) == 40 and states == ["waiting_for_model","investigating"]
    session.transport_backoff(2)
    assert round(now[0]) == 100


@pytest.mark.parametrize('mode',['partition','incremental'])
@pytest.mark.parametrize('change',['role','grain','key'])
def test_update_identity_drift_rejected_before_copy_and_release_switch(client,mode,change):
    source = f'identity_drift_{mode}_{change}'
    original,_ = published(client,source,[row(source,'same-raw-key')])
    job = claim_specific(queued(client)['id'])
    value = candidate(job,source,[row(source,'same-raw-key',fatalities=3,casualties=4)],mode=mode)
    contract = value['source_contract']
    contract['resources'][0][change] = {'role':'renamed_role','grain':'observation','key':['different_key_field']}[change]
    value['admission']['source_contract_sha256'] = registry.execution_contract_hash(contract)
    value['fingerprint'] = registry.digest_json({'original':value['fingerprint'],'contract':contract})
    value.update(registry.register('def adapt(ctx):\n    pass\n# 1',contract,value))
    with pytest.raises(NeedsInput,match='incompatible record identities'):
        worker.publish(job,value,lambda:None)
    assert query.catalog()['release_id'] == original['release_id']
    with store.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM batches WHERE job_id=%s',(job['id'],)).fetchone()['n'] == 0
        assert publication.counts(conn,original['batch_id'])['crash'] == 1


@pytest.mark.parametrize('mode', ['partition', 'incremental'])
@pytest.mark.parametrize('change', ['counts', 'nulls', 'population', 'official_definition'])
def test_update_semantics_drift_rejected_before_copy_and_release_switch(client, monkeypatch, mode, change):
    source = f'semantics_drift_{mode}_{change}'
    original, _ = published(client, source, [row(source, 'same-raw-key')])
    job = claim_specific(queued(client)['id'])
    value = candidate(job, source, [row(source, 'same-raw-key', fatalities=3, casualties=4)], mode=mode)
    contract_value = value['source_contract']
    if change == 'counts': contract_value['resources'][0]['mapping']['fatalities'] = {'field': 'injuries'}
    elif change == 'nulls': contract_value['null_values'] = [0]
    elif change == 'population': contract_value['definitions']['casualties_includes_fatalities'] = False
    else:
        value['admission']['evidence']['grounding'] = {'field_bindings': [{'role': 'crash', 'claim': 'counts', 'field': 'n',
            'evidence': [{'mode': 'official_structured_field', 'official_field': 'n', 'description': 'New restricted population'}]}]}
    value['admission']['source_contract_sha256'] = registry.execution_contract_hash(contract_value)
    value['fingerprint'] = registry.digest_json({'original': value['fingerprint'], 'changed_semantics': change})
    value.update(registry.register('def adapt(ctx):\n    pass\n# 1', contract_value, value))
    monkeypatch.setattr(publication, 'copy_candidate', lambda *a, **kw: pytest.fail('Incompatible update reached COPY'))
    with pytest.raises(NeedsInput, match='Semantic compatibility'):
        worker.publish(job, value, lambda: None)
    assert query.catalog()['release_id'] == original['release_id']
    with store.connect() as conn:
        assert conn.execute('SELECT count(*) AS n FROM batches WHERE job_id=%s', (job['id'],)).fetchone()['n'] == 0
        assert publication.counts(conn, original['batch_id'])['crash'] == 1


def test_workflow_checkpoint_advances_controlled_steps_and_preserves_diagnostics(client):
    session = session_for(client)
    session.code = 'def adapt(ctx):\n    pass'
    session.contract = {'source':{'source_id':'workflow'},'resources':[]}
    assert session.workflow_state()['next_action'] == {'tool':'run_adapter','arguments':{'mode':'sample'},'reason':'Current code and contract are saved; this attempt needs sample execution and independent QA before full execution.'}
    hashes = {'code_sha256':hashlib.sha256(session.code.encode()).hexdigest(),
              'contract_sha256':registry.execution_contract_hash({**session.contract,'documents':[]}), 'image':'trusted-image'}
    session.runs['sample'] = {**hashes,'run_id':'sample','status':'succeeded','mode':'sample'}
    assert session.workflow_state()['next_action']['arguments'] == {'run_id':'sample'}
    session.sample_gate = hashes
    assert session.workflow_state()['next_action']['arguments'] == {'mode':'full'}
    session.runs['full'] = {**hashes,'run_id':'full','status':'succeeded','mode':'full'}
    assert session.workflow_state()['next_action']['tool'] == 'validate_candidate'
    session.runs['full']['qa_status'] = 'failed'
    assert session.workflow_state()['next_action']['tool'] == 'inspect_run'
    session.validated = {'admission':{'status':'admitted'}}
    assert session.workflow_state()['next_action']['tool'] == 'register_adapter'
    session.registered = {'adapter_version_id':'verified-version'}
    assert session.workflow_state()['next_action']['tool'] == 'publish_candidate'
    assert session.ready is None
    session.validated,session.registered = None,None
    session.code += '\n# changed'
    assert session.workflow_state()['next_action']['arguments'] == {'mode':'sample'}


def test_workflow_checkpoint_counts_completed_tools_and_remaining_budget_on_restore(client):
    session = session_for(client)
    step = session.step('tool','get_adapter_contract',{})
    session.finish_step(step,{'contract':'SDK'})
    session.usage['model_calls'] = 17
    session.usage['tool_calls'] = 14
    session.persist()
    restored = agent.AgentSession(session.job['files'],session.work_dir,{},lambda *a,**k:None,lambda:None,session.job)
    checkpoint = restored.workflow_state()
    assert checkpoint['completed_tool_counts'] == {'get_adapter_contract':1}
    assert checkpoint['remaining_budget']['model_calls'] == restored.budget['model_calls']-17
    assert checkpoint['remaining_budget']['tool_calls'] == restored.budget['tool_calls']-14
    assert 'workflow checkpoint' in restored.wire_messages()[-1]['content']


@pytest.mark.parametrize('version',['current','','  ',None])
def test_read_current_adapter_does_not_lookup_registry_or_invalidate_qa(client,monkeypatch,version):
    session = session_for(client)
    session.code = 'def adapt(ctx):\n    pass'
    session.sample_gate = {'sentinel':True}
    monkeypatch.setattr(registry,'read',lambda *a:pytest.fail('Current adapter should not query registered versions'))
    value = session.execute_tool('read_adapter',{'adapter_version_id':version})
    assert value['code'] == session.code
    assert session.sample_gate == {'sentinel':True}


def test_real_owned_orphan_container_cleanup_in_isolated_database(client):
    from arsia_pipeline import scoped_orphans
    from arsia_pipeline.config import read_config
    from arsia_pipeline.isolated_executor import docker,arguments,DEFAULT_LIMITS,IMAGE
    inspected=docker(['image','inspect',IMAGE,'--format','{{.Id}}'])
    if inspected.returncode: pytest.skip('Dedicated real Docker image unavailable')
    cfg=read_config()
    assert cfg['test_session_id'] and cfg['storage_policy']['enabled'] and cfg['dedicated_regression_module']
    job=claim_specific(queued(client)['id'])
    folder=job['work_dir']/'agent'/('run-'+uuid4().hex)
    (folder/'input').mkdir(parents=True)
    (folder/'output').mkdir();(folder/'output').chmod(0o777)
    receipt=scoped_orphans.write_ownership(folder,config=cfg,job_id=job['id'],attempt_id=job['attempt_id'])
    name=receipt['container_name']
    args=arguments(name,folder/'input',folder/'output',inspected.stdout.strip(),DEFAULT_LIMITS,receipt)
    args[-1:-1]=['--entrypoint','python']
    args.extend(['-c','import time; time.sleep(120)'])
    started=docker(args)
    assert started.returncode==0
    container_id=started.stdout.strip()
    try:
        with store.connect() as conn:
            conn.execute('SELECT pg_advisory_lock(%s)',(store.LOCK,))
            before=conn.execute('SELECT release_id FROM current_release').fetchone()
            result=scoped_orphans.recover_owned_orphans(conn,cfg,docker)
            after=conn.execute('SELECT release_id FROM current_release').fetchone()
        assert before==after
        assert result['status']=='passed'
        assert [action['container_id'] for action in result['actions']]==[container_id]
        assert result['actions'][0]['status']=='removed'
        assert docker(['inspect',container_id]).returncode!=0
        assert json.loads((folder/'orphan-recovery.json').read_text())['attempt_id']==str(job['attempt_id'])
    finally:
        present=docker(['inspect',container_id,'--format','{{index .Config.Labels "arsia.import.adapter"}}'])
        if present.returncode==0 and present.stdout.strip()==name:
            docker(['rm','-f',container_id])


def test_final_permitted_model_response_can_execute_pending_publication(client,monkeypatch):
    session=session_for(client);session.budget['model_calls']=2
    session.validated={'source_id':'budget_source','fingerprint':'budget-fixture-fingerprint','admission':{'status':'admitted'}}
    session.registered={'adapter_version_id':'verified-budget-adapter'}
    responses=iter([tool_call('get_adapter_contract',{},1),tool_call('publish_candidate',{},2)])
    called=[]
    def gateway(*args):
        called.append(True)
        if len(called)>2:pytest.fail('Model N+1 must never start')
        return next(responses)
    monkeypatch.setattr(agent,'gateway',gateway)
    result=session.run()
    assert result['adapter_version_id']=='verified-budget-adapter'
    assert session.usage['model_calls']==2 and session.usage['tool_calls']==2
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) AS n FROM agent_steps WHERE session_id=%s AND name='publish_candidate' AND status='succeeded'",(session.id,)).fetchone()['n']==1


def test_model_budget_stops_new_request_after_last_pending_tool_completes(client,monkeypatch):
    session=session_for(client);session.budget['model_calls']=1
    called=[]
    def gateway(*args):
        called.append(True)
        if len(called)>1:pytest.fail('Model N+1 must never start')
        return tool_call('get_adapter_contract',{},1)
    monkeypatch.setattr(agent,'gateway',gateway)
    with pytest.raises(NeedsInput,match='model_calls budget'):
        session.run()
    assert session.usage['model_calls']==1 and session.usage['tool_calls']==1 and not session.pending
