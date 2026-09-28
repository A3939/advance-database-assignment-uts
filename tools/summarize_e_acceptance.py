#!/usr/bin/env python3
"""Summarize completed E replays without copying raw rows or credentials."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


TABLES = {
    "meta.source", "meta.resource", "meta.batch", "meta.current_release", "raw.record",
    "rv.hub_crash", "rv.hub_unit", "rv.sat_crash", "rv.sat_unit", "rv.link_crash_unit",
    "canonical.crash", "canonical.unit", "dw.dim_source", "dw.dim_month",
    "dw.dim_severity", "dw.fact_crash", "qa.check_result",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def subset(value, names):
    return {name: value[name] for name in names if name in value}


class Evidence:
    def __init__(self, root):
        self.root = root.resolve()
        self.refs = {}

    def path(self, relative):
        path = (self.root / relative).resolve()
        require(path.is_relative_to(self.root) and path.is_file(), "Missing evidence file: " + relative)
        return path

    def record(self, relative):
        path = self.path(relative)
        value = {"path": relative, "sha256": digest(path), "bytes": path.stat().st_size}
        self.refs[relative] = value
        return value

    def read(self, relative):
        self.record(relative)
        return json.loads(self.path(relative).read_text(encoding="utf-8"))


def junit(evidence, relative):
    evidence.record(relative)
    root = ET.parse(evidence.path(relative)).getroot()
    modules = {}
    failures, skipped = [], []
    for case in root.iter("testcase"):
        module, name = case.attrib.get("classname", ""), case.attrib.get("name", "")
        require(module and name, "JUnit case is missing its identity")
        node = module + "::" + name
        result = "error" if case.find("error") is not None else (
            "failure" if case.find("failure") is not None else
            "skipped" if case.find("skipped") is not None else "passed")
        group = modules.setdefault(module, {"tests": 0, "passed": 0, "failures": 0,
                                           "errors": 0, "skipped": 0, "test_names": []})
        group["tests"] += 1
        group[{"error": "errors", "failure": "failures"}.get(result, result)] += 1
        group["test_names"].append(name)
        if result in {"failure", "error"}:
            failures.append(node)
        elif result == "skipped":
            skipped.append(node)
    totals = {key: sum(group[key] for group in modules.values())
              for key in ("tests", "passed", "failures", "errors", "skipped")}
    require(totals["tests"] > 0, "JUnit contains no executed test cases")
    require(not failures and not skipped, "JUnit contains failed, errored or skipped tests: " + relative)
    for group in modules.values():
        group["test_names"].sort()
    return {**totals, "modules": dict(sorted(modules.items())),
            "failed_test_names": failures, "skipped_test_names": skipped}


def database(evidence, prefix):
    summary = evidence.read(prefix + "/summary.json")
    cleanup = evidence.read(prefix + "/cleanup.json")
    state = evidence.read(prefix + "/final-state.json")
    tests = junit(evidence, prefix + "/pytest.xml")
    require(summary.get("exit_code") == 0 and summary.get("pytest_exit_code") == 0,
            "Database replay did not finish successfully: " + prefix)
    require(summary.get("final_tables_empty") is True, "Database replay left rows: " + prefix)
    for key in ("tests", "failures", "errors", "skipped"):
        require(summary.get(key) == tests[key], "Summary and JUnit differ: " + prefix + "/" + key)
    require(set(state.get("rows", {})) == TABLES and
            all(type(count) is int and count == 0 for count in state["rows"].values()),
            "Final table counts are missing or nonzero: " + prefix)
    require(state.get("advisory_locks", 0) == 0, "Advisory locks remain: " + prefix)
    require(bool(cleanup.get("container_removed")), "Container cleanup is unconfirmed: " + prefix)
    audited = summary.get("a03_audit_before_and_after") is True or (
        summary.get("permissions") == "Original A03 audit passed before and after")
    require(audited, "A03 audit success is not recorded: " + prefix)
    for name in ("a03-before.log", "a03-after.log"):
        ref = evidence.record(prefix + "/" + name)
        require(ref["bytes"] > 0, "A03 audit log is empty")
    return {"tests": tests, "summary": summary, "final_state": state, "cleanup": cleanup,
            "environment": evidence.read(prefix + "/environment.json")}


def run_summary(root, mode):
    evidence = Evidence(root)
    receipt = evidence.read("receipt.json")
    require(receipt.get("status") == "passed" and receipt.get("mode") == mode,
            "Replay is unfinished, failed or the wrong mode: " + str(root))
    require(receipt.get("started_at") and receipt.get("finished_at"), "Replay timestamps are incomplete")
    require(receipt.get("independent_member_signoff") is False and
            receipt.get("final_platform_accepted") is False, "Unexpected human/final acceptance claim")
    commands = receipt.get("commands", [])
    require(commands and all(command.get("exit_code") == 0 for command in commands),
            "Replay commands are incomplete or failed")
    db = database(evidence, "postgres")
    inputs = evidence.read("postgres/inputs.json")
    versions = receipt["versions"]
    require(inputs.get("integration_head") == versions["runtime_commit"], "Wrong tested runtime commit")
    require(inputs.get("installed_files"), "Installed package checks are missing")
    require(len(inputs.get("migrations", [])) == 11, "Expected all eleven migration records")
    acceptance = receipt.get("acceptance_files", [])
    require(acceptance, "Acceptance-file hashes are missing")
    for item in acceptance:
        path = evidence.path("runtime/" + item["runtime_path"])
        require(digest(path) == item["sha256"], "Copied acceptance file changed: " + item["path"])
    wheel = receipt["wheel"]
    wheel_path = evidence.path("wheel/" + wheel["filename"])
    require(digest(wheel_path) == wheel["sha256"], "Installed wheel archive changed")
    assets = evidence.read("installed-d09-assets.json")
    require(assets == receipt.get("installed_d09_assets"), "Installed-asset records differ")
    require({item["path"] for item in assets["assets"]} == {"templates/dashboard.html", "static/dashboard.css"},
            "D09 asset coverage is incomplete")
    installed = Path(assets["installed_module"]).resolve()
    require(installed.is_relative_to((evidence.root / "venv").resolve()), "D09 was not imported from the replay venv")
    for item in assets["assets"]:
        require(item.get("matches_pinned_source") is True, "D09 installed resource was not checked")
        source = evidence.path("runtime/src/arsia_d09/" + item["path"])
        target = installed.parent / item["path"]
        require(target.is_file() and digest(source) == digest(target) == item["sha256"],
                "D09 source or installed asset changed: " + item["path"])
    result = {
        "status": "passed", "output_directory": str(evidence.root),
        "started_at": receipt["started_at"], "finished_at": receipt["finished_at"],
        "tested_versions": versions, "e_commit": receipt["e_commit"],
        "e_working_tree_at_execution": receipt["e_working_tree"],
        "verifier_sha256": receipt["verifier_sha256"], "command_count": len(commands),
        "acceptance_files": acceptance, "wheel": {**wheel, "bytes": wheel_path.stat().st_size},
        "installed_d09_assets": assets, "installed_file_count": len(inputs["installed_files"]),
        "migrations": inputs["migrations"], "python": inputs["python"], "packages": inputs["packages"],
        "database": db,
    }
    if mode == "synthetic":
        cold = evidence.read("cold-start.json")
        require(cold.get("status") == "passed" and cold.get("cleanup", {}).get("container_removed"),
                "Cold-start success or cleanup is missing")
        require(cold["inputs"]["git_head"] == versions["a_environment_commit"], "Wrong A environment revision")
        require(cold["checks"]["catalog"].get("status") == "passed", "Cold-start catalog check failed")
        result["cold_start"] = {
            "status": cold["status"], "environment": cold["environment"],
            "catalog": subset(cold["checks"]["catalog"], ("status", "table_count", "field_count", "constraint_counts", "roles")),
            "checks": {key: subset(value, ("status", "rows", "all_zero"))
                       for key, value in cold["checks"].items() if key != "catalog" and isinstance(value, dict)},
            "cleanup": cold["cleanup"],
        }
        result["recovery_regression"] = database(evidence, "recovery")
        s0 = evidence.read("postgres/ac-evidence/e07/at02-07-s0.json")
        result["s0_observations"] = {"build": compact_result(s0["build"]), "layers": s0["layers"],
                                     "qa_objects_by_rule": dict(sorted(Counter(row[0] for row in s0["qa"]).items()))}
    else:
        result["official_observations"] = official_summary(evidence)
    result["evidence_files"] = list(evidence.refs.values())
    return result


def compact_result(value):
    return subset(value, ("result", "resolution", "run_id", "batch_id", "current_batch_id", "previous_batch_id",
                          "input_fingerprint", "stage", "observed_batch_status", "evidence_ref"))


def official_summary(evidence):
    base = "postgres/ac-evidence/e09-official/"
    data = {name: evidence.read(base + name + ".json") for name in (
        "full-build", "recovery-cost", "no-change", "expected-provenance", "source-metrics",
        "raw-qa", "dimensions-restrictions", "dashboard", "reader-timings", "intake",
    )}
    full, recovery, repeat = (data[name] for name in ("full-build", "recovery-cost", "no-change"))
    batch = full["result"]["batch_id"]
    require(full["result"]["result"] == "unknown_commit", "Official lost-acknowledgement case was not observed")
    require(recovery["result"]["resolution"] == "succeeded" and
            recovery["result"]["batch_id"] == recovery["result"]["current_batch_id"] == batch,
            "Official recovery did not confirm this successful release")
    require(repeat["result"]["result"] == "no_change" and repeat["result"]["batch_id"] == batch and
            repeat["batch_rows_unchanged"] is True, "Official repeat did not preserve the recovered batch")
    for record in (full, recovery, repeat):
        require(isinstance(record["elapsed_seconds"], (int, float)) and record["elapsed_seconds"] >= 0,
                "A measured elapsed time is missing")
        require(type(record["wal_bytes"]) is int and record["wal_bytes"] >= 0, "Measured WAL bytes are missing")
    qa = data["raw-qa"]
    raw = [{"resource_id": row[0], "sha256": row[1], "parser_version": row[2], "rows": row[3]} for row in qa["raw"]]
    metrics = data["source-metrics"]
    for source, actual in metrics["measured"].items():
        require(actual == {key: metrics["expected"]["sources"][source][key] for key in actual},
                "Official measured source values differ from their saved native expectations")
    prepared = data["intake"]["receipt"]
    require(prepared["status"] == "prepared" and prepared["raw_count"] == sum(row["rows"] for row in raw),
            "Intake and Raw counts disagree")
    costs = {}
    for name, value in (("full_build", full), ("recovery", recovery), ("no_change", repeat)):
        costs[name] = {**subset(value, (
            "elapsed_seconds", "wal_bytes", "database_growth_bytes", "before", "after",
            "python_peak_rss_bytes", "rss_scope", "timing_scope", "scope", "fault",
            "callback_timings", "commit_timings", "batch_rows_unchanged")), "result": compact_result(value["result"])}
    dashboard = data["dashboard"]
    reports = {source: {name: subset(report, ("status", "reason", "source_label"))
                       for name, report in entry["reports"].items()}
               for source, entry in dashboard["sources"].items()}
    evidence.record(base + "reader-results.json")
    evidence.record(base + "manifest.json")
    return {
        "batch_id": batch, "input_fingerprint": full["result"]["input_fingerprint"],
        "native_inputs": data["expected-provenance"]["native_files"],
        "native_expectations": subset(data["expected-provenance"], (
            "expectations_sha256", "evidence_refs", "native_source_year_counts", "basis")),
        "raw_resources": raw, "raw_total": sum(row["rows"] for row in raw),
        "sources": metrics["measured"], "qa_object_count": len(qa["qa"]),
        "qa_objects_by_rule": dict(sorted(Counter(row[0] for row in qa["qa"]).items())),
        "qa_results_by_rule": {rule: dict(Counter(row[2] for row in qa["qa"] if row[0] == rule))
                               for rule in sorted(qa["summary"])},
        "qa_summaries": qa["summary"], "dimensions_and_restrictions": data["dimensions-restrictions"],
        "reader_timings_seconds": data["reader-timings"], "dashboard_report_status": reports,
        "dashboard_checks": subset(dashboard, ("default_and_multiple_official_sources_rejected",
                                                "invalid_year_source_month_rejected", "reader_base_tables_denied")),
        "costs": costs,
        "scope": "Full pinned files; per-source/year crash counts, source metric totals and exact QA coverage. This does not independently verify every official severity category or known-count field.",
        "publication_scope": "Disposable private test database only; no shared/public release",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--synthetic", type=Path, required=True)
    parser.add_argument("--official", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new output file; existing results are not replaced")
    try:
        runs = {"synthetic": run_summary(args.synthetic, "synthetic"),
                "official": run_summary(args.official, "official")}
        for key in ("runtime_commit", "a_environment_commit", "a_schema_commit", "e_original_commit"):
            require(runs["synthetic"]["tested_versions"][key] == runs["official"]["tested_versions"][key],
                    "Synthetic and official runs use different versions: " + key)
        copies = [{row["path"]: row["sha256"] for row in run["acceptance_files"]} for run in runs.values()]
        require(all(copies[0][key] == copies[1][key] for key in copies[0].keys() & copies[1].keys()),
                "The two runs used different shared acceptance files")
        result = {
            "version": "e-acceptance-results-v1", "status": "passed",
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "execution_owner": "Role B / Peixian assisting Role E",
            "independent_member_signoff": False, "final_platform_accepted": False,
            "official_sample": {
                "status": "NOT_RUN",
                "reason": "The current VIC restricted contract checks a complete four-file Raw profile. An arbitrary subset is not a valid official build; the existing 308-row case covers C06 only.",
                "next": "E defines the sample experiment, B prepares parent-complete inputs and hashes, and C/E review its profile before a separate run. No new user-supplied data is needed.",
            },
            "runs": runs,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
        parser.exit(1, "Cannot summarize incomplete or inconsistent evidence: " + str(error) + "\n")
    print(json.dumps({"status": "passed", "output": str(args.output.resolve()),
                      "tests": {key: value["database"]["tests"]["tests"] for key, value in runs.items()}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
