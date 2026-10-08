import copy
import hashlib
import json
from pathlib import Path

import pytest

from arsia_pipeline.count_definitions import definition_meaning, review_direct_count, REVIEWED
from arsia_pipeline.evidence_graph import build_graph
from arsia_pipeline.evidence_grounding import ground_contract
from arsia_pipeline.evidence_references import reference
from test_count_semantics import fixture, review, DOC, URL


def direct(metric='fatalities', field='deaths', statement='Number of deceased persons'):
    c, docs, accepted = fixture()
    mapping = c['resources'][0]['mapping']; mapping.pop('casualties'); mapping[metric] = {'field': field}
    value = json.loads(docs['official']['content_bytes']); value['columns'][2]['description'] = statement
    update(docs, accepted, value)
    return c, docs, accepted


def update(docs, accepted, value):
    raw = json.dumps(value).encode(); sha = hashlib.sha256(raw).hexdigest()
    docs['official'].update(content_bytes=raw, text=raw.decode(), sha256=sha)
    for entries in accepted.values():
        entries[0]['quote'] = raw.decode()


@pytest.mark.parametrize('metric,field', [('fatalities','deaths'),('casualties','total'),('declared_casualties','total')])
def test_direct_definition_and_explicit_total_are_proven(metric,field):
    c,d,a=direct(metric,field)
    result=review(c,d,a)
    assert result['ok'] and result['decisions'][0]['claim_type']=='direct_count_definition'
    assert result['decisions'][0]['evidence'][0]['cited']


@pytest.mark.parametrize('metric,field', [('fatalities','injured'),('casualties','deaths'),('declared_units','deaths'),('declared_casualties','injured')])
def test_source_measure_cannot_be_relabelled_as_another_count(metric,field):
    c,d,a=direct(metric,field)
    c['definitions']={metric:'The model confirms this is the requested measure.'}
    assert review(c,d,a)['issues'][0]['code']=='COUNT_MEANING_CONFLICT'


def test_one_operand_sum_cannot_bypass_meaning():
    c,d,a=direct('fatalities','injured'); c['resources'][0]['mapping']['fatalities']={'sum_fields':['injured']}
    assert review(c,d,a)['issues'][0]['code']=='COUNT_MEANING_CONFLICT'


@pytest.mark.parametrize('statement', ['Fatalities are not represented by this field.',
    'Example: Number of fatalities', 'Number of fatalities if the flag is enabled',
    'Number of fatalities per 100,000 people', 'Percentage of deaths', 'Fatal indicator, 0 or 1',
    'Number of occupants', 'No definition available'])
def test_prose_rate_indicator_or_unproven_meaning_cannot_become_count(statement):
    c,d,a=direct(statement=statement)
    assert review(c,d,a)['issues'][0]['code']=='COUNT_MEANING_UNGROUNDED'


def test_wrong_grain_and_omitted_known_conflict_block():
    c,d,a=direct('casualties','deaths','The total number of casualties for a unit involved in a road crash')
    assert review(c,d,a)['issues'][0]['code']=='COUNT_MEANING_CONFLICT'
    c,d,a=direct();value=json.loads(d['official']['content_bytes']);value['columns'][2]['definition']='Number of injured persons';update(d,a,value)
    a['counts'][0]['quote']='Number of deceased persons'
    assert review(c,d,a)['issues'][0]['code']=='COUNT_MEANING_CONFLICT'


def test_unknown_second_definition_cannot_be_hidden_by_omitting_citation():
    c,d,a=direct();v=json.loads(d['official']['content_bytes']);v['columns'][2]['definition']='This field has a restricted population that needs review';update(d,a,v)
    a['counts'][0]['quote']='Number of deceased persons'
    assert review(c,d,a)['issues'][0]['code']=='COUNT_MEANING_UNGROUNDED'


def test_exact_field_definition_locator_not_neighbour():
    c,d,a=direct();doc=d['official'];a['counts']=[reference(doc['content_bytes'],doc['sha256'],'official',{'kind':'json-pointer','pointer':'/columns/2/description'})]
    assert review(c,d,a)['ok']
    # Keep field presence separately, but cite the unrelated injured definition.
    a['counts']=[reference(doc['content_bytes'],doc['sha256'],'official',{'kind':'json-pointer','pointer':'/columns/2/fieldName'}), reference(doc['content_bytes'],doc['sha256'],'official',{'kind':'json-pointer','pointer':'/columns/3/description'})]
    assert review(c,d,a)['issues'][0]['code']=='COUNT_MEANING_UNGROUNDED'


def test_structured_official_alias_resolves_to_same_field_definition():
    c,d,a=direct();v=json.loads(d['official']['content_bytes']);v['columns'][2]['name']='Fatality total';update(d,a,v)
    c['resources'][0]['mapping']['fatalities']['field']='Fatality total'
    assert review(c,d,a)['ok']


def test_nested_definition_cannot_lend_meaning():
    c,d,a=direct(statement='No definition');v=json.loads(d['official']['content_bytes']);v['neighbour']={'columns':[{'fieldName':'deaths','description':'Number of fatalities'}]};update(d,a,v)
    assert not review(c,d,a)['ok']


def pinned_context():
    from pypdf import PdfReader
    rule=json.loads(REVIEWED.read_text())['claims'][0]
    raw=(REVIEWED.parent/'evidence'/rule['document_sha256']).read_bytes()
    text='\n\n'.join(page.extract_text() for page in PdfReader(REVIEWED.parent/'evidence'/rule['document_sha256']).pages)
    doc={'url':rule['document_url'],'sha256':rule['document_sha256'],'content_bytes':raw,'text':text}
    c={'source':{'dataset_url':rule['dataset_urls'][0],'coverage':rule['coverage']}}
    r={'role':'crash','grain':rule['grain'],'key':rule['key'],'mapping':{}}
    g={'connected_documents':['dictionary']};a={'counts':[{'document_id':'dictionary','quote':text}]}
    graph={'nodes':{'dictionary':{'facts':{'value':None},'scoped_packages':[],'document_sha256':rule['document_sha256']}}}
    return c,r,rule,{'dictionary':doc},g,a,graph


def test_real_frozen_pdf_reviewed_alias_definition_has_exact_provenance():
    c,r,rule,d,g,a,graph=pinned_context()
    result=review_direct_count(c,r,'fatalities','Total Fats',d,g,a,graph)
    assert result['decision']['evidence'][0]['reviewed_claim_id']==rule['id']
    assert result['decision']['measure']=='fatalities'
    assert review_direct_count(c,r,'casualties','Total Fats',d,g,a,graph)['issue']['code']=='COUNT_MEANING_CONFLICT'


@pytest.mark.parametrize('change',['dataset','version','grain','key','coverage','authority','citation'])
def test_pinned_review_cannot_escape_source_version_population_or_citation(change):
    c,r,rule,d,g,a,graph=pinned_context();c=copy.deepcopy(c);r=copy.deepcopy(r)
    if change=='dataset':c['source']['dataset_url']='https://data.sa.gov.au/data/dataset/unrelated'
    if change=='version':d['dictionary']['sha256']='0'*64
    if change=='grain':r['grain']='observation'
    if change=='key':r['key']=['OTHER_ID']
    if change=='coverage':c['source']['coverage']['to']='2025-12-31'
    if change=='authority':g['connected_documents']=[]
    if change=='citation':a['counts'][0]['quote']='Total Fats is an exported column.'
    result=review_direct_count(c,r,'fatalities','Total Fats',d,g,a,graph)
    assert 'issue' in result


def test_source_dictionary_raw_bytes_tampering_invalidates_reviewed_reference():
    from arsia_pipeline.metadata_extractors import MetadataError
    c,r,rule,d,g,a,graph=pinned_context();d['dictionary']['content_bytes']+=b' changed'
    with pytest.raises(MetadataError):review_direct_count(c,r,'fatalities','Total Fats',d,g,a,graph)


def test_rules_are_part_of_trusted_dependency_identity():
    from arsia_pipeline.trusted_qa import trusted_implementation
    assert trusted_implementation()['knowledge/reviewed-count-claims.json']==hashlib.sha256(REVIEWED.read_bytes()).hexdigest()


def test_specific_knowledge_query_exposes_pinned_scope_without_admission():
    from arsia_pipeline.source_knowledge import lookup
    result=lookup(dataset_id='sa-road-crash')
    assert result['authority']=='research_only_requires_fresh_QA'
    claims=result['sources'][0]['reviewed_count_interpretations']
    assert len(claims)==4 and all(c['document_sha256'] and c['coverage']['to']=='2024-12-31' for c in claims)
