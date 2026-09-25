"""Small counterexamples for the VIC source checks."""
import csv
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("vic_profile", ROOT / "tools/profile_vic_inputs.py")
vic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vic)


def sample():
    return {
        "accident": [
            {"ACCIDENT_NO": "0001", "ACCIDENT_DATE": "2020-01-15", "NODE_ID": "N1",
             "SEVERITY": "1", "NO_OF_VEHICLES": "1", "NO_PERSONS_KILLED": "1",
             "NO_PERSONS_INJ_2": "1", "NO_PERSONS_INJ_3": "0", "NO_PERSONS_NOT_INJ": "0", "NO_PERSONS": "2"},
            {"ACCIDENT_NO": "0002", "ACCIDENT_DATE": "2025-12-31", "NODE_ID": "N2",
             "SEVERITY": "3", "NO_OF_VEHICLES": "1", "NO_PERSONS_KILLED": "0",
             "NO_PERSONS_INJ_2": "0", "NO_PERSONS_INJ_3": "1", "NO_PERSONS_NOT_INJ": "0", "NO_PERSONS": "1"},
        ],
        "vehicle": [{"ACCIDENT_NO": "0001", "VEHICLE_ID": "01", "VEHICLE_TYPE": "1"},
                    {"ACCIDENT_NO": "0002", "VEHICLE_ID": "01", "VEHICLE_TYPE": "1"}],
        "person": [{"ACCIDENT_NO": "0001", "PERSON_ID": "P1", "VEHICLE_ID": "01"},
                   {"ACCIDENT_NO": "0001", "PERSON_ID": "P2", "VEHICLE_ID": "01"},
                   {"ACCIDENT_NO": "0002", "PERSON_ID": "P1", "VEHICLE_ID": ""}],
        "node": [{"ACCIDENT_NO": "0001", "NODE_ID": "N1", "LATITUDE": "-37.8", "LONGITUDE": "144.9"},
                 {"ACCIDENT_NO": "0001", "NODE_ID": "N1", "LATITUDE": "-37.8000", "LONGITUDE": "144.9000"},
                 {"ACCIDENT_NO": "0002", "NODE_ID": "N2", "LATITUDE": "-37.9", "LONGITUDE": "145.0"}],
    }


def save(tmp_path, rows):
    config = {"resources": []}
    for name, records in rows.items():
        path = tmp_path / f"{name}.csv"
        header = list(records[0])
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=header)
            writer.writeheader()
            writer.writerows(records)
        config["resources"].append({"resource_id": f"official_vic_{name}", "path": path.name,
                                    "header": header, "expected_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    return path


def test_profile_preserves_observations_and_counts_declared_relationships(tmp_path):
    config = save(tmp_path, sample())
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    result = vic.profile(config)
    assert result["inputs_unchanged"] is True
    assert {k: v["row_count"] for k, v in result["files"].items()} == {
        "accident": 2, "vehicle": 2, "person": 3, "node": 3}
    assert result["accident"]["rows_by_year"] == {"2020": 1, "2025": 1}
    assert result["accident"]["date_min"] == "2020-01-15"
    assert result["accident"]["date_max"] == "2025-12-31"
    assert result["node_observations"]["duplicate_groups"] == 1
    assert result["node_observations"]["multiple_exact_coordinate_groups"] == 0
    assert result["findings"]["person_blank_vehicle_reference"]["count"] == 1
    for name in ("vehicle_missing_accident", "person_nonblank_vehicle_not_found",
                 "person_rows_vs_declared", "vehicle_rows_vs_declared"):
        assert result["findings"][name]["count"] == 0
    assert before == {p.name: p.read_bytes() for p in tmp_path.iterdir()}


def test_profile_reports_bad_keys_counts_dates_and_coordinates(tmp_path):
    rows = sample()
    rows["accident"][1].update(ACCIDENT_DATE="2025-02-30", NO_PERSONS_KILLED="Unknown",
                               NO_OF_VEHICLES="-1", NO_PERSONS="")
    rows["vehicle"][1]["ACCIDENT_NO"] = "9999"
    rows["person"][1]["VEHICLE_ID"] = "99"
    rows["node"][1]["LATITUDE"] = "-37.80000001"
    rows["node"][2]["LATITUDE"] = "NaN"
    rows["accident"].append(dict(rows["accident"][0]))
    result = vic.profile(save(tmp_path, rows))
    assert result["files"]["accident"]["duplicate_key_groups"] == 1
    assert result["files"]["accident"]["duplicate_extra_rows"] == 1
    for name in ("invalid_accident_date", "vehicle_missing_accident",
                 "person_nonblank_vehicle_not_found", "node_invalid_or_missing_coordinates"):
        assert result["findings"][name]["count"] == 1
        assert result["findings"][name]["examples"][0]["row_locator"].startswith("csv:")
    assert result["accident"]["count_tokens_not_nonnegative_integers"]["NO_PERSONS"] == {"": 1}
    assert result["node_observations"]["multiple_exact_coordinate_groups"] == 1
    assert result["node_observations"]["groups_with_invalid_coordinates"] == 1
    assert result["node_observations"]["conflict_examples"][0]["accident_no"] == "0001"


def test_profile_rejects_changed_input_before_reporting(tmp_path):
    config = save(tmp_path, sample())
    path = tmp_path / "vehicle.csv"
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="hash does not match"):
        vic.profile(config)
