"""Adapt the existing official source decisions to B09's frozen interface."""

from copy import deepcopy
from pathlib import Path

from arsia_c.projections.source_contracts import qld_definitions

from .manifest import SOURCE_FIELDS, _digest, read_json
from .models import IntakeError
from .vic_restricted import vic_restricted_definitions


ADMISSION_PATH = "config/official-inputs-v1.json"
NSW_PATH = "config/official-nsw-v1.json"
NSW_SHA256 = "46d6fd0966338b51fd232c77f343b0f5237353f149decd2377da83de909597cf"
EVIDENCE_PATHS = {
    NSW_PATH,
    "config/c05-qld-official-v1.json",
    "docs/sources/evidence/nsw/nsw-source-confirmation-2026-09-23.json",
    "docs/sources/evidence/nsw/nsw-source-validation-2026-09-23.json",
    "docs/sources/evidence/vic/official-package-2026-09-17.json",
    "docs/sources/evidence/official-decisions-2026-09-23/nsw-review.json",
    "docs/sources/evidence/official-decisions-2026-09-23/qld-review.json",
}


def _admission(project_root):
    root = Path(project_root).resolve()
    admission = read_json(root / ADMISSION_PATH)
    if admission.get("version") != "official-inputs-v1":
        raise IntakeError("OFFICIAL_DEFINITION", "Unsupported official input version")
    pins = admission["pinned_files"]
    if len(pins) != len(EVIDENCE_PATHS) or {p["path"] for p in pins} != EVIDENCE_PATHS:
        raise IntakeError("OFFICIAL_DEFINITION", "Official evidence inventory is incomplete or duplicated")
    for pin in pins:
        if _digest(root, pin["path"]) != pin["sha256"]:
            raise IntakeError("OFFICIAL_DEFINITION", "Official source evidence changed", path=pin["path"])
    if _digest(root, NSW_PATH) != NSW_SHA256:
        raise IntakeError("OFFICIAL_DEFINITION", "NSW A04 source contract changed; review a new version")
    return admission


def _nsw_definitions(project_root, admission):
    original = read_json(Path(project_root) / NSW_PATH)
    if original["status"] != "confirmed" or original["dataset_kind"] != "official":
        raise IntakeError("OFFICIAL_DEFINITION", "NSW needs A04's confirmed official contract")
    source = {key: original["source"][key] for key in SOURCE_FIELDS}
    categories = original["severity"]["categories"]
    severity = [
        {"source_id": source["source_id"],
         **{k: item[k] for k in ("severity_code", "severity_label", "is_fatal_crash")},
         "definition_version": original["severity"]["definition_version"],
         "definition_text": item["definition"]}
        for item in categories
    ]
    review = admission["nsw_integration_review"]
    mappings = []
    mapping_ids = {}
    for item in original["mappings"]:
        adapted = deepcopy(item)
        adapted["id"] = item["id"].replace("-", "_")
        adapted["version"] = item["version"] + "-b09-r1"
        adapted["content"]["source_mapping_id"] = item["id"]
        if item["id"] == "nsw-crash-projection-v1":
            crash = next(c for c in original["contracts"] if item["id"] in c["mapping_ids"])
            declared = crash["semantics"].get("declared_unit_count")
            child = next((c for c in original["contracts"]
                          if isinstance(declared, dict) and c["resource_id"] == declared.get("resource_id")), None)
            field = item["content"].get("declared_unit_count")
            relation = child["identity"].get("parent") if child else None
            if (field != "No. of traffic units involved" or not isinstance(declared, dict)
                    or declared.get("field") != field or field not in crash["input"]["header"]
                    or child is None or child["input"]["entity_kind"] != "unit"
                    or child["input"]["source_id"] != crash["input"]["source_id"]
                    or not isinstance(relation, dict) or relation.get("resource_id") != crash["resource_id"]):
                raise IntakeError("OFFICIAL_DEFINITION", "NSW declared count needs its explicit Crash/Traffic Unit relation")
            # A04 states the field in the mapping and the target in the contract.
            adapted["content"]["source_declared_unit_count"] = field
            adapted["content"]["declared_unit_count"] = {
                "field": field, "resource_id": declared["resource_id"],
            }
            adapted["content"]["native_severity_codes"] = {
                c["native_value"]: c["severity_code"] for c in categories if c["native_value"] is not None
            }
        mappings.append(adapted)
        mapping_ids[item["id"]] = adapted["id"]
    confirmation = {
        **deepcopy(original["confirmation"]),
        "reviewed_by": review["reviewed_by"],
        "checked_at": review["checked_at"],
        "licence": original["source"]["licence"]["name"],
        "source_checked_at": original["confirmation"]["checked_at"],
        "source_reviewed_by": original["confirmation"]["reviewed_by"],
        "source_contract_version": original["source_contract_version"],
        "integration_scope": review["scope"],
        "references": list(dict.fromkeys(original["confirmation"]["references"] + review["references"])),
    }
    contracts = []
    for item in original["contracts"]:
        identity = deepcopy(item["identity"])
        identity["resource_ids"] = identity.pop("selected_resource_ids")
        identity["coverage"] = deepcopy(original["analysis"])
        identity["bundle_basis"] = original["source"]["compatibility"]["basis"]
        semantics = deepcopy(item["semantics"])
        semantics.update(
            severity_codes=[s["severity_code"] for s in severity],
            severity_definition_version=original["severity"]["definition_version"],
        )
        contracts.append({
            "id": item["resource_id"],
            "version": item["contract_version"] + "-b09-r1",
            "status": item["status"],
            "mapping_ids": [mapping_ids[mid] for mid in item["mapping_ids"]],
            "content": {
                "input": deepcopy(item["input"]),
                "identity": identity,
                "semantics": semantics,
                "snapshot": {"policy": item["snapshot"]["policy"], "change": item["snapshot"]["change_statement"]},
                "confirmation": deepcopy(confirmation),
            },
        })
    return {"sources": [source], "contracts": contracts,
            "mappings": mappings, "severity": severity,
            "analysis": {k: original["analysis"][k] for k in ("year_from", "year_to")}}


def official_definitions(project_root):
    """Return seven pinned input contracts; VIC restrictions remain unchanged."""
    admission = _admission(project_root)
    nsw = _nsw_definitions(project_root, admission)
    qld = qld_definitions()
    if read_json(Path(project_root) / "config/c05-qld-official-v1.json") != qld:
        raise IntakeError("OFFICIAL_DEFINITION", "Installed C05 and project QLD definitions differ")
    vic = vic_restricted_definitions()
    if nsw["analysis"] != qld["analysis"] or nsw["analysis"] != vic["analysis"]:
        raise IntakeError("OFFICIAL_DEFINITION", "Official analysis scopes differ")
    result = {key: [item for definitions in (nsw, vic, qld) for item in definitions[key]]
              for key in ("sources", "contracts", "mappings", "severity")}
    result.update(analysis=nsw["analysis"], qa_contract=vic["qa_contract"])
    return result


def official_source_reviews(project_root):
    """Supply existing NSW/QLD review decisions. VIC uses its restricted policy."""
    definitions = official_definitions(project_root)
    reviews = []
    for contract in definitions["contracts"]:
        content = contract["content"]
        if content["input"]["source_id"] == "official_vic":
            continue
        reviews.append({
            "resource_id": contract["id"], "contract_version": contract["version"],
            "file_sha256": content["input"]["file_sha256"],
            **{k: content["identity"][k] for k in ("release_label", "release_scope")},
            **{k: content["confirmation"][k]
               for k in ("status", "bundle_confirmed", "reviewed_by", "references", "unresolved")},
        })
    return deepcopy(reviews)


def official_origins(project_root):
    """Use archived download locations, without fetching replacement exports."""
    admission = _admission(project_root)
    expected = {c["id"] for c in official_definitions(project_root)["contracts"]}
    if set(admission["origins"]) != expected:
        raise IntakeError("OFFICIAL_DEFINITION", "Official provenance must cover exactly seven resources")
    return deepcopy(admission["origins"])
