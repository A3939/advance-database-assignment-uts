"""Real S0 query integration. Successful query fixtures are not E releases."""
from dataclasses import replace
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

if "AC_TEST_RUN" not in os.environ:
    pytest.skip("Use tools/verify_analysis_postgres.py and its private database", allow_module_level=True)

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from arsia_d05 import TrendRequest, query_trend, install_sql as trend_sql
from arsia_d06 import SeverityRequest, query_severity, install_sql as severity_sql
from arsia_d07 import MapRequest, query_map, install_sql as map_sql
from arsia_d08 import UnitRequest, query_units, install_sql as units_sql
from arsia_ingest.manifest import FrozenManifest
from arsia_ingest.runner import ModuleConnection
from cd_support import ROOT, interface_manifest
from test_raw_load_postgres import connection
from test_cd_integration_postgres import prepared, private_database, cleanup
from test_qa_joint_postgres import load_chain, finish

QUERIES = ((query_trend, TrendRequest), (query_severity, SeverityRequest),
           (query_map, MapRequest), (query_units, UnitRequest))


@pytest.fixture(scope="session", autouse=True)
def deployment():
    options = conninfo_to_dict(os.environ["ARSIA_TEST_DSN"])
    options["user"] = "arsia_reader"
    with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as owner:
        assert owner.execute("SELECT current_setting('arsia.test_run')").fetchone() == (os.environ["AC_TEST_RUN"],)
        owner.execute("SET LOCAL ROLE arsia_migrator")
        for install in (trend_sql, severity_sql, map_sql, units_sql):
            owner.execute(install())
        owner.execute("RESET ROLE")
        owner.execute(sql.SQL("ALTER ROLE arsia_reader PASSWORD {}").format(sql.Literal(options["password"])))
    return make_conninfo(**options)


@pytest.fixture
def reader(deployment):
    with psycopg.connect(deployment) as conn:
        assert conn.execute("SELECT current_user,session_user").fetchone() == ("arsia_reader", "arsia_reader")
        yield conn
        conn.rollback()


@pytest.fixture
def frozen(prepared):
    value = interface_manifest(prepared[0]).as_dict()
    analysis = json.loads((ROOT / "config/analysis-inventory.json").read_text())
    hashes = {r["path"]: r["sha256"] for r in value["rules"]["code_files"]}
    for row in analysis["code_files"]:
        assert row["path"] not in hashes or hashes[row["path"]] == row["sha256"]
        hashes[row["path"]] = row["sha256"]
    value["rules"]["code_files"] = [{"path": p,"sha256": h} for p,h in sorted(hashes.items())]
    value["provenance"]["prepared_by"] = "D05-D08 query fixture; partial inventory; no E FP1/publication"
    return FrozenManifest(json.dumps(value))


@pytest.fixture
def candidate(connection, prepared, frozen):
    context, inputs = load_chain(connection, prepared, frozen)
    rows, summaries = finish(connection, prepared, context, inputs)
    assert len(rows) == 63 and len(summaries) == 7
    # D queries require this state. This labelled fixture does not execute E's gate.
    connection.execute("UPDATE meta.batch SET status='succeeded',finished_at=clock_timestamp() WHERE batch_id=%s", (context.batch_id,))
    connection.commit()
    try:
        yield context
    finally:
        connection.rollback()
        with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as owner:
            owner.execute("DELETE FROM meta.current_release WHERE batch_id=%s", (context.batch_id,))
        cleanup([context.batch_id], frozen)


def read_all(conn, batch, **filters):
    return tuple(query(ModuleConnection(conn), request("synthetic", batch, **filters)) for query,request in QUERIES)


def test_three_source_queries_use_real_qa_checked_s0(reader, candidate):
    trend, severity, mapping, units = read_all(reader, candidate.batch_id)
    assert len(trend) == 15
    assert {s: sum(r["crash_count"] for r in trend if r["source_id"] == s) for s in ("syn_nsw","syn_vic","syn_qld")} == dict(syn_nsw=2,syn_vic=2,syn_qld=2)
    assert {(r["source_id"],r["severity_code"],r["crash_count"]) for r in severity} == {
        ("syn_nsw","F",1),("syn_nsw","__MISSING__",1),("syn_vic","F",1),
        ("syn_vic","I",1),("syn_qld","I",1),("syn_qld","N",1)}
    assert all(r["definition_version"] == "syn-1" and r["definition_text"] for r in severity)
    assert len(mapping.points) == 4
    assert mapping.coverage["crash_count"] == 6 and mapping.coverage["point_count"] == 4
    assert mapping.coverage["coverage_percentage"] == Decimal("66.67")
    assert len({(r["source_id"],r["release_scope"],r["crash_key"]) for r in mapping.points}) == 4
    assert {s:sum(r["unit_count"] for r in units if r["source_id"] == s) for s in ("syn_nsw","syn_vic","syn_qld")} == dict(syn_nsw=3,syn_vic=3,syn_qld=0)
    assert {(r["source_id"],r["statistical_scope"]) for r in units} == {
        ("syn_nsw","synthetic_traffic_unit"),("syn_vic","synthetic_vehicle")}
    assert all(str(r["batch_id"]) == candidate.batch_id for group in (trend,severity,mapping.points,units) for r in group)
    assert query_units(ModuleConnection(reader), UnitRequest("synthetic",candidate.batch_id,source_ids=("syn_qld",))) == ()
    candidate.evidence.write_json("analysis-result.json", json.loads(json.dumps({
        "scope":"Private S0 query fixture; no E publication or official replay",
        "trend":trend,"severity":severity,"points":mapping.points,"coverage":mapping.coverage,"units":units,
    }, default=str)))


def test_zero_null_unknown_month_and_empty_filters(reader, candidate):
    trend, severity, mapping, units = read_all(reader, candidate.batch_id,year_from=2024,year_to=2024)
    assert len(trend) == 3 and all(r["crash_count"] == 0 for r in trend)
    assert all(r["fatality_known_count"] == 0 and r["fatality_count"] is None for r in trend)
    assert not severity and not units and not mapping.points
    assert mapping.coverage["coverage_percentage"] is None
    annual = query_trend(ModuleConnection(reader), TrendRequest("synthetic",candidate.batch_id,source_ids=("syn_nsw",),year_from=2020,year_to=2020))
    monthly = query_trend(ModuleConnection(reader), TrendRequest("synthetic",candidate.batch_id,grain="month",source_ids=("syn_nsw",),year_from=2020,year_to=2020))
    assert annual[0]["crash_count"] == 2 and annual[0]["month_known_count"] == 1
    assert sum(r["crash_count"] for r in monthly) == 1
    assert all(r["excluded_unknown_month_count"] == 1 for r in monthly)
    qld = query_trend(ModuleConnection(reader), TrendRequest("synthetic",candidate.batch_id,source_ids=("syn_qld",),year_from=2020,year_to=2020))
    assert qld[0]["fatality_known_count"] == 1 and qld[0]["fatality_count"] == 0
    missing = query_trend(ModuleConnection(reader), TrendRequest("synthetic",candidate.batch_id,year_from=2019,year_to=2019))
    assert all(r["coverage_status"] == "not_covered" and r["crash_count"] is None for r in missing)


@pytest.mark.parametrize("index", range(4), ids=("D05","D06","D07","D08"))
@pytest.mark.parametrize("case", ("unknown_batch","wrong_mode","unknown_source"))
def test_reader_rejects_invalid_database_request(reader, candidate, index, case):
    query, request = QUERIES[index]
    parameters = {"dataset_kind":"synthetic","batch_id":candidate.batch_id}
    if case == "unknown_batch": parameters["batch_id"] = str(uuid4())
    elif case == "wrong_mode": parameters["dataset_kind"] = "official"
    else: parameters["source_ids"] = ("not_a_source",)
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        query(ModuleConnection(reader), request(**parameters))
    reader.rollback()


@pytest.mark.parametrize("index", range(4), ids=("D05","D06","D07","D08"))
def test_running_fixture_is_not_readable(reader, connection, prepared, frozen, index):
    context, inputs = load_chain(connection, prepared, frozen)
    finish(connection, prepared, context, inputs)
    connection.commit()
    try:
        query, request = QUERIES[index]
        with pytest.raises(psycopg.errors.InvalidParameterValue):
            query(ModuleConnection(reader), request("synthetic",context.batch_id))
        reader.rollback()
    finally:
        cleanup([context.batch_id], frozen)


def test_reader_permissions_and_deployed_function_owners(reader, candidate):
    for schema in ("meta","raw","rv","canonical","dw","qa"):
        assert reader.execute("SELECT has_schema_privilege(current_user,%s,'USAGE')", (schema,)).fetchone() == (False,)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        reader.execute("SELECT * FROM dw.fact_crash")
    reader.rollback()
    with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as owner:
        functions=owner.execute("""SELECT p.proname,r.rolname,p.prosecdef,p.provolatile,p.proconfig,
            has_function_privilege('arsia_reader',p.oid,'EXECUTE'),
            EXISTS(SELECT 1 FROM aclexplode(p.proacl) a WHERE a.grantee=0 AND a.privilege_type='EXECUTE')
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_roles r ON r.oid=p.proowner
            WHERE n.nspname='published' AND p.proname ~ '^d0[5-8]_' ORDER BY p.proname""").fetchall()
    assert len(functions) == 7
    for name,owner,secure,volatility,settings,execute,public in functions:
        assert (owner,secure,volatility,settings,public) == ("arsia_migrator",True,"s",["search_path=pg_catalog"],False)
        assert execute == ("validate_request" not in name)
    read_all(reader,candidate.batch_id)
    assert reader.info.transaction_status == psycopg.pq.TransactionStatus.INTRANS and not reader.closed


def test_explicit_batch_stays_fixed_after_pointer_switch(reader, candidate):
    before = read_all(reader,candidate.batch_id)
    old = str(uuid4())
    with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as owner:
        owner.execute("""INSERT INTO meta.batch(batch_id,dataset_kind,input_fingerprint,manifest,status,finished_at)
            SELECT %s,dataset_kind,%s,manifest,'succeeded',clock_timestamp() FROM meta.batch WHERE batch_id=%s""",
                      (old,"c"*64,candidate.batch_id))
        owner.execute("INSERT INTO meta.current_release(dataset_kind,batch_id) VALUES ('synthetic',%s)",(candidate.batch_id,))
        owner.execute("UPDATE meta.current_release SET batch_id=%s WHERE dataset_kind='synthetic'",(old,))
    try:
        assert read_all(reader,candidate.batch_id) == before
    finally:
        reader.rollback()
        with psycopg.connect(os.environ["ARSIA_TEST_ADMIN_DSN"]) as owner:
            owner.execute("DELETE FROM meta.current_release WHERE batch_id=%s",(old,))
            owner.execute("DELETE FROM meta.batch WHERE batch_id=%s",(old,))
