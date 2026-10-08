import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { StudioStore, uuid } from "../src/server/studio/store";
import { createStudy } from "../src/server/studio/create";
import { DEFAULT_FILTERS } from "../src/services/config";
const context = { filters: { ...DEFAULT_FILTERS, source: "NSW" }, metric: "crashes" as const, notes: "", references: "" };
function setup() { const dir = mkdtempSync(join(tmpdir(), "arsia-resources-")); const store = new StudioStore(join(dir,"study.sqlite")); return { store, close(){ store.close(); rmSync(dir,{recursive:true,force:true}); } }; }
test("G01 saving an explicitly selected severity resource must not silently save a time series", async () => {
 const x=setup(); try { const study=await createStudy(x.store,{kind:"analytics",definitionId:"severity",requestId:uuid(),context,title:"Selected severity",granularity:"monthly"});
 assert.equal(study.runs[0].evidence[0].query?.tool,"studio_resource:severity");
 assert.equal(study.runs[0].views[0].kind,"bar");
 } finally {x.close();}
});

import { queryResource, resourceCatalog, resourceRequest, saveResource, verifyResearchAsset } from "../src/server/studio/resources";
import { RESOURCE_DEFINITIONS } from "../src/services/studio-resources";
import { analysisRuntime } from "../src/server/agent/runtime";
import type { ResearchRun } from "../src/services/studio-contracts";

test("Selected trend, severity, and map retain independently queried values, identity and persisted geometry", async () => {
 const x=setup();try{
  const {service}=await analysisRuntime({page:"/studio",filters:context.filters});
  const directTrend=await service.getTimeSeries(context.filters,"yearly");
  const directSeverity=await service.getSeverityDistribution(context.filters);
  const directMap=await service.getMapData(context.filters);
  for(const definitionId of ["trend","severity","spatial-map"] as const){
   const s=await saveResource(x.store,{requestId:uuid(),definitionId,context,...(definitionId==="trend"?{query:{granularity:"yearly"}}:{})});
   const reloaded=x.store.get(s.id),run=reloaded.runs[0];verifyResearchAsset(run);
   assert.equal(run.resource?.definitionId,definitionId);assert.deepEqual(run.context,context);assert.equal(run.status,"complete");
   if(definitionId==="trend")assert.deepEqual(run.views[0].rows.map(r=>r.value),directTrend.data.map(r=>r.crashes));
   if(definitionId==="severity"){assert.deepEqual(run.views[0].rows.map(r=>[r.label,r.count]),directSeverity.data.map(r=>[r.label,r.count]));assert.equal(run.views[0].kind,"bar");}
   if(definitionId==="spatial-map"){
    assert.deepEqual(run.views[0].rows.map(r=>[r.id,r.count]),directMap.data.regions.map(r=>[r.id,r.count]));
    const result=run.evidence[0].result as {boundaries:{url:string;geojson:{features:unknown[]}}[]};assert.equal(result.boundaries[0].url,directMap.data.boundaryUrl);assert.ok(result.boundaries[0].geojson.features.length>1);
   }
  }
 }finally{x.close();}
});
test("Resource saves are atomic, request-bound, revision-safe, and preserve each resource's different research scope",async()=>{
 const x=setup();try{
  const request={requestId:uuid(),definitionId:"trend",context};
  const [a,b]=await Promise.all([saveResource(x.store,request),saveResource(x.store,request)]);
  assert.equal(a.id,b.id);assert.equal(x.store.list().length,1);assert.equal(x.store.get(a.id).runs.length,1);
  const otherContext={...context,filters:{...context.filters,source:"VIC"}};
  const append={requestId:uuid(),definitionId:"severity",context:otherContext,target:{studyId:a.id,revision:x.store.get(a.id).revision}};
  const added=await saveResource(x.store,append);assert.equal(added.id,a.id);assert.equal(added.runs.length,2);assert.equal(added.context.filters.source,"NSW");assert.equal(added.runs[1].context.filters.source,"VIC");
  assert.equal((await saveResource(x.store,append)).revision,added.revision);
  await assert.rejects(()=>saveResource(x.store,{...append,requestId:uuid()}),/changed/);
  await assert.rejects(()=>saveResource(x.store,{...request,definitionId:"severity"}),/already bound/);
  await assert.rejects(()=>saveResource(x.store,{...append,target:{studyId:uuid(),revision:1}}),/already bound/);
  assert.equal(x.store.get(a.id).revision,added.revision);
 }finally{x.close();}
});
test("Resource request rejects client values, unknown query fields, wrong version, scope and unsupported periods without empty studies",async()=>{
 const x=setup();try{
  const base={requestId:uuid(),definitionId:"severity",context};
  for(const addition of [{rows:[]},{evidenceId:"E1"},{verified:true},{runId:uuid()},{query:{sql:"SELECT"}},{context:{...context,filters:{...context.filters,extra:true}}}])assert.throws(()=>resourceRequest({...base,...addition}),/Unknown/);
  await assert.rejects(()=>saveResource(x.store,{...base,context:{...context,filters:{...context.filters,datasetVersion:"missing"}}}),/not connected/);
  await assert.rejects(()=>saveResource(x.store,{...base,context:{...context,filters:{...context.filters,dateRange:{from:"2024-01-01",to:"2024-12-31"}}}}),/unsupported/);
  await assert.rejects(()=>saveResource(x.store,{...base,definitionId:"period-comparison",query:{comparison:{first:"2020–2021",second:"2021–2022"}}}),/non-overlapping/);
  assert.equal(x.store.list().length,0);
 }finally{x.close();}
});
test("Saved result reuse validates immutable values and binding without permitting cross-run or changed data",async()=>{
 const x=setup();try{
  const s=await saveResource(x.store,{requestId:uuid(),definitionId:"severity",context});const original=s.runs[0];
  for(const change of [(r:ResearchRun)=>{r.views[0].rows[0].count=0;},(r:ResearchRun)=>{r.context.filters.source="VIC";},(r:ResearchRun)=>{r.resource!.query={severityMode:"share"};},(r:ResearchRun)=>{(r.evidence[0].result as {rows:{count:number}[]}).rows[0].count=0;}]){
   const changed=structuredClone(original);change(changed);assert.throws(()=>verifyResearchAsset(changed),/integrity|binding/);
  }
  verifyResearchAsset(original);
 }finally{x.close();}
});
test("Fixed severity-change and speed-zone resources use their bound derived services; wrong release and area remain unsupported",async()=>{
 const changes=await queryResource("severity-change",context);assert.equal(changes.availability,"available");assert.equal(changes.display.kind,"table");assert.ok(changes.rows.every(r=>typeof r.startCount==="number"&&typeof r.endCount==="number"));
 const speeds=await queryResource("speed-zones",context);assert.equal(speeds.availability,"available");assert.equal(speeds.unit,"percent");assert.ok(speeds.rows.some(r=>r.share!==null));
 const {service}=await analysisRuntime({page:"/studio",filters:context.filters});const map=await service.getMapData(context.filters);const area=map.data.regions[0].id;
 const unavailable=await queryResource("speed-zones",{...context,filters:{...context.filters,regionId:area}});assert.equal(unavailable.availability,"unsupported");assert.equal(unavailable.rows.length,0);
});
test("All-source resources retain source identities and native categories; period arithmetic is independently checked",async()=>{
 const all={...context,filters:{...context.filters,source:"All"}};
 const severity=await queryResource("severity",all);assert.equal(new Set(severity.rows.map(r=>r.source)).size,3);
 const comparison=await queryResource("period-comparison",all,{comparison:{first:"2020–2021",second:"2023–2024"}});
 const {service}=await analysisRuntime({page:"/studio",filters:context.filters});const months=await service.getTimeSeries(context.filters,"monthly");
 const avg=(from:string,to:string)=>{const rows=months.data.filter(r=>r.period>=from&&r.period<=to);return rows.reduce((n,r)=>n+r.crashes!,0)/rows.length;};const a=avg("2020-01","2021-12"),b=avg("2023-01","2024-12");
 const row=comparison.rows.find(r=>r.source==="NSW")!;assert.equal(row.averageA,a);assert.equal(row.averageB,b);assert.equal(row.change,(b/a-1)*100);assert.equal(comparison.rows.length,3);
});
test("Inventory availability derives from real services and contains all registered resources without fabricating unsupported severity",async()=>{
 const catalog=await resourceCatalog(context);assert.equal(catalog.length,RESOURCE_DEFINITIONS.length);assert.ok(catalog.every(r=>r.availability==="available"));
 const short=await resourceCatalog({...context,filters:{...context.filters,dateRange:{from:"2024-01-01",to:"2024-12-31"}}});assert.equal(short.find(r=>r.id==="severity")?.availability,"unsupported");assert.equal(short.find(r=>r.id==="severity-change")?.availability,"unsupported");assert.equal(short.find(r=>r.id==="trend")?.availability,"available");
});
test("Saved coverage is the observed selection rather than the entire source lifetime; view and limitations remain bound",async()=>{
 const x=setup();try{
  const oneYear={...context,filters:{...context.filters,dateRange:{from:"2024-01-01",to:"2024-12-31"}}};
  const s=await saveResource(x.store,{requestId:uuid(),definitionId:"trend",context:oneYear});const original=s.runs[0];
  assert.deepEqual(original.resource!.actualCoverage.map(c=>({from:c.from,to:c.to})),[oneYear.filters.dateRange]);
  for(const change of [(r:ResearchRun)=>{r.views[0].y="fatalCrashes";},(r:ResearchRun)=>{r.resource!.unit="risk rate";},(r:ResearchRun)=>{r.resource!.limitations=[];}]){const altered=structuredClone(original);change(altered);assert.throws(()=>verifyResearchAsset(altered),/integrity|binding/);}
 }finally{x.close();}
});
test("Resource rows bind the actual measure and period rather than borrowing the research metric",async()=>{
 const selected={...context,metric:"casualties" as const};
 const severity=await queryResource("severity",selected);assert.ok(severity.rows.every(r=>r.metric==="crashes"&&r.unit==="crashes"));
 const share=await queryResource("severity",selected,{severityMode:"share"});assert.ok(share.rows.every(r=>r.metric==="native_severity_share"&&r.unit==="fraction of recorded crashes"));
 const fatal=await queryResource("fatal-outcomes",selected);assert.ok(fatal.rows.some(r=>r.metric==="fatalCrashes"&&r.unit==="crashes"));assert.ok(fatal.rows.some(r=>r.metric==="livesLost"&&r.unit==="people"));
 assert.equal(fatal.rows[0].from,"2020-01-01");assert.equal(fatal.rows[0].to,"2020-12-31");
 const trend=await queryResource("trend",selected,{granularity:"monthly"});assert.equal(trend.rows[0].metric,"casualties");assert.equal(trend.rows[0].unit,"people");assert.equal(trend.rows[0].to,"2020-01-31");
});

test("an explicitly empty exploration draft stays empty while supplied questions remain unchanged",async()=>{
 const x=setup();try{
  const empty=await createStudy(x.store,{title:"New exploration",question:"",context});
  assert.equal(empty.draft,"");assert.deepEqual(empty.runs,[]);assert.equal(x.store.get(empty.id).draft,"");
  const supplied=await createStudy(x.store,{title:"My study",question:"What changed?",context});assert.equal(supplied.draft,"What changed?");
  const fallback=await createStudy(x.store,{title:"Legacy title-only entry",context});assert.equal(fallback.draft,"Legacy title-only entry");
 }finally{x.close();}
});
