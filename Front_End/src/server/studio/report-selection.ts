/** Report material dependencies, derived from saved host references. This is an
 * export projection, never a mutation or a replacement for the saved evidence. */
import type { Evidence, Provenance } from '../../services/contracts';
import type { ReportBlock, ResearchRun, Study, StudyArtifact } from '../../services/studio-contracts';
import { validateStudyReport, verifyEvidenceReference, resultHash } from './research-contract';
import { StudioError } from './store';
const object = (value:unknown):Record<string,unknown> => value && typeof value==='object' && !Array.isArray(value) ? value as Record<string,unknown> : {};
export interface ReportSelection {
 blocks:ReportBlock[]; runs:ResearchRun[]; evidenceIds:Map<string,Set<string>>;
 viewIds:Map<string,Set<string>>; findingIds:Set<string>; artifacts:StudyArtifact[];
}
export function selectReportMaterials(study:Study):ReportSelection {
 const blocks=validateStudyReport(study), runs=new Map<string,ResearchRun>(), evidenceIds=new Map<string,Set<string>>(),viewIds=new Map<string,Set<string>>(),findingIds=new Set<string>(),artifacts=new Map<string,StudyArtifact>();
 const requireRun=(id:string)=>{const run=study.runs.find(r=>r.id===id&&r.status==='complete');if(!run)throw new StudioError('A selected material has no completed analysis in this study.',409);runs.set(id,run);return run;};
 const addView=(run:ResearchRun,id:string)=>{const ids=viewIds.get(run.id)??new Set<string>();ids.add(id);viewIds.set(run.id,ids);};
 const addEvidence=(runId:string,id:string)=>{
   const run=requireRun(runId), e=run.evidence.find(e=>e.id===id);if(!e)throw new StudioError('A selected material dependency is missing.',409);
   const ids=evidenceIds.get(runId)??new Set<string>();if(ids.has(id))return;ids.add(id);evidenceIds.set(runId,ids);
   const value=object(e.result), provenance=object(value.provenance);
   // Only actual producer relationships are traversed. inputEvidenceIds is the
   // sandbox's allowed-ID set, not a dependency list, and must not select it all.
   if(e.query?.tool==='python_analysis'&&Array.isArray(value.inputScopes))for(const scope of value.inputScopes){const dep=object(scope).evidenceId;if(typeof dep==='string')addEvidence(runId,dep);}
   if(e.query?.tool==='present_analysis'&&typeof value.queryId==='string'){
     const input=run.evidence.find(candidate=>candidate.query?.tool==='workspace_query'&&object(candidate.result).queryId===value.queryId);
     if(input)addEvidence(runId,input.id);
   }
   // Full CSV data for a selected presentation is retained; arbitrary same-run
   // files and unrelated outputs are not. Explicit artifact blocks remain valid.
   if(Array.isArray(value.artifacts))for(const descriptor of value.artifacts){const d=object(descriptor);const a=study.artifacts.find(a=>a.runId===runId&&a.attempt===run.attempt&&a.sha256===d.sha256&&a.name===d.name);if(a&&(a.kind==='py'||(e.query?.tool==='present_analysis'&&a.kind==='csv')))addArtifact(a);}
   if(e.query?.tool==='python_analysis'&&provenance.status==='succeeded')for(const a of study.artifacts){const p=object(a.provenance);if(a.kind==='py'&&a.runId===runId&&a.attempt===run.attempt&&p.evidenceId===id&&p.status==='succeeded')addArtifact(a);}
 };
 const addArtifact=(a:StudyArtifact)=>{
   if(artifacts.has(a.id))return;artifacts.set(a.id,a);
   const p=object(a.provenance),run=study.runs.find(r=>r.id===a.runId&&r.attempt===a.attempt&&r.status==='complete');
   if(run&&typeof p.evidenceId==='string'&&run.evidence.some(e=>e.id===p.evidenceId))addEvidence(run.id,p.evidenceId);
   // A companion program must bind this exact successful calculation and attempt.
   if(p.status==='succeeded'&&typeof p.evidenceId==='string')for(const code of study.artifacts){const q=object(code.provenance);if(code.kind==='py'&&code.runId===a.runId&&code.attempt===a.attempt&&q.evidenceId===p.evidenceId&&q.status==='succeeded'&&typeof q.code==='string'&&q.code===p.code)addArtifact(code);}
 };
 for(const b of blocks){
   if(b.answerSource)requireRun(b.answerSource.runId);
   for(const ref of b.citations??[]){verifyEvidenceReference(study,ref);addEvidence(ref.runId,ref.evidenceId);}
   if(b.kind==='finding'){
     const finding=study.findings.find(f=>f.id===b.refId)!;findingIds.add(finding.id);
     for(const ref of finding.evidenceRefs??[]){verifyEvidenceReference(study,ref);addEvidence(ref.runId,ref.evidenceId);}
     if(finding.runId)for(const id of finding.evidenceIds)addEvidence(finding.runId,id);
   }else if(b.kind==='resource'){
     const run=requireRun(b.runId!);addEvidence(run.id,'E1');addView(run,run.views[0].id);
   }else if(b.kind==='chart'||b.kind==='table'){
     const run=requireRun(b.runId!),view=run.views.find(v=>v.id===b.refId)!;addView(run,view.id);addEvidence(run.id,view.evidenceId);
   }else if(b.kind==='evidence')addEvidence(b.runId!,b.refId!);
   else if(b.kind==='artifact')addArtifact(study.artifacts.find(a=>a.id===b.refId)!);
 }
 return {blocks,runs:[...runs.values()],evidenceIds,viewIds,findingIds,artifacts:[...artifacts.values()]};
}
/** Private research context is never part of the export. Source provenance notes
 * are different: they describe coverage/definitions and remain intact. */
export function publicMaterial(value:unknown):unknown {
 if(Array.isArray(value))return value.map(publicMaterial);
 if(!value||typeof value!=='object')return value;
 const v=object(value),researchContext=Boolean(v.filters&&typeof v.filters==='object');
 return Object.fromEntries(Object.entries(v).filter(([key])=>!(researchContext&&['notes','references'].includes(key))).map(([key,value])=>[key,publicMaterial(value)]));
}
export function selectedEvidence(run:ResearchRun,selection:ReportSelection):Evidence[]{return run.evidence.filter(e=>selection.evidenceIds.get(run.id)?.has(e.id));}
export function exportEvidence(run:ResearchRun,selection:ReportSelection):Evidence[]{
 return selectedEvidence(run,selection).map(e=>{
   const result=object(e.result);
   // A resource reader may query a wider page payload (e.g. getAnalytics). The
   // exact chosen rows and source metadata are sufficient; unrelated page data
   // must not become implicit report material.
   const chosen = run.resource && e.id==='E1' ? {...result,responses:Array.isArray(result.responses)?result.responses.map(response=>({meta:object(response).meta})):[]} : e.result;
   const clean=(value:unknown):unknown=>{
     if(Array.isArray(value))return value.map(clean);
     if(!value||typeof value!=='object')return value;
     return Object.fromEntries(Object.entries(object(value)).filter(([key])=>key!=='inputEvidenceIds').map(([key,value])=>[key,key==='artifacts'&&Array.isArray(value)?value.filter(item=>selection.artifacts.some(a=>a.sha256===object(item).sha256&&a.name===object(item).name)).map(clean):clean(value)]));
   };
   return publicMaterial({...e,...(e.result!==undefined?{result:clean(chosen)}:{})}) as Evidence;
 });
}
export function exportStudyProjection(study:Study,selection:ReportSelection){
 return {id:study.id,title:study.title,revision:study.revision,createdAt:study.createdAt,updatedAt:study.updatedAt,context:publicMaterial(study.context),report:selection.blocks,reportMeta:study.reportMeta,
   findings:study.findings.filter(f=>selection.findingIds.has(f.id)).map(finding=>publicMaterial(Object.fromEntries(Object.entries(finding).filter(([key])=>key!=='edits')))),
   runs:selection.runs.map(run=>({id:run.id,status:run.status,attempt:run.attempt,context:publicMaterial(run.context),resource:run.resource?publicMaterial(run.resource):undefined,evidence:exportEvidence(run,selection),views:run.views.filter(v=>selection.viewIds.get(run.id)?.has(v.id))})),
   artifacts:selection.artifacts.map(artifact=>publicMaterial(Object.fromEntries(Object.entries(artifact).filter(([key])=>key!=='href'))))};
}
/** Registered result envelopes only; do not walk arbitrary nested tool output. */
export function sourceMetadata(evidence:Evidence[]):Provenance[]{
 const result:Provenance[]=[];
 for(const e of evidence){const v=object(e.result),candidates=[v.meta,...(Array.isArray(v.responses)?v.responses.map(r=>object(r).meta):[]),...(Array.isArray(v.results)?v.results.map(r=>object(r).meta):[])];
   for(const candidate of candidates){const meta=object(candidate),coverage=object(meta.coverage);if(typeof meta.source==='string'&&typeof meta.definition==='string'&&typeof coverage.from==='string'&&typeof coverage.to==='string'&&Array.isArray(meta.evidence))result.push(candidate as Provenance);}
 }
 return [...new Map(result.map(meta=>[resultHash(meta),meta])).values()];
}
