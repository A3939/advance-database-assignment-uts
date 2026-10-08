"""Keep unsupported source facts distinct from unknown values and empty queries."""
import pytest

from arsia_pipeline import query
from test_backend import isolated_database, client
from test_autonomous_backend import published, row


def source(mapping, grain="crash"):
    return {"source_contract": {"contract_version": "canonical-v2", "resources": [
        {"grain": grain, "mapping": mapping}]}, "summary": {}}


@pytest.mark.parametrize('level,registered', [('manual_reviewed', False), ('fixed_native', False),
    ('legacy_unclassified', False), ('official_admitted', True)])
def test_source_names_do_not_grant_registry_authority(level, registered):
    result = {'summary': {}, 'publication_gate': {'version': 'publication-policy-v1', 'admission_level': level}}
    row = {'job_id': 'test', 'result': result, 'source_version_id': 'source', 'adapter_version_id': 'adapter'}
    status = query.metadata('official_nsw', 'batch', row)['publication_status']
    assert status['admission_level'] == level
    assert status['official_registration'] is registered
    row['adapter_version_id'] = None
    assert query.metadata('official_nsw', 'batch', row)['publication_status']['official_registration'] is False


def test_mapping_absence_unknown_and_known_zero_are_distinct():
    result = source({"severity": {"categories": {"U": {"is_fatal_crash": None}}},
                     "fatalities": {"field": "DEATHS"}})
    result["source_contract"]["definitions"] = {"casualties": "Casualties are available"}
    base = {"summary": dict(crash_count=0, fatal_crash_count=None, fatalities=None, casualties=None)}
    assert query.query_result(base, result, "available", None)["metric_availability"] == {
        "crash_count": "available", "fatal_crash_count": "unknown",
        "fatalities": "unknown", "casualties": "unsupported"}


@pytest.mark.parametrize("availability", ["no_results", "unsupported"])
def test_selection_status_applies_to_all_metrics(availability):
    base = {"summary": dict.fromkeys(query.METRICS)}
    assert set(query.query_result(base, source({}), availability, None)["metric_availability"].values()) == {availability}


def test_observations_use_declared_metrics_and_aggregation_policy():
    result = source({"metrics": {"fatalities": {"field": "COUNT"}}}, "observation")
    base = {"summary": dict.fromkeys(query.METRICS)}
    assert query.query_result(base, result, "available", None)["metric_availability"] == {
        "crash_count": "unsupported", "fatal_crash_count": "unsupported",
        "fatalities": "unknown", "casualties": "unsupported"}
    assert set(query.query_result(base, result, "available", None, aggregation_supported=False)["metric_availability"].values()) == {"unsupported"}


def test_actual_published_query_preserves_unsupported_and_empty_interval(client):
    source_id = "availability_boundary"
    job, _ = published(client, source_id, [row(source_id, "one", fatalities=None, casualties=None)])
    current = query.query(source_id, job["release_id"], "2024-01-01", "2024-01-31")
    assert current["summary"]["fatalities"] is None
    assert current["metric_availability"] == {"crash_count": "available", "fatal_crash_count": "available",
                                               "fatalities": "unsupported", "casualties": "unsupported"}
    empty = query.query(source_id, job["release_id"], "2024-02-01", "2024-02-29")
    # This fixture proves an observed January row, not complete annual coverage.
    # The paired complete-calendar fixture in test_unified_publication proves
    # February zero only when an independent completeness receipt is present.
    assert empty["coverage"]["complete"] is False
    assert empty["summary"]["crash_count"] is None
    assert empty["availability"] == "no_results"
    assert empty["metric_availability"]["crash_count"] == "no_results"
    outside = query.query(source_id, job["release_id"], "2025-01-01", "2025-01-31")
    assert set(outside["metric_availability"].values()) == {"no_results"}
