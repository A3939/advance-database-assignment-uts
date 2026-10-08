"""Actual PostgreSQL grid queries report omissions independently of their limit."""
from arsia_pipeline import query, store, worker
from test_backend import isolated_database, client, queued, claim_specific
from test_autonomous_backend import candidate, row


def test_grid_reports_truncation_and_unlocated_records(client):
    source = "bounded_grid"
    rows = [row(source, str(i), geography_status="available", coordinates=[115+(i % 100)/10, -25-(i // 100)/10])
            for i in range(2001)]
    rows.append(row(source, "missing", geography_status="unsupported", coordinates=None))
    job = claim_specific(queued(client)["id"])
    result = candidate(job, source, rows)
    result["capabilities"]["geography"] = True
    worker.publish(job, result, lambda: None)
    release = store.get_job(job["id"])["release_id"]
    output = query.query(source, release, "2024-01-01", "2024-01-31")
    grid = output["geography"]
    assert output["summary"]["crash_count"] == 2002
    assert grid["located_crash_count"] == 2001 and grid["unlocated_crash_count"] == 1
    assert grid["total_cells"] == 2001 and grid["returned_cells"] == 2000 and grid["truncated"] is True
    assert len(grid["cells"]) == 2000 and sum(c["crash_count"] for c in grid["cells"]) == 2000
    assert all(set(c) == {"longitude", "latitude", "crash_count"} for c in grid["cells"])
