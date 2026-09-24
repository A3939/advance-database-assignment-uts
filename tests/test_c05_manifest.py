"""Transport-shape compatibility only: no fabricated build or FP1 claim."""

from copy import deepcopy
import json
from pathlib import Path
import pytest
from test_manifest import build, assemble
from test_c04_vic_projection import official_manifest
from arsia_ingest.manifest import validate_manifest
from arsia_c.projections.source_contracts import qld_definitions


def test_qld_contract_fits_b09_existing_manifest_shape(build):
    m = assemble(build).as_dict()  # Existing test-only inventory fixture.
    q = official_manifest("QLD")
    for name in ("dataset_kind", "analysis", "sources", "files"):
        m[name] = q[name]
    for name in ("contracts", "mappings", "severity"):
        m["rules"][name] = q["rules"][name]
    f = q["files"][0]
    digest = f["file_sha256"]
    m["provenance"][
        "prepared_by"
    ] = "transport-schema-test; not an official intake receipt"
    m["provenance"]["files"] = [
        {
            "resource_id": f["resource_id"],
            "file_sha256": digest,
            "archive_relpath": f"official/archive/sha256/{digest[:2]}/{digest}",
            "original_filename": "qld_crash_locations.csv",
            "download_url": "https://www.data.qld.gov.au/dataset/crash-data-from-queensland-roads",
            "evidence_ref": "Schema fixture only; native bytes are tested by tools/check_c45_native.py",
        }
    ]
    validate_manifest(m)


def test_qld_review_matches_legacy_qa01_binding():
    d = qld_definitions()
    c = d["contracts"][0]
    f = c["content"]["input"]
    identity = c["content"]["identity"]
    r = json.loads(
        (
            Path(__file__).resolve().parents[1]
            / "docs/role-c/c05-qld-source-review.json"
        ).read_text(encoding="utf-8")
    )
    assert (
        r["contract_version"] == c["version"] and r["file_sha256"] == f["file_sha256"]
    )
    assert all(r[k] == identity[k] for k in ("release_label", "release_scope"))
    assert (
        r["status"] == "confirmed"
        and r["bundle_confirmed"] is True
        and r["unresolved"] == []
    )
    assert r["reviewed_by"] and r["references"]
