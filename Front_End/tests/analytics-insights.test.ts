import test from "node:test";
import assert from "node:assert/strict";
import { allSourceAreaRanking, concentrationAtShare, fatalPercentage, monthlyInsights, spatialConcentration, spatialInsights, sourceTrend } from "../src/services/analytics-insights";
import type { MapData, TimePoint } from "../src/services/contracts";

const rows: TimePoint[] = [
  {period:"2023-01",crashes:100,fatalCrashes:4,livesLost:5,casualties:null},
  {period:"2024-01",crashes:300,fatalCrashes:0,livesLost:0,casualties:12},
  {period:"2024-02",crashes:200,fatalCrashes:null,livesLost:null,casualties:0},
];
test("monthly summaries follow the selected metric, retaining zero and excluding unknown", () => {
  const result = monthlyInsights(rows,"fatalCrashes");
  assert.equal(result.average,2);
  assert.equal(result.observed,2);
  assert.equal(result.peak?.period,"2023-01");
  assert.equal(result.calendar[0].average,2);
  assert.equal(result.calendar[1].average,null);
  assert.equal(monthlyInsights(rows,"crashes").peak?.period,"2024-01");
  assert.equal(monthlyInsights(rows,"casualties").calendar[1].average,0);
});
test("an empty or unknown-only selection cannot invent an average or peak", () => {
  assert.equal(monthlyInsights([],"crashes").average,null);
  assert.equal(monthlyInsights([rows[2]],"livesLost").peak,null);
});
test("spatial concentration reconciles with mapped records without mutating API rows", () => {
  const regions = [{id:"b",name:"Beta",count:20,fatalCrashes:0}, {id:"a",name:"Alpha",count:80,fatalCrashes:4}, {id:"z",name:"Zero",count:0,fatalCrashes:null}];
  const copy = structuredClone(regions);
  const result = spatialInsights(regions);
  assert.deepEqual(regions,copy);
  assert.equal(result.total,100);
  assert.equal(result.represented,2);
  assert.equal(result.topFiveShare,100);
  assert.equal(result.ranked[0].id,"a");
  assert.equal(result.ranked[0].share,80);
  assert.equal(result.ranked[0].fatalShare,5);
  assert.equal(result.ranked[1].fatalShare,0);
  assert.equal(result.ranked[2].fatalShare,null);
  assert.equal(result.ranked.at(-1)?.cumulativeShare,100);
});
test("top-five share excludes the sixth area rather than displaying the total", () => {
  const result = spatialInsights(Array.from({length:6},(_,i) => ({id:String(i),name:String(i),count:10})));
  assert.equal(result.topFiveShare,50/60*100);
});
test("zero, unavailable and invalid denominators cannot become a fatal share", () => {
  for (const [all,fatal] of [[0,0],[null,1],[4,null],[4,5],[4,-1]] as const) assert.equal(fatalPercentage(all,fatal),null);
  assert.equal(fatalPercentage(100,0),0);
  assert.equal(spatialInsights([]).topFiveShare,null);
});

test("All ranks actual LGAs together while retaining source and area identity", () => {
  const map = (regions: MapData["regions"], observed = true): MapData => ({
    level: "state", boundaryUrl: "/boundaries", bounds: [[0, 0], [1, 1]],
    regions, regionMode: "lga", illustrationOnly: !observed,
  });
  const inputs = [
    {source: "NSW" as const, data: map([{id: "shared", name: "Alpha", count: 10}])},
    {source: "QLD" as const, data: map([{id: "shared", name: "Beta", count: 50}, {id: "zero", name: "Zero", count: 0}])},
    {source: "VIC" as const, data: map([{id: "fake", name: "Illustration", count: 999}], false)},
    {source: "All" as const, data: map([{id: "state", name: "State total", count: 9999}])},
  ];
  const before = structuredClone(inputs);
  assert.deepEqual(allSourceAreaRanking(inputs).map(({source, id, count, rank}) => ({source, id, count, rank})), [
    {source: "QLD", id: "shared", count: 50, rank: 1},
    {source: "NSW", id: "shared", count: 10, rank: 2},
    {source: "QLD", id: "zero", count: 0, rank: 3},
  ]);
  assert.deepEqual(inputs, before);
  assert.deepEqual(allSourceAreaRanking([]), []);
});

test("concentration preserves exact cumulative counts, including zero-count areas in the denominator", () => {
  const regions = [{id:"b",name:"Beta",count:20}, {id:"a",name:"Alpha",count:80}, {id:"z",name:"Zero",count:0}];
  const before = structuredClone(regions);
  const curve = spatialConcentration(regions);
  assert.equal(curve.areaCount, 3);
  assert.equal(curve.total, 100);
  assert.deepEqual(curve.points.map(({areas,crashes,crashShare})=>({areas,crashes,crashShare})), [
    {areas:0,crashes:0,crashShare:0},
    {areas:1,crashes:80,crashShare:80},
    {areas:2,crashes:100,crashShare:100},
    {areas:3,crashes:100,crashShare:100},
  ]);
  [0,100/3,200/3,100].forEach((expected,i)=>assert.ok(Math.abs(curve.points[i].areaShare-expected)<1e-12));
  assert.deepEqual(regions, before);
});

test("comparison reads each source at its nearest whole-area rank, not interpolated or pooled counts", () => {
  const a = spatialConcentration([80,20].map((count,i)=>({id:String(i),name:String(i),count})));
  const b = spatialConcentration([40,30,20,10].map((count,i)=>({id:String(i),name:String(i),count})));
  assert.equal(concentrationAtShare(a,50)?.crashes,80);
  assert.equal(concentrationAtShare(b,50)?.crashes,70);
  assert.deepEqual(concentrationAtShare(b,30), {areas:1,areaShare:25,crashes:40,crashShare:40});
  assert.equal(concentrationAtShare(a,-10)?.areas,0);
  assert.equal(concentrationAtShare(a,150)?.crashes,100);
  assert.equal(concentrationAtShare(a,NaN),null);
});

test("empty and zero-total selections cannot invent a concentration curve", () => {
  for (const regions of [[],[{id:"z",name:"Zero",count:0}]]) {
    const curve = spatialConcentration(regions);
    assert.deepEqual(curve.points,[]);
    assert.equal(concentrationAtShare(curve,50),null);
  }
});

test("single-area and equal-count curves retain monotone exact endpoints", () => {
  const single=spatialConcentration([{id:"only",name:"Only",count:7}]);
  assert.deepEqual(single.points.at(-1),{areas:1,areaShare:100,crashes:7,crashShare:100});
  const equal=spatialConcentration(Array.from({length:4},(_,i)=>({id:String(i),name:String(i),count:10})));
  assert.ok(equal.points.every(point=>point.areaShare===point.crashShare));
  assert.equal(equal.points.at(-1)?.crashes,40);
});


test("source trends align dates across sources without summing, interpolating or zero-filling gaps", () => {
  const input: TimePoint[] = [
    {...rows[0], source:"NSW", period:"2024-02"},
    {...rows[2], source:"VIC", period:"2024-01"},
    {...rows[1], source:"NSW", period:"2024-01"},
  ];
  const before = structuredClone(input);
  const sources = ["NSW", "VIC", "QLD"] as const;
  assert.deepEqual(sourceTrend(input, "crashes", sources).periods, ["2024-01", "2024-02"]);
  for (const [metric, expected] of [
    ["crashes", [[300,100],[200,null],[null,null]]],
    ["fatalCrashes", [[0,4],[null,null],[null,null]]],
    ["livesLost", [[0,5],[null,null],[null,null]]],
    ["casualties", [[12,null],[0,null],[null,null]]],
  ] as const) assert.deepEqual(sourceTrend(input, metric, sources).series.map(group => group.values), expected);
  assert.deepEqual(input, before);
});

test("source trends preserve partial-year metadata and the single-source path", () => {
  const point = {...rows[0], period:"2024", selectedMonths:[2,3], observedMonths:2, fullYear:false};
  const result = sourceTrend([point], "crashes");
  assert.deepEqual(result.periods, ["2024"]);
  assert.deepEqual(result.series.map(group => group.values), [[100]]);
  assert.deepEqual(result.series[0].points[0], point);
  assert.deepEqual(sourceTrend([], "crashes"), {periods:[],series:[]});
});
