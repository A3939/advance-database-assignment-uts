"""Real B inputs for D02 interface tests, with a partial code inventory."""
import hashlib
import json
from pathlib import Path

from arsia_ingest.manifest import FrozenManifest, REQUIRED_CHECKS, read_json, s0_definitions
from arsia_ingest.raw_load import _PreparedRun

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def definitions():
    return s0_definitions(ROOT / "tests/fixtures/s0/contract.json")


def fragment():
    return read_json(ROOT / "config/d02-inventory.json")


def interface_manifest(prepared):
    """Use the real constructor; this does not call the full-inventory freeze."""
    run = _PreparedRun(prepared)
    run.check_files()
    definition = definitions()
    paths = sorted(set(fragment()["components"]["dw"]) | {
        "src/arsia_ingest/manifest.py", "src/arsia_ingest/runner.py",
    })
    value = {
        "contract_version": "team-v1.1", "dataset_kind": "synthetic",
        "analysis": definition["analysis"], "sources": definition["sources"],
        "files": run.files,
        "rules": {k: definition[k] for k in ("contracts", "mappings", "severity")}
        | {"qa_contract": read_json(ROOT / "config/qa-team-v1.1.json"),
           "code_files": [{"path": p, "sha256": digest(ROOT / p)} for p in paths],
           "schema_files": [{"path": str(p.relative_to(ROOT)), "sha256": digest(p)}
                            for p in sorted((ROOT / "sql/migrations").glob("*.sql"))]},
        "required_checks": list(REQUIRED_CHECKS),
        "provenance": {
            "prepared_at": run.run["finished_at"],
            "prepared_by": "D02 interface test; partial inventory; no FP1 or publication",
            "files": [
                {k: run.provenance[f["resource_id"]][k] for k in
                 ("resource_id", "file_sha256", "archive_relpath", "original_filename")}
                | {"download_url": None, "evidence_ref": "tests/fixtures/s0/contract.json"}
                for f in run.files
            ],
        },
    }
    return FrozenManifest(json.dumps(value))


def partial_inventory():
    return {"components": fragment()["components"], "schema_files": [
        str(p.relative_to(ROOT)) for p in sorted((ROOT / "sql/migrations").glob("*.sql"))]}
