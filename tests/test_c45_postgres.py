"""Native-shaped bad variants and actual B08 -> C03/04/05 -> A06 -> C09."""

from copy import deepcopy
import json
import pytest
from test_c03_nsw_postgres import connection, pytestmark
from c45_support import Case


@pytest.mark.parametrize("state", ["VIC", "QLD"])
def test_project_actual_s0_payloads(connection, state):
    case = Case(connection, state).load()
    case.run()
    rows = case.crashes()
    assert len(rows) == 2
    assert sum(r["fatality_count"] for r in rows) == (1 if state == "VIC" else 0)
    assert sum(r["casualty_count"] for r in rows) == (3 if state == "VIC" else 1)
    assert sum(r["map_eligible"] for r in rows) == (1 if state == "VIC" else 2)
    assert connection.execute("SELECT count(*) FROM pg_temp.arsia_i_unit").fetchone()[
        0
    ] == (3 if state == "VIC" else 0)
    case.run()
    assert case.crashes() == rows


@pytest.mark.parametrize("state", ["VIC", "QLD"])
@pytest.mark.parametrize(
    "token", ["-1", "1.5", "NaN", "Infinity", " 1", "1x", "2147483648", False, {}, []]
)
def test_nonempty_invalid_count_blocks(connection, state, token):
    case = Case(connection, state)
    case.payload("crash")[
        "NO_PERSONS_KILLED" if state == "VIC" else "Count_Casualty_Fatality"
    ] = token
    case.load()
    with pytest.raises(ValueError):
        case.run()


@pytest.mark.parametrize("state", ["VIC", "QLD"])
@pytest.mark.parametrize("value", [None, ""])
def test_unknown_count_keeps_accident_and_independent_flags(connection, state, value):
    case = Case(connection, state)
    case.payload("crash")[
        "NO_PERSONS_INJ_2" if state == "VIC" else "Count_Casualty_Hospitalised"
    ] = value
    case.load()
    case.run()
    row = case.crashes()[0]
    assert row["casualty_count"] is None and not row["casualty_eligible"]
    assert row["fatality_eligible"] and row["fatal_crash_eligible"]
    assert any(n["field"] == "casualty_count" for n in row["quality_notes"]["fields"])


@pytest.mark.parametrize("state", ["VIC", "QLD"])
@pytest.mark.parametrize("value", ["UNKNOWN", " F", "NA"])
def test_unregistered_severity_blocks(connection, state, value):
    case = Case(connection, state)
    case.payload("crash")["SEVERITY" if state == "VIC" else "Crash_Severity"] = value
    case.load()
    with pytest.raises(ValueError, match="categories"):
        case.run()


@pytest.mark.parametrize("state", ["VIC", "QLD"])
def test_missing_severity_not_nonfatal(connection, state):
    case = Case(connection, state)
    case.payload("crash")["SEVERITY" if state == "VIC" else "Crash_Severity"] = ""
    case.load()
    case.run()
    r = case.crashes()[0]
    assert r["severity_code"] == "__MISSING__" and r["is_fatal_crash"] is None
    assert not r["fatal_crash_eligible"] and r["casualty_eligible"]


@pytest.mark.parametrize(
    "value",
    ["2020-02-30", "2020-2-1", "2020/01/01", "", "0000-01-01", "2020-01-01 trailing"],
)
def test_vic_invalid_dates_block(connection, value):
    case = Case(connection, "VIC")
    case.payload("crash")["ACCIDENT_DATE"] = value
    case.load()
    with pytest.raises(ValueError, match="dates"):
        case.run()


@pytest.mark.parametrize(
    "field,value",
    [
        ("Crash_Year", "200x"),
        ("Crash_Year", ""),
        ("Crash_Year", "0000"),
        ("Crash_Month", "13"),
        ("Crash_Month", "Jan"),
        ("Crash_Month", "NA"),
    ],
)
def test_qld_invalid_occurrence_blocks(connection, field, value):
    case = Case(connection, "QLD")
    case.payload("crash")[field] = value
    case.load()
    with pytest.raises(ValueError, match="dates"):
        case.run()


def test_qld_month_precision_no_invented_day(connection):
    case = Case(connection, "QLD")
    case.payload("crash")["Crash_Month"] = ""
    case.load()
    case.run()
    a, b = case.crashes()
    assert a["date_precision"] == "year" and a["occurrence_month"] is None
    assert (
        b["date_precision"] == "month"
        and a["occurrence_date"] is None
        and b["occurrence_date"] is None
    )


def test_qld_known_components_must_equal_total(connection):
    case = Case(connection, "QLD")
    case.payload("crash")["Count_Casualty_Total"] = "99"
    case.load()
    with pytest.raises(ValueError, match="components"):
        case.run()


@pytest.mark.parametrize("state", ["VIC", "QLD"])
def test_duplicates_outside_scope_still_block(connection, state):
    case = Case(connection, state)
    rid = next(
        f["resource_id"]
        for f in case.manifest["files"]
        if f["resource_role"] == "crash"
    )
    row = case.payload("crash")
    row["ACCIDENT_DATE" if state == "VIC" else "Crash_Year"] = (
        "2019-01-01" if state == "VIC" else "2019"
    )
    case.rows[rid].append(deepcopy(row))
    case.load()
    with pytest.raises(ValueError, match="Duplicate"):
        case.run()


@pytest.mark.parametrize("role", ["vehicle", "node"])
def test_vic_orphans_are_not_hidden_by_year_filter(connection, role):
    case = Case(connection, "VIC")
    case.payload(role)["ACCIDENT_NO"] = "ORPHAN"
    case.load()
    with pytest.raises(ValueError, match="relationships"):
        case.run()


def test_vic_duplicate_vehicle_blocks(connection):
    case = Case(connection, "VIC")
    case.rows["syn_vic_vehicle"].append(deepcopy(case.payload("vehicle")))
    case.load()
    with pytest.raises(ValueError, match="relationships"):
        case.run()


def test_vic_unknown_vehicle_type_blocks(connection):
    case = Case(connection, "VIC")
    case.payload("vehicle")["VEHICLE_TYPE"] = "UNREGISTERED"
    case.load()
    with pytest.raises(ValueError, match="vehicle semantics"):
        case.run()


def test_vic_declared_count_mismatch_blocks_synthetic(connection):
    case = Case(connection, "VIC")
    case.payload("crash")["NO_OF_VEHICLES"] = "99"
    case.load()
    with pytest.raises(ValueError, match="declared vehicle"):
        case.run()


@pytest.mark.parametrize(
    "change",
    [
        {"LATITUDE": "NaN"},
        {"LATITUDE": "-90.00000001"},
        {"LONGITUDE": "180.00000001"},
        {"LATITUDE": ""},
        {"LATITUDE": "-37.123456799"},
    ],
)
def test_vic_bad_or_conflicting_node_does_not_delete_crash(connection, change):
    case = Case(connection, "VIC")
    case.payload("node").update(change)
    case.load()
    case.run()
    r = case.crashes()[0]
    assert len(case.crashes()) == 2 and not r["map_eligible"]
    assert all(
        r[k] is None
        for k in ["latitude", "longitude", "location_crs", "location_record_id"]
    )
    assert len(r["quality_notes"]["location"]["candidate_raw_record_ids"]) == 2


def test_vic_missing_match_retains_crash_and_reason(connection):
    case = Case(connection, "VIC")
    case.payload("crash")["NODE_ID"] = "NO_MATCH"
    case.load()
    case.run()
    r = case.crashes()[0]
    assert (
        r["quality_notes"]["location"]["reason_code"] == "no_location"
        and not r["map_eligible"]
        and r["fatality_eligible"]
    )


@pytest.mark.parametrize("state", ["VIC", "QLD"])
def test_incomplete_raw_is_rejected(connection, state):
    case = Case(connection, state)
    rid = next(
        f["resource_id"]
        for f in case.manifest["files"]
        if f["resource_role"] == "crash"
    )
    case.rows[rid].pop()
    case.load(sync_counts=False)
    with pytest.raises(ValueError, match="Incomplete"):
        case.run()


@pytest.mark.parametrize("state", ["VIC", "QLD"])
def test_missing_native_field_is_not_silently_unknown(connection, state):
    case = Case(connection, state)
    case.payload("crash").pop("SEVERITY" if state == "VIC" else "Crash_Severity")
    case.load()
    with pytest.raises(ValueError, match="native fields"):
        case.run()


def test_three_state_actual_raw_to_canonical(connection, tmp_path):
    from pathlib import Path
    from test_c03_nsw_projection import component_manifest
    from test_c03_nsw_postgres import FakeContext
    from arsia_ingest.pipeline import prepare
    from arsia_ingest.raw_load import load_prepared
    from arsia_ingest.runner import ModuleConnection
    from arsia_c.projections import nsw, vic, qld
    from arsia_ingest.vault_load import load_vault
    from arsia_c.canonical import load_canonical

    root = Path(__file__).resolve().parents[1]
    m = component_manifest()
    ctx = FakeContext(m)
    intake = prepare(root / "tests/fixtures/s0/config.json", tmp_path / "intake")
    assert load_prepared(connection, intake["run_dir"], m["sources"]).raw_count == 19
    before = connection.execute(
        "SELECT raw_record_id,payload FROM raw.record ORDER BY raw_record_id"
    ).fetchall()
    connection.execute(
        "INSERT INTO meta.batch(batch_id,dataset_kind,input_fingerprint,manifest) VALUES (%s,'synthetic',%s,%s::jsonb)",
        (ctx.batch_id, "b" * 64, json.dumps(m)),
    )
    shared = ModuleConnection(connection)
    for mod in (nsw, vic, qld):
        mod.project(shared, ctx)
    assert (
        connection.execute("SELECT count(*) FROM pg_temp.arsia_i_crash").fetchone()[0]
        == 6
    )
    load_vault(shared, ctx)
    load_canonical(shared, ctx)
    assert connection.execute(
        "SELECT count(*),sum(fatality_count),sum(casualty_count),count(*) FILTER(WHERE map_eligible) FROM canonical.crash"
    ).fetchone() == (6, 3, 7, 4)
    assert connection.execute("SELECT count(*) FROM canonical.unit").fetchone()[0] == 6
    for kind in ("crash", "unit"):
        assert (
            connection.execute(
                f"SELECT to_jsonb(c) FROM canonical.{kind} c ORDER BY source_id,{kind}_key"
            ).fetchall()
            == connection.execute(
                f"SELECT to_jsonb(c) FROM pg_temp.arsia_i_{kind} c ORDER BY source_id,{kind}_key"
            ).fetchall()
        )
    assert (
        connection.execute(
            "SELECT raw_record_id,payload FROM raw.record ORDER BY raw_record_id"
        ).fetchall()
        == before
    )
    connection.rollback()
    assert connection.execute("SELECT count(*) FROM canonical.crash").fetchone()[0] == 0


@pytest.mark.parametrize("state", ["VIC", "QLD"])
@pytest.mark.parametrize("key", ["", None, "\u00a0", "\t"])
def test_blank_native_crash_keys_block(connection, state, key):
    import psycopg

    case = Case(connection, state)
    case.payload("crash")["ACCIDENT_NO" if state == "VIC" else "Crash_Ref_Number"] = key
    case.load()
    with pytest.raises((ValueError, psycopg.Error)):
        case.run()


@pytest.mark.parametrize("value", ["NaN", "Infinity", "180.000000001", "abc"])
def test_qld_invalid_coordinate_does_not_enable_map(connection, value):
    case = Case(connection, "QLD")
    case.payload("crash")["Crash_Longitude"] = value
    case.load()
    case.run()
    row = case.crashes()[0]
    assert not row["map_eligible"] and row["casualty_eligible"]
    assert row["quality_notes"]["location"]["reason_code"] == "invalid_coordinate"
    assert all(
        row[k] is None
        for k in ("latitude", "longitude", "location_crs", "location_record_id")
    )


def test_qld_unconfirmed_synthetic_crs_keeps_truthful_reason(connection):
    case = Case(connection, "QLD")
    case.manifest["rules"]["mappings"][0]["content"]["location"]["crs"] = None
    case.load()
    case.run()
    rows = case.crashes()
    assert len(rows) == 2
    assert sum(row["fatality_count"] for row in rows) == 0
    assert sum(row["casualty_count"] for row in rows) == 1
    for row in rows:
        assert not row["map_eligible"]
        assert all(row[key] is None for key in (
            "latitude", "longitude", "location_crs", "location_record_id"
        ))
        note = row["quality_notes"]["location"]
        assert note["reason_code"] == "definition_unconfirmed"
        assert note["resolution"] == "Synthetic source CRS is unconfirmed; map disabled."
        assert note["candidate_raw_record_ids"] == [str(row["raw_record_id"])]


def test_qld_official_sql_keeps_known_datum_reason(connection):
    from arsia_c.projections.source_contracts import parameters, clear_projection, sql

    case = Case(connection, "QLD").load()
    case.run()
    before = case.crashes()
    p = parameters(case.manifest, case.context.batch_id, "QLD")
    # Test the official SQL branch with synthetic rows, not an official snapshot.
    p.update(dataset_kind="official", map_enabled=False,
             fatality_field="Count_Casualty_Fatality")
    with connection.cursor() as cursor:
        clear_projection(cursor, p)
        cursor.execute(sql("c45_crash_insert.sql"), p)
    after = case.crashes()
    assert len(after) == len(before)
    changed = {"latitude", "longitude", "location_crs", "location_record_id",
               "map_eligible", "quality_notes"}
    for old, new in zip(before, after):
        assert {k: v for k, v in new.items() if k not in changed} == {
            k: v for k, v in old.items() if k not in changed
        }
        assert not new["map_eligible"]
        note = new["quality_notes"]["location"]
        assert note["reason_code"] == "definition_unconfirmed"
        assert note["resolution"] == (
            "Known GDA2020 source datum; EPSG:4326 operation unverified. Official map disabled."
        )


@pytest.mark.parametrize("state", ["VIC", "QLD"])
def test_sum_overflow_blocks_before_integer_projection(connection, state):
    case = Case(connection, state)
    for field in (
        ["NO_PERSONS_KILLED", "NO_PERSONS_INJ_2"]
        if state == "VIC"
        else ["Count_Casualty_Fatality", "Count_Casualty_Hospitalised"]
    ):
        case.payload("crash")[field] = "2147483647"
    case.load()
    with pytest.raises(ValueError, match="counts"):
        case.run()


def test_vic_year_filter_excludes_real_children_after_full_parent_checks(connection):
    case = Case(connection, "VIC")
    case.payload("crash")["ACCIDENT_DATE"] = "2019-01-01"
    case.load()
    case.run()
    assert len(case.crashes()) == 1
    assert (
        connection.execute("SELECT count(*) FROM pg_temp.arsia_i_unit").fetchone()[0]
        == 2
    )
    assert connection.execute("SELECT count(*) FROM raw.record").fetchone()[0] == 12


def test_qld_aggregate_unit_counts_never_create_units(connection):
    case = Case(connection, "QLD")
    case.payload("crash")["Count_Unit_Car"] = "999999"
    case.load()
    case.run()
    assert (
        len(case.crashes()) == 2
        and connection.execute("SELECT count(*) FROM pg_temp.arsia_i_unit").fetchone()[
            0
        ]
        == 0
    )


def test_vic_many_equivalent_nodes_keep_one_crash_and_numeric_first_location(
    connection,
):
    case = Case(connection, "VIC")
    first = deepcopy(case.payload("node"))
    case.rows["syn_vic_node"] = [deepcopy(first) for _ in range(12)]
    case.load()
    case.run()
    row = case.crashes()[0]
    assert len(case.crashes()) == 2 and row["map_eligible"]
    expected = connection.execute(
        "SELECT raw_record_id FROM raw.record WHERE resource_id='syn_vic_node' AND row_locator='csv:2'"
    ).fetchone()[0]
    assert row["location_record_id"] == str(expected)
    assert (
        connection.execute(
            "SELECT count(*) FROM raw.record WHERE resource_id='syn_vic_node'"
        ).fetchone()[0]
        == 12
    )


def test_vic_exact_coordinate_difference_before_rounding_disables_map(connection):
    case = Case(connection, "VIC")
    case.payload("node", 0)["LATITUDE"] = "-37.800000001"
    case.payload("node", 1)["LATITUDE"] = "-37.800000002"
    case.load()
    case.run()
    row = case.crashes()[0]
    assert (
        not row["map_eligible"]
        and row["quality_notes"]["location"]["reason_code"] == "location_conflict"
    )


def test_late_qld_error_rolls_back_prior_vic_outputs(connection):
    v = Case(connection, "VIC").load()
    v.run()
    q = Case(connection, "QLD")
    q.payload("crash")["Crash_Month"] = "INVALID"
    q.load()
    with pytest.raises(ValueError):
        q.run()
    connection.rollback()
    assert connection.execute("SELECT count(*) FROM raw.record").fetchone()[0] == 0
    assert (
        connection.execute("SELECT to_regclass('pg_temp.arsia_i_crash')").fetchone()[0]
        is None
    )


@pytest.mark.parametrize("state", ["VIC", "QLD"])
def test_alternative_synthetic_resource_ids_use_frozen_contract(connection, state):
    case = Case(connection, state)
    prefix = "syn_" + state.lower()
    replacement = prefix + "_alternate"
    case.manifest = json.loads(json.dumps(case.manifest).replace(prefix, replacement))
    case.rows = {k.replace(prefix, replacement): v for k, v in case.rows.items()}
    case.load()
    case.run()
    assert len(case.crashes()) == 2
    assert all(r["source_id"] == replacement for r in case.crashes())


@pytest.mark.parametrize("state", ["VIC", "QLD"])
def test_unselected_old_raw_snapshot_is_not_used(connection, state):
    from uuid import uuid4

    case = Case(connection, state).load()
    f = case.manifest["files"][0]
    connection.execute(
        "INSERT INTO raw.record(raw_record_id,source_id,resource_id,file_sha256,parser_version,row_locator,payload) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)",
        (
            uuid4(),
            f["source_id"],
            f["resource_id"],
            "f" * 64,
            f["parser_version"],
            "csv:900",
            json.dumps({"invalid": "old snapshot"}),
        ),
    )
    case.run()
    assert len(case.crashes()) == 2


@pytest.mark.parametrize("state", ["VIC", "QLD"])
def test_empty_synthetic_selected_snapshot_is_valid_component(connection, state):
    case = Case(connection, state)
    case.rows = {k: [] for k in case.rows}
    case.load()
    case.run()
    assert (
        case.crashes() == []
        and connection.execute("SELECT count(*) FROM pg_temp.arsia_i_unit").fetchone()[
            0
        ]
        == 0
    )


@pytest.mark.parametrize(
    "kind,attributes",
    [("crash", {"map_eligible": True}), ("unit", {"count_eligible": True})],
)
def test_c09_blocks_unavailable_vic_outputs_even_if_c04_is_bypassed(
    connection, kind, attributes
):
    """Deliberately malformed incoming Satellite: check the restricted boundary."""
    from uuid import uuid4
    from test_c04_vic_projection import official_manifest
    from test_c03_nsw_postgres import FakeContext
    from arsia_ingest.raw_load import RawLoader
    from arsia_ingest.runner import ModuleConnection
    from arsia_ingest.models import IntakeError
    from arsia_c.canonical import load_canonical

    m = official_manifest("VIC")
    ctx = FakeContext(m)
    sid = "official_vic"
    scope = m["sources"][0]["release_scope"]
    RawLoader(
        connection, sources=m["sources"], files=m["files"], dataset_kind="official"
    ).register()
    connection.execute(
        "INSERT INTO meta.batch(batch_id,dataset_kind,input_fingerprint,manifest) VALUES (%s,'official',%s,%s::jsonb)",
        (ctx.batch_id, "d" * 64, json.dumps(m)),
    )
    f = next(f for f in m["files"] if f["entity_kind"] == kind)
    raw_id = uuid4()
    connection.execute(
        "INSERT INTO raw.record(raw_record_id,source_id,resource_id,file_sha256,parser_version,row_locator,payload) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)",
        (
            raw_id,
            sid,
            f["resource_id"],
            f["file_sha256"],
            f["parser_version"],
            "csv:1",
            json.dumps({"ACCIDENT_NO": "fault"}),
        ),
    )
    key = connection.execute("SELECT rv.encode_business_key('fault')").fetchone()[0]
    connection.execute(
        f"INSERT INTO rv.hub_{kind}(source_id,release_scope,{kind}_key,first_seen_batch_id) VALUES (%s,%s,%s,%s)",
        (sid, scope, key, ctx.batch_id),
    )
    connection.execute(
        f"INSERT INTO rv.sat_{kind}(batch_id,source_id,release_scope,{kind}_key,raw_record_id,attributes) VALUES (%s,%s,%s,%s,%s,%s::jsonb)",
        (ctx.batch_id, sid, scope, key, raw_id, json.dumps(attributes)),
    )
    with pytest.raises(IntakeError, match="unavailable output"):
        load_canonical(ModuleConnection(connection), ctx)
