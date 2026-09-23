"""Save public VIC responses for a separate source review; never change inputs."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from urllib.parse import urlencode

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1] / "Workspace_Github"
API = "https://opendata.transport.vic.gov.au/api/3/action/"
EVIDENCE = REPO / "docs/sources/evidence/vic"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fetch(label, url, parameters=None):
    proc = subprocess.run([
        "curl", "--silent", "--show-error", "--location", "--max-time", "35",
        "--max-filesize", "5000000", "--write-out", "\n%{http_code}\n%{url_effective}",
        url,
    ], capture_output=True)
    body, status, final_url = proc.stdout.rsplit(b"\n", 2)
    result = dict(label=label, url=url, final_url=final_url.decode(),
                  retrieved_at_utc=datetime.now(timezone.utc).isoformat(),
                  http_status=int(status or 0), curl_exit=proc.returncode,
                  error=proc.stderr.decode(), response_bytes=len(body),
                  response_sha256=sha(body), response_raw_utf8=body.decode("utf-8"))
    if parameters is not None:
        result["parameters"] = parameters
    print(label, result["http_status"], len(body), flush=True)
    return result


def request(label, resource, filters):
    params = dict(resource_id=resource, filters=json.dumps(filters), limit=2000)
    return fetch(label, API + "datastore_search?" + urlencode(params), params)


def collect(mode):
    old = json.loads((EVIDENCE / "person-node-api-check-2026-09-17.json").read_text())
    review = json.loads((EVIDENCE / "person-node-local-review-2026-09-17.json").read_text())
    if mode == "replay":
        requests = [fetch(r["label"], r["url"], r["parameters"]) for r in old["requests"]]
        return dict(purpose="2026-09-23 replay of the saved targeted selections; not a full release check",
                    local_review_sha256=old["local_review_sha256"], requests=requests)
    if mode == "types":
        return dict(purpose="Retry category selections using the DataStore text field types", requests=[
            request("vehicle_type21", "6d0b21f7-583a-4991-a168-f15a70c13ec4", {"VEHICLE_TYPE": "21"}),
            request("person_type16", "60c8fc0c-2806-40f3-bb33-5c52691120e8", {"ROAD_USER_TYPE": "16"}),
        ])
    if mode == "extra":
        ids = sorted({r["accident_no"] for r in review["person"]["blank_nonpedestrians"]}
                     | {r["accident_no"] for r in review["person"]["pedestrians_with_nonblank_vehicle"]})
        node_ids = sorted({r["accident_no"] for r in review["node"]["missing_matches"]}
                          | {r["accident_no"] for r in review["node"]["example_groups"]})
        requests = [
            request("person_blank_and_linked_pedestrian", "60c8fc0c-2806-40f3-bb33-5c52691120e8", {"ACCIDENT_NO": ids}),
            request("vehicle_blank_and_linked_pedestrian", "6d0b21f7-583a-4991-a168-f15a70c13ec4", {"ACCIDENT_NO": ids}),
            request("vehicle_type21", "6d0b21f7-583a-4991-a168-f15a70c13ec4", {"VEHICLE_TYPE": 21}),
            request("person_type16", "60c8fc0c-2806-40f3-bb33-5c52691120e8", {"ROAD_USER_TYPE": 16}),
            request("accident_location_cases", "e1beb92b-5836-448a-9769-e7aa6a9e7413", {"ACCIDENT_NO": node_ids}),
        ]
        return dict(purpose="Additional selected Person/Vehicle and Accident Location checks", requests=requests)
    urls = [
        ("datavic_package", "https://discover.data.vic.gov.au/api/3/action/package_show?id=victoria-road-crash-data"),
        ("national_package", "https://data.gov.au/data/api/3/action/package_show?id=victoria-road-crash-data"),
        ("statistics_support", "https://www.vic.gov.au/road-crash-statistics"),
        ("legacy_guide", "https://data.vicroads.vic.gov.au/metadata/crashstats_user_guide_and_appendices.pdf"),
        ("legacy_guide_http", "http://data.vicroads.vic.gov.au/metadata/crashstats_user_guide_and_appendices.pdf"),
        ("legacy_uguide", "http://crashstat1.roads.vic.gov.au/crashstats/uguide.pdf"),
    ]
    return dict(purpose="Metadata mirrors, official contact and legacy guide availability", requests=[fetch(*item) for item in urls])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["replay", "extra", "sources", "types"])
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Use a new output file.")
    result = collect(args.mode)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
