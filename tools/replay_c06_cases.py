"""Replay registered Person cases in an isolated database, then roll back."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = ROOT if (ROOT / "src/arsia_ingest").is_dir() else ROOT.parent / "Workspace/Workspace_Github"
REPO = Path(os.environ.get("ARSIA_REPOSITORY", DEFAULT_REPO))
sys.path[:0] = [str(ROOT / "src"), str(REPO / "src")]

from arsia_c.restricted_person import restricted_inputs, review_restricted
from arsia_ingest.config import load_config
from arsia_ingest.models import ParseStats
from arsia_ingest.raw_load import RawLoader
from arsia_ingest.readers import iter_native_rows
from arsia_ingest.runner import ModuleConnection


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def replay(output, input_config=None):
    if output.exists():
        raise ValueError("Choose a new evidence path; existing receipts are retained")
    spec, policy = restricted_inputs()
    keys = {c["accident_no"] for name in ("unmatched_person_vehicle", "unknown_role_blank_vehicle")
            for c in policy["cases"][name]}
    keys.update(c["accident_no"] for c in policy["cases"]["declared_count_differences"] if c["entity"] == "person")
    config = load_config(input_config or REPO / "config/native-inputs.json")
    declarations = {f["resource_id"]: f for f in spec["files"]}
    records, scans = [], []
    for resource in config.resources:
        if resource.resource_id not in declarations or resource.entity_kind == "node_raw":
            continue
        expected = declarations[resource.resource_id]
        with resource.path.open("rb") as stream:
            if stream.read(80).startswith(b"version https://git-lfs.github.com/spec/v1"):
                raise ValueError(
                    f"{resource.resource_id} is a Git LFS pointer. Retrieve the original "
                    "or use --input-config with an existing native-input configuration."
                )
        before = digest(resource.path)
        if before != expected["file_sha256"]:
            raise ValueError("Original file digest differs from the policy")
        stats = ParseStats()
        count = 0
        for row in iter_native_rows(resource.path, resource, stats):
            if row.payload["ACCIDENT_NO"] in keys:
                records.append({"source_id": resource.source_id, "resource_id": resource.resource_id,
                                "file_sha256": before, "parser_version": resource.parser_version,
                                "row_locator": row.row_locator, "payload": row.payload})
                count += 1
        after = digest(resource.path)
        if after != before or stats.raw_count != expected["raw_count"]:
            raise ValueError("Original file changed or its row count differs")
        scans.append({"resource_id": resource.resource_id, "file_sha256": before,
                      "full_native_rows": stats.raw_count, "excerpt_rows": count,
                      "digest_unchanged_after_scan": True})

    import psycopg

    connection = psycopg.connect(os.environ["ARSIA_TEST_DSN"], autocommit=False, connect_timeout=10)
    def counts():
        return {t: connection.execute("SELECT count(*) FROM " + t).fetchone()[0]
                for t in ("meta.source", "meta.resource", "raw.record")}
    try:
        before_counts = counts()
        if any(before_counts.values()):
            raise ValueError("Use the empty isolated test database, not a shared database")
        environment = connection.execute("SELECT version(), current_user, current_setting('TimeZone')").fetchone()
        if connection.info.server_version // 10000 != 16:
            raise ValueError("Use PostgreSQL 16")
        loader = RawLoader(ModuleConnection(connection), dataset_kind="official",
                           sources=[{"source_id": "official_vic", "jurisdiction_code": "VIC",
                                     "source_name": "VIC C06 official case excerpt", "publisher": "Transport Victoria"}],
                           files=spec["files"])
        loader.register()
        for record in records:
            loader.load_record(record)
        report = review_restricted(ModuleConnection(connection), spec["files"], spec["analysis"], policy)
        if (report["status"] != "block" or not report["policy_checks"]["case_set_match"]
                or report["registered_limitations"] != {"counts": 2, "blank": 24, "unmatched": 39}
                or report["reason_counts"].get("selected_raw_count_mismatch") != 3
                or set(report["reason_counts"]) != {"selected_raw_count_mismatch", "pedestrian_count_match_failed"}):
            raise AssertionError("Official excerpt did not produce the expected case matches and completeness blocks")
    finally:
        connection.rollback()
        after_counts = counts()
        connection.rollback()
        connection.close()
    if after_counts != before_counts:
        raise AssertionError("Test rows remained after rollback")
    receipt = {"at_utc": datetime.now(timezone.utc).isoformat(),
               "scope": "Official registered-case excerpt only; three full native scans, no full Raw load or publication.",
               "environment": dict(zip(("version", "user", "timezone"), environment)),
               "scans": scans, "selected_accidents": len(keys), "loaded_excerpt_rows": len(records),
               "before_counts": before_counts, "after_counts": after_counts,
               "expected_completeness_block_observed": True, "report": report}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"excerpt_rows": len(records), "case_matches": report["registered_limitations"],
                      "status": report["status"], "expected_completeness_block": True}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--input-config", type=Path,
                        help="Native-input configuration for existing originals; defaults to the repository configuration")
    args = parser.parse_args()
    replay(args.evidence, args.input_config)
