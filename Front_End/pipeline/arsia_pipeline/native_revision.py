"""Host-owned permission context for a changed complete native export.

This module does not grant QA admission. It proves only the revision route and
one reserved logical source identity. Generated contracts cannot manufacture it.
"""
from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from . import native
from .errors import NeedsInput, ValidationFailure
from .readers import inspect_file

VERSION = "native-revision-snapshot-1"
REFERENCE = {"NSW": "official-nsw-v1.json", "QLD": "c05-qld-official-v1.json", "VIC": "vic-restricted-inputs-v1.json"}
GRAINS = {"crash": "crash", "traffic_unit": "unit", "vehicle": "unit", "person": "casualty", "node": "lookup"}


class NativeBoundary(NeedsInput):
    """A recognized native package must not fall through to generic autonomy."""


@dataclass(frozen=True)
class NativeRevision:
    # Immutable serialized form prevents nested-dict mutation after dispatch.
    receipt_json: str

    @property
    def receipt(self):
        return json.loads(self.receipt_json)

    @property
    def source_id(self):
        return self.receipt["source_id"]

    @property
    def fingerprint(self):
        return hashlib.sha256(self.receipt_json.encode()).hexdigest()

    def public(self):
        return {**self.receipt, "transition_sha256": self.fingerprint}


@dataclass(frozen=True)
class NativeRoute:
    kind: str
    context: NativeRevision | None = None


def classify_native_route(files, check_cancelled=lambda: None):
    """Distinguish exact pinned input from unrelated unknown-source input."""
    if not _looks_native(files, check_cancelled):
        return NativeRoute("unknown")
    context = detect_revision(files, check_cancelled)
    return NativeRoute("revision", context) if context else NativeRoute("pinned")


def stable(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def implementation():
    folder = Path(__file__).parent
    return {name: hashlib.sha256((folder/name).read_bytes()).hexdigest()
            for name in ("native_revision.py", "native.py", "readers.py")}


def _looks_native(files, check_cancelled):
    # Unknown formats remain available to the autonomous intake tools. Only
    # observed native column signatures establish the protected native boundary.
    for file in files:
        check_cancelled()
        if native._supplement(file):
            continue
        try:
            tables = inspect_file(file)
        except (NeedsInput, ValidationFailure):
            if not file.get("archive_file_id"):
                continue
            # The frozen Excel reader checks the physical extension; archive
            # members are intentionally stored as .input. Inspect their actual
            # bytes with the bounded intake reader before deciding unknown.
            from .intakereaders import detect_tables
            try:
                tables = detect_tables(file)
            except (NeedsInput, ValidationFailure):
                continue
        if any(native._resembles_native(table["header"]) for table in tables):
            return True
    return False


def detect_revision(files, check_cancelled=lambda: None):
    """Return context for a complete hash drift, None for exact/unknown input.

    A recognizable incomplete, mixed or structurally changed native bundle
    raises NativeBoundary with the original concrete question.
    """
    if not _looks_native(files, check_cancelled):
        return None
    try:
        bundle = native.identify_bundle(files)
    except (NeedsInput, ValidationFailure) as exc:
        if isinstance(exc, ValidationFailure):
            raise NativeBoundary("A native archive member cannot use the frozen reader in its extracted storage form. Upload the original native files individually; the source cannot fall through to an unrelated autonomous profile.",
                ["Upload every original native data file from the archive together."],
                {"route":"native_archive_boundary","generic_fallback_allowed":False}) from None
        raise NativeBoundary(str(exc), exc.questions,
            {**exc.details, "route": "native_boundary", "generic_fallback_allowed": False}) from None
    if bundle is None:
        return None
    upstream, references = native._references()
    selected = bundle["files_by_role"]
    inputs = []
    for file in files:
        check_cancelled()
        path = Path(file["path"])
        if path.is_symlink() or not path.is_file() or path.stat().st_size != file["size"] or native._sha(path, check_cancelled) != file["sha256"]:
            raise ValidationFailure("Uploaded native revision bytes changed after receipt; this is not a source revision.")
        match = next((item for item in selected.values() if item["file"]["id"] == file["id"]), None)
        inputs.append({"file_id": file["id"], "name": file["name"], "sha256": file["sha256"], "size": file["size"],
                       "role": match["spec"]["resource_role"] if match else "supporting_evidence"})
    changed = [{"role": role, "file_id": item["file"]["id"], "expected_sha256": item["spec"]["expected_sha256"], "actual_sha256": item["file"]["sha256"]}
               for role,item in selected.items() if item["file"]["sha256"] != item["spec"]["expected_sha256"]]
    if not changed:
        return None
    original = references[REFERENCE[bundle["state"]]]
    source = original.get("source") or original["sources"][0]
    receipt = {
        "route": "native_revision", "transition_version": VERSION, "source_id": bundle["source_id"], "jurisdiction": bundle["state"],
        "baseline_profile_id": bundle["profile_id"], "baseline_profile_version": native.VERSION,
        "baseline_coverage": {"from": f"{native.YEARS[0]}-01-01", "to": f"{native.YEARS[1]}-12-31"},
        "source_identity": {key: source[key] for key in ("source_name", "publisher", "dataset_url") if key in source},
        "required_resources": [{"role": role, "grain": GRAINS[role], "file_id": item["file"]["id"],
            "resource_id": item["spec"]["resource_id"], "header": item["table"]["header"], "format": item["table"]["format"], "sheet": item["table"]["sheet"]}
            for role,item in sorted(selected.items())],
        "inputs": sorted(inputs, key=lambda value: value["file_id"]), "changed_resources": sorted(changed, key=lambda value: value["role"]),
        "frozen_references": {item["path"]: item["sha256"] for item in upstream["files"]},
        "upstream_commit": upstream["commit"], "implementation": implementation(),
        "allowed_update_modes": ["snapshot"], "exceptions_inherited": False,
        "instruction": "Investigate a new complete official snapshot under this exact logical source. Preserve every required table. Use strict full QA; frozen exception cases are not authority for new bytes. No generic override or model confirmation grants admission.",
    }
    return NativeRevision(stable(receipt))


def validate_revision_context(context, files, check_cancelled=lambda: None):
    if not isinstance(context, NativeRevision):
        raise ValidationFailure("Reserved native identities require a host-created revision context")
    original_ids = {entry["file_id"] for entry in context.receipt["inputs"]}
    original_files = [file for file in files if file["id"] in original_ids]
    if len(original_files) != len(original_ids):
        raise ValidationFailure("A native revision original input is missing or duplicated")
    current = detect_revision(original_files, check_cancelled)
    if current is None or current.receipt_json != context.receipt_json:
        raise ValidationFailure("Native revision context no longer matches immutable inputs and frozen profile")
    return current.receipt


def validate_revision_contract(context, contract, files, current_coverage=None, check_cancelled=lambda: None):
    """Constrain routing, identity and coverage before trusted full source QA.

    Official document receipt/semantic grounding and independent projection are
    still required by trusted_qa; matching these structural checks is not proof.
    """
    receipt = validate_revision_context(context, files, check_cancelled)
    source, update = contract.get("source", {}), contract.get("update", {})
    if source.get("source_id") != receipt["source_id"] or source.get("jurisdiction") != [receipt["jurisdiction"]] or source.get("grain") != "crash":
        raise ValidationFailure("A native revision can authorize only its proven logical source, jurisdiction and crash grain")
    if " ".join(str(source.get("publisher", "")).casefold().split()) != " ".join(receipt["source_identity"]["publisher"].casefold().split()):
        raise NeedsInput("The revision publisher differs from the frozen official source identity; obtain matching official identity evidence.")
    url = urlsplit(str(source.get("dataset_url", "")))
    if url.scheme != "https" or not (url.hostname or "").endswith("." + receipt["jurisdiction"].lower() + ".gov.au"):
        raise NeedsInput("A native revision requires the matching state's official dataset URL and publisher evidence.")
    if update.get("mode") != "snapshot":
        raise NeedsInput("Native-to-v2 revision currently supports a complete snapshot only. Supply a full export covering the existing history; partition/incremental mixing is not admitted.")
    coverage = source.get("coverage", {})
    try:
        start, end = date.fromisoformat(coverage["from"]), date.fromisoformat(coverage["to"])
    except (KeyError, TypeError, ValueError):
        raise NeedsInput("Provide official coverage evidence for the full native revision snapshot.") from None
    if start > end:
        raise ValidationFailure("Revision coverage dates are reversed")
    for previous in (receipt["baseline_coverage"], current_coverage):
        if previous and (coverage["from"] > previous["from"] or coverage["to"] < previous["to"]):
            raise NeedsInput("This native revision snapshot would remove published history. Supply a full snapshot covering the frozen profile and current release.")
    if (update.get("from"), update.get("to")) != (coverage["from"], coverage["to"]):
        raise ValidationFailure("The complete snapshot update interval must equal its evidenced source coverage")
    resources = contract.get("resources", [])
    for required in receipt["required_resources"]:
        matches = [resource for resource in resources if resource.get("file_id") == required["file_id"]]
        if len(matches) != 1:
            raise NeedsInput("The revised native profile must declare exactly one canonical resource for each original required table.",
                             ["Declare the complete native " + required["role"] + " resource."], {"missing_role": required["role"]})
        if required["grain"] == "lookup":
            raise NeedsInput("This VIC revision includes the required node lookup table. Canonical-v2 has no independently validated lookup grain yet; the node table cannot be discarded or converted into synthetic observations.")
        if matches[0].get("grain") != required["grain"]:
            raise ValidationFailure("A native revision cannot change a required resource's fact grain")
    return {"status": "route_verified", "transition_sha256": context.fingerprint, "source_id": context.source_id,
            "exceptions_inherited": False, "allowed_update_mode": "snapshot"}
