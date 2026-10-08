"""Real frozen publisher prose with pinned references; not source admission."""
import copy
import json

import pytest

from arsia_pipeline.lookup_evidence import REVIEWED, review_lookup_relations
from arsia_pipeline.metadata_extractors import MetadataError
from test_resource_schema_subjects import frozen_vic_context


def context():
    c,d,g,a,graph=frozen_vic_context()
    claim=json.loads(REVIEWED.read_text())['claims'][0]
    a['relations']=[{**ref,'document_id':'official'} for ref in claim['references']]
    return c,d,g,a,graph


def test_frozen_official_node_reference_is_verified_without_inventing_csvw():
    c,d,g,a,graph=context()
    review=review_lookup_relations(c,graph,g,a,documents=d)
    assert review['ok'],review
    evidence=review['decisions'][0]['evidence'][0]
    assert evidence['interpretation']=='implementation_reviewed_pinned_relation'
    assert evidence['child_fields']==evidence['parent_fields']==['NODE_ID']
    assert len(evidence['references'])==12
    assert any('duplicate' in limit for limit in evidence['source_limits'])
    assert review['decisions'][0]['physical_uniqueness_and_coverage_required'] is True


@pytest.mark.parametrize('fault',['dataset','coverage','uncited','partial_citation','key','nullable','document_url','hash','scope','query','no_raw_documents'])
def test_pinned_relation_cannot_escape_exact_context_or_citation(fault):
    c,d,g,a,graph=context()
    if fault=='dataset':c['source']['dataset_url']='https://data.example.gov.au/dataset/unrelated'
    if fault=='coverage':c['source']['coverage']['to']='2026-01-01'
    if fault=='uncited':a['relations']=[]
    if fault=='partial_citation':a['relations']=a['relations'][:4]
    if fault=='key':c['lookup_tables'][0]['key']=['ACCIDENT_NO']
    if fault=='nullable':c['resources'][0]['lookups'][0]['allow_blank']=True
    if fault=='document_url':d['official']['url']+='&other=true'
    if fault=='hash':d['official']['sha256']='0'*64
    if fault=='scope':g['applicability']['roles']['nodes']['applicable_documents']=[]
    if fault=='query':c['resources'][0]['source_url']+='?year=2010'
    assert not review_lookup_relations(c,graph,g,a,documents=None if fault=='no_raw_documents' else d)['ok']


def test_original_bytes_are_reverified_even_when_graph_was_already_built():
    c,d,g,a,graph=context();d['official']['content_bytes']+=b' '
    with pytest.raises(MetadataError) as error:review_lookup_relations(c,graph,g,a,documents=d)
    assert error.value.code=='EVIDENCE_HASH_MISMATCH'
