import copy
import pytest
from arsia_pipeline.source_knowledge import load_catalog
from arsia_pipeline.catalog_schema import validate_catalog


@pytest.mark.parametrize('fault',['resource_id','grain','evidence','field','header','licence_scope','verified_licence','adoption','standard_field'])
def test_catalog_rejects_invalid_scopes_and_schema(fault):
    catalog=copy.deepcopy(load_catalog());source=next(s for s in catalog['sources'] if s['id']=='act-road-crash');r=source['resources'][0]
    if fault=='resource_id':source['resources'].append(copy.deepcopy(r))
    elif fault=='grain':r['grain']='crashes_or_people_whatever'
    elif fault=='evidence':r['evidence']['id']='missing'
    elif fault=='field':r['fields'].append(copy.deepcopy(r['fields'][0]))
    elif fault=='header':r['headers'].append(r['headers'][0])
    elif fault=='licence_scope':r['licence']['resource_url']='https://unrelated.example/data'
    elif fault=='verified_licence':r['licence']['status']='verified'
    elif fault=='adoption':catalog['standards_links'][0]['adoption_sha256']='0'*64
    elif fault=='standard_field':catalog['standards_links'][0]['field']='unrelated'
    with pytest.raises(ValueError,match='Invalid knowledge catalogue'):validate_catalog(catalog)


def test_current_capability_does_not_rewrite_historical_research_or_grant_admission():
    catalog=load_catalog();act=next(s for s in catalog['sources'] if s['id']=='act-road-crash')
    assert act['research_history'][0]['adapter_status']=='blocked_CRS_UNGROUNDED'
    assert act['runtime_capabilities']['rdf_geography']=='implemented'
    assert act['runtime_capabilities']['current_full_upload_acceptance']=='not_run_this_goal'
    assert act['resources'][0]['licence']['status']=='declared_unverified'
