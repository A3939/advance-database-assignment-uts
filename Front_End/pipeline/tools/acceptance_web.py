"""Read the actual test release through ASGI and the product's Node provider.

Only a private, short-lived Unix socket is exposed. There is no preview port,
normal website rebinding, Studio store or model. This is API/service acceptance,
explicitly not a real browser test.
"""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from uuid import uuid4


def verify(output, result, expected):
    from tools.managed_acceptance import child_config
    cfg=child_config(output)
    from arsia_pipeline.query import catalog
    actual = catalog(str(result['release_id']))
    source = next(s for s in actual['sources'] if s['source_id'] == result['source_id'])
    assert source['batch_id'] == str(result['batch_id'])
    from arsia_pipeline.api import app
    from fastapi import FastAPI, Request
    from fastapi.responses import JSONResponse
    import uvicorn
    marker=uuid4().hex
    scope=FastAPI()
    @scope.middleware('http')
    async def read_only(request:Request, next_handler):
        if request.method!='GET' or request.url.path not in {'/catalog','/query','/__acceptance_identity'}:
            return JSONResponse({'error':'Read-only isolated acceptance'},status_code=403)
        return await next_handler(request)
    @scope.get('/__acceptance_identity')
    def identity():
        return {'instance_id':cfg['instance_id'],'test_session_id':cfg['test_session_id'],'marker':marker}
    scope.mount('/',app)
    with tempfile.TemporaryDirectory(prefix='arsia-source-read-') as directory:
        os.chmod(directory,0o700);socket=str(Path(directory)/'read.sock')
        server=uvicorn.Server(uvicorn.Config(scope,uds=socket,log_level='error',lifespan='off'))
        thread=threading.Thread(target=server.run,daemon=True);thread.start()
        try:
            for _ in range(100):
                if server.started:break
                if not thread.is_alive():raise RuntimeError('Isolated read service did not start')
                time.sleep(.05)
            else:raise RuntimeError('Isolated read service startup exceeded budget')
            request={'socket':socket,'instance_id':cfg['instance_id'],'test_session_id':cfg['test_session_id'],
                     'marker':marker,'release_id':str(result['release_id']),'batch_id':str(result['batch_id']),
                     'source_id':result['source_id'],'coverage':source['coverage'],
                     'expected':expected,'output':str(output/'web-service.json')}
            control=output/'web-read-request.json';control.write_text(json.dumps(request));control.chmod(0o600)
            done=subprocess.run(['node','--import','tsx','scripts/verify-published-service.ts',str(control)],
                cwd=Path(__file__).resolve().parents[2],capture_output=True,text=True,timeout=120)
            (output/'web-service.log').write_text(done.stdout+done.stderr)
            if done.returncode:raise RuntimeError('Published website service acceptance failed; see web-service.log')
        finally:
            server.should_exit=True;thread.join(timeout=10)
            if thread.is_alive():raise RuntimeError('Owned acceptance API did not stop')
