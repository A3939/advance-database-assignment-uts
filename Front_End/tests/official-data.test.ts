import test from "node:test";
import assert from "node:assert/strict";
import {
  createOfficialProvider,
  loadOfficialSnapshot,
  parseOfficialFilters,
} from "../src/server/official-data";
import { DEFAULT_FILTERS, selectSource } from "../src/services/config";
import { getAnalytics } from "../src/services/analytics";
const totals = {
  NSW: [92082, 1388, 1507, 78154],
  VIC: [72170, 1182, 1265, 91798],
  QLD: [66624, 1304, 1424, 88609],
};
const keys = ["crashes", "fatalCrashes", "livesLost", "casualties"] as const;
for (const source of ["NSW", "VIC", "QLD"] as ("NSW" | "VIC" | "QLD")[])
  test(`${source}: admitted official snapshot, monthly, yearly and severity reconcile to independently recorded totals`, async () => {
    const snapshot = await loadOfficialSnapshot();
    const api = createOfficialProvider(snapshot),
      filters = selectSource(DEFAULT_FILTERS, source);
    const [overview, monthly, annual, severity] = await Promise.all([
      api.getOverview(filters),
      api.getTimeSeries(filters, "monthly"),
      api.getTimeSeries(filters, "yearly"),
      api.getSeverityDistribution(filters),
    ]);
    assert.equal(overview.meta.demo, false);
    assert.equal(overview.meta.batchId, "bcc5da57-25f2-41ec-9925-bef421b02671");
    assert.equal(monthly.data.length, 60);
    assert.equal(annual.data.length, 5);
    keys.forEach((key, i) => {
      assert.equal(overview.data[key].value, totals[source][i]);
      assert.equal(
        monthly.data.reduce((s, r) => s + r[key]!, 0),
        totals[source][i],
      );
      assert.equal(
        annual.data.reduce((s, r) => s + r[key]!, 0),
        totals[source][i],
      );
    });
    assert.equal(
      severity.data.reduce((s, r) => s + r.count, 0),
      totals[source][0],
    );
    const analysis = await getAnalytics(filters, api);
    assert.equal(analysis.data.summary.total, totals[source][0]);
    assert.equal(analysis.data.severityAvailability, "available");
    assert.equal(analysis.meta.demo, false);
  });
test("All remains three separate metrics and source series, never a national total", async () => {
  const api = createOfficialProvider(await loadOfficialSnapshot());
  const overview = await api.getOverview(DEFAULT_FILTERS);
  for (const key of keys) {
    assert.equal(overview.data[key].value, null);
    assert.equal(overview.data[key].availability, "unsupported");
    assert.equal(overview.data[key].bySource?.length, 3);
  }
  assert.equal(
    (await api.getTimeSeries(DEFAULT_FILTERS, "monthly")).data.length,
    180,
  );
});
test("continuous cross-year month windows are selected exactly; severity is withheld, never apportioned", async () => {
  const api = createOfficialProvider(await loadOfficialSnapshot());
  const filters = {
    ...selectSource(DEFAULT_FILTERS, "NSW"),
    dateRange: { from: "2022-03-01", to: "2023-08-31" },
  };
  const months = await api.getTimeSeries(filters, "monthly");
  assert.equal(months.data.length, 18);
  assert.equal(months.data[0].period, "2022-03");
  assert.equal(months.data.at(-1)?.period, "2023-08");
  const severity = await api.getSeverityDistribution(filters);
  assert.equal(severity.meta.availability, "unsupported");
  assert.deepEqual(severity.data, []);
  const analytics = await getAnalytics(filters, api);
  assert.equal(analytics.data.severityAvailability, "unsupported");
  assert.equal(analytics.data.yearly[0].comparisonMonths.length, 10);
  assert.equal(analytics.data.yearly[1].comparisonMonths.length, 8);
});
test("zero, unknown, empty and unsupported are distinct", async () => {
  const snapshot = structuredClone(await loadOfficialSnapshot());
  const raw = snapshot.reports["official_nsw:monthly"]
    .rows![0] as unknown as Record<string, unknown>;
  raw.fatality_count = null;
  raw.fatality_known_count = 0;
  raw.casualty_count = 0;
  const api = createOfficialProvider(snapshot);
  const f = {
    ...selectSource(DEFAULT_FILTERS, "NSW"),
    dateRange: { from: "2020-01-01", to: "2020-01-31" },
  };
  const observed = await api.getOverview(f);
  assert.equal(observed.data.livesLost.value, null);
  assert.equal(observed.data.livesLost.availability, "unknown");
  assert.equal(observed.data.casualties.value, 0);
  assert.equal(observed.data.casualties.availability, "available");
  const analysis = await getAnalytics(f, api);
  assert.equal(analysis.data.yearly[0].livesLost, null);
  assert.equal(analysis.data.yearly[0].casualties, 0);
  const empty = await api.getOverview({
    ...f,
    dateRange: { from: "2025-01-01", to: "2025-12-31" },
  });
  assert.equal(empty.meta.availability, "no_results");
  assert.equal(empty.data.crashes.value, null);
  const unsupported = await api.getOverview({ ...f, batchId: "another-batch" });
  assert.equal(unsupported.meta.availability, "unsupported");
  assert.equal(unsupported.data.crashes.value, null);
});
test("real map data contains only source totals and boundaries; records cannot fall back to demo samples", async () => {
  const api = createOfficialProvider(await loadOfficialSnapshot());
  const country = await api.getMapData(DEFAULT_FILTERS);
  assert.equal(
    country.data.states?.find((r) => r.source === "NSW")?.count,
    92082,
  );
  assert.equal(
    country.data.states?.find((r) => r.label === "WA")?.count,
    undefined,
  );
  for (const source of ["NSW", "VIC", "QLD"] as ("NSW" | "VIC" | "QLD")[]) {
    const f = selectSource(DEFAULT_FILTERS, source);
    const map = await api.getMapData(f);
    assert.equal(map.meta.availability, "unsupported");
    assert.equal(map.data.illustrationOnly, false);
    assert.deepEqual(map.data.regions, []);
    const records = await api.getCrashRecords(
      f,
      { page: 1, pageSize: 20 },
      { field: "date", direction: "desc" },
    );
    assert.equal(records.meta.availability, "unsupported");
    assert.deepEqual(records.data.rows, []);
    assert.equal(records.data.sampleOnly, false);
  }
});
test("source metadata and evidence expose restrictions and hashes without local paths", async () => {
  const snapshot = await loadOfficialSnapshot(),
    api = createOfficialProvider(snapshot);
  const data = await api.getDatasetMetadata();
  assert.equal(data.length, 3);
  assert.ok(
    data.every(
      (d) => d.demo === false && d.batchId === DEFAULT_FILTERS.batchId,
    ),
  );
  assert.equal(snapshot.provenance.publicationStatus, "succeeded");
  assert.equal(
    snapshot.provenance.qa.find((q) => q.check === "QA07_LOCATION")?.status,
    "limited",
  );
  assert.equal(snapshot.provenance.finalPlatformAccepted, false);
  assert.doesNotMatch(
    JSON.stringify(snapshot.provenance),
    /\/Users\/|postgres:\/\/|password/i,
  );
});
test("HTTP filter parsing rejects bad dates, source, partial days and unbounded ranges", () => {
  for (const query of [
    "source=SA",
    "from=2020-02-30",
    "from=2020-01-02",
    "to=2024-12-30",
    "from=2025-01-01&to=2020-12-31",
    "from=1900-01-01&to=2024-12-31",
  ])
    assert.throws(() => parseOfficialFilters(new URLSearchParams(query)));
  const f = parseOfficialFilters(
    new URLSearchParams("source=VIC&from=2024-02-01&to=2024-02-29"),
  );
  assert.equal(f.source, "VIC");
  assert.equal(f.batchId, DEFAULT_FILTERS.batchId);
});

test("both aggregate bytes and provenance coverage must match their admitted hashes", async () => {
  const { readFile } = await import("node:fs/promises");
  const { decodeOfficialSnapshot } =
    await import("../src/server/official-data");
  const bytes = await readFile("data/official/reader-results.json");
  const text = await readFile("data/official/provenance.json", "utf8");
  assert.equal(
    decodeOfficialSnapshot(bytes, text).provenance.batchId,
    DEFAULT_FILTERS.batchId,
  );
  assert.throws(
    () => decodeOfficialSnapshot(Buffer.from("{}"), text),
    /integrity/,
  );
  assert.throws(
    () =>
      decodeOfficialSnapshot(bytes, text.replace("2020-01-01", "2024-01-01")),
    /integrity/,
  );
});
