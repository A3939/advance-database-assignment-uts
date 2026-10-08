import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { StudioStore, uuid } from '../src/server/studio/store';
import { saveResource } from '../src/server/studio/resources';
import { exportStudy, exportStudyBundle } from '../src/server/studio/export';
import { ResearchCollector } from '../src/server/studio/collector';
import { loadOfficialSnapshot, createOfficialProvider } from '../src/server/official-data';
import { executeAnalysisTool } from '../src/server/agent/tools';
import { renderStudyReport } from '../src/server/studio/report-renderer';
import { DEFAULT_FILTERS } from '../src/services/config';
import { escapeXml } from '../src/services/studio-figure';
import type { Study, ResearchContext } from '../src/services/studio-contracts';
const context:ResearchContext={filters:{...DEFAULT_FILTERS,source:'NSW'},metric:'crashes',notes:'PRIVATE_NOTES_SENTINEL',references:'PRIVATE_REFERENCE_SENTINEL'};
function fixture(){const dir=mkdtempSync(join(tmpdir(),'arsia-selected-export-'));const store=new StudioStore(join(dir,'research.sqlite'));return{store,close(){store.close();rmSync(dir,{recursive:true,force:true});}};}
function action(store:StudioStore,s:Study,a:Record<string,unknown>){return store.action(s.id,{...a,revision:s.revision});}
async function resource(store:StudioStore,s:Study,id='trend',query={}){return saveResource(store,{requestId:uuid(),definitionId:id,context,query,target:{studyId:s.id,revision:s.revision}});}
function entries(bytes:Buffer){const map=new Map<string,Buffer>();for(let p=0;bytes.readUInt32LE(p)===0x04034b50;){const n=bytes.readUInt16LE(p+26),extra=bytes.readUInt16LE(p+28),size=bytes.readUInt32LE(p+18),start=p+30+n+extra;map.set(bytes.subarray(p+30,p+30+n).toString(),bytes.subarray(start,start+size));p=start+size;}return map;}
function saveText(store:StudioStore,s:Study,runId:string,name:string,content:string,provenance:unknown={}){const bytes=Buffer.from(content);return store.saveFile(s.id,runId,{bytes,provenance,artifact:{id:'a'.repeat(48),name,kind:name.endsWith('.py')?'py':'txt',bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex'),href:'/ignored',expiresAt:'2000-01-01'}});}
test('selected export excludes unselected runs, private notes, findings, history and attachments without altering the store',async()=>{
 const x=fixture();try{let s=await resource(x.store,x.store.create('Public title',context));const chosen=s.runs[0];s=await resource(x.store,s,'severity');const privateRun=s.runs[1];privateRun.answer='UNSELECTED_ANSWER_SENTINEL';x.store.updateRun(s.id,privateRun);s=x.store.get(s.id);
 s=action(x.store,s,{type:'finding',kind:'Hypothesis',title:'UNSELECTED_FINDING_SENTINEL',explanation:'Do not publish this',runId:privateRun.id,evidenceIds:['E1']});
 saveText(x.store,s,chosen.id,'private.txt','UNSELECTED_ATTACHMENT_SENTINEL');saveText(x.store,s,chosen.id,'unrelated.py','UNBOUND_CODE_SENTINEL');s=x.store.get(s.id);s=action(x.store,s,{type:'snapshot',label:'UNSELECTED_HISTORY_SENTINEL'});s=action(x.store,s,{type:'block_add',kind:'resource',runId:chosen.id,refId:chosen.resource!.id});const before=x.store.get(s.id);
 const zip=exportStudy(x.store,s),files=entries(zip),all=[...files.values()].map(b=>b.toString()).join('\n');
 for(const secret of ['PRIVATE_NOTES_SENTINEL','PRIVATE_REFERENCE_SENTINEL','UNSELECTED_ANSWER_SENTINEL','UNSELECTED_FINDING_SENTINEL','UNSELECTED_ATTACHMENT_SENTINEL','UNBOUND_CODE_SENTINEL','UNSELECTED_HISTORY_SENTINEL'])assert.ok(!all.includes(secret),`Unselected material leaked: ${secret}`);
 assert.ok(![...files.keys()].some(n=>n.includes(privateRun.id)));assert.ok([...files.keys()].some(n=>n.includes(chosen.id)&&n.endsWith('.csv')));assert.deepEqual(x.store.get(s.id),before);assert.equal(x.store.versions(s.id).length,1);
 }finally{x.close();}
});
test('finding-only reports identify the precise selected source and export its data without unrelated views',async()=>{
 const x=fixture();try{let s=await resource(x.store,x.store.create('Finding only',context),'severity');const run=s.runs[0];s=action(x.store,s,{type:'finding',kind:'Observation',title:'The category is recorded',explanation:'Only a source-linked observation.',runId:run.id,evidenceIds:['E1']});s=action(x.store,s,{type:'block_add',kind:'finding',refId:s.findings[0].id});const report=renderStudyReport(s);assert.match(report.html,/<p class="note">Sources: \[1\] E1<\/p>/);const files=entries(exportStudy(x.store,s));assert.ok([...files].some(([n,b])=>n.endsWith('.csv')&&b.includes(Buffer.from('Fatal'))));assert.ok(![...files.keys()].some(n=>n.startsWith('figures/')));
 }finally{x.close();}
});
test('resource tables retain their saved measure unit instead of the study metric',async()=>{
 const x=fixture();try{let s=await resource(x.store,x.store.create('Shares',context),'severity',{severityMode:'share'});const run=s.runs[0];s=action(x.store,s,{type:'block_add',kind:'table',runId:run.id,refId:run.views[0].id});const report=renderStudyReport(s);assert.match(report.html,/<p class="scope">[^<]+ · fraction of recorded crashes<\/p>/);
 }finally{x.close();}
});

test('actual core_metrics source definitions, coverage and references survive the selected report envelope',async()=>{
 const x=fixture();try{let s=x.store.create('Actual metrics',context);const {run}=x.store.beginRun(s.id,uuid(),'Read metrics');const snapshot=await loadOfficialSnapshot(),parameters={source:null,dateRange:null};
 const result=await executeAnalysisTool('core_metrics',parameters,{page:'/studio',filters:context.filters},createOfficialProvider(snapshot),snapshot);
 run.question='PRIVATE_QUESTION_SENTINEL';const c=new ResearchCollector(x.store,s.id,run);await c.accept({type:'evidence',evidence:{id:'E1',title:'Recorded metrics',description:'Actual official snapshot query',result,query:{tool:'core_metrics',parameters,requestedContext:{page:'/studio',filters:context.filters},assurance:{parameters:'validated',execution:'returned',claims:'not_automatically_verified'}}}});await c.accept({type:'done',model:'zero-model host fixture'});s=c.persist();s=action(x.store,s,{type:'block_add',kind:'evidence',runId:run.id,refId:'E1'});
 const report=renderStudyReport(s),meta=(result as {results:{meta:{definition:string,coverage:{from:string,to:string},evidence:{title:string,href:string}[]}}[]}).results[0].meta;
 assert.ok(report.html.includes(escapeXml(meta.definition)),'The source definition must be printed');assert.ok(report.html.includes(`Source coverage: ${meta.coverage.from} - ${meta.coverage.to}`));assert.ok(report.html.includes(escapeXml(meta.evidence[0].title)));assert.ok(report.html.includes(escapeXml(meta.evidence[0].href)));assert.ok(!report.html.includes('PRIVATE_QUESTION_SENTINEL'));assert.ok(report.markdown.includes(meta.evidence[0].title));
 }finally{x.close();}
});
test('artifact-only selection retains precisely bound calculation code and inputs but excludes sibling outputs and other evidence',async()=>{
 const x=fixture();try{let s=x.store.create('Controlled artifact dependency fixture',context);const {run}=x.store.beginRun(s.id,uuid(),'Developer fixture, no actual Python execution');const c=new ResearchCollector(x.store,s.id,run);const query=(tool:string)=>({tool,parameters:{},requestedContext:{page:'/studio',filters:context.filters},assurance:{parameters:'validated' as const,execution:'fixture',claims:'not_automatically_verified' as const}});
 for(const [id,value] of [['E1',42],['E2',999]] as const)await c.accept({type:'evidence',evidence:{id,title:id,description:id==='E2'?'UNSELECTED_EVIDENCE_SENTINEL':'Selected fixture input',result:{queryId:id==='E1'?'Q1':'Q2',rows:[{label:id,value}]},query:query('workspace_query')}});
 const code='print(42)\n',provenance={context:{...context},status:'succeeded',evidenceId:'E3',code,inputScopes:[{evidenceId:'E1'}]};
 await c.accept({type:'evidence',evidence:{id:'E3',title:'Selected calculation',description:'Explicit no-model calculation fixture',result:{status:'succeeded',inputScopes:[{evidenceId:'E1'}],provenance,inputEvidenceIds:['E1','E2','E3']},query:query('python_analysis')}});await c.accept({type:'done',model:'fixture only'});s=c.persist();
 const selected=saveText(x.store,s,run.id,'result.txt','42',provenance),program=saveText(x.store,s,run.id,'calculation.py',code,provenance);saveText(x.store,s,run.id,'sibling.txt','UNSELECTED_SIBLING_OUTPUT_SENTINEL',provenance);saveText(x.store,s,run.id,'wrong-code.py','UNRELATED_CODE_SENTINEL',{...provenance,evidenceId:'E2'});s=x.store.get(s.id);s=action(x.store,s,{type:'block_add',kind:'artifact',refId:selected.id});const files=entries(exportStudy(x.store,s)),all=[...files.values()].map(b=>b.toString()).join('\n');
 assert.equal(files.get(`attachments/${selected.id}-result.txt`)!.toString(),'42');assert.equal(files.get(`code/${program.id}-calculation.py`)!.toString(),code);assert.ok(all.includes('Selected fixture input'));for(const secret of ['UNSELECTED_EVIDENCE_SENTINEL','UNSELECTED_SIBLING_OUTPUT_SENTINEL','UNRELATED_CODE_SENTINEL','PRIVATE_NOTES_SENTINEL'])assert.ok(!all.includes(secret),`Unexpected dependency: ${secret}`);
 const manifest=JSON.parse(files.get('manifest.json')!.toString());assert.deepEqual(manifest.study.runs[0].evidence.map((e:{id:string})=>e.id),['E1','E3']);assert.ok(renderStudyReport(s).html.includes('Result SHA-256'));
 }finally{x.close();}
});
test('selected export rejects stale hashes and explicit same-run evidence selection does not expose unrelated evidence',async()=>{
 const x=fixture();try{let s=await resource(x.store,x.store.create('Hash checks',context));const run=s.runs[0];run.evidence.push({id:'E9',title:'UNSELECTED_EVIDENCE_TITLE_SENTINEL',description:'UNSELECTED_EVIDENCE_DESCRIPTION_SENTINEL',result:{secret:121}});x.store.updateRun(s.id,run);s=x.store.get(s.id);s=action(x.store,s,{type:'block_add',kind:'evidence',runId:run.id,refId:'E1'});const output=exportStudy(x.store,s);assert.ok(!output.includes(Buffer.from('UNSELECTED_EVIDENCE_')));const tampered=structuredClone(s);tampered.report[0].resultHash='0'.repeat(64);assert.throws(()=>exportStudy(x.store,tampered),/hash/);
 }finally{x.close();}
});
test('selected PDF and ZIP bind one revision and neither material nor PDF includes private context', {timeout:60000}, async()=>{
 const x=fixture();try{let s=await resource(x.store,x.store.create('Selection PDF',context),'severity');s=action(x.store,s,{type:'block_add',kind:'resource',runId:s.runs[0].id,refId:s.runs[0].resource!.id});const revision=s.revision,bundle=await exportStudyBundle(x.store,s,revision),files=entries(bundle.zip),manifest=JSON.parse(files.get('manifest.json')!.toString());assert.equal(bundle.revision,revision);assert.equal(manifest.study.revision,revision);assert.equal(manifest.exportScope.policy,'selected-report-dependencies-v1');assert.ok(files.get('report.pdf')!.equals(bundle.pdf));assert.ok(!bundle.zip.includes(Buffer.from('PRIVATE_NOTES_SENTINEL')));assert.equal(x.store.get(s.id).revision,revision);for(const item of manifest.files)assert.equal(createHash('sha256').update(files.get(item.name)!).digest('hex'),item.sha256);
 }finally{x.close();}
});
