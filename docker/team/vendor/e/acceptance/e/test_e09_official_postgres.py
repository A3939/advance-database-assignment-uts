"""E09 full official run, source-scoped reader checks and measured recovery."""
from dataclasses import replace
from importlib.resources import files
import json
import os
from pathlib import Path
import resource
import sys
import time
from uuid import UUID

import pytest

if not {"AC_TEST_RUN", "ARSIA_OFFICIAL_NATIVE_ROOT", "ARSIA_OFFICIAL_PREPARED_RUN"} <= os.environ.keys():
    pytest.skip("Use the E acceptance verifier with pinned official inputs", allow_module_level=True)

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from arsia_d05 import install_sql as trend_sql
from arsia_d06 import install_sql as severity_sql
from arsia_d07 import install_sql as map_sql
from arsia_d08 import install_sql as units_sql
from arsia_d09 import DashboardFilters, load_dashboard
from arsia_d09.web import render_page
from arsia_ingest.build import fp1_sql, official_request
from arsia_ingest.manifest import FrozenManifest
from arsia_ingest.models import IntakeError
from arsia_ingest.official_reader import query_official
from arsia_ingest.recovery import recover_run
from arsia_ingest.runner import ModuleConnection, run_build
from e_official_expected import QA_RULES, expected_qa_objects, load_expectations


ROOT = Path(__file__).resolve().parents[1]
TABLES = ("meta.source", "meta.resource", "meta.batch", "meta.current_release", "raw.record",
          "rv.hub_crash", "rv.hub_unit", "rv.sat_crash", "rv.sat_unit", "rv.link_crash_unit",
          "canonical.crash", "canonical.unit", "dw.dim_source", "dw.dim_month",
          "dw.dim_severity", "dw.fact_crash", "qa.check_result")
BATCH_TABLES = ("rv.sat_crash", "rv.sat_unit", "rv.link_crash_unit", "canonical.crash",
                "canonical.unit", "dw.dim_source", "dw.dim_severity", "dw.fact_crash", "qa.check_result")


def connect():
    return psycopg.connect(os.environ["ARSIA_TEST_DSN"])


def write(root, name, value):
    (root / name).write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")


def measurements():
    with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as owner:
        wal, size = owner.execute("SELECT pg_current_wal_lsn()::text,pg_database_size(current_database())").fetchone()
    return {"wal_lsn": wal, "database_bytes": size}


def wal_bytes(first, last):
    with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as owner:
        return int(owner.execute("SELECT pg_wal_lsn_diff(%s::pg_lsn,%s::pg_lsn)",
                                 (last["wal_lsn"], first["wal_lsn"])).fetchone()[0])


def batch_counts(batch):
    with connect() as connection:
        return {table: connection.execute(f"SELECT count(*) FROM {table} WHERE batch_id=%s", (batch,)).fetchone()[0]
                for table in BATCH_TABLES}


@pytest.fixture(scope="module")
def official():
    root = Path(os.environ["AC_EVIDENCE_DIR"]) / "e09-official"
    root.mkdir(parents=True)
    options = conninfo_to_dict(os.environ["ARSIA_TEST_DSN"])
    options["user"] = "arsia_reader"
    with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as owner:
        assert owner.execute("SELECT current_setting('arsia.test_run')").fetchone() == (os.environ["AC_TEST_RUN"],)
        assert all(owner.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,) for table in TABLES)
        owner.execute(fp1_sql())
        owner.execute("SET LOCAL ROLE arsia_migrator")
        for install in (trend_sql, severity_sql, map_sql, units_sql):
            owner.execute(install())
        owner.execute(files("arsia_d09").joinpath("sql/d09_context.sql").read_text(encoding="utf-8"))
        owner.execute("RESET ROLE")
        owner.execute(sql.SQL("ALTER ROLE arsia_reader PASSWORD {}").format(sql.Literal(options["password"])))
    try:
        prepared_run = Path(os.environ["ARSIA_OFFICIAL_PREPARED_RUN"]).resolve()
        prepared = json.loads((prepared_run / "run.json").read_text(encoding="utf-8"))
        assert (prepared["status"], prepared["dataset_kind"], prepared["raw_count"]) == ("prepared", "official", 2118028)
        assert len(prepared["files"]) == 7
        request = official_request(connect=connect, project_root=ROOT, prepared_run=prepared_run,
                                   evidence_root=root / "builds")
        assert type(request["manifest"]) is FrozenManifest
        value = request["manifest"].as_dict()
        assert value["analysis"] == {"year_from": 2020, "year_to": 2024}
        expected, provenance = load_expectations(ROOT, os.environ["ARSIA_OFFICIAL_NATIVE_ROOT"], value)
        write(root, "expected-provenance.json", provenance)
        write(root, "manifest.json", value)
        write(root, "intake.json", {"prepared_run": str(prepared_run), "receipt": prepared,
                                   "scope": "Complete seven-file intake; the runner rechecks file and row identities"})
        stages, commits = [], []
        modules = request["modules"]
        for stage in ("project", "vault", "canonical", "dw", "qa_c", "qa_d", "publish"):
            binding = getattr(modules, stage)
            def timed(connection, context, *, stage=stage, callback=binding.callback):
                started = time.perf_counter()
                try:
                    return callback(connection, context)
                finally:
                    stages.append({"stage": stage, "elapsed_seconds": round(time.perf_counter() - started, 3)})
                    write(root, "callback-timings.json", stages)
            modules = replace(modules, **{stage: replace(binding, callback=timed)})

        class LostPublicationReply:
            """The server commits; only the client's acknowledgement is lost."""
            def __init__(self):
                self.connection = connect()
                self.commits = 0
            def __getattr__(self, name):
                return getattr(self.connection, name)
            def commit(self):
                self.commits += 1
                started = time.perf_counter()
                self.connection.commit()
                commits.append({"number": self.commits, "elapsed_seconds": round(time.perf_counter() - started, 3),
                                "seconds_since_build_start": round(time.perf_counter() - build_started, 3)})
                write(root, "commit-timings.json", commits)
                if self.commits == 2:
                    raise ConnectionError("E09 injected loss of publication acknowledgement")

        before = measurements()
        build_started = time.perf_counter()
        result = run_build(**{**request, "connect": LostPublicationReply, "modules": modules}).as_dict()
        elapsed = round(time.perf_counter() - build_started, 3)
        after = measurements()
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        write(root, "full-build.json", {"result": result, "elapsed_seconds": elapsed,
            "before": before, "after": after, "wal_bytes": wal_bytes(before, after),
            "database_growth_bytes": after["database_bytes"] - before["database_bytes"],
            "python_peak_rss_bytes": peak if sys.platform == "darwin" else peak * 1024,
            "rss_scope": "Whole pytest process, not the PostgreSQL server; includes pre-build hashing",
            "callback_timings": stages, "commit_timings": commits,
            "timing_scope": "Full B10 including intake validation, Raw registration, all callbacks, QA and publication",
            "publication_scope": "Private PostgreSQL database only",
            "fault": "One real full build; response lost after the real publication commit"})
        assert result["result"] == "unknown_commit", result
        assert len(commits) == 2
        assert [row["stage"] for row in stages] == ["project", "vault", "canonical", "dw", "qa_c", "qa_d", "publish"]
        batch = result["batch_id"]
        before_counts = batch_counts(batch)
        recovery_before = measurements()
        started = time.perf_counter()
        recovered = recover_run(connect=connect, run_dir=result["evidence_ref"], evidence_root=root / "recovery").as_dict()
        recovery_elapsed = round(time.perf_counter() - started, 3)
        recovery_after = measurements()
        write(root, "recovery-cost.json", {"result": recovered, "elapsed_seconds": recovery_elapsed,
            "before": recovery_before, "after": recovery_after,
            "wal_bytes": wal_bytes(recovery_before, recovery_after),
            "scope": "Resolve committed full-snapshot state; no rebuild and no release-pointer change"})
        assert recovered["resolution"] == "succeeded", recovered
        assert recovered["batch_id"] == recovered["current_batch_id"] == batch
        assert batch_counts(batch) == before_counts
        with connect() as connection:
            assert connection.execute("SELECT dataset_kind,status FROM meta.batch WHERE batch_id=%s", (batch,)).fetchone() == ("official", "succeeded")
            assert connection.execute("SELECT dataset_kind,batch_id FROM meta.current_release").fetchall() == [("official", UUID(batch))]
        yield {"root": root, "request": request, "manifest": value, "expected": expected,
               "batch": batch, "counts": before_counts, "reader_dsn": make_conninfo(**options),
               "result": result, "recovery": recovered}
    finally:
        with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as owner:
            assert owner.execute("SELECT current_setting('arsia.test_run')").fetchone() == (os.environ["AC_TEST_RUN"],)
            owner.execute("TRUNCATE " + ",".join(TABLES))


def test_full_input_raw_and_qa_groups(official):
    batch = official["batch"]
    with connect() as connection:
        assert connection.execute("SELECT current_user,session_user").fetchone() == ("arsia_loader", "arsia_loader")
        raw = connection.execute("SELECT resource_id,file_sha256,parser_version,count(*) FROM raw.record GROUP BY 1,2,3 ORDER BY 1").fetchall()
        expected = {row["resource_id"]: (row["file_sha256"], row["parser_version"], row["raw_count"])
                    for row in official["manifest"]["files"]}
        assert {row[0]: row[1:] for row in raw} == expected
        assert sum(row[3] for row in raw) == 2118028
        qa = connection.execute("SELECT rule_id,object_key,result,affected_count,evidence FROM qa.check_result WHERE batch_id=%s ORDER BY 1,2", (batch,)).fetchall()
    summary = {row[0]: row[2] for row in qa if row[1] == "batch"}
    assert set(summary) == set(QA_RULES)
    assert all(result == ("limited" if rule == "QA07_LOCATION" else "pass") for rule, result in summary.items())
    assert all(row[2] in {"pass", "limited"} and row[4] for row in qa)
    assert len(qa) == 63
    assert {(row[0], row[1]): (row[2], row[3]) for row in qa} == expected_qa_objects(official["manifest"], official["expected"])
    write(official["root"], "raw-qa.json", {"raw": raw, "qa": qa, "summary": summary})


def test_source_metrics_match_saved_native_observations(official):
    measured = {}
    with connect() as connection:
        expected_years = [(row["source_id"], row["year"], row["crash_count"])
                          for row in official["expected"]["native_source_year_counts"]]
        for table in ("canonical.crash", "dw.fact_crash"):
            actual_years = connection.execute(f"SELECT source_id,occurrence_year,count(*) FROM {table} WHERE batch_id=%s GROUP BY 1,2 ORDER BY 1,2",
                                               (official["batch"],)).fetchall()
            assert actual_years == expected_years
        for source, expected in official["expected"]["sources"].items():
            row = connection.execute("""SELECT count(*),count(*) FILTER (WHERE fatal_crash_eligible AND is_fatal_crash),
                sum(fatality_count) FILTER (WHERE fatality_eligible),sum(casualty_count) FILTER (WHERE casualty_eligible),
                count(*) FILTER (WHERE map_eligible),count(*) FILTER (WHERE NOT map_eligible)
                FROM dw.fact_crash WHERE batch_id=%s AND source_id=%s""", (official["batch"], source)).fetchone()
            actual = dict(zip(("crash_count", "fatal_crash_count", "fatality_count", "casualty_count", "map_count", "unmapped_count"), row))
            units = connection.execute("SELECT count(*),count(*) FILTER (WHERE count_eligible) FROM canonical.unit WHERE batch_id=%s AND source_id=%s",
                                       (official["batch"], source)).fetchone()
            actual.update(canonical_unit_count=units[0], report_eligible_unit_count=units[1])
            assert actual == {key: expected[key] for key in actual}
            measured[source] = actual
    write(official["root"], "source-metrics.json", {"measured": measured, "expected": official["expected"],
          "boundary": "Sources compared separately; unavailable maps and audit-only VIC units retain their restrictions"})


def test_dimensions_and_vic_restrictions(official):
    batch, value = official["batch"], official["manifest"]
    with connect() as connection:
        for table, entries, columns in (
            ("dw.dim_source", value["sources"], ("source_id", "source_name", "jurisdiction_code", "release_label", "release_scope")),
            ("dw.dim_severity", value["rules"]["severity"], ("source_id", "severity_code", "severity_label", "definition_version", "definition_text")),
        ):
            actual = connection.execute(f"SELECT {','.join(columns)} FROM {table} WHERE batch_id=%s", (batch,)).fetchall()
            assert sorted(actual) == sorted(tuple(row[key] for key in columns) for row in entries)
        assert connection.execute("SELECT * FROM dw.dim_month ORDER BY month_id").fetchall() == [(year * 100 + month, year, month) for year in range(2020, 2025) for month in range(1, 13)]
        assert connection.execute("SELECT count(*) FROM dw.dim_severity WHERE batch_id=%s AND severity_code='__MISSING__'", (batch,)).fetchone() == (3,)
        assert connection.execute("""SELECT count(*) FROM canonical.crash WHERE batch_id=%s AND source_id='official_vic'
            AND (map_eligible OR latitude IS NOT NULL OR longitude IS NOT NULL OR location_crs IS NOT NULL OR location_record_id IS NOT NULL)""", (batch,)).fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM canonical.unit WHERE batch_id=%s AND source_id='official_vic' AND count_eligible", (batch,)).fetchone() == (0,)
    write(official["root"], "dimensions-restrictions.json", {"sources": len(value["sources"]), "months": 60,
          "severity_definitions": len(value["rules"]["severity"]), "missing_categories": 3, "vic_map_and_unit_limits_retained": True})


def test_real_reader_queries_and_permissions(official):
    outputs, timings = {}, {}
    with psycopg.connect(official["reader_dsn"]) as reader:
        assert reader.execute("SELECT current_user").fetchone() == ("arsia_reader",)
        shared = ModuleConnection(reader)
        for source, expected in official["expected"]["sources"].items():
            for report in ("trend", "severity", "map", "units"):
                started = time.perf_counter()
                result = query_official(shared, batch_id=official["batch"], source_id=source, report=report)
                key = source + ":" + report
                outputs[key], timings[key] = result, round(time.perf_counter() - started, 3)
                assert result["source_label"] and result["quality_limits"] and result["coverage_basis"]
                unavailable = report == "map" or (report == "units" and source != "official_nsw")
                if unavailable:
                    assert result["status"] == "unavailable" and result["reason"] and result["rows"] is None
                else:
                    assert result["status"] == "available"
                    assert all(row["source_id"] == source for row in result["rows"])
                    field, metric = ("unit_count", "report_eligible_unit_count") if report == "units" else ("crash_count", "crash_count")
                    assert sum(row[field] or 0 for row in result["rows"]) == expected[metric]
            monthly = query_official(shared, batch_id=official["batch"], source_id=source, report="trend", grain="month")
            assert monthly["status"] == "available" and len(monthly["rows"]) == 60
            assert sum(row["crash_count"] or 0 for row in monthly["rows"]) == expected["crash_count"]
            outputs[source + ":monthly"] = monthly
        for forbidden in ("SELECT payload FROM raw.record LIMIT 1", "SELECT manifest FROM meta.batch LIMIT 1"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                reader.execute(forbidden)
            reader.rollback()
    write(official["root"], "reader-results.json", outputs)
    write(official["root"], "reader-timings.json", timings)


def test_d09_uses_full_official_batch_and_rejects_invalid_filters(official):
    outputs = {}
    with psycopg.connect(official["reader_dsn"]) as reader:
        shared = ModuleConnection(reader)
        for source, expected in official["expected"]["sources"].items():
            page = load_dashboard(shared, DashboardFilters("official", source_ids=(source,)))
            assert str(page.release.batch_id) == official["batch"]
            assert sum(row["crash_count"] or 0 for row in page.trend) == expected["crash_count"]
            html = render_page(page.filters, page)
            assert "Map coverage</span><strong>Unavailable</strong>" in html
            assert "Map points</span><strong>Unavailable</strong>" in html
            assert page.official_reports["map"]["reason"] in html
            if source != "official_nsw":
                assert "Eligible units</span><strong>Unavailable</strong>" in html
                assert page.official_reports["units"]["reason"] in html
            else:
                assert f"Eligible units</span><strong>{expected['report_eligible_unit_count']}</strong>" in html
            (official["root"] / f"dashboard-{source}.html").write_text(html, encoding="utf-8")
            outputs[source] = {"crash_count": expected["crash_count"], "reports": page.official_reports}
        for sources in (None, ("official_nsw", "official_vic")):
            with pytest.raises(IntakeError) as error:
                load_dashboard(shared, DashboardFilters("official", source_ids=sources))
            assert error.value.code == "D09_OFFICIAL_SOURCE"
        for bounds in ({"year_from": 2019}, {"year_to": 2025}):
            with pytest.raises(IntakeError) as error:
                load_dashboard(shared, DashboardFilters("official", source_ids=("official_nsw",), **bounds))
            assert error.value.code == "D09_YEAR_RANGE"
        with pytest.raises(IntakeError) as error:
            load_dashboard(shared, DashboardFilters("official", source_ids=("not_in_manifest",)))
        assert error.value.code == "OFFICIAL_READER"
        reader.rollback()
        with pytest.raises(IntakeError) as error:
            load_dashboard(shared, DashboardFilters("official", source_ids=("official_nsw",), months=(13,)))
        assert error.value.code == "D05_ARGUMENT"
        reader.rollback()
    write(official["root"], "dashboard.json", {"batch_id": official["batch"], "sources": outputs,
          "default_and_multiple_official_sources_rejected": True,
          "invalid_year_source_month_rejected": True, "reader_base_tables_denied": True})


def test_retry_after_recovery_is_no_change(official):
    before = measurements()
    started = time.perf_counter()
    result = run_build(**official["request"]).as_dict()
    elapsed = round(time.perf_counter() - started, 3)
    after = measurements()
    assert result["result"] == "no_change" and result["batch_id"] == official["batch"]
    assert result["input_fingerprint"] == official["result"]["input_fingerprint"]
    assert batch_counts(official["batch"]) == official["counts"]
    with connect() as connection:
        assert connection.execute("SELECT count(*) FROM meta.batch").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM raw.record").fetchone() == (2118028,)
    write(official["root"], "no-change.json", {"result": result, "elapsed_seconds": elapsed,
          "wal_bytes": wal_bytes(before, after), "before": before, "after": after,
          "batch_rows_unchanged": True})
