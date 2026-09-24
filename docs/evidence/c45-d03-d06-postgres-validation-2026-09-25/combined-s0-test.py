"""Combined C04/C05 -> D03-D06 S0 acceptance on PostgreSQL 16."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from arsia_c.canonical import load_canonical
from arsia_c.projections import nsw, qld, vic
from arsia_d03 import runner_callback as load_dw
from arsia_d04 import runner_callback as run_qa06
from arsia_d05 import TrendRequest, query_trend
from arsia_d06 import SeverityRequest, query_severity
from arsia_ingest.pipeline import prepare
from arsia_ingest.raw_load import load_prepared
from arsia_ingest.runner import ModuleConnection, RunEvidence
from arsia_ingest.vault_load import load_vault
from d_acceptance_support import connection
from test_c03_nsw_projection import component_manifest
from test_c03_nsw_postgres import FakeContext


pytestmark = pytest.mark.skipif(
    "ARSIA_TEST_DSN" not in os.environ,
    reason="Combined C/D acceptance requires PostgreSQL 16",
)


def _stage(context, name):
    return SimpleNamespace(
        batch_id=context.batch_id,
        dataset_kind="synthetic",
        manifest=context.manifest,
        evidence=context.evidence.for_stage(name),
    )


def test_three_state_canonical_to_all_role_d_outputs(connection, tmp_path):
    root = Path(__file__).resolve().parents[1]
    manifest = component_manifest()
    context = FakeContext(manifest)
    context.dataset_kind = "synthetic"
    context.evidence = RunEvidence(tmp_path / "evidence")

    intake = prepare(root / "tests/fixtures/s0/config.json", tmp_path / "intake")
    assert load_prepared(
        connection, intake["run_dir"], manifest["sources"]
    ).raw_count == 19
    connection.execute(
        """INSERT INTO meta.batch(
               batch_id,dataset_kind,input_fingerprint,manifest
           ) VALUES (%s,'synthetic',%s,%s::jsonb)""",
        (context.batch_id, "c" * 64, json.dumps(manifest)),
    )

    shared = ModuleConnection(connection)
    for projection in (nsw, vic, qld):
        projection.project(shared, context)
    assert connection.execute(
        "SELECT count(*) FROM pg_temp.arsia_i_crash"
    ).fetchone() == (6,)

    load_vault(shared, context)
    load_canonical(shared, context)
    assert connection.execute(
        """SELECT count(*),sum(fatality_count),sum(casualty_count),
                  count(*) FILTER (WHERE map_eligible)
             FROM canonical.crash WHERE batch_id=%s""",
        (context.batch_id,),
    ).fetchone() == (6, 3, 7, 4)
    assert connection.execute(
        "SELECT count(*) FROM canonical.unit WHERE batch_id=%s",
        (context.batch_id,),
    ).fetchone() == (6,)

    assert load_dw(shared, _stage(context, "dw")) == {
        "dim_source": 3,
        "dim_month": 60,
        "dim_severity": 12,
        "fact_crash": 6,
    }
    assert connection.execute(
        "SELECT count(*) FROM dw.fact_crash WHERE batch_id=%s",
        (context.batch_id,),
    ).fetchone() == (6,)

    assert run_qa06(shared, _stage(context, "qa_d")) == {
        "qa06_object_count": 15,
        "qa06_pass_count": 15,
        "qa06_block_count": 0,
    }
    assert connection.execute(
        """SELECT count(*) FROM qa.check_result
            WHERE batch_id=%s AND rule_id='QA06_RECONCILIATION'
              AND result='pass'""",
        (context.batch_id,),
    ).fetchone() == (16,)

    connection.execute(
        """UPDATE meta.batch SET status='succeeded',finished_at=now()
            WHERE batch_id=%s""",
        (context.batch_id,),
    )
    trends = query_trend(shared, TrendRequest("synthetic", context.batch_id))
    assert len(trends) == 15
    totals = {
        source: sum(row["crash_count"] for row in trends if row["source_id"] == source)
        for source in ("syn_nsw", "syn_vic", "syn_qld")
    }
    assert totals == {"syn_nsw": 2, "syn_vic": 2, "syn_qld": 2}

    severities = query_severity(
        shared, SeverityRequest("synthetic", context.batch_id)
    )
    assert len(severities) == 6
    assert {
        (row["source_id"], row["severity_code"], row["crash_count"])
        for row in severities
    } == {
        ("syn_nsw", "F", 1),
        ("syn_nsw", "__MISSING__", 1),
        ("syn_vic", "F", 1),
        ("syn_vic", "I", 1),
        ("syn_qld", "I", 1),
        ("syn_qld", "N", 1),
    }

    assert connection.execute(
        "SELECT count(*) FROM meta.current_release WHERE batch_id=%s",
        (context.batch_id,),
    ).fetchone() == (0,)
