import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { RESOURCE_DEFINITIONS, type ResearchAsset, type ResourceCatalogEntry, type ResourceId, type ResourceQuery, type ResourceRequest } from "../../services/studio-resources";
import type { ResearchContext, ResearchRun, Study } from "../../services/studio-contracts";
import type { AnalysisRow } from "../../services/analysis-contracts";
import type { Availability, Provenance, Response } from "../../services/contracts";
import { getAnalytics } from "../../services/analytics";
import { monthlyInsights, spatialConcentration, spatialInsights } from "../../services/analytics-insights";
import { comparisonAverage, comparisonChange, comparisonPeriods } from "../../services/period-comparison";
import { analysisRuntime } from "../agent/runtime";
import { loadRegionSnapshot } from "../region-data";
import { getSeverityChange } from "../severity-change";
import { getSpeedZones, loadSpeedZoneSnapshot } from "../speed-zone";
import { contextValue, now, StudioError, type StudioStore, textValue, uuid, validId } from "./store";

const metrics = ["crashes", "fatalCrashes", "livesLost", "casualties"] as const;
function exact(value: unknown, keys: readonly string[], name: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new StudioError(`Invalid ${name}.`);
  const obj = value as Record<string, unknown>;
  if (Object.keys(obj).some(key => !keys.includes(key))) throw new StudioError(`Unknown ${name} field.`);
  return obj;
}
import { resourceHash as hash, canonicalResourceHash as canonicalHash, actualResourceCoverage, verifyResearchAsset } from "./resource-integrity";
export { verifyResearchAsset } from "./resource-integrity";
function readContext(value: unknown) {
  const c=exact(value,["filters","metric","notes","references"],"context");
  const f=exact(c.filters,["source","regionId","dateRange","datasetVersion","batchId","releaseId"],"filters");
  exact(f.dateRange,["from","to"],"date range");
  return contextValue(c);
}
function queryValue(id: ResourceId, value: unknown): ResourceQuery {
  const allowed = id === "trend" ? ["granularity"] : id === "severity" ? ["severityMode"] : id === "period-comparison" ? ["comparison"] : id === "area-table" ? ["sort"] : [];
  const q=exact(value ?? {},allowed,"resource query");
  if (id === "trend") {
    if (q.granularity !== undefined && !["monthly","yearly"].includes(String(q.granularity))) throw new StudioError("Unsupported trend interval.");
    return {granularity:(q.granularity ?? "monthly") as "monthly"|"yearly"};
  }
  if (id === "severity") {
    if(q.severityMode !== undefined && !["count","share"].includes(String(q.severityMode))) throw new StudioError("Unsupported severity measure.");
    return {severityMode:(q.severityMode ?? "count") as "count"|"share"};
  }
  if (id === "area-table") {
    if(q.sort!==undefined && !["count","fatalShare","name"].includes(String(q.sort))) throw new StudioError("Unsupported area sort.");
    return {sort:(q.sort ?? "count") as "count"|"fatalShare"|"name"};
  }
  if (q.comparison !== undefined) {
    const pair=exact(q.comparison,["first","second"],"comparison periods");
    return {comparison:{first:textValue(pair.first,40),second:textValue(pair.second,40)}};
  }
  return {};
}
export function resourceRequest(value: unknown): ResourceRequest {
  const r=exact(value,["requestId","definitionId","context","query","title","target","document"],"resource request");
  if(!RESOURCE_DEFINITIONS.some(d=>d.id===r.definitionId)) throw new StudioError("Unknown Studio resource.");
  const definitionId=r.definitionId as ResourceId;
  let target:ResourceRequest["target"];
  if(r.target!==undefined){ const t=exact(r.target,["studyId","revision"],"target"); if(!Number.isSafeInteger(t.revision)||Number(t.revision)<1) throw new StudioError("A saved revision is required."); target={studyId:validId(t.studyId),revision:Number(t.revision)}; }
  let document:ResourceRequest["document"];
  if(r.document!==undefined){const d=exact(r.document,["afterId"],"document insertion");document=d.afterId===undefined?{}:{afterId:d.afterId===null?null:validId(d.afterId)};}
  return {requestId:validId(r.requestId),definitionId,context:readContext(r.context),query:queryValue(definitionId,r.query),...(r.title!==undefined?{title:textValue(r.title,120)}:{}),...(target?{target}:{}),...(document?{document}:{})};
}
interface ResourceResult {
  definitionId:ResourceId;
  context:ResearchContext;
  query:ResourceQuery;
  responses:Response<unknown>[];
  rows:AnalysisRow[];
  display:ResearchAsset["display"];
  availability:Availability;
  limitations:string[];
  unit:string;
  boundaries?:{url:string;sha256:string;geojson:unknown}[];
}
function overall(values: Availability[]): Availability {return values.includes("available")?"available":values.includes("unknown")?"unknown":values.includes("unsupported")?"unsupported":"no_results";}
function identity(meta:Provenance, context:ResearchContext, source:string){const f=context.filters;if(meta.source!==source||meta.datasetVersion!==f.datasetVersion||meta.batchId!==f.batchId||meta.releaseId!==f.releaseId)throw new StudioError("Resource response identity does not match the requested scope.",409);}
/** All counts/derived statistics come from the same readers used by the pages. */
export async function queryResource(definitionId:ResourceId, rawContext:ResearchContext, rawQuery:ResourceQuery={}):Promise<ResourceResult> {
  const context=readContext(rawContext), query=queryValue(definitionId,rawQuery);
  const definition=RESOURCE_DEFINITIONS.find(d=>d.id===definitionId);if(!definition)throw new StudioError("Unknown Studio resource.");
  const {service,catalog}=await analysisRuntime({page:"/studio",filters:context.filters});
  const sources=context.filters.source==="All"?catalog.sources.map(s=>s.source):[context.filters.source];
  const responses:Response<unknown>[]=[],rows:AnalysisRow[]=[],limitations:string[]=["Sources remain separate. Counts are not exposure-adjusted risk or evidence of causation."];
  const display:ResearchAsset["display"]={kind:definition.kind,x:"label",y:"count",series:context.filters.source==="All"?"source":null};
  let unit="crashes";const availabilities:Availability[]=[];const boundaries:NonNullable<ResourceResult["boundaries"]>=[];
  function add(response:Response<unknown>, source:string){identity(response.meta,context,source); responses.push(response);availabilities.push(response.meta.availability);if(response.meta.reason)limitations.push(response.meta.reason);limitations.push(response.meta.definition);}
  if(definitionId==="severity-change"||definitionId==="speed-zones"){
    const result=definitionId==="severity-change"?await getSeverityChange(context.filters,service,await loadRegionSnapshot(),catalog):await getSpeedZones(context.filters,service,await loadSpeedZoneSnapshot(),catalog);
    add(result,context.filters.source); unit=result.meta.unit;
    if(definitionId==="severity-change"){
      const typed=result as Awaited<ReturnType<typeof getSeverityChange>>;
      typed.data.groups.forEach(g=>{if(g.reason)limitations.push(g.reason);g.rows.forEach(r=>rows.push({source:g.source,...r}));});display.y="change";
    }else{
      const typed=result as Awaited<ReturnType<typeof getSpeedZones>>;
      typed.data.groups.forEach(g=>{if(g.reason)limitations.push(g.reason);g.rows.forEach(r=>rows.push({source:g.source,...r,label:typed.data.bands.find(b=>b.id===r.band)?.label??r.band}));});display.y="share";
      limitations.push("Unknown/special speed values are excluded from chart bands and preserved in the source result.");
    }
  }else if(["spatial-map","area-table","spatial-concentration"].includes(definitionId)){
    const maps = definitionId==="spatial-map"?[{source:context.filters.source,response:await service.getMapData(context.filters)}]:await Promise.all(sources.map(async source=>({source,response:await service.getMapData({...context.filters,source})})));
    for(const {source,response} of maps){add(response,source);const data=response.data;
      if(definitionId==="spatial-map"){
        if(data.pointGrid){rows.push(...data.pointGrid.cells.map(cell=>({source,...cell})));display.x="longitude";display.y="count";limitations.push(`Rounded ${data.pointGrid.precisionDegrees}° cells; not exact crash sites.`);}
        else if(data.states){rows.push(...data.states.map(state=>({source:state.source??state.code,label:state.name,count:state.count??null,availability:state.available?"available":"unsupported"})));}
        else rows.push(...data.regions.map(region=>({source,id:region.id,label:region.name,count:region.count,fatalCrashes:region.fatalCrashes??null})));
        if(response.meta.availability==="available"&&!data.illustrationOnly&&!data.pointGrid){
          // Only a server-returned local boundary asset may be copied, never a caller path or remote URL.
          if(!/^\/geo\/[a-z0-9-]+\.geojson$/.test(data.boundaryUrl))throw new StudioError("This map has no supported local boundary asset.",422);
          const bytes=await readFile(join(process.cwd(),"public",data.boundaryUrl));
          boundaries.push({url:data.boundaryUrl,sha256:createHash("sha256").update(bytes).digest("hex"),geojson:JSON.parse(bytes.toString())});
        }
        if(data.illustrationOnly){availabilities[availabilities.length-1]="unsupported";limitations.push("Illustrative geometry is not a verified spatial resource.");}
      }else if(data.pointGrid || data.regionMode!=="lga" || data.illustrationOnly){availabilities[availabilities.length-1]="unsupported";limitations.push(`${source}: this resource requires admitted LGA aggregates; coordinate grids are a different grain.`);}
      else if(definitionId==="spatial-concentration"){display.x="areaShare";display.y="crashShare";unit="percent of mapped crashes";rows.push(...spatialConcentration(data.regions).points.map(point=>({source,...point})));}
      else{const ranked=spatialInsights(data.regions).ranked;const sorted=[...ranked].sort((a,b)=>query.sort==="name"?a.name.localeCompare(b.name):query.sort==="fatalShare"?(b.fatalShare??-1)-(a.fatalShare??-1):a.rank-b.rank);rows.push(...sorted.map(r=>({source,id:r.id,label:r.name,rank:r.rank,count:r.count,share:r.share,fatalCrashes:r.fatalCrashes??null,fatalShare:r.fatalShare})));}
      if(data.coverage)limitations.push(`${source}: ${data.coverage.unmatched} unmatched records remain outside mapped-area statistics.`);
    }
  }else if(definitionId==="period-comparison"){
    const analytics=await Promise.all(sources.map(source=>getAnalytics({...context.filters,source},service)));
    const periods=comparisonPeriods(analytics.flatMap(r=>r.data.monthly));
    const first= query.comparison?periods.find(p=>p.label===query.comparison?.first):periods.find(p=>periods.some(q=>q.start>p.end));
    const second=query.comparison?periods.find(p=>p.label===query.comparison?.second):periods.filter(p=>first&&p.start>first.end).at(-1);
    if(!first||!second||first.end>=second.start)throw new StudioError("Choose two supported, ordered, non-overlapping comparison periods.",422);
    query.comparison={first:first.label,second:second.label};display.x="source";display.y="change";display.series=null;unit="percent change in monthly average";
    for(const response of analytics){add(response,response.data.source);const a=comparisonAverage(response.data.monthly,context.metric,first),b=comparisonAverage(response.data.monthly,context.metric,second);rows.push({source:response.data.source,periodA:first.label,periodB:second.label,averageA:a.average,averageB:b.average,observedA:a.observed,selectedA:a.selected,observedB:b.observed,selectedB:b.selected,change:comparisonChange(a,b)});}
    limitations.push("Averages use known selected months. Relative change requires complete periods and a positive baseline; null is not zero.");
  }else for(const source of sources){
    const f={...context.filters,source};
    if(definitionId==="overview-kpis"){
      const response=await service.getOverview(f);add(response,source);unit="source-specific metric units";
      rows.push(...metrics.map(metric=>({source,metric,label:response.data[metric].label,value:response.data[metric].value,unit:response.data[metric].unit,availability:response.data[metric].availability,definition:response.data[metric].definition})));display.y="value";
    }else if(definitionId==="trend"||definitionId==="fatal-outcomes"){
      const response=await service.getTimeSeries(f,definitionId==="fatal-outcomes"?"yearly":query.granularity??"monthly");add(response,source);display.x="period";display.y="value";
      if(definitionId==="fatal-outcomes"){display.series="series";unit="source-specific fatal crashes / people killed";rows.push(...response.data.flatMap(r=>["fatalCrashes","livesLost"].map(m=>({source,series:`${source} · ${m}`,metric:m,unit:m==="fatalCrashes"?"crashes":"people",period:r.period,value:r[m as "fatalCrashes"|"livesLost"],fullYear:r.fullYear===undefined?null:String(r.fullYear)}))));}
      else{unit=context.metric==="crashes"||context.metric==="fatalCrashes"?"crashes":"people";
        if(response.meta.availability==="available")availabilities[availabilities.length-1]=response.meta.metricAvailability?.[context.metric] ?? (response.data.length===0?"no_results":response.data.every(r=>r[context.metric]===null)?"unknown":"available");
        rows.push(...response.data.map(r=>({source,period:r.period,value:r[context.metric],fullYear:r.fullYear===undefined?null:String(r.fullYear),observedMonths:r.observedMonths??null})));}
    }else{
      const response=await getAnalytics(f,service);add(response,source);const data=response.data;
      if(definitionId==="severity"){availabilities[availabilities.length-1]=data.severityAvailability;if(data.severityReason)limitations.push(data.severityReason);rows.push(...data.severity.map(r=>({source,label:r.label,count:r.count,share:r.share,definition:r.definition})));display.y=query.severityMode==="share"?"share":"count";unit=query.severityMode==="share"?"fraction of recorded crashes":"crashes";}
      if(definitionId==="calendar-pattern"){availabilities[availabilities.length-1]=data.monthlyAvailability;display.x="month";display.y="average";unit=`${context.metric} per observed month`;rows.push(...monthlyInsights(data.monthly,context.metric).calendar.map(r=>({source,...r})));}
      if(definitionId==="monthly-matrix"){availabilities[availabilities.length-1]=data.monthlyAvailability;display.x="period";display.y="value";unit=context.metric;rows.push(...data.monthly.map(r=>({source,period:r.period,year:r.year,month:r.month,value:r[context.metric],availability:r.availability})));limitations.push("Monthly matrix is retained as an accessible data table; no heatmap colour scale is inferred.");}
      if(definitionId==="yearly-comparison"){display.x="year";display.y="current";unit=context.metric;rows.push(...data.yearly.map(r=>({source,year:r.year,...r.comparisons[context.metric],fullYear:String(r.fullYear),comparisonMonths:r.comparisonMonths.join(",")})));}
      limitations.push(...data.notes);
    }
  }
  const availability=overall(availabilities);
  const measure = definitionId==="severity" ? query.severityMode==="share"?"native_severity_share":"crashes"
    : definitionId==="severity-change"?"native_severity_share_change"
    : definitionId==="speed-zones"?"fatal_crash_share"
    : definitionId==="spatial-concentration"?"mapped_crash_share"
    : ["spatial-map","area-table"].includes(definitionId)?"crashes"
    : definitionId==="period-comparison"?`${context.metric}_monthly_average_change`
    : context.metric;
  const boundRows=rows.map(row=>{
    const result:AnalysisRow={...row,metric:row.metric??measure,unit:row.unit??unit};
    const period = ["trend","fatal-outcomes","monthly-matrix"].includes(definitionId)?row.period:definitionId==="yearly-comparison"?String(row.year):null;
    if(typeof period==="string"&&/^\d{4}(-\d{2})?$/.test(period)){
      const from=period.length===4?`${period}-01-01`:`${period}-01`;
      const to=period.length===4?`${period}-12-31`:`${period}-${new Date(Date.UTC(Number(period.slice(0,4)),Number(period.slice(5)),0)).getUTCDate()}`;
      result.from=from>context.filters.dateRange.from?from:context.filters.dateRange.from;
      result.to=to<context.filters.dateRange.to?to:context.filters.dateRange.to;
    }
    return result;
  });
  return {definitionId,context,query,responses,rows:boundRows,display,availability,limitations:[...new Set(limitations)],unit,...(boundaries.length?{boundaries}:{})};
}
export async function saveResource(store:StudioStore,input:unknown):Promise<Study>{
  const request=resourceRequest(input);
  const requestHash=canonicalHash(request);
  // An already-bound immutable server result is reusable, including after the live source disappears.
  // No caller-provided result or cross-study reference is accepted.
  const repeat=store.db.prepare("SELECT study_id,run_id FROM run_requests WHERE request_id=?").all(request.requestId) as {study_id:string;run_id:string}[];
  if(repeat.length){if(repeat.length!==1)throw new StudioError("Ambiguous resource request identity.",409);const study=store.get(repeat[0].study_id),run=study.runs.find(r=>r.id===repeat[0].run_id);if(!run?.resource||run.resource.requestHash!==requestHash||run.resource.targetStudyId!==request.target?.studyId)throw new StudioError("Resource request ID is already bound to a different save.",409);verifyResearchAsset(run);return study;}
  if(request.target&&store.get(request.target.studyId).revision!==request.target.revision)throw new StudioError("This study changed. Reload before adding the resource.",409);
  const result=await queryResource(request.definitionId,request.context,request.query);
  if(result.availability!=="available")throw new StudioError(`Resource is ${result.availability}: ${result.limitations.join(" ")}`,422);
  const at=now(), resultHash=hash(result), resource:ResearchAsset={id:uuid(),definitionId:request.definitionId,definitionVersion:1,requestId:request.requestId,requestHash,...(request.target?{targetStudyId:request.target.studyId}:{}),context:result.context,query:result.query,resultHash,bindingHash:canonicalHash({context:result.context,query:result.query,definitionId:request.definitionId,definitionVersion:1,resultHash}),availability:result.availability,display:result.display,actualCoverage:actualResourceCoverage(result.responses,result.context.filters.dateRange),unit:result.unit,limitations:result.limitations,createdAt:at};
  const title=RESOURCE_DEFINITIONS.find(d=>d.id===request.definitionId)!.label;
  const run:ResearchRun={id:uuid(),question:`Save ${title}`,context:result.context,status:"complete",answer:`Saved ${title} from a server query. ${result.limitations.join(" ")}`,progress:"",createdAt:at,updatedAt:at,attempt:1,previousAttempts:[],plan:[],skipPresentation:false,artifactIds:[],changes:[],origin:"analytics",resource,evidence:[{id:"E1",title,description:"Immutable server-queried resource, with exact selected scope and source result. No client result rows were accepted.",result,query:{tool:`studio_resource:${request.definitionId}`,parameters:result.query,requestedContext:{page:"/studio",filters:result.context.filters},assurance:{parameters:"validated",execution:"server-query-complete",claims:"not_automatically_verified"}}}],views:[{id:resource.id,title,kind:result.display.kind==="map"||result.display.kind==="kpi"?"table":result.display.kind,rows:result.rows,x:result.display.x,y:result.display.y,series:result.display.series,evidenceId:"E1",source:result.context.filters.source,period:`${result.context.filters.dateRange.from} – ${result.context.filters.dateRange.to}`,truncated:false}]};
  return store.saveResource({requestId:request.requestId,requestHash,title:request.title??title,context:result.context,run,target:request.target,document:request.document});
}
export async function resourceCatalog(rawContext:unknown):Promise<ResourceCatalogEntry[]>{
  const context=readContext(rawContext);
  return Promise.all(RESOURCE_DEFINITIONS.map(async definition=>{
    try{const result=await queryResource(definition.id,context);return {...definition,availability:result.availability,reason:result.availability==="available"?undefined:result.limitations.join(" "),limitations:result.limitations,query:result.query};}
    catch(error){return {...definition,availability:"unsupported" as const,reason:error instanceof StudioError?error.message:"The selected resource could not be verified by its source service.",limitations:["No substitute results are used."],query:{}};}
  }));
}
