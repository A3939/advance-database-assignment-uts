from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from importlib.resources import files
import re
from typing import Iterable, Iterator


NODE_OBSERVATIONS_SQL_PATH = files("arsia_c").joinpath(
    "sql", "c07_vic_node_observations.sql"
)


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


def _parse_decimal(
    value: str | None,
) -> Decimal | None:
    if value is None or value == "":
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


def _numeric_locator(
    row_locator: str,
) -> int:
    match = re.search(
        r"(\d+)$",
        row_locator,
    )

    if match is None:
        raise ValueError(
            "row locator has no numeric native position: "
            f"{row_locator!r}"
        )

    return int(
        match.group(1)
    )


def _representative(
    observations: list[NodeObservation],
) -> NodeObservation:
    return min(
        observations,
        key=lambda row: (
            row.file_sha256,
            row.parser_version,
            _numeric_locator(
                row.row_locator
            ),
        ),
    )


def resolve_node_location(
    observations: Iterable[NodeObservation],
    *,
    expected_accident_no: str,
    expected_node_id: str,
    crs_confirmed: bool,
) -> NodeLocationDecision:
    """
    Resolve one ACCIDENT_NO + NODE_ID observation group.

    Every observation is evaluated together.
    No observation may be silently dropped to make
    a location usable.
    """

    rows = list(
        observations
    )

    if not rows:
        return NodeLocationDecision(
            observation_count=0,
            coordinate_pair_count=0,
            latitude=None,
            longitude=None,
            location_record_id=None,
            map_eligible=False,
            reason_code="no_location",
            resolution=(
                "no_matching_node_observation"
            ),
        )

    for row in rows:
        if (
            row.accident_no
            != expected_accident_no
            or row.node_id
            != expected_node_id
        ):
            raise ValueError(
                "Node observation does not belong "
                "to the expected "
                "ACCIDENT_NO + NODE_ID group"
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

            if (
                latitude is None
                or longitude is None
            ):
                return NodeLocationDecision(
                    observation_count=len(rows),
                    coordinate_pair_count=0,
                    latitude=None,
                    longitude=None,
                    location_record_id=None,
                    map_eligible=False,
                    reason_code=(
                        "invalid_coordinate"
                    ),
                    resolution=(
                        "incomplete_coordinate_observation"
                    ),
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
                    reason_code=(
                        "invalid_coordinate"
                    ),
                    resolution=(
                        "latitude_out_of_range"
                    ),
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
                    reason_code=(
                        "invalid_coordinate"
                    ),
                    resolution=(
                        "longitude_out_of_range"
                    ),
                )

            coordinate_pairs.add(
                (
                    latitude,
                    longitude,
                )
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
            resolution=(
                "invalid_coordinate_token"
            ),
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
            resolution=(
                "conflicting_coordinate_observations"
            ),
        )

    latitude, longitude = next(
        iter(
            coordinate_pairs
        )
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

    representative = _representative(
        rows
    )

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
        resolution=(
            "equivalent_observations_resolved"
        ),
    )


def _load_node_sql() -> str:
    return (
        NODE_OBSERVATIONS_SQL_PATH
        .read_text(
            encoding="utf-8"
        )
    )


def iter_node_observation_groups(
    connection,
    node_input: dict,
) -> Iterator[
    tuple[
        tuple[str, str],
        list[NodeObservation],
    ]
]:
    """
    Stream selected VIC Node Raw rows grouped by
    ACCIDENT_NO + NODE_ID.

    Every selected Raw observation remains represented.
    This function does not deduplicate, select a
    representative, resolve coordinates or infer CRS.
    """

    sql = _load_node_sql()

    with connection.cursor() as cursor:
        cursor.execute(
            sql,
            (
                node_input["source_id"],
                node_input["resource_id"],
                node_input["file_sha256"],
                node_input["parser_version"],
            ),
        )

        current_key: (
            tuple[str, str] | None
        ) = None

        current_rows: list[
            NodeObservation
        ] = []

        for row in cursor:
            (
                raw_record_id,
                _source_id,
                _resource_id,
                file_sha256,
                parser_version,
                row_locator,
                accident_no,
                node_id,
                latitude_raw,
                longitude_raw,
                _deg_urban_name,
            ) = row

            key = (
                accident_no,
                node_id,
            )

            observation = (
                NodeObservation(
                    raw_record_id=str(
                        raw_record_id
                    ),
                    accident_no=accident_no,
                    node_id=node_id,
                    latitude_raw=latitude_raw,
                    longitude_raw=longitude_raw,
                    file_sha256=file_sha256,
                    parser_version=(
                        parser_version
                    ),
                    row_locator=row_locator,
                )
            )

            if current_key is None:
                current_key = key

            if key != current_key:
                yield (
                    current_key,
                    current_rows,
                )

                current_key = key
                current_rows = []

            current_rows.append(
                observation
            )

        if current_key is not None:
            yield (
                current_key,
                current_rows,
            )


def build_location_update(
    decision: NodeLocationDecision,
    observations: Iterable[NodeObservation],
    *,
    existing_quality_notes: dict | None = None,
    evidence_ref: str,
    confirmed_crs: str = "EPSG:4326",
) -> dict:
    """
    Convert a Node resolution decision into the
    location fields required by I_crash.

    Existing non-location quality notes are preserved.
    """

    rows = list(
        observations
    )

    notes = dict(
        existing_quality_notes or {}
    )

    candidate_raw_record_ids = [
        row.raw_record_id
        for row in rows
    ]

    if decision.map_eligible and confirmed_crs != "EPSG:4326":
        decision = replace(
            decision, latitude=None, longitude=None, location_record_id=None,
            map_eligible=False, reason_code="crs_unconfirmed",
            resolution="coordinates_not_confirmed_as_epsg4326",
        )

    if decision.map_eligible:
        if (
            decision.latitude is None
            or decision.longitude is None
            or decision.location_record_id is None
        ):
            raise ValueError(
                "map-eligible Node decision is missing "
                "trusted location values"
            )

        # Raw agreement and range checks happen before PostgreSQL-scale rounding.
        with localcontext() as context:
            context.prec = 10
            scale = Decimal("0.0000001")
            latitude = decision.latitude.quantize(scale, rounding=ROUND_HALF_UP)
            longitude = decision.longitude.quantize(scale, rounding=ROUND_HALF_UP)

        notes.pop(
            "location",
            None,
        )

        return {
            "latitude":
                latitude,
            "longitude":
                longitude,
            "location_crs":
                confirmed_crs,
            "map_eligible":
                True,
            "location_record_id":
                decision.location_record_id,
            "quality_notes":
                notes,
        }

    allowed_reasons = {
        "missing",
        "unmapped",
        "definition_unconfirmed",
        "invalid_coordinate",
        "crs_unconfirmed",
        "location_conflict",
        "no_location",
    }

    if (
        decision.reason_code
        not in allowed_reasons
    ):
        raise ValueError(
            "unsupported location reason code: "
            f"{decision.reason_code!r}"
        )

    notes["location"] = {
        "reason_code":
            decision.reason_code,
        "candidate_raw_record_ids":
            candidate_raw_record_ids,
        "resolution":
            decision.resolution,
        "evidence_ref":
            evidence_ref,
    }

    return {
        "latitude":
            None,
        "longitude":
            None,
        "location_crs":
            None,
        "map_eligible":
            False,
        "location_record_id":
            None,
        "quality_notes":
            notes,
    }


def resolve_location_update(
    observations: Iterable[NodeObservation],
    *,
    expected_accident_no: str,
    expected_node_id: str,
    crs_confirmed: bool,
    existing_quality_notes: dict | None = None,
    evidence_ref: str,
    confirmed_crs: str = "EPSG:4326",
) -> dict:
    """
    Resolve a full Node observation group and convert it
    into the location portion of I_crash.

    This wrapper is intended for C04/C07 integration.
    """

    rows = list(
        observations
    )

    decision = resolve_node_location(
        rows,
        expected_accident_no=expected_accident_no,
        expected_node_id=expected_node_id,
        crs_confirmed=crs_confirmed,
    )

    return build_location_update(
        decision,
        rows,
        existing_quality_notes=(
            existing_quality_notes
        ),
        evidence_ref=evidence_ref,
        confirmed_crs=confirmed_crs,
    )
