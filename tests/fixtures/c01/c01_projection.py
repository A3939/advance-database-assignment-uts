"""
C01 fixed projection fixtures.

Internal development/test data only.
These fixtures use semantic identity components and do not depend on the
final A05 physical business-key encoding.

Contract:
- l_crash: exactly 24 fields
- l_unit: exactly 11 fields
"""

CRASH_FIELDS = (
    "source_id",
    "primary_resource_id",
    "source_crash_id",
    "occurrence_year",
    "occurrence_month",
    "occurrence_date",
    "date_precision",
    "source_severity",
    "definition_version",
    "fatality_count",
    "serious_injury_count",
    "other_injury_count",
    "casualty_count",
    "declared_unit_count",
    "declared_person_count",
    "latitude",
    "longitude",
    "crs_code",
    "primary_raw_record_id",
    "location_raw_record_id",
    "metric_eligible",
    "metric_reason",
    "map_eligible",
    "map_reason",
)

UNIT_FIELDS = (
    "source_id",
    "primary_resource_id",
    "source_crash_id",
    "source_unit_id",
    "source_unit_type",
    "direction",
    "movement",
    "primary_raw_record_id",
    "parent_crash_raw_record_id",
    "metric_eligible",
    "metric_reason",
)


CRASH_FIXTURES = [
    # ------------------------------------------------------------------
    # F01 — normal valid crash
    # ------------------------------------------------------------------
    {
        "fixture_id": "F01",
        "scenario": "normal_valid_crash",
        "expected_valid": True,
        "row": {
            "source_id": "vic",
            "primary_resource_id": "vic_accident",
            "source_crash_id": "VIC-000001",
            "occurrence_year": 2024,
            "occurrence_month": 6,
            "occurrence_date": "2024-06-15",
            "date_precision": "DAY",
            "source_severity": "SERIOUS_INJURY",
            "definition_version": "synthetic-v0.1",
            "fatality_count": 0,
            "serious_injury_count": 1,
            "other_injury_count": 0,
            "casualty_count": 1,
            "declared_unit_count": 2,
            "declared_person_count": 3,
            "latitude": -37.8136,
            "longitude": 144.9631,
            "crs_code": "EPSG:4326",
            "primary_raw_record_id": "11111111-1111-1111-1111-111111111111",
            "location_raw_record_id": "22222222-2222-2222-2222-222222222222",
            "metric_eligible": True,
            "metric_reason": None,
            "map_eligible": True,
            "map_reason": None,
        },
    },

    # ------------------------------------------------------------------
    # F02 — optional source values are missing
    # NULL must remain explicit rather than becoming zero/default.
    # ------------------------------------------------------------------
    {
        "fixture_id": "F02",
        "scenario": "optional_null_values",
        "expected_valid": True,
        "row": {
            "source_id": "nsw",
            "primary_resource_id": "nsw_crash",
            "source_crash_id": "NSW-000002",
            "occurrence_year": 2023,
            "occurrence_month": None,
            "occurrence_date": None,
            "date_precision": "YEAR",
            "source_severity": None,
            "definition_version": "synthetic-v0.1",
            "fatality_count": None,
            "serious_injury_count": None,
            "other_injury_count": None,
            "casualty_count": None,
            "declared_unit_count": None,
            "declared_person_count": None,
            "latitude": None,
            "longitude": None,
            "crs_code": None,
            "primary_raw_record_id": "33333333-3333-3333-3333-333333333333",
            "location_raw_record_id": None,
            "metric_eligible": True,
            "metric_reason": None,
            "map_eligible": False,
            "map_reason": "MISSING_LOCATION_DRAFT",
        },
    },

    # ------------------------------------------------------------------
    # F03 — unknown / unmapped source classification
    # Source value remains visible; do not silently map to a default.
    # ------------------------------------------------------------------
    {
        "fixture_id": "F03",
        "scenario": "unknown_classification",
        "expected_valid": True,
        "row": {
            "source_id": "vic",
            "primary_resource_id": "vic_accident",
            "source_crash_id": "VIC-000003",
            "occurrence_year": 2024,
            "occurrence_month": 8,
            "occurrence_date": "2024-08-03",
            "date_precision": "DAY",
            "source_severity": "UNMAPPED_NATIVE_VALUE",
            "definition_version": "synthetic-v0.1",
            "fatality_count": 0,
            "serious_injury_count": None,
            "other_injury_count": None,
            "casualty_count": None,
            "declared_unit_count": 1,
            "declared_person_count": 1,
            "latitude": -37.8100,
            "longitude": 144.9600,
            "crs_code": "EPSG:4326",
            "primary_raw_record_id": "44444444-4444-4444-4444-444444444444",
            "location_raw_record_id": "55555555-5555-5555-5555-555555555555",
            "metric_eligible": False,
            "metric_reason": "UNMAPPED_CLASSIFICATION_DRAFT",
            "map_eligible": True,
            "map_reason": None,
        },
    },

    # ------------------------------------------------------------------
    # F04A/F04B — same native crash ID in different sources.
    # They must remain distinct semantic crash identities.
    # ------------------------------------------------------------------
    {
        "fixture_id": "F04A",
        "scenario": "same_native_crash_id_different_source_nsw",
        "expected_valid": True,
        "row": {
            "source_id": "nsw",
            "primary_resource_id": "nsw_crash",
            "source_crash_id": "10001",
            "occurrence_year": 2024,
            "occurrence_month": 5,
            "occurrence_date": "2024-05-10",
            "date_precision": "DAY",
            "source_severity": "INJURY",
            "definition_version": "synthetic-v0.1",
            "fatality_count": 0,
            "serious_injury_count": 1,
            "other_injury_count": 0,
            "casualty_count": 1,
            "declared_unit_count": 2,
            "declared_person_count": 2,
            "latitude": -33.8688,
            "longitude": 151.2093,
            "crs_code": "EPSG:4326",
            "primary_raw_record_id": "66666666-6666-6666-6666-666666666666",
            "location_raw_record_id": "66666666-6666-6666-6666-666666666666",
            "metric_eligible": True,
            "metric_reason": None,
            "map_eligible": True,
            "map_reason": None,
        },
    },
    {
        "fixture_id": "F04B",
        "scenario": "same_native_crash_id_different_source_vic",
        "expected_valid": True,
        "row": {
            "source_id": "vic",
            "primary_resource_id": "vic_accident",
            "source_crash_id": "10001",
            "occurrence_year": 2024,
            "occurrence_month": 5,
            "occurrence_date": "2024-05-11",
            "date_precision": "DAY",
            "source_severity": "OTHER_INJURY",
            "definition_version": "synthetic-v0.1",
            "fatality_count": 0,
            "serious_injury_count": 0,
            "other_injury_count": 1,
            "casualty_count": 1,
            "declared_unit_count": 1,
            "declared_person_count": 1,
            "latitude": -37.8136,
            "longitude": 144.9631,
            "crs_code": "EPSG:4326",
            "primary_raw_record_id": "77777777-7777-7777-7777-777777777777",
            "location_raw_record_id": "88888888-8888-8888-8888-888888888888",
            "metric_eligible": True,
            "metric_reason": None,
            "map_eligible": True,
            "map_reason": None,
        },
    },

    # ------------------------------------------------------------------
    # F07 — VIC-style separate Node location lineage.
    # primary_raw_record_id != location_raw_record_id
    # ------------------------------------------------------------------
    {
        "fixture_id": "F07",
        "scenario": "separate_location_raw_lineage",
        "expected_valid": True,
        "row": {
            "source_id": "vic",
            "primary_resource_id": "vic_accident",
            "source_crash_id": "VIC-000007",
            "occurrence_year": 2022,
            "occurrence_month": 9,
            "occurrence_date": "2022-09-18",
            "date_precision": "DAY",
            "source_severity": "SERIOUS_INJURY",
            "definition_version": "synthetic-v0.1",
            "fatality_count": 0,
            "serious_injury_count": 1,
            "other_injury_count": 0,
            "casualty_count": 1,
            "declared_unit_count": 2,
            "declared_person_count": 3,
            "latitude": -37.8200,
            "longitude": 144.9700,
            "crs_code": "EPSG:4326",
            "primary_raw_record_id": "99999999-9999-9999-9999-999999999999",
            "location_raw_record_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            "metric_eligible": True,
            "metric_reason": None,
            "map_eligible": True,
            "map_reason": None,
        },
    },

    # ------------------------------------------------------------------
    # F08 — location comes from the same Raw row.
    # ------------------------------------------------------------------
    {
        "fixture_id": "F08",
        "scenario": "same_row_location_lineage",
        "expected_valid": True,
        "row": {
            "source_id": "nsw",
            "primary_resource_id": "nsw_crash",
            "source_crash_id": "NSW-000008",
            "occurrence_year": 2021,
            "occurrence_month": 3,
            "occurrence_date": "2021-03-21",
            "date_precision": "DAY",
            "source_severity": "INJURY",
            "definition_version": "synthetic-v0.1",
            "fatality_count": 0,
            "serious_injury_count": 1,
            "other_injury_count": 0,
            "casualty_count": 1,
            "declared_unit_count": 1,
            "declared_person_count": 2,
            "latitude": -33.8700,
            "longitude": 151.2100,
            "crs_code": "EPSG:4326",
            "primary_raw_record_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "location_raw_record_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "metric_eligible": True,
            "metric_reason": None,
            "map_eligible": True,
            "map_reason": None,
        },
    },

    # ------------------------------------------------------------------
    # F09 — crash exists but no trusted location is available.
    # Crash stays available for non-spatial analysis.
    # ------------------------------------------------------------------
    {
        "fixture_id": "F09",
        "scenario": "missing_or_untrusted_location",
        "expected_valid": True,
        "row": {
            "source_id": "vic",
            "primary_resource_id": "vic_accident",
            "source_crash_id": "VIC-000009",
            "occurrence_year": 2024,
            "occurrence_month": 2,
            "occurrence_date": "2024-02-20",
            "date_precision": "DAY",
            "source_severity": "OTHER_INJURY",
            "definition_version": "synthetic-v0.1",
            "fatality_count": 0,
            "serious_injury_count": 0,
            "other_injury_count": 1,
            "casualty_count": 1,
            "declared_unit_count": 1,
            "declared_person_count": 1,
            "latitude": None,
            "longitude": None,
            "crs_code": None,
            "primary_raw_record_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
            "location_raw_record_id": None,
            "metric_eligible": True,
            "metric_reason": None,
            "map_eligible": False,
            "map_reason": "NO_TRUSTED_LOCATION_DRAFT",
        },
    },

    # ------------------------------------------------------------------
    # F10 — QLD crash with aggregate unit counts only.
    # Expected unit output count is zero.
    # ------------------------------------------------------------------
    {
        "fixture_id": "F10",
        "scenario": "qld_crash_without_individual_unit_rows",
        "expected_valid": True,
        "expected_unit_rows": 0,
        "row": {
            "source_id": "qld",
            "primary_resource_id": "qld_crash",
            "source_crash_id": "QLD-000010",
            "occurrence_year": 2024,
            "occurrence_month": 7,
            "occurrence_date": "2024-07-12",
            "date_precision": "DAY",
            "source_severity": "HOSPITALISATION",
            "definition_version": "synthetic-v0.1",
            "fatality_count": 0,
            "serious_injury_count": 1,
            "other_injury_count": None,
            "casualty_count": 1,
            "declared_unit_count": 3,
            "declared_person_count": None,
            "latitude": -27.4698,
            "longitude": 153.0251,
            "crs_code": "EPSG:4326",
            "primary_raw_record_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
            "location_raw_record_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
            "metric_eligible": True,
            "metric_reason": None,
            "map_eligible": True,
            "map_reason": None,
        },
    },
]


UNIT_FIXTURES = [
    # ------------------------------------------------------------------
    # F05 — valid real unit with a valid real parent crash.
    # ------------------------------------------------------------------
    {
        "fixture_id": "F05",
        "scenario": "valid_real_unit_with_parent",
        "expected_valid": True,
        "row": {
            "source_id": "vic",
            "primary_resource_id": "vic_vehicle",
            "source_crash_id": "VIC-000001",
            "source_unit_id": "1",
            "source_unit_type": "PASSENGER_VEHICLE",
            "direction": "NORTH",
            "movement": "STRAIGHT",
            "primary_raw_record_id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
            "parent_crash_raw_record_id": "11111111-1111-1111-1111-111111111111",
            "metric_eligible": True,
            "metric_reason": None,
        },
    },

    # ------------------------------------------------------------------
    # F06 — unit references the wrong/non-matching parent crash.
    #
    # The fixture remains structurally complete, but validation is
    # expected to reject the relationship. No artificial parent may be
    # created.
    # ------------------------------------------------------------------
    {
        "fixture_id": "F06",
        "scenario": "unit_with_wrong_parent",
        "expected_valid": False,
        "expected_error": "PARENT_CRASH_MISMATCH_DRAFT",
        "row": {
            "source_id": "vic",
            "primary_resource_id": "vic_vehicle",
            "source_crash_id": "VIC-NONEXISTENT",
            "source_unit_id": "99",
            "source_unit_type": "PASSENGER_VEHICLE",
            "direction": None,
            "movement": None,
            "primary_raw_record_id": "ffffffff-ffff-ffff-ffff-ffffffffffff",
            "parent_crash_raw_record_id": "12121212-1212-1212-1212-121212121212",
            "metric_eligible": False,
            "metric_reason": "INVALID_PARENT_DRAFT",
        },
    },
]


def validate_fixture_shapes():
    """
    Development guard for the C01 contract.

    Checks that every crash row has exactly the 24 contract fields and
    every unit row has exactly the 11 contract fields.
    """

    expected_crash_fields = set(CRASH_FIELDS)
    expected_unit_fields = set(UNIT_FIELDS)

    assert len(CRASH_FIELDS) == 24
    assert len(UNIT_FIELDS) == 11

    for fixture in CRASH_FIXTURES:
        row = fixture["row"]

        assert len(row) == 24, (
            f"{fixture['fixture_id']} must contain exactly 24 crash fields; "
            f"found {len(row)}"
        )

        assert set(row) == expected_crash_fields, (
            f"{fixture['fixture_id']} crash field mismatch: "
            f"missing={expected_crash_fields - set(row)}, "
            f"extra={set(row) - expected_crash_fields}"
        )

    for fixture in UNIT_FIXTURES:
        row = fixture["row"]

        assert len(row) == 11, (
            f"{fixture['fixture_id']} must contain exactly 11 unit fields; "
            f"found {len(row)}"
        )

        assert set(row) == expected_unit_fields, (
            f"{fixture['fixture_id']} unit field mismatch: "
            f"missing={expected_unit_fields - set(row)}, "
            f"extra={set(row) - expected_unit_fields}"
        )


if __name__ == "__main__":
    validate_fixture_shapes()
    print("C01 fixture shapes are valid: l_crash=24 fields, l_unit=11 fields.")
