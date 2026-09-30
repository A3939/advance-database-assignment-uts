"""C07 output must satisfy C09 without losing the original Node checks."""

import csv
from decimal import Decimal, ROUND_DOWN, localcontext
from pathlib import Path
from uuid import UUID

import pytest

from arsia_c.canonical_validation import validate_values
from arsia_c.node_location import NodeObservation, resolve_location_update

ROOT = Path(__file__).resolve().parents[1]


def observation(latitude="-37.8", longitude="144.9", row=1, **keys):
    return NodeObservation(
        raw_record_id=str(UUID(int=row)),
        accident_no=keys.get("accident_no", "A1"),
        node_id=keys.get("node_id", "N1"),
        latitude_raw=latitude,
        longitude_raw=longitude,
        file_sha256="a" * 64,
        parser_version="csv-native-v1",
        row_locator=f"csv:{row}",
    )


def resolve(rows, **options):
    return resolve_location_update(
        rows, expected_accident_no=rows[0].accident_no,
        expected_node_id=rows[0].node_id, crs_confirmed=True,
        evidence_ref="synthetic:c07-regression", **options,
    )


def check_c09(update):
    validate_values({
        "severity_raw": "1", "severity_code": "1",
        "severity_definition_version": "synthetic-v1",
        "date_precision": "year", "occurrence_year": 2020,
        "occurrence_month": None, "occurrence_date": None,
        "is_fatal_crash": None, "fatality_count": None, "casualty_count": None,
        "fatal_crash_eligible": False, "fatality_eligible": False,
        "casualty_eligible": False, **update,
    }, "crash")


@pytest.mark.parametrize("crs", [None, "", "EPSG:4283", "EPSG:7855"])
def test_other_crs_keeps_crash_without_map_location(crs):
    update = resolve([observation()], confirmed_crs=crs)
    assert update["map_eligible"] is False
    for field in ("latitude", "longitude", "location_crs", "location_record_id"):
        assert update[field] is None
    location = update["quality_notes"]["location"]
    assert location["reason_code"] == "crs_unconfirmed"
    assert location["candidate_raw_record_ids"] == [str(UUID(int=1))]
    check_c09(update)


@pytest.mark.parametrize("latitude,longitude,expected_lat,expected_lon", [
    ("-37.80000001", "144.90000001", "-37.8000000", "144.9000000"),
    ("-37.80000005", "144.90000005", "-37.8000001", "144.9000001"),
    ("37.80000005", "-144.90000005", "37.8000001", "-144.9000001"),
    ("89.99999999", "179.99999999", "90.0000000", "180.0000000"),
])
def test_output_matches_numeric_scale(latitude, longitude, expected_lat, expected_lon):
    with localcontext() as context:
        context.prec = 6
        context.rounding = ROUND_DOWN
        update = resolve([observation(latitude, longitude)])
    assert update["latitude"] == Decimal(expected_lat)
    assert update["longitude"] == Decimal(expected_lon)
    assert update["location_crs"] == "EPSG:4326"
    assert update["map_eligible"] is True
    check_c09(update)


def test_conflict_is_checked_before_rounding():
    rows = [observation("-37.80000001"), observation("-37.80000002", row=2)]
    update = resolve(rows)
    assert update["map_eligible"] is False
    assert update["quality_notes"]["location"]["reason_code"] == "location_conflict"
    check_c09(update)


@pytest.mark.parametrize("latitude,longitude", [
    ("90.00000001", "144.9"), ("-90.00000001", "144.9"),
    ("-37.8", "180.00000001"), ("-37.8", "-180.00000001"),
])
def test_range_is_checked_before_rounding(latitude, longitude):
    update = resolve([observation(latitude, longitude)])
    assert update["map_eligible"] is False
    assert update["quality_notes"]["location"]["reason_code"] == "invalid_coordinate"
    check_c09(update)


def test_b_s0_native_node_examples():
    groups = {}
    with (ROOT / "tests/fixtures/s0/syn_vic_node.csv").open(
        encoding="utf-8-sig", newline="",
    ) as stream:
        for index, row in enumerate(csv.DictReader(stream), 1):
            key = (row["ACCIDENT_NO"], row["NODE_ID"])
            groups.setdefault(key, []).append(observation(
                row["LATITUDE"], row["LONGITUDE"], index,
                accident_no=key[0], node_id=key[1],
            ))
    assert [len(rows) for rows in groups.values()] == [2, 2]
    equivalent = resolve(groups[("0001", "NODE01")])
    assert equivalent["map_eligible"] is True
    assert equivalent["location_record_id"] == str(UUID(int=1))
    conflict = resolve(groups[("0002", "NODE02")])
    assert conflict["quality_notes"]["location"]["reason_code"] == "location_conflict"
    check_c09(equivalent)
    check_c09(conflict)
