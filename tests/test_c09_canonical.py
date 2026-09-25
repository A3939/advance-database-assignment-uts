from __future__ import annotations

from uuid import UUID

import pytest

from arsia_c.canonical import (
    _crash_parameters,
    _unit_parameters,
)
from arsia_ingest.models import IntakeError

BATCH_ID = UUID("00000000-0000-0000-0000-000000000009")

CRASH_RAW_ID = UUID("00000000-0000-0000-0000-000000000101")

UNIT_RAW_ID = UUID("00000000-0000-0000-0000-000000000201")


def _allowed_scopes():
    return {
        (
            "official_nsw",
            "nsw_pinned_2020_2024_v1",
        )
    }


def _crash_row():
    return {
        "batch_id": BATCH_ID,
        "source_id": "official_nsw",
        "release_scope": "nsw_pinned_2020_2024_v1",
        "crash_key": '["000123"]',
        "raw_record_id": CRASH_RAW_ID,
        "attributes": {
            "occurrence_year": 2020,
            "occurrence_month": 1,
            "occurrence_date": None,
            "date_precision": "month",
            "severity_raw": "Fatal",
            "severity_code": "FATAL",
            "severity_definition_version": "nsw-crash-severity-v1",
            "is_fatal_crash": True,
            "fatality_count": 1,
            "casualty_count": 1,
            "fatal_crash_eligible": True,
            "fatality_eligible": True,
            "casualty_eligible": True,
            "latitude": None,
            "longitude": None,
            "location_crs": None,
            "map_eligible": False,
            "location_record_id": None,
            "quality_notes": {
                "location": {
                    "reason_code": "crs_unconfirmed",
                    "candidate_raw_record_ids": [],
                    "resolution": "Retain the crash without trusted coordinates.",
                    "evidence_ref": "synthetic:C09",
                }
            },
        },
    }


def _unit_row():
    return {
        "batch_id": BATCH_ID,
        "source_id": "official_nsw",
        "release_scope": "nsw_pinned_2020_2024_v1",
        "unit_key": '["000123", "01"]',
        "crash_key": '["000123"]',
        "raw_record_id": UNIT_RAW_ID,
        "attributes": {
            "crash_key": '["000123"]',
            "unit_type_raw": "Car/car derivative",
            "unit_type_code": "Car/car derivative",
            "statistical_scope": "NSW traffic units",
            "count_eligible": True,
            "quality_notes": {},
        },
    }


def test_crash_parameters_rebuild_fixed_contract():
    parameters = _crash_parameters(
        _crash_row(),
        batch_id=BATCH_ID,
        allowed_scopes=_allowed_scopes(),
    )

    assert parameters[0] == BATCH_ID
    assert parameters[1] == "official_nsw"
    assert parameters[2] == "nsw_pinned_2020_2024_v1"
    assert parameters[3] == '["000123"]'
    assert parameters[4] == CRASH_RAW_ID
    assert parameters[5] == 2020
    assert parameters[6] == 1
    assert parameters[8] == "month"
    assert parameters[10] == "FATAL"
    assert parameters[12] is True
    assert parameters[13] == 1
    assert parameters[14] == 1
    assert parameters[21] is False


def test_crash_rejects_wrong_batch():
    row = _crash_row()
    row["batch_id"] = UUID("00000000-0000-0000-0000-000000000999")

    with pytest.raises(
        IntakeError,
        match="different batch",
    ):
        _crash_parameters(
            row,
            batch_id=BATCH_ID,
            allowed_scopes=_allowed_scopes(),
        )


def test_crash_rejects_scope_outside_manifest():
    row = _crash_row()
    row["release_scope"] = "wrong-release"

    with pytest.raises(
        IntakeError,
        match="outside the frozen manifest",
    ):
        _crash_parameters(
            row,
            batch_id=BATCH_ID,
            allowed_scopes=_allowed_scopes(),
        )


def test_crash_rejects_missing_attribute():
    row = _crash_row()
    del row["attributes"]["casualty_count"]

    with pytest.raises(
        IntakeError,
        match="fixed Canonical attribute contract",
    ):
        _crash_parameters(
            row,
            batch_id=BATCH_ID,
            allowed_scopes=_allowed_scopes(),
        )


def test_unit_parameters_keep_link_parent():
    parameters = _unit_parameters(
        _unit_row(),
        batch_id=BATCH_ID,
        allowed_scopes=_allowed_scopes(),
    )

    assert parameters[0] == BATCH_ID
    assert parameters[1] == "official_nsw"
    assert parameters[3] == '["000123", "01"]'
    assert parameters[4] == '["000123"]'
    assert parameters[5] == UNIT_RAW_ID
    assert parameters[6] == "Car/car derivative"
    assert parameters[7] == "Car/car derivative"
    assert parameters[8] == "NSW traffic units"
    assert parameters[9] is True


def test_unit_rejects_parent_mismatch():
    row = _unit_row()
    row["attributes"]["crash_key"] = '["999999"]'

    with pytest.raises(
        IntakeError,
        match="parent does not match",
    ):
        _unit_parameters(
            row,
            batch_id=BATCH_ID,
            allowed_scopes=_allowed_scopes(),
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("occurrence_year", "2020"),
        ("fatality_count", 1.5),
        ("fatality_count", True),
        ("fatality_count", 2**31),
        ("is_fatal_crash", "false"),
        ("map_eligible", 1),
        ("latitude", "-33.8"),
        ("latitude", float("nan")),
        ("longitude", 181),
        ("latitude", -33.12345678),
        ("occurrence_date", "2020-02-31"),
        ("occurrence_date", "20200101"),
        ("location_record_id", "other-record"),
        ("severity_code", None),
    ],
)
def test_rejects_attributes_that_sql_would_coerce(field, value):
    row = _crash_row()
    row["attributes"][field] = value
    with pytest.raises(IntakeError):
        _crash_parameters(row, batch_id=BATCH_ID, allowed_scopes=_allowed_scopes())


@pytest.mark.parametrize(
    "notes",
    [
        {"location": "crs_unconfirmed"},
        {"location": {}},
        {"fields": {}},
        {"fields": [{"field": "fatality_count"}]},
        {"references": "unstructured"},
    ],
)
def test_rejects_unstructured_quality_notes(notes):
    row = _crash_row()
    row["attributes"]["quality_notes"] = notes
    with pytest.raises(IntakeError):
        _crash_parameters(row, batch_id=BATCH_ID, allowed_scopes=_allowed_scopes())


def test_null_and_zero_remain_distinct():
    row = _crash_row()
    row["attributes"].update(
        fatality_count=0, casualty_count=None, casualty_eligible=False
    )
    values = _crash_parameters(row, batch_id=BATCH_ID, allowed_scopes=_allowed_scopes())
    assert values[13] == 0 and values[14] is None and values[17] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"occurrence_year": 1899},
        {"occurrence_month": 13},
        {"date_precision": "year"},
        {"date_precision": "day"},
        {"fatality_count": -1},
        {"fatality_count": None},
        {"latitude": -33.8, "longitude": 151.2},
        {"map_eligible": True},
        {"quality_notes": {}},
    ],
)
def test_rejects_inconsistent_core_values(changes):
    row = _crash_row()
    row["attributes"].update(changes)
    with pytest.raises(IntakeError):
        _crash_parameters(row, batch_id=BATCH_ID, allowed_scopes=_allowed_scopes())


@pytest.mark.parametrize("value", [None, "", "  "])
def test_eligible_unit_needs_type(value):
    row = _unit_row()
    row["attributes"]["unit_type_code"] = value
    with pytest.raises(IntakeError):
        _unit_parameters(row, batch_id=BATCH_ID, allowed_scopes=_allowed_scopes())
