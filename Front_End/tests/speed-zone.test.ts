import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { DEFAULT_FILTERS } from "../src/services/config";
import { createOfficialProvider, loadOfficialSnapshot } from "../src/server/official-data";
import { getSpeedZones, loadSpeedZoneSnapshot, decodeSpeedZoneSnapshot, speedZoneEvidence, type SpeedZoneSnapshot } from "../src/server/speed-zone";
import type { Filters, Overview, Response, Source } from "../src/services/contracts";
import { GET } from "../src/app/api/data/[report]/route";

const filters = {...DEFAULT_FILTERS, source:"NSW" as const};
function fixture() {
  const data = {field:"posted_limit", rows:[["2020-01","60",10,2,10],["2020-02","60",20,1,20],["2020-01","70",4,0,4]], excluded:[["2020-01","unknown",6,1,6]]};
  const snapshot = {extensionVersion:"test", batchId:filters.batchId, datasetVersion:filters.datasetVersion,
    coverage:{from:"2020-01-01",to:"2024-12-31"}, bands:[{id:"60",label:"60"},{id:"70",label:"70"},{id:"80-90",label:"80–90"}],
    sources:{NSW:structuredClone(data),VIC:structuredClone(data),QLD:structuredClone(data)}} as SpeedZoneSnapshot;
  const service = {getOverview:async(f:Filters):Promise<Response<Overview>> => {
    const source = f.source === "All" ? "NSW" : f.source;
    const rows = [...snapshot.sources[source].rows,...snapshot.sources[source].excluded].filter(r=>r[0]>=f.dateRange.from.slice(0,7)&&r[0]<=f.dateRange.to.slice(0,7));
    const count=rows.reduce((n,r)=>n+r[2],0), fatal=rows.some(r=>r[4]!==r[2]) ? null : rows.reduce((n,r)=>n+r[3],0);
    const metric=(value:number|null)=>({value,availability:"available" as const,label:"count",unit:"events",definition:"fixture"});
    return {data:{crashes:metric(count),fatalCrashes:metric(fatal),livesLost:metric(null),casualties:metric(null),fatalShare:null},
      meta:{demo:false,source:f.source,datasetVersion:f.datasetVersion,batchId:f.batchId,availability:"available",coverage:{...snapshot.coverage,granularity:"month",complete:true},definition:"fixture",unit:"events",evidence:[]}};
  }};
  return {snapshot,service};
}

test("shares use the source/band denominator and retain excluded observations",async()=>{
  const {snapshot,service}=fixture();
  const r=await getSpeedZones(filters,service,snapshot);
  assert.equal(r.data.groups[0].rows[0].share,10); // (2+1)/(10+20); not total-source denominator.
  assert.equal(r.data.groups[0].rows[1].share,0);
  assert.equal(r.data.groups[0].rows[2].share,null); // no observations is not 0%.
  assert.deepEqual(r.data.groups[0].excluded,[{nativeValue:"unknown",crashes:6,fatalCrashes:1}]);
  const january=await getSpeedZones({...filters,dateRange:{from:"2020-01-01",to:"2020-01-31"}},service,snapshot);
  assert.equal(january.data.groups[0].rows[0].share,20);
});

test("unknown fatal status withholds its band; other bands remain available",async()=>{
  const {snapshot,service}=fixture();snapshot.sources.NSW.rows[0][4]=9;
  const r=await getSpeedZones(filters,service,snapshot);
  assert.equal(r.data.groups[0].rows[0].share,null);
  assert.equal(r.data.groups[0].rows[1].share,0);
  assert.match(r.data.groups[0].reason!,/unknown/);
});

test("wrong identity, partial coverage and LGA scope never use unfiltered totals",async()=>{
  const {snapshot,service}=fixture();
  for(const f of [{...filters,batchId:"other"},{...filters,datasetVersion:"other"},{...filters,regionId:"10100"},{...filters,dateRange:{from:"2019-01-01",to:"2024-12-31"}},{...filters,dateRange:{from:"2020-01-02",to:"2024-12-31"}}]){
    const r=await getSpeedZones(f,service,snapshot);assert.equal(r.meta.availability,"unsupported");assert.equal(r.data.groups[0].rows.length,0);
  }
});

test("empty selection has no invented zero-percent bars",async()=>{
  const {snapshot,service}=fixture();
  const r=await getSpeedZones({...filters,dateRange:{from:"2021-01-01",to:"2021-12-31"}},service,snapshot);
  assert.equal(r.meta.availability,"no_results");assert.ok(r.data.groups[0].rows.every(r=>r.share===null));
});

test("duplicate, invalid and unregistered band counts fail closed",async()=>{
  for(const mutate of [
    (s:SpeedZoneSnapshot)=>s.sources.NSW.rows.push([...s.sources.NSW.rows[0]]),
    (s:SpeedZoneSnapshot)=>{s.sources.NSW.rows[0][3]=11;},
    (s:SpeedZoneSnapshot)=>{s.sources.NSW.rows[0][1]="unregistered";},
    (s:SpeedZoneSnapshot)=>{s.sources.NSW.rows[0][2]=-1;},
  ]) {const {snapshot,service}=fixture();mutate(snapshot);await assert.rejects(getSpeedZones(filters,service,snapshot));}
});

test("mismatched official counts and source identities fail closed",async()=>{
  const {snapshot,service}=fixture();
  const wrongCount={getOverview:async(f:Filters)=>{const r=await service.getOverview(f);r.data.crashes.value=999;return r;}};
  await assert.rejects(getSpeedZones(filters,wrongCount,snapshot),/reconcile/);
  const wrongSource={getOverview:async(f:Filters)=>{const r=await service.getOverview(f);r.meta.source="VIC";return r;}};
  await assert.rejects(getSpeedZones(filters,wrongSource,snapshot),/identity/);
});

test("actual snapshot reconciles selected months and all three source totals",async()=>{
  const snapshot=await loadSpeedZoneSnapshot(), official=createOfficialProvider(await loadOfficialSnapshot());
  const full=await getSpeedZones(DEFAULT_FILTERS,official,snapshot);
  assert.equal(full.meta.demo,false);assert.equal(full.meta.availability,"available");
  assert.deepEqual(full.data.bands.map(b=>b.id),["0-50","60","70","80-90","100-110"]);
  const totals={NSW:[92082,1388,26],VIC:[72170,1182,6105],QLD:[66624,1304,0]};
  for(const g of full.data.groups){
    assert.equal(g.rows.reduce((n,r)=>n+r.crashes,0)+g.excluded.reduce((n,r)=>n+r.crashes,0),totals[g.source][0]);
    assert.equal(g.rows.reduce((n,r)=>n+r.fatalCrashes,0)+g.excluded.reduce((n,r)=>n+r.fatalCrashes,0),totals[g.source][1]);
    assert.equal(g.excluded.reduce((n,r)=>n+r.crashes,0),totals[g.source][2]);
    assert.ok(g.rows.every(r=>r.share===r.fatalCrashes/r.crashes*100));
  }
  for(const source of ["NSW","VIC","QLD"] as Source[]){
    const r=await getSpeedZones({...filters,source,dateRange:{from:"2021-02-01",to:"2021-04-30"}},official,snapshot);
    assert.equal(r.data.groups.length,1);assert.equal(r.meta.availability,"available");
  }
});

test("tampered aggregate bytes are rejected and evidence is pinned",async()=>{
  const bytes=await readFile("data/speed-zones/aggregates.json");
  assert.throws(()=>decodeSpeedZoneSnapshot(Buffer.concat([bytes,Buffer.from(" ")])),/integrity/);
  assert.equal((await speedZoneEvidence()).extensionVersion,"speed-zone-v1");
});

test("actual API honours whole-month validation and pinned identity",async()=>{
  const call=(query:string)=>GET(new Request(`http://localhost/api/data/speed-zones?${query}`),{params:Promise.resolve({report:"speed-zones"})});
  const response=await call("source=All");assert.equal(response.status,200);
  const body=await response.json();assert.equal(body.data.groups.length,3);assert.equal(body.meta.availability,"available");
  assert.equal((await call("from=2020-01-02")).status,400);
  const unknown=await (await call("batchId=unverified")).json();assert.equal(unknown.meta.availability,"unsupported");assert.ok(unknown.data.groups.every((g:{rows:unknown[]})=>!g.rows.length));
});
