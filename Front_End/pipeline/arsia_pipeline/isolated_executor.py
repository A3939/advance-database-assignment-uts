"""Task-scoped Docker isolation; never executes adapter code on the host."""
import hashlib
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time
from uuid import uuid4

from .errors import ImportCancelled

from .config import explicit_executor_image
IMAGE=explicit_executor_image() or "arsia-import-adapter:3"
DEFAULT_LIMITS={"seconds":900,"memory_mb":2048,"cpus":2,"pids":64,"output_bytes":4*1024**3,
                "work_bytes":12*1024**3,"reserve_bytes":1024**3}
ARTIFACTS={"crashes.jsonl","units.jsonl","casualties.jsonl","observations.jsonl","exclusions.jsonl","row-lineage.jsonl","runner-result.json","diagnostic.txt","report.json"}


class ExecutorEnvironmentError(RuntimeError):
    """Trusted Docker lifecycle failure, never constructed from adapter output."""
    kind = 'environment_dependency'

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.details = {}


def bounded_report(reported,limits):
    """Treat even the runner envelope as untrusted generated-code output.

    Exception text and arbitrary usage keys can contain raw person records.
    Only fixed classifications, line numbers and bounded numeric telemetry
    cross back to the model; full diagnostics stay on local disk.
    """
    if not isinstance(reported,dict):raise ValueError('Invalid sandbox result envelope')
    status='succeeded' if reported.get('status')=='succeeded' else 'failed'
    usage={}
    incoming=reported.get('usage',{})
    if isinstance(incoming,dict):
        for key,maximum in [('seconds',limits['seconds']*2),('ru_maxrss_bytes',limits['memory_mb']*1024**2*2)]:
            value=incoming.get(key)
            if type(value) in {float,int} and math.isfinite(value) and 0<=value<=maximum:usage[key]=value
    error=None
    if status=='failed':
        raw=reported.get('error',{})
        if not isinstance(raw,dict):raw={}
        allowed={'ContractError','SyntaxError','NameError','ImportError','ModuleNotFoundError','KeyError','ValueError','TypeError','MemoryError','PermissionError','FileNotFoundError','AssertionError','RuntimeError','OSError','AttributeError','IndexError','ZeroDivisionError'}
        kind=raw.get('type') if raw.get('type') in allowed else 'AdapterError'
        frames=[]
        for frame in raw.get('frames',[])[:8] if isinstance(raw.get('frames'),list) else []:
            if not isinstance(frame,dict) or type(frame.get('line')) is not int or not 0<=frame['line']<=1000000:continue
            filename=frame.get('file') if frame.get('file') in {'adapter.py','canonical.py','adapter_sdk.py','intakereaders.py','runner.py'} else 'dependency'
            frames.append({'file':filename,'line':frame['line']})
        error={'type':kind,'origin':'adapter','message':'Isolated adapter failed. Inspect its code at the reported line; full exception text is retained locally.','frames':frames}
    return {'status':status,'error':error,'usage':usage}


def sha(path):
    with Path(path).open('rb') as handle:return hashlib.file_digest(handle,'sha256').hexdigest()


def docker(args,timeout=30):
    env={"PATH":os.environ.get("PATH","/usr/local/bin:/usr/bin:/bin"),"HOME":os.environ.get("HOME","")}
    # Docker CLI connection configuration is not forwarded inside the container.
    return subprocess.run(["docker",*args],env=env,capture_output=True,text=True,timeout=timeout)


@lru_cache(maxsize=16)
def _probe_transforms(image, sources_json):
    """Trusted image probe: no adapter, uploaded files, network or writable mount.

    The immutable image determines the receipt. Never read the same information
    from runner-result.json, which generated adapter code can forge.
    """
    name='arsia-transform-probe-'+uuid4().hex
    code="import sys,json;sys.path.insert(0,'/opt/arsia');from arsia_pipeline.transform_plan import plan;print(json.dumps({key:plan(crs) for key,crs in json.loads(sys.argv[1]).items()},allow_nan=False))"
    try:
        result=docker(['run','--rm','--name',name,'--label','arsia.import.transform-probe='+name,
            '--pull=never','--network=none','--read-only','--user=65534:65534','--cap-drop=ALL',
            '--security-opt=no-new-privileges','--memory=256m','--memory-swap=256m','--cpus=1','--pids-limit=16',
            '--entrypoint','python',image,'-I','-c',code,sources_json],timeout=30)
        if result.returncode or len(result.stdout)>512*1024:
            from .transform_plan import TransformError
            raise TransformError('TRANSFORM_EXECUTOR_UNAVAILABLE','Reviewed executor image could not provide an offline coordinate plan. Rebuild the image with the current transform implementation.')
        return json.loads(result.stdout)
    finally:
        inspected=docker(['inspect',name,'--format','{{index .Config.Labels "arsia.import.transform-probe"}}'])
        if inspected.returncode==0 and inspected.stdout.strip()==name:docker(['rm','-f',name])


def probe_transforms(image, contract):
    from .transform_plan import contract_plans, compare_plans
    host=contract_plans(contract)
    if not host:return {}
    sources={resource['role']:resource['mapping']['geography']['crs'] for resource in contract['resources'] if resource['role'] in host}
    observed=_probe_transforms(image,json.dumps(sources,sort_keys=True))
    compare_plans(host,observed)
    return json.loads(json.dumps(observed))


def arguments(name,input_dir,output_dir,image,limits,ownership=None):
    args=['run','-d','--name',name,'--label','arsia.import.adapter='+name,'--pull=never','--network=none',
        '--read-only','--user=65534:65534','--cap-drop=ALL','--security-opt=no-new-privileges',
        '--memory='+str(limits['memory_mb'])+'m','--memory-swap='+str(limits['memory_mb'])+'m',
        '--cpus='+str(limits['cpus']),'--pids-limit='+str(limits['pids']),
        '--ulimit','nofile=256:256','--ulimit',f"fsize={limits['output_bytes']}:{limits['output_bytes']}",
        '--shm-size=8m','--log-driver=local','--log-opt','max-size=1m','--log-opt','max-file=1','--log-opt','compress=false',
        '--mount',f'type=bind,source={input_dir},target=/input,readonly',
        '--mount',f'type=bind,source={output_dir},target=/output',
        '--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=134217728,uid=65534,gid=65534,mode=700']
    if ownership:
        from .scoped_orphans import ownership_labels
        for key,value in ownership_labels(ownership).items():
            if key!='arsia.import.adapter':args.extend(['--label',key+'='+value])
    return [*args,image]


def safe_files(output,limit,hash_artifacts=True):
    total=0;files=[]
    for index,path in enumerate(output.rglob('*')):
        if index>8192:raise RuntimeError('Sandbox filesystem entry quota exceeded')
        if path.is_symlink():raise RuntimeError('Sandbox created a symlink; candidate refused')
        if path.is_file():
            total+=path.stat().st_size
            if total>limit:raise RuntimeError('Sandbox output quota exceeded')
            if hash_artifacts and path.parent==output and path.name in ARTIFACTS:
                files.append({'name':path.name,'sha256':sha(path),'size':path.stat().st_size})
        elif not path.is_dir():raise RuntimeError('Sandbox created an unsupported filesystem object')
    return files,total


def check_storage(root,limits,incoming=0):
    """Bound the whole job across attempts without deleting saved evidence."""
    total=0
    for index,path in enumerate(Path(root).rglob('*')):
        if index>100000:raise RuntimeError('Task filesystem entry budget exceeded')
        if path.is_symlink():raise RuntimeError('Task storage contains a symlink; candidate refused')
        if path.is_file():total+=path.stat().st_size
        if total+incoming>limits['work_bytes']:raise RuntimeError('Task storage budget exceeded; previous evidence is preserved')
    if shutil.disk_usage(root).free<limits['reserve_bytes']+incoming:
        raise RuntimeError('Insufficient free disk reserve; previous evidence is preserved')
    return total


def run_python(code,files,work_dir,mode='sample',check_cancelled=lambda:None,limits=None,source_contract=None,storage_root=None,ownership=None):
    if mode not in {'sample','full','diagnostic'}:raise ValueError('Invalid adapter execution mode')
    if not isinstance(code,str) or not 1<=len(code.encode())<=256*1024:raise ValueError('Adapter source must be 1–256 KiB')
    limits={**DEFAULT_LIMITS,**(limits or {})}
    if not 1<=limits['seconds']<=3600 or not 32<=limits['memory_mb']<=4096 or not .1<=limits['cpus']<=4 or not 8<=limits['pids']<=128 or not 1024<=limits['output_bytes']<=8*1024**3:
        raise ValueError('Adapter resource limits exceed local policy')
    if not 1024**2<=limits['work_bytes']<=32*1024**3 or not 256*1024**2<=limits['reserve_bytes']<=10*1024**3:
        raise ValueError('Task storage limits exceed local policy')
    Path(work_dir).mkdir(parents=True,exist_ok=True)
    storage_root=Path(storage_root or work_dir).resolve()
    if not Path(work_dir).resolve().is_relative_to(storage_root):raise ValueError('Task storage boundary does not contain the executor')
    check_storage(storage_root,limits,sum(Path(file['path']).stat().st_size for file in files))
    run_id=uuid4().hex;root=Path(work_dir).resolve()/('run-'+run_id)
    inp,out=root/'input',root/'output';inp.mkdir(parents=True,mode=0o755);out.mkdir(mode=0o777);os.chmod(out,0o777);os.chmod(root,0o755)
    owner_receipt=None
    if ownership:
        from .scoped_orphans import write_ownership
        owner_receipt=write_ownership(root,config=ownership,job_id=ownership['job_id'],attempt_id=ownership['attempt_id'])
    code_path=inp/'adapter.py';code_path.write_text(code);code_path.chmod(0o444)
    admitted=[];input_hashes={}
    for index,file in enumerate(files):
        check_cancelled();path=Path(file['path'])
        if path.is_symlink() or not path.is_file():raise ValueError('Input is not an admitted regular file')
        suffix=Path(file['name']).suffix.lower()
        copied=inp/(f'file-{index}'+suffix);shutil.copyfile(path,copied);copied.chmod(0o444)
        digest=sha(copied)
        if file.get('sha256') and digest!=file['sha256']:raise ValueError('Input hash changed before isolation')
        input_hashes[copied.name]=digest
        admitted.append({**{k:v for k,v in file.items() if k!='path'},'path':'/input/'+copied.name})
    envelope={'files':admitted,'source_contract':source_contract or {},'mode':mode}
    (inp/'run.json').write_text(json.dumps(envelope,allow_nan=False));(inp/'run.json').chmod(0o444)
    storage_ledger=None
    if ownership:
        from .config import read_config
        cfg=read_config()
        if cfg.get('storage_policy',{}).get('enabled'):
            from .storage_lifecycle import Ledger
            storage_ledger=Ledger(cfg)
            if cfg['instance_id']!=ownership['instance_id']:raise ValueError('Execution storage owner mismatch')
            identity=storage_ledger.register('execution_input',str(inp.relative_to(storage_ledger.root)),
                job_id=ownership['job_id'],attempt_id=ownership['attempt_id'],run_id=run_id,
                metadata={'strategy':'safe_copy_fallback','mount_contract':'arsia-adapter-owner-v1'})
            storage_ledger.refresh(identity)
    image=docker(['image','inspect',IMAGE,'--format','{{.Id}}'])
    result={'run_id':run_id,'mode':mode,'output_dir':str(out),'code_sha256':hashlib.sha256(code.encode()).hexdigest(),
            'contract_sha256':hashlib.sha256(json.dumps(source_contract,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),
            'limits':limits,'artifacts':[],'stdout':'','stderr':'','usage':{}}
    if image.returncode or not image.stdout.strip().startswith('sha256:'):
        result.update(status='unavailable',error={'type':'ImageUnavailable','origin':'trusted_host','message':'Build the dedicated adapter sandbox image; host execution is prohibited.'})
        (root/'execution.json').write_text(json.dumps(result,indent=2,allow_nan=False))
        if storage_ledger:
            try:
                identity=storage_ledger.register('candidate_output',str(out.relative_to(storage_ledger.root)),
                    job_id=ownership['job_id'],attempt_id=ownership['attempt_id'],run_id=run_id)
                storage_ledger.refresh(identity)
                storage_ledger.register('evidence',str((root/'execution.json').relative_to(storage_ledger.root)),
                    job_id=ownership['job_id'],attempt_id=ownership['attempt_id'],run_id=run_id)
            except Exception as exc:
                storage_ledger.journal('execution_storage_blocked',code=getattr(exc,'code','STORAGE_MEASUREMENT'))
        return result
    result['image']=image.stdout.strip()
    name='arsia-adapter-'+run_id;started=time.monotonic();status=None
    try:
        check_cancelled()
        result['transform_plans']=probe_transforms(result['image'],source_contract or {})
        result['transform_probe_image']=result['image']
        check_cancelled()
        created=docker(arguments(name,inp,out,result['image'],limits,owner_receipt))
        if created.returncode:
            (root/'process.log').write_text((created.stdout+created.stderr)[:200000]);(root/'process.log').chmod(0o600)
            raise ExecutorEnvironmentError('EXECUTOR_START_UNAVAILABLE', 'Dedicated sandbox container could not start; trusted operator can inspect its local process.log')
        while True:
            check_cancelled()
            check_storage(storage_root,limits)
            status_result=docker(['inspect',name,'--format','{{json .State}}'])
            if status_result.returncode:raise ExecutorEnvironmentError('EXECUTOR_STATE_UNAVAILABLE', 'Sandbox state became unavailable')
            status=json.loads(status_result.stdout)
            if not status['Running']:break
            _,size=safe_files(out,limits['output_bytes'],False)
            if time.monotonic()-started>limits['seconds']:
                result.update(status='timeout',error={'type':'Timeout','message':'Adapter exceeded its configured execution budget'})
                break
            time.sleep(.25)
        if not result.get('status'):
            if status.get('OOMKilled'):result.update(status='oom',error={'type':'OutOfMemory','message':'Adapter exceeded its memory allowance'})
            elif status.get('ExitCode')!=0:result.update(status='failed',error={'type':'ProcessExit','message':f"Adapter container exited with status {status.get('ExitCode')}"})
            elif (out/'runner-result.json').is_file() and not (out/'runner-result.json').is_symlink() and (out/'runner-result.json').stat().st_size<65536:
                reported=json.loads((out/'runner-result.json').read_text())
                result.update(bounded_report(reported,limits))
            else:result.update(status='failed',error={'type':'MissingEnvelope','message':'Adapter did not produce a bounded runner result'})
        result['artifacts'],size=safe_files(out,limits['output_bytes'])
        result['usage'].update(wall_seconds=time.monotonic()-started,output_bytes=size,container_exit=status.get('ExitCode') if status else None)
        # Logs stay in the private local run. They are never returned to the model.
        logs=docker(['logs',name]);(root/'process.log').write_text((logs.stdout+logs.stderr)[:200000]);(root/'process.log').chmod(0o600)
        for filename,digest in input_hashes.items():
            if sha(inp/filename)!=digest:raise RuntimeError('Read-only source input changed inside the sandbox')
        if sha(code_path)!=result['code_sha256']:raise RuntimeError('Read-only adapter source changed')
    except BaseException as exc:
        if not isinstance(exc,Exception):
            result.update(status='interrupted',error={'type':type(exc).__name__,'message':'Trusted worker interrupted sandbox execution; candidate was not admitted'})
            raise
        if isinstance(exc,ImportCancelled):
            result.update(status='cancelled',error={'type':'Cancelled','message':'Adapter execution was cancelled'})
            raise
        from .storage_lifecycle import StorageError
        result.update(status='failed',error={'type':type(exc).__name__,'origin':'trusted_host','message':str(exc)[:1000],
            **({'code':exc.code,'kind':exc.kind,'details':exc.details} if isinstance(exc, (ExecutorEnvironmentError,StorageError)) or type(exc).__name__=='TransformError' else {})})
    finally:
        # The only mutable container name is cryptographically unique and owned
        # by this invocation; no global stop/prune/kill operation is permitted.
        inspected=docker(['inspect',name,'--format','{{index .Config.Labels "arsia.import.adapter"}}'])
        if inspected.returncode==0 and inspected.stdout.strip()==name:docker(['rm','-f',name])
        (root/'execution.json').write_text(json.dumps(result,indent=2,allow_nan=False))
        if storage_ledger:
            try:
                identity=storage_ledger.register('candidate_output',str(out.relative_to(storage_ledger.root)),
                    job_id=ownership['job_id'],attempt_id=ownership['attempt_id'],run_id=run_id)
                storage_ledger.refresh(identity)
                storage_ledger.register('evidence',str((root/'execution.json').relative_to(storage_ledger.root)),
                    job_id=ownership['job_id'],attempt_id=ownership['attempt_id'],run_id=run_id)
            except Exception as exc:
                storage_ledger.journal('execution_storage_blocked',code=getattr(exc,'code','STORAGE_MEASUREMENT'))
    return result
