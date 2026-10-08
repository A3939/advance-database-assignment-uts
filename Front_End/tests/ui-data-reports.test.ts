import test, { before } from "node:test";
import assert from "node:assert/strict";
import { setImmediate } from "node:timers/promises";
import { DEFAULT_FILTERS } from "../src/services/config";
import type { Filters, Metric, Overview, Response as DataResponse } from "../src/services/contracts";
import { getSeverityChange } from "../src/server/severity-change";
import { getSpeedZones, loadSpeedZoneSnapshot } from "../src/server/speed-zone";
import { createOfficialProvider, loadOfficialSnapshot } from "../src/server/official-data";
import { createRegionalProvider, loadRegionSnapshot } from "../src/server/region-data";
import { getSeverityChange as readSeverityChange, getSpeedZones as readSpeedZones, httpProvider, DATA_REQUEST_TIMEOUT_MS } from "../src/services/http-provider";
import { parseAgentRequest } from "../src/server/agent/request";

let regional: Awaited<ReturnType<typeof loadRegionSnapshot>>;
let speed: Awaited<ReturnType<typeof loadSpeedZoneSnapshot>>;
let official: ReturnType<typeof createOfficialProvider>;
let service: ReturnType<typeof createRegionalProvider>;
before(async () => {
  [regional, speed] = await Promise.all([loadRegionSnapshot(), loadSpeedZoneSnapshot()]);
  official = createOfficialProvider(await loadOfficialSnapshot());
  service = createRegionalProvider(official, regional);
});

// Only the dynamic overview boundary is controlled. Both extension functions and
// their immutable aggregate files are real; no server, database or model is used.
function dynamicOverview(filters: Filters): Promise<DataResponse<Overview>> {
  const unknown: Metric = { value: null, availability: "unknown", label: "Unavailable", unit: "events", definition: "No admitted count in this test context." };
  return Promise.resolve({
    data: { crashes: unknown, fatalCrashes: unknown, livesLost: unknown, casualties: unknown, fatalShare: null },
    meta: { demo: false, source: filters.source, batchId: filters.batchId, datasetVersion: filters.datasetVersion,
      ...(filters.releaseId ? { releaseId: filters.releaseId } : {}), availability: "unknown", unit: "events",
      coverage: { ...filters.dateRange, granularity: "month", complete: false }, definition: "Dynamic publication boundary fixture", evidence: [] },
  });
}

test("both fixed reports retain the independently reconciled official path", async () => {
  const filters = { ...DEFAULT_FILTERS, source: "NSW" };
  const severity = await getSeverityChange(filters, service, regional);
  const zones = await getSpeedZones(filters, official, speed);
  assert.equal(severity.meta.availability, "available");
  assert.equal(zones.meta.availability, "available");
  const full = await official.getOverview(filters);
  assert.equal(zones.data.groups[0].rows.reduce((n, row) => n + row.crashes, 0)
    + zones.data.groups[0].excluded.reduce((n, row) => n + row.crashes, 0), full.data.crashes.value);
  for (const [index, period] of severity.data.periods!.entries()) {
    const independentlySelected = await official.getOverview({ ...filters, dateRange: period.dateRange });
    assert.equal(severity.data.groups[0].totals![index], independentlySelected.data.crashes.value);
  }
});

for (const [label, filters] of [
  ["a different batch", { ...DEFAULT_FILTERS, source: "NSW", batchId: "other-admitted-batch" }],
  ["a different dataset version", { ...DEFAULT_FILTERS, source: "NSW", datasetVersion: "local-integrated-v1" }],
  ["a release even when its batch text matches", { ...DEFAULT_FILTERS, source: "NSW", releaseId: DEFAULT_FILTERS.batchId }],
  ["a dynamic source absent from the extensions", { ...DEFAULT_FILTERS, source: "SOURCE_UNKNOWN_27" }],
  ["a dynamic source and its own area", { ...DEFAULT_FILTERS, source: "SOURCE_UNKNOWN_27", regionId: "area-27", datasetVersion: "local-integrated-v1", batchId: "dynamic-batch", releaseId: "dynamic-release" }],
] as const) {
  test(`${label} never borrows fixed severity or speed observations`, async () => {
    const overview = filters.source.startsWith("SOURCE_")
      ? { getOverview: dynamicOverview } : service;
    for (const result of [
      await getSeverityChange(filters, overview, regional),
      await getSpeedZones(filters, overview, speed),
    ]) {
      assert.equal(result.meta.availability, "unsupported");
      assert.equal(result.meta.source, filters.source);
      assert.equal(result.meta.batchId, filters.batchId);
      assert.equal(result.meta.datasetVersion, filters.datasetVersion);
      assert.ok(result.data.groups.every(group => group.rows.length === 0));
      assert.ok(result.data.reason, "The unavailable scope needs an explanation");
      assert.ok(!result.meta.evidence.some(item => [regional.extensionVersion, speed.extensionVersion].includes(item.id)), "An unbound snapshot extension must not become release evidence");
    }
  });
}

test("all report clients preserve release identity through deadlines and a fresh retry", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const calls: { url: string; signal: AbortSignal }[] = [];
  t.mock.method(globalThis, "fetch", async (url: string, init: RequestInit) => {
    calls.push({ url, signal: init.signal as AbortSignal });
    return calls.length === 1 ? new Promise(() => {}) : Response.json({ data: {}, meta: {} });
  });
  const filters: Filters = { ...DEFAULT_FILTERS, source: "dynamic-source", datasetVersion: "local-integrated-v1", batchId: "a-pinned-batch", releaseId: "a-pinned-release" };
  let stopped: unknown;
  void httpProvider.getMapData(filters).catch(error => { stopped = error; });
  await setImmediate();
  t.mock.timers.tick(DATA_REQUEST_TIMEOUT_MS + 1);
  await setImmediate();
  assert.equal((stopped as Error | undefined)?.name, "TimeoutError");
  assert.equal(calls.length, 1, "No hidden retry before the caller acts");
  assert.equal(calls[0].signal.aborted, true);
  await httpProvider.getMapData(filters);
  await readSeverityChange(filters);
  await readSpeedZones(filters);
  assert.equal(calls[0].url, calls[1].url);
  assert.deepEqual(calls.slice(1).map(call => new URL(call.url, "http://localhost").pathname),
    ["/api/data/map", "/api/data/severity-change", "/api/data/speed-zones"]);
  for (const call of calls) {
    const query = new URL(call.url, "http://localhost").searchParams;
    for (const key of ["source", "datasetVersion", "batchId", "releaseId"] as const)
      assert.equal(query.get(key), filters[key]);
    assert.equal(query.get("from"), filters.dateRange.from);
    assert.equal(query.get("to"), filters.dateRange.to);
  }
});

test("the real AI request parser accepts each new analytics context while rejecting unknown pages", () => {
  for (const page of ["/analytics/severity", "/analytics/spatial"]) {
    const parsed = parseAgentRequest({ context: { page, filters: DEFAULT_FILTERS }, message: "Explain the selected report", history: [] });
    assert.equal(parsed.context.page, page);
    assert.deepEqual(parsed.context.filters, { ...DEFAULT_FILTERS, regionId: undefined });
  }
  assert.throws(() => parseAgentRequest({ context: { page: "/analytics/unregistered", filters: DEFAULT_FILTERS }, message: "Explain", history: [] }), /Unknown page context/);
});
