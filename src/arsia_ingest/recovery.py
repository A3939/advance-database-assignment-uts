"""Resolve one interrupted run from its saved evidence and current database state."""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import importlib
import json
from pathlib import Path
import re
from uuid import UUID, uuid4

from .manifest import validate_manifest
from .models import IntakeError
from .runner import LOCK_KEY, RunEvidence, _error, _execute, _json, _now, _query


PHASES = ("registration", "publication", "failure")
FILES = ("manifest.json", *(f"before-{phase}-commit.json" for phase in PHASES), "result.json", "error.json")
EXIT_CODES = {"succeeded": 0, "failed": 0, "not_registered": 0, "busy": 2, "unknown_commit": 3}


@dataclass(frozen=True)
class RecoveryResult:
    data: dict

    @property
    def exit_code(self):
        return EXIT_CODES[self.data["resolution"]]

    def as_dict(self):
        return json.loads(_json(self.data))


def _require(condition, message):
    if not condition:
        raise IntakeError("RECOVERY_STATE", message)


def _uuid(value):
    _require(isinstance(value, str) and str(UUID(value)) == value, "Expected a canonical UUID")
    return value


def _utc(value):
    stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    _require(isinstance(stamp, datetime) and stamp.utcoffset() == timedelta(0), "Expected a UTC timestamp")
    return stamp


def _digest(value):
    _require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value), "Invalid saved fingerprint")
    return value


def _pairs(items):
    value = {}
    for key, item in items:
        _require(key not in value, "Duplicate key in recovery evidence")
        value[key] = item
    return value


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _read_run(run_dir):
    path = Path(run_dir).absolute()
    _require(not any(p.is_symlink() for p in (path, *path.parents)), "Run evidence must not use symlinks")
    path = path.resolve(strict=True)
    documents, references = {}, []
    for name in FILES:
        file = path / name
        _require(not file.is_symlink(), "Run evidence must not use symlinks")
        if not file.exists():
            continue
        data = file.read_bytes()
        documents[name] = json.loads(data, object_pairs_hook=_pairs)
        _require(isinstance(documents[name], dict), "Run evidence must contain JSON objects")
        references.append({"path": str(file), "sha256": hashlib.sha256(data).hexdigest()})
    manifest = documents["manifest.json"]
    validate_manifest(manifest)
    marker = documents["before-registration-commit.json"]
    run_id, batch_id = _uuid(marker["run_id"]), _uuid(marker["batch_id"])
    kind = manifest["dataset_kind"]
    _require(path.name == run_id and path.parent.name == "runs" and path.parent.parent.name == kind,
             "Run directory, mode and saved run ID disagree")
    phases, digests = [], set()
    for phase in PHASES:
        entry = documents.get(f"before-{phase}-commit.json")
        if entry is None:
            continue
        _require((entry["run_id"], entry["batch_id"], entry["dataset_kind"], entry["stage"])
                 == (run_id, batch_id, kind, phase), "Commit evidence belongs to a different run or phase")
        _require(_utc(entry["checked_at"]) >= _utc(marker["checked_at"]), "Commit evidence is out of order")
        if "input_fingerprint" in entry:
            digests.add(_digest(entry["input_fingerprint"]))
        phases.append(phase)
    _require(not {"publication", "failure"} <= set(phases), "Conflicting publication and failure commit evidence")
    result = documents.get("result.json")
    if result is not None:
        _require((result["run_id"], result["batch_id"], result["dataset_kind"]) == (run_id, batch_id, kind),
                 "Saved result belongs to another run")
        _require(result["result"] in {"succeeded", "failed", "unknown_commit"}, "This run has no candidate to recover")
        if "input_fingerprint" in result:
            digests.add(_digest(result["input_fingerprint"]))
    error = documents.get("error.json")
    if error is not None:
        _require(error["run_id"] == run_id, "Saved error belongs to another run")
        _utc(error["checked_at"])
    _require(len(digests) <= 1, "Saved fingerprints disagree")
    return {"path": path, "run_id": run_id, "batch_id": batch_id, "dataset_kind": kind,
            "manifest": manifest, "phases": phases, "fingerprint": next(iter(digests), None),
            "result": result, "error": error, "references": references}


def _unchanged(original):
    present = {name for name in FILES if (original["path"] / name).exists()}
    _require(present == {Path(ref["path"]).name for ref in original["references"]}, "Run evidence changed during recovery")
    for ref in original["references"]:
        path = Path(ref["path"])
        _require(not path.is_symlink() and hashlib.sha256(path.read_bytes()).hexdigest() == ref["sha256"],
                 "Run evidence changed during recovery")


def _absence_is_resolved(original):
    if original["phases"] != ["registration"] or original["error"] is not None:
        return False
    result = original["result"]
    if result is None:
        return True
    diagnostics = result.get("diagnostics")
    return (result["result"] == "unknown_commit" and isinstance(diagnostics, list)
            and all(isinstance(item, dict) and item.get("stage") in {"registration", "close", "result_evidence"}
                    for item in diagnostics)
            and sum(item["stage"] == "registration" for item in diagnostics) == 1)


def _observe(connection, original):
    rows = _query(connection, """SELECT batch_id,dataset_kind,status,input_fingerprint,manifest,finished_at,error_details
        FROM meta.batch WHERE batch_id=%s::uuid FOR UPDATE""", (original["batch_id"],))
    _require(len(rows) <= 1, "Batch query returned more than one row")
    status, digest = None, None
    if rows:
        row = rows[0]
        _require(len(row) == 7, "Batch query returned an unexpected shape")
        bid, kind, status, digest, manifest, finished, error = row
        _require(str(bid) == original["batch_id"] and kind == original["dataset_kind"], "Batch identity or mode differs")
        _require(status in {"running", "succeeded", "failed"}, "Unknown batch status")
        _digest(digest)
        validate_manifest(manifest)
        _require(_canonical(manifest) == _canonical(original["manifest"]), "Frozen manifest differs from the saved run")
        _require(original["fingerprint"] in (None, digest), "Fingerprint differs from the saved run")
        _require((status == "running") == (finished is None), "Batch status and finish time disagree")
        if finished is not None:
            _utc(finished)
        _require(status != "failed" or error is not None, "Failed batch has no error evidence")
    pointers = _query(connection, """SELECT cr.dataset_kind,cr.batch_id,cr.batch_status,b.dataset_kind,b.status
        FROM meta.current_release AS cr LEFT JOIN meta.batch AS b ON b.batch_id=cr.batch_id
        WHERE cr.dataset_kind=%s OR cr.batch_id=%s::uuid""", (original["dataset_kind"], original["batch_id"]))
    _require(len(pointers) <= 1, "Conflicting current-release pointers")
    _require(status != "succeeded" or bool(pointers), "Succeeded batch has no current release for its mode")
    for pointer in pointers:
        _require(len(pointer) == 5, "Current-release query returned an unexpected shape")
        kind, bid, pointer_status, batch_kind, batch_status = pointer
        _uuid(str(bid))
        _require(kind == batch_kind == original["dataset_kind"] and pointer_status == batch_status == "succeeded",
                 "Current release is not a successful batch of this mode")
        _require(str(bid) != original["batch_id"] or status == "succeeded", "Current release contradicts the target batch")
    return {"status": status, "input_fingerprint": digest,
            "current_batch_id": str(pointers[0][1]) if pointers else None,
            "manifest_matches": True if rows else None}


def recover_run(*, connect, run_dir, evidence_root):
    """Resolve one batch, without retrying a build or changing any release pointer.

    connect must open a new dedicated session to the original run's database.
    A resolution describes the old batch; it is not a run_build success report.
    """
    try:
        original = _read_run(run_dir)
        root = Path(evidence_root).absolute()
        _require(not root.resolve().is_relative_to(original["path"]), "Recovery evidence must be outside the original run")
        _require(callable(connect), "Supply a fresh recovery connection factory")
    except (OSError, ValueError, KeyError, TypeError, IntakeError) as exc:
        raise IntakeError("RECOVERY_EVIDENCE", "Cannot identify the saved run; no database changes were attempted") from exc
    recovery_id = str(uuid4())
    evidence = RunEvidence(root / original["dataset_kind"] / "recoveries" / recovery_id)
    base = {key: original[key] for key in ("run_id", "batch_id", "dataset_kind")}
    base.update(recovery_id=recovery_id, evidence_ref=str(evidence.directory))
    evidence.write_json("original.json", {**base, "run_dir": str(original["path"]),
                        "commit_phases": original["phases"], "references": original["references"]})
    outcome = {**base, "resolution": "unknown_commit"}
    connection, commit_attempted = None, False
    diagnostics = []
    stage = "connect"
    try:
        connection = connect()
        _require(getattr(connection, "autocommit", None) is False, "Recovery requires autocommit=False")
        _execute(connection, "SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
        _execute(connection, "SET TIME ZONE 'UTC'")
        _execute(connection, "SET client_encoding TO 'UTF8'")
        stage = "lock"
        locked = _query(connection, "SELECT pg_try_advisory_lock(%s,%s)", LOCK_KEY)
        _require(len(locked) == 1 and len(locked[0]) == 1 and type(locked[0][0]) is bool,
                 "Cannot confirm the session lock")
        if locked == [(False,)]:
            connection.rollback()
            outcome = {**base, "resolution": "busy"}
        else:
            stage = "state"
            _unchanged(original)
            observed = _observe(connection, original)
            _unchanged(original)
            evidence.write_json("observed.json", observed)
            status = observed["status"]
            if original["result"] and original["result"]["result"] == "succeeded":
                _require(status == "succeeded", "Acknowledged success is missing from the database")
            if status is None:
                _require(_absence_is_resolved(original), "Missing batch conflicts with the saved commit stage")
                connection.rollback()
                outcome = {**base, "resolution": "not_registered", "observed_batch_status": None}
            elif status in {"succeeded", "failed"}:
                connection.rollback()
                outcome = {**base, "resolution": status, "observed_batch_status": status,
                           "input_fingerprint": observed["input_fingerprint"], "current_batch_id": observed["current_batch_id"]}
            else:
                stage = "close_running"
                _unchanged(original)
                details = {"stage": "recovery", "error_code": "ABANDONED_RUN", "run_id": original["run_id"],
                           "recovery_id": recovery_id, "message": "The previous session ended without a committed successful build.",
                           "checked_at": _now(), "references": original["references"]}
                evidence.write_json("decision.json", details)
                updated = _query(connection, """UPDATE meta.batch SET status='failed',finished_at=clock_timestamp(),
                    error_details=%s::jsonb WHERE batch_id=%s::uuid AND dataset_kind=%s AND status='running'
                    AND input_fingerprint=%s AND manifest=%s::jsonb AND finished_at IS NULL RETURNING batch_id""",
                    (_json(details), original["batch_id"], original["dataset_kind"], observed["input_fingerprint"], _json(original["manifest"])))
                _require(len(updated) == 1 and len(updated[0]) == 1 and str(updated[0][0]) == original["batch_id"],
                         "The candidate changed before its recovery update")
                stage = "recovery_commit"
                evidence.write_json("before-recovery-commit.json", {**base, "stage": stage, "checked_at": _now()})
                commit_attempted = True
                connection.commit()
                outcome = {**base, "resolution": "failed", "observed_batch_status": "running",
                           "action": "closed_abandoned_run", "input_fingerprint": observed["input_fingerprint"]}
    except BaseException as exc:
        diagnostics.append(_error(exc, stage))
        if connection is not None and not commit_attempted:
            try:
                connection.rollback()
            except Exception as rollback_error:
                diagnostics.append(_error(rollback_error, "recovery_rollback"))
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception as close_error:
                diagnostics.append(_error(close_error, "recovery_close"))
    if diagnostics:
        outcome["diagnostics"] = diagnostics
    try:
        evidence.write_json("result.json", outcome)
    except Exception as evidence_error:
        outcome.setdefault("diagnostics", []).append(_error(evidence_error, "recovery_evidence"))
    return RecoveryResult(outcome)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Resolve one saved ARSIA run without starting another build")
    parser.add_argument("--connect", required=True, help="module:function opening a fresh connection to the original database")
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--evidence-root", required=True)
    args = parser.parse_args(argv)
    try:
        module, separator, name = args.connect.partition(":")
        _require(separator and name.isidentifier(), "Use module:function for the connection factory")
        result = recover_run(connect=getattr(importlib.import_module(module), name),
                             run_dir=args.run_dir, evidence_root=args.evidence_root)
        print(_json(result.as_dict()))
        return result.exit_code
    except Exception as exc:
        print(_json({"resolution": "unknown_commit", "diagnostics": [_error(exc, "recovery_setup")]}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
