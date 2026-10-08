"""Source-neutral intake dispatch. All publications are isolated local tests.

This module does not grant source approval. It identifies supported inputs,
verifies immutable bytes and dispatches to explicit deterministic contracts.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .errors import NeedsInput, ValidationFailure


def digest_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def implementation_identity():
    root = Path(__file__).parent
    return {name: digest_file(root / name) for name in
            ("licence_assessment.py", "publication_summary.py", "archive_parser.py", "parser_guard.py", "parser_worker.py", "document_parser.py", "processing.py", "generic.py", "readers.py", "native.py", "errors.py", "coverage_policy.py", "date_bounds.py", "knowledge/date-range.json", "publication_policy.py", "worker.py", "reconcile.py")
            if (root / name).is_file()}


IMPLEMENTATION_AT_LOAD = implementation_identity()


def _profile_attachment(files):
    profiles = []
    for file in files:
        if Path(file["name"]).suffix.lower() == ".json" and file["size"] <= 262144:
            try:
                candidate = json.loads(Path(file["path"]).read_text(encoding="utf-8-sig"))
            except (UnicodeError, ValueError):
                continue
            if isinstance(candidate, dict) and candidate.get("profile_version") == "generic-v1":
                profiles.append(candidate)
    if len(profiles) > 1:
        raise NeedsInput("Several mapping profiles were supplied.",
                         ["Keep exactly one reviewed mapping profile for this source bundle."])
    return profiles[0] if profiles else None


def process_bundle(files, work_dir, options, progress, check_cancelled):
    from .native import identify_bundle, process_native
    from .generic import process_generic, describe_unknown

    code = implementation_identity()
    if code != IMPLEMENTATION_AT_LOAD:
        raise ValidationFailure("Processing code changed since this worker started; restart the local import worker before retrying.")
    if not files:
        raise NeedsInput("No files were uploaded.", ["Upload a complete source bundle."])
    if len(files) > 16:
        raise ValidationFailure("A local import accepts at most 16 files.")
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    for file in files:
        check_cancelled()
        path = Path(file["path"])
        if path.is_symlink() or not path.is_file():
            raise ValidationFailure("An uploaded input is no longer an immutable regular file.")
        if path.stat().st_size != file["size"] or digest_file(path) != file["sha256"]:
            raise ValidationFailure("Uploaded bytes changed after receipt; upload a fresh copy.")
    progress("profiling", "Verifying source structure and complete file combinations.")
    bundle = identify_bundle(files)
    if bundle is not None:
        # Recognition takes priority over user-supplied profiles: a generic
        # mapping cannot bypass VIC's four-file or exact-policy constraints.
        if options.get("source_hint"):
            hint = str(options["source_hint"]).upper()
            state = str(bundle.get("state", "")).upper()
            if hint not in (state, str(bundle.get("source_id", "")).upper(), "AUTO"):
                raise NeedsInput("The selected state conflicts with the file structure.",
                                 [f"The files identify as {state}; correct the selected state."])
        result = process_native(files, work_dir, options, progress, check_cancelled)
    else:
        profile = options.get("profile") or _profile_attachment(files)
        if profile:
            result = process_generic(files, work_dir, {**options, "profile": profile},
                                     progress, check_cancelled)
        else:
            description = describe_unknown(files)
            raise NeedsInput("This source needs a reviewed mapping before it can run.",
                             description["questions"], description)

    check_cancelled()
    for file in files:
        path = Path(file["path"])
        if path.is_symlink() or not path.is_file() or path.stat().st_size != file["size"] or digest_file(path) != file["sha256"]:
            raise ValidationFailure("Uploaded bytes changed during processing; upload a fresh copy.")
        check_cancelled()
    if not result.get("qa") or any(q.get("status") not in ("pass", "limited") for q in result["qa"]):
        raise ValidationFailure("The candidate did not satisfy its quality gates.", result.get("qa"))
    if any(q.get("status") == "limited" and q.get("code") != "QA07_LOCATION" for q in result["qa"]):
        raise ValidationFailure("Only the declared location limitation may be published as limited.", result["qa"])
    if implementation_identity() != code:
        raise ValidationFailure("Processing code changed during this attempt; retry with one immutable worker version.")
    identity = {"engine": "arsia-local-import-v1", "source_id": result["source_id"],
                "profile_id": result["profile_id"], "profile_version": result["profile_version"],
                "source_fingerprint": result["fingerprint"], "implementation": code}
    result["fingerprint"] = canonical_digest(identity)
    result.setdefault("evidence", {}).update({"implementation": code,
        "fingerprint_contract": "arsia-local-import-v1; separate from historical E SQL FP1",
        "mode": "local-test", "cross_state_pooling": False})
    result["mode"] = "local-test"
    from .coverage_policy import VERSION as COVERAGE_VERSION
    result['temporal_coverage'] = {'version': COVERAGE_VERSION,
        'complete_intervals': [{'from':'2020-01-01','to':'2024-12-31'}] if bundle is not None else [],
        'basis': 'hash-pinned-native-dataset-snapshot' if bundle is not None else 'observed-records-only',
        'limitation': 'Dataset reporting scope only; not complete population coverage or deletion authority.'}
    from .publication_policy import seal_deterministic
    seal_deterministic(result, files, native_bundle=bundle)
    evidence = {k: v for k, v in result.items() if k not in ("canonical_path", "units_path")}
    (work_dir / "result.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2,
                                                   allow_nan=False) + "\n")
    return result
