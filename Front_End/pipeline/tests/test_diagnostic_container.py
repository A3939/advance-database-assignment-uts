"""Actual Docker boundary checks, intentionally bypassing AST preflight.

Doing so tests the access-control layer independently of static rejection.
"""
import hashlib
import json
from pathlib import Path

import pytest

from arsia_pipeline.isolated_executor import IMAGE, docker, run_python


def test_diagnostic_container_denies_escapes_and_preserves_input(tmp_path):
    if docker(['image','inspect',IMAGE]).returncode:
        pytest.skip('Explicit reviewed Docker image required')
    raw = tmp_path/'data.csv'; raw.write_text('id,value\n1,2\n')
    secret = tmp_path/'host-secret.txt'; secret.write_text('synthetic-host-canary')
    original = hashlib.sha256(raw.read_bytes()).hexdigest()
    code = '''import json, socket, os
from pathlib import Path
def adapt(ctx):
    outcomes = {}
    for key,path in {"host_secret":HOST_SECRET,"docker_socket":"/var/run/docker.sock", "credentials":"/root/.aws/credentials", "other_job":"/input/../other-job/data.csv"}.items():
        try: Path(path).read_bytes(); outcomes[key] = "UNEXPECTED_ACCESS"
        except (PermissionError, FileNotFoundError, OSError): outcomes[key] = "denied"
    for key,path in {"input_write":list(ctx.input_paths.values())[0],"root_write":"/etc/arsia-escape","host_write":HOST_SECRET}.items():
        try: Path(path).write_text("changed"); outcomes[key] = "UNEXPECTED_WRITE"
        except (PermissionError, FileNotFoundError, OSError): outcomes[key] = "denied"
    try:
        socket.create_connection(("1.1.1.1",443), timeout=.5).close(); outcomes["network"]="UNEXPECTED_NETWORK"
    except OSError: outcomes["network"]="denied"
    outcomes["input_read"] = Path(list(ctx.input_paths.values())[0]).read_text() == "id,value\\n1,2\\n"
    outcomes["secret_env"] = not any(k in os.environ for k in ("OPENAI_API_KEY","ARSIA_IMPORT_CONFIG","ARSIA_TOOL_CAPABILITY"))
    (ctx.output_dir/"report.json").write_text(json.dumps(outcomes))
'''.replace('HOST_SECRET',repr(str(secret)))
    run = run_python(code,[{'id':'f','name':raw.name,'path':str(raw),'size':raw.stat().st_size,'sha256':original}],
                     tmp_path/'runs',mode='diagnostic',source_contract={},
                     limits={'seconds':10,'memory_mb':128,'pids':16,'output_bytes':1024*1024})
    assert run['status'] == 'succeeded', run
    report = json.loads((Path(run['output_dir'])/'report.json').read_text())
    assert report == {**dict.fromkeys(['host_secret','docker_socket','credentials','other_job','input_write',
                                     'root_write','host_write','network'],'denied'), 'input_read':True,'secret_env':True}
    assert hashlib.sha256(raw.read_bytes()).hexdigest() == original
    assert secret.read_text() == 'synthetic-host-canary'


def test_diagnostic_wall_limit_is_enforced_by_host(tmp_path):
    if docker(['image','inspect',IMAGE]).returncode:
        pytest.skip('Explicit reviewed Docker image required')
    result = run_python('def adapt(ctx):\n    while True: pass\n',[],tmp_path,
                        mode='diagnostic',source_contract={},limits={'seconds':1,'memory_mb':64,'pids':8,'output_bytes':1024*1024})
    assert result['status'] == 'timeout'
    assert result['usage']['wall_seconds'] < 10
