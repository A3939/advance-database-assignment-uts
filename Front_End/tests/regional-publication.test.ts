import test from 'node:test';
import assert from 'node:assert/strict';
import reports from './fixtures/regional-publication.json';
import {resolveCatalog,validateCatalogFilters,type publicationRead} from '../src/server/data-catalog';
import {createPublishedProvider} from '../src/server/published-data';
import {createOfficialProvider,loadOfficialSnapshot} from '../src/server/official-data';
import {createRegionalProvider,loadRegionSnapshot} from '../src/server/region-data';
import {catalogFilters,hasRegionalProvider} from '../src/services/catalog-contracts';
import {AnalysisWorkspace} from '../src/server/analysis/workspace';

// Sanitised, read-only publication reports captured 2026-10-08. No job is created.
const coverage={from:'2020-01-01',to:'2024-12-31'},release=reports.NSW.release_id;
type Report=import('../src/server/regional-publication').RegionalPublicationReport;
const keys=['crash_count','fatal_crash_count','fatalities','casualties'] as const;
function reader(mutate?:(r:Report)=>void, liveDelta=0):typeof publicationRead {
  return (async(path:string,q:Record<string,string>={})=>{
    if(path==='catalog')return {release_id:release,sources:Object.entries(reports).map(([source,r])=>({
      source_id:r.source_id,batch_id:r.batch_id,jurisdiction:source,coverage,complete_intervals:[coverage],
      publication_status:{admission_level:'fixed_native',official_registration:false,scope:'local_research'},
      capabilities:{monthly:true,severity:true,geography:false,units:false}}))};
    const original=Object.values(reports).find(r=>r.source_id===q.source_id)!;
    const r=structuredClone(original);if(mutate)mutate(r);
    if(path==='reports')return r;
    assert.equal(path,'query');assert.equal(q.release_id,release);
    const monthly=original.monthly_trend.filter(row=>{const p=`${row.year}-${String(row.month).padStart(2,'0')}`;return p>=q.from.slice(0,7)&&p<=q.to.slice(0,7);});
    const summary=Object.fromEntries(keys.map(k=>[k,monthly.reduce((sum,r)=>sum+r[k],0)]));
    summary.crash_count+=liveDelta;
    return {release_id:release,source_id:r.source_id,batch_id:r.batch_id,availability:'available',coverage:{...coverage,complete:true},summary,monthly,yearly:[],severity:original.severity};
  }) as typeof publicationRead;
}
async function setup(read=reader()) {
  const [catalog,snapshot,regional]=await Promise.all([resolveCatalog(release,false,read),loadOfficialSnapshot(),loadRegionSnapshot()]);
  const baseline=createRegionalProvider(createOfficialProvider(snapshot),regional);
  return {catalog,regional,baseline,service:createPublishedProvider(catalog,baseline,read)};
}
for(const source of ['NSW','VIC','QLD'] as const)test(`${source}: current release map, date filter and area metrics reuse exact verified inputs`,async()=>{
  const {catalog,service,baseline}=await setup();
  const entry=catalog.sources.find(s=>s.source===source)!;
  assert.equal(hasRegionalProvider(entry,release),true);
  assert.equal(entry.origin,'publication');assert.equal(entry.publicationStatus?.official_registration,false);
  for(const dateRange of [coverage,{from:'2024-01-01',to:'2024-12-31'}]) {
    const f={...catalogFilters(catalog),source,dateRange};
    const map=await service.getMapData(f),overview=await service.getOverview(f);
    assert.equal(map.meta.availability,'available');assert.ok(map.data.regions.length>70);
    assert.equal(map.data.coverage?.total,overview.data.crashes.value);
    assert.equal(map.meta.releaseId,release);assert.equal(map.meta.sourceBatchId,entry.batchId);
    const selected={...f,regionId:map.data.regions[0].id};
    const ref={...selected,datasetVersion:entry.regionalProvider!.datasetVersion,batchId:entry.regionalProvider!.batchId,releaseId:undefined};
    const [o,t,s]=await Promise.all([service.getOverview(selected),service.getTimeSeries(selected,'monthly'),service.getSeverityDistribution(selected)]);
    assert.equal(o.data.crashes.value,map.data.regions[0].count);
    assert.deepEqual(o.data,(await baseline.getOverview(ref)).data);
    assert.equal(t.data.reduce((n,r)=>n+r.crashes!,0),o.data.crashes.value);
    assert.equal(s.data.reduce((n,r)=>n+r.count,0),o.data.crashes.value);
    assert.match(JSON.stringify(o.meta.evidence),/Verified regional publication binding/);
  }
});
test('changed input, missing related table, QA, monthly metrics, severity or report identity cannot inherit LGA capability',async()=>{
  const mutations:((r:Report)=>void)[]=[r=>{r.files[0].sha256='changed';},r=>{r.files.pop();},r=>{r.files.push(r.files[0]);},
    r=>{r.qa[0].status='fail';},r=>{r.monthly_trend[0].fatalities=(r.monthly_trend[0].fatalities ?? 0)+1;},r=>{r.monthly_trend[0]=r.monthly_trend[1];},
    r=>{r.severity[0].count++;},r=>{r.batch_id='another';},r=>{r.release_id='another';},r=>{r.source_id='another';},r=>{r.profile_version='another';}];
  for(const mutate of mutations){
    const {catalog}=await setup(reader(mutate));
    assert.equal(catalog.sources.some(s=>s.regionalProvider),false);
    assert.throws(()=>validateCatalogFilters({...catalogFilters(catalog),source:'NSW',regionId:'17200'},catalog),/verified ABS/);
  }
});
test('same totals without original-file evidence, or stale bindings, never establish region authority',async()=>{
  const {catalog}=await setup(reader(r=>{r.files=[];}));
  assert.equal(catalog.sources.some(s=>s.capabilities.geography),false);
  const valid=(await setup()).catalog,entry=valid.sources[0];
  assert.equal(hasRegionalProvider({...entry,batchId:'changed'},release),false);
  assert.equal(hasRegionalProvider(entry,'other-release'),false);
  assert.equal(hasRegionalProvider({...entry,regionalProvider:undefined},release),false);
});
test('changed live canonical totals fail closed even when the stored publication report still matches',async()=>{
  const {catalog,service}=await setup(reader(undefined,1));
  await assert.rejects(service.getMapData({...catalogFilters(catalog),source:'NSW'}),/reconciliation failed/);
  await assert.rejects(service.getOverview({...catalogFilters(catalog),source:'NSW',regionId:'17200'}),/reconciliation failed/);
});
test('cross-source areas and dates outside the verified extension cannot be silently substituted',async()=>{
  const {catalog,service}=await setup();const f={...catalogFilters(catalog),source:'NSW',regionId:'17200'};
  await assert.rejects(service.getMapData({...f,source:'QLD'}),/Unknown LGA/);
  await assert.rejects(service.getOverview({...f,dateRange:{from:'2019-01-01',to:'2024-12-31'}}),/outside verified coverage/);
});
test('the Studio/Agent read-only area table agrees with map and release without a model call',async()=>{
  const {catalog,service,regional}=await setup();const filters={...catalogFilters(catalog),source:'NSW',regionId:'17200'};
  const workspace=new AnalysisWorkspace({page:'/studio',filters},service,regional,catalog);
  const result=await workspace.execute('workspace_query',{dataset:'lga_monthly',source:null,dateRange:null,regionId:null,groupBy:['source'],metrics:['crashes'],where:[],orderBy:null,limit:10},new AbortController().signal,'binding-test');
  assert.equal(result.releaseId,release);
  assert.equal((result.preview as {crashes:number}[])[0].crashes,(await service.getOverview(filters)).data.crashes.value);
});
