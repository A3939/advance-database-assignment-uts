import copy
import hashlib
import json
from pathlib import Path

import pytest
from arsia_pipeline import publication_identity as identity
from arsia_pipeline.errors import ValidationFailure
from test_canonical_v2 import contract


def candidate(tmp_path):
    paths={}
    hashes={}
    for grain,name in [('crash','crashes'),('unit','units'),('casualty','casualties'),('observation','observations')]:
        p=tmp_path/(name+'.jsonl');p.write_text(''.join(json.dumps(x)+'\n' for x in ([{'id':2,'coordinates':[149,-35]},{'id':1}] if grain=='crash' else [])))
        paths[grain]=p;hashes[p.name]=hashlib.sha256(p.read_bytes()).hexdigest()
    return {'source_id':'independent_fixture','source_contract':contract(),'update':{'mode':'snapshot'},'coverage':{'from':'2024-01-01','to':'2024-12-31'},'capabilities':{'crashes':True},'admission':{'artifact_hashes':hashes}},paths


def test_order_json_format_upload_name_and_execution_metadata_are_not_content(tmp_path):
    r,p=candidate(tmp_path);a=identity.identify(r,p,lambda:None)
    r['source_contract']['resources'][0]['file_id']='renamed-upload'
    r.update(fingerprint='new exact execution',files=[{'name':'renamed.json'}],adapter_version_id='different',job_id='other')
    r['admission'].update(adapter_sha256='different',policy_version='new rules',image='new image')
    p['crash'].write_text('{"id": 1}\n{"coordinates":[149,-35],"id":2}\n')
    r['admission']['artifact_hashes'][p['crash'].name]=hashlib.sha256(p['crash'].read_bytes()).hexdigest()
    assert identity.identify(r,p,lambda:None)['sha256']==a['sha256']


@pytest.mark.parametrize('change',['output','definition','permission','scope','mode','capability','source'])
def test_equal_counts_cannot_hide_semantic_or_output_changes(tmp_path,change):
    r,p=candidate(tmp_path);a=identity.identify(r,p,lambda:None)
    if change=='output':
        p['crash'].write_text(p['crash'].read_text().replace('149','148'))
        r['admission']['artifact_hashes'][p['crash'].name]=hashlib.sha256(p['crash'].read_bytes()).hexdigest()
    elif change=='definition':r['source_contract']['definitions']['casualties_includes_fatalities']=False
    elif change=='permission':r['source_contract']['source']['licence']='different rights'
    elif change=='scope':r['update']['from']='2024-06-01'
    elif change=='mode':r['update']['mode']='partition'
    elif change=='capability':r['capabilities']['crashes']=False
    else:r['source_id']='other_source'
    assert identity.identify(r,p,lambda:None)['sha256']!=a['sha256']


def test_content_hash_does_not_waive_artifact_integrity(tmp_path):
    r,p=candidate(tmp_path);p['crash'].write_text('{}\n')
    with pytest.raises(ValidationFailure,match='changed'):identity.identify(r,p,lambda:None)
