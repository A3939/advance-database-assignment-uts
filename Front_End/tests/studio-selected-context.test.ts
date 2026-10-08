import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import type { ResponseStreamEvent } from 'openai/resources/responses/responses';
import { StudioStore, uuid } from '../src/server/studio/store';
import { saveResource } from '../src/server/studio/resources';
import { ResearchCollector, researchHistory, selectedResearchContext } from '../src/server/studio/collector';
import { runAgent, type ModelStream } from '../src/server/agent/runner';
import { createOfficialProvider, loadOfficialSnapshot } from '../src/server/official-data';
import { DEFAULT_FILTERS } from '../src/services/config';

const context={filters:{...DEFAULT_FILTERS,source:'NSW' as const},metric:'crashes' as const,notes:'Private draft notes',references:'Private reference prose'};
function fixture(){
 const root=mkdtempSync(join(tmpdir(),'arsia-selected-context-'));
 const store=new StudioStore(join(root,'research.sqlite'));
 return {store,close(){store.close();rmSync(root,{recursive:true,force:true});}};
}

test('explicit selected research remains available when general history excludes it, with immutable scope and bounded rows',async()=>{
 const x=fixture();try{
  const study=await saveResource(x.store,{requestId:uuid(),definitionId:'trend',context});
  const selected=study.runs[0];
  const later={...structuredClone(selected),id:uuid(),question:'Unselected private question',answer:'x'.repeat(20001)};
  study.runs.push(later);
  study.context={...context,filters:{...DEFAULT_FILTERS,source:'VIC'}};
  assert.deepEqual(researchHistory(study,{...selected,id:uuid()}),[]);
  const result=selectedResearchContext(study,[selected.id])!;
  assert.equal(result.resources.length,1);
  assert.equal(result.resources[0].runId,selected.id);
  assert.equal(result.resources[0].attempt,selected.attempt);
  assert.equal(result.resources[0].scope.filters.source,'NSW');
  assert.equal(result.resources[0].resource!.bindingHash,selected.resource!.bindingHash);
  const excerpt=result.resources[0].evidence[0].result as {rows:unknown[];totalRows:number;truncated:boolean};
  assert.equal(excerpt.rows.length,40);assert.equal(excerpt.truncated,true);assert.ok(excerpt.totalRows>40);
  assert.equal(result.resources[0].evidence[0].query!.tool,'studio_resource:trend');
  assert.equal(result.resources[0].evidence[0].ref.attempt,selected.attempt);
  assert.equal(JSON.stringify(result).includes(later.id),false);
  assert.equal(JSON.stringify(result).includes('Unselected private question'),false);
  result.resources[0].scope.filters.source='All';
  assert.equal(study.runs[0].context.filters.source,'NSW','selected context owns a snapshot, not mutable study references');
  assert.equal(selectedResearchContext(study,[]),undefined);
 }finally{x.close();}
});

test('selected context rejects foreign, incomplete, duplicated, oversized and tampered selections',async()=>{
 const x=fixture();try{
  const study=await saveResource(x.store,{requestId:uuid(),definitionId:'trend',context});
  const id=study.runs[0].id;
  for(const ids of [[uuid()],[id,id],Array.from({length:17},uuid)])assert.throws(()=>selectedResearchContext(study,ids));
  const incomplete=structuredClone(study);incomplete.runs[0].status='failed';assert.throws(()=>selectedResearchContext(incomplete,[id]),/completed/);
  const changed=structuredClone(study);changed.runs[0].resource!.unit='Wrong unit';assert.throws(()=>selectedResearchContext(changed,[id]),/integrity|binding/);
  const noEvidence=structuredClone(study);delete noEvidence.runs[0].resource;noEvidence.runs[0].evidence=[];assert.throws(()=>selectedResearchContext(noEvidence,[id]),/evidence|conversation answer/);
  const tooLarge=structuredClone(study);delete tooLarge.runs[0].resource;tooLarge.runs[0].evidence[0].description='x'.repeat(65000);assert.throws(()=>selectedResearchContext(tooLarge,[id]),/too large/);
 }finally{x.close();}
});

test('selected knowledge-only conversation survives truncated history without gaining evidence authority',async()=>{
 const x=fixture();try{
  let study=x.store.create('Question context',context);
  const begun=x.store.beginRun(study.id,uuid(),'Explain the distinction between counts and risk.',false,undefined,{mode:'explore'});
  const collector=new ResearchCollector(x.store,study.id,begun.run);
  await collector.accept({type:'message',text:'Counts describe recorded events; risk also needs a suitable exposure measure.',simulated:false});
  await collector.accept({type:'done',model:'explicit-zero-model-fixture'});collector.persist();study=x.store.get(study.id);
  const original=structuredClone(study.runs[0]);
  study.runs.push({...structuredClone(original),id:uuid(),question:'Unselected later question',answer:'x'.repeat(20001)});
  study.context={...context,filters:{...DEFAULT_FILTERS,source:'VIC'}};
  assert.deepEqual(researchHistory(study,{...original,id:uuid()}),[]);
  const selected=selectedResearchContext(study,[original.id])!,item=selected.resources[0];
  assert.equal(item.runId,original.id);assert.equal(item.attempt,original.attempt);
  assert.equal(item.scope.filters.source,'NSW');
  assert.equal(item.conversation?.question,original.question);assert.equal(item.conversation?.answer,original.answer);
  assert.equal(item.conversation?.assurance,'unverified_narrative');
  assert.deepEqual(item.conversation?.truncated,{question:false,answer:false});
  assert.deepEqual(item.evidence,[]);assert.deepEqual(item.views,[]);assert.equal(item.resource,undefined);
  assert.match(selected.notice,/does not grant evidence authority/);
  assert.ok(!JSON.stringify(selected).includes('Unselected later question'));
  assert.ok(!JSON.stringify(selected).includes('Private draft notes'));
  item.scope.filters.source='All';item.conversation!.answer='Caller-side modification';
  assert.equal(study.runs[0].answer,original.answer);assert.equal(study.runs[0].context.filters.source,'NSW');
 }finally{x.close();}
});

test('conversation selections bound long text and reject incomplete, malformed and non-conversation records',async()=>{
 const x=fixture();try{
  let study=x.store.create('Bounded conversation',context);
  const begun=x.store.beginRun(study.id,uuid(),'Question');
  const collector=new ResearchCollector(x.store,study.id,begun.run);
  await collector.accept({type:'message',text:'Bounded narrative. '.repeat(2000),simulated:false});
  await collector.accept({type:'done',model:'explicit-zero-model-fixture'});collector.persist();study=x.store.get(study.id);
  const id=study.runs[0].id,selected=selectedResearchContext(study,[id])!;
  assert.equal(selected.resources[0].conversation!.answer.length,12000);
  assert.equal(selected.resources[0].conversation!.truncated.answer,true);
  assert.equal(selected.resources[0].conversation!.answerCharacters,study.runs[0].answer.length);
  assert.deepEqual(selected.resources[0].evidence,[]);
  for(const change of [{status:'running'},{status:'failed'},{status:'stopped'},{status:'interrupted'},{answer:''},{answer:null},{question:null},{origin:'analytics'},{mode:'draft'},{mode:'revise'},{attempt:0}]){
   const invalid=structuredClone(study);Object.assign(invalid.runs[0],change);
   assert.throws(()=>selectedResearchContext(invalid,[id]),/completed|conversation|attempt/);
  }
  const foreign=x.store.create('Other study',context);
  assert.throws(()=>selectedResearchContext(foreign,[id]),/completed/);
 }finally{x.close();}
});

test('Explore selected-context reaches the actual runner separately from history and still completes through a fresh metadata tool',async()=>{
 const x=fixture();try{
  let study=await saveResource(x.store,{requestId:uuid(),definitionId:'trend',context});
  const selected=selectedResearchContext(study,[study.runs[0].id])!;
  const begun=x.store.beginRun(study.id,uuid(),'What does this chart measure?',false,undefined,{mode:'explore',selectedRunIds:[study.runs[0].id]});
  const collector=new ResearchCollector(x.store,study.id,begun.run),snapshot=await loadOfficialSnapshot();let localStubCalls=0,toolResults=0;
  const stream:ModelStream=async params=>(async function*(){
   assert.match(String(params.instructions),/Explicitly selected saved research/);
   assert.ok(String(params.instructions).includes(JSON.stringify(selected)));
   assert.match(String(params.instructions),/Continue to query fresh registered-tool evidence/);
   assert.equal(params.model,'explicit-zero-model-fixture');
   if(localStubCalls++===0){
    assert.equal(params.tool_choice,'required');
    yield {type:'response.completed',response:{status:'completed',output:[{type:'function_call',name:'dataset_metadata',arguments:JSON.stringify({source:'NSW'}),call_id:'metadata-call'}]}} as unknown as ResponseStreamEvent;
   }else{
    yield {type:'response.output_text.delta',delta:'The selected chart shows recorded crash counts, not a causal explanation [E1].'} as ResponseStreamEvent;
    yield {type:'response.completed',response:{status:'completed',output:[]}} as unknown as ResponseStreamEvent;
   }
  })();
  for await(const event of runAgent({context:{page:'/studio',filters:DEFAULT_FILTERS},message:begun.run.question,history:[]},{model:'explicit-zero-model-fixture',stream,signal:new AbortController().signal,snapshot,service:createOfficialProvider(snapshot),research:{mode:'explore',selectedContext:selected,notes:'',references:'',skipPresentation:()=>false}})){
   if(event.type==='tool_result')toolResults++;await collector.accept(event);
  }
  study=collector.persist();
  assert.equal(localStubCalls,2);assert.equal(toolResults,1);assert.equal(study.runs.at(-1)!.status,'complete');
  assert.equal(study.runs.at(-1)!.evidence[0].query!.tool,'dataset_metadata');assert.equal(study.runs[0].id,selected.resources[0].runId);
 }finally{x.close();}
});

test('selected saved context alone cannot bypass the runner fresh-evidence completion gate',async()=>{
 const x=fixture();try{
  const study=await saveResource(x.store,{requestId:uuid(),definitionId:'trend',context});
  const selected=selectedResearchContext(study,[study.runs[0].id]),snapshot=await loadOfficialSnapshot();let done=0;
  await assert.rejects(async()=>{
   for await(const event of runAgent({context:{page:'/studio',filters:DEFAULT_FILTERS},message:'Explain the selected chart',history:[]},{model:'explicit-zero-model-fixture',signal:new AbortController().signal,snapshot,service:createOfficialProvider(snapshot),research:{mode:'explore',selectedContext:selected,notes:'',references:'',skipPresentation:()=>false},stream:async()=>(async function*(){yield {type:'response.output_text.delta',delta:'Unsupported direct answer'} as ResponseStreamEvent;yield {type:'response.completed',response:{status:'completed',output:[]}} as unknown as ResponseStreamEvent;})()}))if(event.type==='done')done++;
  },/MODEL_INCOMPLETE/);
  assert.equal(done,0);
 }finally{x.close();}
});
