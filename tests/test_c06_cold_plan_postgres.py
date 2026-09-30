"""C06 selection stays exact on cold Raw statistics and caller-owned transactions."""

from collections import Counter
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from arsia_c.person_checks import SQL_PATH, _run, _stage_selected
from arsia_ingest.runner import ModuleConnection
from test_c03_nsw_postgres import connection, pytestmark


ANALYSIS = {"year_from": 2020, "year_to": 2024}


class RawCase:
    """Synthetic SQL inputs, not an official FrozenManifest or release."""

    def __init__(self, conn):
        self.connection = conn
        self.source = "syn_c06_cold_" + uuid4().hex
        conn.execute("INSERT INTO meta.source(source_id,jurisdiction_code,source_name,publisher) "
                     "VALUES (%s,'VIC','C06 cold-plan test','ARSIA synthetic')", (self.source,))
        self.files = {}
        for role, entity, fields in (
            ("accident", "crash", ["ACCIDENT_NO", "ACCIDENT_DATE", "NO_PERSONS"]),
            ("vehicle", "unit", ["ACCIDENT_NO", "VEHICLE_ID"]),
            ("person", "person_raw", ["ACCIDENT_NO", "PERSON_ID", "VEHICLE_ID"]),
        ):
            rid = self.source + "_" + role
            conn.execute("INSERT INTO meta.resource(resource_id,source_id,resource_role,entity_kind) "
                         "VALUES (%s,%s,%s,%s)", (rid, self.source, role, entity))
            self.files[role] = {"role": role, "source_id": self.source, "resource_id": rid,
                "file_sha256": "a" * 64, "parser_version": "csv-native-v1", "raw_count": 0,
                "locator_version": "csv-logical-v1", "format": "csv", "entity_kind": entity,
                "header": fields}

    def add(self, role, payload, *, digest=None, parser=None):
        file = self.files[role]
        file["raw_count"] += 1
        self.connection.execute("""INSERT INTO raw.record
            (raw_record_id,resource_id,source_id,file_sha256,parser_version,row_locator,payload)
            VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)""", (uuid4(), file["resource_id"], self.source,
                digest or file["file_sha256"], parser or file["parser_version"],
                "csv:" + str(file["raw_count"]), json.dumps(payload)))
        if digest or parser:
            file["raw_count"] -= 1

    def request(self, **rules):
        return {"files": list(self.files.values()), "analysis": ANALYSIS,
                "blank_vehicle_allowed": True, "count_scope_confirmed": True, **rules}

    def run(self, **rules):
        _stage_selected(ModuleConnection(self.connection), list(self.files.values()))
        return self.connection.execute(SQL_PATH.read_text(encoding="utf-8"),
                                       (json.dumps(self.request(**rules)),)).fetchall()


def previous_selection(sql):
    start = sql.index("selected_raw AS")
    end = sql.index("\nnative AS", start)
    return (sql[:start] + """selected_raw AS MATERIALIZED (
    SELECT f.role, r.*
    FROM files f
    JOIN raw.record r
      ON r.source_id = f.source_id AND r.resource_id = f.resource_id
     AND r.file_sha256 = f.file_sha256 AND r.parser_version = f.parser_version
),""" + sql[end:]).replace("native AS NOT MATERIALIZED (", "native AS (")


def nodes(plan):
    yield plan
    for child in plan.get("Plans", []):
        yield from nodes(child)


@pytest.mark.parametrize("restricted", [False, True])
def test_selected_file_plan_preserves_native_diagnostics(connection, restricted):
    case = RawCase(connection)
    for key, count, date in [("A", "2", "2020-01-01"), ("D", "1", "2020-01-01"),
                             ("D", "1", "2020-01-01"), ("M", "3", "2019-01-01"),
                             ("I", "bad", "bad"), (None, None, None)]:
        case.add("accident", {"ACCIDENT_NO": key, "NO_PERSONS": count, "ACCIDENT_DATE": date})
    for key, vehicle in [("A", "01"), ("D", "01"), ("D", "01"), ("M", "01"), ("I", " ")]:
        case.add("vehicle", {"ACCIDENT_NO": key, "VEHICLE_ID": vehicle})
    for key, person, vehicle in [("A", "1", "01"), ("A", "1", "01"), ("D", "1", "01"),
                                  ("M", "1", "missing"), ("missing", "1", "01"),
                                  ("I", None, " "), (None, "1", None)]:
        case.add("person", {"ACCIDENT_NO": key, "PERSON_ID": person, "VEHICLE_ID": vehicle})
    case.add("person", {"ACCIDENT_NO": "not-selected", "PERSON_ID": "x"}, digest="b" * 64)
    case.add("person", {"ACCIDENT_NO": "not-selected", "PERSON_ID": "y"}, parser="csv-native-v2")
    rules = {"restricted_diagnostics": restricted}
    actual = case.run(**rules)
    previous = connection.execute(previous_selection(SQL_PATH.read_text(encoding="utf-8")),
                                  (json.dumps(case.request(**rules)),)).fetchall()
    assert actual == previous
    assert Counter(row[0]["kind"] for row in actual) == {"file": 3, "accident": 6, "vehicle": 5, "person": 7}
    issues = {issue for row, in actual for issue in row["issues"]}
    assert {"invalid_person_key", "duplicate_person_key", "ambiguous_accident_parent",
            "missing_accident_parent", "ambiguous_vehicle_reference", "unmatched_nonblank_vehicle_ref",
            "invalid_vehicle_reference", "invalid_person_count", "invalid_accident_date"} <= issues
    mismatch = next(row for row, in actual if row["kind"] == "accident" and row["accident_no"] == "M")
    assert mismatch["diagnostic_count_delta"] == -2 and mismatch["in_scope"] is False
    assert len(mismatch["person_references"]) == len(mismatch["vehicle_references"]) == 1


def test_scaled_checks_bound_group_scans_repeat_and_obey_rollback(connection):
    connection.execute("SAVEPOINT before_c06_input")
    case = RawCase(connection)
    counts = {"accident": 1000, "vehicle": 2000, "person": 3000}
    for role, copies in (("accident", 1), ("vehicle", 2), ("person", 3)):
        file = case.files[role]
        connection.execute("""INSERT INTO raw.record
            (raw_record_id,resource_id,source_id,file_sha256,parser_version,row_locator,payload)
            SELECT gen_random_uuid(),%s,%s,%s,%s,'csv:'||((n-1)*%s+i)::text,
              jsonb_build_object('ACCIDENT_NO',n::text) || CASE %s
                WHEN 'accident' THEN jsonb_build_object('ACCIDENT_DATE','2020-01-01','NO_PERSONS','3')
                WHEN 'vehicle' THEN jsonb_build_object('VEHICLE_ID',i::text)
                ELSE jsonb_build_object('PERSON_ID',i::text,'VEHICLE_ID',((i-1) %% 2+1)::text) END
            FROM generate_series(1,1000) n CROSS JOIN generate_series(1,%s) i""",
            (file["resource_id"], case.source, file["file_sha256"], file["parser_version"], copies, role, copies))
        file["raw_count"] = counts[role]
    connection.execute("SET LOCAL statement_timeout='30s'")
    _stage_selected(ModuleConnection(connection), list(case.files.values()))
    statement = SQL_PATH.read_text(encoding="utf-8")
    plan = connection.execute("EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement,
                              (json.dumps(case.request()),)).fetchone()[0]
    if os.environ.get("AC_EVIDENCE_DIR"):
        path = Path(os.environ["AC_EVIDENCE_DIR"]) / "c06-cold-plan.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"scope": "Synthetic SQL regression; not official build acceptance",
            "rows": counts, "executed_as": "arsia_loader", "caller_rollback": "not checked yet",
            "permanent_statistics_or_grants_changed": False, "plan": plan}, indent=2) + "\n", encoding="utf-8")
    group_names = {"accident_groups", "vehicle_groups", "person_counts", "mismatch_references"}
    group_scans = [node for node in nodes(plan[0]["Plan"]) if node.get("CTE Name") in group_names]
    assert group_scans
    assert all(node["Actual Loops"] <= 3 for node in group_scans)
    first = _run(ModuleConnection(connection), list(case.files.values()), ANALYSIS, synthetic=True)
    second = _run(ModuleConnection(connection), list(case.files.values()), ANALYSIS, synthetic=True)
    assert first == second
    assert first["status"] == "pass" and first["evaluated_count"] == 6000
    assert first["person_count_comparisons"] == 1000
    assert first["declared_count_absolute_delta"] == 0
    assert first["vehicle_reference_counts"] == {"matched": 3000}
    assert connection.info.transaction_status.name == "INTRANS" and not connection.closed
    connection.execute("ROLLBACK TO SAVEPOINT before_c06_input")
    assert connection.execute("SELECT to_regclass('pg_temp.c06_selected_raw')").fetchone() == (None,)
    assert connection.execute("SELECT count(*) FROM raw.record WHERE source_id=%s", (case.source,)).fetchone() == (0,)
    assert connection.execute("SELECT count(*) FROM meta.source WHERE source_id=%s", (case.source,)).fetchone() == (0,)
    if os.environ.get("AC_EVIDENCE_DIR"):
        path.write_text(json.dumps({"scope": "Synthetic SQL regression; not official build acceptance",
            "rows": counts, "executed_as": "arsia_loader", "caller_rollback": True,
            "permanent_statistics_or_grants_changed": False, "plan": plan}, indent=2) + "\n", encoding="utf-8")
