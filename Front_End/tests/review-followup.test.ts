import test from "node:test";
import assert from "node:assert/strict";
import { wholeMonthRange, validateWholeDateRange } from "../src/services/date-range";
import { parseAnalysisState } from "../src/services/analysis-state";
import { mapCountBand, mapCountBins } from "../src/lib/map-scale";

test("date controls and URL restoration share bounded whole-month validation", () => {
  for (const [from, to] of [["2018-01", "2020-02"], ["2024-01", "2027-01"], ["2024-03", "2024-02"], ["2024-13", "2024-12"], ["", "2024-12"]]) {
    assert.ok(wholeMonthRange(from, to).error, `${from} to ${to}`);
  }
  for (const [from, to] of [["2019-01", "2026-12"], ["2024-02", "2024-02"], ["2023-07", "2024-03"]]) {
    const result = wholeMonthRange(from, to);
    assert.equal(result.error, undefined);
    assert.equal(validateWholeDateRange(result.dateRange!), undefined);
    const query = new URLSearchParams(result.dateRange!).toString();
    assert.equal(parseAnalysisState(query).error, undefined);
  }
  assert.equal(wholeMonthRange("2024-02", "2024-02").dateRange!.to, "2024-02-29");
  assert.equal(wholeMonthRange("2023-02", "2023-02").dateRange!.to, "2023-02-28");
  assert.match(parseAnalysisState("from=2018-01-01&to=2020-02-29").error!, /2019/);
});
test("integer legend bins exactly partition positive event counts and match colouring", () => {
  for (const maximum of [0, 1, 2, 3, 6, 7, 8, 10, 13, 14, 49, 100, 1601, 18939, 92082]) {
    const bins = mapCountBins(maximum);
    let end = 0;
    for (const bin of bins) {
      assert.equal(bin.from, end + 1, `max ${maximum}: no overlap or gap`);
      assert.ok(bin.to >= bin.from, "empty bins are omitted");
      assert.equal(mapCountBand(bin.from, maximum), bin.band);
      assert.equal(mapCountBand(bin.to, maximum), bin.band);
      end = bin.to;
    }
    assert.equal(end, maximum);
  }
  assert.deepEqual(mapCountBins(1), [{ band: 7, from: 1, to: 1 }]);
  assert.deepEqual(mapCountBins(2), [{ band: 4, from: 1, to: 1 }, { band: 7, from: 2, to: 2 }]);
  assert.equal(mapCountBand(0, 0), 0);
  assert.equal(mapCountBand(undefined, 1), null);
});
