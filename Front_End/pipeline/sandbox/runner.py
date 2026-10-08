"""Untrusted adapter container entrypoint; host validates every artifact again."""
import importlib.util
import json
from pathlib import Path
import resource
import sys
import time
import traceback

sys.path.insert(0,"/opt/arsia")
from arsia_pipeline.adapter_sdk import AdapterContext

started=time.monotonic()
context=None
result={"status":"failed"}
try:
    envelope=json.loads(Path('/input/run.json').read_text())
    context=AdapterContext(envelope['source_contract'],envelope['files'],'/output',envelope['mode'])
    spec=importlib.util.spec_from_file_location('task_adapter','/input/adapter.py')
    adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
    if not callable(getattr(adapter,'adapt',None)):raise ValueError('Adapter must define adapt(ctx)')
    adapter.adapt(context)
    result={'status':'succeeded','counts':context.counts}
except BaseException as exc:
    frames=traceback.extract_tb(exc.__traceback__)
    result={'status':'failed','error':{'type':type(exc).__name__[:80],
        'message':'Adapter raised an exception; use the exception type, adapter line and trusted QA diagnostics. Full exception text remains in the local diagnostic artifact.',
        'frames':[{'file':Path(f.filename).name[:80],'line':f.lineno,'function':f.name[:80]} for f in frames[-8:]]}}
    Path('/output/diagnostic.txt').write_text(traceback.format_exc()[:100000])
finally:
    if context:context.close()
    result['usage']={'seconds':time.monotonic()-started,'ru_maxrss_bytes':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024}
    Path('/output/runner-result.json').write_text(json.dumps(result,allow_nan=False))
