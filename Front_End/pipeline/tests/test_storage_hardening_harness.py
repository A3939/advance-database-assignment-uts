"""Tool tests, deliberately not reported as Docker/SQL acceptance."""
import copy
import json
import signal
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import storage_hardening_harness as h
from arsia_pipeline import store


def test_P01_two_real_cwd_probes(tmp_path):
    children = h.Children(tmp_path / 'children', time.monotonic() + 30)
    values = [children.finish(children.spawn(None, 'probe', cwd=cwd))
              for cwd in (h.PROJECT_ROOT, tmp_path)]
    assert values[0] == values[1]
    assert values[0]['probe'] == 'pass'
    assert not values[0]['database_created'] and not values[0]['docker_created']
    assert all(x['receipt']['returncode'] == 0 for x in children.children)
    children.stop()


@pytest.fixture
def receipts(monkeypatch):
    jid = str(uuid4()); fid = uuid4().hex
    session = SimpleNamespace(cfg={'instance_id':'isolated-instance'})
    public = {'id':fid,'name':'file.csv','format':'csv','size':7,'sha256':'a'*64}
    private = {**public,'path':'/private/content','storage_version':'instance-cas-v1',
               'instance_id':session.cfg['instance_id'],'job_id':jid}
    holder = {'row':{'id':jid,'files':[private]}, 'cfg':None, 'queries':[]}
    class Conn:
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def transaction(self): return self
        def execute(self,query,args=None): holder['queries'].append((query,args)); return self
        def fetchone(self): return holder['row']
    def connect(cfg): holder['cfg']=cfg; return Conn()
    monkeypatch.setattr(store,'connect',connect)
    return session,jid,public,private,holder


def test_P02_explicit_internal_receipt(receipts):
    session,jid,public,private,holder=receipts
    assert h.load_internal_receipt(session,jid,public)==private
    assert holder['cfg'] is session.cfg
    assert holder['queries'][0][0]=='SET TRANSACTION READ ONLY'
    assert 'path' not in public


@pytest.mark.parametrize('fault',['wrong_file','duplicate','wrong_row_job','wrong_job','wrong_instance','sha256','format','public_path','missing_path'])
def test_P02_receipt_rejections(receipts,fault):
    session,jid,public,private,holder=receipts
    if fault=='wrong_file': public['id']=uuid4().hex
    elif fault=='duplicate': holder['row']['files'].append(copy.deepcopy(private))
    elif fault=='wrong_row_job': holder['row']['id']=str(uuid4())
    elif fault=='wrong_job': private['job_id']=str(uuid4())
    elif fault=='wrong_instance': private['instance_id']='other'
    elif fault in {'sha256','format'}: private[fault]='wrong'
    elif fault=='public_path': public['path']='/private'
    elif fault=='missing_path': private.pop('path')
    with pytest.raises(AssertionError): h.load_internal_receipt(session,jid,public)


def test_P03_phase_contract():
    for phase in ('upload_partial','upload_pending_commit'):
        assert h.PHASES[phase]['check_busy'] and h.PHASES[phase]['sql_files']==0
    assert h.PHASES['upload_sql_committed']=={'sql_files':1,'check_busy':False,'prekill_apply':False}


def test_P04_proof_survives_later_failure(tmp_path):
    children=h.Children(tmp_path/'children',time.monotonic()+30)
    child=children.spawn(None,'probe'); result=children.finish(child)
    h.atomic_json(tmp_path/'gc-result.json',{'results':[{'action':'committed'}]})
    try: raise AssertionError('later semantic failure')
    except AssertionError: pass
    receipt=json.loads(child['process_path'].read_text())
    assert receipt['pid'] and receipt['returncode']==0 and receipt['result_sha256']
    assert {'spawn_intent','spawned','exited','result_saved'} <= {x['state'] for x in receipt['history']}
    assert json.loads((tmp_path/'gc-result.json').read_text())['results']
    with pytest.raises(AssertionError,match='no SIGKILL'): children.finish(child,kill=True)
    assert json.loads(child['process_path'].read_text())['returncode']==0
    assert not any(x['state']=='signal_sent' for x in receipt['history'])
    # Exercise durable barrier/signal/exit records independently of business validation.
    synthetic={'receipt':{'history':[],'log':'synthetic.log','barrier':'synthetic.barrier.json','result':'synthetic.result.json'},'process_path':tmp_path/'synthetic-mock.process.json'}
    children.save(synthetic,'barrier_reached',actual_phase='synthetic')
    children.save(synthetic,'exited',returncode=-signal.SIGKILL)
    assert json.loads(synthetic['process_path'].read_text())['actual_phase']=='synthetic'
    children.stop()


def test_P05_semantic_assertion_and_json(tmp_path):
    steps=h.Steps(tmp_path,time.monotonic()+30)
    def failed():
        result={'status':'returned'}
        assert result['status']=='verified'
    with pytest.raises(AssertionError): steps.run('semantic',failed)
    assert json.loads((tmp_path/'steps.json').read_text())[0]['status']=='fail'
    with pytest.raises(TypeError): steps.run('object',lambda:SimpleNamespace(cfg={}))
    assert json.loads((tmp_path/'steps.json').read_text())[-1]['status']=='fail'
    assert 'namespace(' not in (tmp_path/'steps.json').read_text()


def test_P06_expired_no_child_and_original_deadline(tmp_path,monkeypatch):
    children=h.Children(tmp_path/'children',time.monotonic()-1)
    calls=[];monkeypatch.setattr(h.subprocess,'Popen',lambda *a,**k:calls.append(a))
    initial=children.deadline
    for _ in range(2):
        with pytest.raises(TimeoutError): children.spawn(None,'probe')
    assert not calls and not children.children and children.deadline==initial
    # Runner's first operation checks remaining before TestSpace.create.
    import verify_storage_hardening as runner
    monkeypatch.setattr(runner.TestSpace,'create',lambda *a,**k:calls.append(a))
    args=SimpleNamespace(output=tmp_path/'expired',source=tmp_path/'absent',recipe=tmp_path/'absent',deadline='2000-01-01T00:00:00+00:00')
    with pytest.raises(TimeoutError): runner.main(args)
    assert not calls and not args.output.exists()


def test_P08_cleanup_checks_exact_owned_resources(tmp_path,monkeypatch):
    from arsia_pipeline import test_session,storage_restore
    h.atomic_json(tmp_path/'session.json',{'state':'retained','docker':{'volume':'own-v'}})
    calls=[]
    session=SimpleNamespace(cfg={'test_session_id':'own'},ledger=SimpleNamespace(home=tmp_path),
        own=lambda:(_ for _ in ()).throw(RuntimeError('inspection unavailable')))
    monkeypatch.setattr(test_session,'docker',lambda *a,**k:calls.append(a))
    with pytest.raises(RuntimeError):h.stop_owned_session(session)
    assert not calls
    c={'Id':'exact-parent-created','State':{'Running':True}}
    def docker(*a,**k):calls.append(a);c['State']['Running']=False
    session.own=lambda:({},c,{})
    session.update=lambda **k:None
    monkeypatch.setattr(test_session,'docker',docker)
    assert h.stop_owned_session(session)['running'] is False
    assert calls==[('stop','--time','30','exact-parent-created')]
    h.atomic_json(tmp_path/'session.json',{'state':'archived','docker':{'name':'own-c','volume':'own-v'}})
    monkeypatch.setattr(storage_restore,'inspect_optional',lambda *a:(_ for _ in ()).throw(RuntimeError('unknown')))
    with pytest.raises(RuntimeError):h.stop_owned_session(session)


def test_P05_sql_decimal_is_numeric_not_object_string():
    from decimal import Decimal
    assert h.json_value({'compute_seconds':Decimal('1.25')})=={'compute_seconds':1.25}
    with pytest.raises(ValueError):h.json_value({'bad':Decimal('Infinity')})
