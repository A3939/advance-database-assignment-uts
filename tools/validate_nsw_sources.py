#!/usr/bin/env python3
"""Read-only structural and relationship checks for the pinned NSW pair."""

from __future__ import annotations

import argparse
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path

from arsia_ingest.models import ParseStats, ResourceSpec
from arsia_ingest.readers import iter_native_rows


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "native-inputs.json"
RESOURCE_IDS = (
    "official_nsw_crash",
    "official_nsw_traffic_unit",
)
EXPECTED_COUNTS = {
    "official_nsw_crash": 92_189,
    "official_nsw_traffic_unit": 170_962,
}
ANALYSIS_YEARS = {str(year) for year in range(2020, 2025)}
MONTH_NUMBERS = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}
EXPECTED_ANALYSIS = {
    "crash_count": 92_082,
    "traffic_unit_count": 170_747,
    "raw_only_2019_crash_count": 107,
    "raw_only_2019_traffic_unit_count": 215,
    "covered_year_months": 60,
    "fatal_crash_count": 1_388,
    "fatality_count": 1_507,
    "casualty_count": 78_154,
    "invalid_people_counts": {},
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _spec(value: dict[str, object]) -> ResourceSpec:
    return ResourceSpec(
        source_id=str(value["source_id"]),
        resource_id=str(value["resource_id"]),
        resource_role=str(value["resource_role"]),
        entity_kind=str(value["entity_kind"]),
        path=(CONFIG_PATH.parent / str(value["path"])).resolve(),
        format=str(value["format"]),
        encoding=value.get("encoding"),  # type: ignore[arg-type]
        sheet=value.get("sheet"),  # type: ignore[arg-type]
        header_row=int(value["header_row"]),
        header=tuple(value["header"]),  # type: ignore[arg-type]
        expected_sha256=str(value["expected_sha256"]),
    )


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


def _integer(value: str | None) -> int | None:
    if _blank(value):
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    if not number.is_finite() or number != number.to_integral_value():
        return None
    return int(number)


def _display(value: str | None) -> str:
    return "<NULL>" if value is None else value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def validate() -> dict[str, object]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    selected = {
        value["resource_id"]: _spec(value)
        for value in config["resources"]
        if value["resource_id"] in RESOURCE_IDS
    }
    if set(selected) != set(RESOURCE_IDS):
        raise SystemExit("The frozen intake config does not contain both NSW resources")

    hashes: dict[str, str] = {}
    for resource_id, spec in selected.items():
        observed = _sha256(spec.path)
        hashes[resource_id] = observed
        if observed != spec.expected_sha256:
            raise SystemExit(
                f"{resource_id} SHA256 mismatch: {observed} != {spec.expected_sha256}"
            )

    crash_spec = selected["official_nsw_crash"]
    crash_stats = ParseStats()
    crash_ids: set[str] = set()
    duplicate_crash_ids: Counter[str] = Counter()
    blank_crash_ids = 0
    declared_units: dict[str, int | None] = {}
    invalid_declared_units = 0
    occurrence_years: Counter[str] = Counter()
    reporting_years: Counter[str] = Counter()
    occurrence_months: Counter[str] = Counter()
    severity: Counter[str] = Counter()
    detailed_severity: Counter[str] = Counter()
    coordinate_pairs = 0
    partial_coordinate_pairs = 0
    reporting_occurrence_year_differences = 0
    crash_year_by_id: dict[str, str | None] = {}
    analysis_crash_ids: set[str] = set()
    analysis_months: set[tuple[str, int]] = set()
    analysis_fatal_crashes = 0
    analysis_fatalities = 0
    analysis_casualties = 0
    invalid_people_counts: Counter[str] = Counter()

    for row in iter_native_rows(crash_spec.path, crash_spec, crash_stats):
        payload = row.payload
        crash_id = payload["Crash ID"]
        if _blank(crash_id):
            blank_crash_ids += 1
        else:
            assert crash_id is not None
            if crash_id in crash_ids:
                duplicate_crash_ids[crash_id] += 1
            crash_ids.add(crash_id)
            crash_year_by_id[crash_id] = payload["Year of crash"]
            declared = _integer(payload["No. of traffic units involved"])
            declared_units[crash_id] = declared
            if declared is None or declared < 0:
                invalid_declared_units += 1

        occurrence_years[_display(payload["Year of crash"])] += 1
        reporting_years[_display(payload["Reporting year"])] += 1
        occurrence_months[_display(payload["Month of crash"])] += 1
        severity[_display(payload["Degree of crash"])] += 1
        detailed_severity[_display(payload["Degree of crash - detailed"])] += 1

        if payload["Reporting year"] != payload["Year of crash"]:
            reporting_occurrence_year_differences += 1

        if payload["Year of crash"] in ANALYSIS_YEARS:
            if not _blank(crash_id):
                assert crash_id is not None
                analysis_crash_ids.add(crash_id)
            month_number = MONTH_NUMBERS.get(payload["Month of crash"] or "")
            if month_number is not None:
                analysis_months.add((payload["Year of crash"], month_number))
            if payload["Degree of crash"] == "Fatal":
                analysis_fatal_crashes += 1
            count_fields = (
                "No. killed",
                "No. seriously injured",
                "No. moderately injured",
                "No. minor-other injured",
            )
            counts: list[int] = []
            for field in count_fields:
                count = _integer(payload[field])
                if count is None or count < 0:
                    invalid_people_counts[field] += 1
                else:
                    counts.append(count)
            if len(counts) == len(count_fields):
                analysis_fatalities += counts[0]
                analysis_casualties += sum(counts)

        latitude_present = not _blank(payload["Latitude"])
        longitude_present = not _blank(payload["Longitude"])
        if latitude_present and longitude_present:
            coordinate_pairs += 1
        elif latitude_present != longitude_present:
            partial_coordinate_pairs += 1

    unit_spec = selected["official_nsw_traffic_unit"]
    unit_stats = ParseStats()
    unit_keys: set[tuple[str, str]] = set()
    duplicate_unit_keys: Counter[tuple[str, str]] = Counter()
    blank_unit_parent_ids = 0
    blank_unit_ids = 0
    orphan_units = 0
    units_per_crash: Counter[str] = Counter()
    unit_type_groups: Counter[str] = Counter()
    units_by_parent_occurrence_year: Counter[str] = Counter()

    for row in iter_native_rows(unit_spec.path, unit_spec, unit_stats):
        payload = row.payload
        crash_id = payload["Crash ID"]
        unit_id = payload["Traffic unit ID"]
        if _blank(crash_id):
            blank_unit_parent_ids += 1
        if _blank(unit_id):
            blank_unit_ids += 1
        if not _blank(crash_id):
            assert crash_id is not None
            units_per_crash[crash_id] += 1
            units_by_parent_occurrence_year[
                _display(crash_year_by_id.get(crash_id))
            ] += 1
            if crash_id not in crash_ids:
                orphan_units += 1
        if not _blank(crash_id) and not _blank(unit_id):
            assert crash_id is not None and unit_id is not None
            key = (crash_id, unit_id)
            if key in unit_keys:
                duplicate_unit_keys[key] += 1
            unit_keys.add(key)
        unit_type_groups[_display(payload["TU type group"])] += 1

    mismatches = [
        {
            "crash_id": crash_id,
            "declared": declared,
            "observed": units_per_crash.get(crash_id, 0),
        }
        for crash_id, declared in declared_units.items()
        if declared is not None and declared != units_per_crash.get(crash_id, 0)
    ]

    result: dict[str, object] = {
        "contract": "nsw-pinned-pair-v1",
        "files": {
            "official_nsw_crash": {
                "sha256": hashes["official_nsw_crash"],
                "sheet": crash_spec.sheet,
                "raw_count": crash_stats.raw_count,
                "expected_raw_count": EXPECTED_COUNTS["official_nsw_crash"],
                "column_count": len(crash_stats.header),
                "blank_crash_ids": blank_crash_ids,
                "duplicate_crash_key_rows": sum(duplicate_crash_ids.values()),
                "invalid_declared_unit_counts": invalid_declared_units,
                "occurrence_years": dict(sorted(occurrence_years.items())),
                "reporting_years": dict(sorted(reporting_years.items())),
                "occurrence_months": dict(sorted(occurrence_months.items())),
                "severity": dict(sorted(severity.items())),
                "detailed_severity": dict(sorted(detailed_severity.items())),
                "coordinate_pairs": coordinate_pairs,
                "partial_coordinate_pairs": partial_coordinate_pairs,
                "reporting_occurrence_year_differences": (
                    reporting_occurrence_year_differences
                ),
            },
            "official_nsw_traffic_unit": {
                "sha256": hashes["official_nsw_traffic_unit"],
                "sheet": unit_spec.sheet,
                "raw_count": unit_stats.raw_count,
                "expected_raw_count": EXPECTED_COUNTS["official_nsw_traffic_unit"],
                "column_count": len(unit_stats.header),
                "blank_parent_crash_ids": blank_unit_parent_ids,
                "blank_traffic_unit_ids": blank_unit_ids,
                "duplicate_composite_key_rows": sum(duplicate_unit_keys.values()),
                "orphan_unit_rows": orphan_units,
                "unit_type_groups": dict(sorted(unit_type_groups.items())),
                "units_by_parent_occurrence_year": dict(
                    sorted(units_by_parent_occurrence_year.items())
                ),
            },
        },
        "relationship": {
            "declared_unit_count_mismatches": len(mismatches),
            "first_20_mismatches": mismatches[:20],
        },
        "analysis_scope_2020_2024": {
            "crash_count": len(analysis_crash_ids),
            "traffic_unit_count": sum(
                count
                for year, count in units_by_parent_occurrence_year.items()
                if year in ANALYSIS_YEARS
            ),
            "raw_only_2019_crash_count": occurrence_years["2019"],
            "raw_only_2019_traffic_unit_count": (
                units_by_parent_occurrence_year["2019"]
            ),
            "covered_year_months": len(analysis_months),
            "fatal_crash_count": analysis_fatal_crashes,
            "fatality_count": analysis_fatalities,
            "casualty_count": analysis_casualties,
            "invalid_people_counts": dict(sorted(invalid_people_counts.items())),
        },
    }

    _require(
        crash_stats.raw_count == EXPECTED_COUNTS["official_nsw_crash"],
        "NSW Crash row count differs from the frozen contract",
    )
    _require(
        unit_stats.raw_count == EXPECTED_COUNTS["official_nsw_traffic_unit"],
        "NSW Traffic Unit row count differs from the frozen contract",
    )
    _require(blank_crash_ids == 0, "NSW Crash contains a blank Crash ID")
    _require(not duplicate_crash_ids, "NSW Crash contains duplicate Crash IDs")
    _require(blank_unit_parent_ids == 0, "NSW Traffic Unit contains a blank Crash ID")
    _require(blank_unit_ids == 0, "NSW Traffic Unit contains a blank Traffic unit ID")
    _require(not duplicate_unit_keys, "NSW Traffic Unit contains duplicate composite keys")
    _require(orphan_units == 0, "NSW Traffic Unit contains orphan parent Crash IDs")
    _require(not mismatches, "NSW declared and observed traffic-unit counts differ")
    _require(
        result["analysis_scope_2020_2024"] == EXPECTED_ANALYSIS,
        "NSW 2020–2024 analysis observations differ from the reviewed snapshot",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate the pinned NSW Crash and Traffic Unit pair."
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON evidence path; stdout is always printed.",
    )
    args = parser.parse_args()
    result = validate()
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    print(encoded)
    if args.output:
        output = args.output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(encoded + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
