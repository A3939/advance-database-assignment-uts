import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync,existsSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { spawn } from 'node:child_process';
import { ModelBudget,ModelBudgetError,taskBudget,modelBudgetView } from '../src/server/agent/model-budget';
import { ModelSseAudit } from '../src/server/agent/model-sse-audit';

const directory=()=>mkdtempSync(join(tmpdir(),'arsia-budget-test-'));
test('separate processes compete for two durable global slots; restarts cannot forget active calls',async()=>{
  const root=directory();new ModelBudget(root).close();
  const program=`const {ModelBudget,taskBudget}=require('./src/server/agent/model-budget');const db=new ModelBudget(process.argv[1]);try{db.start(taskBudget('ask',process.argv[2]),process.argv[2]);console.log('admitted');}catch(e){console.log(e.code||'unexpected');}finally{db.close();}`;
  const output=await Promise.all(Array.from({length:4},(_,i)=>new Promise<string>((resolve,reject)=>{
    const child=spawn(process.execPath,['--require','tsx/cjs','-e',program,root,'request-'+i],{stdio:['ignore','pipe','pipe']});let text='',errors='';
    child.stdout.on('data',b=>text+=b);child.stderr.on('data',b=>errors+=b);child.on('error',reject);child.on('exit',code=>code===0?resolve(text.trim()):reject(Error(errors)));
  })));
  assert.equal(output.filter(v=>v==='admitted').length,2);assert.equal(output.filter(v=>v==='MODEL_BUSY').length,2);
  const snapshot=modelBudgetView(root);assert.equal(snapshot.totals.requests,2);assert.equal(snapshot.totals.active,2);assert.equal(snapshot.totals.unknownRequests,2);
});
test('expired owner consumption survives recovery; cumulative limit includes failed and interrupted attempts',()=>{
  const root=directory(),task=taskBudget('ask','same-task');
  let db=new ModelBudget(root);db.start(task,'abandoned',1000);db.close();
  db=new ModelBudget(root);assert.equal(db.view(1001).totals.active,1);
  for(let i=1;i<12;i++) {db.start(task,'retry-'+i,300000+i);db.finish(task.taskId,'retry-'+i,'failed',undefined,300000+i);}
  assert.throws(()=>db.start(task,'over-budget',400000),e=>e instanceof ModelBudgetError&&e.code==='MODEL_TASK_LIMIT');
  assert.equal(db.view(400000).totals.requests,12);assert.equal(db.view(400000).totals.unknownRequests,12);
  assert.equal(db.view(400000).totals.active,0);db.close();
});
test('Imports gateways share one slot; reported cached input is not counted twice and late receipts are idempotent',()=>{
  const db=new ModelBudget(directory()),a=taskBudget('imports-codex','codex'),b=taskBudget('imports-agent','agent');
  db.start(a,'first');assert.throws(()=>db.start(b,'second'),ModelBudgetError);
  db.finish(a.taskId,'first','completed',{input_tokens:100,output_tokens:10,input_tokens_details:{cached_tokens:80}});
  db.finish(a.taskId,'first','completed',{input_tokens:900,output_tokens:900});
  db.start(b,'second');db.finish(b.taskId,'second','cancelled');
  const v=db.view();assert.equal(v.totals.reportedInput,100);assert.equal(v.totals.reportedOutput,10);assert.equal(v.totals.reportedCachedInput,80);assert.equal(v.totals.unknownRequests,1);assert.equal(v.tokenBudget,null);db.close();
});
test('read-only empty view does not create or migrate a ledger',()=>{
  const root=directory();assert.equal(modelBudgetView(root).totals.requests,0);assert.equal(existsSync(join(root,'usage.sqlite')),false);
});
test('split terminal SSE records exact usage once; an event header alone never certifies usage',async()=>{
  const receipts:unknown[]=[];const parser=new ModelSseAudit(async v=>{receipts.push(v);});
  const text='event: response.completed\ndata: '+JSON.stringify({type:'response.completed',response:{id:'r',model:'gpt-6.1-sol',status:'completed',usage:{input_tokens:4,output_tokens:3}}})+'\n\n';
  await parser.push(Buffer.from(text.slice(0,26)));assert.equal(parser.terminal,false);
  for(let i=26;i<text.length;i+=7) await parser.push(Buffer.from(text.slice(i,i+7)));
  assert.equal(parser.terminal,true);assert.equal(receipts.length,1);
  assert.deepEqual(receipts[0],{id:'r',model:'gpt-6.1-sol',status:'completed',usage:{input_tokens:4,output_tokens:3}});
  await parser.push(Buffer.from(text));assert.equal(receipts.length,1);
});
