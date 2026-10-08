import { hasRegionalProvider } from '../services/catalog-contracts';
import { selectedMonths } from "../services/periods";
import type { Filters, Overview, Provenance, Availability, TimePoint, Severity, Dataset } from '../services/contracts';
import type { DataCatalog, CatalogSource } from '../services/catalog-contracts';
import { DEFAULT_FILTERS } from '../services/config';
import { publicationRead, validateCatalogFilters } from './data-catalog';
import type { OfficialReadService } from './official-data';
interface Counts { crash_count:number|null; fatal_crash_count:number|null; fatalities:number|null; casualties:number|null }
interface QueryResult {
  selection_quality?: import("../services/preprocessing-contracts").SelectionQuality;
  publication_status?: CatalogSource['publicationStatus'];
  release_id:string; batch_id:string; source_id:string;
  availability:'available'|'unsupported'|'no_results';reason?:string;
  coverage:{from:string;to:string;complete:boolean};summary:Counts;
  capability_limits?: CatalogSource['capabilityLimits']; capability_review?: unknown;
  row_preprocessing?: CatalogSource['rowPreprocessing'];
  retained_resources?: CatalogSource['retainedResources'];
  metric_availability?: Partial<Record<keyof Counts,Availability>>;
  geography?: {status:string;precision_degrees?:number;reason?:string;cells?:{longitude:number;latitude:number;crash_count:number}[];total_cells?:number;returned_cells?:number;truncated?:boolean;located_crash_count?:number;unlocated_crash_count?:number};
  monthly:(Counts & {year:number;month:number})[]; yearly:(Counts & {year:number})[];
  severity:{code:string;label:string;count:number}[]; limitations?:string[]; qa?:unknown[];
}
const fields = {crashes:'crash_count',fatalCrashes:'fatal_crash_count',livesLost:'fatalities',casualties:'casualties'} as const;
const labels = {crashes:'Crashes',fatalCrashes:'Fatal crashes',livesLost:'Lives lost',casualties:'Casualties'};
const combinedAvailability = (values:Availability[]):Availability => values.includes("available") ? "available" : values.every(v=>v==="no_results") ? "no_results" : values.every(v=>v==="unsupported") ? "unsupported" : "unknown";
const keys = Object.keys(fields) as (keyof typeof fields)[];
const metricAvailability = (q:QueryResult,key:keyof typeof fields):Availability => q.metric_availability?.[fields[key]] || (q.availability==='available' ? q.summary[fields[key]]===null ? 'unknown' : 'available' : q.availability);
export function createPublishedProvider(catalog:DataCatalog, baseline:OfficialReadService, read:typeof publicationRead = publicationRead):OfficialReadService {
  const entry = (f:Filters) => { validateCatalogFilters(f,catalog); const s=catalog.sources.find(s=>s.source===f.source); if (!s) throw Error('Choose one catalog source.'); return s; };
  const oldFilters = (f:Filters):Filters => ({...f,datasetVersion:DEFAULT_FILTERS.datasetVersion,batchId:DEFAULT_FILTERS.batchId,releaseId:undefined});
  const query = async(f:Filters,s:CatalogSource) => {
    const q=await read<QueryResult>('query',{release_id:catalog.releaseId!,source_id:s.sourceId,from:f.dateRange.from,to:f.dateRange.to,include_units:'false'});
    if(q.release_id!==catalog.releaseId || q.batch_id!==s.batchId || q.source_id!==s.sourceId) throw Error('Publication identity mismatch.');
    return q;
  };
  function meta(f:Filters,s?:CatalogSource,q?:QueryResult):Provenance {
    const coverage=q?.coverage || {...(s?.coverage || catalog.coverage),complete:s?.origin === "snapshot" ? f.dateRange.from>=s.coverage.from && f.dateRange.to<=s.coverage.to : !!s?.completeIntervals?.some(i=>i.from<=f.dateRange.from && i.to>=f.dateRange.to)};
    return {demo:false,source:f.source,datasetVersion:catalog.datasetVersion,batchId:catalog.batchId,releaseId:catalog.releaseId,sourceBatchId:s?.batchId,sourceBatches:Object.fromEntries(catalog.sources.map(item=>[item.source,item.batchId])),availability:q?.availability || 'available',reason:q?.reason,...(q?{metricAvailability:Object.fromEntries(keys.map(key=>[key,metricAvailability(q,key)]))}:{}),
      coverage:{...coverage,granularity:'month'},definition:'Source-specific observations in a pinned local release. Sources are never pooled.',unit:'crashes',
      evidence:[{id:`release-${catalog.releaseId}`,title:'Immutable local release',description:`Release ${catalog.releaseId}; source batch ${s?.batchId || 'see source metadata'}.`, result:{publicationStatus:s?.publicationStatus,sourcePublicationStatus:Object.fromEntries(catalog.sources.map(item=>[item.source,item.publicationStatus || null])),capabilityLimits:s?.capabilityLimits || [],capabilityReview:s?.capabilityReview,rowPreprocessing:s?.rowPreprocessing,retainedResources:s?.retainedResources},...(q ? {result:{publicationStatus:q.publication_status || s?.publicationStatus,selectionQuality:q.selection_quality,releaseId:q.release_id,sourceBatchId:q.batch_id,sourceId:q.source_id,qa:q.qa || [],limitations:q.limitations || [],capabilityLimits:q.capability_limits || s?.capabilityLimits || [],capabilityReview:q.capability_review || s?.capabilityReview,rowPreprocessing:q.row_preprocessing || s?.rowPreprocessing,retainedResources:q.retained_resources || s?.retainedResources}} : {}),href:`/api/data/evidence?${new URLSearchParams({source:f.source,from:f.dateRange.from,to:f.dateRange.to,datasetVersion:f.datasetVersion,batchId:f.batchId,releaseId:f.releaseId!})}`}]};
  }
  const retag=<T>(r:{data:T;meta:Provenance},f:Filters,s:CatalogSource) => ({data:r.data,meta:{...r.meta,...meta(f,s),definition:r.meta.definition,availability:r.meta.availability,reason:r.meta.reason,coverage:r.meta.coverage,evidence:[...r.meta.evidence,...meta(f,s).evidence,...(s.regionalProvider ? [{id:`regional-${s.batchId}`,title:'Verified regional publication binding',description:'Same original resources and reconciled monthly metrics. Derived LGA name matching; canonical point eligibility and QA07 are unchanged.',result:s.regionalProvider}] : [])]}});
  const regional = (f:Filters,s:CatalogSource) => hasRegionalProvider(s,catalog.releaseId) && !!s.regionalProvider &&
    f.dateRange.from>=s.regionalProvider.coverage.from && f.dateRange.to<=s.regionalProvider.coverage.to;
  async function regionalFilters(f:Filters,s:CatalogSource) {
    // Compare the live pinned publication, not just its stored import report.
    const binding=s.regionalProvider!;
    const linked={...f,datasetVersion:binding.datasetVersion,batchId:binding.batchId,releaseId:undefined};
    const [q,reference]=await Promise.all([query({...f,regionId:undefined},s),baseline.getOverview({...linked,regionId:undefined})]);
    if (q.availability!=='available' || !q.coverage.complete || keys.some(key=>q.summary[fields[key]]!==reference.data[key].value))
      throw Error('Regional publication reconciliation failed. No snapshot has been substituted.');
    return linked;
  }
  const point=(r:Counts,period:string,source:string):TimePoint=>({period,source,crashes:r.crash_count,fatalCrashes:r.fatal_crash_count,livesLost:r.fatalities,casualties:r.casualties});
  const service:OfficialReadService={
    async getOverview(f) {
      validateCatalogFilters(f,catalog);
      if(f.source==='All') {
        const results=await Promise.all(catalog.sources.map(s=>service.getOverview({...f,source:s.source})));
        const data={fatalShare:null} as Overview;
        for(const k of keys) data[k]={label:labels[k],value:null,availability:combinedAvailability(results.map(r=>r.data[k].availability)),unit:k==='livesLost'||k==='casualties'?'people':'crashes',definition:'Separate source-specific counts; overlapping datasets and different definitions must not be added.',bySource:results.map((r,i)=>({source:catalog.sources[i].source,value:r.data[k].value,availability:r.data[k].availability}))};
        return {data,meta:{...meta(f),availability:combinedAvailability(results.map(r=>r.meta.availability)),coverage:{...meta(f).coverage,complete:results.every(r=>r.meta.coverage.complete)}}};
      }
      const s=entry(f);if(s.origin==='snapshot') return retag(await baseline.getOverview(oldFilters(f)),f,s);
      if(f.regionId && regional(f,s)) return retag(await baseline.getOverview(await regionalFilters(f,s)),f,s);
      const q=await query(f,s), data={fatalShare:q.summary.crash_count && q.summary.fatal_crash_count!==null?q.summary.fatal_crash_count/q.summary.crash_count:null} as Overview;
      for(const k of keys) {const value=q.summary[fields[k]],availability=metricAvailability(q,k);data[k]={label:labels[k],value,availability,unit:k==='livesLost'||k==='casualties'?'people':'crashes',definition:s.definitions[k] || 'See the source evidence for this metric definition.',reason:availability==='unsupported'?(q.availability==='unsupported'&&q.reason?q.reason:`This source does not provide ${labels[k].toLowerCase()}.`):availability==='unknown'?'No known observation for this measure in the selected period.':q.reason};}
      return {data,meta:meta(f,s,q)};
    },
    async getTimeSeries(f,granularity) {
      validateCatalogFilters(f,catalog);
      if(f.source==='All') {const all=await Promise.all(catalog.sources.map(s=>service.getTimeSeries({...f,source:s.source},granularity)));return {data:all.flatMap((r,i)=>r.data.map(p=>({...p,source:catalog.sources[i].source}))),meta:{...meta(f),availability:combinedAvailability(all.map(r=>r.meta.availability)),coverage:{...meta(f).coverage,complete:all.every(r=>r.meta.coverage.complete)}}};}
      const s=entry(f);if(s.origin==='snapshot') return retag(await baseline.getTimeSeries(oldFilters(f),granularity),f,s);
      if(f.regionId && regional(f,s)) return retag(await baseline.getTimeSeries(await regionalFilters(f,s),granularity),f,s);
      const q=await query(f,s), m=meta(f,s,q);
      if(granularity==='monthly'&&!s.capabilities.monthly) return {data:[],meta:{...m,availability:'unsupported',reason:'This dataset does not establish calendar months. Annual observations remain available.'}};
      const data=granularity==='monthly'?q.monthly.map(r=>point(r,`${r.year}-${String(r.month).padStart(2,'0')}`,s.source)):q.yearly.map(r=>{ const selected = selectedMonths(f,r.year); const observed = s.capabilities.monthly ? q.monthly.filter(month=>month.year===r.year).length : undefined; return {...point(r,String(r.year),s.source),selectedMonths:selected,observedMonths:observed,fullYear:q.coverage.complete && selected.length===12 && q.coverage.from<=`${r.year}-01-01` && q.coverage.to>=`${r.year}-12-31` && (observed===undefined || observed===12)}; });
      return {data,meta:m};
    },
    async getSeverityDistribution(f) {
      validateCatalogFilters(f,catalog);
      if(f.source==='All') {const all=await Promise.all(catalog.sources.map(s=>service.getSeverityDistribution({...f,source:s.source})));return {data:all.flatMap(r=>r.data),meta:{...meta(f),availability:combinedAvailability(all.map(r=>r.meta.availability)),coverage:{...meta(f).coverage,complete:all.every(r=>r.meta.coverage.complete)}}};}
      const s=entry(f);if(s.origin==='snapshot')return retag(await baseline.getSeverityDistribution(oldFilters(f)),f,s);
      if(f.regionId && regional(f,s)) return retag(await baseline.getSeverityDistribution(await regionalFilters(f,s)),f,s);
      const q=await query(f,s);const data:Severity[]=q.severity.map(r=>({source:s.source,label:r.label,count:r.count,definition:s.definitions.severity || 'Source-native severity; categories are not pooled across sources.'}));
      return {data,meta:{...meta(f,s,q),...(!s.capabilities.severity?{availability:'unsupported' as const,reason:'Severity classification is not established for this source.'}:{})}};
    },
    async getMapData(f) {
      validateCatalogFilters(f,catalog);
      if(f.source==='All') {
        const original = await baseline.getMapData(oldFilters(f));
        // The baseline supplies ABS boundary identities, never replacement counts.
        // State totals need a declared jurisdiction, not an LGA/coordinate provider.
        const entries = (original.data.states || []).map(state => ({state,sources:catalog.sources.filter(item=>item.jurisdiction===state.label)}));
        const observations = await Promise.all(entries.map(async ({sources}) => sources.length===1
          ? service.getOverview({...f,source:sources[0].source}) : undefined));
        const states = entries.map(({state,sources},index) => {
          const metric = observations[index]?.data.crashes;
          const count = metric?.availability==='available' && metric.value!==null ? metric.value : undefined;
          if(count!==undefined && (!Number.isSafeInteger(count) || count<0))throw Error('Invalid state crash aggregate.');
          return {...state,source:sources.length===1?sources[0].source:undefined,available:count!==undefined,count};
        });
        const ambiguous = entries.filter(item=>item.sources.length>1).map(item=>item.state.label);
        const results = observations.filter(result=>result!==undefined);
        const definition = 'State/source aggregate crash counts from the pinned release on ABS reference boundaries. These are not crash locations, regional hotspots, severity rates or comparable interstate risk measures. Overlapping sources are not combined.';
        return {data:{...original.data,states,...(ambiguous.length?{unavailableReason:`${ambiguous.join(', ')} has multiple separate sources. Choose a source to inspect it; their counts are not combined on the country map.`}:{})},meta:{...meta(f),
          availability:states.some(state=>state.available)?'available':results.length?combinedAvailability(results.map(result=>result.data.crashes.availability)):'unsupported',
          coverage:{...meta(f).coverage,complete:false},definition,reason:'State totals use the same source and date selection as the overview. Detailed geographic layers have independent availability.',
          evidence:[...meta(f).evidence,...results.flatMap(result=>result.meta.evidence)]}};
      }
      if(f.source!=='All') {
        const s=entry(f);if(s.origin==='snapshot')return retag(await baseline.getMapData(oldFilters(f)),f,s);
        if(regional(f,s)) return retag(await baseline.getMapData(await regionalFilters(f,s)),f,s);
        if(s.capabilities.geography) {
          const q=await query(f,s),geo=q.geography;
          if(geo?.status==='available' && geo.cells?.length) {
            if(geo.precision_degrees!==0.1 || geo.cells.length>2000 || geo.cells.some(c=>!Number.isFinite(c.longitude)||!Number.isFinite(c.latitude)||c.longitude < -180||c.longitude>180||c.latitude < -85||c.latitude>85||!Number.isSafeInteger(c.crash_count)||c.crash_count<0))throw Error('Invalid published coordinate aggregate.');
            const cells=geo.cells.map(c=>({longitude:c.longitude,latitude:c.latitude,count:c.crash_count}));
            for(const count of [geo.total_cells,geo.returned_cells,geo.located_crash_count,geo.unlocated_crash_count])if(count!==undefined&&(!Number.isSafeInteger(count)||count<0))throw Error('Invalid coordinate coverage metadata.');
            if(geo.returned_cells!==undefined&&geo.returned_cells!==cells.length || geo.total_cells!==undefined&&geo.total_cells<cells.length || geo.total_cells!==undefined&&geo.truncated!==undefined&&geo.truncated!==(geo.total_cells>cells.length))throw Error('Inconsistent coordinate coverage metadata.');
            const lon=cells.map(c=>c.longitude),lat=cells.map(c=>c.latitude);
            return {data:{level:'state',boundaryUrl:'/geo/australia-states.geojson',regions:[],bounds:[[Math.max(-180,Math.min(...lon)-0.5),Math.max(-85,Math.min(...lat)-0.5)],[Math.min(180,Math.max(...lon)+0.5),Math.min(85,Math.max(...lat)+0.5)]],illustrationOnly:false,legendLabel:'Recorded crashes by rounded coordinate cell',pointGrid:{metric:'crashes',precisionDegrees:0.1,cells,returnedCells:cells.length,totalCells:geo.total_cells,truncated:geo.truncated,locatedCrashCount:geo.located_crash_count,unlocatedCrashCount:geo.unlocated_crash_count}},meta:{...meta(f,s,q),availability:'available',definition:'Crash counts grouped by trusted coordinates rounded to 0.1 degrees. Cell centres are not exact crash sites or ABS area assignments.'}};
          }
          if(q.availability==='no_results' || geo && q.availability==='available') return {data:{level:'state',boundaryUrl:'/geo/australia-states.geojson',regions:[],bounds:[[112,-44],[154,-10]],illustrationOnly:false,legendLabel:'No coordinate observations',unavailableReason:'No trusted coordinate cells are available in the selected source and period.'},meta:{...meta(f,s,q),availability:'no_results',reason:'No trusted coordinate cells are available in this selection.'}};
        }
      }
      return {data:{level:f.source==='All'?'country':'state',boundaryUrl:'/geo/australia-states.geojson',regions:[],bounds:[[112,-44],[154,-10]],illustrationOnly:false,legendLabel:'Geography unavailable',unavailableReason:'No verified geographic aggregate provider is published for this selection.'},meta:{...meta(f,f.source==='All'?undefined:entry(f)),availability:'unsupported',reason:'Geographic capability is unavailable. No locations are inferred.'}};
    },
    async getCrashRecords(f,pagination,sort) {
      if(f.source!=='All'){const s=entry(f);if(s.origin==='snapshot')return retag(await baseline.getCrashRecords(oldFilters(f),pagination,sort),f,s);}
      validateCatalogFilters(f,catalog);
      return {data:{rows:[],total:0,page:pagination.page,pageSize:pagination.pageSize,aggregateCount:null,sampleOnly:false},meta:{...meta(f,f.source==='All'?undefined:entry(f)),availability:'unsupported',reason:'Raw records are not exposed by the website provider.'}};
    },
    async getDatasetMetadata() {
      const base=await baseline.getDatasetMetadata();
      return catalog.sources.map(s=>s.origin==='snapshot'?{...base.find(d=>d.source===s.source)!,version:catalog.datasetVersion,batchId:catalog.batchId,sourceBatchId:s.batchId,releaseId:catalog.releaseId,description:`Baseline reference within release ${catalog.releaseId}`}:{source:s.source,title:s.title,version:catalog.datasetVersion,batchId:catalog.batchId,sourceBatchId:s.batchId,releaseId:catalog.releaseId,coverage:`${s.coverage.from} → ${s.coverage.to}`,description:`${s.publicationStatus?.label || 'Admission not classified'} · ${s.publisher} · ${s.jurisdiction} · release ${catalog.releaseId}`,limitations:s.limitations,metricDefinitions:Object.entries(s.definitions).map(([label,value])=>({label,value})),evidence:[{id:`admission-${s.batchId}`,title:'Source admission status',description:s.publicationStatus?.label || 'Historical publication: admission not classified',result:s.publicationStatus,rows:[{label:'Official registry admission',value:s.publicationStatus?.official_registration ? 'Registered after independent QA' : 'Not registered as an official adapter'},{label:'Scope',value:'Local research; this status does not grant redistribution permission.'}]},...(s.retainedResources ? [{id:`retained-${s.batchId}`,title:'Unverified auxiliary records',description:s.retainedResources.limitation,result:s.retainedResources,rows:s.retainedResources.resources.map(r=>({label:r.role,value:`${r.records_scanned} original records retained · ${r.semantic_qa} · ${r.reason}`}))}] : []),...(s.rowPreprocessing ? [{id:`row-processing-${s.batchId}`,title:'Original row destinations',description:'Whole-input duplicate accounting; these totals are not limited to the current date filter.',result:s.rowPreprocessing,rows:[{label:'Input records in processed resources',value:String(s.rowPreprocessing.raw_rows)},{label:'Retained records',value:String(s.rowPreprocessing.raw_rows-s.rowPreprocessing.collapsed_duplicate_rows)},{label:'Identical duplicate records',value:String(s.rowPreprocessing.collapsed_duplicate_rows)}]}] : []),{id:`capabilities-${s.batchId}`,title:'Requested and achieved capabilities',description:'Unresolved requirements and original capability diagnostics remain visible.',result:{limits:s.capabilityLimits || [],review:s.capabilityReview},rows:(s.capabilityLimits || []).map(item=>({label:item.capability,value:`${item.requested?'Requested':'Optional'} · ${item.status} · ${item.reason} · ${item.actual}`}))},{id:`batch-${s.batchId}`,title:'Source publication',description:`${s.sourceId} · ${s.batchId} · ${catalog.releaseId}`}, {id:`licence-${s.batchId}`, title:'Resource licence status',description:'Local research scope; external redistribution has not been assessed.',result:s.licensing,rows:s.licensing?.resources.map(r=>({label:r.role,value:`${r.status} · ${r.resource_url || 'resource not established'} · ${r.limitation}`})) || [{label:'Status',value:'Unknown for this historical publication.'}]}]} satisfies Dataset);
    },
  };
  return service;
}
