"""Version namespacing checks; these small fixtures do not prove official SA semantics."""
import copy
import pytest
from arsia_pipeline import independent_versions as versions
from arsia_pipeline.errors import ValidationFailure
from arsia_pipeline.source_identity import canonical_source_identity
from test_source_identity import admitted


def fixture():
    url = 'https://www.data.act.gov.au/api/views/6jn4-m8rx.json'
    contract = {'source': {'dataset_url':url, 'source_id':'events'}, 'update':{'mode':'snapshot'},
                'resources':[{'role':'crash','file_id':'f'}]}
    files = [{'id':'f','sha256':'a'*64,'size':30}]
    result = {**admitted(url), 'files':files}
    family = canonical_source_identity(result, contract)
    identity = versions.inputs(contract, files)
    contract['version_scope'] = {'version':versions.VERSION,'family_identity_key':family['identity_key'],
                                 'input_sha256':identity,'cross_version_record_mapping':'unverified'}
    contract['source']['source_id'] = versions.source_id(family['identity_key'], identity)
    return contract, files, result


def test_full_input_version_identity_and_single_official_family():
    contract, files, result = fixture()
    first = canonical_source_identity(result, contract)
    assert first['identity_key'].startswith(first['family_identity_key'] + ':independent:')
    renamed = copy.deepcopy(files); renamed[0].update(name='renamed.csv', id='new-id')
    same = copy.deepcopy(contract); same['resources'][0]['file_id'] = 'new-id'
    assert versions.inputs(same, renamed) == versions.inputs(contract, files)
    assert canonical_source_identity({**result,'files':renamed},same) == first


@pytest.mark.parametrize('fault',['input','family','id','mapping','merge','extra_field'])
def test_version_selection_cannot_grant_missing_authority(fault):
    c, files, r = fixture()
    if fault == 'input': files[0]['sha256']='b'*64
    if fault == 'family':
        c['version_scope']['family_identity_key']='official-dataset-'+'b'*64
        c['source']['source_id']=versions.source_id(c['version_scope']['family_identity_key'],c['version_scope']['input_sha256'])
    if fault == 'id': c['source']['source_id']='events'
    if fault == 'mapping': c['version_scope']['cross_version_record_mapping']='verified'
    if fault == 'merge': c['update']['mode']='incremental'
    if fault == 'extra_field': c['version_scope']['trusted']=True
    with pytest.raises(ValidationFailure): canonical_source_identity(r,c)


def test_version_cannot_promote_unadmitted_source():
    c, files, r = fixture()
    r['admission']['status']='sample_only'
    with pytest.raises(ValidationFailure): canonical_source_identity(r,c)


def test_preflight_namespace_is_not_admission_and_invalidates_qa(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from arsia_pipeline import trusted_qa
    c, files, result = fixture();c.pop('version_scope');c['source']['source_id']='events'
    calls=[]
    def set_contract(name,args):
        assert name=='set_source_contract'
        calls.append(args['contract'])
        return {'status':'proposal'}
    s=SimpleNamespace(contract=c, documents={'host': {'document_id':'host'}}, files=files, native_context=None, cancel_check=lambda:None,
                      work_dir=tmp_path, validated=None, execute_tool=set_contract)
    monkeypatch.setattr(trusted_qa,'validate_contract',lambda *a,**k:calls.append('validated'))
    def host_proof(contract,*args):
        assert contract['documents']==[{'document_id':'host'}]
        return result['admission']['evidence']
    monkeypatch.setattr(trusted_qa,'_proof',host_proof)
    proposal=versions.select(s)
    assert proposal['admission'] is False and proposal['target_satisfied'] is False
    candidate=calls[-1]
    assert candidate['update']=={'mode':'snapshot'}
    with pytest.raises(ValidationFailure):
        canonical_source_identity({'admission':{'status':'sample_only'},'files':files},candidate)
    verified=canonical_source_identity(result,candidate)
    assert verified['family_identity_key']==candidate['version_scope']['family_identity_key']


def test_preflight_namespace_refuses_missing_source_proof(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from arsia_pipeline import trusted_qa
    from arsia_pipeline.errors import NeedsInput
    c,files,_=fixture();c.pop('version_scope')
    s=SimpleNamespace(contract=c,documents={},files=files,native_context=None,cancel_check=lambda:None,work_dir=tmp_path)
    monkeypatch.setattr(trusted_qa,'validate_contract',lambda *a,**k:None)
    monkeypatch.setattr(trusted_qa,'_proof',lambda *a:{})
    with pytest.raises(NeedsInput):versions.select(s)
