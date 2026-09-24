from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
import re
from typing import Iterable


@dataclass(frozen=True)
class NodeObservation:
    raw_record_id: str
    accident_no: str
    node_id: str
    latitude_raw: str | None
    longitude_raw: str | None
    file_sha256: str
    parser_version: str
    row_locator: str


@dataclass(frozen=True)
class NodeLocationDecision:
    observation_count: int
    coordinate_pair_count: int
    latitude: Decimal | None
    longitude: Decimal | None
    location_record_id: str | None
    map_eligible: bool
    reason_code: str
    resolution: str


def _parse_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None

    if value == "":
        return None

    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ValueError(
            f"invalid coordinate token: {value!r}"
        )

    if not result.is_finite():
        raise ValueError(
            f"non-finite coordinate token: {value!r}"
        )

    return result


def _numeric_locator(row_locator: str) -> int:
    match = re.search(r"(\d+)$", row_locator)

    if match is None:
        raise ValueError(
            f"row locator has no numeric native position: "
            f"{row_locator!r}"
        )

    return int(match.group(1))


def _representative(
    observations: list[NodeObservation],
) -> NodeObservation:
    return min(
        observations,
        key=lambda row: (
            row.file_sha256,
            row.parser_version,
            _numeric_locator(row.row_locator),
        ),
    )


def resolve_node_location(
    observations: Iterable[NodeObservation],
    *,
    expected_accident_no: str,
    expected_node_id: str,
    crs_confirmed: bool,
) -> NodeLocationDecision:
    rows = list(observations)

    if not rows:
        return NodeLocationDecision(
            observation_count=0,
            coordinate_pair_count=0,
            latitude=None,
            longitude=None,
            location_record_id=None,
            map_eligible=False,
            reason_code="no_location",
            resolution="no_matching_node_observation",
        )

    for row in rows:
        if (
            row.accident_no != expected_accident_no
            or row.node_id != expected_node_id
        ):
            raise ValueError(
                "Node observation does not belong to the "
                "expected ACCIDENT_NO + NODE_ID group"
            )

    coordinate_pairs: set[
        tuple[Decimal, Decimal]
    ] = set()

    try:
        for row in rows:
            latitude = _parse_decimal(
                row.latitude_raw
            )
            longitude = _parse_decimal(
                row.longitude_raw
            )

            if latitude is None or longitude is None:
                return NodeLocationDecision(
                    observation_count=len(rows),
                    coordinate_pair_count=0,
                    latitude=None,
                    longitude=None,
                    location_record_id=None,
                    map_eligible=False,
                    reason_code="invalid_coordinate",
                    resolution="incomplete_coordinate_observation",
                )

            if not (
                Decimal("-90")
                <= latitude
                <= Decimal("90")
            ):
                return NodeLocationDecision(
                    observation_count=len(rows),
                    coordinate_pair_count=0,
                    latitude=None,
                    longitude=None,
                    location_record_id=None,
                    map_eligible=False,
                    reason_code="invalid_coordinate",
                    resolution="latitude_out_of_range",
                )

            if not (
                Decimal("-180")
                <= longitude
                <= Decimal("180")
            ):
                return NodeLocationDecision(
                    observation_count=len(rows),
                    coordinate_pair_count=0,
                    latitude=None,
                    longitude=None,
                    location_record_id=None,
                    map_eligible=False,
                    reason_code="invalid_coordinate",
                    resolution="longitude_out_of_range",
                )

            coordinate_pairs.add(
                (latitude, longitude)
            )

    except ValueError:
        return NodeLocationDecision(
            observation_count=len(rows),
            coordinate_pair_count=0,
            latitude=None,
            longitude=None,
            location_record_id=None,
            map_eligible=False,
            reason_code="invalid_coordinate",
            resolution="invalid_coordinate_token",
        )

    if len(coordinate_pairs) != 1:
        return NodeLocationDecision(
            observation_count=len(rows),
            coordinate_pair_count=len(
                coordinate_pairs
            ),
            latitude=None,
            longitude=None,
            location_record_id=None,
            map_eligible=False,
            reason_code="location_conflict",
            resolution="conflicting_coordinate_observations",
        )

    latitude, longitude = next(
        iter(coordinate_pairs)
    )

    if not crs_confirmed:
        return NodeLocationDecision(
            observation_count=len(rows),
            coordinate_pair_count=1,
            latitude=None,
            longitude=None,
            location_record_id=None,
            map_eligible=False,
            reason_code="crs_unconfirmed",
            resolution=(
                "coordinates_agree_but_crs_is_unconfirmed"
            ),
        )

    representative = _representative(rows)

    return NodeLocationDecision(
        observation_count=len(rows),
        coordinate_pair_count=1,
        latitude=latitude,
        longitude=longitude,
        location_record_id=(
            representative.raw_record_id
        ),
        map_eligible=True,
        reason_code="",
        resolution="equivalent_observations_resolved",
    )
