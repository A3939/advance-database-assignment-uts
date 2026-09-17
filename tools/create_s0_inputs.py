"""Write the team's S0 native files, or one separate input variant."""
import argparse
import copy
import csv
import hashlib
import io
import json
import re
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from openpyxl import Workbook


ROOT = Path(__file__).resolve().parents[1]
VARIANTS = (
    "s0", "missing_file", "bad_header", "bad_hash", "duplicate_crash",
    "orphan_unit", "person_vehicle_99", "invalid_date", "negative_count",
    "undefined_category", "invalid_coordinate", "unknown_crs", "revised_n1",
    "delete_q2", "delete_q2_unexplained",
)
FIXED_TIME = datetime(2000, 1, 1)


def _xlsx_bytes(spec: dict, rows: list[dict], header: list[str]) -> bytes:
    workbook = Workbook()
    workbook.properties.creator = "ARSIA team"
    workbook.properties.lastModifiedBy = "ARSIA team"
    workbook.properties.created = FIXED_TIME
    workbook.properties.modified = FIXED_TIME
    sheet = workbook.active
    sheet.title = spec["sheet"]
    sheet.append(header)
    for row in rows:
        sheet.append([row.get(field) for field in spec["header"]])
    buffer = io.BytesIO()
    workbook.save(buffer)
    workbook.close()

    # openpyxl updates the modified time when saving; keep fixture hashes stable.
    result = io.BytesIO()
    with ZipFile(buffer) as original, ZipFile(result, "w") as fixed:
        for name in sorted(original.namelist()):
            data = original.read(name)
            if name == "docProps/core.xml":
                data = re.sub(
                    rb"(<dcterms:modified\b[^>]*>).*?(</dcterms:modified>)",
                    rb"\g<1>2000-01-01T00:00:00Z\g<2>", data,
                )
            info = ZipInfo(name, (2000, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o600 << 16
            fixed.writestr(info, data, compresslevel=9)
    return result.getvalue()


def _native_bytes(spec: dict, rows: list[dict], header: list[str]) -> bytes:
    if spec["format"] == "xlsx":
        return _xlsx_bytes(spec, rows, header)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\r\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([row.get(field, "") for field in spec["header"]])
    return stream.getvalue().encode("utf-8-sig")


def _apply_variant(definition: dict, variant: str) -> None:
    resources = {item["resource_id"]: item for item in definition["resources"]}
    rows = {rid: item["rows"] for rid, item in resources.items()}
    if variant == "duplicate_crash":
        rows["syn_nsw_crash"].append(copy.deepcopy(rows["syn_nsw_crash"][0]))
    elif variant == "orphan_unit":
        rows["syn_vic_vehicle"][2]["ACCIDENT_NO"] = "9999"
    elif variant == "person_vehicle_99":
        rows["syn_vic_person"][2]["VEHICLE_ID"] = "99"
    elif variant == "invalid_date":
        rows["syn_vic_accident"][1]["ACCIDENT_DATE"] = "2021-02-30"
    elif variant == "negative_count":
        rows["syn_vic_accident"][0]["NO_PERSONS_KILLED"] = "-1"
    elif variant == "undefined_category":
        rows["syn_vic_accident"][1]["SEVERITY"] = "X"
    elif variant == "invalid_coordinate":
        rows["syn_qld_crash"][0]["Crash_Latitude"] = "-91"
    elif variant == "unknown_crs":
        resources["syn_qld_crash"]["mapping"]["location"]["crs"] = None
        resources["syn_qld_crash"]["mapping"]["location"]["basis"] = (
            "AT07 deliberately removes the synthetic CRS declaration."
        )
    elif variant == "revised_n1":
        rows["syn_nsw_crash"][0]["No. killed"] = 3
        definition["sources"][0]["release_label"] = "Synthetic S0 NSW revision 1"
        definition["snapshot_change"] = {
            "source_id": "syn_nsw", "previous_release_label": "Synthetic S0 v1",
            "kind": "correction", "native_key": ["0001"],
            "description": "N1 deaths corrected from 2 to 3; casualties from 3 to 4. Other components stay unchanged.",
        }
    elif variant in {"delete_q2", "delete_q2_unexplained"}:
        rows["syn_qld_crash"].pop()
        definition["sources"][2]["release_label"] = "Synthetic S0 QLD revision 1"
        if variant == "delete_q2":
            definition["snapshot_change"] = {
                "source_id": "syn_qld", "previous_release_label": "Synthetic S0 v1",
                "kind": "deletion", "native_key": ["0002"],
                "description": "Q2 is intentionally removed from this complete replacement snapshot. Coverage stays 2020–2024.",
            }


def create_s0(output: Path, variant: str = "s0") -> Path:
    """Create one fixture directory without replacing existing files."""
    if variant not in VARIANTS:
        raise ValueError(f"Unknown S0 variant: {variant}")
    output = Path(output).expanduser().resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Output must be a new or empty directory; choose another --output path")
    definition = json.loads((ROOT / "config/synthetic-s0.json").read_text(encoding="utf-8"))
    template = json.loads((ROOT / "config/native-inputs.json").read_text(encoding="utf-8"))
    _apply_variant(definition, variant)
    resources = {item["resource_id"]: item for item in definition["resources"]}
    config = {"config_version": "intake-v1", "dataset_kind": "synthetic", "resources": []}
    contracts = []
    pending_files = []
    for original in template["resources"]:
        spec = copy.deepcopy(original)
        spec["source_id"] = spec["source_id"].replace("official_", "syn_", 1)
        spec["resource_id"] = spec["resource_id"].replace("official_", "syn_", 1)
        rid = spec["resource_id"]
        resource = resources.pop(rid)
        samples = resource.pop("rows")
        mapped_fields = set(resource["used_fields"])
        if mapped_fields - set(spec["header"]):
            raise ValueError(f"Unknown declared fields for {rid}")
        for row in samples:
            if row.keys() - mapped_fields:
                raise ValueError(f"Undeclared fixture fields for {rid}: {row.keys() - mapped_fields}")
        actual_header = list(spec["header"])
        if variant == "bad_header" and rid == "syn_vic_accident":
            actual_header[0] = "ACCIDENT_NUMBER"
        data = _native_bytes(spec, samples, actual_header)
        spec["path"] = f'{rid}.{spec["format"]}'
        actual_hash = hashlib.sha256(data).hexdigest()
        spec["expected_sha256"] = (
            "0" * 64 if variant == "bad_hash" and rid == "syn_vic_accident" else actual_hash
        )
        config["resources"].append(spec)
        contracts.append({
            **resource,
            "source_id": spec["source_id"], "resource_role": spec["resource_role"],
            "entity_kind": spec["entity_kind"], "raw_count": len(samples),
            "native": {
                key: spec[key] for key in (
                    "path", "format", "encoding", "sheet", "header_row", "header", "expected_sha256",
                )
            },
            "parser_version": "csv-native-v1" if spec["format"] == "csv" else "xlsx-native-v1",
            "locator_version": "csv-logical-v1" if spec["format"] == "csv" else "xlsx-physical-v1",
            "unused_fields": [field for field in spec["header"] if field not in mapped_fields],
        })
        if not (variant == "missing_file" and rid == "syn_vic_node"):
            pending_files.append((spec["path"], data))
    if resources:
        raise ValueError(f"No native header template for: {', '.join(resources)}")
    definition["resources"] = contracts
    definition["variant"] = {
        "name": variant,
        **definition.pop("variants")[variant],
        "test_status": "NOT_RUN",
    }
    output.mkdir(parents=True, exist_ok=True)
    for name, data in pending_files:
        with (output / name).open("xb") as stream:
            stream.write(data)
    for name, content in (("config.json", config), ("contract.json", definition)):
        with (output / name).open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(content, ensure_ascii=False, indent=2) + "\n")
    return output / "config.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variant", choices=VARIANTS, default="s0")
    args = parser.parse_args()
    try:
        target = create_s0(args.output, args.variant)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Cannot create S0 inputs: {exc}\n")
    print(f"Created {args.variant} input fixture: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
