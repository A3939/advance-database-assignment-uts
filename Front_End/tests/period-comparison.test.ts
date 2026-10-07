import assert from "node:assert/strict";
import test from "node:test";
import type { AnalyticsMonth } from "../src/services/analytics";
import { comparisonAverage, comparisonChange, comparisonPeriods } from "../src/services/period-comparison";

const row = (year: number, month: number, crashes: number | null, availability: AnalyticsMonth["availability"] = "available"): AnalyticsMonth => ({
  year, month, period: `${year}-${String(month).padStart(2, "0")}`,
  availability, crashes, fatalCrashes: null, livesLost: null, casualties: null,
});

test("periods default to separate two-year windows when five years are available", () => {
  const periods = comparisonPeriods([2020, 2021, 2022, 2023, 2024].map(year => row(year, 1, 1)));
  assert.equal(periods[0].label, "2020–2021");
  assert.equal(periods.at(-1)?.label, "2023–2024");
  assert.deepEqual(comparisonPeriods([row(2023, 1, 1), row(2024, 1, 1)]).map(period => period.label), ["2023", "2024"]);
});

test("comparison uses real monthly averages and never treats missing data as zero", () => {
  const first = { start: 2020, end: 2020, label: "2020" };
  const second = { start: 2024, end: 2024, label: "2024" };
  const a = comparisonAverage([row(2020, 1, 10), row(2020, 2, 30)], "crashes", first);
  const b = comparisonAverage([row(2024, 1, 30), row(2024, 2, 30)], "crashes", second);
  assert.equal(a.average, 20);
  assert.equal(comparisonChange(a, b), 50);
  const incomplete = comparisonAverage([row(2024, 1, 30), row(2024, 2, null, "unknown")], "crashes", second);
  assert.equal(incomplete.average, 30);
  assert.equal(incomplete.complete, false);
  assert.equal(comparisonChange(a, incomplete), null);
  assert.equal(comparisonChange(comparisonAverage([row(2020, 1, 0)], "crashes", first), b), null);
});
