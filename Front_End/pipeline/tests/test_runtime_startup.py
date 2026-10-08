"""Explicit opt-in real fresh-process startup and writable path boundary matrix."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
from uuid import uuid4
import pytest

PROJECT=Path(__file__).resolve().parents[2]
@pytest.fixture(scope='module')
def cases():
    p=os.environ.get('ARSIA_STARTUP_CASES')
    if not p:pytest.skip('Requires explicit fresh managed startup test instances')
    return json.loads(Path(p).read_text())

def call(cases,config=None,*,instance=None,session=None,cwd=None,code=None,extra_env=None):
    p=Path(config or cases['a']);cfg=json.loads(p.read_text()) if p.exists() else json.loads(Path(cases['a']).read_text())
    env={**os.environ,'PYTHONPATH':str(PROJECT/'pipeline'),'PYTHONDONTWRITEBYTECODE':'1'};env.pop('ARSIA_IMPORT_CONFIG',None)
    if extra_env:env.update(extra_env)
    args=[sys.executable,'-B','-c',code] if code else [sys.executable,'-B','-m','arsia_pipeline.runtime','check','--config',str(p),'--instance',instance or cfg['instance_id'],'--session',session or cfg['test_session_id']]
    r=subprocess.run(args,env=env,cwd=cwd or PROJECT,capture_output=True,text=True,timeout=25)
    evidence={'args':args,'cwd':str(cwd or PROJECT),'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr}
    out=Path(cases['evidence']);(out/(uuid4().hex+'.json')).write_text(json.dumps(evidence,indent=2));return r

@pytest.mark.parametrize('which',['a','b'])
@pytest.mark.parametrize('other_cwd',[False,True])
def test_real_subprocess_binding(cases,tmp_path,which,other_cwd):
    cfg=json.loads(Path(cases[which]).read_text());r=call(cases,cases[which],cwd=tmp_path if other_cwd else None)
    assert r.returncode==0,r.stderr;d=json.loads(r.stdout);assert d['config_root']==cfg['data_root']
    assert all(v==cfg['data_root'] for v in d['module_bindings'].values());assert d['model_calls']==d['jobs_claimed']==0
    assert d['checked_jobs']==d['checked_attempts']==0

@pytest.mark.parametrize('fault',['missing','instance','session','root','trace','registry','evidence','knowledge','database','symlink-trace','symlink-config','conflicting-env'])
def test_reject_before_work(cases,tmp_path,fault):
    original=Path(cases['b'] if fault=='symlink-trace' else cases['a']);cfg=json.loads(original.read_text());path=original.parent/(uuid4().hex+'.json');kwargs={}
    try:
        if fault=='missing':path=original.parent/'missing-runtime.json'
        elif fault=='instance':kwargs['instance']=uuid4().hex
        elif fault=='session':kwargs['session']=uuid4().hex
        elif fault=='root':cfg['data_root']=str(tmp_path)
        elif fault in {'trace','registry','evidence'}:cfg[fault+'_root']=str(tmp_path)
        elif fault=='knowledge':cfg['knowledge_root']=str(tmp_path)
        elif fault=='database':cfg['dsn']=json.loads(Path(cases['b']).read_text())['dsn']
        elif fault=='symlink-trace':(original.parent/'codex-tasks').symlink_to(tmp_path,target_is_directory=True)
        elif fault=='symlink-config':path.symlink_to(original)
        elif fault=='conflicting-env':kwargs['extra_env']={'ARSIA_IMPORT_CONFIG':cases['b']}
        if fault not in {'missing','symlink-config'}:path.write_text(json.dumps(cfg));path.chmod(0o600)
        r=call(cases,path,**kwargs);assert r.returncode!=0;assert 'RUNTIME_ISOLATION' in r.stderr
        assert not list(tmp_path.iterdir()),'Rejected startup created business outputs'
    finally:
        if path!=original and path.exists():path.unlink()
        if fault=='symlink-trace':(original.parent/'codex-tasks').unlink()


def test_no_explicit_config_and_late_bootstrap_rejected(cases):
    r=subprocess.run([sys.executable,'-B','-m','arsia_pipeline.runtime','check'],env={**os.environ,'PYTHONPATH':str(PROJECT/'pipeline')},capture_output=True,text=True,timeout=15)
    assert r.returncode!=0
    cfg=json.loads(Path(cases['a']).read_text());code='from arsia_pipeline import config; from arsia_pipeline.runtime import bootstrap; bootstrap('+repr(cases['a'])+','+repr(cfg['instance_id'])+','+repr(cfg['test_session_id'])+')'
    r=call(cases,code=code);assert r.returncode!=0 and 'before explicit bootstrap' in r.stderr


def test_old_env_only_worker_import_now_binds_correctly(cases):
    code="from arsia_pipeline import worker,config,codex_runtime,registry; import json; print(json.dumps([str(config.ROOT),str(codex_runtime.ROOT),str(registry.ROOT)]))"
    r=call(cases,code=code,extra_env={'ARSIA_IMPORT_CONFIG':cases['a']});assert r.returncode==0,r.stderr
    assert json.loads(r.stdout)==[json.loads(Path(cases['a']).read_text())['data_root']]*3


def test_real_evidence_and_trace_components(cases):
    cfg=json.loads(Path(cases['a']).read_text());code='''
import json,hashlib
from pathlib import Path
from uuid import uuid4
from types import SimpleNamespace
from arsia_pipeline.runtime import bootstrap
bootstrap(CONFIG,INSTANCE,SESSION)
from arsia_pipeline import config
from arsia_pipeline.codex_runtime import CodexRuntime
from arsia_pipeline.intake_tools import IntakeTools
job,attempt=uuid4(),uuid4();work=config.output_path('attempts',str(job),str(attempt));work.mkdir(parents=True)
runtime=CodexRuntime(SimpleNamespace(job={'id':job,'attempt_id':attempt,'work_dir':work},runtime_state={}))
runtime.root.mkdir(parents=True);marker=runtime.root/'startup-probe.json';marker.write_text(json.dumps({'untrusted_test_marker':True,'job':str(job)}))
source=work/'untrusted-startup-probe.txt';source.write_text('Nonofficial startup isolation marker. This document cannot authorize any source.')
files=[{'id':'startup-probe','name':source.name,'path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'size':source.stat().st_size}]
intake=IntakeTools(files,work/'intake',lambda:None)
result=intake.read_document(file_id='startup-probe')
docs=result['__documents'];assert docs and all(Path(d['text_path']).resolve().is_relative_to(config.ROOT) for d in docs)
for d in docs:
 assert 'Nonofficial startup isolation marker' in Path(d['text_path']).read_text()
 assert not d.get('official')
assert json.loads(marker.read_text())['untrusted_test_marker']
print(json.dumps({'trace':str(marker),'documents':[d['text_path'] for d in docs],'model_calls':0,'jobs_claimed':0,'admission':False}))
'''.replace('CONFIG',repr(cases['a'])).replace('INSTANCE',repr(cfg['instance_id'])).replace('SESSION',repr(cfg['test_session_id']))
    r=call(cases,code=code);assert r.returncode==0,r.stderr;d=json.loads(r.stdout);assert d['admission'] is False
    assert Path(d['trace']).resolve().is_relative_to(Path(cfg['data_root']))


def test_final_instances_still_empty_and_default_unchanged(cases):
    for which in ['a','b']:
        r=call(cases,cases[which]);assert r.returncode==0,r.stderr
        result=json.loads(r.stdout);assert result['checked_jobs']==result['checked_attempts']==0
    baseline_path=Path(cases['evidence']).parents[1]/'DEFAULT-before.json'
    baseline=json.loads(baseline_path.read_text());root=PROJECT/'artifacts/imports-local'
    current={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and not p.is_symlink()}
    assert current==baseline,'Default directory changed during isolated checks'
