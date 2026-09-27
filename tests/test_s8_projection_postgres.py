"""SA projection faults on private PG16 using B's real manifest and context.

Faults are inserted into test Raw deliberately. This isolates projection behavior;
the full AT15 tests also run B's input checks, publication and reader queries.
"""

from copy import deepcopy
from dataclasses import replace
import csv
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

if "AC_TEST_RUN" not in os.environ:
    pytest.skip("Use the isolated S8 PostgreSQL verifier", allow_module_level=True)

from arsia_c.projections.sa import project
from arsia_ingest.build import s8_request
from arsia_ingest.manifest import FrozenManifest
from arsia_ingest.pipeline import prepare
from arsia_ingest.raw_load import RawLoader
from arsia_ingest.runner import ModuleConnection, RunContext, RunEvidence
from test_c03_nsw_postgres import connection

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def frozen(tmp_path_factory):
    root = tmp_path_factory.mktemp("s8-projection-inputs")
    prepared = prepare(ROOT / "tests/fixtures/s8/config.json", root / "intake")
    request = s8_request(connect=lambda: None, project_root=ROOT,
                         prepared_run=prepared["run_dir"], evidence_root=root / "unused-build")
    assert type(request["manifest"]) is FrozenManifest
    return request["manifest"]


@pytest.fixture
def case(connection, frozen, tmp_path):
    class Case:
        def __init__(self):
            self.manifest = frozen.as_dict()
            self.calls = 0
            with (ROOT / "tests/fixtures/s8/syn_sa_crash.csv").open(encoding="utf-8-sig", newline="") as stream:
                self.payloads = list(csv.DictReader(stream))
            assert list(self.payloads[0]) == ["CRASH_ID", "YEAR", "MONTH", "SEVERITY",
                                              "FATALITIES", "CASUALTIES", "LATITUDE", "LONGITUDE"]

        def load(self, *, expected_count=None):
            selected = next(f for f in self.manifest["files"] if f["resource_id"] == "syn_sa_crash")
            selected["raw_count"] = len(self.payloads) if expected_count is None else expected_count
            contract = next(c for c in self.manifest["rules"]["contracts"] if c["id"] == "syn_sa_crash")
            contract["content"]["input"] = deepcopy(selected)
            snapshot = FrozenManifest(json.dumps(self.manifest))
            sources = [s for s in self.manifest["sources"] if s["source_id"] == "syn_sa"]
            RawLoader(connection, dataset_kind="synthetic", sources=sources, files=[selected]).register()
            self.ids = []
            for row, payload in enumerate(self.payloads, 2):
                raw_id = uuid4()
                self.ids.append(str(raw_id))
                connection.execute("INSERT INTO raw.record(raw_record_id,source_id,resource_id,file_sha256,parser_version,row_locator,payload) "
                    "VALUES (%s,'syn_sa','syn_sa_crash',%s,%s,%s,%s::jsonb)",
                    (raw_id, selected["file_sha256"], selected["parser_version"], f"csv:{row}", json.dumps(payload)))
            self.context = RunContext(str(uuid4()), "synthetic", str(uuid4()), "a" * 64, None,
                                      snapshot, RunEvidence(tmp_path / "evidence"))
            connection.execute("INSERT INTO meta.batch(batch_id,dataset_kind,input_fingerprint,manifest) "
                "VALUES (%s,'synthetic',%s,%s::jsonb)",
                (self.context.batch_id, self.context.input_fingerprint, json.dumps(snapshot.as_dict())))
            return self

        def run(self):
            self.calls += 1
            self.context = replace(self.context, evidence=RunEvidence(tmp_path / f"evidence-{self.calls}"))
            project(ModuleConnection(connection), self.context)

        def rows(self):
            return [r[0] for r in connection.execute("SELECT to_jsonb(t) FROM pg_temp.arsia_i_crash t ORDER BY crash_key")]

    return Case()


def test_exact_s8_projection_repeat_and_caller_rollback(case, connection):
    case.load().run()
    (row,) = case.rows()
    assert len(row) == 24
    assert row["crash_key"] == connection.execute("SELECT rv.encode_business_key('0001')").fetchone()[0]
    assert (row["occurrence_year"], row["occurrence_month"], row["occurrence_date"], row["date_precision"]) == (2020, 1, None, "month")
    assert (row["severity_raw"], row["severity_code"], row["severity_definition_version"], row["is_fatal_crash"]) == ("F", "F", "syn-1", True)
    assert (row["fatality_count"], row["casualty_count"]) == (1, 1)
    assert all(row[k] for k in ("fatal_crash_eligible", "fatality_eligible", "casualty_eligible", "map_eligible"))
    assert (row["latitude"], row["longitude"], row["location_crs"]) == (-34.92, 138.60, "EPSG:4326")
    assert row["raw_record_id"] == row["location_record_id"] == case.ids[0]
    assert row["quality_notes"] == {}
    assert connection.execute("SELECT count(*) FROM pg_temp.arsia_i_unit").fetchone() == (0,)
    case.run()
    assert case.rows() == [row]
    assert connection.info.transaction_status.name == "INTRANS"
    connection.rollback()
    assert connection.execute("SELECT count(*) FROM raw.record WHERE source_id='syn_sa'").fetchone() == (0,)
    assert connection.execute("SELECT count(*) FROM meta.batch WHERE batch_id=%s", (case.context.batch_id,)).fetchone() == (0,)


@pytest.mark.parametrize("field,value", [
    ("CRASH_ID", "   "), ("CRASH_ID", "\t\n"), ("CRASH_ID", ""), ("CRASH_ID", None),
    ("YEAR", "0000"), ("YEAR", "1899"), ("YEAR", "2101"),
    ("YEAR", "20x0"), ("YEAR", " 2020"), ("YEAR", None),
    ("MONTH", ""), ("MONTH", "0"), ("MONTH", "13"), ("MONTH", "January"), ("MONTH", "1.0"),
    ("SEVERITY", "NA"), ("SEVERITY", " F"), ("SEVERITY", "__MISSING__"),
    ("FATALITIES", "-1"), ("FATALITIES", "1.5"), ("FATALITIES", "2147483648"),
    ("CASUALTIES", "0"), ("CASUALTIES", "NaN"), ("CASUALTIES", " 1"), ("CASUALTIES", False),
])
def test_invalid_native_values_block(case, field, value):
    case.payloads[0][field] = value
    case.load()
    with pytest.raises(ValueError) as error:
        case.run()
    if value is False:
        assert str(error.value) == "S8 Raw native fields/types validation failed: (1,)"
    else:
        failures = [0] * 7
        index = {"CRASH_ID": 0, "YEAR": 2, "MONTH": 3, "SEVERITY": 4,
                 "FATALITIES": 5, "CASUALTIES": 5}[field]
        if field == "CASUALTIES" and value == "0":
            index = 6
        failures[index] = 1
        if field == "CRASH_ID" and value is None:
            failures[1] = 1
        assert str(error.value) == f"S8 keys/dates/categories/counts validation failed: {tuple(failures)}"


@pytest.mark.parametrize("field,value,metric", [
    ("SEVERITY", "", "fatal_crash_eligible"), ("SEVERITY", None, "fatal_crash_eligible"),
    ("FATALITIES", "", "fatality_eligible"), ("FATALITIES", None, "fatality_eligible"),
    ("CASUALTIES", "", "casualty_eligible"), ("CASUALTIES", None, "casualty_eligible"),
])
def test_native_missing_is_unknown_without_zero_inference(case, field, value, metric):
    case.payloads[0][field] = value
    case.load().run()
    (row,) = case.rows()
    assert row[metric] is False
    expected_field = {"SEVERITY": "is_fatal_crash", "FATALITIES": "fatality_count", "CASUALTIES": "casualty_count"}[field]
    assert row[expected_field] is None
    assert all(row[k] for k in {"fatal_crash_eligible", "fatality_eligible", "casualty_eligible"} - {metric})
    assert len(row["quality_notes"]["fields"]) == 1
    if field == "SEVERITY":
        assert row["severity_code"] == "__MISSING__"


@pytest.mark.parametrize("field,value,reason", [
    ("LATITUDE", "-90.00000001", "invalid_coordinate"), ("LONGITUDE", "180.00000001", "invalid_coordinate"),
    ("LATITUDE", "NaN", "invalid_coordinate"), ("LONGITUDE", "Infinity", "invalid_coordinate"),
    ("LATITUDE", "", "missing"), ("LONGITUDE", None, "missing"),
])
def test_invalid_or_missing_location_keeps_crash(case, field, value, reason):
    case.payloads[0][field] = value
    case.load().run()
    (row,) = case.rows()
    assert row["map_eligible"] is False
    assert all(row[k] is None for k in ("latitude", "longitude", "location_crs", "location_record_id"))
    assert row["fatality_count"] == row["casualty_count"] == 1
    assert row["quality_notes"]["location"]["reason_code"] == reason


def test_unconfirmed_crs_keeps_location_out_of_projection(case):
    mapping = next(m for m in case.manifest["rules"]["mappings"] if m["id"] == "syn_sa_crash_mapping")
    mapping["content"]["location"]["crs"] = None
    case.load().run()
    (row,) = case.rows()
    assert row["map_eligible"] is False and row["latitude"] is None
    assert row["quality_notes"]["location"]["reason_code"] == "crs_unconfirmed"


def test_duplicate_key_outside_analysis_still_blocks(case):
    case.payloads[0]["YEAR"] = "2019"
    case.payloads.append(deepcopy(case.payloads[0]))
    case.load()
    with pytest.raises(ValueError) as error:
        case.run()
    assert str(error.value) == "S8 keys/dates/categories/counts validation failed: (0, 1, 0, 0, 0, 0, 0)"


@pytest.mark.parametrize("year", ["1900", "2019", "2100"])
def test_valid_outside_analysis_is_excluded_without_inventing_units(case, connection, year):
    case.payloads[0]["YEAR"] = year
    case.load().run()
    assert case.rows() == []
    assert connection.execute("SELECT count(*) FROM pg_temp.arsia_i_unit").fetchone() == (0,)


def test_incomplete_selected_raw_blocks(case):
    case.load(expected_count=2)
    with pytest.raises(ValueError, match="Incomplete selected S8 Raw"):
        case.run()


def test_declared_empty_snapshot_emits_no_crash_or_unit_rows(case, connection):
    case.payloads.clear()
    case.load().run()
    assert case.rows() == []
    assert connection.execute("SELECT count(*) FROM pg_temp.arsia_i_unit").fetchone() == (0,)


def test_total_casualties_is_not_added_to_fatalities(case):
    case.payloads[0]["FATALITIES"] = case.payloads[0]["CASUALTIES"] = "2147483647"
    case.load().run()
    (row,) = case.rows()
    assert row["fatality_count"] == row["casualty_count"] == 2147483647
