"""Tool-only pause of a receipted backup helper, portable across Docker Desktop."""
import json
import subprocess
from arsia_pipeline.storage_lifecycle import atomic_json, now
from storage_test_barrier import read_line


def archive_with_live_helper(session, barrier, output):
    from arsia_pipeline import test_session
    original=test_session.docker;selected={}
    def wrapped(*args,**kwargs):
        if args and args[0]=='create' and 'storage_archive import create' in str(args[-1]):
            name=args[args.index('--name')+1]
            # Block SIGUSR1 before announcing readiness; sigwait cannot lose an
            # early release. SIGTERM cleanly ends this trusted test-only helper.
            prefix="import signal,sys,json;signal.signal(signal.SIGTERM,lambda *a:sys.exit(0));signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGUSR1});signal.alarm(120);print(json.dumps({'state':'ready','helper':"+repr(name)+"}),flush=True);signal.sigwait({signal.SIGUSR1});signal.alarm(0);"
            value=original(*args[:-1],prefix+args[-1],**kwargs)
            selected.update(id=value.decode().strip(),name=name,original_code=args[-1]);return value
        if not args or args[:2]!=('start','--attach') or args[-1]!=selected.get('id'):
            return original(*args,**kwargs)
        name=selected['name'];command=['docker',*args]
        log=output.with_suffix('.helper-stderr.log').open('wb')
        process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=log)
        atomic_json(output.with_suffix('.helper-cli.json'),{'pid':process.pid,'helper':name,'container_id':selected['id'],'at':now(),'owned_by_child':True})
        try:
            ready=read_line(process.stdout.fileno(),30)
            assert ready=={'state':'ready','helper':name}
            with session.ledger.connect() as db:
                intents=[json.loads(x['details']) for x in db.execute("SELECT details FROM journal WHERE event='helper_intent'")]
            intent=next(x for x in intents if x['name']==name)
            atomic_json(output.with_suffix('.live-helper.json'),{'at':now(),'intent':intent,
                'cli_pid':process.pid,'container_id':selected['id'],'original_code':selected['original_code'],'ready':ready,
                'injection':'stdout ready; blocked SIGUSR1 + sigwait release; SIGTERM clean stop; 120s orphan bound'})
            barrier('backup_helper_running')
            original('kill','--signal','USR1',selected['id'])
            data,_=process.communicate(timeout=120)
            if process.returncode:raise subprocess.CalledProcessError(process.returncode,command,output=data)
            return data
        finally:log.close()
    test_session.docker=wrapped
    try:return session.archive_database()
    finally:test_session.docker=original
