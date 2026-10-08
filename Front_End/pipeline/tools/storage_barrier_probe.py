"""Real subprocess / ASGI streaming probe without a database or Docker."""
import asyncio
import fcntl
import os
from starlette.requests import Request
from storage_test_barrier import RequestBarrier
from arsia_pipeline.storage_lifecycle import atomic_json


def run(a):
    lock = a.output.with_suffix('.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    barrier = RequestBarrier(output=a.output, phase=a.phase, ready_fd=a.ready_fd,
        timeout=a.barrier_timeout, occurrence=a.occurrence,
        identity={'child_id':a.child_id,'scenario':a.scenario,
                  'instance_id':None,'session_id':None,'job_id':None})
    async def requests():
        result=[]
        for n in range(a.probe_requests):
            request_id=a.request_id if n==0 else a.request_id+'-'+str(n)
            messages=[{'type':'http.request','body':b'x','more_body':True} for _ in range(a.probe_chunks)]
            messages.append({'type':'http.request','body':b'','more_body':False})
            async def receive():return messages.pop(0)
            request=Request({'type':'http','method':'PUT','path':'/upload'}, receive=receive)
            sizes=[]
            async for chunk in request.stream():
                sizes.append(len(chunk));barrier('upload_partial',request_id=request_id)
            result.append({'request_id':request_id,'chunk_sizes':sizes})
        return result
    try:
        result=asyncio.run(requests())
        atomic_json(a.output,{'requests':result,'pid':os.getpid()})
    finally:
        lock.close()
