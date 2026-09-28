"""C09 parent lookup on a fresh, uncommitted synthetic batch."""

import json
import os
from pathlib import Path

import pytest

from arsia_c import canonical_validation as validation
from arsia_c.canonical import load_canonical
from arsia_ingest.models import IntakeError
from arsia_ingest.runner import ModuleConnection
from arsia_ingest.vault_load import load_vault
from test_c09_postgres import C09Case, connection, pytestmark


def nodes(plan):
    yield plan
    for child in plan.get("Plans", []):
        yield from nodes(child)


def add_rows(case, parents=1000):
    conn = case.connection
    conn.execute("""CREATE TEMP TABLE c09_extra AS
        SELECT gen_random_uuid() AS raw_id, n::text AS native_key, u,
               CASE WHEN u=0 THEN 'crash' ELSE 'unit' END AS kind
        FROM generate_series(1,%s) n CROSS JOIN generate_series(0,2) u""", (parents,))
    conn.execute("""INSERT INTO raw.record
        (raw_record_id,resource_id,source_id,file_sha256,parser_version,row_locator,payload)
        SELECT raw_id, CASE WHEN kind='crash' THEN %s ELSE %s END, %s,
          CASE WHEN kind='crash' THEN %s ELSE %s END, %s,
          kind || ':' || native_key || ':' || u,
          jsonb_build_object('Crash ID',native_key) ||
          CASE WHEN kind='unit' THEN jsonb_build_object('Traffic unit ID',u::text)
               ELSE '{}'::jsonb END
        FROM pg_temp.c09_extra""", (case.crash_resource_id, case.unit_resource_id,
        case.source_id, case.crash_sha, case.unit_sha, case.parser_version))
    for kind in ("crash", "unit"):
        key = ("rv.encode_business_key(e.native_key)" if kind == "crash" else
               "rv.encode_business_key(e.native_key,e.u::text)")
        parent = (",'crash_key',rv.encode_business_key(e.native_key)" if kind == "unit" else "")
        conn.execute(f"""INSERT INTO pg_temp.arsia_i_{kind}
            SELECT (jsonb_populate_record(NULL::pg_temp.arsia_i_{kind},
              to_jsonb(template) || jsonb_build_object(
                '{kind}_key',{key},'raw_record_id',e.raw_id {parent}))).*
            FROM (SELECT * FROM pg_temp.arsia_i_{kind} LIMIT 1) template
            CROSS JOIN pg_temp.c09_extra e WHERE e.kind=%s""", (kind,))


def test_parent_lookup_uses_full_key_and_caller_rollback(connection, monkeypatch):
    case = C09Case(connection)
    add_rows(case)
    load_vault(ModuleConnection(connection), case.context)
    captured = []
    scalar = validation._scalar

    def record(conn, sql, parameters):
        if "jsonb_to_recordset" in sql and "rv.sat_unit s" in sql:
            captured.append((sql, parameters))
        return scalar(conn, sql, parameters)

    monkeypatch.setattr(validation, "_scalar", record)
    connection.execute("SET LOCAL statement_timeout='30s'")
    validation.validate_snapshot(ModuleConnection(connection), case.context)
    sql, parameters = captured[0]
    plan = connection.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + sql,
                              parameters).fetchone()[0]
    parent_scans = [node for node in nodes(plan[0]["Plan"])
                    if node.get("Relation Name") == "sat_crash" and node.get("Alias") == "p"]
    assert parent_scans
    for node in parent_scans:
        condition = node.get("Index Cond", "")
        assert all(name in condition for name in
                   ("batch_id", "source_id", "release_scope", "crash_key"))
        assert node["Actual Rows"] <= 1
        assert node.get("Rows Removed by Filter", 0) == 0
    # Capture the previous join for comparison without executing its unbounded scan.
    prior_join = """LEFT JOIN rv.sat_crash p ON p.batch_id=s.batch_id AND p.source_id=s.source_id
          AND p.release_scope=s.release_scope AND p.crash_key=l.crash_key"""
    start = sql.index("LEFT JOIN LATERAL (\n          SELECT p.*")
    end = sql.index(") p ON true", start) + len(") p ON true")
    prior_sql = sql[:start] + prior_join + sql[end:]
    before_plan = connection.execute("EXPLAIN (FORMAT JSON) " + prior_sql,
                                     parameters).fetchone()[0]
    connection.execute("SAVEPOINT before_canonical")
    load_canonical(ModuleConnection(connection), case.context)
    for kind, expected in (("crash", 1001), ("unit", 2001)):
        assert connection.execute(f"SELECT count(*) FROM canonical.{kind} WHERE batch_id=%s",
                                  (case.batch_id,)).fetchone() == (expected,)
    connection.execute("ROLLBACK TO SAVEPOINT before_canonical")
    for kind in ("crash", "unit"):
        assert connection.execute(f"SELECT count(*) FROM canonical.{kind} WHERE batch_id=%s",
                                  (case.batch_id,)).fetchone() == (0,)
    assert connection.execute("SELECT count(*) FROM rv.sat_unit WHERE batch_id=%s",
                              (case.batch_id,)).fetchone() == (2001,)
    if os.environ.get("AC_EVIDENCE_DIR"):
        path = Path(os.environ["AC_EVIDENCE_DIR"]) / "c09-cold-parent-plan.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"scope": "Synthetic C09 SQL regression, not official build acceptance",
            "crashes": 1001, "units": 2001, "old_plan_executed": False,
            "before_plan": before_plan, "after_plan": plan,
            "executed_as": "arsia_loader", "permanent_statistics_or_grants_changed": False,
            "caller_rollback": "Canonical rows removed; input Satellites retained"}, indent=2) + "\n",
            encoding="utf-8")


def test_existing_parent_with_wrong_native_identity_is_rejected(connection):
    case = C09Case(connection)
    add_rows(case, parents=2)
    connection.execute("UPDATE pg_temp.arsia_i_unit SET crash_key=%s WHERE unit_key=%s",
                       ('["1"]', case.unit_key))
    load_vault(ModuleConnection(connection), case.context)
    with pytest.raises(IntakeError, match="parent is invalid"):
        validation.validate_snapshot(ModuleConnection(connection), case.context)
    assert connection.execute("SELECT count(*) FROM canonical.unit WHERE batch_id=%s",
                              (case.batch_id,)).fetchone() == (0,)
