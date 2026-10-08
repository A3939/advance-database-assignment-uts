import { timePointLabel } from "../src/services/periods";
import { getAnalytics } from "../src/services/analytics";
import test from 'node:test';
import assert from 'node:assert/strict';
import {resolveCatalog,parseDataFilters,validateCatalogFilters, type publicationRead} from '../src/server/data-catalog';
import {createPublishedProvider} from '../src/server/published-data';
import {createOfficialProvider,loadOfficialSnapshot} from '../src/server/official-data';
import {loadRegionSnapshot} from '../src/server/region-data';
import {AnalysisWorkspace} from '../src/server/analysis/workspace';
import {executeAnalysisTool} from '../src/server/agent/tools';
import {parseAgentRequest} from '../src/server/agent/request';
import {analysisHref,parseAnalysisState,DEFAULT_VIEW} from '../src/services/analysis-state';
import {catalogFilters,coverageMonthRange,LOCAL_VERSION,SNAPSHOT_CATALOG,sourceDisplayName} from '../src/services/catalog-contracts';
import {DEFAULT_FILTERS} from '../src/services/config';
const release='aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa';
const batch='bbbbbbbb-1111-4111-8111-bbbbbbbbbbbb';
const source={source_id:'act_official_dataset',batch_id:batch,jurisdiction:'ACT',source_name:'ACT road crash records',publisher:'ACT Government',coverage:{from:'2025-01-01',to:'2025-12-31'},definitions:{crashes:'One reported crash.',fatalCrashes:'Fatal crash flag.',livesLost:'Not supplied.'},capabilities:{monthly:true,severity:true,geography:false,units:false},limitations:['Fatal crash count is not lives lost.']};
const read = (async (path:string,q:Record<string,string>={})=>{
 if(path==='catalog') { if(q.release_id && q.release_id!==release)throw Error('missing');return {release_id:release,sources:[source,{...source,source_id:'act_other_dataset'}]}; }
 assert.equal(q.include_units,'false','Website aggregate queries omit unused unit aggregates.');
 assert.equal(q.release_id,release);assert.ok(['act_official_dataset','act_other_dataset'].includes(q.source_id));
 const summary={crash_count:2,fatal_crash_count:1,fatalities:null,casualties:null};
 return {release_id:release,batch_id:batch,source_id:q.source_id,coverage:{...source.coverage,complete:true},availability:'available',summary,monthly:[{year:2025,month:1,...summary}],yearly:[{year:2025,...summary}],severity:[{code:'F',label:'Fatal',count:1},{code:'N',label:'Non-fatal',count:1}]};
}) as typeof publicationRead;

test('country map uses pinned published totals, not stale baseline counts or location capability',async()=>{
 const calls:Record<string,string>[]=[];
 const native=['NSW','VIC','QLD'].map((jurisdiction,i)=>({...source,source_id:`official_${jurisdiction.toLowerCase()}`,jurisdiction,batch_id:`batch-${i}`,coverage:DEFAULT_FILTERS.dateRange}));
 const nativeRead=(async(path:string,q:Record<string,string>={})=>{
   if(path==='catalog')return {release_id:release,sources:native};
   calls.push(q);const index=native.findIndex(s=>s.source_id===q.source_id);assert.ok(index>=0);
   return {release_id:release,batch_id:native[index].batch_id,source_id:q.source_id,availability:'available',coverage:{...DEFAULT_FILTERS.dateRange,complete:true},summary:{crash_count:(index+1)*11,fatal_crash_count:0,fatalities:0,casualties:null},monthly:[],yearly:[],severity:[]};
 }) as typeof publicationRead;
 const catalog=await resolveCatalog(release,false,nativeRead);
 const service=createPublishedProvider(catalog,createOfficialProvider(await loadOfficialSnapshot()),nativeRead);
 const f={...catalogFilters(catalog),dateRange:{from:'2024-03-01',to:'2024-05-31'}};
 const result=await service.getMapData(f);
 assert.deepEqual(result.data.states?.filter(s=>s.available).map(s=>[s.source,s.count]),[['NSW',11],['VIC',22],['QLD',33]]);
 assert.equal(result.meta.availability,'available');assert.equal(result.meta.releaseId,release);
 assert.equal(result.data.states?.find(s=>s.label==='WA')?.count,undefined);
 assert.equal(calls.length,3);for(const q of calls){assert.equal(q.from,f.dateRange.from);assert.equal(q.to,f.dateRange.to);assert.equal(q.release_id,release);assert.equal(q.include_units,'false');}
 assert.deepEqual(result.meta.sourceBatches,{NSW:'batch-0',VIC:'batch-1',QLD:'batch-2'});
 assert.equal((await service.getMapData({...f,source:'NSW'})).meta.availability,'unsupported','State totals must not invent an LGA/coordinate provider.');
});

test('country map uses unique catalog jurisdiction, preserves zero and refuses overlapping sources',async()=>{
 const publications=[{...source,source_id:'independent_package',jurisdiction:'WA'},source,{...source,source_id:'other_package'}];
 const readUnique=(async(path:string,q:Record<string,string>={})=>path==='catalog'?{release_id:release,sources:publications}:{...await read<Record<string,unknown>>('query',{...q,source_id:source.source_id}),source_id:q.source_id,summary:{crash_count:0,fatal_crash_count:0,fatalities:null,casualties:null}}) as typeof publicationRead;
 const catalog=await resolveCatalog(release,false,readUnique);
 const service=createPublishedProvider(catalog,createOfficialProvider(await loadOfficialSnapshot()),readUnique);
 const result=await service.getMapData({...catalogFilters(catalog),dateRange:source.coverage});
 const wa=result.data.states?.find(s=>s.label==='WA'),act=result.data.states?.find(s=>s.label==='ACT');
 assert.equal(wa?.source,'independent_package');assert.equal(wa?.count,0);assert.equal(wa?.available,true);
 assert.equal(act?.count,undefined);assert.equal(act?.available,false);assert.equal(act?.source,undefined);
 assert.match(result.data.unavailableReason!,/multiple.*sources/i);
});

test('country map keeps unknown and unsupported totals neutral, even with non-null stale summary values',async()=>{
 for(const availability of ['unknown','unsupported','no_results'] as const){
   const readUnavailable=(async(path:string,q:Record<string,string>={})=>path==='catalog'?{release_id:release,sources:[{...source,source_id:'official_nsw',jurisdiction:'NSW'}]}:{...await read<Record<string,unknown>>('query',{...q,source_id:source.source_id}),source_id:q.source_id,metric_availability:{crash_count:availability}}) as typeof publicationRead;
   const catalog=await resolveCatalog(release,false,readUnavailable);
   const result=await createPublishedProvider(catalog,createOfficialProvider(await loadOfficialSnapshot()),readUnavailable).getMapData(catalogFilters(catalog));
   const nsw=result.data.states?.find(s=>s.label==='NSW');assert.equal(nsw?.count,undefined);assert.equal(nsw?.available,false);
 }
});

test('country map fails closed on a mismatched published identity instead of borrowing snapshot counts',async()=>{
 const broken=(async(path:string,q:Record<string,string>={})=>path==='catalog'?{release_id:release,sources:[{...source,source_id:'official_nsw',jurisdiction:'NSW'}]}:{...await read<Record<string,unknown>>('query',{...q,source_id:source.source_id}),source_id:q.source_id,batch_id:'different-batch'}) as typeof publicationRead;
 const catalog=await resolveCatalog(release,false,broken);
 await assert.rejects(createPublishedProvider(catalog,createOfficialProvider(await loadOfficialSnapshot()),broken).getMapData(catalogFilters(catalog)),/identity mismatch/);
});

test('manual research authority stays visible in catalog, individual and All evidence',async()=>{
 const status={admission_level:'manual_reviewed',label:'Local research: official source identity unverified',official_registration:false,scope:'local_research'} as const;
 const manualRead=(async(path:string,q:Record<string,string>={})=>path==='catalog'
   ? {release_id:release,sources:[{...source,publication_status:status}]}
   : {...await read<Record<string,unknown>>(path,q),publication_status:status}) as typeof publicationRead;
 const catalog=await resolveCatalog(release,false,manualRead);
 const entry=catalog.sources.find(s=>s.sourceId===source.source_id)!;
 assert.equal(sourceDisplayName(entry,catalog),'ACT road crash records · local research');
 const provider=createPublishedProvider(catalog,createOfficialProvider(await loadOfficialSnapshot()),manualRead);
 for(const selected of [entry.source,'All']){
   const overview=await provider.getOverview({...catalogFilters(catalog),source:selected,dateRange:source.coverage});
   assert.match(JSON.stringify(overview.meta.evidence),/official source identity unverified/);
 }
 const dataset=(await provider.getDatasetMetadata()).find(d=>d.source===entry.source)!;
 assert.ok(dataset.description);
 assert.match(dataset.description,/official source identity unverified/);
 assert.deepEqual(dataset.evidence?.find(e=>e.title==='Source admission status')?.result,status);
});

test('catalog composes immutable baseline and independent same-jurisdiction sources, deduping native identity only',async()=>{
 const catalog=await resolveCatalog(release,false,read);
 assert.equal(parseAnalysisState("",catalog).error,undefined);
 assert.equal(catalog.sources.length,5);assert.equal(catalog.sources.filter(s=>s.jurisdiction==='ACT').length,2);
 assert.equal(catalog.coverage.to,'2025-12-31');
 const nativeRead=(async()=>({release_id:release,sources:[{...source,source_id:'official_nsw'}]})) as typeof publicationRead;
 const native=await resolveCatalog(release,false,nativeRead);
 assert.equal(native.sources.length,3);assert.equal(native.sources.find(s=>s.source==='NSW')?.batchId,batch);
 await assert.rejects(resolveCatalog('cccccccc-1111-4111-8111-cccccccccccc',false,read));
});
test('local URLs and Agent context pin release, preserve source identity, and reject substitution',async()=>{
 const catalog=await resolveCatalog(release,false,read),filters={...catalogFilters(catalog),source:source.source_id,dateRange:source.coverage};
 const href=analysisHref('/analytics',filters,DEFAULT_VIEW),params=new URL(href,'http://localhost').searchParams;
 assert.deepEqual(parseAnalysisState(params.toString(),catalog).filters,{...filters,regionId:undefined});
 assert.equal(parseDataFilters(params).releaseId,release);
 assert.equal(parseAgentRequest({context:{page:'/analytics',filters},message:'Show crashes',history:[]}).context.filters.source,source.source_id);
 assert.ok(parseAnalysisState(params.toString(),SNAPSHOT_CATALOG).error);
 assert.throws(()=>validateCatalogFilters({...filters,source:'fake'},catalog));
 assert.throws(()=>parseDataFilters(new URLSearchParams({...Object.fromEntries(params),batchId:batch})));
 const old=analysisHref('/',DEFAULT_FILTERS,DEFAULT_VIEW);
 assert.equal(parseAnalysisState(new URL(old,'http://localhost').search).filters.batchId,DEFAULT_FILTERS.batchId);
});
test('website, analysis tools and Studio workspace return the same pinned dynamic-source counts and nulls',async()=>{
 const catalog=await resolveCatalog(release,false,read),snapshot=await loadOfficialSnapshot();
 const service=createPublishedProvider(catalog,createOfficialProvider(snapshot),read);
 const filters={...catalogFilters(catalog),source:source.source_id,dateRange:source.coverage},context={page:'/studio',filters};
 const overview=await service.getOverview(filters);
 assert.equal(overview.data.crashes.value,2);assert.equal(overview.data.livesLost.value,null);assert.equal(overview.data.livesLost.availability,'unknown');
 assert.equal(overview.meta.releaseId,release);
 const mappedSnapshot={...snapshot,provenance:{...snapshot.provenance,version:LOCAL_VERSION,batchId:release,coverage:catalog.coverage}};
 const tool=await executeAnalysisTool('core_metrics',{source:null,dateRange:null},context,service,mappedSnapshot) as {releaseId:string;results:{data:{crashes:{value:number}}}[]};
 assert.equal(tool.releaseId,release);assert.equal(tool.results[0].data.crashes.value,2);
 const workspace=new AnalysisWorkspace(context,service,await loadRegionSnapshot(),catalog);
 const result=await workspace.execute('workspace_query',{dataset:'monthly_metrics',source:null,dateRange:null,regionId:null,groupBy:[],metrics:['crashes','livesLost'],where:[],orderBy:null,limit:10},new AbortController().signal,'evidence-test');
 assert.equal(result.releaseId,release);
 assert.equal((result.preview as {crashes:number;livesLost:null}[])[0].crashes,2);
 assert.equal((result.preview as {crashes:number;livesLost:null}[])[0].livesLost,null);
 const metadata=await service.getDatasetMetadata();
 assert.equal(metadata.find(d=>d.source===source.source_id)?.sourceBatchId,batch);
 const unsupportedMap=await service.getMapData(filters);
 assert.equal(unsupportedMap.meta.availability,'unsupported');
 assert.equal(unsupportedMap.meta.sourceBatchId,batch);
 assert.deepEqual(unsupportedMap.meta.coverage,{...source.coverage,complete:false,granularity:'month'}); // An unsupported query has no completeness proof.
 const unsupportedRecords=await service.getCrashRecords(filters,{page:1,pageSize:20},{field:'date',direction:'desc'});
 assert.equal(unsupportedRecords.meta.availability,'unsupported');
 assert.equal(unsupportedRecords.meta.sourceBatchId,batch);
 assert.deepEqual(unsupportedRecords.meta.coverage,{...source.coverage,complete:false,granularity:'month'}); // Bounds alone cannot establish coverage.
 const all=await service.getOverview({...filters,source:'All'});
 assert.equal(all.data.crashes.value,null);assert.equal(all.data.crashes.bySource?.length,5);
});

test('source-specific incomplete coverage blocks comparisons inside a wider composite release',async()=>{
 const catalog=await resolveCatalog(release,false,read),snapshot=await loadOfficialSnapshot();
 const partialRead=(async(_path:string,q:Record<string,string>)=>{
  const result=await read<Record<string,unknown>>('query',q);
  return {...result,coverage:{from:'2024-03-01',to:'2025-10-31',complete:false},summary:{crash_count:q.from.startsWith('2025')?8:4,fatal_crash_count:1,fatalities:null,casualties:null}};
 }) as typeof publicationRead;
 const service=createPublishedProvider(catalog,createOfficialProvider(snapshot),partialRead);
 const filters={...catalogFilters(catalog),source:source.source_id,dateRange:{from:'2025-01-01',to:'2025-12-31'}};
 const result=await executeAnalysisTool('compare_periods',{source:null,dateRange:null,baseline:{from:'2024-01-01',to:'2024-12-31'}},{page:'/studio',filters},service,{...snapshot,provenance:{...snapshot.provenance,version:LOCAL_VERSION,batchId:release,coverage:{from:'2020-01-01',to:'2026-12-31'}}}) as {results:{metrics:{availability:string;difference:null;percentChange:null}[]}[]};
 assert.equal(result.results[0].metrics[0].availability,'no_results');
 assert.equal(result.results[0].metrics[0].difference,null);assert.equal(result.results[0].metrics[0].percentChange,null);
});

test('published metric support preserves zero, unknown, unsupported and no-results across website and tools',async()=>{
 const catalog=await resolveCatalog(release,false,read),snapshot=await loadOfficialSnapshot();
 const supportRead=(async(path:string,q:Record<string,string>)=>({...await read<Record<string,unknown>>(path,q),summary:{crash_count:0,fatal_crash_count:null,fatalities:null,casualties:null},metric_availability:{crash_count:'available',fatal_crash_count:'unknown',fatalities:'unsupported',casualties:'no_results'}})) as typeof publicationRead;
 const service=createPublishedProvider(catalog,createOfficialProvider(snapshot),supportRead),filters={...catalogFilters(catalog),source:source.source_id,dateRange:source.coverage};
 const overview=await service.getOverview(filters);
 assert.deepEqual(Object.fromEntries(Object.entries(overview.data).filter(([key])=>key!=='fatalShare').map(([key,metric])=>[key,(metric as {availability:string}).availability])),{crashes:'available',fatalCrashes:'unknown',livesLost:'unsupported',casualties:'no_results'});
 assert.equal(overview.data.crashes.value,0);assert.equal(overview.data.livesLost.value,null);
 const monthly=await service.getTimeSeries(filters,'monthly');
 assert.deepEqual(monthly.meta.metricAvailability,overview.meta.metricAvailability);
 const context={page:'/studio',filters},mapped={...snapshot,provenance:{...snapshot.provenance,version:LOCAL_VERSION,batchId:release,coverage:catalog.coverage}};
 const tool=await executeAnalysisTool('core_metrics',{source:null,dateRange:null},context,service,mapped) as {results:{data:{livesLost:{availability:string;value:null}}}[]};
 assert.equal(tool.results[0].data.livesLost.availability,'unsupported');assert.equal(tool.results[0].data.livesLost.value,null);
 const workspace=new AnalysisWorkspace(context,service,await loadRegionSnapshot(),catalog);
 const queried=await workspace.execute('workspace_query',{dataset:'monthly_metrics',source:null,dateRange:null,regionId:null,groupBy:[],metrics:['livesLost'],where:[],orderBy:null,limit:10},new AbortController().signal,'E1');
 assert.equal((queried.sourceAvailability as {meta:{metricAvailability:{livesLost:string}}}[])[0].meta.metricAvailability.livesLost,'unsupported');
});

test('partial-month source coverage opens whole-month queries without inflating the declared coverage',async()=>{
 const partialSource={...source,coverage:{from:'2026-02-12',to:'2026-09-29'}};
 const partialRead=(async()=>({release_id:release,sources:[partialSource]})) as typeof publicationRead;
 const catalog=await resolveCatalog(release,false,partialRead);
 assert.deepEqual(catalog.sources.find(s=>s.source===source.source_id)?.coverage,partialSource.coverage);
 assert.equal(catalog.coverage.to,'2026-09-29');
 assert.equal(catalogFilters(catalog).dateRange.to,'2026-09-30');
 const filters={...catalogFilters(catalog),source:source.source_id,dateRange:coverageMonthRange(partialSource.coverage)};
 assert.deepEqual(filters.dateRange,{from:'2026-02-01',to:'2026-09-30'});
 const params=new URL(analysisHref('/',filters,DEFAULT_VIEW),'http://localhost').searchParams;
 assert.equal(parseAnalysisState(params.toString(),catalog).error,undefined);
 assert.deepEqual(parseDataFilters(params).dateRange,filters.dateRange);
 assert.deepEqual(coverageMonthRange({from:'2024-02-11',to:'2024-02-20'}),{from:'2024-02-01',to:'2024-02-29'});
});

test('AI time changes and monthly contributions reject partial source months while retaining known counts',async()=>{
 const catalog=await resolveCatalog(release,false,read),snapshot=await loadOfficialSnapshot();
 const partialRead=(async(_path:string,q:Record<string,string>)=>{
  const year=Number(q.from.slice(0,4)),counts={crash_count:year===2025?2:1,fatal_crash_count:0,fatalities:null,casualties:null};
  return {release_id:release,batch_id:batch,source_id:q.source_id,coverage:{from:'2024-01-01',to:'2025-12-20',complete:year===2024},availability:'available',summary:{...counts,crash_count:counts.crash_count*12},monthly:Array.from({length:12},(_,i)=>({year,month:i+1,...counts})),yearly:[{year,...counts,crash_count:counts.crash_count*12}],severity:[]};
 }) as typeof publicationRead;
 const service=createPublishedProvider(catalog,createOfficialProvider(snapshot),partialRead),filters={...catalogFilters(catalog),source:source.source_id,dateRange:source.coverage};
 const context={page:'/studio',filters},mapped={...snapshot,provenance:{...snapshot.provenance,version:LOCAL_VERSION,batchId:release,coverage:catalog.coverage}};
 const trend=await executeAnalysisTool('time_series',{source:null,dateRange:null,granularity:'monthly',metric:'crashes'},context,service,mapped) as {results:{points:{value:number;coverageComplete:boolean;previousPeriodChange:{difference:number}|null}[]}[]};
 assert.equal(trend.results[0].points[10].previousPeriodChange?.difference,0);
 assert.equal(trend.results[0].points[11].value,2);assert.equal(trend.results[0].points[11].coverageComplete,false);assert.equal(trend.results[0].points[11].previousPeriodChange,null);
 const contribution=await executeAnalysisTool('monthly_contributions',{source:null,dateRange:null,metric:'crashes'},context,service,mapped) as {results:{netChange:number|null;rows:{current:number;baseline:number;difference:number|null;percentChange:number|null;contributionToNetPercent:number|null}[]}[]};
 assert.equal(contribution.results[0].rows[0].difference,1);
 assert.equal(contribution.results[0].netChange,null);
 assert.deepEqual(contribution.results[0].rows[11],{source:source.source_id,period:'2025-12',baselinePeriod:'2024-12',current:2,baseline:1,difference:null,percentChange:null,percentReason:'Both matching months must be fully covered by this source.',contributionToNetPercent:null});
});

test('Analytics retains known partial-month subtotals but refuses a comparison and preserves unknown deaths',async()=>{
 const catalog=await resolveCatalog(release,false,read),snapshot=await loadOfficialSnapshot();
 const partialRead=(async(_path:string,q:Record<string,string>)=>{
  const year=Number(q.from.slice(0,4)), crashes=year===2025?2:1;
  const counts={crash_count:crashes,fatal_crash_count:0,fatalities:null,casualties:null};
  return {release_id:release,batch_id:batch,source_id:q.source_id,coverage:{from:'2024-01-01',to:'2025-12-20',complete:year===2024},availability:'available',summary:{...counts,crash_count:crashes*12},monthly:Array.from({length:12},(_,i)=>({year,month:i+1,...counts})),yearly:[{year,...counts,crash_count:crashes*12}],severity:[{code:'N',label:'No fatal crash',count:crashes*12}]};
 }) as typeof publicationRead;
 const service=createPublishedProvider(catalog,createOfficialProvider(snapshot),partialRead),filters={...catalogFilters(catalog),source:source.source_id,dateRange:source.coverage};
 const {data}=await getAnalytics(filters,service);
 assert.equal(data.yearly[0].crashes,24);assert.equal(data.timeSeriesYearly[0].crashes,24);
 assert.equal(data.yearly[0].fullYear,false);assert.equal(data.timeSeriesYearly[0].fullYear,false);
 assert.equal(data.yearly[0].comparisons.crashes.yoyPct,null);assert.match(data.yearly[0].comparisonReason!,/not fully covered by this source/);
 assert.equal(data.overview.livesLost.value,null);assert.equal(data.yearly[0].livesLost,null);
 assert.equal(data.yearly[0].fatalCrashes,0);assert.ok(data.monthly.every(row=>row.livesLost===null));
});

test('published annual points retain selected-month subtotal labels and physical batch evidence',async()=>{
 const catalog=await resolveCatalog(release,false,read),snapshot=await loadOfficialSnapshot();
 const service=createPublishedProvider(catalog,createOfficialProvider(snapshot),read);
 const f={...catalogFilters(catalog),source:source.source_id,dateRange:{from:'2025-01-01',to:'2025-03-31'}};
 const result=await service.getTimeSeries(f,'yearly');
 assert.deepEqual(result.data[0].selectedMonths,[1,2,3]);assert.equal(result.data[0].fullYear,false);
 assert.equal(timePointLabel(result.data[0]),'2025 · Jan–Mar subtotal (1/3 months)');
 assert.equal(result.meta.sourceBatchId,batch);
});

test('annual-only sources remain chartable in Analytics and queryable in Studio without fabricated months',async()=>{
 const catalog=await resolveCatalog(release,false,read),snapshot=await loadOfficialSnapshot();
 for(const item of catalog.sources.filter(s=>s.origin==='publication'))item.capabilities.monthly=false;
 const annualRead=(async(_path:string,q:Record<string,string>)=>{
  const year=Number(q.from.slice(0,4));const counts={crash_count:year===2025?12:10,fatal_crash_count:1,fatalities:null,casualties:null};
  return {release_id:release,batch_id:batch,source_id:q.source_id,coverage:{from:'2024-01-01',to:'2025-12-31',complete:true},availability:'available',summary:counts,monthly:[],yearly:[{year,...counts}],severity:[{code:'F',label:'Fatal',count:1},{code:'N',label:'Nonfatal',count:counts.crash_count-1}]};
 }) as typeof publicationRead;
 const service=createPublishedProvider(catalog,createOfficialProvider(snapshot),annualRead),filters={...catalogFilters(catalog),source:source.source_id,dateRange:source.coverage};
 const analytics=await getAnalytics(filters,service);
 assert.equal(analytics.data.monthlyAvailability,'unsupported');assert.equal(analytics.data.timeSeriesYearly[0].crashes,12);
 assert.equal(analytics.data.yearly[0].observedMonths,null);assert.equal(analytics.data.yearly[0].yoyPct,20);
 assert.ok(analytics.data.monthly.every(p=>p.crashes===null&&p.availability==='unsupported'));
 const workspace=new AnalysisWorkspace({page:'/studio',filters},service,await loadRegionSnapshot(),catalog);
 const args={source:null,dateRange:null,regionId:null,groupBy:[],metrics:['crashes'],where:[],orderBy:null,limit:10};
 const monthly=await workspace.execute('workspace_query',{...args,dataset:'monthly_metrics'},new AbortController().signal,'E1');
 assert.equal(monthly.availability,'unsupported');assert.equal((monthly.sourceAvailability as {meta:{availability:string}}[])[0].meta.availability,'unsupported');
 const yearly=await workspace.execute('workspace_query',{...args,dataset:'yearly_metrics'},new AbortController().signal,'E2');
 assert.equal(yearly.availability,'available');assert.deepEqual(yearly.preview,[{source:source.source_id,period:'2025',year:'2025',crashes:12}]);
});

test('trusted coordinate cells remain a separate truncated crash-only layer and analytical dataset',async()=>{
 const catalog=await resolveCatalog(release,false,read),snapshot=await loadOfficialSnapshot();
 catalog.sources.find(s=>s.source===source.source_id)!.capabilities.geography=true;
 const geography={status:'available',precision_degrees:0.1,cells:[{longitude:138.6,latitude:-34.9,crash_count:2},{longitude:139.1,latitude:-35.1,crash_count:1}],returned_cells:2,total_cells:3,truncated:true,located_crash_count:5,unlocated_crash_count:1};
 const geoRead=(async(path:string,q:Record<string,string>)=>({...await read<Record<string,unknown>>(path,q),geography})) as typeof publicationRead;
 const service=createPublishedProvider(catalog,createOfficialProvider(snapshot),geoRead),filters={...catalogFilters(catalog),source:source.source_id,dateRange:source.coverage};
 const result=await service.getMapData(filters);
 assert.equal(result.meta.releaseId,release);assert.equal(result.meta.sourceBatchId,batch);assert.equal(result.meta.availability,'available');
 assert.equal(result.data.illustrationOnly,false);assert.equal(result.data.regionMode,undefined);assert.deepEqual(result.data.regions,[]);
 assert.deepEqual(result.data.pointGrid,{metric:'crashes',precisionDegrees:0.1,cells:[{longitude:138.6,latitude:-34.9,count:2},{longitude:139.1,latitude:-35.1,count:1}],returnedCells:2,totalCells:3,truncated:true,locatedCrashCount:5,unlocatedCrashCount:1});
 assert.throws(()=>validateCatalogFilters({...filters,regionId:'40100'},catalog),/ABS area/);
 assert.equal((await service.getMapData({...filters,source:'All',dateRange:DEFAULT_FILTERS.dateRange})).meta.availability,'available'); // Existing pinned baseline maps remain visible.
 const workspace=new AnalysisWorkspace({page:'/studio',filters},service,await loadRegionSnapshot(),catalog);
 const args={dataset:'geographic_cells',source:null,dateRange:null,regionId:null,groupBy:[],metrics:['crashes'],where:[],orderBy:null,limit:10};
 const queried=await workspace.execute('workspace_query',args,new AbortController().signal,'E1');
 assert.equal(queried.availability,'available');assert.equal(queried.truncated,true);assert.equal(queried.observedRange,null);
 assert.deepEqual(queried.preview,[{source:source.source_id,longitude:138.6,latitude:-34.9,crashes:2},{source:source.source_id,longitude:139.1,latitude:-35.1,crashes:1}]);
 assert.equal((queried.coordinateCoverage as {totalCells:number}).totalCells,3);
 for(const override of [{metrics:['fatalCrashes']},{source:'All'}])assert.equal((await workspace.execute('workspace_query',{...args,...override},new AbortController().signal,'E2')).availability,'unsupported');
});

test('untrusted or malformed geographic cells cannot become a published map',async()=>{
 const catalog=await resolveCatalog(release,false,read),snapshot=await loadOfficialSnapshot(),filters={...catalogFilters(catalog),source:source.source_id,dateRange:source.coverage};
 const queryWith=(geography:unknown)=>(async(path:string,q:Record<string,string>)=>({...await read<Record<string,unknown>>(path,q),geography})) as typeof publicationRead;
 const cells=[{longitude:138.6,latitude:-34.9,crash_count:2}];
 assert.equal((await createPublishedProvider(catalog,createOfficialProvider(snapshot),queryWith({status:'available',precision_degrees:0.1,cells})).getMapData(filters)).meta.availability,'unsupported');
 catalog.sources.find(s=>s.source===source.source_id)!.capabilities.geography=true;
 assert.equal((await createPublishedProvider(catalog,createOfficialProvider(snapshot),queryWith({status:'unsupported',cells:[]})).getMapData(filters)).meta.availability,'no_results');
 for(const geography of [{status:'available',precision_degrees:0.001,cells},{status:'available',precision_degrees:0.1,cells,returned_cells:2},{status:'available',precision_degrees:0.1,cells,total_cells:3,truncated:false},{status:'available',precision_degrees:0.1,cells:[{...cells[0],latitude:999}]}])await assert.rejects(createPublishedProvider(catalog,createOfficialProvider(snapshot),queryWith(geography)).getMapData(filters));
});

test('catalog distinguishes explicit snapshot, no local publication, and backend failure',async()=>{
 const failure=(async()=>{throw Error('unavailable')}) as typeof publicationRead;
 await assert.rejects(resolveCatalog(undefined,false,failure),/publication service is unavailable/);
 assert.equal((await resolveCatalog(undefined,true,failure)).localStatus,'not_requested');
 const empty=(async()=>({release_id:null,sources:[]})) as typeof publicationRead;
 assert.equal((await resolveCatalog(undefined,false,empty)).localStatus,'empty');
});
test('local date boundaries match canonical supported years and reject outside years',()=>{
 for(const [from,to,valid] of [['1800-01-01','1800-12-31',true],['2200-01-01','2200-12-31',true],['1799-01-01','1800-12-31',false],['2199-01-01','2201-12-31',false]] as const){
   const query=new URLSearchParams({datasetVersion:LOCAL_VERSION,batchId:release,releaseId:release,source:'All',from,to});
   if(valid)assert.equal(parseDataFilters(query).dateRange.from,from);else assert.throws(()=>parseDataFilters(query));
 }
});
