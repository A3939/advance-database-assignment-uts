"""Capture D11 reports from one real E-published S0 batch in private PG16."""

from decimal import Decimal
import json
import os
from pathlib import Path
import sys

import psycopg

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from arsia_d05 import TrendRequest, query_trend
from arsia_d06 import SeverityRequest, query_severity
from arsia_d07 import MapRequest, query_map
from arsia_ingest.build import s0_request
from arsia_ingest.pipeline import prepare
from arsia_ingest.runner import ModuleConnection, run_build
from test_full_build_postgres import ROOT, connect, deployed, private_database


def serial(value):
    return str(value)


def test_d11_three_reports_use_one_successful_published_batch(
    tmp_path, deployed, private_database
):
    evidence_root = Path(os.environ["AC_EVIDENCE_DIR"]).parent
    prepared = prepare(
        ROOT / "tests/fixtures/s0/config.json",
        evidence_root / "d11-intake",
    )
    request = s0_request(
        connect=connect,
        project_root=ROOT,
        prepared_run=prepared["run_dir"],
        evidence_root=evidence_root / "d11-builds",
    )
    build = run_build(**request).as_dict()
    assert build["result"] == "succeeded", build
    batch_id = build["batch_id"]

    with connect() as loader:
        assert loader.execute(
            "SELECT status FROM meta.batch WHERE batch_id=%s", (batch_id,)
        ).fetchone() == ("succeeded",)
        assert loader.execute(
            "SELECT batch_id::text FROM meta.current_release "
            "WHERE dataset_kind='synthetic'"
        ).fetchone() == (batch_id,)
        counts = loader.execute(
            """SELECT count(*),
                      count(*) FILTER (WHERE fatal_crash_eligible AND is_fatal_crash),
                      sum(fatality_count) FILTER (WHERE fatality_eligible),
                      sum(casualty_count) FILTER (WHERE casualty_eligible),
                      count(*) FILTER (WHERE map_eligible)
                 FROM dw.fact_crash WHERE batch_id=%s""",
            (batch_id,),
        ).fetchone()

    with psycopg.connect(deployed) as reader:
        scoped = ModuleConnection(reader)
        trend_year = query_trend(
            scoped, TrendRequest("synthetic", batch_id, grain="year")
        )
        trend_month = query_trend(
            scoped, TrendRequest("synthetic", batch_id, grain="month")
        )
        severity = query_severity(
            scoped, SeverityRequest("synthetic", batch_id)
        )
        mapped = query_map(scoped, MapRequest("synthetic", batch_id))

    assert counts == (6, 2, 3, 7, 4)
    assert len(trend_year) == 15
    assert len(trend_month) == 180
    assert len(severity) == 6
    assert len(mapped.points) == 4
    assert mapped.coverage["point_count"] == 4
    assert mapped.coverage["crash_count"] == 6
    assert mapped.coverage["coverage_percentage"] == Decimal("66.67")
    assert sum(row["crash_count"] for row in trend_year) == 6
    assert sum((row["fatal_crash_count"] or 0) for row in trend_year) == 2
    assert sum((row["fatality_count"] or 0) for row in trend_year) == 3
    assert sum((row["casualty_count"] or 0) for row in trend_year) == 7

    receipt = {
        "evidence_version": "d11-s0-three-reports-v1",
        "status": "passed",
        "scope": "Private synthetic S0 publication through real B10 and E03/E06; no shared/public release.",
        "integration_commit": os.environ.get("D11_INTEGRATION_COMMIT"),
        "batch": {
            "dataset_kind": "synthetic",
            "batch_id": batch_id,
            "status": "succeeded",
            "current_release": True,
            "input_fingerprint": build["input_fingerprint"],
            "raw_rows": prepared["raw_count"],
            "crashes": counts[0],
            "fatal_crashes": counts[1],
            "fatalities": counts[2],
            "casualties": counts[3],
            "map_points": counts[4],
        },
        "trend": {
            "query": "published.d05_trend",
            "annual_rows": trend_year,
            "monthly_rows": trend_month,
        },
        "severity": {
            "query": "published.d06_severity",
            "rows": severity,
        },
        "map": {
            "query": "published.d07_map",
            "coverage": mapped.coverage,
            "points": mapped.points,
        },
        "limits": [
            "Synthetic fixtures only; results are not official road-safety statistics.",
            "All three reports are pinned to the same successful batch_id.",
            "Empty covered periods keep zero crash_count while unknown measures remain null.",
            "Severity definitions remain source-specific and must not be pooled across sources.",
            "Two crashes are unmapped; absence from the map is not absence from crash totals.",
            "Independent E07 acceptance remains separate.",
        ],
    }
    output = evidence_root / "d11-s0-query-results.json"
    output.write_text(
        json.dumps(receipt, indent=2, default=serial) + "\n",
        encoding="utf-8",
    )
