import test from "node:test";
import assert from "node:assert/strict";
import { DEFAULT_FILTERS } from "../src/services/config";
import { parseAnalysisState, analysisHref, DEFAULT_VIEW } from "../src/services/analysis-state";
import { monthRangeLabel, timePointLabel, yearScope } from "../src/services/periods";
import { getAnalytics } from "../src/services/analytics";
import { loadOfficialSnapshot, createOfficialProvider } from "../src/server/official-data";

const filters = { ...DEFAULT_FILTERS, source: "NSW" as const, dateRange: { from: "2024-01-01", to: "2024-12-31" } };
test("URL roundtrips whole-month scope, region, metric, intervals and pinned identity", () => {
  const state = { ...filters, regionId: "17200" };
  const view = { ...DEFAULT_VIEW, metric: "livesLost" as const, granularity: "yearly" as const };
  const parsed = parseAnalysisState(analysisHref("/analytics", state, view).split("?")[1]);
  assert.equal(parsed.error, undefined);
  assert.deepEqual(parsed.filters, state); assert.deepEqual(parsed.view, view);
});
test("invalid links do not silently replace unsupported requests", () => {
  for (const query of ["source=WA", "metrc=livesLost", "source=All&regionId=17200", "source=VIC&regionId=17200", "batchId=other", "datasetVersion=other", "from=2024-01-99", "from=2024-02-30", "to=2024-02-28", "metric=injuries", "interval=weekly", "source=NSW&source=VIC", "from=2024-03-01&to=2024-02-29"]) {
    assert.ok(parseAnalysisState(query).error, query);
  }
});
test("single-month and uneven cross-year subtotals retain requested and observed month scope", () => {
  const march = { ...filters, dateRange: { from: "2024-03-01", to: "2024-03-31" } };
  assert.equal(monthRangeLabel(march), "Mar 2024");
  assert.equal(timePointLabel({ period: "2024", ...yearScope(march, 2024, 1), crashes: 1601, fatalCrashes: null, livesLost: null, casualties: null }), "2024 · Mar subtotal (1/1 months)");
  const cross = { ...filters, dateRange: { from: "2023-07-01", to: "2024-03-31" } };
  assert.deepEqual(yearScope(cross, 2023, 6).selectedMonths, [7,8,9,10,11,12]);
  assert.deepEqual(yearScope(cross, 2024, 2), { selectedMonths: [1,2,3], observedMonths: 2, fullYear: false });
});
test("official 2024 four metric comparisons retain different directions and units", async () => {
  const provider = createOfficialProvider(await loadOfficialSnapshot());
  const { data } = await getAnalytics(filters, provider);
  const year = data.yearly[0];
  const expected = { crashes: [18939,18711], fatalCrashes: [298,303], livesLost: [327,340], casualties: [16318,16379] };
  for (const key of Object.keys(expected) as (keyof typeof expected)[]) {
    const [current, previous] = expected[key];
    assert.deepEqual(year.comparisons[key], { current, previous, yoyPct: (current-previous)/previous*100, reason: null });
  }
  assert.equal(year.comparisons.crashes.yoyPct!.toFixed(1), "1.2");
  assert.equal(year.comparisons.livesLost.yoyPct!.toFixed(1), "-3.8");
});
test("metric-specific zero/unknown baselines withhold only that comparison", async () => {
  const provider = createOfficialProvider(await loadOfficialSnapshot());
  const custom = { ...provider, async getTimeSeries(f: typeof filters, grain: "monthly" | "yearly") {
    const result = await provider.getTimeSeries(f, grain);
    return { ...result, data: result.data.map(row => f.dateRange.from.startsWith("2023") ? { ...row, livesLost: 0, casualties: null } : row) };
  } };
  const { data } = await getAnalytics(filters, custom);
  assert.equal(data.yearly[0].comparisons.livesLost.yoyPct, null);
  assert.match(data.yearly[0].comparisons.livesLost.reason!, /zero/);
  assert.equal(data.yearly[0].comparisons.casualties.yoyPct, null);
  assert.match(data.yearly[0].comparisons.casualties.reason!, /unknown/);
  assert.equal(data.yearly[0].comparisons.crashes.yoyPct!.toFixed(1), "1.2");
});
test("coverage detects a missing interior month rather than only valid boundaries", async () => {
  const snapshot = structuredClone(await loadOfficialSnapshot());
  const report = snapshot.reports["official_nsw:monthly"];
  report.rows = report.rows!.filter(row => !("period_month" in row && row.period_year === 2024 && row.period_month === 6));
  const provider = createOfficialProvider(snapshot);
  const overview = await provider.getOverview(filters);
  assert.equal(overview.meta.coverage.complete, false);
  const analysis = await getAnalytics(filters, provider);
  assert.equal(analysis.data.monthly.find(row => row.period === "2024-06")!.availability, "unknown");
  assert.equal(analysis.data.yearly[0].comparisons.livesLost.yoyPct, null);
});
