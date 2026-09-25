"""Check the four local VIC files without changing or loading them."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import platform
import re


COUNTS = ("NO_OF_VEHICLES", "NO_PERSONS_KILLED", "NO_PERSONS_INJ_2",
          "NO_PERSONS_INJ_3", "NO_PERSONS_NOT_INJ", "NO_PERSONS")
KEYS = {"accident": ("ACCIDENT_NO",), "vehicle": ("ACCIDENT_NO", "VEHICLE_ID"),
        "person": ("ACCIDENT_NO", "PERSON_ID"), "node": ("ACCIDENT_NO", "NODE_ID")}


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def native_rows(path: Path, header: list[str]):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        if next(reader, None) != header:
            raise ValueError(f"Header does not match: {path.name}")
        for number, values in enumerate(reader, 1):
            if not values:
                continue
            if len(values) != len(header):
                raise ValueError(f"Wrong row width: {path.name}, csv:{number}")
            yield f"csv:{number}", dict(zip(header, values))


def nonnegative_integer(token: str) -> int | None:
    # Empty or unusual tokens are counted separately, never changed to zero.
    return int(token) if re.fullmatch(r"[0-9]+", token) else None


def profile(config_path: Path) -> dict:
    config_path = config_path.resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    specs = {name: next(r for r in config["resources"]
                       if r["resource_id"] == f"official_vic_{name}") for name in KEYS}
    paths = {name: (config_path.parent / spec["path"]).resolve()
             for name, spec in specs.items()}
    hashes = {name: sha256(path) for name, path in paths.items()}
    for name, spec in specs.items():
        if hashes[name] != spec["expected_sha256"]:
            raise ValueError(f"Input hash does not match: {paths[name].name}")

    report = {
        "profile_version": "vic-profile-v1", "checked_at": datetime.now(timezone.utc).isoformat(),
        "python_version": platform.python_version(),
        "scope": "local_file_observations", "config_sha256": sha256(config_path),
        "script_sha256": sha256(Path(__file__)), "files": {}, "findings": {},
        "limits": ["Counts describe these file bytes, not an approved release or database QA.",
                   "Person and Node observations support C's review; they do not replace it.",
                   "Raw vehicle/person totals may differ from a declared statistical scope."],
    }
    findings = report["findings"]
    for name in ("invalid_accident_date", "person_components_vs_declared_total",
                 "vehicle_missing_accident", "person_missing_accident", "node_missing_accident",
                 "person_blank_vehicle_reference", "person_nonblank_vehicle_not_found",
                 "node_invalid_or_missing_coordinates", "vehicle_rows_vs_declared",
                 "person_rows_vs_declared", "accident_node_match_not_found"):
        findings[name] = {"count": 0, "examples": []}

    def note(name: str, locator: str, **values):
        entry = findings.setdefault(name, {"count": 0, "examples": []})
        entry["count"] += 1
        parent = crashes.get(values.get("accident_no"))
        if parent:
            year = parent[1]["ACCIDENT_DATE"][:4]
            years_found = entry.setdefault("accident_years", {})
            years_found[year] = years_found.get(year, 0) + 1
            values["accident_date"] = parent[1]["ACCIDENT_DATE"]
        limit = 100 if name in {"person_nonblank_vehicle_not_found", "vehicle_rows_vs_declared",
                                "person_rows_vs_declared", "accident_node_match_not_found"} else 5
        if len(entry["examples"]) < limit:
            entry["examples"].append({"row_locator": locator, **values})

    def rows(name: str):
        seen = Counter()
        stats = {"resource_id": specs[name]["resource_id"], "filename": paths[name].name,
                 "file_sha256": hashes[name], "bytes": paths[name].stat().st_size,
                 "header": specs[name]["header"], "row_count": 0, "blank_key_rows": 0}
        report["files"][name] = stats
        for locator, row in native_rows(paths[name], specs[name]["header"]):
            stats["row_count"] += 1
            key = tuple(row[field] for field in KEYS[name])
            seen[key] += 1
            if any(not value.strip() for value in key):
                stats["blank_key_rows"] += 1
                note(f"{name}_blank_key", locator, key=list(key))
            yield locator, row
        stats["distinct_key_count"] = len(seen)
        stats["duplicate_key_groups"] = sum(n > 1 for n in seen.values())
        stats["duplicate_extra_rows"] = sum(n - 1 for n in seen.values())
        stats["duplicate_key_examples"] = [{"key": list(k), "rows": n}
                                           for k, n in seen.items() if n > 1][:5]

    crashes = {}
    years, severity, months = Counter(), Counter(), Counter()
    count_tokens = {field: Counter() for field in COUNTS}
    dates = []
    for locator, row in rows("accident"):
        key = row["ACCIDENT_NO"]
        crashes.setdefault(key, (locator, {field: row[field] for field in (*COUNTS, "NODE_ID", "ACCIDENT_DATE")}))
        token = row["ACCIDENT_DATE"]
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", token):
                raise ValueError(token)
            occurred = date.fromisoformat(token)
            years[str(occurred.year)] += 1
            months[token[:7]] += 1
            dates.append(token)
        except ValueError:
            note("invalid_accident_date", locator, accident_no=key, token=token)
        severity[row["SEVERITY"]] += 1
        for field in COUNTS:
            if nonnegative_integer(row[field]) is None:
                count_tokens[field][row[field]] += 1
        values = [nonnegative_integer(row[field]) for field in COUNTS[1:]]
        if all(value is not None for value in values) and sum(values[:4]) != values[4]:
            note("person_components_vs_declared_total", locator, accident_no=key,
                 components=values[:4], declared=values[4])
    report["accident"] = {"date_min": min(dates) if dates else None,
                          "date_max": max(dates) if dates else None,
                          "rows_by_year": dict(sorted(years.items())),
                          "rows_by_month": dict(sorted(months.items())),
                          "severity_tokens": dict(sorted(severity.items())),
                          "count_tokens_not_nonnegative_integers": {
                              k: dict(v) for k, v in count_tokens.items()}}

    vehicles = set()
    vehicle_counts, person_counts, vehicle_types = Counter(), Counter(), Counter()
    vehicle_descriptions = defaultdict(Counter)
    for locator, row in rows("vehicle"):
        crash = row["ACCIDENT_NO"]
        vehicles.add((crash, row["VEHICLE_ID"]))
        vehicle_counts[crash] += 1
        vehicle_types[row["VEHICLE_TYPE"]] += 1
        vehicle_descriptions[row["VEHICLE_TYPE"]][row.get("VEHICLE_TYPE_DESC", "")] += 1
        if row["VEHICLE_TYPE"] == "21":
            note("vehicle_type_21", locator, accident_no=crash, vehicle_id=row["VEHICLE_ID"],
                 description=row.get("VEHICLE_TYPE_DESC", ""))
        if crash not in crashes:
            note("vehicle_missing_accident", locator, accident_no=crash, vehicle_id=row["VEHICLE_ID"])
    report["vehicle_type_tokens"] = dict(sorted(vehicle_types.items()))
    report["vehicle_type_descriptions"] = {key: dict(value) for key, value in sorted(vehicle_descriptions.items())}

    for locator, row in rows("person"):
        crash, vehicle = row["ACCIDENT_NO"], row["VEHICLE_ID"]
        person_counts[crash] += 1
        if crash not in crashes:
            note("person_missing_accident", locator, accident_no=crash, person_id=row["PERSON_ID"])
        if not vehicle.strip():
            note("person_blank_vehicle_reference", locator, accident_no=crash, person_id=row["PERSON_ID"])
        elif (crash, vehicle) not in vehicles:
            note("person_nonblank_vehicle_not_found", locator, accident_no=crash,
                 person_id=row["PERSON_ID"], vehicle_id=vehicle)

    nodes = defaultdict(lambda: {"rows": 0, "coordinates": set(), "invalid": 0})
    for locator, row in rows("node"):
        crash, node = row["ACCIDENT_NO"], row["NODE_ID"]
        group = nodes[(crash, node)]
        group.setdefault("first_locator", locator)
        group["rows"] += 1
        if crash not in crashes:
            note("node_missing_accident", locator, accident_no=crash, node_id=node)
        try:
            lat, lon = Decimal(row["LATITUDE"]), Decimal(row["LONGITUDE"])
            if not lat.is_finite() or not lon.is_finite() or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("Invalid coordinates")
            group["coordinates"].add((lat, lon))
        except (InvalidOperation, ValueError):
            group["invalid"] += 1
            note("node_invalid_or_missing_coordinates", locator, accident_no=crash, node_id=node,
                 latitude=row["LATITUDE"], longitude=row["LONGITUDE"])

    for key, (locator, row) in crashes.items():
        for field, actual, label in (("NO_OF_VEHICLES", vehicle_counts[key], "vehicle_rows_vs_declared"),
                                     ("NO_PERSONS", person_counts[key], "person_rows_vs_declared")):
            declared = nonnegative_integer(row[field])
            if declared is not None and declared != actual:
                note(label, locator, accident_no=key, declared=declared, observed=actual)
        if row["NODE_ID"].strip() and (key, row["NODE_ID"]) not in nodes:
            note("accident_node_match_not_found", locator, accident_no=key, node_id=row["NODE_ID"])
    report["node_observations"] = {
        "matching_key_groups": len(nodes),
        "duplicate_groups": sum(g["rows"] > 1 for g in nodes.values()),
        "multiple_exact_coordinate_groups": sum(len(g["coordinates"]) > 1 for g in nodes.values()),
        "groups_with_invalid_coordinates": sum(g["invalid"] > 0 for g in nodes.values()),
        "conflict_examples": [{"accident_no": key[0], "node_id": key[1],
                               "first_row_locator": group["first_locator"],
                               "coordinates": [[str(a), str(b)] for a, b in sorted(group["coordinates"])]}
                              for key, group in nodes.items() if len(group["coordinates"]) > 1][:5],
        "note": "Coordinates are compared before rounding. No CRS or map eligibility is assigned.",
    }
    for name, path in paths.items():
        if sha256(path) != hashes[name]:
            raise ValueError(f"Input changed during profiling: {path.name}")
    for entry in findings.values():
        entry["examples_complete"] = len(entry["examples"]) == entry["count"]
    report["inputs_unchanged"] = True
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parents[1] / "config/native-inputs.json")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output already exists; use a new filename.")
    try:
        result = profile(args.config)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    except (OSError, ValueError, KeyError, StopIteration) as exc:
        parser.exit(1, f"Cannot profile VIC inputs: {exc}\n")
    print(f"Checked four VIC files. Results: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
