from __future__ import annotations

from decimal import Decimal

from arsia_c.node_location import (
    NodeObservation,
    resolve_node_location,
)


def _obs(
    *,
    raw_record_id="raw-1",
    accident_no="A1",
    node_id="N1",
    latitude="-37.8000000",
    longitude="144.9000000",
    file_sha256="a" * 64,
    parser_version="csv-native-v1",
    row_locator="csv:1",
):
    return NodeObservation(
        raw_record_id=raw_record_id,
        accident_no=accident_no,
        node_id=node_id,
        latitude_raw=latitude,
        longitude_raw=longitude,
        file_sha256=file_sha256,
        parser_version=parser_version,
        row_locator=row_locator,
    )


def test_no_matching_node_returns_no_location():
    result = resolve_node_location(
        [],
        expected_accident_no="A1",
        expected_node_id="N1",
        crs_confirmed=False,
    )

    assert result.observation_count == 0
    assert result.coordinate_pair_count == 0
    assert result.latitude is None
    assert result.longitude is None
    assert result.location_record_id is None
    assert result.map_eligible is False
    assert result.reason_code == "no_location"


def test_equivalent_duplicate_resolves_when_crs_confirmed():
    rows = [
        _obs(
            raw_record_id="raw-2",
            row_locator="csv:2",
        ),
        _obs(
            raw_record_id="raw-1",
            row_locator="csv:1",
        ),
    ]

    result = resolve_node_location(
        rows,
        expected_accident_no="A1",
        expected_node_id="N1",
        crs_confirmed=True,
    )

    assert result.observation_count == 2
    assert result.coordinate_pair_count == 1
    assert result.latitude == Decimal("-37.8000000")
    assert result.longitude == Decimal("144.9000000")
    assert result.location_record_id == "raw-1"
    assert result.map_eligible is True
    assert result.reason_code == ""


def test_conflicting_coordinates_are_not_averaged():
    rows = [
        _obs(
            raw_record_id="raw-1",
            latitude="-37.8000000",
            longitude="144.9000000",
            row_locator="csv:1",
        ),
        _obs(
            raw_record_id="raw-2",
            latitude="-37.9000000",
            longitude="145.0000000",
            row_locator="csv:2",
        ),
    ]

    result = resolve_node_location(
        rows,
        expected_accident_no="A1",
        expected_node_id="N1",
        crs_confirmed=True,
    )

    assert result.coordinate_pair_count == 2
    assert result.latitude is None
    assert result.longitude is None
    assert result.location_record_id is None
    assert result.map_eligible is False
    assert result.reason_code == "location_conflict"


def test_incomplete_coordinate_is_invalid():
    rows = [
        _obs(
            latitude="-37.8000000",
            longitude=None,
        )
    ]

    result = resolve_node_location(
        rows,
        expected_accident_no="A1",
        expected_node_id="N1",
        crs_confirmed=True,
    )

    assert result.latitude is None
    assert result.longitude is None
    assert result.map_eligible is False
    assert result.reason_code == "invalid_coordinate"


def test_out_of_range_coordinate_is_invalid():
    rows = [
        _obs(
            latitude="-95.0000000",
            longitude="144.9000000",
        )
    ]

    result = resolve_node_location(
        rows,
        expected_accident_no="A1",
        expected_node_id="N1",
        crs_confirmed=True,
    )

    assert result.map_eligible is False
    assert result.reason_code == "invalid_coordinate"


def test_non_numeric_coordinate_is_invalid():
    rows = [
        _obs(
            latitude="not-a-number",
            longitude="144.9000000",
        )
    ]

    result = resolve_node_location(
        rows,
        expected_accident_no="A1",
        expected_node_id="N1",
        crs_confirmed=True,
    )

    assert result.map_eligible is False
    assert result.reason_code == "invalid_coordinate"


def test_official_vic_equivalent_coordinates_remain_unavailable_without_crs():
    rows = [
        _obs(
            raw_record_id="raw-1",
            row_locator="csv:1",
        ),
        _obs(
            raw_record_id="raw-2",
            row_locator="csv:2",
        ),
    ]

    result = resolve_node_location(
        rows,
        expected_accident_no="A1",
        expected_node_id="N1",
        crs_confirmed=False,
    )

    assert result.coordinate_pair_count == 1
    assert result.latitude is None
    assert result.longitude is None
    assert result.location_record_id is None
    assert result.map_eligible is False
    assert result.reason_code == "crs_unconfirmed"


def test_wrong_accident_or_node_group_blocks():
    rows = [
        _obs(
            accident_no="OTHER",
            node_id="N1",
        )
    ]

    try:
        resolve_node_location(
            rows,
            expected_accident_no="A1",
            expected_node_id="N1",
            crs_confirmed=True,
        )
    except ValueError as exc:
        assert "ACCIDENT_NO + NODE_ID" in str(exc)
    else:
        raise AssertionError(
            "Expected mismatched Node group to raise ValueError"
        )


def test_representative_selection_uses_numeric_row_locator():
    rows = [
        _obs(
            raw_record_id="raw-10",
            row_locator="csv:10",
        ),
        _obs(
            raw_record_id="raw-2",
            row_locator="csv:2",
        ),
    ]

    result = resolve_node_location(
        rows,
        expected_accident_no="A1",
        expected_node_id="N1",
        crs_confirmed=True,
    )

    assert result.location_record_id == "raw-2"
