import copy
import hashlib
import json

from arsia_pipeline.licence_assessment import assess
from arsia_pipeline.evidence_references import reference


def fixture():
    url='https://data.example.gov.au/download/crashes.csv'
    raw=json.dumps({'result':{'resources':[{'url':url,'license':'https://creativecommons.org/licenses/by/4.0/','licence':'https://creativecommons.org/publicdomain/zero/1.0/'}]}}).encode()
    sha=hashlib.sha256(raw).hexdigest()
    doc={'url':'https://data.example.gov.au/api/3/action/package_show?id=crashes','sha256':sha,'content_bytes':raw,'fetched_at':'2026-10-03'}
    entry=reference(raw,sha,'doc',{'kind':'json-pointer','pointer':'/result/resources/0/license'})
    contract={'source':{'licence':'Unknown for this exact layer'},'resources':[{'role':'crash','source_url':url,'licence':{'status':'verified','evidence':[entry]}}]}
    return contract,{'doc':doc},{'authorized':{'doc'}}


def test_exact_publisher_resource_licence_is_traceable_but_not_redistribution_approval():
    c,d,g=fixture();result=assess(c,d,g)['resources'][0]
    assert result['status']=='verified' and result['licence_id']=='CC-BY-4.0'
    assert result['resource_url']==c['resources'][0]['source_url']
    assert result['evidence'][0]['fetched_at']=='2026-10-03'
    assert result['redistribution']=='not_assessed'


def test_strings_unknown_scopes_forged_hash_and_unauthorized_links_never_grant_licence():
    c,d,g=fixture()
    for change in ('string','scope','hash','authority'):
        candidate=copy.deepcopy(c);graph=copy.deepcopy(g)
        if change=='string':candidate['resources'][0]['licence']={'text':'Definitely verified CC-BY-4.0','status':'verified'}
        elif change=='scope':candidate['resources'][0]['source_url']='https://data.example.gov.au/download/other.csv'
        elif change=='hash':candidate['resources'][0]['licence']['evidence'][0]['document_sha256']='0'*64
        else:graph['authorized']=set()
        assert assess(candidate,d,graph)['resources'][0]['status']=='unknown'


def test_conflicting_and_restricted_states_do_not_get_collapsed_into_string():
    c,d,g=fixture();doc=d['doc']
    c['resources'][0]['licence']['evidence'].append(reference(doc['content_bytes'],doc['sha256'],'doc',{'kind':'json-pointer','pointer':'/result/resources/0/licence'}))
    assert assess(c,d,g)['resources'][0]['status']=='conflicting'
    c['resources'][0]['licence']={'status':'restricted','text':'Review restrictions before reuse'}
    result=assess(c,d,g)['resources'][0]
    assert result['status']=='restricted' and result['restriction_verified'] is False
