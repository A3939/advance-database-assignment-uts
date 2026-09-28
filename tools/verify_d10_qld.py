"""Reproduce D10 QLD source evidence from the unchanged file in raw.zip."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import zipfile
from collections import Counter
from pathlib import Path


MEMBER = "raw/qld_crash_locations.csv"
FILE_SHA256 = "975be4b02a235d06589de9b486f73bafe22d0f2007f0c07abb84f54cb926c704"
YEAR_FROM = 2020
YEAR_TO = 2024
MONTHS = {
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
CASUALTY_FIELDS = (
    "Count_Casualty_Fatality",
    "Count_Casualty_Hospitalised",
    "Count_Casualty_MedicallyTreated",
    "Count_Casualty_MinorInjury",
    "Count_Casualty_Total",
)
UNIT_FIELDS = (
    "Count_Unit_Car",
    "Count_Unit_Motorcycle_Moped",
    "Count_Unit_Truck",
    "Count_Unit_Bus",
    "Count_Unit_Bicycle",
    "Count_Unit_Pedestrian",
    "Count_Unit_Other",
)
EXPECTED_YEARS = {2020: 12147, 2021: 13476, 2022: 13021, 2023: 13622, 2024: 14358}
EXPECTED_SEVERITY = {
    "Fatal": 1304,
    "Hospitalisation": 31922,
    "Medical treatment": 22730,
    "Minor injury": 10668,
    "Property damage only": 0,
}


def _hash_member(archive: Path, member: str) -> str:
    digest = hashlib.sha256()
    with zipfile.ZipFile(archive) as zipped, zipped.open(member) as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _integer(value: str) -> int | None:
    text = value.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def scan(archive: Path, member: str = MEMBER) -> dict:
    keys: set[str] = set()
    duplicate_keys = 0
    blank_keys = 0
    full_rows = 0
    analysis_rows = 0
    by_year: Counter[int] = Counter()
    by_month: Counter[tuple[int, int]] = Counter()
    severity: Counter[str] = Counter()
    casualty_sums: Counter[str] = Counter()
    unit_sums: Counter[str] = Counter()
    unit_nonzero_rows: Counter[str] = Counter()
    missing_casualty_rows = 0
    invalid_casualty_rows = 0
    negative_casualty_rows = 0
    casualty_mismatch_rows = 0
    missing_unit_rows = 0
    invalid_unit_rows = 0
    negative_unit_rows = 0
    native_coordinate_rows = 0
    blank_coordinate_rows = 0
    invalid_coordinate_rows = 0
    examples: list[dict[str, str]] = []

    with zipfile.ZipFile(archive) as zipped, zipped.open(member) as binary:
        with io.TextIOWrapper(binary, encoding="utf-8-sig", newline="") as text:
            reader = csv.DictReader(text)
            if reader.fieldnames is None or len(reader.fieldnames) != 52:
                raise ValueError("QLD source must retain its exact 52-column header")
            for row in reader:
                full_rows += 1
                key = row["Crash_Ref_Number"].strip()
                if not key:
                    blank_keys += 1
                elif key in keys:
                    duplicate_keys += 1
                else:
                    keys.add(key)

                year = _integer(row["Crash_Year"])
                if year is None or not YEAR_FROM <= year <= YEAR_TO:
                    continue
                analysis_rows += 1
                by_year[year] += 1
                month = MONTHS.get(row["Crash_Month"].strip())
                if month is not None:
                    by_month[(year, month)] += 1
                severity[row["Crash_Severity"].strip()] += 1
                if len(examples) < 5:
                    examples.append({
                        "row_locator": f"csv:{full_rows}",
                        "Crash_Ref_Number": key,
                        "Crash_Year": row["Crash_Year"],
                        "Crash_Month": row["Crash_Month"],
                        "Crash_Severity": row["Crash_Severity"],
                    })

                casualty_values: dict[str, int] = {}
                casualty_missing = False
                casualty_invalid = False
                casualty_negative = False
                for field in CASUALTY_FIELDS:
                    raw = row[field].strip()
                    value = _integer(raw)
                    if not raw:
                        casualty_missing = True
                    elif value is None:
                        casualty_invalid = True
                    elif value < 0:
                        casualty_negative = True
                    else:
                        casualty_values[field] = value
                        casualty_sums[field] += value
                missing_casualty_rows += casualty_missing
                invalid_casualty_rows += casualty_invalid
                negative_casualty_rows += casualty_negative
                if len(casualty_values) == len(CASUALTY_FIELDS):
                    components = sum(casualty_values[field] for field in CASUALTY_FIELDS[:-1])
                    casualty_mismatch_rows += components != casualty_values[CASUALTY_FIELDS[-1]]

                unit_missing = False
                unit_invalid = False
                unit_negative = False
                for field in UNIT_FIELDS:
                    raw = row[field].strip()
                    value = _integer(raw)
                    if not raw:
                        unit_missing = True
                    elif value is None:
                        unit_invalid = True
                    elif value < 0:
                        unit_negative = True
                    else:
                        unit_sums[field] += value
                        unit_nonzero_rows[field] += value > 0
                missing_unit_rows += unit_missing
                invalid_unit_rows += unit_invalid
                negative_unit_rows += unit_negative

                latitude = row["Crash_Latitude"].strip()
                longitude = row["Crash_Longitude"].strip()
                if not latitude and not longitude:
                    blank_coordinate_rows += 1
                elif not latitude or not longitude:
                    invalid_coordinate_rows += 1
                else:
                    try:
                        lat, lon = float(latitude), float(longitude)
                    except ValueError:
                        invalid_coordinate_rows += 1
                    else:
                        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                            invalid_coordinate_rows += 1
                        else:
                            native_coordinate_rows += 1

    month_rows = [
        {"year": year, "month": month, "crash_count": by_month[(year, month)]}
        for year in range(YEAR_FROM, YEAR_TO + 1)
        for month in range(1, 13)
    ]
    result = {
        "evidence_version": "d10-qld-source-query-v1",
        "scope": {
            "source_id": "official_qld",
            "resource_id": "official_qld_crash",
            "release_scope": "qld_pinned_2020_2024_v1",
            "file_sha256": _hash_member(archive, member),
            "analysis_year_from": YEAR_FROM,
            "analysis_year_to": YEAR_TO,
            "source_grain": "one native row per crash",
            "native_key": ["Crash_Ref_Number"],
        },
        "key_query": {
            "full_source_rows": full_rows,
            "distinct_nonblank_keys": len(keys),
            "blank_keys": blank_keys,
            "duplicate_keys": duplicate_keys,
            "analysis_rows": analysis_rows,
            "examples": examples,
        },
        "month_query": {
            "rows_by_year": {str(year): by_year[year] for year in range(YEAR_FROM, YEAR_TO + 1)},
            "year_month_rows": month_rows,
            "observed_year_months": sum(row["crash_count"] > 0 for row in month_rows),
            "missing_or_unknown_month_rows": analysis_rows - sum(by_month.values()),
        },
        "severity_query": {
            "counts": {name: severity[name] for name in EXPECTED_SEVERITY},
            "missing_or_unknown_rows": analysis_rows - sum(severity.values()),
            "definition_version": "qld-native-severity-v1",
        },
        "unknown_count_query": {
            "rows_with_missing_casualty_count": missing_casualty_rows,
            "rows_with_invalid_casualty_count": invalid_casualty_rows,
            "rows_with_negative_casualty_count": negative_casualty_rows,
            "casualty_component_mismatch_rows": casualty_mismatch_rows,
            "fatality_sum": casualty_sums["Count_Casualty_Fatality"],
            "casualty_total_sum": casualty_sums["Count_Casualty_Total"],
        },
        "unit_aggregate_query": {
            "handling": "crash-row aggregate attributes only; no Unit entity or parent relationship",
            "rows_with_missing_unit_count": missing_unit_rows,
            "rows_with_invalid_unit_count": invalid_unit_rows,
            "rows_with_negative_unit_count": negative_unit_rows,
            "category_sums": {field: unit_sums[field] for field in UNIT_FIELDS},
            "crash_rows_with_nonzero_category": {
                field: unit_nonzero_rows[field] for field in UNIT_FIELDS
            },
        },
        "location_query": {
            "native_coordinate_rows": native_coordinate_rows,
            "blank_coordinate_rows": blank_coordinate_rows,
            "invalid_coordinate_rows": invalid_coordinate_rows,
            "source_crs": "GDA2020",
            "published_map_status": "unavailable",
            "published_map_count": 0,
            "published_unmapped_count": analysis_rows,
            "reason": "definition_unconfirmed: no validated GDA2020 to EPSG:4326 operation",
        },
        "published_build": {
            "basis_commit": "562de2910bfd7be276b3036983e5680d436fde1e",
            "batch_id": "d6f0e958-7c94-4f2f-ba85-9d44e597cc02",
            "status": "succeeded",
            "qa06": "pass",
            "qa07": "limited",
            "crash_count": 66624,
            "fatal_crash_count": 1304,
            "fatality_count": 1424,
            "casualty_count": 88609,
            "canonical_unit_count": 0,
            "report_eligible_unit_count": 0,
            "trend_rows": 5,
            "monthly_rows": 60,
            "severity_rows": 4,
            "map_rows": None,
            "unit_rows": None,
        },
        "limits": [
            "The exact pinned file and occurrence years 2020-2024 are the reporting scope.",
            "Crash_Ref_Number is opaque text; the year comes only from Crash_Year.",
            "Severity and casualty definitions remain QLD source-specific; do not pool interstate totals.",
            "Count_Unit_* values are crash-row aggregates and cannot create Unit or Person records.",
            "Native GDA2020 coordinates are present, but official map output remains unavailable.",
            "Zero Property damage only rows after 2010 does not mean zero real property-only crashes.",
        ],
    }
    if result["scope"]["file_sha256"] != FILE_SHA256:
        raise ValueError("QLD file SHA-256 differs from the frozen source contract")
    if full_rows != 415407 or analysis_rows != 66624:
        raise ValueError("QLD row counts differ from the frozen source evidence")
    if dict(by_year) != EXPECTED_YEARS or result["severity_query"]["counts"] != EXPECTED_SEVERITY:
        raise ValueError("QLD category counts differ from the frozen source evidence")
    if casualty_sums["Count_Casualty_Fatality"] != 1424 or casualty_sums["Count_Casualty_Total"] != 88609:
        raise ValueError("QLD casualty totals differ from the frozen source evidence")
    if any((blank_keys, duplicate_keys, missing_casualty_rows, invalid_casualty_rows,
            negative_casualty_rows, casualty_mismatch_rows, missing_unit_rows,
            invalid_unit_rows, negative_unit_rows, blank_coordinate_rows,
            invalid_coordinate_rows)):
        raise ValueError("QLD frozen analysis slice contains an unexpected key/value defect")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--member", default=MEMBER)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = scan(args.archive, args.member)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "file_sha256": result["scope"]["file_sha256"],
        "full_source_rows": result["key_query"]["full_source_rows"],
        "analysis_rows": result["key_query"]["analysis_rows"],
        "status": "passed",
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
