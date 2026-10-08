"""Provider-key normalization, separate from official semantic admission."""
import pytest
from arsia_pipeline.errors import NeedsInput, ValidationFailure
from arsia_pipeline.source_identity import url_identity, canonical_source_identity


def admitted(url):
    return {"admission":{"status":"admitted", "evidence":{"source_identity":[{"url":url,"sha256":"verified-by-upstream-QA"}]}}}


@pytest.mark.parametrize("url", [
    "https://www.data.act.gov.au/Transport/ACT-Road-Crash-Data/6jn4-m8rx",
    "https://www.data.act.gov.au/api/views/6jn4-m8rx.json",
    "https://data.act.gov.au/resource/6jn4-m8rx.csv?$limit=30000",
])
def test_socrata_identity_independent_of_display_path_or_format(url):
    assert url_identity(url) == {"kind":"socrata","host":"data.act.gov.au","dataset":"6jn4-m8rx"}


def test_same_official_dataset_different_model_slug_has_same_identity():
    proof = admitted("https://www.data.act.gov.au/api/views/6jn4-m8rx.json")
    one = {"source":{"source_id":"act_crashes","dataset_url":"https://www.data.act.gov.au/Transport/ACT-Road-Crash-Data/6jn4-m8rx"}}
    two = {"source":{"source_id":"act_road_data","dataset_url":"https://data.act.gov.au/resource/6jn4-m8rx.csv"}}
    assert canonical_source_identity(proof,one) == canonical_source_identity(proof,two)


def test_arcgis_layer_query_and_trailing_slash_do_not_make_new_identity():
    one = url_identity("https://data.stategrowth.tas.gov.au/ags/rest/services/PUBLIC/CDM_CRASH/FeatureServer/0?f=json")
    two = url_identity("https://data.stategrowth.tas.gov.au/ags/rest/services/PUBLIC/CDM_CRASH/FeatureServer/0/")
    assert one == two and one["kind"] == "arcgis_layer"
    assert url_identity("https://data.stategrowth.tas.gov.au/ags/rest/services/PUBLIC/CDM_CRASH/FeatureServer/1") != one


def test_ckan_package_show_and_specific_dataset_are_same_key():
    one = url_identity("https://data.sa.gov.au/data/api/3/action/package_show?id=road-crash-data")
    two = url_identity("https://data.sa.gov.au/data/dataset/road-crash-data")
    assert one == two and one["kind"] == "ckan"


def test_different_dataset_or_unproved_uri_requires_correction():
    proof = admitted("https://www.data.act.gov.au/api/views/6jn4-m8rx.json")
    with pytest.raises(NeedsInput, match="does not match"):
        canonical_source_identity(proof, {"source":{"dataset_url":"https://www.data.act.gov.au/api/views/abcd-1234.json"}})
    with pytest.raises(NeedsInput, match="specific"):
        canonical_source_identity(proof, {"source":{"dataset_url":"https://www.data.act.gov.au/"}})


def test_private_or_nonofficial_urls_cannot_claim_official_dataset_key():
    assert url_identity("https://evil.example/6jn4-m8rx") is None
    assert url_identity("https://user:password@data.act.gov.au/6jn4-m8rx") is None
    with pytest.raises(ValidationFailure):
        canonical_source_identity({"admission":{"status":"sample_only"}}, {})


def test_provider_context_is_part_of_identity():
    ckan = url_identity('https://data.example.gov.au/dataset/abcd-1234')
    assert ckan['kind'] == 'ckan'
    one = url_identity('https://data.example.gov.au/resource/abcd-1234.csv')
    two = url_identity('https://data.example.gov.au/api/views/abcd-1234/rows.csv?accessType=DOWNLOAD')
    assert one == two and one['kind'] == 'socrata'
    assert url_identity('https://data.example.gov.au/resource/abcd-1234/unrelated.csv')['kind'] != 'socrata'
    assert url_identity('https://[malformed') is None


@pytest.mark.parametrize('change', [None, 'no_full_qa', 'no_graph', 'discovery_only', 'other_version', 'other_host'])
def test_external_registry_identity_requires_scoped_full_qa(change):
    import json
    from arsia_pipeline.evidence_graph import build_graph
    publisher = 'https://data.example.gov.au/api/3/action/package_show?id=events'
    external = 'https://cdn.example/events.csv?version=2'
    catalogue = json.dumps({'result': {'name': 'events', 'resources': [{'url': external}]}})
    docs = {'publisher': {'url': publisher, 'text': catalogue}, 'resource': {'url': external, 'text': 'id,date\n1,2024-01-01'}}
    graph = build_graph(external, docs, {'publisher'})['proof']
    result = admitted(publisher)
    result['admission']['evidence']['grounding'] = {'evidence_graph': graph}
    contract = {'source': {'dataset_url': external}}
    if change == 'no_full_qa': result['admission']['status'] = 'sample_only'
    if change == 'no_graph': result['admission']['evidence'].pop('grounding')
    if change == 'discovery_only': graph['edges'][0]['predicate'] = 'links_to'
    if change == 'other_version': contract['source']['dataset_url'] = external.replace('version=2', 'version=3')
    if change == 'other_host': contract['source']['dataset_url'] = external.replace('cdn.example', 'other.example')
    if change is None:
        assert canonical_source_identity(result, contract)['host'] == 'cdn.example'
    else:
        with pytest.raises((NeedsInput, ValidationFailure)):
            canonical_source_identity(result, contract)
