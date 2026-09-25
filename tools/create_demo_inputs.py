"""Generate 19 native parser smoke rows; not the semantic S0/QA fixture."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from openpyxl import Workbook


SAMPLES = {
    "official_nsw_crash": [
        {"Crash ID": "0001", "Year of crash": 2020, "Month of crash": "January",
         "Degree of crash": "Injury", "No. of traffic units involved": 2,
         "Street of crash": "Example road", "Latitude": -33.86, "Longitude": 151.21},
        {"Crash ID": "0002", "Year of crash": 2024, "Month of crash": "December",
         "Degree of crash": "Non-casualty (towaway)", "No. of traffic units involved": 1},
    ],
    "official_nsw_traffic_unit": [
        {"Crash ID": "0001", "Traffic unit ID": "01", "TU type group": "Car"},
        {"Crash ID": "0001", "Traffic unit ID": "02", "TU type group": "Bicycle"},
        {"Crash ID": "0002", "Traffic unit ID": "01", "TU type group": "Car"},
    ],
    "official_vic_accident": [
        {"ACCIDENT_NO": "0001", "ACCIDENT_DATE": "2019-12-31", "NODE_ID": "0010",
         "ACCIDENT_TYPE_DESC": "Example, with a comma\nand a quoted newline", "SEVERITY": "Unknown"},
        {"ACCIDENT_NO": "0002", "ACCIDENT_DATE": "2024-01-01", "NODE_ID": "0020",
         "ACCIDENT_TYPE_DESC": "Unicode example: café / 道路", "SEVERITY": "NA"},
    ],
    "official_vic_vehicle": [
        {"ACCIDENT_NO": "0001", "VEHICLE_ID": "01", "VEHICLE_TYPE_DESC": "Car"},
        {"ACCIDENT_NO": "0001", "VEHICLE_ID": "02", "VEHICLE_TYPE_DESC": "Bicycle"},
        {"ACCIDENT_NO": "0002", "VEHICLE_ID": "01", "VEHICLE_TYPE_DESC": "Unknown"},
    ],
    "official_vic_person": [
        {"ACCIDENT_NO": "0001", "PERSON_ID": "01", "VEHICLE_ID": "01", "AGE_GROUP": "Unknown"},
        {"ACCIDENT_NO": "0001", "PERSON_ID": "02", "VEHICLE_ID": "02", "AGE_GROUP": "  "},
        {"ACCIDENT_NO": "0002", "PERSON_ID": "01", "VEHICLE_ID": "01", "AGE_GROUP": "NA"},
    ],
    "official_vic_node": [
        {"ACCIDENT_NO": "0001", "NODE_ID": "0010", "LATITUDE": "-37.81", "LONGITUDE": "144.96"},
        {"ACCIDENT_NO": "0001", "NODE_ID": "0010", "LATITUDE": "-37.81", "LONGITUDE": "144.96"},
        {"ACCIDENT_NO": "0002", "NODE_ID": "0020", "POSTCODE_CRASH": "0300"},
        {"ACCIDENT_NO": "0002", "NODE_ID": "0020", "POSTCODE_CRASH": "0300"},
    ],
    "official_qld_crash": [
        {"Crash_Ref_Number": "0001", "Crash_Year": "2019", "Crash_Severity": "Unknown",
         "Count_Casualty_Total": "0", "Count_Unit_Car": "2", "Crash_Street": 'Example "quoted" street'},
        {"Crash_Ref_Number": "0002", "Crash_Year": "2024", "Crash_Severity": "NA",
         "Count_Casualty_Total": "1", "Count_Unit_Car": "1", "Count_Unit_Bicycle": "1"},
    ],
}


def create_demo(output: Path) -> Path:
    template = Path(__file__).resolve().parents[1] / "config" / "native-inputs.json"
    config = json.loads(template.read_text(encoding="utf-8"))
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Demo output must be a new or empty directory; choose another --output path")
    output.mkdir(parents=True, exist_ok=True)
    config["dataset_kind"] = "synthetic"
    for spec in config["resources"]:
        samples = SAMPLES[spec["resource_id"]]
        for sample in samples:
            if sample.keys() - set(spec["header"]):
                raise ValueError("Demo header baseline changed; review the smoke inputs")
        spec["source_id"] = spec["source_id"].replace("official_", "syn_", 1)
        spec["resource_id"] = spec["resource_id"].replace("official_", "syn_", 1)
        filename = f'{spec["resource_id"]}.{spec["format"]}'
        path = output / filename
        if spec["format"] == "csv":
            with path.open("x", encoding="utf-8-sig", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=spec["header"])
                writer.writeheader()
                writer.writerows(samples)
        else:
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = spec["sheet"]
            sheet.append(spec["header"])
            for sample in samples:
                sheet.append([sample.get(name) for name in spec["header"]])
            workbook.save(path)
            workbook.close()
        spec["path"] = filename
        with path.open("rb") as stream:
            spec["expected_sha256"] = hashlib.file_digest(stream, "sha256").hexdigest()
    target = output / "config.json"
    target.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        target = create_demo(args.output.expanduser().resolve())
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Cannot create demo: {exc}\n")
    print(f"Created 7 synthetic native files (19 rows) and {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
