"""Real isolated Python output -> independent full QA -> registry/publication.
Synthetic official-shaped receipts, never the real TAS input or its oracle.
"""
import hashlib
import json
from pathlib import Path
import pytest
from test_backend import isolated_database,client,queued,claim_specific
from test_arcgis_representation import bundle,doc
from test_lookup_admission import install_documents
from arsia_pipeline import config,registry,publication,query,store
from arsia_pipeline.evidence_references import reference
from arsia_pipeline.errors import ValidationFailure
from arsia_pipeline.isolated_executor import run_python
from arsia_pipeline.trusted_qa import validate_candidate

@pytest.mark.parametrize('fault',[None,'swapped_axes','legal_wrong_point'])
def test_generated_coordinate_output_independently_rejected(client,fault):
    job=claim_specific(queued(client)['id']);root=job['work_dir']
    c,files,docs,_=bundle(root,count=1)
    value=json.loads(docs['query']['text']);value['features'][0]['geometry']['coordinates']=[149.1,-35.2]
    docs['query']=doc(docs['query']['url'],value)
    Path(files[0]['path']).write_bytes(docs['query']['content_bytes'])
    files[0].update(name='synthetic.geojson',sha256=docs['query']['sha256'],size=len(docs['query']['content_bytes']))
    c.update(contract_version='canonical-v2',relations=[],definitions={})
    c['source'].update(source_id='coordinate_'+(fault or 'control'),title='Synthetic point control',publisher='Synthetic protocol fixture',jurisdiction=['ACT'],grain='crash',licence='Synthetic fixture only')
    c['resources'][0]['table']={'format':'json','json_kind':'geojson'}
    def ref(key,pointer):return reference(docs[key]['content_bytes'],docs[key]['sha256'],key,{'kind':'json-pointer','pointer':pointer})
    c['evidence']={'source_identity':[ref('layer','/id')],'grain':[ref('layer','/fields/0')],'date':[ref('layer','/fields/1')],
        'geography':[ref('query','/type')],'coverage_update':[ref('query','/type')]}
    install_documents(c,docs,root/'evidence')
    for d in c['documents']:
        p=Path(d['receipt_path']);v=json.loads(p.read_text());v['final_host_official']=True;p.write_text(json.dumps(v))
    code='def adapt(ctx):\n    for locator, raw in ctx.iter_rows("event"):\n        row=ctx.project("event",locator,raw)\n'
    if fault=='swapped_axes':code+='        row["coordinates"]=list(reversed(row["raw_coordinates"]))\n'
    if fault=='legal_wrong_point':code+='        row["coordinates"]=[149.2,-35.3]\n'
    code+='        ctx.emit("crash",row)\n'
    before=query.catalog()
    run=run_python(code,files,root/'runs',source_contract=c,mode='full',limits={'seconds':15,'memory_mb':128})
    assert run['status']=='succeeded',run
    emitted=json.loads((Path(run['output_dir'])/'crashes.jsonl').read_text())
    if fault:
        with pytest.raises(ValidationFailure,match='independent raw-row projection') as error:
            validate_candidate(run,c,files,run['code_sha256'],root)
        assert error.value.qa[0]['code']=='QA06_RECONCILIATION'
        (root/'coordinate-rejection.json').write_text(json.dumps({'fault':fault,'qa':error.value.qa,'emitted':emitted['coordinates']},indent=2))
        assert not list(root.glob('trusted-qa-*.json'))
        # Failed QA has no admission token: both public boundaries must refuse it.
        rejected={'source_id':c['source']['source_id'],'source_contract':c,'qa':error.value.qa}
        with pytest.raises(ValidationFailure):registry.register(code,c,rejected)
        with pytest.raises(ValidationFailure):publication.publish(job,rejected,lambda:None)
        assert query.catalog()==before
        with store.connect() as conn:
            assert conn.execute('SELECT count(*) AS n FROM batches WHERE job_id=%s',(job['id'],)).fetchone()['n']==0
            assert conn.execute('SELECT count(*) AS n FROM adapter_versions WHERE source_id=%s',(c['source']['source_id'],)).fetchone()['n']==0
    else:
        result=validate_candidate(run,c,files,run['code_sha256'],root)
        assert result['admission']['status']=='admitted'
        assert emitted['coordinates']==[149.1,-35.2]
        result['source_contract']=c
        result.update(registry.register(code,c,result))
        assert publication.publish(job,result,lambda:None)=='succeeded'
        first=store.get_job(job['id'])
        assert first['result']['summary']['crash_count']==1
        # Two independently executed and fully validated variants: local names /
        # formatting, then identical bytes under a different uploaded filename.
        for index in range(2):
            next_job=claim_specific(queued(client)['id'])
            next_root=next_job['work_dir']
            files[0]['name']='renamed.geojson' if index else 'synthetic.geojson'
            variant=code.replace('row=', 'projected = ').replace('"crash",row','"crash", projected')
            next_run=run_python(variant,files,next_root/'runs',source_contract=c,mode='full',limits={'seconds':15,'memory_mb':128})
            assert next_run['status']=='succeeded'
            fresh=validate_candidate(next_run,c,files,next_run['code_sha256'],next_root)
            fresh['source_contract']=c
            fresh.update(registry.register(variant,c,fresh))
            assert fresh['admission']['adapter_sha256']!=result['admission']['adapter_sha256']
            assert publication.publish(next_job,fresh,lambda:None)=='no_change'
            current=store.get_job(next_job['id'])
            assert current['release_id']==first['release_id']
            assert current['result']['publication_evidence']['candidate_validation']['evidence']['run_id']==next_run['run_id']
