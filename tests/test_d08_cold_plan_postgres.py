"""D08 avoids repeated parent scans on cold synthetic Canonical and DW rows."""

import json
import os
from pathlib import Path
import time

import pytest

from arsia_c.canonical import load_canonical
from arsia_d03.facts import FACT_INSERT_SQL
from arsia_d08 import UnitRequest, query_units, install_sql
from arsia_ingest.runner import ModuleConnection
from arsia_ingest.vault_load import load_vault
from d_acceptance_support import connection
from test_analysis_postgres import deployment
from test_c09_postgres import C09Case
from test_c09_cold_plan_postgres import add_rows


pytestmark = pytest.mark.skipif("ARSIA_TEST_DSN" not in os.environ,
                              reason="Use the private PostgreSQL 16 verifier")

ORIGINAL_SQL = """
SELECT p_dataset_kind,p_batch_id,unit.source_id,source.source_name,source.jurisdiction_code,
       unit.statistical_scope,unit.unit_type_code,count(*)::bigint
FROM canonical.unit AS unit
JOIN dw.fact_crash AS parent
  ON parent.batch_id=unit.batch_id AND parent.source_id=unit.source_id
 AND parent.release_scope=unit.release_scope AND parent.crash_key=unit.crash_key
 AND parent.occurrence_year BETWEEN v_year_from AND v_year_to
JOIN dw.dim_source AS source ON source.batch_id=unit.batch_id AND source.source_id=unit.source_id
WHERE unit.batch_id=p_batch_id AND unit.count_eligible
 AND (p_source_ids IS NULL OR unit.source_id=ANY(p_source_ids))
 AND (p_months IS NULL OR (parent.month_id IS NOT NULL AND (parent.month_id % 100)=ANY(p_months)))
GROUP BY unit.source_id,source.source_name,source.jurisdiction_code,unit.statistical_scope,unit.unit_type_code
ORDER BY unit.source_id,unit.statistical_scope,unit.unit_type_code
"""


def nodes(plan):
    yield plan
    for child in plan.get("Plans", []):
        yield from nodes(child)


def underlying_sql(batch, source, *, year_from=2020, year_to=2024, months=None, original=False):
    statement = (ORIGINAL_SQL if original else install_sql().split("AS $d08_counts$")[1]
                 .split("    RETURN QUERY\n", 1)[1].split("\nEND;", 1)[0])
    values = {"p_dataset_kind": "'synthetic'::text", "p_batch_id": f"'{batch}'::uuid",
              "p_source_ids": f"ARRAY['{source}']::text[]", "v_year_from": str(year_from),
              "v_year_to": str(year_to), "p_months": "NULL::integer[]" if months is None
              else "ARRAY[" + ",".join(map(str, months)) + "]::integer[]"}
    for token, value in values.items():
        statement = statement.replace(token, value)
    return statement


def save_evidence(parents, receipt):
    if os.environ.get("AC_EVIDENCE_DIR"):
        path = Path(os.environ["AC_EVIDENCE_DIR"]) / f"d08-cold-plan-{parents}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")


def seed(connection, parents):
    # Reuse typed synthetic projection rows. This fixture is not a frozen official build.
    case = C09Case(connection)
    add_rows(case, parents=parents)
    load_vault(ModuleConnection(connection), case.context)
    load_canonical(ModuleConnection(connection), case.context)
    connection.execute("""INSERT INTO dw.dim_source
        SELECT %s,source_id,source_name,jurisdiction_code,'Synthetic cold-plan fixture',%s
        FROM meta.source WHERE source_id=%s""", (case.batch_id, case.release_scope, case.source_id))
    connection.execute("""INSERT INTO dw.dim_month
        SELECT DISTINCT occurrence_year*100+occurrence_month,occurrence_year,occurrence_month
        FROM canonical.crash WHERE batch_id=%s AND occurrence_month IS NOT NULL
        ON CONFLICT DO NOTHING""", (case.batch_id,))
    connection.execute("""INSERT INTO dw.dim_severity
        SELECT DISTINCT batch_id,source_id,severity_code,severity_code,severity_definition_version,
                        'Synthetic cold-plan fixture'
        FROM canonical.crash WHERE batch_id=%s""", (case.batch_id,))
    connection.execute(FACT_INSERT_SQL, (case.batch_id,))
    connection.execute("UPDATE meta.batch SET status='succeeded',finished_at=clock_timestamp() WHERE batch_id=%s",
                       (case.batch_id,))
    return case


@pytest.mark.parametrize("parents", [1000, 5000])
def test_cold_parent_membership_reads_each_input_once_and_preserves_counts(connection, parents):
    case = seed(connection, parents)
    connection.execute("SET LOCAL statement_timeout='30s'")
    statement = underlying_sql(case.batch_id, case.source_id)
    original = underlying_sql(case.batch_id, case.source_id, original=True)
    before = connection.execute("EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + original).fetchone()[0]
    after = connection.execute("EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + statement).fetchone()[0]
    receipt = {"scope": "Synthetic query-plan regression; not official acceptance",
               "parents": parents + 1, "units": parents * 2 + 1,
               "before_plan": before, "after_plan": after}
    save_evidence(parents, receipt)
    plan_nodes = list(nodes(after[0]["Plan"]))
    for relation, count in (("fact_crash", parents + 1), ("unit", parents * 2 + 1)):
        scans = [n for n in plan_nodes if n.get("Relation Name") == relation]
        assert scans and all(n["Actual Loops"] == 1 for n in scans)
        assert sum(n["Actual Rows"] for n in scans) == count
    # A materialized parent scan repeated per unit is quadratic even if its base scan ran once.
    assert all(n.get("Rows Removed by Join Filter", 0) * n["Actual Loops"] <= 4 * parents
               for n in plan_nodes)
    expected = connection.execute(original).fetchall()
    assert connection.execute(statement).fetchall() == expected
    assert sum(row[-1] for row in expected) == 2 * parents + 1
    counts_before = {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                     for table in ("raw.record", "canonical.crash", "canonical.unit", "dw.fact_crash")}
    started = time.monotonic()
    rows = query_units(ModuleConnection(connection), UnitRequest(
        "synthetic", case.batch_id, source_ids=(case.source_id,), year_from=2020, year_to=2024))
    elapsed = time.monotonic() - started
    assert sum(row["unit_count"] for row in rows) == 2 * parents + 1
    assert {row["source_id"] for row in rows} == {case.source_id}
    for filters in ({"year_from": 2024, "year_to": 2024}, {"months": (2,)}):
        assert connection.execute(underlying_sql(case.batch_id, case.source_id, **filters)).fetchall() == \
            connection.execute(underlying_sql(case.batch_id, case.source_id, original=True, **filters)).fetchall()
        assert query_units(ModuleConnection(connection), UnitRequest(
            "synthetic", case.batch_id, source_ids=(case.source_id,),
            **({"year_from": 2020, "year_to": 2024} | filters))) == ()
    january = query_units(ModuleConnection(connection), UnitRequest(
        "synthetic", case.batch_id, source_ids=(case.source_id,),
        year_from=2020, year_to=2024, months=(1,)))
    assert january == rows
    assert connection.info.transaction_status.name == "INTRANS" and not connection.closed
    assert counts_before == {table: connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                             for table in counts_before}
    receipt.update(function_seconds=elapsed, read_only_counts_unchanged=True,
                   permanent_statistics_or_grants_changed=False)
    save_evidence(parents, receipt)
