"""Reconcile saved public responses with the pinned VIC inputs, offline."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(repo, evidence):
    sys.path.insert(0, str(repo / "tools"))
    from profile_vic_inputs import native_rows

    checks = []

    def check(label, condition):
        checks.append({"check": label, "passed": bool(condition)})
        if not condition:
            raise ValueError(label)

    def read(name):
        return json.loads((evidence / name).read_text(encoding="utf-8"))

    responses = {}
    failures = []
    for filename in ("api-replay.json", "api-extra.json", "api-types.json", "source-retrieval.json"):
        for item in read(filename)["requests"]:
            raw = item["response_raw_utf8"].encode()
            check(f"{filename}:{item['label']}: saved body intact",
                  hashlib.sha256(raw).hexdigest() == item["response_sha256"]
                  and len(raw) == item["response_bytes"])
            if item["curl_exit"] or item["http_status"] != 200:
                failures.append({"file": filename, "label": item["label"],
                                 "http_status": item["http_status"], "error": item["error"]})
                continue
            if item["label"] == "statistics_support":
                continue
            data = json.loads(raw)
            check(f"{filename}:{item['label']}: API success", data.get("success") is True)
            result = data["result"]
            if "records" in result:
                check(f"{filename}:{item['label']}: complete selected response",
                      result["total"] == len(result["records"]) and not result.get("total_was_estimated"))
                filters = json.loads(item["parameters"]["filters"])
                check(f"{filename}:{item['label']}: rows match request",
                      all(all(row[key] in value if isinstance(value, list) else row[key] == value
                              for key, value in filters.items()) for row in result["records"]))
            responses[item["label"]] = result

    old_path = repo / "docs/sources/evidence/vic/person-node-local-review-2026-09-17.json"
    old = json.loads(old_path.read_text(encoding="utf-8"))
    local = read("local-review.json")
    ignored = {"checked_at_utc"}
    check("Fresh full-file review matches historical content except timestamp",
          {k: v for k, v in old.items() if k not in ignored} ==
          {k: v for k, v in local.items() if k not in ignored})
    check("Original files unchanged during fresh scan", local["inputs_unchanged"])
    comparison = read("api-comparison.json")
    check("All 39 selected unmatched references still present and unmatched",
          len(comparison["original_unmatched_references"]) == 39 and
          all(r["reference_unchanged"] and r["vehicle_still_absent"]
              for r in comparison["original_unmatched_references"]))
    check("All 85 selected missing Nodes still missing", len(comparison["original_missing_node_cases"]) == 85
          and all(r["still_absent"] for r in comparison["original_missing_node_cases"]))
    check("All 12 previous flat comparisons still numerically equal",
          len(comparison["node_and_flat_coordinates"]) == 12
          and all(r["all_selected_values_numerically_equal"] for r in comparison["node_and_flat_coordinates"]))

    config = json.loads((repo / "config/native-inputs.json").read_text(encoding="utf-8"))
    specs = {r["resource_id"].removeprefix("official_vic_"): r for r in config["resources"]
             if r["resource_id"].startswith("official_vic_")}
    selected = {
        "person": {"person_blank_and_linked_pedestrian": lambda r: r["ACCIDENT_NO"] in
                   {p["accident_no"] for p in old["person"]["blank_nonpedestrians"] +
                    old["person"]["pedestrians_with_nonblank_vehicle"]},
                   "person_type16": lambda r: r["ROAD_USER_TYPE"] == "16"},
        "vehicle": {"vehicle_blank_and_linked_pedestrian": lambda r: r["ACCIDENT_NO"] in
                    {p["accident_no"] for p in old["person"]["blank_nonpedestrians"] +
                     old["person"]["pedestrians_with_nonblank_vehicle"]},
                    "vehicle_type21": lambda r: r["VEHICLE_TYPE"] == "21"},
    }
    selected_checks = {}
    for resource, tests in selected.items():
        spec = specs[resource]
        path = (repo / "config" / spec["path"]).resolve()
        check(f"{resource}: current CSV SHA256", digest(path) == spec["expected_sha256"])
        header = spec["header"]
        expected = {label: Counter() for label in tests}
        for locator, row in native_rows(path, header):
            for label, predicate in tests.items():
                if predicate(row):
                    expected[label][tuple(row[field] for field in header)] += 1
        for label in tests:
            received = Counter(tuple("" if row[field] is None else str(row[field]) for field in header)
                               for row in responses[label]["records"])
            check(f"{label}: complete row multiset equals pinned CSV", expected[label] == received)
            selected_checks[label] = {"local_rows": expected[label].total(), "api_rows": received.total()}
        check(f"{resource}: CSV unchanged after comparison", digest(path) == spec["expected_sha256"])

    location_rows = responses["accident_location_cases"]["records"]
    locations = {r["ACCIDENT_NO"]: r for r in location_rows}
    check("Accident Location: one row per requested crash", len(location_rows) == len(locations) == 90)
    missing_locations = []
    for missing in old["node"]["missing_matches"]:
        row = locations[missing["accident_no"]]
        check(f"{missing['accident_no']}: same negative Node in Accident Location",
              row["NODE_ID"] == missing["accident"]["NODE_ID"])
        missing_locations.append({"accident_no": row["ACCIDENT_NO"], "node_id": row["NODE_ID"],
                                  "api_id": row["_id"], "scope": missing["scope"],
                                  "road_name": row["ROAD_NAME"], "road_name_int": row["ROAD_NAME_INT"]})
    duplicate_examples = []
    for group in old["node"]["example_groups"]:
        row = locations[group["accident_no"]]
        check(f"{group['accident_no']}: positive Node agrees with Accident Location", row["NODE_ID"] == group["node_id"])
        duplicate_examples.append({"accident_no": group["accident_no"], "node_id": group["node_id"],
                                   "node_rows": len(group["rows"]), "accident_location_rows": 1,
                                   "lga_names": dict(Counter(r["LGA_NAME"] for r in group["rows"])),
                                   "node_locators": [r["row_locator"] for r in group["rows"]],
                                   "location_api_id": row["_id"]})

    metadata = {}
    fields = ("dataset_last_updated_date", "reporting_period_start", "reporting_period_end",
              "geographic_coordinate_system", "hash", "datastore_contains_all_records_of_source_file")
    for label in ("current_package", "datavic_package", "national_package"):
        package = responses[label]
        metadata[label] = [{"name": r["name"], "id": r["id"], **{k: r.get(k) for k in fields}}
                           for r in package["resources"] if r["name"] in
                           {"Accident", "Vehicle", "Person", "Node", "Accident Location", "Victorian Road Crash Data"}]

    hashes = {str(path.relative_to(repo)): digest(path) for path in [old_path, repo / "config/native-inputs.json",
              repo / "docs/sources/vic-accident-vehicle.md", repo / "tools/review_vic_links.py",
              repo / "tools/compare_vic_evidence.py", repo / "tools/profile_vic_inputs.py"]}
    c_commit = "87d1c5803a6ec61475823ea877a995ba589f22f7"
    c_doc = subprocess.check_output(["git", "show", c_commit + ":docs/role-c/c02-vic-person-node-review.md"], cwd=repo)
    return dict(checked_at_utc=datetime.now(timezone.utc).isoformat(),
                scope="Evidence consistency checks; no source approval, C02 sign-off, SQL QA or CRS transformation",
                checks=checks, passed=sum(r["passed"] for r in checks),
                retained_failed_requests=failures, local_review_matches_history=True,
                additional_selections=selected_checks, negative_nodes_in_accident_location=missing_locations,
                duplicate_node_examples=duplicate_examples, metadata=metadata,
                reviewed_c_commit=c_commit, reviewed_c02_sha256=hashlib.sha256(c_doc).hexdigest(),
                repository_evidence_sha256=hashes)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2] / "Workspace_Github")
    parser.add_argument("--evidence", type=Path, default=Path(__file__).resolve().parent / "evidence")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Use a new output file.")
    result = run(args.repo.resolve(), args.evidence.resolve())
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(f"{result['passed']} evidence consistency checks passed")
