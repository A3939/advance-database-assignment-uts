"""C06 checks on PostgreSQL 16. All test rows are synthetic and rolled back."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = ROOT if (ROOT / "src/arsia_ingest").is_dir() else ROOT.parent / "Workspace/Workspace_Github"
REPOSITORY = Path(os.environ.get("ARSIA_REPOSITORY", DEFAULT_REPO))
SQL_PATH = ROOT / "sql/qa/c06_vic_person_checks.sql"
pytestmark = pytest.mark.skipif(
    "ARSIA_TEST_DSN" not in os.environ,
    reason="Set ARSIA_TEST_DSN to A's migrated PostgreSQL 16 test database",
)


@pytest.fixture
def connection():
    dsn = os.environ.get("ARSIA_TEST_DSN")
    if not dsn:
        pytest.fail("ARSIA_TEST_DSN is set but empty", pytrace=False)
    try:
        import psycopg
    except ImportError:
        pytest.fail("ARSIA_TEST_DSN is set but psycopg is unavailable", pytrace=False)
    try:
        conn = psycopg.connect(dsn, autocommit=False, connect_timeout=10)
    except psycopg.Error as exc:
        pytest.fail(f"Test database connection failed ({type(exc).__name__})", pytrace=False)
    try:
        assert conn.info.server_version // 10000 == 16
        for table in ("meta.source", "meta.resource", "raw.record"):
            assert conn.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0], table
            assert conn.execute(
                "SELECT has_table_privilege(current_user, %s, 'SELECT'), "
                "has_table_privilege(current_user, %s, 'INSERT')", (table, table),
            ).fetchone() == (True, True)
        conn.rollback()
        yield conn
    finally:
        conn.rollback()
        conn.close()


class RawCase:
    def __init__(self, conn):
        self.connection = conn
        self.source_id = f"syn_c06_{uuid4().hex}"
        self.files = {}
        conn.execute(
            "INSERT INTO meta.source (source_id, jurisdiction_code, source_name, publisher) "
            "VALUES (%s, 'VIC', 'C06 test', 'ARSIA synthetic')", (self.source_id,))
        for role, entity in (("accident", "crash"), ("vehicle", "unit"),
                             ("person", "person_raw")):
            resource_id = f"{self.source_id}_{role}"
            conn.execute(
                "INSERT INTO meta.resource (resource_id, source_id, resource_role, entity_kind) "
                "VALUES (%s, %s, %s, %s)", (resource_id, self.source_id, role, entity))
            self.files[role] = {
                "role": role, "source_id": self.source_id, "resource_id": resource_id,
                "file_sha256": "a" * 64, "parser_version": "csv-native-v1", "raw_count": 0,
            }
        self.rows = {role: [] for role in self.files}

    def add(self, role, payload, **identity):
        selected = self.files[role]
        row_id = uuid4()
        locator = f"csv:{len(self.rows[role]) + 1}"
        digest = identity.get("file_sha256", selected["file_sha256"])
        parser = identity.get("parser_version", selected["parser_version"])
        self.connection.execute(
            "INSERT INTO raw.record (raw_record_id, resource_id, source_id, file_sha256, "
            "parser_version, row_locator, payload) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)",
            (row_id, selected["resource_id"], self.source_id, digest, parser, locator,
             json.dumps(payload)),
        )
        if (digest, parser) == (selected["file_sha256"], selected["parser_version"]):
            selected["raw_count"] += 1
        self.rows[role].append({"raw_record_id": str(row_id), "row_locator": locator,
                                "payload": deepcopy(payload)})
        return str(row_id)

    def accident(self, key="0001", count="1", date="2020-01-15"):
        return self.add("accident", {"ACCIDENT_NO": key, "ACCIDENT_DATE": date,
                                      "NO_PERSONS": count})

    def vehicle(self, accident="0001", key="01"):
        return self.add("vehicle", {"ACCIDENT_NO": accident, "VEHICLE_ID": key})

    def person(self, accident="0001", key="P1", vehicle="01"):
        return self.add("person", {"ACCIDENT_NO": accident, "PERSON_ID": key,
                                   "VEHICLE_ID": vehicle, "ROAD_USER_TYPE": "1"})

    def run(self, **rules):
        params = {
            "files": list(self.files.values()), "analysis": {"year_from": 2020, "year_to": 2024},
            "blank_vehicle_allowed": True, "count_scope_confirmed": True,
        }
        params.update(rules)
        return [row[0] for row in self.connection.execute(
            SQL_PATH.read_text(encoding="utf-8"), (json.dumps(params),)).fetchall()]


@pytest.fixture
def case(connection):
    return RawCase(connection)


def reports(result, kind):
    return [row for row in result if row["kind"] == kind]


def issue_set(result, kind=None):
    rows = result if kind is None else reports(result, kind)
    return {issue for row in rows for issue in row["issues"]}


def test_complete_case_has_row_evidence_and_no_issues(case):
    case.accident()
    case.vehicle()
    person_id = case.person()
    result = case.run()
    assert not issue_set(result)
    assert {kind: len(reports(result, kind)) for kind in
            ("file", "accident", "vehicle", "person")} == {
                "file": 3, "accident": 1, "vehicle": 1, "person": 1}
    person = reports(result, "person")[0]
    assert (person["raw_record_id"], person["source_id"], person["row_locator"]) == (
        person_id, case.source_id, "csv:1")
    assert person["file_sha256"] == case.files["person"]["file_sha256"]
    accident = reports(result, "accident")[0]
    assert (accident["declared_count"], accident["observed_count"], accident["count_delta"],
            accident["count_state"], accident["in_scope"]) == (1, 1, 0, "compared", True)


@pytest.mark.parametrize("key", [None, "", " ", "\t", "\n", "\u00a0", 1, False, [], {}])
def test_person_key_must_be_present_native_text(case, key):
    case.accident()
    case.vehicle()
    case.person(key=key)
    person = reports(case.run(), "person")[0]
    assert "invalid_person_key" in person["issues"]
    assert person["person_id"] == key


@pytest.mark.parametrize("key", [None, "", " ", "\t", "\u00a0"])
def test_person_accident_key_cannot_be_blank(case, key):
    case.accident(count="0")
    case.person(accident=key, vehicle="")
    assert "invalid_accident_key" in issue_set(case.run(), "person")


@pytest.mark.parametrize("accident,vehicle,person", [
    ("0001", "01", "00001"), ("A", "V", "p"), (" A ", " V ", " P "),
])
def test_valid_keys_keep_case_zeros_and_original_whitespace(case, accident, vehicle, person):
    case.accident(key=accident)
    case.vehicle(accident=accident, key=vehicle)
    case.person(accident=accident, key=person, vehicle=vehicle)
    result = case.run()
    assert not issue_set(result)
    row = reports(result, "person")[0]
    assert (row["accident_no"], row["vehicle_id"], row["person_id"]) == (
        accident, vehicle, person)


@pytest.mark.parametrize("parent,child", [("0001", "1"), ("A", "a"), ("A", " A ")])
def test_parent_matching_does_not_normalize_keys(case, parent, child):
    case.accident(key=parent, count="0")
    case.vehicle(accident=parent)
    case.person(accident=child)
    assert "missing_accident_parent" in issue_set(case.run(), "person")


def test_duplicate_person_key_reports_both_native_rows(case):
    case.accident(count="2")
    case.vehicle()
    ids = {case.person(), case.person()}
    result = case.run()
    duplicate_rows = [row for row in reports(result, "person")
                      if "duplicate_person_key" in row["issues"]]
    assert {row["raw_record_id"] for row in duplicate_rows} == ids
    assert reports(result, "accident")[0]["observed_count"] == 2


def test_duplicate_accident_parent_does_not_multiply_person_count(case):
    case.accident()
    case.accident()
    case.vehicle()
    case.person()
    result = case.run()
    assert len(reports(result, "person")) == 1
    assert "ambiguous_accident_parent" in issue_set(result, "person")
    for accident in reports(result, "accident"):
        assert "duplicate_accident_key" in accident["issues"]
        assert accident["observed_count"] == 1
        assert accident["count_delta"] is None


def test_duplicate_vehicle_parent_does_not_multiply_person_rows(case):
    case.accident()
    case.vehicle()
    case.vehicle()
    case.person()
    result = case.run()
    assert len(reports(result, "person")) == 1
    assert "duplicate_vehicle_key" in issue_set(result, "vehicle")
    assert "ambiguous_vehicle_reference" in issue_set(result, "person")


def test_vehicle_id_from_another_accident_cannot_match(case):
    case.accident()
    case.accident(key="0002", count="0")
    case.vehicle(accident="0002")
    case.person()
    assert "unmatched_nonblank_vehicle_ref" in issue_set(case.run(), "person")


def test_parent_keys_from_another_source_cannot_match(case):
    other = RawCase(case.connection)
    other.accident()
    other.vehicle()
    case.person()
    issues = issue_set(case.run(), "person")
    assert {"missing_accident_parent", "unmatched_nonblank_vehicle_ref"} <= issues


@pytest.mark.parametrize("vehicle", [None, ""])
@pytest.mark.parametrize("allowed,issue", [
    (True, None), (False, "blank_vehicle_reference_forbidden"),
    (None, "blank_vehicle_reference_unconfirmed"),
])
def test_blank_vehicle_rules_are_explicit(case, vehicle, allowed, issue):
    case.accident()
    case.person(vehicle=vehicle)
    result = case.run(blank_vehicle_allowed=allowed)
    row = reports(result, "person")[0]
    assert row["vehicle_id"] == vehicle
    if issue is None:
        assert not row["issues"]
    else:
        assert issue in row["issues"]


@pytest.mark.parametrize("vehicle", [" ", "\t", "\u00a0", 1, False])
def test_whitespace_or_nontext_vehicle_reference_is_not_legal_blank(case, vehicle):
    case.accident()
    case.person(vehicle=vehicle)
    row = reports(case.run(blank_vehicle_allowed=True), "person")[0]
    assert "invalid_vehicle_reference" in row["issues"]
    assert row["vehicle_id"] == vehicle


@pytest.mark.parametrize("field,value", [("file_sha256", "b" * 64),
                                         ("parser_version", "csv-native-v2")])
def test_only_the_selected_file_and_parser_are_checked(case, field, value):
    case.accident()
    case.vehicle()
    old_id = case.person()
    case.files["person"][field] = value
    case.files["person"]["raw_count"] = 0
    new_id = case.person(vehicle="MISSING")
    result = case.run()
    assert {row["raw_record_id"] for row in reports(result, "person")} == {new_id}
    assert old_id != new_id
    assert "unmatched_nonblank_vehicle_ref" in issue_set(result, "person")
    assert "selected_raw_count_mismatch" not in issue_set(result, "file")


def test_unselected_bad_history_is_not_checked(case):
    case.accident()
    case.vehicle()
    selected_id = case.person()
    case.add("person", {"ACCIDENT_NO": "BAD", "PERSON_ID": "", "VEHICLE_ID": "BAD"},
             file_sha256="b" * 64)
    result = case.run()
    assert not issue_set(result)
    assert {row["raw_record_id"] for row in reports(result, "person")} == {selected_id}


@pytest.mark.parametrize("role", ["accident", "vehicle", "person"])
def test_missing_selected_file_cannot_look_like_zero_violations(case, role):
    case.files[role]["raw_count"] = 1
    result = case.run()
    mismatches = [row for row in reports(result, "file")
                  if "selected_raw_count_mismatch" in row["issues"]]
    assert len(mismatches) == 1
    assert mismatches[0]["resource_id"] == case.files[role]["resource_id"]


@pytest.mark.parametrize("date", ["today", "01/02/2020", "2020-02-30", "2021-02-29",
                                  "2020-1-01", "", None, 20200101])
def test_invalid_dates_are_found_even_when_person_counts_match(case, date):
    case.accident(date=date)
    case.vehicle()
    case.person()
    accident = reports(case.run(), "accident")[0]
    assert "invalid_accident_date" in accident["issues"]
    assert accident["date_text"] == date
    assert accident["in_scope"] is None


def test_iso_date_results_do_not_depend_on_datestyle(case):
    case.accident(date="2020-02-01")
    case.vehicle()
    case.person()
    case.connection.execute("SET LOCAL DateStyle = 'ISO, DMY'")
    dmy = case.run()
    case.connection.execute("SET LOCAL DateStyle = 'ISO, MDY'")
    assert case.run() == dmy
    assert not issue_set(dmy)


@pytest.mark.parametrize("count", ["-1", "1.0", "1e1", "2147483648", "NaN", 1, False])
def test_invalid_person_count_is_reported_without_failing_the_query(case, count):
    case.accident(count=count)
    case.vehicle()
    case.person()
    row = reports(case.run(), "accident")[0]
    assert "invalid_person_count" in row["issues"]
    assert row["count_state"] == "invalid"
    assert row["count_text"] == count
    assert row["count_delta"] is None


@pytest.mark.parametrize("count", [None, ""])
def test_missing_person_count_remains_unknown(case, count):
    case.accident(count=count)
    row = reports(case.run(), "accident")[0]
    assert not row["issues"]
    assert row["count_state"] == "missing"
    assert row["declared_count"] is None
    assert row["count_delta"] is None


def test_unconfirmed_count_scope_is_not_compared_as_if_approved(case):
    case.accident(count="2")
    case.vehicle()
    case.person()
    row = reports(case.run(count_scope_confirmed=False), "accident")[0]
    assert "person_count_scope_unconfirmed" in row["issues"]
    assert "person_count_mismatch" not in row["issues"]
    assert row["count_state"] == "unconfirmed"
    assert row["count_delta"] is None


def test_opposite_count_deltas_remain_two_separate_violations(case):
    case.accident(key="A", count="0")
    case.accident(key="B", count="2")
    case.person(accident="A", vehicle="")
    case.person(accident="B", vehicle="")
    rows = reports(case.run(), "accident")
    assert {row["count_delta"] for row in rows} == {-1, 1}
    assert all("person_count_mismatch" in row["issues"] for row in rows)


def test_out_of_scope_parent_is_resolved_before_the_year_filter(case):
    case.accident(date="2015-01-01")
    case.vehicle()
    case.person()
    result = case.run()
    assert not issue_set(result)
    assert reports(result, "person")[0]["in_scope"] is False
    assert reports(result, "accident")[0]["in_scope"] is False


@pytest.fixture
def loaded_s0(connection, tmp_path, request):
    from arsia_ingest.pipeline import prepare
    from arsia_ingest.raw_load import load_prepared

    variant = request.param
    expected_count = 19 if variant == "s0" else 20
    directory = REPOSITORY / "tests/fixtures" / variant
    config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
    contract = json.loads((directory / "contract.json").read_text(encoding="utf-8"))
    prefix = f"syn_c06_{uuid4().hex}_"

    def namespace(value):
        return prefix + value.removeprefix("syn_")

    identities = {value: namespace(value) for resource in config["resources"]
                  for value in (resource["source_id"], resource["resource_id"])}

    def remap(value):
        if isinstance(value, dict):
            return {key: remap(item) for key, item in value.items()}
        if isinstance(value, list):
            return [remap(item) for item in value]
        return identities.get(value, value) if isinstance(value, str) else value

    contract = remap(contract)
    for resource in config["resources"]:
        resource["source_id"] = namespace(resource["source_id"])
        resource["resource_id"] = namespace(resource["resource_id"])
        resource["path"] = str(directory / resource["path"])
    sources = contract["sources"]
    config_path = tmp_path / "inputs.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(contract), encoding="utf-8")
    receipt = prepare(config_path, tmp_path / "intake")
    assert (receipt["status"], receipt["raw_count"]) == ("prepared", expected_count)
    run_dir = Path(receipt["run_dir"])
    loaded = load_prepared(connection, run_dir, sources)
    assert (loaded.raw_count, loaded.inserted_count) == (expected_count, expected_count)
    files = json.loads((run_dir / "files.json").read_text(encoding="utf-8"))["files"]
    selected = []
    for role in ("accident", "vehicle", "person"):
        item = next(item for item in files if item["resource_id"].endswith(f"_vic_{role}"))
        selected.append({key: item[key] for key in
                         ("source_id", "resource_id", "file_sha256", "parser_version", "raw_count")}
                        | {"role": role})
    return {"files": selected, "run_dir": run_dir, "sources": sources, "receipt": receipt,
            "contract_path": contract_path}


@pytest.mark.parametrize("loaded_s0", ["s0", "s8"], indirect=True)
def test_existing_synthetic_inputs_reach_c06_through_raw_loader(connection, loaded_s0):
    params = {"files": loaded_s0["files"], "analysis": {"year_from": 2020, "year_to": 2024},
              "blank_vehicle_allowed": True, "count_scope_confirmed": True}
    selected_ids = [item["resource_id"] for item in loaded_s0["files"]]
    before = connection.execute(
        "SELECT raw_record_id, payload FROM raw.record WHERE resource_id = ANY(%s) "
        "ORDER BY raw_record_id", (selected_ids,),
    ).fetchall()
    result = [row[0] for row in connection.execute(
        SQL_PATH.read_text(encoding="utf-8"), (json.dumps(params),)).fetchall()]
    assert not issue_set(result)
    assert {kind: len(reports(result, kind)) for kind in
            ("file", "accident", "vehicle", "person")} == {
                "file": 3, "accident": 2, "vehicle": 3, "person": 3}
    assert sorted(row["observed_count"] for row in reports(result, "accident")) == [1, 2]
    after = connection.execute(
        "SELECT raw_record_id, payload FROM raw.record WHERE resource_id = ANY(%s) "
        "ORDER BY raw_record_id", (selected_ids,),
    ).fetchall()
    assert after == before
    assert len(after) == 8


@pytest.mark.parametrize("loaded_s0", ["s0", "s8"], indirect=True)
def test_real_frozen_manifest_reaches_the_adapter(connection, loaded_s0, tmp_path):
    from arsia_ingest.manifest import COMPONENTS, build_manifest, read_json, s0_definitions
    from arsia_c.person_checks import review_manifest

    project = tmp_path / "test-inventory"
    project.mkdir()
    components = {}
    for name in COMPONENTS:
        relative = f"{name}.sql"
        (project / relative).write_text(f"-- {name}: test inventory, not platform SQL.\n")
        components[name] = [relative]
    (project / "schema.sql").write_text("-- Test inventory; no schema is installed here.\n")
    definitions = s0_definitions(loaded_s0["contract_path"])
    manifest = build_manifest(
        loaded_s0["run_dir"], **definitions, project_root=project,
        inventory={"components": components, "schema_files": ["schema.sql"]},
        qa_contract=read_json(REPOSITORY / "config/qa-team-v1.1.json"),
        prepared_by="C06 PostgreSQL test",
        origins={resource["id"]: {"download_url": None, "evidence_ref": "S0 test contract"}
                 for resource in definitions["contracts"]},
    )
    before = manifest.as_dict()
    result = review_manifest(connection, manifest)
    assert len(result) == 1
    report = result[0]
    assert report["status"] == "pass"
    assert report["evaluated_count"] == 8
    assert report["affected_count"] == 0
    assert report["reason_counts"] == {}
    assert report["person_count_comparisons"] == 2
    assert report["declared_count_absolute_delta"] == 0
    assert report["vehicle_reference_counts"] == {"matched": 2, "allowed_blank": 1}
    assert manifest.as_dict() == before
    assert len(report["diagnostics"]) == 1
    assert report["diagnostics"][0]["vehicle_reference"] == "allowed_blank"
