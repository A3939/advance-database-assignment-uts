"""B's official report guards; database behaviour is tested separately."""

from uuid import UUID

import pytest

from arsia_ingest import official_reader as reader
from arsia_ingest.models import IntakeError


BATCH = UUID("12345678-1234-5678-9234-567812345678")
SOURCES = ("official_nsw", "official_vic", "official_qld")


@pytest.fixture
def delegated(monkeypatch):
    connection = object()
    calls = []
    rows = {report: ({"marker": report},) for report in ("trend", "severity", "units")}

    def callback(report):
        def query(actual_connection, request):
            assert actual_connection is connection
            request.parameters()
            calls.append((report, request))
            return rows[report]
        return query

    for report in rows:
        monkeypatch.setattr(reader, "query_" + report, callback(report))
    return connection, calls, rows


@pytest.mark.parametrize("source", SOURCES)
def test_disabled_maps_are_unavailable_not_empty_reports(delegated, source):
    connection, calls, _ = delegated
    result = reader.query_official(connection, batch_id=BATCH, source_id=source, report="map")
    assert result["status"] == "unavailable"
    assert result["rows"] is None
    assert result["reason"]
    assert [name for name, _ in calls] == ["trend"]
    assert calls[0][1].source_ids == (source,)


@pytest.mark.parametrize("source", ("official_vic", "official_qld"))
def test_restricted_units_are_unavailable_not_zero(delegated, source):
    connection, calls, _ = delegated
    result = reader.query_official(connection, batch_id=BATCH, source_id=source, report="units")
    assert result["status"] == "unavailable"
    assert result["rows"] is None
    assert result["reason"]
    assert [name for name, _ in calls] == ["trend"]


@pytest.mark.parametrize("source", SOURCES)
@pytest.mark.parametrize("report", ("trend", "severity"))
def test_available_reports_keep_source_filters_and_fixed_batch(delegated, source, report):
    connection, calls, rows = delegated
    result = reader.query_official(
        connection, batch_id=BATCH, source_id=source, report=report,
        year_from=2021, year_to=2023, months=(2, 7), grain="month",
    )
    assert result["status"] == "available"
    assert result["rows"] is rows[report]
    assert result["reason"] is None
    assert result["dataset_kind"] == "official"
    assert result["batch_id"] == str(BATCH)
    assert result["source_id"] == source
    assert result["comparison_scope"]
    assert calls[0][1].grain == "month"
    assert [name for name, _ in calls] == (["trend"] if report == "trend" else ["trend", report])
    for _, request in calls:
        assert request.dataset_kind == "official"
        assert request.batch_id == BATCH
        assert request.source_ids == (source,)
        assert (request.year_from, request.year_to, request.months) == (2021, 2023, (2, 7))


def test_only_nsw_units_reach_d08(delegated):
    connection, calls, rows = delegated
    result = reader.query_official(connection, batch_id=BATCH, source_id="official_nsw", report="units")
    assert result["status"] == "available"
    assert result["rows"] is rows["units"]
    assert [name for name, _ in calls] == ["trend", "units"]
    assert calls[-1][1].source_ids == ("official_nsw",)


@pytest.mark.parametrize("source", (None, "", "syn_nsw", "official_sa", "all", SOURCES, list(SOURCES)))
def test_implicit_or_pooled_sources_stop_before_sql(delegated, source):
    connection, calls, _ = delegated
    with pytest.raises(IntakeError) as error:
        reader.query_official(connection, batch_id=BATCH, source_id=source, report="trend")
    assert error.value.code == "OFFICIAL_READER"
    assert calls == []


@pytest.mark.parametrize("report", (None, "people", "interstate_total"))
def test_unknown_reports_stop_before_sql(delegated, report):
    connection, calls, _ = delegated
    with pytest.raises(IntakeError) as error:
        reader.query_official(connection, batch_id=BATCH, source_id="official_nsw", report=report)
    assert error.value.code == "OFFICIAL_READER"
    assert calls == []


@pytest.mark.parametrize("report", ("trend", "severity", "map", "units"))
@pytest.mark.parametrize("failure", ("unknown batch", "failed batch", "wrong dataset kind", "source not enabled"))
def test_database_validation_errors_propagate_for_every_report(monkeypatch, delegated, report, failure):
    connection, calls, _ = delegated
    error = RuntimeError(failure)

    def reject(actual_connection, request):
        assert actual_connection is connection
        assert request.source_ids == ("official_vic",)
        raise error

    monkeypatch.setattr(reader, "query_trend", reject)
    with pytest.raises(RuntimeError) as caught:
        reader.query_official(connection, batch_id=BATCH, source_id="official_vic", report=report)
    assert caught.value is error
    assert calls == []
