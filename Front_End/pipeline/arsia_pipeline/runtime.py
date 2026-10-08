"""Explicit managed API/worker startup. Import this before business modules.

`python -m arsia_pipeline.runtime check|worker|api --config /absolute/runtime.json
 --instance ID --session ID` uses one immutable binding. No test data/hooks.
"""
import argparse
import importlib
import json
import os
from pathlib import Path
import sys


def bootstrap(path,instance_id,session_id):
    # Do not import config or business modules before validating explicit intent.
    if not path or not instance_id or not session_id:
        raise RuntimeError('RUNTIME_ISOLATION: explicit config, instance and session are required')
    p=Path(path)
    if not p.is_absolute() or not p.is_file() or p.is_symlink():
        raise RuntimeError('RUNTIME_ISOLATION: absolute regular config is required')
    previous=os.environ.get('ARSIA_IMPORT_CONFIG')
    if previous and Path(previous).resolve()!=p.resolve():
        raise RuntimeError('RUNTIME_ISOLATION: conflicting explicit configuration')
    loaded=sys.modules.get('arsia_pipeline.config')
    if loaded and loaded.CONFIG.resolve()!=p.resolve():
        raise RuntimeError('RUNTIME_ISOLATION: config was imported before explicit bootstrap')
    os.environ['ARSIA_IMPORT_CONFIG']=str(p)
    from . import config
    cfg=config.read_config()
    if cfg.get('storage_policy',{}).get('enabled') is not True:
        raise config.RuntimeConfigurationError('Managed isolation is required by this entrypoint')
    if cfg['instance_id']!=instance_id or cfg.get('test_session_id')!=session_id:
        raise config.RuntimeConfigurationError('Expected instance/session differs from runtime owner')
    from .storage_lifecycle import validate_managed
    root,home,manifest=validate_managed(cfg)
    targets={k:config.output_path(k) for k in ('registry','attempts','trace','evidence','output')}
    targets['knowledge']=root/'recipes'
    for key,target in targets.items():
        supplied=cfg.get('knowledge_root' if key=='knowledge' else key+'_root')
        if supplied is not None and Path(supplied).resolve()!=target.resolve():
            raise config.RuntimeConfigurationError('Configured '+key+' target differs from managed destination')
        if not target.resolve().is_relative_to(root.resolve()) or any(x.is_symlink() for x in [target,*target.parents]):
            raise config.RuntimeConfigurationError('Indirect/outside '+key+' destination refused')
    if cfg.get('socket_path') and not Path(cfg['socket_path']).resolve().is_relative_to(home.resolve()):
        raise config.RuntimeConfigurationError('Managed API socket escaped session')
    # All actual ROOT consumers in this execution chain are loaded only now.
    modules=['api','worker','registry','source_identity','agent','trusted_qa','codex_runtime','codex_bridge','adapter_reuse','isolated_executor']
    bindings={}
    for name in modules:
        module=importlib.import_module('arsia_pipeline.'+name)
        if hasattr(module,'ROOT'):
            if Path(module.ROOT).resolve()!=root.resolve():raise config.RuntimeConfigurationError('Stale '+name+' ROOT binding')
            bindings[name]=str(module.ROOT)
    from . import store,isolated_executor
    if isolated_executor.IMAGE!=cfg.get('executor_image'):
        raise config.RuntimeConfigurationError('Executor image differs from explicit instance')
    # Existing production identity checks are SELECT-only; no initialization or migrations.
    try:
        with store.connect(cfg) as conn,conn.transaction():
            conn.execute('SET TRANSACTION READ ONLY')
            database=conn.execute('SELECT current_database() AS database').fetchone()['database']
            jobs=conn.execute('SELECT id FROM jobs').fetchall()
            attempts=conn.execute('SELECT id,job_id,work_dir FROM attempts').fetchall()
    except Exception as exc:
        raise config.RuntimeConfigurationError('Read-only database identity preflight failed ('+type(exc).__name__+')') from None
    for a in attempts:
        expected=config.output_path('attempts',str(a['job_id']),str(a['id']))
        if Path(a['work_dir']).resolve()!=expected.resolve():raise config.RuntimeConfigurationError('Recorded attempt belongs to another output root')
    for j in jobs:config.output_path('trace',str(j['id']))
    return {'status':'pass','instance_id':instance_id,'session_id':session_id,'database':database,
        'config_root':str(config.ROOT),'config_path':str(config.CONFIG),'storage_home':str(home),
        'targets':{k:str(p) for k,p in targets.items()},'module_bindings':bindings,'executor_image':isolated_executor.IMAGE,
        'checked_jobs':len(jobs),'checked_attempts':len(attempts),'read_only_database_check':True,
        'model_calls':0,'jobs_claimed':0}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['check','worker','api'])
    p.add_argument('--config',required=True);p.add_argument('--instance',required=True);p.add_argument('--session',required=True);p.add_argument('--once',action='store_true')
    a=p.parse_args()
    try:
        result=bootstrap(a.config,a.instance,a.session);print(json.dumps(result),flush=True)
        if a.mode=='worker':
            from .worker import run
            run(once=a.once)
        elif a.mode=='api':
            from .dev import serve
            serve()
    except Exception as exc:
        print(json.dumps({'status':'error','code':'RUNTIME_ISOLATION','kind':'system_configuration','type':type(exc).__name__,
            'message':str(exc) if str(exc).startswith(('RUNTIME_ISOLATION','Runtime','Explicit','Managed','Expected','Configured','Indirect','Stale','Executor','Read-only','Recorded','Non-default')) else 'Explicit startup validation failed; inspect the configuration identity.'}),file=sys.stderr)
        return 2
    return 0

if __name__=='__main__':raise SystemExit(main())
