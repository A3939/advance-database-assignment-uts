"""Read-only independent oracle verification of a stopped, owned acceptance lab.

Starts/stops only its marker-matched container. Uses the actual in-process GET
API and a database-enforced read-only DSN; never starts a worker/model, changes
the lab runtime, republishes or connects to the website/main databases.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace


def run(args):
    lab=args.lab.resolve(); output=args.output.resolve()
    owner=json.loads((lab/'ownership.json').read_text())
    original=json.loads((lab/'lab/runtime.json').read_text())
    container=json.loads(subprocess.check_output(['docker','inspect',owner['container']],text=True))[0]
    label='arsia.knowledge-test' if 'arsia.knowledge-test' in container['Config']['Labels'] else 'arsia.acceptance'
    assert container['Config']['Labels'].get(label)==owner['marker']==original['instance_id']
    assert container['Name'].lstrip('/')==owner['name']
    assert not container['State']['Running'], 'Do not interrupt an active acceptance lab'
    output.mkdir(parents=True,mode=0o700)
    subprocess.run(['docker','start',owner['container']],check=True,capture_output=True)
    started=time.monotonic()
    try:
        from psycopg.conninfo import conninfo_to_dict,make_conninfo
        import psycopg
        from arsia_pipeline import config
        parts=conninfo_to_dict(original['dsn'])
        parts['port']=subprocess.check_output(['docker','port',owner['container'],'5432/tcp'],text=True).strip().rsplit(':',1)[1]
        parts['options']='-c default_transaction_read_only=on'
        # This is an audit config, not a change to the accepted instance config.
        config.ROOT=lab/'lab';config.CONFIG=output/'readonly-runtime.json'
        cfg={**original,'dsn':make_conninfo(**parts)}
        config.CONFIG.write_text(json.dumps(cfg));config.CONFIG.chmod(0o600)
        os.environ['ARSIA_IMPORT_CONFIG']=str(config.CONFIG)
        for _ in range(100):
            try:
                with psycopg.connect(cfg['dsn']) as conn:
                    assert conn.execute('SHOW transaction_read_only').fetchone()[0]=='on'
                    assert conn.execute('SELECT instance_id FROM local_instance').fetchone()[0]==owner['marker']
                break
            except psycopg.OperationalError:time.sleep(.2)
        else:raise RuntimeError('Owned acceptance database unavailable')
        from arsia_pipeline import api,store,agent
        from arsia_pipeline.codex_runtime import CodexRuntime
        def forbidden(*a,**kw):raise AssertionError('Read-only acceptance must never invoke an import model')
        agent.gateway=forbidden;CodexRuntime.run=forbidden
        from fastapi.testclient import TestClient
        import verify_autonomous_sources as verifier
        calls=[]
        client=TestClient(api.app)
        class InProcessGetOnly:
            def __init__(self,via_website):
                assert via_website is False
            def get(self,path):
                assert path.startswith(('/jobs/','/query?'))
                calls.append(path)
                response=client.get(path);response.raise_for_status();return response.json()
        verifier.GetOnlyAPI=InProcessGetOnly
        with store.connect() as conn:
            selected=conn.execute("SELECT id,result FROM jobs WHERE status='succeeded' ORDER BY created_at LIMIT 1").fetchone()
            assert selected, 'No published initial job in this owned lab'
            states=selected['result']['source_contract']['source']['jurisdiction']
            assert (states if isinstance(states,list) else [states])==[args.state.upper()]
            before=[str(row['release_id']) for row in conn.execute('SELECT release_id FROM current_release')]
        report=verifier.verify(SimpleNamespace(state=args.state,oracle=args.oracle.resolve(),job_id=selected['id'],expect='published',via_website=False,before_release_id=None))
        with store.connect() as conn:
            after=[str(row['release_id']) for row in conn.execute('SELECT release_id FROM current_release')]
        report.update(wall_seconds=time.monotonic()-started,api_transport='actual FastAPI in-process GET; no browser',
            real_model_calls=0,release_unchanged=before==after,readonly_dsn=True,api_calls=calls,
            audit_time=datetime.now(timezone.utc).isoformat())
        (output/'acceptance.json').write_text(json.dumps(report,indent=2,default=str))
        print(json.dumps({key:report[key] for key in ('status','passed','failed','wall_seconds','release_unchanged','geography_verification')}))
        return 0 if report['status']=='passed' and before==after else 1
    except Exception as exc:
        (output/'failure.json').write_text(json.dumps({'type':type(exc).__name__,'message':str(exc).replace(parts.get('password','__no_password__'),'[redacted]')},indent=2))
        raise
    finally:
        actual=subprocess.check_output(['docker','inspect',owner['container'],'--format','{{index .Config.Labels "'+label+'"}}'],text=True).strip()
        assert actual==owner['marker']
        subprocess.run(['docker','stop',owner['container']],check=True,capture_output=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lab',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--state',choices=('sa','act','tas'),required=True)
    parser.add_argument('--oracle',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('Use a fresh evidence directory')
    raise SystemExit(run(args))
