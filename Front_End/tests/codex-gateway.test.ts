import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {codexGateway} from '../src/server/imports/codex-gateway';
import {modelBudgetView} from '../src/server/agent/model-budget';
const task='00000000000000000000000000000000:11111111-1111-1111-1111-111111111111';
const secret='synthetic-private-gateway-token-01234567890';
const config=async()=>({mode:'local-test',agent_gateway_token:secret});
function request(extra:Record<string,string>={}) {return new Request('http://127.0.0.1:3100/api/imports/codex-model',{method:'POST',headers:{host:'127.0.0.1:3100',authorization:'Bearer '+secret,'content-type':'application/json','x-arsia-task':task,...extra},body:JSON.stringify({model:'gpt-6.1-sol',stream:true,input:[]})});}

test('actual Codex transport reserves and reconciles the shared ledger without disclosing content',async()=>{
  const root=mkdtempSync(join(tmpdir(),'arsia-gateway-test-'));const prior=process.env.OPENAI_API_KEY;process.env.OPENAI_API_KEY='synthetic-no-provider';
  try {
    const event={type:'response.completed',response:{id:'response-fixture',model:'gpt-6.1-sol',status:'completed',output:[{secret:'never logged'}],usage:{input_tokens:40,output_tokens:5,input_tokens_details:{cached_tokens:30}}}};
    const response=await codexGateway(request(),{runtimeConfig:config,auditRoot:root,fetcher:async(url,options)=>{
      assert.equal(url,'https://api.openai.com/v1/responses');const body=JSON.parse(options!.body as string);assert.equal(body.reasoning.effort,'high');assert.equal(body.max_output_tokens,24000);
      return new Response('event: response.completed\ndata: '+JSON.stringify(event)+'\n\n',{headers:{'content-type':'text/event-stream'}});
    }});
    assert.equal(response.status,200);assert.match(await response.text(),/response.completed/);
    const usage=modelBudgetView(root);assert.equal(usage.totals.requests,1);assert.equal(usage.totals.active,0);assert.equal(usage.totals.reportedInput,40);assert.equal(usage.totals.reportedOutput,5);assert.equal(usage.totals.reportedCachedInput,30);assert.equal(usage.usageComplete,true);
    assert.equal(JSON.stringify(usage).includes('never logged'),false);
  } finally {if(prior===undefined)delete process.env.OPENAI_API_KEY;else process.env.OPENAI_API_KEY=prior;}
});
test('provider refusal keeps usage unknown and forged task requests never reach the provider',async()=>{
  const root=mkdtempSync(join(tmpdir(),'arsia-gateway-failed-'));const prior=process.env.OPENAI_API_KEY;process.env.OPENAI_API_KEY='synthetic-no-provider';let calls=0;
  const options={runtimeConfig:config,auditRoot:root,fetcher:async()=>{calls++;return new Response('private provider payload',{status:503});}};
  try {
    assert.equal((await codexGateway(request({authorization:'Bearer invalid'}),options)).status,403);
    assert.equal(calls,0);
    const response=await codexGateway(request(),options);assert.equal(response.status,503);assert.equal((await response.text()).includes('private provider payload'),false);
    const view=modelBudgetView(root);assert.equal(view.totals.requests,1);assert.equal(view.totals.unknownRequests,1);assert.equal(view.totals.active,0);assert.equal(view.usageComplete,false);
  } finally {if(prior===undefined)delete process.env.OPENAI_API_KEY;else process.env.OPENAI_API_KEY=prior;}
});
