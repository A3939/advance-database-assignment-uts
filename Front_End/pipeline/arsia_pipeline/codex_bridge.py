"""Per-attempt capability bridge. Codex owns the loop; ARSIA owns authority.

Only two HTTP paths exist: stateless MCP and Responses transport. Tokens are
short-lived task capabilities, never real provider or database credentials.
"""
import hashlib
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import socket
import threading

from .agent import TOOLS, safe, spec
from .config import PROJECT, read_config
from .errors import AgentStalled, BudgetExhausted, ImportCancelled, NeedsInput, ValidationFailure, ModelUnavailable
from .intake_tools import TOOL_SPECS as INTAKE
from .public_sources import TOOL_SPECS as PUBLIC
from .task_workspace import admit_proposal

SPECS = {s['name']:s for s in [*TOOLS, *INTAKE, *PUBLIC,
    spec('get_workflow_state', 'Read current host state, version hashes, budget and unresolved gates.'),
    spec('submit_workspace', 'Submit proposals/contract.json and proposals/adapter.py as a candidate. File edits alone have no authority. Sample and full QA remain mandatory.',
         {'expected_contract_sha256':{'type':'string'},'expected_code_sha256':{'type':'string'}},
         ['expected_contract_sha256','expected_code_sha256'])]}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, default=str).encode()


class TaskBridge:
    def __init__(self, session, workspace):
        self.session, self.workspace = session, Path(workspace)
        self.lock = threading.RLock()
        self.model_token, self.tool_token = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self.closed = threading.Event()
        self.terminal = None
        self.connections = set()
        self.handlers = set()
        self.model_active = False
        self.native_calls = set()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), self.handler())
        self.server.daemon_threads = True
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.closed.set()
        for conn in list(self.connections):
            if conn.sock:
                try: conn.sock.shutdown(socket.SHUT_RDWR)
                except OSError: pass
            conn.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        for handler in list(self.handlers):
            handler.join(timeout=3)

    def snapshot(self):
        """Writable only to the trusted host, directly readable by Codex."""
        from .task_workspace import _json
        values = {'contract.json':self.session.contract, 'workflow.json':self.session.workflow_state(),
                  'diagnostics.json':self.session.diagnostics(bounded=False)}
        from .agent_facts import snapshot_views
        facts, index = snapshot_views(safe(self.session.tool_steps()))
        values.update({'facts.json': facts, 'index.json': index,
                       'issues.json': {'progress': self.session.progress_state(), 'diagnostics': values['diagnostics.json']}})
        if self.session.runtime_state.get('source_knowledge'):
            values['source-knowledge.json'] = self.session.runtime_state['source_knowledge']
        root = self.workspace / 'evidence'
        for name, value in values.items():
            path = root / name
            # Evidence directory cannot be changed by the sandbox process.
            temporary = path.with_suffix(path.suffix+'.tmp')
            temporary.write_bytes(_json(safe(value))); temporary.chmod(0o400); temporary.replace(path)
        path = root / 'adapter.py'
        temporary = path.with_suffix('.tmp'); temporary.write_text(self.session.code); temporary.chmod(0o400); temporary.replace(path)
        docs = root / 'documents'; docs.mkdir(exist_ok=True)
        for ident, doc in self.session.documents.items():
            target = docs / (hashlib.sha256(ident.encode()).hexdigest()+'.json')
            if target.exists(): continue
            text_path = doc.get('text_path')
            if text_path:
                from .config import ROOT
                source = Path(text_path)
                if source.resolve().is_relative_to(ROOT.resolve()) and source.is_file() and source.stat().st_size <= 4*1024**2:
                    target.write_bytes(_json({'document_id':ident, 'text':source.read_text(), 'untrusted_evidence':True}))
                    target.chmod(0o400)

    def tool(self, name, args):
        with self.lock:
            s = self.session
            s.check_budget()
            if self.closed.is_set() or self.terminal or s.ready:
                raise ValueError('Task no longer accepts tool work')
            if name not in SPECS or not isinstance(args, dict): raise ValueError('Unknown controlled tool')
            schema = SPECS[name]['parameters']
            if set(args)-set(schema.get('properties',{})) or set(schema.get('required',[]))-set(args):
                raise ValueError('Tool arguments do not match the allowed schema')
            s.usage['tool_calls'] += 1
            step = s.step('tool', name, args)
            s.active_tool = {'name':name,'arguments':args}
            s.persist()
            s.progress('agent', 'Codex is investigating evidence and validating an adapter', tool=name)
            status = 'succeeded'
            try:
                if name == 'get_workflow_state': output = s.workflow_state()
                elif name == 'submit_workspace': output = admit_proposal(s, self.workspace, **args)
                else: output = s.execute_tool(name, args)
            except (ImportCancelled, BudgetExhausted) as exc:
                self.terminal = exc; status = 'cancelled' if isinstance(exc, ImportCancelled) else 'paused'
                output = {'status':status,'message':str(exc)}
                if getattr(s, 'adaptation_v1', False) and not isinstance(exc, ImportCancelled):
                    from .capability_preflight import classified_blockers
                    output['details'] = {**getattr(exc, 'details', {}), 'blockers': classified_blockers(exc, operation=name)}
            except NeedsInput as exc:
                from .native_revision import NativeBoundary
                from .repair_context import should_stop
                if name in {'request_missing_information', 'request_engineering_repair'} or isinstance(exc, NativeBoundary) or should_stop(s, exc): self.terminal = exc
                status = 'paused' if self.terminal else 'needs_evidence'
                output = {'status':status,'message':str(exc),'questions':exc.questions,'details':safe(exc.details)}
            except Exception as exc:
                status = 'failed'
                output = {'status':'error','type':type(exc).__name__,'message':str(exc)[:3000]}
                if isinstance(exc, ValidationFailure): output.update(qa=safe(exc.qa), details=safe(exc.details))
                if getattr(s, 'adaptation_v1', False):
                    from .capability_preflight import classified_blockers, requires_system_change
                    output['details'] = safe({**getattr(exc, 'details', {}), 'blockers': classified_blockers(exc, operation=name)})
                    from .repair_context import should_stop
                    if should_stop(s, exc):
                        self.terminal = NeedsInput(str(exc), [], output['details'])
                        status = 'paused'
                signature = hashlib.sha256(encoded({'name':name,'message':str(exc)[:500]})).hexdigest()
                s.errors[signature] = s.errors.get(signature, 0)+1
                if s.errors[signature] >= 4:
                    self.terminal = AgentStalled('Repeated identical tool failure; evidence saved.', output)
                elif s.errors[signature] >= 2: output['next_action'] = 'Change diagnostic approach; do not repeat the same failed operation.'
            except BaseException as exc:
                self.terminal = exc; status = 'interrupted'; output = {'status':'interrupted'}
            s.finish_step(step, safe(output), status)
            s.active_tool = {}
            s.persist('cancelled' if isinstance(self.terminal, ImportCancelled) else
                      'needs_input' if self.terminal else 'ready_to_publish' if s.ready else 'investigating')
            self.snapshot()
            result_path = self.workspace/'evidence/results'/f'{step}.json'
            result_path.parent.mkdir(exist_ok=True)
            result_path.write_bytes(encoded(safe(output))); result_path.chmod(0o400)
            result = {'step_id':step,'result_file':f'evidence/results/{step}.json',
                      'current_contract_sha256':hashlib.sha256(b'').hexdigest()}
            from .registry import digest_json
            result.update(current_contract_sha256=digest_json(s.contract),current_code_sha256=hashlib.sha256(s.code.encode()).hexdigest())
            data = encoded(safe(output))
            from .agent_facts import VERSION, project
            # Explicit paginated reads stay exact; routine results are compact.
            # The separate full file hash names its bytes, not an admission.
            targeted = name in {'read_task_state', 'read_source_evidence', 'read_document'}
            maximum = 48000 if targeted else 12288 if status != 'succeeded' else 6144
            result['output'] = project(safe(output), max_bytes=maximum)
            result['projection'] = {'version': VERSION, 'full_result_bytes': len(data),
                'returned_output_bytes': len(encoded(result['output'])),
                'result_file_sha256': hashlib.sha256(data).hexdigest(),
                'retrieval': {'tool':'read_task_state', 'arguments':{'kind':'tool_result','step_id':step,'pointer':'','max_chars':4000}},
                'note':'Use a specific JSON Pointer from the result shape; full durable results include host_context.'}
            return result, status in {'failed','paused','cancelled','interrupted'}

    def rpc(self, message):
        ident, method = message.get('id'), message.get('method')
        if ident is None: return None
        def response(value): return {'jsonrpc':'2.0','id':ident,'result':value}
        if method == 'initialize':
            return response({'protocolVersion':message.get('params',{}).get('protocolVersion','2024-11-05'),
                'capabilities':{'tools':{}},'serverInfo':{'name':'arsia-import-task','version':'1.0'}})
        if method == 'ping': return response({})
        if method == 'tools/list':
            return response({'tools':[{'name':s['name'],'description':s['description'],'inputSchema':s['parameters']} for s in SPECS.values()]})
        if method == 'tools/call':
            params = message.get('params') or {}
            try: value, error = self.tool(params.get('name'), params.get('arguments') or {})
            except Exception as exc:
                if isinstance(exc,(ImportCancelled,BudgetExhausted)): self.terminal = exc
                value, error = {'error':type(exc).__name__,'message':str(exc)[:1000]}, True
            return response({'content':[{'type':'text','text':encoded(value).decode()}],'isError':error})
        return {'jsonrpc':'2.0','id':ident,'error':{'code':-32601,'message':'Method not found'}}

    def guard_model_event(self, event):
        """Host gate BEFORE forwarding an executable call to the CLI.

        Code Mode dispatches MCP calls itself; those are charged separately by
        tool(). The VM invocation is also a bounded action, even if it calls no
        MCP tool. Direct delegation/native shell cannot inherit task authority.
        """
        if not getattr(self.session, 'bounded_repair_v1', False):
            return
        items = [event.get('item', {})]
        if event.get('type') in {'response.completed', 'response.incomplete'}:
            items += event.get('response', {}).get('output', [])
        for item in items:
            if item.get('type') not in {'function_call', 'custom_tool_call'}:
                continue
            namespace, name = item.get('namespace'), item.get('name', '')
            allowed = ((namespace == 'functions' and name in {'exec', 'wait'}) or
                       (namespace is None and name in {'exec', 'wait', 'functions.exec', 'functions.wait'}))
            if not allowed:
                exc = NeedsInput('The model requested an action outside this task tool authority.', [],
                                 {'namespace':namespace, 'name':name, 'trusted_origin':'model_transport_gate'})
                exc.code = 'TASK_ACTION_BOUNDARY'
                exc.kind = 'system_configuration'
                self.terminal = exc
                raise exc
            ident = item.get('call_id') or item.get('id')
            if not ident:
                raise ValueError('Executable call has no stable identity')
            with self.lock:
                if ident in self.native_calls:
                    continue
                s = self.session
                s.check_budget()
                self.native_calls.add(ident)
                s.usage['tool_calls'] += 1
                step = s.step('tool', 'codex.' + name, {'call_id':ident, 'authority':'bounded_code_mode'})
                s.finish_step(step, {'status':'authorized_for_dispatch',
                    'execution_success':'unknown; MCP and resource receipts record subsequent outcomes'})
                s.persist()

    def relay(self, handler, body):
        s = self.session
        compact = getattr(handler,'path','') == '/v1/responses/compact'
        with self.lock:
            if self.closed.is_set() or self.terminal or s.ready: raise ValueError('Task stopped')
            if self.model_active: raise ValueError('Parallel model requests prohibited')
            s.check_budget(new_model=True)
            if body.get('model') != 'gpt-6.1-sol' or (not compact and body.get('stream') is not True): raise ValueError('Model policy mismatch')
            s.usage['model_calls'] += 1
            step = s.step('model','codex.compact' if compact else 'codex.responses',{'model_call':s.usage['model_calls'],'model':'gpt-6.1-sol','reasoning_effort':None if compact else 'high',
                'request_shape':{key:{'type':type(value).__name__,'length':len(value) if isinstance(value,(list,dict,str)) else None} for key,value in body.items()}})
            s.persist(); self.model_active = True
        (self.workspace.parent / f'model-request-{step}.json').write_bytes(encoded(body))
        cfg = read_config()
        from .model_transport import connection
        conn = connection(cfg,605)
        self.connections.add(conn)
        receipt, status, finalized = None, 'failed', False
        def finalize():
            nonlocal finalized
            if finalized: return
            with self.lock:
                s.finish_step(step, {**(receipt or {'usage':None,'status':status}),
                    'agent_policy':s.agent_policy,'runtime':'codex','usage_known':bool(receipt and receipt.get('usage'))}, status)
                s.persist('cancelled' if isinstance(self.terminal, ImportCancelled) else
                          'needs_input' if self.terminal else
                          s.status if getattr(s,'status',None) in {'cancelled','needs_input','paused','published','no_change'} else
                          'ready_to_publish' if s.ready else 'investigating')
                self.model_active = False
                finalized = True
        try:
            conn.request('POST','/api/imports/codex-model',body=encoded(body),headers={
                'Content-Type':'application/json','Authorization':'Bearer '+cfg['agent_gateway_token'],
                'X-Arsia-Operation':'compact' if compact else 'responses',
                'X-Arsia-Task':str(cfg['instance_id'])+':'+str(s.id)})
            upstream = conn.getresponse()
            handler.send_response(upstream.status)
            handler.send_header('Content-Type','text/event-stream' if upstream.status == 200 and not compact else 'application/json')
            handler.send_header('Connection','close'); handler.end_headers(); handler.close_connection = True
            if upstream.status != 200:
                handler.wfile.write(upstream.read(8192)); handler.wfile.flush()
                raise ModelUnavailable('Codex model transport refused request.', {'http_status':upstream.status})
            if compact:
                payload = upstream.read(4*1024**2+1)
                if len(payload)>4*1024**2: raise ValueError('Compaction result too large')
                r = json.loads(payload)
                receipt = {'id':r.get('id'),'model':r.get('model'),'requested_model':body['model'],'usage':r.get('usage'),
                           'status':'completed' if r.get('object')=='response.compaction' else 'failed'}
                status = 'succeeded' if receipt['status']=='completed' else 'failed'
                finalize(); handler.wfile.write(payload); handler.wfile.flush(); return
            pending = b''
            while not self.closed.is_set():
                chunk = upstream.read1(65536)
                if not chunk: break
                pending += chunk
                forward = []
                while b'\n' in pending:
                    line, pending = pending.split(b'\n',1)
                    if line.startswith(b'data: '):
                        try: event = json.loads(line[6:])
                        except ValueError: event = {}
                        self.guard_model_event(event)
                        if event.get('type') in {'response.completed','response.incomplete','response.failed'}:
                            r = event.get('response',{})
                            receipt = {k:r.get(k) for k in ('id','model','usage','status')}
                            status = 'succeeded' if r.get('status') == 'completed' else 'failed'
                            # Finalize BEFORE exposing completed to Codex: it may
                            # immediately send the next request while EOF is pending.
                            finalize()
                    forward.append(line + b'\n')
                if len(pending) > 8*1024**2: raise ValueError('SSE event too large')
                if forward:
                    handler.wfile.write(b''.join(forward)); handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            status = 'cancelled' if self.closed.is_set() else 'failed'
        except (ModelUnavailable, NeedsInput, BudgetExhausted, ImportCancelled) as exc: self.terminal = exc
        finally:
            conn.close(); self.connections.discard(conn)
            finalize()

    def handler(self):
        bridge = self
        class Handler(BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.1'
            def log_message(self, *_): pass
            def reply(self, status, value=None):
                data = encoded(value) if value is not None else b''
                self.send_response(status); self.send_header('Content-Type','application/json')
                self.send_header('Content-Length',str(len(data))); self.end_headers()
                self.wfile.write(data)
            def do_GET(self): self.reply(405)
            def do_DELETE(self): self.reply(405)
            def do_POST(self):
                current = threading.current_thread()
                bridge.handlers.add(current)
                try: self.post()
                finally: bridge.handlers.discard(current)
            def post(self):
                token = bridge.tool_token if self.path == '/mcp' else bridge.model_token if self.path in {'/v1/responses','/v1/responses/compact'} else None
                if token is None or not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+token):
                    self.reply(403); return
                if bridge.closed.is_set(): self.reply(410); return
                if self.headers.get('Content-Encoding') or self.headers.get('Transfer-Encoding'):
                    self.reply(415, {'error':'Unsupported encoding'}); return
                try:
                    size = int(self.headers.get('Content-Length','0'))
                    if not 0 < size <= 4*1024**2: self.reply(413); return
                    self.connection.settimeout(610)
                    body = json.loads(self.rfile.read(size))
                    if not isinstance(body,dict): raise ValueError('Object required')
                    if self.path == '/mcp':
                        result = bridge.rpc(body); self.reply(200 if result else 202, result)
                    else: bridge.relay(self,body)
                except (ImportCancelled,BudgetExhausted) as exc:
                    bridge.terminal = exc; self.reply(409,{'error':str(exc)})
                except (ValueError,TypeError) as exc:
                    with (bridge.workspace.parent/'rejections.jsonl').open('a') as log:
                        log.write(json.dumps({'path':self.path,'type':type(exc).__name__,'message':str(exc)[:200]})+'\n')
                    self.reply(400,{'error':'Invalid scoped request'})
                except (BrokenPipeError,ConnectionResetError): pass
                except BaseException as exc:
                    bridge.terminal = exc
                    try: self.reply(500,{'error':'Task bridge interrupted'})
                    except OSError: pass
        return Handler
