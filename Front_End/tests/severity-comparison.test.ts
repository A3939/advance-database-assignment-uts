import test from "node:test";
import assert from "node:assert/strict";
import { severityComparison, severityComposition, formatSeverityShare, type SeverityValue } from "../src/services/severity-comparison";
const row = (source: SeverityValue["source"], label: string, count: number, share?: number | null): SeverityValue => ({source, label, count, definition:`Native definition: ${label}`, ...(share === undefined ? {} : {share})});
test("All display slots retain native rows and three distinct source series", () => {
  const input = [row("NSW","Fatal",10,.1), row("VIC","Fatal",20,.2), row("QLD","Fatal",5,.05), row("NSW","Serious Injury",30,.3), row("VIC","Serious injury",40,.4), row("QLD","Hospitalisation",50,.5), row("NSW","Moderate Injury",20,.2), row("QLD","Medical treatment",30,.3)];
  const copy = structuredClone(input);
  const result = severityComparison(input,["NSW","VIC","QLD"]);
  assert.deepEqual(result.series.map(series => series.counts), [[10,30,20],[20,40,null],[5,50,30]]);
  assert.deepEqual(result.series.map(series => series.shares), [[10,30,20],[20,40,null],[5,50,30]]);
  assert.equal(result.groups[1].rows[2]?.label,"Hospitalisation");
  assert.equal(result.groups[1].rows[2]?.definition,"Native definition: Hospitalisation");
  assert.deepEqual(input,copy);
});
test("Share uses supplied source denominators, preserving unknown, tiny values and zero", () => {
  const result=severityComparison([row("NSW","Fatal",10,.01),row("VIC","Fatal",0,0),row("QLD","Fatal",1,null),row("VIC","Non-injury",3,3/72170)],["NSW","VIC","QLD"]);
  assert.equal(result.series[0].shares[0],1);
  assert.equal(result.series[1].shares[0],0);
  assert.equal(result.series[2].shares[0],null);
  assert.ok(result.series[1].shares[1]! > 0 && result.series[1].shares[1]! < .1);
  assert.equal(result.series[1].counts[0],0);
});
test("Absent source/category stays null rather than becoming a recorded zero", () => {
  const result=severityComparison([row("NSW","Fatal",0)], ["NSW","VIC","QLD"]);
  assert.deepEqual(result.series.map(series=>series.counts),[[0],[null],[null]]);
  assert.deepEqual(result.series.map(series=>series.shares),[[null],[null],[null]]);
});
test("Single-source original labels and order are retained", () => {
  const result=severityComparison([row("NSW","Fatal",1),row("NSW","Minor/Other Injury",3)]);
  assert.equal(result.multiple,false);
  assert.deepEqual(result.groups.map(group=>group.label),["Fatal","Minor/Other Injury"]);
  assert.deepEqual(result.series[0].shares,[25,75]);
});
test("Extra categories and ambiguous display pairings cannot be merged or lost", () => {
  const input=[row("NSW","Minor injury",2),row("NSW","Other injury",3),row("VIC","Other injury",4),row("QLD","Unclassified",5)];
  const result=severityComparison(input,["NSW","VIC","QLD"]);
  assert.equal(result.groups.flatMap(group=>group.rows.filter(Boolean)).length,4);
  assert.equal(result.series[0].counts.reduce<number>((sum,value)=>sum+(value??0),0),5);
  assert.ok(result.groups.some(group=>group.label==="Unclassified"));
});
test("Invalid metrics cannot become plotted values", () => {
  const result=severityComparison([row("NSW","Fatal",-1,.2),row("VIC","Fatal",3,NaN)],["NSW","VIC"]);
  assert.deepEqual(result.series.map(series=>series.counts),[[null],[3]]);
  assert.deepEqual(result.series.map(series=>series.shares),[[null],[null]]);
});

test("Composition orders native segments without losing counts, labels or definitions", () => {
  const input=[row("NSW","Minor/Other Injury",15483,15483/92082),row("NSW","Fatal",1388,1388/92082),row("NSW","Non-casualty (towaway)",29507,29507/92082),row("NSW","Serious Injury",19589,19589/92082),row("NSW","Moderate Injury",26115,26115/92082)];
  const copy=structuredClone(input);
  const composition=severityComposition(input,["NSW","VIC","QLD"]);
  assert.deepEqual(composition[0].segments.map(row=>row.label),["Fatal","Serious Injury","Moderate Injury","Minor/Other Injury","Non-casualty (towaway)"]);
  assert.equal(composition[0].segments.reduce((sum,row)=>sum+row.count,0),92082);
  assert.ok(Math.abs(composition[0].knownShare-100)<1e-8);
  assert.ok(composition[0].unclassifiedShare!<1e-8);
  assert.equal(composition[1].available,false);
  assert.equal(composition[2].available,false);
  assert.deepEqual(input,copy);
});
test("Composition retains per-source denominators and leaves an unclassified remainder", () => {
  const result=severityComposition([row("NSW","Fatal",10,.1),row("NSW","Serious Injury",40,.4),row("VIC","Fatal",10,.2)],["NSW","VIC"]);
  assert.equal(result[0].segments[0].share,10);
  assert.equal(result[1].segments[0].share,20);
  assert.equal(result[0].unclassifiedShare,50);
  assert.equal(result[1].unclassifiedShare,80);
});
test("Unknown and over-100-percent compositions are not presented as complete bars", () => {
  const unknown=severityComposition([row("NSW","Fatal",10,null)])[0];
  assert.equal(unknown.available,false);
  assert.equal(unknown.unclassifiedShare,null);
  const invalid=severityComposition([row("NSW","Fatal",10,.8),row("NSW","Serious Injury",10,.8)])[0];
  assert.equal(invalid.available,false);
  assert.equal(invalid.knownShare,160);
});
test("Tiny nonzero proportions remain nonzero, and do not round to recorded zero", () => {
  assert.equal(formatSeverityShare(3/72170*100),"<0.1%");
  assert.equal(formatSeverityShare(0),"0%");
  assert.equal(formatSeverityShare(null),"Unavailable");
  assert.equal(formatSeverityShare(21.3),"21.3%");
});
