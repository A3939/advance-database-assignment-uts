"""Host-only parser process boundary, preserving reader semantics and row order.

No generated code enters this process. The worker accepts fixed operations,
streams bounded JSON packets and has OS CPU/address-space/file limits plus an
independent SIGALRM wall deadline. The parent polls cancellation every 100 ms.
"""
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

IN_CHILD = False
SECONDS = 120
MEMORY_BYTES = 1536 * 1024**2
PACKET_BYTES = 8 * 1024**2
OUTPUT_BYTES = 4 * 1024**3


class ParserFailure(RuntimeError):
    kind = 'system_fault'
    code = 'HOST_PARSER_FAILURE'


def resident_bytes(pid):
    if sys.platform == 'darwin':
        result = subprocess.run(['/bin/ps','-o','rss=','-p',str(pid)],capture_output=True,text=True,timeout=1)
        return int(result.stdout.strip())*1024 if result.returncode == 0 and result.stdout.strip().isdigit() else None
    return None  # Linux uses RLIMIT_AS; other platforms fail at child setup.


class ParserResourceError(RuntimeError):
    kind = 'unsupported_capability'
    code = 'HOST_PARSER_RESOURCE_LIMIT'


def required():
    # Docker adapters already have the stricter OS boundary and complete task
    # wall budget; do not add nested processes inside an untrusted adapter.
    return not IN_CHILD and not Path('/.dockerenv').exists()


def packets(operation, arguments, cancelled=lambda: None, *, seconds=SECONDS, memory_bytes=MEMORY_BYTES):
    if not 0 < seconds <= SECONDS or not 64 * 1024**2 <= memory_bytes <= MEMORY_BYTES:
        raise ValueError('Invalid trusted parser budget')
    cancelled()
    source = str(Path(__file__).resolve().parent.parent)
    program = "import sys;sys.path.insert(0,sys.argv[1]);from arsia_pipeline.parser_worker import main;main()"
    payload = json.dumps({'operation':operation,'arguments':arguments,'seconds':seconds,'memory_bytes':memory_bytes,'owner_pid':os.getpid()}, default=str).encode()
    if len(payload) > PACKET_BYTES:
        raise ParserResourceError('Parser request exceeds the bounded control-message size.')
    env = {'PATH':os.environ.get('PATH','/usr/bin:/bin'),'LANG':'C.UTF-8','PYTHONDONTWRITEBYTECODE':'1','OPENBLAS_NUM_THREADS':'1'}
    process = subprocess.Popen([sys.executable,'-I','-c',program,source],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL,env=env,start_new_session=True)
    selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ)
    start=time.monotonic();buffer=b'';total=0;ended=False;last_memory_check=0.0
    try:
        process.stdin.write(payload);process.stdin.close()
        while True:
            cancelled()
            instant=time.monotonic()
            if sys.platform=='darwin' and instant-last_memory_check>=.1 and process.poll() is None:
                used=resident_bytes(process.pid);last_memory_check=instant
                if used is not None and used>memory_bytes:
                    raise ParserResourceError('Host parser exceeded its sampled resident-memory budget (100 ms polling; transient overshoot is possible).')
            if time.monotonic()-start > seconds+1:
                raise ParserResourceError('Host parser exceeded its wall-clock budget; no input was modified.')
            if not selector.select(.1):
                continue
            chunk=os.read(process.stdout.fileno(),65536)
            if not chunk:
                break
            buffer+=chunk;total+=len(chunk)
            if total>OUTPUT_BYTES:
                raise ParserResourceError('Host parser exceeded its streamed output budget.')
            while b'\n' in buffer:
                raw,buffer=buffer.split(b'\n',1)
                if len(raw)>PACKET_BYTES:
                    raise ParserResourceError('Host parser row/metadata packet exceeds its byte budget.')
                packet=json.loads(raw)
                if packet['type']=='data':
                    yield packet['value']
                elif packet['type']=='end':
                    ended=True
                elif packet['type']=='error':
                    from .errors import NeedsInput, ValidationFailure, UnsupportedCapability
                    if packet['class']=='NeedsInput':raise NeedsInput(packet['message'],packet.get('questions'),packet.get('details'))
                    if packet['class']=='UnsupportedCapability':raise UnsupportedCapability(packet.get('code','PARSER_UNSUPPORTED'),packet['message'])
                    if packet['class']=='ValidationFailure':raise ValidationFailure(packet['message'],details=packet.get('details'))
                    if packet['class']=='MetadataError':
                        from .metadata_extractors import MetadataError
                        raise MetadataError(packet['code'],packet['message'],packet.get('details'))
                    if packet['class'] in {'MemoryError','ParserResourceError'}:raise ParserResourceError(packet['message'])
                    raise ParserFailure(packet['message'])
                else:
                    raise ParserResourceError('Host parser protocol is invalid.')
            if len(buffer)>PACKET_BYTES:
                raise ParserResourceError('Host parser packet exceeds its byte budget.')
        code=process.wait(timeout=1)
        if code or buffer or not ended:
            raise ParserResourceError('Host parser exited before complete output (resource limit or parser failure).')
    finally:
        selector.close()
        if process.poll() is None:
            try:
                os.killpg(process.pid,signal.SIGKILL)
            except (ProcessLookupError,PermissionError):
                # A short parse can exit between poll and group signalling;
                # some Darwin runtimes also restrict the group signal. Reap
                # the exact Popen child, never search/kill by process name.
                if process.poll() is None:
                    process.kill()
        process.wait(timeout=2)
        process.stdout.close()


def call(operation, arguments, cancelled=lambda: None):
    values=list(packets(operation,arguments,cancelled))
    if len(values)!=1:raise ParserResourceError('Invalid host parser scalar response')
    return values[0]
