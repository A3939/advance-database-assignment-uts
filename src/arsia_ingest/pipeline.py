"""Archive input files and write L1 records, metadata and run logs."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .config import load_config
from .models import IntakeError, ParseStats, ResourceSpec
from .readers import iter_native_rows

CHUNK_SIZE = 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, allow_nan=False,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _write_json(path: Path, value: object) -> None:
    """Write JSON to a temporary file, then move it into place atomically."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(_json(value))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _verify_archive(path: Path, digest: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise IntakeError("ARCHIVE_INTEGRITY", "Archive must be a regular file", archive_path=str(path))
    actual = _sha256(path)
    if actual != digest:
        raise IntakeError("ARCHIVE_INTEGRITY", "Existing archive bytes do not match their SHA256 name",
                          archive_path=str(path), expected_sha256=digest, actual_sha256=actual)


def _archive(spec: ResourceSpec, archive_root: Path) -> tuple[str, Path, int]:
    """Copy and hash the same bytes, reusing a matching archive if one exists."""
    archive_root.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with spec.path.open("rb") as source:
            before = os.fstat(source.fileno())
            if not spec.path.is_file():
                raise IntakeError("INPUT_NOT_FILE", "Input must be a regular file", path=str(spec.path))
            with tempfile.NamedTemporaryFile(prefix=".copy-", dir=archive_root, delete=False) as target:
                temporary = Path(target.name)
                digest = hashlib.sha256()
                count = 0
                while chunk := source.read(CHUNK_SIZE):
                    digest.update(chunk)
                    target.write(chunk)
                    count += len(chunk)
                target.flush()
                os.fsync(target.fileno())
            after = os.fstat(source.fileno())
        hexdigest = digest.hexdigest()
        destination = archive_root / hexdigest[:2] / hexdigest
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            # os.link fails if another run has already created this archive.
            os.link(temporary, destination)
        except FileExistsError:
            _verify_archive(destination, hexdigest)
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_size, after.st_mtime_ns, after.st_ctime_ns) or count != before.st_size:
            raise IntakeError("INPUT_CHANGED", "Input changed while it was being archived; retry from a stable file",
                              path=str(spec.path), archive_path=str(destination), file_sha256=hexdigest)
        return hexdigest, destination, count
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _file_metadata(spec: ResourceSpec, digest: str, stats: ParseStats) -> dict:
    # The L1 contract defines these 13 fields for each files[] entry.
    return {
        "source_id": spec.source_id, "resource_id": spec.resource_id,
        "resource_role": spec.resource_role, "entity_kind": spec.entity_kind,
        "file_sha256": digest, "parser_version": spec.parser_version,
        "locator_version": spec.locator_version, "format": spec.format,
        "encoding": spec.encoding, "sheet": spec.sheet, "header_row": spec.header_row,
        "header": stats.header, "raw_count": stats.raw_count,
    }


def prepare(config_path: str | Path, output_root: str | Path) -> dict:
    """Prepare inputs in a new run directory and return the saved receipt.

    Invalid configuration raises IntakeError before creating a run. Processing
    errors return status=failed; use the exports only when status is prepared.
    Failed runs keep their archives and logs. Earlier runs are left in place.
    """
    config = load_config(config_path)
    output_root = Path(output_root).expanduser().resolve()
    run_id = str(uuid.uuid4())
    mode_root = output_root / config.dataset_kind
    run_dir = mode_root / "runs" / run_id
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        raise IntakeError("RUN_SETUP", "Cannot create a new output run directory",
                          run_id=run_id, path=str(run_dir), reason=str(exc)) from exc
    summary = {
        "output_version": "intake-output-v1", "tool_version": __version__,
        "run_id": run_id, "dataset_kind": config.dataset_kind,
        "run_dir": str(run_dir), "config_path": str(config.config_path),
        "scope": "native_preparation_only", "status": "preparing",
        "started_at": _now(), "finished_at": None, "files": [], "errors": [],
    }
    files: list[dict] = []
    provenance: list[dict] = []
    current: ResourceSpec | None = None
    stats: ParseStats | None = None
    events_path = run_dir / "events.jsonl"

    def event(name: str, **details: object) -> None:
        with events_path.open("ab") as stream:
            stream.write(_json({"at": _now(), "run_id": run_id, "event": name, **details}))

    try:
        _write_json(run_dir / "run.json", summary)
        event("run_started", dataset_kind=config.dataset_kind)
        records_dir = run_dir / "records"
        records_dir.mkdir()
        for spec in config.resources:
            current, stats = spec, ParseStats()
            event("file_started", resource_id=spec.resource_id, input_path=str(spec.path))
            digest, archive_path, size = _archive(spec, mode_root / "archive" / "sha256")
            relative_archive = archive_path.relative_to(output_root).as_posix()
            event("file_archived", resource_id=spec.resource_id, file_sha256=digest,
                  archive_relpath=relative_archive, bytes=size)
            with archive_path.open("rb") as stream:
                prefix = stream.read(200)
            if prefix.startswith(b"version https://git-lfs.github.com/spec/v1\n") or prefix.startswith(
                    b"version https://git-lfs.github.com/spec/v1\r\n"):
                raise IntakeError("LFS_POINTER", "Input is a Git LFS pointer; run git lfs pull to obtain the original bytes",
                                  path=str(spec.path), archive_relpath=relative_archive)
            if spec.expected_sha256 is not None and digest != spec.expected_sha256:
                raise IntakeError("FILE_HASH_MISMATCH", "Input bytes differ from the pinned catalogue; review the input before changing the pin",
                                  expected_sha256=spec.expected_sha256, actual_sha256=digest,
                                  archive_relpath=relative_archive)
            records_path = records_dir / f"{spec.resource_id}.jsonl"
            records_hash = hashlib.sha256()
            with records_path.open("xb") as output, closing(iter_native_rows(archive_path, spec, stats)) as rows:
                for row in rows:
                    encoded = _json({
                        "source_id": spec.source_id, "resource_id": spec.resource_id,
                        "file_sha256": digest, "parser_version": spec.parser_version,
                        "row_locator": row.row_locator, "payload": row.payload,
                    })
                    output.write(encoded)
                    records_hash.update(encoded)
                output.flush()
                os.fsync(output.fileno())
            _verify_archive(archive_path, digest)
            files.append(_file_metadata(spec, digest, stats))
            provenance.append({
                "resource_id": spec.resource_id, "file_sha256": digest,
                "archive_relpath": relative_archive, "original_filename": spec.path.name,
                "input_path": str(spec.path),
            })
            summary["files"].append({
                "resource_id": spec.resource_id, "file_sha256": digest,
                "input_bytes": size, "records_path": records_path.relative_to(run_dir).as_posix(),
                "records_sha256": records_hash.hexdigest(), **asdict(stats),
            })
            event("file_prepared", **summary["files"][-1])
        _write_json(run_dir / "files.json", {"files": files})
        _write_json(run_dir / "provenance.json", {
            "run_id": run_id, "dataset_kind": config.dataset_kind, "files": provenance,
        })
        summary["status"] = "prepared"
        event("run_prepared", resources=len(files), raw_count=sum(f["raw_count"] for f in files))
    except (Exception, KeyboardInterrupt) as exc:
        if isinstance(exc, IntakeError):
            error = exc.as_dict()
        elif isinstance(exc, KeyboardInterrupt):
            error = {"code": "INTERRUPTED", "message": "Native preparation was interrupted"}
        else:
            error = {"code": "IO_ERROR" if isinstance(exc, OSError) else "PROCESSING_ERROR",
                     "message": str(exc), "exception_type": type(exc).__name__}
        error["run_id"] = run_id
        if current is not None:
            error.setdefault("resource_id", current.resource_id)
            error.setdefault("input_path", str(current.path))
            error["partial_stats"] = asdict(stats) if stats is not None else None
        summary["status"], summary["files"], summary["errors"] = "failed", [], [error]
        # Clean up this run's exports, leaving archives and earlier runs intact.
        for artifact in ("records", "files.json", "provenance.json"):
            try:
                path = run_dir / artifact
                if artifact == "records":
                    if path.exists():
                        shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                summary["errors"].append({"code": "CLEANUP_ERROR", "path": str(path),
                                          "message": str(cleanup_error)})
        try:
            event("run_failed", error=error)
        except OSError as log_error:
            summary["errors"].append({"code": "LOG_WRITE_ERROR", "message": str(log_error)})
    summary["finished_at"] = _now()
    summary["raw_count"] = sum(file["raw_count"] for file in summary["files"])
    try:
        _write_json(run_dir / "run.json", summary)
    except OSError as exc:
        raise IntakeError("RECEIPT_WRITE", "Cannot persist final receipt; this run must not be consumed",
                          run_id=run_id, path=str(run_dir), reason=str(exc)) from exc
    return summary
