"""Policy guards and real SQL counterexamples. Database fixtures are synthetic."""
from copy import deepcopy
import json
import os

import pytest

from arsia_c import person_checks as c06
from arsia_c import restricted_person as restricted
from arsia_ingest.models import IntakeError
from arsia_ingest.manifest import FrozenManifest
from arsia_ingest.runner import ModuleConnection
from test_c06_postgres import RawCase, connection  # Shared rollback fixture.
from test_person_checks import manifest


database = pytest.mark.skipif("ARSIA_TEST_DSN" not in os.environ, reason="Set ARSIA_TEST_DSN for real SQL tests")


class NoQuery:
    autocommit = False

    def cursor(self, **kwargs):
        raise AssertionError("Invalid policy must fail before SQL")


@pytest.mark.parametrize("field,value", [
    ("file_sha256", "f" * 64), ("parser_version", "csv-native-v2"),
    ("locator_version", "csv-logical-v2"), ("raw_count", 1),
    ("raw_count", True), ("source_id", "syn_vic"), ("resource_role", "wrong"),
    ("header", ["ACCIDENT_NO"]), ("format", "xlsx"),
])
def test_changed_file_identity_is_rejected(field, value):
    spec, policy = restricted.restricted_inputs()
    spec["files"][0][field] = value
    with pytest.raises(IntakeError, match="snapshot"):
        restricted.review_restricted(NoQuery(), spec["files"], spec["analysis"], policy)


@pytest.mark.parametrize("change", ["missing_node", "duplicate_file", "years", "policy", "case", "qa", "authority"])
def test_selection_and_policy_cannot_be_relaxed(change):
    spec, policy = restricted.restricted_inputs()
    if change == "missing_node":
        spec["files"].pop()
    elif change == "duplicate_file":
        spec["files"][-1] = deepcopy(spec["files"][0])
    elif change == "years":
        spec["analysis"]["year_from"] = 2015
    elif change == "policy":
        policy["blank_vehicle_rules"]["only_native_csv_empty_string"] = False
    elif change == "case":
        policy["cases"]["unmatched_person_vehicle"][0]["person_id"] = "99"
    elif change == "qa":
        policy["protocol_version"] = "team-v1.1"
    else:
        policy["authority"]["team_use_approved"] = False
    with pytest.raises(IntakeError):
        restricted.review_restricted(NoQuery(), spec["files"], spec["analysis"], policy)


def test_legacy_protocol_is_not_relabelled_as_approved():
    with pytest.raises(IntakeError, match="legacy QA remains blocked"):
        restricted.review_restricted_manifest(NoQuery(), {"rules": {
            "qa_contract": {"version": "team-v1.1"}}})


def test_supported_input_dispatch_uses_independent_policy_copy(monkeypatch):
    spec, policy = restricted.restricted_inputs()
    original = deepcopy(policy)
    calls = []
    def capture(connection, files, analysis, **kwargs):
        calls.append((files, analysis, kwargs))
        return {"scope": "dispatch test only"}
    monkeypatch.setattr(restricted, "_run", capture)
    assert restricted.review_restricted(NoQuery(), list(reversed(spec["files"])),
                                        spec["analysis"], policy)["scope"] == "dispatch test only"
    files, years, arguments = calls[0]
    assert {f["role"] for f in files} == {"person", "vehicle", "accident"}
    assert years == {"year_from": 2020, "year_to": 2024} and arguments["synthetic"] is False
    policy["cases"].clear()
    assert arguments["restricted"].policy == original


def test_relabelling_the_baseline_does_not_create_a_restricted_contract(manifest):
    value = manifest.as_dict()
    value["rules"]["qa_contract"]["version"] = "team-v1.1-vic-r1"
    with pytest.raises(IntakeError, match="protocol changes need a reviewed version"):
        FrozenManifest(json.dumps(value))


@pytest.mark.parametrize("change", ["mapping_missing", "version", "content", "contract_link", "other_person"])
def test_new_manifest_route_requires_complete_policy_binding(change):
    spec, policy = restricted.restricted_inputs()
    value = {"files": spec["files"], "analysis": spec["analysis"], "rules": {
        "qa_contract": {"version": policy["protocol_version"]},
        "mappings": [{"id": restricted.MAPPING_ID, "version": policy["profile_id"], "content": policy}],
        "contracts": [{"id": f["resource_id"], "mapping_ids": [restricted.MAPPING_ID]} for f in spec["files"]],
    }}
    if change == "mapping_missing":
        value["rules"]["mappings"] = []
    elif change == "version":
        value["rules"]["mappings"][0]["version"] = "next-version"
    elif change == "content":
        policy["cases"]["unknown_role_blank_vehicle"] = []
    elif change == "contract_link":
        value["rules"]["contracts"][0]["mapping_ids"] = []
    else:
        value["files"].append({"source_id": "official_other", "resource_id": "official_other_person",
                               "entity_kind": "person_raw"})
    with pytest.raises(IntakeError):
        restricted.review_restricted_manifest(NoQuery(), value)


def test_restricted_entry_rejects_autocommit():
    spec, policy = restricted.restricted_inputs()
    connection = NoQuery()
    connection.autocommit = True
    with pytest.raises(IntakeError, match="active transaction"):
        restricted.review_restricted(connection, spec["files"], spec["analysis"], policy)


def build_case(connection, change=None):
    case = RawCase(connection)
    spec, policy = restricted.restricted_inputs()
    for role, file in case.files.items():
        template = next(f for f in spec["files"] if f["resource_id"].endswith("_" + role))
        case.files[role] = {**template, **file}
    accidents = [
        {"ACCIDENT_NO": "A", "ACCIDENT_DATE": "2020-01-15", "NO_PERSONS": "4"},
        {"ACCIDENT_NO": "B", "ACCIDENT_DATE": "2015-01-15", "NO_PERSONS": "2"},
    ]
    vehicles = [{"ACCIDENT_NO": key, "VEHICLE_ID": "01"} for key in ("A", "B")]
    people = [
        {"ACCIDENT_NO": "A", "PERSON_ID": "01", "VEHICLE_ID": "01", "ROAD_USER_TYPE": "2", "SEATING_POSITION": "D", "INJ_LEVEL": "3"},
        {"ACCIDENT_NO": "A", "PERSON_ID": "02", "VEHICLE_ID": "", "ROAD_USER_TYPE": "1", "SEATING_POSITION": "NA", "INJ_LEVEL": "3"},
        {"ACCIDENT_NO": "A", "PERSON_ID": "03", "VEHICLE_ID": "", "ROAD_USER_TYPE": "9", "SEATING_POSITION": "NA", "INJ_LEVEL": "3"},
        {"ACCIDENT_NO": "A", "PERSON_ID": "04", "VEHICLE_ID": "99", "ROAD_USER_TYPE": "2", "SEATING_POSITION": "D", "INJ_LEVEL": "3"},
        {"ACCIDENT_NO": "B", "PERSON_ID": "01", "VEHICLE_ID": "01", "ROAD_USER_TYPE": "2", "SEATING_POSITION": "D", "INJ_LEVEL": "3"},
    ]
    def ref(role, n):
        return {"resource_id": case.files[role]["resource_id"], "row_locator": f"csv:{n}"}
    def expected_person(n):
        p = people[n - 1]
        return {"accident_no": p["ACCIDENT_NO"], "person_id": p["PERSON_ID"],
                "vehicle_id": p["VEHICLE_ID"], "occurrence_date": "2020-01-15", "scope": "2020-2024",
                "person": ref("person", n), "accident": ref("accident", 1),
                "native_person_fields": deepcopy(p)}
    unmatched = expected_person(4)
    unmatched.update(available_vehicle_refs=[ref("vehicle", 1)], missing_target=["A", "99"])
    policy["cases"] = {
        "unmatched_person_vehicle": [unmatched], "unknown_role_blank_vehicle": [expected_person(3)],
        "declared_count_differences": [{"entity": "person", "accident_no": "B",
            "occurrence_date": "2015-01-15", "scope": "outside_2020-2024", "declared": 2, "observed": 1,
            "accident": ref("accident", 2), "person_refs": [ref("person", 5)], "vehicle_refs": [ref("vehicle", 2)]}],
    }
    policy["source_id"] = case.source_id
    policy["dataset_kind"] = "synthetic"
    policy["authority"]["team_use_approved"] = False
    policy["profile_id"] = "synthetic-policy-engine-test"
    policy["blank_vehicle_rules"]["pedestrian_nonassociation"].update(expected_full_rows=1, expected_analysis_rows=1)
    policy["case_counts"].update({name: {"full": 1, "analysis": analysis} for name, analysis in (
        ("unmatched_person_vehicle", 1), ("unknown_role_blank_vehicle", 1), ("declared_person_differences", 0))})
    expected = policy["qa_expectations"]["QA04_AUXILIARY"]["expected_metrics_by_resource"].pop("official_vic_person")
    expected.update(nonblank_unmatched_count=1, full_count_difference_count=1)
    policy["qa_expectations"]["QA04_AUXILIARY"]["expected_metrics_by_resource"][ref("person", 1)["resource_id"]] = expected
    # Expectations above stay fixed when the input is changed below.
    if change:
        change(accidents, vehicles, people)
    for role, rows in (("accident", accidents), ("vehicle", vehicles), ("person", people)):
        for payload in rows:
            case.add(role, payload)
    return case, policy


def run_case(case, policy):
    return c06._run(ModuleConnection(case.connection), list(case.files.values()), policy["analysis"],
                    synthetic=False, restricted=restricted.RestrictedChecks(policy))


@database
def test_restricted_sql_reports_registered_cases_without_approving_export_scope(connection):
    case, policy = build_case(connection)
    before = connection.execute("SELECT raw_record_id, payload FROM raw.record ORDER BY raw_record_id").fetchall()
    report = run_case(case, policy)
    assert report["status"] == "pass" and report["affected_count"] == 0
    assert report["registered_limitations"] == {"unmatched": 1, "blank": 1, "counts": 1}
    assert all(report["policy_checks"].values())
    assert report["observed_counts"]["diagnostic_comparisons"] == 2
    assert report["declared_count_absolute_delta"] is None and report["definitions_confirmed"] is False
    contribution = report["qa04_person_contribution"]
    assert contribution["actual_metrics"] == contribution["expected_metrics"]
    assert contribution["unexecuted_metrics"] and not report["publication_authorized"]
    assert report["dataset_kind"] == "synthetic" and not report["team_use_approved"]
    difference = next(r for r in report["diagnostics"] if r["kind"] == "accident")
    assert difference["count_text"] == "2" and difference["observed_count"] == 1
    assert difference["diagnostic_count_delta"] == -1 and difference["count_delta"] is None
    assert difference["person_references"][0]["raw_record_id"]
    assert before == connection.execute("SELECT raw_record_id, payload FROM raw.record ORDER BY raw_record_id").fetchall()


@database
@pytest.mark.parametrize("value", [None, " ", "\t", "\u00a0", "NA", 1, False])
def test_only_native_empty_string_is_covered(connection, value):
    case, policy = build_case(connection, lambda a, v, p: p[1].update(VEHICLE_ID=value))
    report = run_case(case, policy)
    assert report["status"] == "block"
    assert any(r.get("person_id") == "02" and r["issues"] for r in report["diagnostics"])


@database
@pytest.mark.parametrize("field,value", [("ROAD_USER_TYPE", "2"), ("ROAD_USER_TYPE", 1),
                                         ("SEATING_POSITION", "D"), ("SEATING_POSITION", None)])
def test_pedestrian_nonassociation_needs_both_native_tokens(connection, field, value):
    case, policy = build_case(connection, lambda a, v, p: p[1].update({field: value}))
    report = run_case(case, policy)
    assert report["status"] == "block" and report["unexpected_cases"]["blank"]


@database
@pytest.mark.parametrize("index,field,value", [
    (2, "PERSON_ID", "88"), (2, "INJ_LEVEL", "2"), (2, "SEATING_POSITION", "D"),
    (3, "VEHICLE_ID", "88"), (3, "ROAD_USER_TYPE", "9"), (3, "ACCIDENT_NO", "B"),
])
def test_same_number_different_case_still_blocks(connection, index, field, value):
    case, policy = build_case(connection, lambda a, v, p: p[index].update({field: value}))
    report = run_case(case, policy)
    assert report["status"] == "block" and not report["policy_checks"]["case_set_match"]
    assert any(report["missing_cases"].values()) and any(report["unexpected_cases"].values())


@database
@pytest.mark.parametrize("change", [
    lambda a, v, p: a[0].update(ACCIDENT_DATE="2019-01-15"),
    lambda a, v, p: a[1].update(NO_PERSONS="3"),
    lambda a, v, p: a[1].update(NO_PERSONS="1"),
    lambda a, v, p: a[0].update(NO_PERSONS="3"),
    lambda a, v, p: p.reverse(),
    lambda a, v, p: v.reverse(),
    lambda a, v, p: a.reverse(),
    lambda a, v, p: v[0].update(VEHICLE_ID="99"),
    lambda a, v, p: p.append(deepcopy(p[3])),
    lambda a, v, p: v.append(deepcopy(v[0])),
    lambda a, v, p: a.append(deepcopy(a[0])),
    lambda a, v, p: p[0].update(ACCIDENT_NO="MISSING"),
    lambda a, v, p: a[1].update(NO_PERSONS="not a number"),
    lambda a, v, p: a[0].update(ACCIDENT_DATE="today"),
])
def test_unregistered_differences_locators_parents_and_duplicates_block(connection, change):
    case, policy = build_case(connection, change)
    report = run_case(case, policy)
    assert report["status"] == "block"
    assert report["reason_counts"]


@database
def test_nonempty_pedestrian_reference_stays_matched(connection):
    case, policy = build_case(connection, lambda a, v, p: p[0].update(ROAD_USER_TYPE="1", SEATING_POSITION="NA"))
    report = run_case(case, policy)
    assert report["status"] == "pass"
    assert report["vehicle_reference_counts"]["matched"] == 2


@database
def test_old_draft_still_blocks_with_the_same_rows(connection):
    case, policy = build_case(connection)
    result = c06._run(ModuleConnection(connection), list(case.files.values()), policy["analysis"], synthetic=False)
    assert result["status"] == "block"
    assert result["reason_counts"]["source_definitions_unconfirmed"] == 1


@database
def test_empty_selected_snapshot_and_unknown_declaration_are_not_zero_success(connection):
    case, policy = build_case(connection, lambda a, v, p: a[1].update(NO_PERSONS=""))
    report = run_case(case, policy)
    assert report["status"] == "block" and report["missing_cases"]["counts"]
    row = next(r for r in report["diagnostics"] if r["kind"] == "accident")
    assert row["declared_count"] is None and row["diagnostic_count_delta"] is None
    for file in case.files.values():
        file["file_sha256"] = "b" * 64
    empty = run_case(case, policy)
    assert empty["status"] == "block" and empty["evaluated_count"] == 0


@database
def test_fictional_policy_cannot_enter_the_official_api(connection):
    case, policy = build_case(connection)
    with pytest.raises(IntakeError, match="Unsupported"):
        restricted.review_restricted(ModuleConnection(connection), list(case.files.values()), policy["analysis"], policy)
