"""Admission changes and synthetic files cannot silently enter an official build."""
import json
from pathlib import Path
import shutil

import pytest

from arsia_ingest.build import build_inventory, official_request
from arsia_ingest.models import IntakeError
from arsia_ingest.pipeline import prepare

ROOT = Path(__file__).resolve().parents[1]


def no_connection():
    pytest.fail("Admission must fail before opening a database connection")


@pytest.mark.parametrize("relative", ["config/official-inputs-v1.json",
                                      "config/official-nsw-v1.json",
                                      "config/native-inputs.json"])
def test_unreviewed_official_config_change_is_rejected(tmp_path, relative):
    inventory = build_inventory(ROOT)
    paths = {p for group in inventory["components"].values() for p in group}
    paths.update(inventory["schema_files"])
    paths.add("config/build-inventory.json")
    for path in paths:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, target)
    changed = tmp_path / relative
    value = json.loads(changed.read_text(encoding="utf-8"))
    value["unreviewed_change"] = True
    changed.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(IntakeError) as caught:
        official_request(connect=no_connection, project_root=tmp_path,
                         prepared_run=tmp_path / "not-read", evidence_root=tmp_path / "evidence")
    assert caught.value.code == "MANIFEST_VERSION_CHANGED"


def test_real_s0_preparation_is_not_an_official_snapshot(tmp_path):
    prepared = prepare(ROOT / "tests/fixtures/s0/config.json", tmp_path / "intake")
    assert prepared["status"] == "prepared"
    with pytest.raises(IntakeError):
        official_request(connect=no_connection, project_root=ROOT,
                         prepared_run=prepared["run_dir"], evidence_root=tmp_path / "evidence")
