"""Real child handshake regressions; no model, SQL, Docker or production hooks."""
import fcntl
import json
import signal
import sys
import time
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from storage_hardening_harness import Children

@pytest.fixture
def children(tmp_path):
    owner=Children(tmp_path/'children',time.monotonic()+30)
    yield owner
    assert all(x['stopped'] for x in owner.stop())

def events(child):
    return [json.loads(x) for x in child['result'].with_suffix('.handshake.jsonl').read_text().splitlines()]

@pytest.mark.parametrize('chunks',[1,4])
def test_real_stream_once_per_request(children,chunks):
    p=children.spawn(None,'barrier-probe','upload_partial',probe_chunks=chunks)
    value=children.finish(p)
    assert value['requests'][0]['chunk_sizes']==[1]*chunks+[0]
    seen=events(p)
    assert len([x for x in seen if x['state']=='ready'])==1
    assert len([x for x in seen if x['state']=='released'])==1
    assert len([x for x in seen if x['state']=='callback'])==chunks+1

def test_two_requests_both_pause(children):
    p=children.spawn(None,'barrier-probe','upload_partial',probe_requests=2)
    first=p['receipt']['actual_barrier'];children.release(p)
    p['receipt']['request_id']+='-1'
    second=children.await_ready(p)
    assert first['request_id']!=second['request_id']
    assert first['barrier_id']!=second['barrier_id']
    assert len(children.finish(p)['requests'])==2
    assert len([x for x in events(p) if x['state']=='released'])==2

def test_selected_occurrence(children):
    p=children.spawn(None,'barrier-probe','upload_partial',occurrence=2)
    assert p['receipt']['actual_barrier']['occurrence']==2
    children.finish(p)
    assert len([x for x in events(p) if x['state']=='ready'])==1

@pytest.mark.parametrize('failure',['eof','wrong','timeout'])
def test_first_pause_is_not_silently_skipped(children,failure):
    p=children.spawn(None,'barrier-probe','upload_partial',barrier_timeout=.4 if failure=='timeout' else 5)
    if failure=='eof':p['p'].stdin.close()
    if failure=='wrong':p['p'].stdin.write(b'{"command":"CONTINUE"}\n');p['p'].stdin.flush()
    assert p['p'].wait(timeout=10)!=0
    last=events(p)[-1]
    assert last['state']==('timeout' if failure=='timeout' else 'release_failed')
    assert last['error_type']=={'eof':'EOFError','wrong':'ValueError','timeout':'TimeoutError'}[failure]
    assert not p['result'].exists()

def test_sigkill_releases_actual_flock(children):
    p=children.spawn(None,'barrier-probe','upload_partial')
    with p['result'].with_suffix('.lock').open('a') as lock:
        with pytest.raises(BlockingIOError):fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        receipt=children.finish(p,kill=True)
        assert receipt['returncode']==-signal.SIGKILL
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        fcntl.flock(lock,fcntl.LOCK_UN)

def test_real_parent_exit_closes_first_release_pipe(tmp_path):
    """The intermediary parent exits; the real orphan reports EOF, never success."""
    import os,subprocess
    from storage_test_barrier import read_line
    ready_r,ready_w=os.pipe();done_r,done_w=os.pipe()
    output=tmp_path/'orphan.json'
    pipeline=Path(__file__).resolve().parents[1]
    child_code='''
import os,sys,json,argparse
from pathlib import Path
from storage_barrier_probe import run
try:
 run(argparse.Namespace(output=Path(sys.argv[1]),phase='upload_partial',ready_fd=int(sys.argv[2]),barrier_timeout=5,occurrence=1,child_id='orphan',scenario='parent-exit',request_id='request-1',probe_requests=1,probe_chunks=3))
except BaseException as exc:
 os.write(int(sys.argv[3]),(json.dumps({'error':type(exc).__name__,'pid':os.getpid()})+'\\n').encode())
 sys.exit(1)
'''
    parent_code='''
import os,subprocess,sys
p=subprocess.Popen([sys.executable,'-B','-c',sys.argv[1],*sys.argv[2:]],stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,pass_fds=(int(sys.argv[3]),int(sys.argv[4])))
assert sys.stdin.readline().strip()=='EXIT'
os._exit(0)
'''
    parent=subprocess.Popen([sys.executable,'-B','-c',parent_code,child_code,str(output),str(ready_w),str(done_w)],
        stdin=subprocess.PIPE,pass_fds=(ready_w,done_w),env={**os.environ,'PYTHONPATH':str(pipeline)+os.pathsep+str(pipeline/'tools'),'PYTHONDONTWRITEBYTECODE':'1'})
    os.close(ready_w);os.close(done_w)
    try:
        ready=read_line(ready_r,10);assert ready['state']=='ready'
        parent.stdin.write(b'EXIT\n');parent.stdin.flush();parent.stdin.close()
        assert parent.wait(timeout=5)==0
        done=read_line(done_r,10);assert done['error']=='EOFError'
        assert done['pid']==ready['pid'] and not output.exists()
        with output.with_suffix('.lock').open('a') as lock:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    finally:
        if parent.poll() is None:parent.kill();parent.wait(timeout=5)
        os.close(ready_r);os.close(done_r)
