"""No database creation: actual probe, tool contract tests, readonly fixed materials."""
import argparse
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from arsia_pipeline.storage_lifecycle import atomic_json, sha, now
from storage_hardening_harness import PROJECT_ROOT, PIPELINE_ROOT, require_venv

# Exact published fixture digest is recorded independently in the prior source receipt.
SOURCE_SHA='c1336426b2414fc590d8b97ce6213c253d7bee3e6b0b1cf625c8331768452f38'
PG='sha256:efedf3595f1d6f415c08568ba171029bf54052e754cc9f030e3f2412b21f3d67'
EXECUTOR='sha256:a88768477864a1ee5ba1e6fd00534bee225c1e28d48875ae36611c59f2430bdd'


def materials(source,recipe_path):
    source=Path(source).absolute();recipe_path=Path(recipe_path).absolute()
    assert sha(source)==SOURCE_SHA, 'Fixed source differs'
    recipe=json.loads(recipe_path.read_text());docs=[]
    for doc in recipe['documents']:
        receipt=Path(doc['receipt_path'])
        raw=receipt.parent/'sha256'/doc['sha256']
        assert sha(raw)==doc['sha256']
        row={'document_id':doc['document_id'],'raw_sha256':sha(raw),'receipt_sha256':sha(receipt)}
        if doc.get('text_path'):row['text_sha256']=sha(Path(doc['text_path']))
        docs.append(row)
    assert {(r['sha256'],r['size']) for r in recipe['resources']}=={(sha(source),source.stat().st_size)}
    oracle=PROJECT_ROOT/'artifacts/closeout-20261002/tas_oracle.py'
    pg=subprocess.check_output(['docker','image','inspect',PG,'--format','{{.Id}}'],timeout=10).decode().strip()
    exe=subprocess.check_output(['docker','image','inspect','arsia-import-adapter:closeout-20261002','--format','{{.Id}}'],timeout=10).decode().strip()
    assert pg==PG and exe==EXECUTOR
    return {'source_sha256':sha(source),'source_bytes':source.stat().st_size,
            'recipe_sha256':sha(recipe_path),'documents':docs,'oracle_sha256':sha(oracle),
            'postgres_image':pg,'executor_image':exe,'downloads':0,'models':0}


def run(a):
    require_venv();out=a.output.absolute();out.mkdir(parents=True,exist_ok=True)
    started=time.monotonic();xml=out/'preflight-tests.xml'
    cmd=[sys.executable,'-B','-m','pytest',str(PIPELINE_ROOT/'tests/test_storage_hardening_harness.py'),'-q','--junitxml='+str(xml)]
    result=subprocess.run(cmd,cwd=PROJECT_ROOT,env={**os.environ,'PYTHONPATH':str(PIPELINE_ROOT),'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,timeout=60)
    (out/'preflight-tests.txt').write_bytes(result.stdout+result.stderr)
    tests=ET.parse(xml).getroot().findall('.//testcase');rows=[]
    for number in (1,2,3,4,5,6,8):
        name='P%02d'%number;cases=[t for t in tests if name in t.attrib['name']]
        status='pass' if cases and all(t.find('failure') is None and t.find('error') is None and t.find('skipped') is None for t in cases) else 'fail'
        rows.append({'id':name,'status':status,'testcases':[t.attrib['name'] for t in cases],
                     'type':'actual two-cwd subprocess probe' if number==1 else 'controlled tool unit/transport test',
                     'evidence':['preflight-tests.xml','preflight-tests.txt']})
    try:
        proof=materials(a.source,a.recipe);atomic_json(out/'materials.json',proof)
        rows.append({'id':'P07','status':'pass','type':'readonly local materials/image inspection','evidence':['materials.json']})
    except Exception as exc:rows.append({'id':'P07','status':'blocked','type':type(exc).__name__,'message':str(exc)})
    rows.sort(key=lambda r:r['id'])
    passed=result.returncode==0 and all(r['status']=='pass' for r in rows)
    atomic_json(out/'PREFLIGHT.json',{'status':'pass' if passed else 'blocked','at':now(),
        'seconds':time.monotonic()-started,'checks':rows,'database_created':False,
        'docker_created':False,'data_model_calls':0,'data_model_tokens':0,
        'command':cmd,'production_sources_changed':False})
    print(json.dumps({'status':'pass' if passed else 'blocked','checks':[(r['id'],r['status']) for r in rows]}))
    return 0 if passed else 1


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--source',type=Path,required=True);p.add_argument('--recipe',type=Path,required=True)
    raise SystemExit(run(p.parse_args()))
