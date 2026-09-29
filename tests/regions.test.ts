import test, { before } from "node:test";
import assert from "node:assert/strict";
import { loadOfficialSnapshot, createOfficialProvider, parseOfficialFilters } from "../src/server/official-data";
import { loadRegionSnapshot, createRegionalProvider, regionEvidence } from "../src/server/region-data";
import { DEFAULT_FILTERS, selectSource } from "../src/services/config";
import { executeAnalysisTool } from "../src/server/agent/tools";
import { parseAgentRequest } from "../src/server/agent/request";
import type { Source } from "../src/services/contracts";
let snapshot: Awaited<ReturnType<typeof loadOfficialSnapshot>>, regional: Awaited<ReturnType<typeof loadRegionSnapshot>>, service: ReturnType<typeof createRegionalProvider>;
before(async () => {
  snapshot = await loadOfficialSnapshot(); regional = await loadRegionSnapshot();
  service = createRegionalProvider(createOfficialProvider(snapshot), regional);
});
const expected = { NSW: [92077,5], VIC: [69805,2365], QLD: [66623,1] };
for (const source of ["NSW","VIC","QLD"] as Source[]) test(`${source}: real region coverage reconciles per month, source metrics and severity remain pinned`, async () => {
  const f = selectSource(DEFAULT_FILTERS,source), map = await service.getMapData(f);
  assert.deepEqual([map.data.coverage!.matched,map.data.coverage!.unmatched], expected[source]);
  assert.equal(map.data.regions.reduce((n,r)=>n+r.count,0),expected[source][0]);
  assert.equal(map.data.illustrationOnly,false);
  assert.equal(map.meta.availability,"available");
  assert.ok(map.data.regions.every(r=>!r.coordinates));
  const months = await service.getTimeSeries(f,"monthly");
  for (const month of months.data) {
    const rows=regional.sources[source].rows.filter(r=>r[0]===month.period);
    for(const [i,key] of (["crashes","fatalCrashes","livesLost","casualties"] as const).entries())
      assert.equal(rows.reduce((n,r)=>n+(r[i+2] as number),0),month[key]);
  }
});
test("Sydney and Brisbane LGA counts match independent raw name profiles; localities are distinct labels", async()=>{
  for(const [source,regionId,crashes] of [["NSW","17200",2932],["QLD","31000",16662]] as const) {
    const f={...selectSource(DEFAULT_FILTERS,source),regionId};
    const overview=await service.getOverview(f),trend=await service.getTimeSeries(f,"monthly"),severity=await service.getSeverityDistribution(f),map=await service.getMapData(f);
    assert.equal(overview.data.crashes.value,crashes);
    assert.equal(trend.data.reduce((n,r)=>n+r.crashes!,0),crashes);
    assert.equal(severity.data.reduce((n,r)=>n+r.count,0),crashes);
    const r=map.data.regions.find(r=>r.id===regionId)!;
    assert.ok(r.localities!.length>0 && r.localities!.length<=8);
    assert.ok(r.localityTotal!<=crashes);
  }
});
test("regional severity is genuinely month-counted, source-only partial severity remains unsupported",async()=>{
  const f={...selectSource(DEFAULT_FILTERS,"NSW"),regionId:"17200",dateRange:{from:"2024-01-01",to:"2024-06-30"}};
  const s=await service.getSeverityDistribution(f),o=await service.getOverview(f);
  assert.equal(s.meta.availability,"available");
  assert.equal(s.data.reduce((n,r)=>n+r.count,0),o.data.crashes.value);
  assert.equal((await service.getSeverityDistribution({...f,regionId:undefined})).meta.availability,"unsupported");
});
test("0 matched crashes, outside coverage, unknown measures and wrong batch are different",async()=>{
  const f={...selectSource(DEFAULT_FILTERS,"QLD"),regionId:"37570"};
  assert.equal((await service.getOverview(f)).data.crashes.value,0);
  assert.equal((await service.getOverview({...f,dateRange:{from:"2025-01-01",to:"2025-12-31"}})).data.crashes.value,null);
  assert.equal((await service.getOverview({...f,batchId:"other"})).meta.availability,"unsupported");
  const copy=structuredClone(regional),cell=copy.sources.NSW.rows.find(r=>r[1]==="17200")!;cell[4]=null;
  const unknown=await createRegionalProvider(createOfficialProvider(snapshot),copy).getOverview({...DEFAULT_FILTERS,source:"NSW",regionId:"17200"});
  assert.equal(unknown.data.livesLost.availability,"unknown");
  assert.equal(unknown.data.livesLost.value,null);
});
test("ambiguous VIC areas and unmatched islands retain explicit evidence; agreeing duplicate rows do not multiply",async()=>{
  const e=await regionEvidence();
  assert.equal(e.sources.VIC.unmatchedByReason.ambiguous_lga,2310);
  assert.equal(e.sources.VIC.audit.duplicateNodeAccidentsCollapsed,71264);
  assert.equal(e.sources.NSW.audit.unmatched,5);
  assert.equal(e.sources.QLD.audit.unmatched,1);
  assert.equal(regional.sources.VIC.rows.reduce((n,r)=>n+r[2],0),72170);
});
test("source and region validation prevents cross-state or invented codes; switching source clears the area",()=>{
  for(const params of [{source:"All",regionId:"17200"},{source:"QLD",regionId:"17200"},{source:"NSW",regionId:"19999"}])
    assert.throws(()=>parseOfficialFilters(new URLSearchParams(params)),/LGA/);
  assert.equal(selectSource({...DEFAULT_FILTERS,source:"NSW",regionId:"17200"},"QLD").regionId,undefined);
});
test("agent area context is fresh and tools agree with the page, including code-calculated regional YoY",async()=>{
  const context={page:"/",filters:{...DEFAULT_FILTERS,source:"NSW" as const,regionId:"17200"}};
  const old={...context,filters:{...context.filters,regionId:"15900"}};
  assert.equal(parseAgentRequest({context,message:"How many?",history:[{role:"assistant",text:"Old area",context:old}]}).history.length,0);
  const core=await executeAnalysisTool("core_metrics",{source:null,dateRange:null},context,service,snapshot) as {results: {data: {crashes: {value:number}}}[]};
  assert.equal(core.results[0].data.crashes.value,2932);
  const q=JSON.parse(JSON.stringify(await executeAnalysisTool("compare_periods",{source:null,dateRange:{from:"2024-01-01",to:"2024-12-31"},baseline:null},context,service,snapshot)));
  const c=await service.getOverview({...context.filters,dateRange:{from:"2024-01-01",to:"2024-12-31"}}),b=await service.getOverview({...context.filters,dateRange:{from:"2023-01-01",to:"2023-12-31"}});
  assert.equal(q.results[0].metrics[0].difference,c.data.crashes.value!-b.data.crashes.value!);
  const area=JSON.parse(JSON.stringify(await executeAnalysisTool("regional_analysis",{source:"QLD",dateRange:null,regionId:"31000"},context,service,snapshot)));
  assert.equal(area.regionName,"Brisbane");assert.equal(area.results[0].data.crashes.value,16662);
  assert.ok(!JSON.stringify(area).includes('"coordinates"'));
});
