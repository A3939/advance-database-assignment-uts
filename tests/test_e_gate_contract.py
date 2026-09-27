"""VIC policy acceptance checks only; these do not replay official data."""
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from arsia_ingest.manifest import FrozenManifest, REQUIRED_CHECKS, validate_manifest
from arsia_ingest.models import IntakeError
from arsia_ingest.publication_checks import Requirements
from arsia_ingest.vic_restricted import PINS, vic_restricted_definitions

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def restricted():
    definitions = vic_restricted_definitions()
    files = [c["content"]["input"] for c in definitions["contracts"]]
    paths = [*PINS, "sql/e/fp1.sql", "src/arsia_ingest/publication.py", "src/arsia_ingest/publication_checks.py"]
    value = {
        "contract_version": "team-v1.1", "dataset_kind": "official",
        "analysis": definitions["analysis"], "sources": definitions["sources"], "files": files,
        "rules": {k: definitions[k] for k in ("contracts", "mappings", "severity", "qa_contract")},
        "required_checks": list(REQUIRED_CHECKS),
        "provenance": {"prepared_at": "2026-09-26T00:00:00Z", "prepared_by": "E policy unit test; no official replay",
                       "files": [{"resource_id": f["resource_id"], "file_sha256": f["file_sha256"],
                                  "archive_relpath": f"official/archive/sha256/{f['file_sha256'][:2]}/{f['file_sha256']}",
                                  "original_filename": f["resource_role"] + ".csv",
                                  "download_url": "https://opendata.transport.vic.gov.au/",
                                  "evidence_ref": "Pinned policy identity, not an execution receipt."} for f in files]},
    }
    value["rules"]["code_files"] = [{"path": p, "sha256": hashlib.sha256((ROOT/p).read_bytes()).hexdigest()} for p in sorted(paths)]
    value["rules"]["schema_files"] = [{"path": str(p.relative_to(ROOT)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                                       for p in sorted((ROOT/"sql/migrations").glob("*.sql"))]
    return FrozenManifest(json.dumps(value))


def test_restricted_expectations_remain_file_bound(restricted):
    checks = Requirements(None, str(uuid4()), restricted.as_dict())
    assert len(checks.restricted) == 4
    for file in checks.files.values():
        n, metrics = checks.expected("QA01_INPUT", "file:" + file["resource_id"])
        assert n == 1 and not metrics["bundle_confirmed"] and not metrics["contract_confirmed"]
        assert metrics["profile_approved"] and metrics["case_register_match"]
    n, metrics = checks.expected("QA04_AUXILIARY", "resource:official_vic_person")
    assert n == checks.files["official_vic_person"]["raw_count"]
    assert metrics["nonblank_unmatched_count"] == 39 and metrics["declared_count_delta"] is None
    n, metrics = checks.expected("QA05_SEMANTICS", "source:official_vic")
    assert n == 1439470 and metrics["undefined_category_count"] == 879
    assert metrics["unconfirmed_definition_count"] == 10 and metrics["disposition_match"]


@pytest.mark.parametrize("change", ["files", "years", "case", "output", "protocol"])
def test_restricted_profile_cannot_be_loosened(restricted, change):
    value = restricted.as_dict()
    if change == "files": value["files"][0]["file_sha256"] = "0"*64
    elif change == "years": value["analysis"]["year_from"] = 2019
    elif change == "case": value["rules"]["mappings"][0]["content"]["cases"].clear()
    elif change == "output": value["rules"]["mappings"][0]["content"]["retention"]["vic_map_eligible"] = True
    else: value["rules"]["qa_contract"]["version"] = "team-v1.1"
    with pytest.raises(IntakeError):
        validate_manifest(value)
