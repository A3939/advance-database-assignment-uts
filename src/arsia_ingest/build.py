"""Installed team bindings and a reproducible three-source S0 build request."""
from importlib.resources import files
from pathlib import Path

from .components import bindings
from .fingerprint import FP1Operation
from .manifest import build_manifest, digest_inventory, read_json, s0_definitions
from .models import IntakeError
from .publication import publish
from .runner import BuildModules, ModuleBinding


FP1 = FP1Operation("e", "fp1", "e03-fp1-v1.1", 160015, "sql/e/fp1.sql")
PUBLISH_VERSION = "e06-publication-8092765"


def fp1_sql():
    """Return E's packaged SQL for deployment by the database owner."""
    return files("arsia_ingest").joinpath("sql/fp1.sql").read_text(encoding="utf-8")


def build_modules():
    return BuildModules(**bindings(), publish=ModuleBinding(
        publish, "src/arsia_ingest/publication.py", PUBLISH_VERSION))


def build_inventory(project_root):
    """Check the reviewed build inventory before freezing actual file bytes."""
    root = Path(project_root).resolve()
    declared = read_json(root / "config/build-inventory.json")
    inventory = {"components": declared["components"],
                 "schema_files": [row["path"] for row in declared["schema_files"]]}
    actual = digest_inventory(root, inventory)
    if any(actual[group] != declared[group] for group in actual):
        raise IntakeError("MANIFEST_VERSION_CHANGED", "Build files differ from the reviewed inventory")
    return inventory


def s0_request(*, connect, project_root, prepared_run, evidence_root,
               prepared_by="ARSIA S0 build", analysis=None, contract_path=None):
    """Freeze generated synthetic definitions with all real build components."""
    root = Path(project_root).resolve()
    contract = Path(contract_path) if contract_path else root / "tests/fixtures/s0/contract.json"
    definitions = s0_definitions(contract)
    if analysis is not None:
        definitions["analysis"] = analysis
    if {s["jurisdiction_code"] for s in definitions["sources"]} != {"NSW", "VIC", "QLD"}:
        raise IntakeError("BUILD_SCOPE", "This recipe supports the three-source S0 contract")
    inventory = build_inventory(root)
    origins = {entry["id"]: {"download_url": None, "evidence_ref": "B07 synthetic contract"}
               for entry in definitions["contracts"]}
    manifest = build_manifest(
        prepared_run, **definitions, inventory=inventory, project_root=root,
        qa_contract=read_json(root / "config/qa-team-v1.1.json"),
        prepared_by=prepared_by, origins=origins)
    return dict(connect=connect, prepared_run=prepared_run, manifest=manifest,
                project_root=root, inventory=inventory, modules=build_modules(),
                fp1=FP1, evidence_root=evidence_root,
                supported_mappings=definitions["mappings"])
