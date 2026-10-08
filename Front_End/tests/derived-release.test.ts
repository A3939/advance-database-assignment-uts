import test from 'node:test';
import assert from 'node:assert/strict';
import reports from './fixtures/regional-publication.json';
import {analysisRuntime} from '../src/server/agent/runtime';
import {resolveCatalog,type publicationRead} from '../src/server/data-catalog';
import {catalogFilters} from '../src/services/catalog-contracts';
import {DEFAULT_FILTERS} from '../src/services/config';
import {createOfficialProvider,loadOfficialSnapshot} from '../src/server/official-data';
import {createRegionalProvider,loadRegionSnapshot,regionEvidence} from '../src/server/region-data';
import {getSeverityChange} from '../src/server/severity-change';
import {getSpeedZones,loadSpeedZoneSnapshot,speedZoneEvidence} from '../src/server/speed-zone';
import {derivedSourceBinding} from '../src/server/derived-report-binding';

const release=reports.NSW.release_id,coverage=DEFAULT_FILTERS.dateRange;
const read=(async(path:string,q:Record<string,string>={})=>{
  if(path==='catalog')return {release_id:release,sources:Object.entries(reports).map(([source,r])=>({source_id:r.source_id,batch_id:r.batch_id,
    jurisdiction:source,coverage,complete_intervals:[coverage],publication_status:{admission_level:'fixed_native'},
    capabilities:{monthly:true,severity:true,geography:false,units:false}}))};
  const r=Object.values(reports).find(r=>r.source_id===q.source_id)!;
  if(path==='reports')return r;
  assert.equal(path,'query');assert.equal(q.release_id,release);
  const monthly=r.monthly_trend.filter(r=>{const p=`${r.year}-${String(r.month).padStart(2,'0')}`;return p>=q.from.slice(0,7)&&p<=q.to.slice(0,7);});
  const summary=Object.fromEntries(['crash_count','fatal_crash_count','fatalities','casualties'].map(k=>[k,monthly.reduce((n,r)=>n+r[k as 'crash_count'],0)]));
  return {release_id:release,source_id:r.source_id,batch_id:r.batch_id,summary,availability:'available',coverage:{...coverage,complete:true},monthly,yearly:[],severity:r.severity};
}) as typeof publicationRead;
async function setup() {
  const catalog=await resolveCatalog(release,false,read),filters=catalogFilters(catalog);
  const runtime=await analysisRuntime({page:'/analytics/severity',filters},read);
  const regional=await loadRegionSnapshot(),speed=await loadSpeedZoneSnapshot();
  const baseline=createRegionalProvider(createOfficialProvider(await loadOfficialSnapshot()),regional);
  return {...runtime,filters,regional,speed,baseline};
}
for(const source of ['All','NSW','VIC','QLD'])test(`${source}: current release derived charts equal verified original observations without losing publication identity`,async()=>{
  const {filters,service,catalog,regional,speed,baseline}=await setup();const f={...filters,source};
  const severity=await getSeverityChange(f,service,regional,catalog),zones=await getSpeedZones(f,service,speed,catalog);
  assert.deepEqual(severity.data,(await getSeverityChange({...DEFAULT_FILTERS,source},baseline,regional)).data);
  assert.deepEqual(zones.data,(await getSpeedZones({...DEFAULT_FILTERS,source},baseline,speed)).data);
  for(const r of [severity,zones]){
    assert.equal(r.meta.availability,'available');assert.equal(r.meta.releaseId,release);assert.equal(r.meta.batchId,release);
    const evidence=r.meta.evidence.at(-1)!;assert.ok(evidence.href?.includes(`releaseId=${release}`));
    assert.ok((evidence.result as {bindings:{sourceBatchId:string}[]}).bindings.every(b=>Object.values(reports).some(r=>r.batch_id===b.sourceBatchId)));
  }
});
test('matching months and LGA severity work; one-year comparison and LGA speed remain honestly unsupported',async()=>{
  const {filters,service,catalog,regional,speed,baseline}=await setup();
  const f={...filters,source:'NSW',regionId:'17200',dateRange:{from:'2020-02-01',to:'2024-06-30'}};
  const change=await getSeverityChange(f,service,regional,catalog);
  assert.equal(change.data.groups[0].area,'Sydney');
  assert.deepEqual(change.data,(await getSeverityChange({...f,...DEFAULT_FILTERS,releaseId:undefined,source:f.source,regionId:f.regionId,dateRange:f.dateRange},baseline,regional)).data);
  const unsupported=await getSpeedZones(f,service,speed,catalog);assert.equal(unsupported.meta.availability,'unsupported');assert.match(unsupported.data.reason!,/whole sources/);
  const year={...filters,source:'NSW',dateRange:{from:'2024-01-01',to:'2024-12-31'}};
  assert.equal((await getSeverityChange(year,service,regional,catalog)).meta.availability,'unsupported');
  assert.equal((await getSpeedZones(year,service,speed,catalog)).meta.availability,'available');
});
test('wrong input/role, source batch, release or derivation cannot inherit either extension',async()=>{
  const {filters,catalog,regional,speed}=await setup(),f={...filters,source:'NSW'};
  for(const [snapshot,manifest] of [[regional,await regionEvidence()],[speed,await speedZoneEvidence()]] as const){
    assert.ok(derivedSourceBinding(f,'NSW',snapshot,catalog,manifest));
    for(const mutate of [
      (c:typeof catalog)=>{c.sources[0].regionalProvider!.inputs[0].sha256='changed';},
      (c:typeof catalog)=>{c.sources[0].regionalProvider!.inputs=[];},
      (c:typeof catalog)=>{c.sources[0].batchId='changed';},
      (c:typeof catalog)=>{c.releaseId='changed';},
      (c:typeof catalog)=>{c.sources[0].regionalProvider!.batchId='changed';},
    ]){const c=structuredClone(catalog);mutate(c);assert.equal(derivedSourceBinding(f,'NSW',snapshot,c,manifest),undefined);}
    const m=structuredClone(manifest);m.inputs.find((i:{sourceId:string})=>i.sourceId==='official_nsw').sha256='changed';
    assert.equal(derivedSourceBinding(f,'NSW',snapshot,catalog,m),undefined);
    assert.equal(derivedSourceBinding({...f,releaseId:'other'},'NSW',snapshot,catalog,manifest),undefined);
  }
});
test('mixed All selection preserves supported groups and exposes an unbound source separately',async()=>{
  const {filters,service,catalog,regional,speed}=await setup();const partial=structuredClone(catalog);
  partial.sources[1].regionalProvider=undefined;
  for(const result of [await getSeverityChange(filters,service,regional,partial),await getSpeedZones(filters,service,speed,partial)]){
    assert.equal(result.meta.availability,'available');assert.deepEqual(result.data.groups.map(g=>g.availability),['available','unsupported','available']);
    assert.equal(result.data.groups[1].rows.length,0);
  }
});
test('live response with stale release/source batch or unreconciled totals is rejected',async()=>{
  const {filters,service,catalog,regional,speed}=await setup();const f={...filters,source:'NSW'};
  for(const mutate of [
    (r:Awaited<ReturnType<typeof service.getOverview>>)=>{r.meta.sourceBatchId='stale';},
    (r:Awaited<ReturnType<typeof service.getOverview>>)=>{r.meta.releaseId='stale';},
    (r:Awaited<ReturnType<typeof service.getOverview>>)=>{r.data.crashes.value!++;},
  ]) {
    const broken={getOverview:async(f:typeof filters)=>{const r=await service.getOverview(f);mutate(r);return r;}};
    await assert.rejects(getSeverityChange(f,broken,regional,catalog),/identity|reconcile/);
    await assert.rejects(getSpeedZones(f,broken,speed,catalog),/identity|reconcile/);
  }
});
