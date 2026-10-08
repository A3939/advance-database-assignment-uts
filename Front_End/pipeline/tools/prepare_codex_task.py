"""Export an existing session read-only and verify a pinned Codex MCP config.

Does not start Codex inference, enqueue/retry an import, edit a DB or publish.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arsia_pipeline import store
from arsia_pipeline.agent import safe
from arsia_pipeline.agent_policy import policy
from arsia_pipeline.config import PROJECT, ROOT
from arsia_pipeline.contract_diagnostics import unresolved_diagnostics
from arsia_pipeline.registry import digest_json
from arsia_pipeline.task_workspace import create_workspace


def prepare(job_id, destination, profile='expanded-v1'):
    destination = Path(destination).absolute()
    if destination.exists() or not destination.resolve().is_relative_to((PROJECT/'artifacts/autonomous-imports').resolve()):
        raise ValueError('Use a fresh destination below artifacts/autonomous-imports')
    with store.connect() as conn, conn.transaction():
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        session=conn.execute('SELECT * FROM agent_sessions WHERE job_id=%s',(job_id,)).fetchone()
        if not session:raise ValueError('No durable agent session exists for this job')
        steps=conn.execute("SELECT id,attempt_id,name,status,arguments,result FROM agent_steps WHERE session_id=%s AND kind='tool' ORDER BY id",(session['id'],)).fetchall()
        latest=conn.execute('SELECT id FROM attempts WHERE job_id=%s ORDER BY number DESC LIMIT 1',(job_id,)).fetchone()
    saved=session['checkpoint'];contract=saved.get('contract',{});code=saved.get('code','')
    documents={}
    for key,doc in saved.get('documents',{}).items():
        name=doc.get('text_path')
        if name:
            path=Path(name)
            if path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()) or not path.is_file() or path.stat().st_size>4*1024**2:
                raise ValueError('Registered source document is outside the expected local evidence boundary')
            documents[key]=path.read_text()
    diagnostics=unresolved_diagnostics(steps,contract_sha256=digest_json(contract),code_sha256=hashlib.sha256(code.encode()).hexdigest(),attempt_id=latest['id'],bounded=False)
    settings=policy(profile)
    destination.mkdir(parents=True,mode=0o700)
    task=destination/'task';control=destination/'control';control.mkdir(mode=0o700)
    identity={'job_id':str(job_id),'session_id':str(session['id']),'attempt_id':str(latest['id']),
        'source_status':session['status'],'historical_model_policy':safe(saved.get('agent_policy')),
        'note':'Read-only export; does not resume or migrate the source session'}
    manifest=create_workspace(task,contract=contract,code=code,diagnostics=diagnostics,steps=steps,documents=documents,
        sdk=(PROJECT/'pipeline/AUTONOMOUS_CONTRACT.md').read_text(),policy=settings,identity=identity)
    binary=PROJECT/'codex-0.159.3-macos-arm64/bin/codex'
    package=json.loads((binary.parent.parent/'codex-package.json').read_text())
    if package.get('version')!='0.159.3' or package.get('target')!='aarch64-apple-darwin':
        raise ValueError('Unexpected Codex runtime package')
    version=subprocess.run([str(binary),'--version'],check=True,capture_output=True,text=True).stdout.strip()
    if version!='codex-cli 0.159.3':raise ValueError('Unexpected Codex binary version')
    home=control/'codex-home';home.mkdir(mode=0o700)
    q=json.dumps
    config=f'''model = {q(settings['model'])}
model_reasoning_effort = {q(settings['reasoning_effort'])}
approval_policy = "never"
sandbox_mode = "read-only"
web_search = "disabled"
[shell_environment_policy]
inherit = "none"
[mcp_servers.arsia_evidence]
command = {q(str(PROJECT/'pipeline/.venv/bin/python'))}
args = ["-m", "arsia_pipeline.task_evidence_mcp", "--workspace", {q(str(task))}]
required = true
startup_timeout_sec = 15
tool_timeout_sec = 30
enabled_tools = ["list_task_evidence", "read_task_evidence"]
[mcp_servers.arsia_evidence.env]
PYTHONPATH = {q(str(PROJECT/'pipeline'))}
'''
    (home/'config.toml').write_text(config);(home/'config.toml').chmod(0o600)
    env={key:value for key,value in os.environ.items() if key in {'PATH','HOME','TMPDIR','LANG','SYSTEMROOT'}}
    env['CODEX_HOME']=str(home)
    result=subprocess.run([str(binary),'mcp','list','--json'],env=env,cwd=task,check=True,capture_output=True,text=True,timeout=30)
    servers=json.loads(result.stdout)
    receipt={'binary':str(binary),'version':version,'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
        'requested_model':settings['model'],'reasoning_effort':settings['reasoning_effort'],
        'config_sha256':hashlib.sha256(config.encode()).hexdigest(),'mcp_config':servers,
        'model_calls':0,'database_mutations':0,'execution_ready':False,
        'remaining':'Connect a task-scoped trusted worker, external execution boundary, cancellation and lifecycle receipts before enabling Codex inference.'}
    (control/'preflight.json').write_text(json.dumps(receipt,indent=2));(control/'preflight.json').chmod(0o600)
    return {'workspace':str(task),'evidence_files':len(manifest['files']),'codex_version':version,'model_calls':0,'execution_ready':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--job-id',required=True);parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();print(json.dumps(prepare(args.job_id,args.output)))
