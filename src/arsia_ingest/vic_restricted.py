"""Transport and evidence checks for the adopted, file-bound VIC profile."""
from __future__ import annotations

from copy import deepcopy
import hashlib
from importlib.resources import files
import json
from pathlib import Path

from .models import IntakeError


PROTOCOL = "team-v1.1-vic-r1"
PROFILE = "vic-accident-only-2020-2024-v1"
MAPPING_ID = "official_vic_restricted_use"
ROOT = Path(__file__).resolve().parents[2]
PINS = {
    "config/vic-restricted-use-v1.json": "bc892d07f81f51fc2859cccd9c1302e4b1ade22240bd36f8fe118d95e861ec40",
    "config/vic-restricted-inputs-v1.json": "7eaf1e4834c6dcdb8c74e933aaff602dcaad0094e72f5508fe64ab3a34b583a3",
    "config/qa-team-v1.1-vic-r1.json": "859a5684b2a276cd69509877ea4660344fecac4ca6e5041de77280d40ebaca6b",
}
QA_TEXT_SHA256 = "292c8d3562a8bef9c1a1572a5dc1e2f18e95be936b2857a2bc60eb153174f553"


def _fail(message):
    raise IntakeError("VIC_PROFILE", message)


def _bytes(root, relative, expected):
    root = Path(root).resolve()
    path = root / relative
    if (not path.resolve().is_relative_to(root)
            or any(p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(root))):
        _fail("VIC policy and evidence must stay inside the repository without symlinks")
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise IntakeError("VIC_EVIDENCE", "Required VIC policy or evidence is missing", path=relative) from exc
    if hashlib.sha256(data).hexdigest() != expected:
        raise IntakeError("VIC_EVIDENCE", "VIC policy or evidence bytes changed", path=relative)
    return data


def vic_restricted_definitions():
    """Return independent copies of the approved input definitions, not a build."""
    values = {path: json.loads(_policy_bytes(path, sha)) for path, sha in PINS.items()}
    policy = values["config/vic-restricted-use-v1.json"]
    return {
        **values["config/vic-restricted-inputs-v1.json"],
        "mappings": [{"id": MAPPING_ID, "version": PROFILE, "content": policy}],
        "qa_contract": values["config/qa-team-v1.1-vic-r1.json"],
    }


def _policy_bytes(path, expected):
    package = files("arsia_ingest")
    relative = "policies/" + Path(path).name
    if isinstance(package, Path):
        return _bytes(package, relative, expected)
    try:
        data = package.joinpath(relative).read_bytes()
    except OSError as exc:
        raise IntakeError("VIC_EVIDENCE", "Packaged VIC policy is missing", path=path) from exc
    if hashlib.sha256(data).hexdigest() != expected:
        raise IntakeError("VIC_EVIDENCE", "Packaged VIC policy bytes changed", path=path)
    return data


def validate_profile(value):
    """Only the new protocol can use restricted contracts; other sources stay unchanged."""
    rules = value["rules"]
    active = rules["qa_contract"].get("version") == PROTOCOL
    selected = [f for f in value["files"] if f["source_id"] == "official_vic"]
    if not active:
        if any(m.get("id") == MAPPING_ID for m in rules["mappings"]):
            _fail("The VIC restricted mapping requires its adopted QA protocol")
        return set()
    definitions = vic_restricted_definitions()
    if value["dataset_kind"] != "official" or value["analysis"] != definitions["analysis"]:
        _fail("The VIC profile is restricted to official data and 2020-2024")
    expected = {c["id"]: c for c in definitions["contracts"]}
    if sorted(selected, key=lambda f: f["resource_id"]) != sorted(
            [c["content"]["input"] for c in expected.values()], key=lambda f: f["resource_id"]):
        _fail("Select all four exact VIC file identities, headers and counts")
    if [s for s in value["sources"] if s["source_id"] == "official_vic"] != definitions["sources"]:
        _fail("VIC source/release definitions differ from the adopted profile")
    if [m for m in rules["mappings"] if m.get("id") == MAPPING_ID] != definitions["mappings"]:
        _fail("Freeze the complete adopted VIC policy, including exact cases and dispositions")
    for contract in rules["contracts"]:
        if contract["id"] in expected and contract != expected[contract["id"]]:
            _fail("VIC input contracts must retain the approved restrictions and unresolved issues")
        if contract["id"] not in expected and MAPPING_ID in contract["mapping_ids"]:
            _fail("The VIC profile cannot approve another source")
    actual_severity = sorted([s for s in rules["severity"] if s["source_id"] == "official_vic"], key=lambda s: s["severity_code"])
    if actual_severity != definitions["severity"]:
        _fail("VIC severity definitions must remain source-specific")
    inventory = {item["path"]: item["sha256"] for item in rules["code_files"]}
    if any(inventory.get(path) != sha for path, sha in PINS.items()):
        _fail("Include all three VIC profile configuration files in the actual code inventory")
    return set(expected)


def _evidence_path(original):
    prefix = "Reviews/VIC-source-followup-2026-09-23/"
    if original.startswith(prefix):
        return "docs/sources/evidence/vic/followup-2026-09-23/" + original.removeprefix(prefix)
    if original.startswith("Workspace_Github/"):
        return original.removeprefix("Workspace_Github/")
    basis = {
        "Resources/source/metadata/victoria_package.json": "victoria_package.json",
        "F/ARSIA-Team-Handoff/04-团队分工与验收.md": "team-04-v1.1.md",
        "F/ARSIA-Team-Handoff/05-来源与映射说明.md": "team-05-v1.1.md",
    }
    if original in basis:
        return "docs/sources/evidence/vic/followup-2026-09-23/basis/" + basis[original]
    _fail("Unrecognized VIC evidence reference")


def check_profile_evidence(root=None):
    """Hash the frozen register and cited files; do not claim semantic SQL was run."""
    root = ROOT if root is None else Path(root)
    for path, sha in PINS.items():
        _bytes(root, path, sha)
    policy = vic_restricted_definitions()["mappings"][0]["content"]
    case_bytes = (json.dumps(policy["cases"], sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
    if hashlib.sha256(case_bytes).hexdigest() != policy["case_set_digest"]["sha256"]:
        _fail("VIC case register digest differs")
    references = [(_evidence_path(item["path"]), item["sha256"]) for item in policy["source_evidence"].values()]
    references += [(_evidence_path(item["workspace_path"]), item["sha256"]) for item in policy["additional_basis"]]
    references.append((policy["previous_draft"]["path"], policy["previous_draft"]["sha256"]))
    for path, sha in references:
        _bytes(root, path, sha)
    return {"profile_id": PROFILE, "protocol_version": PROTOCOL,
            "case_set_sha256": policy["case_set_digest"]["sha256"],
            "files": [{"path": path, "sha256": sha} for path, sha in references],
            "semantic_checks_executed": False}


def input_expectations():
    return deepcopy(vic_restricted_definitions()["mappings"][0]["content"]["qa_expectations"]["QA01_INPUT"])
