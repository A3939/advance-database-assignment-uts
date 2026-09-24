"""B's build entry point. Team modules use one connection without owning it."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
from typing import Callable
from uuid import uuid4

from .fingerprint import FP1Operation, fingerprint
from .manifest import FrozenManifest, REQUIRED_CHECKS, freeze_manifest
from .models import IntakeError
from .qa_input import check_inputs, check_raw, write_evidence, write_results
from .raw_load import _PreparedRun, load_prepared


LOCK_KEY = (32113, 2)
STAGES = {"project": "project", "vault": "vault", "canonical": "canonical",
          "dw": "dw", "qa_c": "qa", "qa_d": "qa", "publish": "publish"}
EXIT_CODES = {"succeeded": 0, "no_change": 0, "busy": 2, "failed": 1, "unknown_commit": 3}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


@dataclass(frozen=True)
class ModuleBinding:
    callback: Callable
    code_path: str
    version: str


@dataclass(frozen=True)
class BuildModules:
    project: ModuleBinding | None = None
    vault: ModuleBinding | None = None
    canonical: ModuleBinding | None = None
    dw: ModuleBinding | None = None
    qa_c: ModuleBinding | None = None
    qa_d: ModuleBinding | None = None
    publish: ModuleBinding | None = None


@dataclass(frozen=True)
class RunEvidence:
    directory: Path

    def write_json(self, name, value):
        """Use a fresh local filename; every reference includes a digest and count."""
        if not isinstance(name, str) or Path(name).name != name or not name.endswith(".json"):
            raise IntakeError("RUN_EVIDENCE", "Evidence needs a local .json filename")
        return write_evidence(self.directory / name, value)

    def for_stage(self, name):
        if name not in (*STAGES, "input", "raw", "registration", "failure"):
            raise IntakeError("RUN_STAGE", "Unknown evidence stage")
        return RunEvidence(self.directory / name)


@dataclass(frozen=True)
class RunContext:
    run_id: str
    dataset_kind: str
    batch_id: str
    input_fingerprint: str
    previous_batch_id: str | None
    manifest: FrozenManifest
    evidence: RunEvidence


@dataclass(frozen=True)
class RunResult:
    data: dict

    @property
    def exit_code(self):
        return EXIT_CODES[self.data["result"]]

    def as_dict(self):
        return json.loads(_json(self.data))


class _Cursor:
    """Expose query operations, without a cursor.connection escape by accident."""
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        self._cursor.__enter__()
        return self

    def __exit__(self, *args):
        return self._cursor.__exit__(*args)

    def execute(self, *args, **kwargs):
        self._cursor.execute(*args, **kwargs)
        return self

    def executemany(self, *args, **kwargs):
        self._cursor.executemany(*args, **kwargs)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def fetchmany(self, size):
        return self._cursor.fetchmany(size)

    def __iter__(self):
        return iter(self._cursor)

    @property
    def rowcount(self):
        return self._cursor.rowcount

    @property
    def description(self):
        return self._cursor.description


class ModuleConnection:
    """Query-only facade over B's connection; SQL modules must also respect L4."""
    def __init__(self, connection):
        self._connection = connection

    @property
    def autocommit(self):
        return self._connection.autocommit

    def cursor(self, *args, **kwargs):
        return _Cursor(self._connection.cursor(*args, **kwargs))


def _query(connection, sql, parameters=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, parameters)
        return cursor.fetchall()


def _execute(connection, sql):
    with connection.cursor() as cursor:
        cursor.execute(sql)


def _bindings(modules, fp1, inventory):
    if not isinstance(modules, BuildModules):
        raise IntakeError("MODULE_UNAVAILABLE", "Supply explicit BuildModules from A/C/D/E")
    missing = [name for name in STAGES if not isinstance(getattr(modules, name), ModuleBinding)
               or not callable(getattr(modules, name).callback)]
    if missing:
        raise IntakeError("MODULE_UNAVAILABLE", "Required team modules are unavailable", modules=missing)
    if not isinstance(fp1, FP1Operation):
        raise IntakeError("FP1_UNAVAILABLE", "E's FP1 operation has not been registered")
    for name, component in STAGES.items():
        binding = getattr(modules, name)
        if not isinstance(binding.version, str) or not binding.version.strip():
            raise IntakeError("MODULE_VERSION", "Every module needs a declared version", module=name)
        if binding.code_path not in inventory["components"][component]:
            raise IntakeError("MODULE_CODE", "Module is absent from its frozen component inventory", module=name)
    if fp1.code_path not in inventory["components"]["fp1"]:
        raise IntakeError("MODULE_CODE", "FP1 is absent from its frozen component inventory")


def _current(connection, kind):
    rows = _query(connection, """SELECT cr.batch_id, cr.batch_status, b.dataset_kind,
        b.status, b.input_fingerprint, b.manifest
        FROM meta.current_release AS cr LEFT JOIN meta.batch AS b ON b.batch_id=cr.batch_id
        WHERE cr.dataset_kind=%s""", (kind,))
    if not rows:
        return None
    if len(rows) != 1 or len(rows[0]) != 6 or rows[0][1:4] != ("succeeded", kind, "succeeded"):
        raise IntakeError("CURRENT_RELEASE", "Current release is not a successful batch of this mode")
    batch_id, _, _, _, digest, value = rows[0]
    frozen = FrozenManifest(_json(value))
    if frozen.as_dict()["dataset_kind"] != kind:
        raise IntakeError("CURRENT_RELEASE", "Current manifest belongs to another mode")
    return str(batch_id), digest, frozen


def _qa_summary(connection, batch_id):
    rows = _query(connection, """SELECT rule_id,result,affected_count FROM qa.check_result
        WHERE batch_id=%s::uuid AND object_key='batch' ORDER BY rule_id""", (batch_id,))
    summary = {}
    for row in rows:
        if len(row) != 3:
            raise IntakeError("QA_SUMMARY", "QA summary has an unexpected shape")
        rule, result, affected = row
        if (rule not in REQUIRED_CHECKS or rule in summary or type(affected) is not int or affected < 0
                or result not in ("pass", "limited") or (result == "limited" and rule != "QA07_LOCATION")
                or (result == "pass" and affected != 0)):
            raise IntakeError("QA_SUMMARY", "A required QA summary is missing or blocked")
        summary[rule] = {"rule_id": rule, "result": result, "affected_count": affected}
    if set(summary) != set(REQUIRED_CHECKS):
        raise IntakeError("QA_SUMMARY", "All seven QA summaries are required")
    return [summary[rule] for rule in REQUIRED_CHECKS]


def _error(exc, stage):
    # Driver errors may include connection strings. Keep their text out of receipts.
    return {"stage": stage, "error_code": exc.code if isinstance(exc, IntakeError) else "RUN_ERROR",
            "message": str(exc) if isinstance(exc, IntakeError) else f"{stage} raised {type(exc).__name__}",
            "details": exc.details if isinstance(exc, IntakeError) else {}, "checked_at": _now()}


class _UnknownCommit(Exception):
    pass


def run_build(*, connect, prepared_run, manifest, project_root, inventory, modules,
              evidence_root, fp1=None, supported_mappings=(), official_reviews=(),
              producer_version="b11-v1"):
    """Run one complete candidate using a fresh connection supplied by A.

    There are no built-in business modules or FP1 implementation. The caller
    registers real module callbacks; mocks belong only in tests.
    """
    run_id = str(uuid4())
    kind = manifest.as_dict()["dataset_kind"] if isinstance(manifest, FrozenManifest) else None
    if kind is None:
        raise IntakeError("RUN_MANIFEST", "The runner requires a FrozenManifest")
    directory = Path(evidence_root).resolve() / kind / "runs" / run_id
    directory.mkdir(parents=True, exist_ok=False)
    evidence = RunEvidence(directory)
    base = {"run_id": run_id, "dataset_kind": kind, "batch_id": None, "evidence_ref": str(directory)}
    connection = None
    batch_id = None
    registered = False
    stage = "preflight"
    cleanup = []

    def commit(phase):
        evidence.write_json(f"before-{phase}-commit.json", {**base, "batch_id": batch_id, "stage": phase, "checked_at": _now()})
        try:
            connection.commit()
        except BaseException as exc:
            raise _UnknownCommit(phase) from exc

    try:
        frozen = freeze_manifest(manifest.as_dict(), project_root=project_root, inventory=inventory)
        value = frozen.as_dict()
        run = _PreparedRun(prepared_run)
        if run.kind != kind or sorted(run.files, key=lambda f: f["resource_id"]) != value["files"]:
            raise IntakeError("RUN_INPUT", "Prepared files differ from the frozen manifest")
        run.check_files()
        _bindings(modules, fp1, inventory)
        if not callable(connect):
            raise IntakeError("CONNECTION_UNAVAILABLE", "A must supply a fresh loader connection factory")
        evidence.write_json("manifest.json", value)
        evidence.write_json("bindings.json", {name: {"code_path": getattr(modules, name).code_path,
                                                     "version": getattr(modules, name).version} for name in STAGES})
        stage = "connect"
        connection = connect()
        if getattr(connection, "autocommit", None) is not False:
            raise IntakeError("RUN_AUTOCOMMIT", "The connection factory must return autocommit=False")
        shared = ModuleConnection(connection)
        _execute(shared, "SET TIME ZONE 'UTC'")
        _execute(shared, "SET client_encoding TO 'UTF8'")
        stage = "lock"
        rows = _query(shared, "SELECT pg_try_advisory_lock(%s,%s)", LOCK_KEY)
        if rows == [(False,)]:
            outcome = {**base, "result": "busy", "reason": "Another ARSIA run owns the session lock"}
            connection.rollback()
        else:
            if rows != [(True,)]:
                raise IntakeError("RUN_LOCK", "Cannot confirm the session lock")
            stage = "history"
            running = _query(shared, """SELECT batch_id,dataset_kind FROM meta.batch
                WHERE status='running' ORDER BY started_at,batch_id""")
            if running:
                raise IntakeError("RECOVERY_REQUIRED", "Resolve existing running batches before another build",
                                  batches=[{"batch_id": str(row[0]), "dataset_kind": row[1]} for row in running])
            current = _current(shared, kind)
            previous_id = current[0] if current else None
            stage = "input"
            inputs = check_inputs(value, run.root, previous_manifest=current[2].as_dict() if current else None,
                                  evidence_dir=evidence.for_stage("input").directory,
                                  producer_version=producer_version, supported_mappings=supported_mappings,
                                  official_reviews=official_reviews, policy_evidence_root=project_root)
            evidence.write_json("qa01.json", inputs.as_dict())
            if inputs.blocked:
                raise IntakeError("QA_BLOCK", "QA01_INPUT blocked the input", rule_id="QA01_INPUT", evidence="qa01.json")
            stage = "fingerprint"
            digest = fingerprint(shared, frozen, fp1, project_root=project_root)
            if current is not None and current[1] == digest:
                summary = _qa_summary(shared, current[0])
                connection.rollback()
                outcome = {**base, "result": "no_change", "batch_id": current[0], "input_fingerprint": digest,
                           "previous_batch_id": current[0], "qa_summary": summary}
            else:
                stage = "registration"
                raw = load_prepared(shared, run.path, value["sources"])
                evidence.write_json("raw-load.json", raw.__dict__)
                batch_id = str(uuid4())
                rows = _query(shared, """INSERT INTO meta.batch(batch_id,dataset_kind,input_fingerprint,manifest)
                    VALUES (%s::uuid,%s,%s,%s::jsonb) RETURNING batch_id""", (batch_id, kind, digest, _json(value)))
                if len(rows) != 1 or str(rows[0][0]) != batch_id:
                    raise IntakeError("RUN_REGISTRATION", "The database did not return the candidate batch")
                commit("registration")
                registered = True
                context = RunContext(run_id, kind, batch_id, digest, previous_id, frozen, evidence)
                for stage in ("project", "vault", "canonical", "dw"):
                    getattr(modules, stage).callback(shared, replace(context, evidence=evidence.for_stage(stage)))
                stage = "raw"
                raw_qa = check_raw(shared, value, run.root, evidence_dir=evidence.for_stage("raw").directory,
                                   producer_version=producer_version)
                evidence.write_json("qa02.json", raw_qa.as_dict())
                if raw_qa.blocked:
                    raise IntakeError("QA_BLOCK", "QA02_RAW blocked the build", rule_id="QA02_RAW", evidence="qa02.json")
                write_results(shared, batch_id, inputs)
                write_results(shared, batch_id, raw_qa)
                for stage in ("qa_c", "qa_d", "publish"):
                    getattr(modules, stage).callback(shared, replace(context, evidence=evidence.for_stage(stage)))
                published = _current(shared, kind)
                if published is None or published[:2] != (batch_id, digest) or published[2].as_dict() != value:
                    raise IntakeError("PUBLICATION_UNCONFIRMED", "E did not publish this candidate and frozen manifest")
                summary = _qa_summary(shared, batch_id)
                stage = "publication_commit"
                commit("publication")
                outcome = {**base, "result": "succeeded", "batch_id": batch_id, "input_fingerprint": digest,
                           "previous_batch_id": previous_id, "qa_summary": summary}
    except _UnknownCommit as exc:
        outcome = {**base, "result": "unknown_commit", "batch_id": batch_id}
        cleanup.append({"stage": str(exc), "reason": "COMMIT response was not confirmed; query database state before retrying"})
    except BaseException as exc:
        error = {"run_id": run_id, **_error(exc, stage)}
        try:
            evidence.write_json("error.json", error)
        except Exception as evidence_error:
            cleanup.append({"stage": "error_evidence", "exception_type": type(evidence_error).__name__})
        rolled_back = connection is None
        if connection is not None:
            try:
                connection.rollback()
                rolled_back = True
            except Exception as rollback_error:
                cleanup.append({"stage": "rollback", "exception_type": type(rollback_error).__name__})
        outcome = {**base, "result": "failed", "batch_id": batch_id if registered else None,
                   "stage": stage, "error_code": error["error_code"], "message": error["message"]}
        if not rolled_back:
            outcome = {**base, "result": "unknown_commit", "batch_id": batch_id}
        elif registered:
            try:
                _execute(connection, "SET TIME ZONE 'UTC'")
                rows = _query(connection, """UPDATE meta.batch SET status='failed',finished_at=clock_timestamp(),
                    error_details=%s::jsonb WHERE batch_id=%s::uuid AND dataset_kind=%s AND status='running'
                    RETURNING batch_id""", (_json(error), batch_id, kind))
                if len(rows) != 1 or str(rows[0][0]) != batch_id:
                    raise IntakeError("FAILURE_STATE", "Candidate is no longer running; inspect its state")
                commit("failure")
            except _UnknownCommit:
                outcome = {**base, "result": "unknown_commit", "batch_id": batch_id}
                cleanup.append({"stage": "failure_commit", "reason": "Failure record COMMIT was not confirmed"})
            except Exception as failure_error:
                cleanup.append(_error(failure_error, "failure_record"))
                if isinstance(failure_error, IntakeError) and failure_error.code == "FAILURE_STATE":
                    outcome = {**base, "result": "unknown_commit", "batch_id": batch_id}
                try:
                    connection.rollback()
                except Exception as rollback_error:
                    cleanup.append({"stage": "failure_rollback", "exception_type": type(rollback_error).__name__})
    finally:
        if connection is not None:
            # Closing this dedicated session releases its session lock, including after COMMIT loss.
            try:
                connection.close()
            except Exception as close_error:
                cleanup.append({"stage": "close", "exception_type": type(close_error).__name__})
    if cleanup:
        outcome["diagnostics"] = cleanup
    try:
        evidence.write_json("result.json", outcome)
    except Exception as evidence_error:
        outcome.setdefault("diagnostics", []).append({"stage": "result_evidence", "exception_type": type(evidence_error).__name__})
    return RunResult(outcome)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run ARSIA with the team's explicit database/module bindings.")
    parser.add_argument("--bindings", required=True, help="Importable module:function returning run_build keyword arguments")
    args = parser.parse_args(argv)
    try:
        module_name, separator, name = args.bindings.partition(":")
        if not separator or not module_name or not name.isidentifier():
            raise IntakeError("RUN_BINDINGS", "Use module:function for the team bindings")
        factory = getattr(importlib.import_module(module_name), name)
        if not callable(factory):
            raise IntakeError("RUN_BINDINGS", "The bindings factory is not callable")
        arguments = factory()
        if not isinstance(arguments, dict):
            raise IntakeError("RUN_BINDINGS", "The bindings factory must return keyword arguments")
        result = run_build(**arguments)
    except Exception as exc:
        print(_json({"result": "failed", "batch_id": None, **_error(exc, "bindings")}))
        return 1
    print(_json(result.as_dict()))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
