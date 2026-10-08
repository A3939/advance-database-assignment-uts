import test from "node:test";
import assert from "node:assert/strict";
import {
  analyticsFilters,
  getAnalytics as readAnalytics,
} from "../src/services/analytics";
import { mockProvider } from "../src/services/mock-provider";
import type {
  ArsiaService,
  Filters,
  Metric,
  Provenance,
  Source,
  TimePoint,
} from "../src/services/contracts";

const FILTERS: Filters = {
  source: "NSW",
  dateRange: { from: "2020-01-01", to: "2024-12-31" },
  datasetVersion: "demo-v1.0",
  batchId: "demo-nsw-v1",
};

// These fixture-contract tests always inject their provider; production defaults
// may use HTTP and must never change which observations this suite validates.
const getAnalytics: typeof readAnalytics = (filters, service = mockProvider) =>
  readAnalytics(filters, service);

for (const source of ["NSW", "VIC", "QLD"] as Source[]) {
  test(`${source}: analytics reconciles with the existing public service`, async () => {
    const filters = {
      ...FILTERS,
      source,
      batchId: `demo-${source.toLowerCase()}-v1`,
    };
    const [result, overview, annual] = await Promise.all([
      getAnalytics(filters),
      mockProvider.getOverview(filters),
      mockProvider.getTimeSeries(filters, "yearly"),
    ]);
    const data = result.data;
    assert.equal(result.meta.batchId, filters.batchId);
    assert.deepEqual(data.overview, overview.data);
    assert.deepEqual(data.timeSeriesYearly.map(row => ({ period: row.period, crashes: row.crashes, fatalCrashes: row.fatalCrashes, livesLost: row.livesLost, casualties: row.casualties })), annual.data);
    assert.equal(data.monthly.length, 60);
    assert.equal(data.summary.total, overview.data.crashes.value);
    assert.equal(data.summary.fatalShare, overview.data.fatalShare);
    assert.equal(
      data.severity.reduce((sum, row) => sum + row.count, 0),
      data.summary.total,
    );
    assert.ok(
      Math.abs(data.severity.reduce((sum, row) => sum + row.share!, 0) - 1) <
        1e-12,
    );
    assert.ok(data.calendarMonths.every((row) => row.observedMonths === 5));
    assert.deepEqual(data.heatmap, data.monthly);
    assert.equal(data.summary.latestYear, 2024);
    assert.equal(data.summary.latestComparableYear, 2024);
    const prior = annual.data.at(-2)!.crashes!,
      latest = annual.data.at(-1)!.crashes!;
    assert.equal(data.summary.yoyPct, ((latest - prior) / prior) * 100);
    assert.ok(
      data.notes.some((note) => note.includes("synthetically allocated")),
    );
  });
}

test("half-year comparison uses exactly the same six months in the preceding year", async () => {
  const filters = {
    ...FILTERS,
    dateRange: { from: "2024-01-12", to: "2024-06-18" },
  };
  const calls: Filters[] = [];
  const provider = {
    ...mockProvider,
    async getTimeSeries(f: Filters, grain: "yearly" | "monthly") {
      calls.push(structuredClone(f));
      return mockProvider.getTimeSeries(f, grain);
    },
  };
  const { data } = await getAnalytics(filters, provider);
  const previous = await mockProvider.getOverview({
    ...filters,
    dateRange: { from: "2023-01-01", to: "2023-06-30" },
  });
  const year = data.yearly[0];
  assert.equal(year.requestedMonths, 6);
  assert.equal(year.observedMonths, 6);
  assert.equal(year.complete, true);
  assert.equal(year.fullYear, false);
  assert.deepEqual(year.comparisonMonths, [1, 2, 3, 4, 5, 6]);
  assert.equal(year.previousCrashes, previous.data.crashes.value);
  assert.equal(
    year.yoyPct,
    ((year.crashes! - previous.data.crashes.value!) /
      previous.data.crashes.value!) *
      100,
  );
  assert.equal(data.monthly.length, 6);
  assert.equal(data.calendarMonths[6].average, null);
  assert.equal(data.calendarMonths[6].observedMonths, 0);
  assert.deepEqual(calls[0].dateRange, filters.dateRange);
  assert.deepEqual(calls[1].dateRange, {
    from: "2023-01-01",
    to: "2023-06-30",
  });
  assert.ok(
    calls.every(
      (call) =>
        call.batchId === filters.batchId &&
        call.datasetVersion === filters.datasetVersion &&
        call.source === filters.source,
    ),
  );
});

test("a range spanning partial years compares each year using its own selected months", async () => {
  const { data } = await getAnalytics({
    ...FILTERS,
    dateRange: { from: "2022-08-01", to: "2024-03-31" },
  });
  assert.deepEqual(
    data.yearly.map((row) => row.requestedMonths),
    [5, 12, 3],
  );
  assert.deepEqual(data.yearly[0].comparisonMonths, [8, 9, 10, 11, 12]);
  assert.deepEqual(data.yearly[2].comparisonMonths, [1, 2, 3]);
  assert.ok(data.yearly.every((row) => row.previousCrashes !== null));
});

test("uncovered prior periods yield null, and latest summary never falls back to an earlier year", async () => {
  const earliest = await getAnalytics({
    ...FILTERS,
    dateRange: { from: "2020-01-01", to: "2020-06-30" },
  });
  assert.equal(earliest.data.summary.yoyPct, null);
  assert.equal(earliest.data.yearly[0].previousCrashes, null);
  assert.match(earliest.data.yearly[0].comparisonReason!, /not fully covered/);
  const later = await getAnalytics({
    ...FILTERS,
    dateRange: { from: "2023-01-01", to: "2025-06-30" },
  });
  assert.equal(later.data.yearly[1].yoyPct !== null, true);
  assert.equal(later.data.summary.latestYear, 2025);
  assert.equal(later.data.summary.latestComparableYear, null);
  assert.equal(later.data.summary.yoyPct, null);
});

/** Small independent service double, unrelated to the application fixtures. */
function observedProvider(
  points: TimePoint[],
  unavailable = false,
): ArsiaService {
  const selected = (f: Filters) =>
    unavailable
      ? []
      : points.filter(
          (row) =>
            row.period >= f.dateRange.from.slice(0, 7) &&
            row.period <= f.dateRange.to.slice(0, 7),
        );
  const meta = (f: Filters): Provenance => ({
    demo: true,
    source: f.source,
    datasetVersion: f.datasetVersion,
    batchId: f.batchId,
    availability: unavailable
      ? "unsupported"
      : selected(f).length
        ? "available"
        : "no_results",
    coverage: {
      from: "2020-01-01",
      to: "2024-12-31",
      granularity: "month",
      complete: true,
    },
    definition: "Independent test observations",
    unit: "crashes",
    evidence: [],
  });
  const sum = (
    rows: TimePoint[],
    key: "crashes" | "fatalCrashes" | "livesLost" | "casualties",
  ) =>
    !rows.length || rows.some((row) => row[key] === null)
      ? null
      : rows.reduce((total, row) => total + row[key]!, 0);
  return {
    ...mockProvider,
    async getTimeSeries(f) {
      return { data: selected(f), meta: meta(f) };
    },
    async getSeverityDistribution(f) {
      const count = sum(selected(f), "crashes");
      return {
        data:
          count !== null
            ? [
                {
                  label: "Other",
                  count,
                  definition: "Test category",
                },
              ]
            : [],
        meta:
          count === null && selected(f).length
            ? { ...meta(f), availability: "unknown" }
            : meta(f),
      };
    },
    async getOverview(f) {
      const rows = selected(f);
      const metric = (
        key: "crashes" | "fatalCrashes" | "livesLost" | "casualties",
      ): Metric => {
        const value = sum(rows, key);
        return {
          value,
          availability:
            rows.length && value === null ? "unknown" : meta(f).availability,
          label: key,
          unit: "test count",
          definition: "Independent test observations",
        };
      };
      return {
        meta: meta(f),
        data: {
          crashes: metric("crashes"),
          fatalCrashes: metric("fatalCrashes"),
          livesLost: metric("livesLost"),
          casualties: metric("casualties"),
          fatalShare: null,
        },
      };
    },
  };
}

const point = (period: string, crashes: number): TimePoint => ({
  period,
  crashes,
  fatalCrashes: 0,
  livesLost: 0,
  casualties: 0,
});

test("real zeros stay observed; missing months stay null and do not dilute averages", async () => {
  const provider = observedProvider([
    point("2021-01", 0),
    point("2022-01", 12),
    point("2022-03", 3),
  ]);
  const { data } = await getAnalytics(
    { ...FILTERS, dateRange: { from: "2021-01-01", to: "2022-03-31" } },
    provider,
  );
  assert.equal(data.monthly[0].crashes, 0);
  assert.equal(data.monthly[0].availability, "available");
  assert.equal(data.monthly[1].crashes, null);
  assert.equal(data.monthly[1].availability, "unknown");
  assert.equal(data.calendarMonths[0].observedMonths, 2);
  assert.equal(data.calendarMonths[0].average, 6);
  assert.equal(data.calendarMonths[1].observedMonths, 0);
  assert.equal(data.calendarMonths[1].average, null);
  assert.equal(data.summary.total, 15);
  assert.equal(data.yearly[1].crashes, null);
  assert.equal(data.yearly[1].complete, false);
  assert.equal(data.yearly[1].yoyPct, null);
});

test("a zero prior count does not produce Infinity, and an observed zero current count is -100%", async () => {
  const filters = {
    ...FILTERS,
    dateRange: { from: "2022-01-01", to: "2022-01-31" },
  };
  const zeroPrior = await getAnalytics(
    filters,
    observedProvider([point("2021-01", 0), point("2022-01", 5)]),
  );
  assert.equal(zeroPrior.data.yearly[0].previousCrashes, 0);
  assert.equal(zeroPrior.data.summary.yoyPct, null);
  assert.match(
    zeroPrior.data.yearly[0].comparisonReason!,
    /previous count is zero/,
  );
  const zeroCurrent = await getAnalytics(
    filters,
    observedProvider([point("2021-01", 5), point("2022-01", 0)]),
  );
  assert.equal(zeroCurrent.data.summary.total, 0);
  assert.equal(zeroCurrent.data.summary.yoyPct, -100);
  assert.equal(zeroCurrent.data.calendarMonths[0].average, 0);
  assert.equal(zeroCurrent.data.severity[0].share, null);
});

test("empty, unsupported and invalid version selections never masquerade as zero", async () => {
  const empty = await getAnalytics({
    ...FILTERS,
    dateRange: { from: "2025-01-01", to: "2025-03-31" },
  });
  assert.equal(empty.meta.availability, "no_results");
  assert.equal(empty.data.summary.total, null);
  assert.equal(empty.data.summary.peakMonth, null);
  assert.ok(empty.data.monthly.every((row) => row.crashes === null));
  assert.equal(empty.data.timeSeriesYearly.length, 0);
  const unsupported = await getAnalytics(FILTERS, observedProvider([], true));
  assert.equal(unsupported.meta.availability, "unsupported");
  assert.equal(unsupported.data.summary.total, null);
  assert.ok(
    unsupported.data.monthly.every((row) => row.availability === "unsupported"),
  );
  for (const filters of [
    { ...FILTERS, datasetVersion: "unknown" },
    { ...FILTERS, batchId: "wrong-batch" },
  ]) {
    const invalid = await getAnalytics(filters);
    assert.equal(invalid.meta.availability, "unsupported");
    assert.equal(invalid.data.summary.total, null);
    assert.equal(invalid.data.severity.length, 0);
  }
});

test("All resolves visibly to NSW without mutating filters or repairing an unknown batch", async () => {
  const all: Filters = { ...FILTERS, source: "All", batchId: "demo-all-v1" };
  const { data, meta } = await getAnalytics(all);
  assert.equal(data.source, "NSW");
  assert.equal(data.filters.source, "NSW");
  assert.equal(data.filters.batchId, "demo-nsw-v1");
  assert.equal(meta.source, "NSW");
  assert.equal(data.summary.total, 18420);
  assert.equal(all.source, "All");
  assert.equal(all.batchId, "demo-all-v1");
  assert.equal(
    analyticsFilters({ ...all, batchId: "unknown" }).batchId,
    "unknown",
  );
});

test("mixed batches and inconsistent totals are rejected instead of composed into charts", async () => {
  const mixed = {
    ...mockProvider,
    async getSeverityDistribution(f: Filters) {
      const response = await mockProvider.getSeverityDistribution(f);
      return {
        ...response,
        meta: { ...response.meta, batchId: "different-batch" },
      };
    },
  };
  await assert.rejects(
    () => getAnalytics(FILTERS, mixed),
    /same source, dataset version and batch/,
  );
  const inconsistent = {
    ...mockProvider,
    async getTimeSeries(f: Filters, grain: "yearly" | "monthly") {
      const response = await mockProvider.getTimeSeries(f, grain);
      return {
        ...response,
        data: response.data.map((row, index) =>
          index === 0 ? { ...row, crashes: row.crashes! + 1 } : row,
        ),
      };
    },
  };
  await assert.rejects(
    () => getAnalytics(FILTERS, inconsistent),
    /do not reconcile/,
  );
});

test("invalid dates and reversed ranges are rejected before reading the service", async () => {
  for (const dateRange of [
    { from: "2024-02-30", to: "2024-03-01" },
    { from: "2024-05-20", to: "2024-05-01" },
  ])
    await assert.rejects(
      () => getAnalytics({ ...FILTERS, dateRange }),
      /calendar dates|start before/,
    );
});

test("unknown metric values propagate through yearly totals while known metrics remain usable", async () => {
  const provider = observedProvider([
    point("2021-01", 5),
    point("2021-02", 5),
    { ...point("2022-01", 4), fatalCrashes: null, casualties: null },
    { ...point("2022-02", 6), fatalCrashes: 2, casualties: 8 },
  ]);
  const { data } = await getAnalytics(
    { ...FILTERS, dateRange: { from: "2022-01-01", to: "2022-02-28" } },
    provider,
  );
  assert.equal(data.monthly[0].availability, "available");
  assert.equal(data.monthly[0].fatalCrashes, null);
  assert.equal(data.yearly[0].complete, true);
  assert.equal(data.yearly[0].crashes, 10);
  assert.equal(data.yearly[0].fatalCrashes, null);
  assert.equal(data.yearly[0].casualties, null);
  assert.equal(data.yearly[0].livesLost, 0);
  assert.equal(data.timeSeriesYearly[0].fatalCrashes, null);
  assert.equal(data.summary.total, 10);
  assert.equal(data.summary.yoyPct, 0);
  assert.ok(data.notes.some((note) => note.includes("Unknown metric values")));
});

test("unknown current or prior crash counts withhold percentages and are excluded from calendar means", async () => {
  const range = {
    ...FILTERS,
    dateRange: { from: "2022-01-01", to: "2022-02-28" },
  };
  const unknownCurrent = await getAnalytics(
    range,
    observedProvider([
      point("2021-01", 5),
      point("2021-02", 5),
      { ...point("2022-01", 0), crashes: null },
      point("2022-02", 0),
    ]),
  );
  assert.equal(unknownCurrent.data.summary.total, null);
  assert.equal(unknownCurrent.data.summary.yoyPct, null);
  assert.equal(unknownCurrent.data.yearly[0].crashes, null);
  assert.equal(unknownCurrent.data.calendarMonths[0].average, null);
  assert.equal(unknownCurrent.data.calendarMonths[0].observedMonths, 0);
  assert.equal(unknownCurrent.data.calendarMonths[1].average, 0);
  assert.equal(unknownCurrent.data.calendarMonths[1].observedMonths, 1);
  assert.equal(unknownCurrent.data.severityAvailability, "unknown");
  assert.deepEqual(unknownCurrent.data.severity, []);
  const unknownPrior = await getAnalytics(
    range,
    observedProvider([
      { ...point("2021-01", 0), crashes: null },
      point("2021-02", 5),
      point("2022-01", 4),
      point("2022-02", 6),
    ]),
  );
  assert.equal(unknownPrior.data.summary.total, 10);
  assert.equal(unknownPrior.data.summary.yoyPct, null);
  assert.equal(unknownPrior.data.yearly[0].previousCrashes, null);
  assert.match(
    unknownPrior.data.yearly[0].comparisonReason!,
    /unknown crash counts/,
  );
});

test("an unavailable severity window retains its reason without blocking real monthly analysis", async () => {
  const base = observedProvider([point("2021-01", 5), point("2022-01", 6)]);
  const reason = "Only the full 2020–2024 severity distribution was exported.";
  const provider: ArsiaService = {
    ...base,
    async getOverview(f) {
      const response = await base.getOverview(f);
      return { ...response, meta: { ...response.meta, demo: false } };
    },
    async getTimeSeries(f, grain) {
      const response = await base.getTimeSeries(f, grain);
      return { ...response, meta: { ...response.meta, demo: false } };
    },
    async getSeverityDistribution(f) {
      const response = await base.getSeverityDistribution(f);
      return {
        data: [],
        meta: {
          ...response.meta,
          demo: false,
          availability: "unsupported",
          reason,
        },
      };
    },
  };
  const { data, meta } = await getAnalytics(
    { ...FILTERS, dateRange: { from: "2022-01-01", to: "2022-01-31" } },
    provider,
  );
  assert.equal(meta.demo, false);
  assert.equal(data.summary.total, 6);
  assert.equal(data.summary.yoyPct, 20);
  assert.deepEqual(data.severity, []);
  assert.equal(data.severityAvailability, "unsupported");
  assert.equal(data.severityReason, reason);
  assert.ok(data.notes.includes(reason));
  assert.ok(
    data.notes.some((note) => note.includes("published source-specific")),
  );
  assert.ok(data.notes.every((note) => !note.includes("synthetic")));
});

test("official All keeps its published batch when resolving the analysis source", () => {
  const official: Filters = {
    ...FILTERS,
    source: "All",
    datasetVersion: "official-v1",
    batchId: "bcc5da57-25f2-41ec-9925-bef421b02671",
  };
  assert.deepEqual(analyticsFilters(official), { ...official, source: "NSW" });
  assert.equal(official.source, "All");
});
