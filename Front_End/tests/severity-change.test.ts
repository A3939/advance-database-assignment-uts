import test, { before } from "node:test";
import assert from "node:assert/strict";
import { getSeverityChange } from "../src/server/severity-change";
import { severityChangePeriods } from "../src/services/severity-change";
import { createOfficialProvider, loadOfficialSnapshot } from "../src/server/official-data";
import { createRegionalProvider, loadRegionSnapshot } from "../src/server/region-data";
import { DEFAULT_FILTERS, selectSource } from "../src/services/config";

let regional: Awaited<ReturnType<typeof loadRegionSnapshot>>;
let service: ReturnType<typeof createRegionalProvider>;
before(async () => {
  regional = await loadRegionSnapshot();
  service = createRegionalProvider(createOfficialProvider(await loadOfficialSnapshot()), regional);
});

test("All keeps native categories, counts and percentage-point changes separate by source", async () => {
  const response = await getSeverityChange({ ...DEFAULT_FILTERS, source: "All" }, service, regional);
  assert.equal(response.meta.availability, "available");
  assert.deepEqual(response.data.periods?.map(period => period.label), ["2020", "2024"]);
  assert.deepEqual(response.data.groups.map(group => group.source), ["NSW", "VIC", "QLD"]);
  for (const group of response.data.groups) {
    assert.deepEqual(group.rows.map(row => row.label), regional.sources[group.source].severityLabels);
    for (const [i, year] of ["2020", "2024"].entries()) {
      const overview = await service.getOverview({ ...DEFAULT_FILTERS, source: group.source, dateRange: { from: `${year}-01-01`, to: `${year}-12-31` } });
      assert.equal(group.totals?.[i], overview.data.crashes.value);
      assert.equal(group.rows.reduce((sum, row) => sum + (i ? row.endCount : row.startCount), 0), overview.data.crashes.value);
    }
    for (const row of group.rows) {
      assert.equal(row.startShare, row.startCount / group.totals![0] * 100);
      assert.equal(row.endShare, row.endCount / group.totals![1] * 100);
      assert.equal(row.change, row.endShare! - row.startShare!);
    }
  }
  assert.equal(response.data.groups.find(group => group.source === "QLD")?.rows.length, 4);
  assert.equal(response.data.groups.find(group => group.source === "NSW")?.rows.length, 5);
});

test("full-year source comparison includes unmatched-area counts; dropping them fails reconciliation", async () => {
  const copy = structuredClone(regional);
  copy.sources.VIC.rows = copy.sources.VIC.rows.filter(row => row[1] !== "__unmatched__");
  await assert.rejects(getSeverityChange(selectSource(DEFAULT_FILTERS, "VIC"), service, copy), /reconcile/);
});

test("partial endpoints compare exactly the common selected months, including leap February", async () => {
  const range = { from: "2020-02-01", to: "2024-06-30" };
  const periods = severityChangePeriods(range)!;
  assert.deepEqual(periods.map(period => period.dateRange), [{ from: "2020-02-01", to: "2020-06-30" }, { from: "2024-02-01", to: "2024-06-30" }]);
  assert.deepEqual(periods.map(period => period.label), ["Feb–Jun 2020", "Feb–Jun 2024"]);
  assert.equal(severityChangePeriods({ from: "2020-02-01", to: "2024-02-29" })?.[0].dateRange.to, "2020-02-29");
  const response = await getSeverityChange({ ...selectSource(DEFAULT_FILTERS, "QLD"), dateRange: range }, service, regional);
  for (const [i, period] of periods.entries()) {
    const overview = await service.getOverview({ ...selectSource(DEFAULT_FILTERS, "QLD"), dateRange: period.dateRange });
    assert.equal(response.data.groups[0].totals?.[i], overview.data.crashes.value);
  }
});

test("one year, disjoint endpoint months and out-of-coverage years never fabricate a comparison", async () => {
  for (const dateRange of [{ from: "2021-01-01", to: "2021-12-31" }, { from: "2020-10-01", to: "2021-03-31" }, { from: "2019-01-01", to: "2024-12-31" }]) {
    const result = await getSeverityChange({ ...selectSource(DEFAULT_FILTERS, "NSW"), dateRange }, service, regional);
    assert.equal(result.meta.availability, "unsupported");
    assert.ok(result.data.reason);
    assert.deepEqual(result.data.groups[0].rows, []);
  }
});

test("a selected LGA uses its own counts and retains zero-count categories", async () => {
  const f = { ...selectSource(DEFAULT_FILTERS, "NSW"), regionId: "17200" };
  const result = await getSeverityChange(f, service, regional);
  assert.equal(result.data.groups[0].area, "Sydney");
  for (const [i, period] of result.data.periods!.entries()) {
    const native = await service.getSeverityDistribution({ ...f, dateRange: period.dateRange });
    assert.deepEqual(result.data.groups[0].rows.map(row => i ? row.endCount : row.startCount), native.data.map(row => row.count));
  }
});

test("empty LGA periods retain null shares, never invented zero percentage changes", async () => {
  const result = await getSeverityChange({ ...selectSource(DEFAULT_FILTERS, "QLD"), regionId: "37570" }, service, regional);
  assert.equal(result.data.groups[0].availability, "no_results");
  assert.deepEqual(result.data.groups[0].totals, [0, 0]);
  assert.ok(result.data.groups[0].rows.every(row => row.startCount === 0 && row.startShare === null && row.endShare === null && row.change === null));
});

test("wrong batch is unavailable, and mismatched source responses fail closed", async () => {
  const f = selectSource(DEFAULT_FILTERS, "NSW");
  const result = await getSeverityChange({ ...f, batchId: "not-this-snapshot" }, service, regional);
  assert.equal(result.meta.availability, "unsupported");
  assert.deepEqual(result.data.groups[0].rows, []);
  await assert.rejects(getSeverityChange(f, { async getOverview(filters) { const result = await service.getOverview(filters); return { ...result, meta: { ...result.meta, source: "VIC" } }; } }, regional), /identity/);
});

test("invalid monthly category counts fail rather than fabricating a distribution", async () => {
  const copy = structuredClone(regional);
  copy.sources.QLD.rows.find(row => row[0].startsWith("2020"))![6][0] += 1;
  await assert.rejects(getSeverityChange(selectSource(DEFAULT_FILTERS, "QLD"), service, copy), /Invalid monthly/);
});

test("unavailable crash totals remain unknown, not a zero-count comparison", async () => {
  const f = selectSource(DEFAULT_FILTERS, "NSW");
  const response = await getSeverityChange(f, { async getOverview(filters) {
    const result = await service.getOverview(filters);
    return { ...result, data: { ...result.data, crashes: { ...result.data.crashes, value: null, availability: "unknown" } } };
  } }, regional);
  assert.equal(response.meta.availability, "unknown");
  assert.equal(response.data.groups[0].availability, "unknown");
  assert.deepEqual(response.data.groups[0].rows, []);
});

test("the derived report leaves the five-year official severity contract unchanged", async () => {
  const f = selectSource(DEFAULT_FILTERS, "QLD");
  const before = await service.getSeverityDistribution(f);
  await getSeverityChange(f, service, regional);
  assert.deepEqual(await service.getSeverityDistribution(f), before);
  assert.equal((await service.getSeverityDistribution({ ...f, dateRange: { from: "2020-01-01", to: "2020-12-31" } })).meta.availability, "unsupported");
});
