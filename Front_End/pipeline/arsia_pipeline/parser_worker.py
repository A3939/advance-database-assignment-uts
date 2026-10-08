"""Fixed trusted parser subprocess. Never imports a user module or executes code."""
import json
import os
import resource
import signal
import sys
import threading
import time


def main():
    from . import parser_guard
    parser_guard.IN_CHILD=True
    request=json.loads(sys.stdin.buffer.read(parser_guard.PACKET_BYTES+1))
    seconds=request['seconds'];memory=request['memory_bytes']
    if not 0<seconds<=parser_guard.SECONDS or not 64*1024**2<=memory<=parser_guard.MEMORY_BYTES:
        raise ValueError('Invalid parser budget')
    try:
        resource.setrlimit(resource.RLIMIT_AS,(memory,memory))
    except ValueError:
        if sys.platform != 'darwin':raise
        # Darwin rejects RLIMIT_AS/DATA/RSS; the independent parent monitors
        # resident bytes and kills the process group. No hard-limit claim.

    resource.setrlimit(resource.RLIMIT_CPU,(int(seconds)+1,int(seconds)+1))
    resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))
    resource.setrlimit(resource.RLIMIT_FSIZE,(0,0))
    signal.signal(signal.SIGALRM,signal.SIG_DFL)
    signal.setitimer(signal.ITIMER_REAL,seconds)
    owner=request['owner_pid']
    if os.getppid()!=owner:os._exit(125)
    def watch_owner():
        while True:
            if os.getppid()!=owner:os._exit(125)
            time.sleep(.25)
    threading.Thread(target=watch_owner,daemon=True).start()
    def send(value):
        raw=json.dumps(value,ensure_ascii=False,allow_nan=False).encode()+b'\n'
        if len(raw)>parser_guard.PACKET_BYTES:raise parser_guard.ParserResourceError('Parser output packet exceeds its byte budget.')
        sys.stdout.buffer.write(raw);sys.stdout.buffer.flush()
    try:
        operation=request['operation'];args=request['arguments']
        if operation in {'detect','rows'}:
            from .intakereaders import detect_tables,iter_table
            if operation=='detect':send({'type':'data','value':detect_tables(*args)})
            else:
                for row in iter_table(*args):send({'type':'data','value':row})
        elif operation in {'native_detect','native_rows'}:
            from .readers import inspect_file,iter_rows
            if operation=='native_detect':send({'type':'data','value':inspect_file(*args)})
            else:
                for row in iter_rows(*args):send({'type':'data','value':row})
        elif operation=='pdf':
            from .document_parser import pdf_text
            send({'type':'data','value':pdf_text(*args)})
        elif operation=='format':
            from .intakereaders import detect_format
            send({'type':'data','value':detect_format(*args)})
        elif operation=='zip_inventory':
            from .archive_parser import inventory
            send({'type':'data','value':inventory(*args)})
        elif operation=='zip_member_hash':
            from .archive_parser import member_hash
            send({'type':'data','value':member_hash(*args)})
        elif operation=='json_signature':
            from .representation_binding import json_signature
            send({'type':'data','value':json_signature(*args)})
        elif operation=='pdf_locator':
            import base64
            from .metadata_extractors import resolve_locator
            send({'type':'data','value':resolve_locator(base64.b64decode(args[0],validate=True),*args[1:])})
        else:raise ValueError('Unknown parser operation')
        send({'type':'end'})
    except (BrokenPipeError,ConnectionError):
        pass
    except BaseException as exc:
        send({'type':'error','class':type(exc).__name__,'message':str(exc)[:4000],
              'details':getattr(exc,'details',None),'questions':getattr(exc,'questions',None),'code':getattr(exc,'code',None)})
