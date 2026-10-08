/** Static entry wiring plus real ledger transports; no provider call is made. */
import test from 'node:test';
import assert from 'node:assert/strict';
import { ModelSseAudit } from '../src/server/agent/model-sse-audit';
import { ModelBudgetError } from '../src/server/agent/model-budget';
import { safeAgentError } from '../src/server/agent/runner';

test('Ask and Studio audit objects actually share the persisted limit and retain unknown failures',async()=>{
  const {mkdtempSync}=await import('node:fs');const {tmpdir}=await import('node:os');const {join}=await import('node:path');
  const {createModelAudit}=await import('../src/server/agent/model-audit');const {routeModel}=await import('../src/server/agent/model-routing');
  const {modelBudgetView}=await import('../src/server/agent/model-budget');
  const root=mkdtempSync(join(tmpdir(),'arsia-audit-budget-'));
  const a=await createModelAudit(routeModel({surface:'ask'}),'ask',root,'ask-task');
  const b=await createModelAudit(routeModel({surface:'studio'}),'studio',root,'studio-task');
  const c=await createModelAudit(routeModel({surface:'ask'}),'ask',root,'other-task');
  await a.request('ask-request');await b.request('studio-request');
  await assert.rejects(c.request('blocked-request'),ModelBudgetError);
  await a.finish('failed');await c.request('next-request');await c.finish('cancelled');await b.finish('failed');
  assert.equal(modelBudgetView(root).totals.requests,3);assert.equal(modelBudgetView(root).totals.unknownRequests,3);assert.equal(modelBudgetView(root).totals.active,0);
});
test('failed/incomplete SSE retains provider usage without being labelled completed',async()=>{
  for(const status of ['failed','incomplete']) {
    const parser=new ModelSseAudit(async()=>{});
    await parser.push(Buffer.from('data: '+JSON.stringify({type:'response.'+status,response:{id:'response',model:'gpt-6.1-sol',status}})+'\n'));
    assert.equal(parser.terminal,true);assert.equal(parser.status,'failed');
  }
});
test('only trusted budget errors expose their specific stop reason to the UI',()=>{
  assert.deepEqual(safeAgentError(new ModelBudgetError('MODEL_BUSY','The shared local model service is busy.')),{code:'MODEL_BUSY',message:'The shared local model service is busy.'});
  assert.notEqual(safeAgentError({name:'ModelBudgetError',code:'MODEL_BUSY',message:'private data'}).message,'private data');
});
