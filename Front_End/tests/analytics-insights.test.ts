import test from "node:test";
import assert from "node:assert/strict";
import { fatalPercentage, monthlyInsights, spatialInsights } from "../src/services/analytics-insights";
import type { TimePoint } from "../src/services/contracts";

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
