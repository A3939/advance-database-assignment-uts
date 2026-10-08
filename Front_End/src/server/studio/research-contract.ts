/** Host-owned research references and checks. Text never grants evidence authority. */
import { createHash, randomUUID } from 'node:crypto';
import type { Evidence } from '../../services/contracts';
import type { EvidenceReference, FindingChecks, NumericClaim, ReportBlock, ReportMetadata, ResearchFinding, ResearchReportDraft, ResearchRun, Study } from '../../services/studio-contracts';
import { checkClaims } from '../agent/claims';
import { StudioError } from './store';
import { verifyResearchAsset } from './resource-integrity';
export const resultHash = (value: unknown): string => createHash('sha256').update(JSON.stringify(value) ?? 'null').digest('hex');
const record = (value: unknown): Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string,unknown> : {};
const error = (message:string): never => { throw new StudioError(message); };
export function evidenceReference(study: Study, runId:string, evidenceId:string): EvidenceReference {
 const run=study.runs.find(r=>r.id===runId && r.status==='complete');const evidence=run?.evidence.find(e=>e.id===evidenceId);
 if(!run || !evidence || evidence.result===undefined || !evidence.query || !(evidence.query.validated || evidence.query.assurance?.parameters==='validated')) return error('A completed, host-validated evidence reference in this study is required.');
 return {runId,attempt:run.attempt,evidenceId,resultHash:resultHash({result:evidence.result,query:evidence.query,context:run.context})};
}
export function verifyEvidenceReference(study:Study, ref:EvidenceReference): Evidence {
 const actual=evidenceReference(study,ref.runId,ref.evidenceId);
 if(actual.attempt!==ref.attempt || actual.resultHash!==ref.resultHash) return error('Saved evidence binding has changed; select its current immutable result.');
 return study.runs.find(r=>r.id===ref.runId)!.evidence.find(e=>e.id===ref.evidenceId)!;
}
export function findingContentHash(f:Pick<ResearchFinding,'title'|'explanation'|'kind'|'context'|'evidenceRefs'|'claims'>):string {
 return resultHash({title:f.title.trim(),explanation:f.explanation.trim(),kind:f.kind,context:f.context,evidenceRefs:f.evidenceRefs||[],claims:f.claims||[]});
}
export function findingChecks(study:Study,f:ResearchFinding): FindingChecks {
 const refs=f.evidenceRefs||[], claims=f.claims||[];
 for(const ref of refs)verifyEvidenceReference(study,ref);
 const map=new Map<string,Evidence>(refs.map(ref=>[ref.evidenceId,verifyEvidenceReference(study,ref)]));
 const unitForMetric:Record<string,string>={crashes:'crashes',fatalCrashes:'fatal crashes',livesLost:'people',casualties:'people'};
 const unitMatches=(c:NumericClaim)=>c.unit===(/\/(percentChange|fatalSharePercent)$/.test(c.pointer)?'percent':unitForMetric[c.metric]);
 const resourceClaim=(c:NumericClaim):boolean=>{
   const run=study.runs.find(r=>r.id===f.runId), asset=run?.resource;
   if(!run||!asset)return false;verifyResearchAsset(run);
   if(c.evidenceId!=='E1')return false;
   const match=/^\/rows\/(0|[1-9]\d*)\/([A-Za-z][A-Za-z0-9]*)$/.exec(c.pointer);
   if(!match||match[2]!==asset.display.y)return false;
   const rows=record(map.get(c.evidenceId)?.result).rows;if(!Array.isArray(rows))return false;
   const row=record(rows[Number(match[1])]);
   return row.source===c.source&&c.source!=='All'&&typeof row.metric==='string'&&typeof row.unit==='string'&&c.metric===row.metric&&c.unit===row.unit&&c.from===(row.from??asset.context.filters.dateRange.from)&&c.to===(row.to??asset.context.filters.dateRange.to)&&typeof row[match[2]]==='number'&&row[match[2]]===c.value&&(row.availability===undefined||row.availability==='available');
 };
 const supported=claims.length>0 && claims.every(c=>map.get(c.evidenceId)?.query?.tool.startsWith('studio_resource:')?resourceClaim(c):checkClaims({claims:[c]},map).claims[0]?.status==='supported_exact_value'&&unitMatches(c));
 return {evidenceLinked:refs.length>0,numericChecked:supported,reviewNeeded:true,unsupportedClaim:claims.length>0&&!supported,userReviewed:false,checkedAt:new Date().toISOString(),contentHash:findingContentHash(f),notes:[supported?'Only the specified exact values, units and query ranges were checked. Narrative and causal claims remain unverified.':claims.length?'One or more numerical value, unit or scope bindings are unsupported.':'No numerical claims have been checked.',...(refs.length?[]:['No linked data evidence.'])]};
}
export function parseNumericClaims(value:unknown):NumericClaim[] {
 if(!Array.isArray(value)||value.length>12)return error('Choose at most 12 exact numerical claims.');
 return value.map(v=>{const c=record(v);if(Object.keys(c).some(k=>!['evidenceId','pointer','source','metric','from','to','value','unit'].includes(k)) || ['evidenceId','pointer','source','metric','from','to','unit'].some(k=>typeof c[k]!=='string'||String(c[k]).length>500) || typeof c.value!=='number'||!Number.isFinite(c.value))return error('Invalid numerical claim.');return c as unknown as NumericClaim;});
}
export function reportMetadata(value:unknown,study:Study):ReportMetadata {
 const v=record(value);if(Object.keys(v).some(k=>!['contractVersion','template','language','title','author','date'].includes(k)))return error('Unknown report setting.');
 if(!['brief','full'].includes(String(v.template)) || !['en','zh','bilingual'].includes(String(v.language)))return error('Unknown report template or language.');
 const title=v.title??study.title,author=v.author??'',date=v.date??new Date().toISOString().slice(0,10);
 if(typeof title!=='string'||!title.trim()||title.length>120||typeof author!=='string'||author.length>300||typeof date!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(date))return error('Invalid report metadata.');
 return {contractVersion:1,template:v.template as ReportMetadata['template'],language:v.language as ReportMetadata['language'],title,author,date};
}
export function reportTemplate(meta:ReportMetadata):ReportBlock[] {
 const full=meta.template==='full';const zh=meta.language==='zh';
 const labels=zh?(full?['摘要','研究问题','数据与方法','结果','讨论','限制','结论','参考资料']:['研究问题与主要发现','主要图表','数据与方法','限制与来源']):(full?['Abstract','Research question','Data and methods','Results','Discussion','Limitations','Conclusion','References']:['Research question and findings','Main figures','Data and methods','Limitations and sources']);
 return [{id:randomUUID(),kind:'title',text:meta.title},...labels.flatMap(text=>[{id:randomUUID(),kind:'section' as const,text},{id:randomUUID(),kind:'text' as const,text:zh?'待补充：请使用已保存的证据完成本节。':'To complete: add findings and saved evidence for this section.'}])];
}
export const reportHash=(study:Study)=>resultHash({report:study.report,metadata:study.reportMeta});
/** Resource-save notices and structured writing proposals are not conversation answers. */
export function isCompletedConversationAnswer(run: ResearchRun | undefined): run is ResearchRun {
 return !!run && run.status==='complete' && ['assistant','ask-ai'].includes(run.origin) && !run.resource && !run.reportDraft && !['draft','revise'].includes(run.mode || '') && !!run.answer.trim();
}
export function bindReportBlock(study:Study,block:ReportBlock):ReportBlock {
 const b=structuredClone(block);
 if(!['title','section','text','finding','chart','table','evidence','artifact','resource'].includes(b.kind))return error('Unknown report block kind.');
 for(const ref of b.citations||[])verifyEvidenceReference(study,ref);
 if(b.answerSource){
   const ref=b.answerSource,run=study.runs.find(r=>r.id===ref.runId);
   if(b.kind!=='text'||Object.keys(ref).some(k=>!['runId','attempt','answerHash'].includes(k))||!isCompletedConversationAnswer(run)||run.attempt!==ref.attempt||resultHash(run.answer)!==ref.answerHash)return error('Saved answer binding has changed; select its current completed response.');
 }
 if(['title','section','text'].includes(b.kind)){if(b.refId||b.runId)return error('Text blocks cannot impersonate a resource.');return b;}
 const run=study.runs.find(r=>r.id===b.runId&&r.status==='complete');
 let value:unknown;
 if(b.kind==='finding') value=study.findings.find(f=>f.id===b.refId);
 else if(b.kind==='artifact') value=study.artifacts.find(a=>a.id===b.refId);
 else if(['chart','table'].includes(b.kind)) value=run?.views.find(v=>v.id===b.refId);
 else if(b.kind==='evidence') value=run?.evidence.find(e=>e.id===b.refId);
 else if(b.kind==='resource' && run?.resource) {verifyResearchAsset(run);value=run.resource.id===b.refId?{resource:run.resource,evidence:run.evidence,views:run.views}:undefined;}
 if(!value)return error('This result reference does not belong to a completed analysis in this study.');
 const hash=resultHash(value);
 if(b.resultHash && b.resultHash!==hash)return error('Report reference hash no longer matches its saved result.');
 b.resultHash=hash;return b;
}
export function validateStudyReport(study:Study):ReportBlock[]{return study.report.map(b=>bindReportBlock(study,b));}
function evidenceExcerpt(evidence:Evidence,resource?:Study['runs'][number]['resource']) {
 if(resource){const value=record(evidence.result);const rows=Array.isArray(value.rows)?value.rows:[];return {definitionId:resource.definitionId,query:resource.query,context:resource.context,unit:resource.unit,availability:resource.availability,limitations:resource.limitations,actualCoverage:resource.actualCoverage,rows:rows.slice(0,40),totalRows:rows.length,truncated:rows.length>40,notice:'Only these exact rows are supplied for writing. The complete immutable resource remains available for referenced figures. Do not infer omitted values.'};}
 if(JSON.stringify(evidence.result).length>20000)return {summary:evidence.rows,limitation:'Detailed values omitted from writing context; do not make numerical claims from this summary.'};
 return evidence.result;
}
export function prepareResearchDraft(study:Study,mode:'draft'|'revise',selectedRunIds:string[],targetBlockId?:string){
 if(selectedRunIds.length>16||new Set(selectedRunIds).size!==selectedRunIds.length)return error('Select at most 16 distinct saved analyses.');
 const target=targetBlockId?study.report.find(b=>b.id===targetBlockId):undefined;
 if(mode==='revise'&&(!target||!['text','title','section'].includes(target.kind)))return error('Select a saved text paragraph to revise.');
 if(mode==='draft'&&targetBlockId)return error('A whole draft cannot specify a target paragraph.');
 const refs:EvidenceReference[]=[];
 const resources=selectedRunIds.map(id=>{const run=study.runs.find(r=>r.id===id&&r.status==='complete');if(!run)return error('Select completed analyses in this study.');if(run.resource)verifyResearchAsset(run);const evidence=run.evidence.filter(e=>e.query&&(e.query.validated||e.query.assurance?.parameters==='validated')).map(e=>{const ref=evidenceReference(study,id,e.id);refs.push(ref);return {ref,title:e.title,description:e.description,rows:e.rows,result:evidenceExcerpt(e,run.resource)};});return {runId:run.id,context:run.context,resource:run.resource,views:run.views.map(({id,title,kind,x,y,series})=>({id,title,kind,x,y,series})),evidence};});
 const materials={studyId:study.id,question:study.title,scope:study.context,mode,target:target?{id:target.id,kind:target.kind,text:target.text}:undefined,resources,findings:study.findings.filter(f=>!f.archived&&f.runId&&selectedRunIds.includes(f.runId)).map(f=>({id:f.id,title:f.title,explanation:f.explanation,checks:f.checks,evidenceRefs:f.evidenceRefs,limitations:f.limitations}))};
 if(JSON.stringify(materials).length>64000)return error('Selected report evidence is too large. Select fewer analyses.');
 return {materials,refs,baseReportHash:reportHash(study),target};
}
export function validateResearchDraft(study:Study,prepared:ReturnType<typeof prepareResearchDraft>,value:unknown):ResearchReportDraft {
 const root=record(value);if(Object.keys(root).some(k=>k!=='blocks')||!Array.isArray(root.blocks)||!root.blocks.length||root.blocks.length>40)return error('A report draft must contain 1–40 structured blocks.');
 const mode=prepared.materials.mode;
 if(mode==='revise'&&root.blocks.length!==1)return error('Revision can change only the selected paragraph.');
 const blocks=root.blocks.map(raw=>{const v=record(raw);if(Object.keys(v).some(k=>!['kind','text','runId','refId','caption','citations'].includes(k))||typeof v.text!=='string'||v.text.length>10000||typeof v.kind!=='string')return error('Unknown field or invalid report draft block.');
 if(v.caption!==null&&v.caption!==undefined&&(typeof v.caption!=='string'||v.caption.length>2000))return error('Invalid report caption.');
 if(/<\s*(script|iframe|object|embed)\b|javascript\s*:|```(?:js|javascript|tsx?|jsx?|html)\b/i.test(v.text))return error('Executable markup is not allowed in report drafts.');
 if(!Array.isArray(v.citations)||v.citations.length>16)return error('Report blocks require an explicit bounded citations list.');
 const citations=v.citations.map(rawRef=>{const ref=record(rawRef);if(Object.keys(ref).some(k=>!['runId','attempt','evidenceId','resultHash'].includes(k)))return error('Unknown citation field.');const known=prepared.refs.find(r=>JSON.stringify(r)===JSON.stringify({runId:ref.runId,attempt:ref.attempt,evidenceId:ref.evidenceId,resultHash:ref.resultHash}));if(!known)return error('Draft citation is not part of the selected, host-verified evidence.');verifyEvidenceReference(study,known);return known;});
 if(/\d/.test(v.text)&&!citations.length)return error('Numerical draft paragraphs require selected evidence citations.');
 if(v.runId!==null&&v.runId!==undefined&&!prepared.materials.resources.some(r=>r.runId===v.runId))return error('Draft referenced an unselected analysis.');
 if(v.refId!==null&&v.refId!==undefined&&typeof v.refId!=='string')return error('Invalid report result reference.');
 const b:ReportBlock={id:randomUUID(),kind:v.kind as ReportBlock['kind'],text:v.text,citations,...(v.runId?{runId:String(v.runId)}:{}),...(v.refId?{refId:String(v.refId)}:{}),...(v.caption?{caption:String(v.caption)}:{})};
 if(mode==='revise'){if(b.kind!==prepared.target!.kind||b.runId||b.refId)return error('Revision cannot change paragraph kind or other resources.');b.id=prepared.target!.id;}
 if(b.kind==='finding'&&!prepared.materials.findings.some(f=>f.id===b.refId))return error('Draft referenced an unselected finding.');
 if(b.kind==='artifact')return error('Draft cannot select arbitrary attachments.');
 return bindReportBlock(study,b);});
 return {id:randomUUID(),mode,baseReportHash:prepared.baseReportHash,...(prepared.target?{targetBlockId:prepared.target.id}:{}),blocks,createdAt:new Date().toISOString(),status:'proposed'};
}
