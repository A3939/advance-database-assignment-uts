"""Exercise the actual PostgreSQL plan with realistic key cardinality."""
from arsia_pipeline import query
from test_backend import isolated_database, client
from test_autonomous_backend import published, row


def test_unit_counts_at_high_cardinality_obey_selected_crash_interval(client):
    source = "many_unique_unit_parents"
    crashes = [row(source, str(i), month=1+i%2) for i in range(10000)]
    units = [row(source, f"{i}-{j}", role="unit", grain="unit", unit_type="car",
                 crash_id=crash["record_id"], relations={"crash": crash["record_id"]})
             for i, crash in enumerate(crashes) for j in range(2)]
    job, _ = published(client, source, crashes, units=units)
    result = query.query(source, job["release_id"], "2024-01-01", "2024-01-31")
    assert result["summary"]["crash_count"] == 5000
    assert result["units"]["rows"] == [{"unit_type": "car", "count": 10000}]
    reduced = client.get('/query', params={"source_id":source,"release_id":str(job["release_id"]),
        "from":"2024-01-01","to":"2024-01-31","include_units":"false"})
    assert reduced.status_code == 200
    assert reduced.json()["summary"] == result["summary"]
    assert reduced.json()["units"]["status"] == "not_requested"
    assert client.get('/query',params={"source_id":source,"release_id":str(job["release_id"]),
        "from":"2024-01-01","to":"2024-01-31","include_units":"invalid"}).status_code == 422
