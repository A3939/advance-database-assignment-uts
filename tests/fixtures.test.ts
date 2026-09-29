import test from "node:test";
import assert from "node:assert/strict";
import { mockProvider as api } from "../src/services/mock-provider";
import {
  DEFAULT_FILTERS as APP_DEFAULT,
  allocate,
} from "../src/services/fixtures";
import type { Filters, Source } from "../src/services/contracts";

const DEFAULT_FILTERS: Filters = {
  ...APP_DEFAULT,
  source: "NSW",
  batchId: "demo-nsw-v1",
};

test("largest remainder allocation conserves totals, including zero", () => {
  for (const total of [0, 1, 7, 172, 18420])
    assert.equal(
      allocate(total, [1, 3, 7, 9]).reduce((a, b) => a + b, 0),
      total,
    );
});
test("NSW screenshot totals and severity distribution reconcile exactly", async () => {
  const [o, t, s] = await Promise.all([
    api.getOverview(DEFAULT_FILTERS),
    api.getTimeSeries(DEFAULT_FILTERS, "yearly"),
    api.getSeverityDistribution(DEFAULT_FILTERS),
  ]);
  assert.deepEqual(
    [
      o.data.crashes.value,
      o.data.fatalCrashes.value,
      o.data.livesLost.value,
      o.data.casualties.value,
    ],
    [18420, 172, 188, 8640],
  );
  assert.deepEqual(
    t.data.map((r) => r.crashes),
    [3215, 3482, 3911, 4028, 3784],
  );
  assert.deepEqual(
    s.data.map((r) => r.count),
    [172, 1308, 3000, 4160, 9780],
  );
});
for (const source of ["NSW", "VIC", "QLD"] as Source[]) {
  test(`${source}: all months, partial ranges, map groups and severity reconcile`, async () => {
    for (const dates of [
      { from: "2020-01-01", to: "2024-12-31" },
      { from: "2022-03-01", to: "2023-08-31" },
      { from: "2024-02-01", to: "2024-02-29" },
    ]) {
      const f: Filters = {
        ...DEFAULT_FILTERS,
        source,
        batchId: `demo-${source.toLowerCase()}-v1`,
        dateRange: dates,
      };
      const o = await api.getOverview(f),
        m = await api.getTimeSeries(f, "monthly"),
        y = await api.getTimeSeries(f, "yearly"),
        s = await api.getSeverityDistribution(f),
        map = await api.getMapData(f);
      for (const k of [
        "crashes",
        "fatalCrashes",
        "livesLost",
        "casualties",
      ] as const) {
        assert.equal(
          m.data.reduce((n, r) => n + r[k]!, 0),
          o.data[k].value,
        );
        assert.equal(
          y.data.reduce((n, r) => n + r[k]!, 0),
          o.data[k].value,
        );
      }
      assert.equal(
        s.data.reduce((n, r) => n + r.count, 0),
        o.data.crashes.value,
      );
      assert.equal(
        map.data.regions.reduce((n, r) => n + r.count, 0),
        o.data.crashes.value,
      );
      assert.ok(o.meta.demo);
      assert.equal(o.meta.source, source);
    }
  });
}
test("uncovered dates and wrong batch do not masquerade as zero", async () => {
  for (const f of [
    { ...DEFAULT_FILTERS, dateRange: { from: "2025-01-01", to: "2025-12-31" } },
    { ...DEFAULT_FILTERS, batchId: "not-this-version" },
  ]) {
    const o = await api.getOverview(f);
    assert.equal(o.meta.availability, "no_results");
    assert.equal(o.data.crashes.value, null);
    assert.equal((await api.getMapData(f)).data.regions.length, 0);
  }
});
test("partial coverage is explicit", async () => {
  assert.equal(
    (
      await api.getOverview({
        ...DEFAULT_FILTERS,
        dateRange: { from: "2019-01-01", to: "2021-12-31" },
      })
    ).meta.coverage.complete,
    false,
  );
});
test("record samples are labelled, paginated, searched and sorted", async () => {
  const p = await api.getCrashRecords(
    DEFAULT_FILTERS,
    { page: 1, pageSize: 8 },
    { field: "date", direction: "asc" },
  );
  assert.equal(p.data.total, 180);
  assert.equal(p.data.rows.length, 8);
  assert.equal(p.data.aggregateCount, 18420);
  assert.ok(p.data.sampleOnly);
  const q = await api.getCrashRecords(
    DEFAULT_FILTERS,
    { page: 2, pageSize: 8 },
    { field: "date", direction: "asc" },
  );
  assert.ok(!q.data.rows.some((r) => p.data.rows.some((a) => r.id === a.id)));
  const s = await api.getCrashRecords(
    DEFAULT_FILTERS,
    { page: 1, pageSize: 50, search: "Sydney" },
    { field: "date", direction: "desc" },
  );
  assert.equal(s.data.total, 60);
  assert.ok(s.data.rows.every((r) => r.region === "Sydney"));
});
test("agent streams simulation and evidence, honours cancelled requests", async () => {
  const events = [];
  for await (const e of api.sendAgentMessage(
    { filters: DEFAULT_FILTERS, page: "/" },
    "Explain the change",
  ))
    events.push(e);
  assert.ok(
    events.some(
      (e) => e.type === "message" && e.simulated && e.text.includes("6.1%"),
    ),
  );
  assert.ok(events.some((e) => e.type === "evidence"));
  const controller = new AbortController();
  controller.abort();
  const cancelled = [];
  for await (const e of api.sendAgentMessage(
    { filters: DEFAULT_FILTERS, page: "/" },
    "Hello",
    controller.signal,
  ))
    cancelled.push(e);
  assert.equal(cancelled.length, 0);
});
test("import is metadata-only and never pretends to publish", async () => {
  await assert.rejects(() => api.createImportJob([]));
  const job = await api.createImportJob([
    { name: "example.csv", size: 12, type: "text/csv" },
  ]);
  assert.equal(job.status, "queued");
  assert.ok(job.demo);
  await new Promise((r) => setTimeout(r, 1450));
  assert.equal((await api.getImportJobStatus(job.id)).status, "needs_input");
});

test("sample record identity and attributes stay stable across date filters", async () => {
  const pagination = { page: 1, pageSize: 50, search: "2024-03" };
  const sort = { field: "id", direction: "asc" } as const;
  const all = await api.getCrashRecords(DEFAULT_FILTERS, pagination, sort);
  const filtered = await api.getCrashRecords(
    { ...DEFAULT_FILTERS, dateRange: { from: "2024-03-01", to: "2024-03-31" } },
    pagination,
    sort,
  );
  assert.deepEqual(filtered.data.rows, all.data.rows);
});
test("suggested summary returns the selected aggregate", async () => {
  const replies = [];
  for await (const event of api.sendAgentMessage(
    { filters: DEFAULT_FILTERS, page: "/" },
    "Summarise this selection",
  ))
    if (event.type === "message") replies.push(event.text);
  assert.ok(replies[0].includes("18,420"));
});

test("All defaults to a country view with independent state metrics", async () => {
  assert.equal(APP_DEFAULT.source, "All");
  const o = await api.getOverview(APP_DEFAULT);
  assert.equal(o.data.crashes.value, null);
  assert.equal(o.data.crashes.availability, "unsupported");
  assert.deepEqual(
    o.data.crashes.bySource?.map((r) => r.value),
    [18420, 10180, 9390],
  );
  const map = await api.getMapData(APP_DEFAULT);
  assert.equal(map.data.level, "country");
  assert.deepEqual(
    map.data.states?.filter((s) => s.available).map((s) => s.source),
    ["NSW", "VIC", "QLD"],
  );
  assert.deepEqual(
    map.data.states?.filter((s) => s.available).map((s) => s.count),
    [18420, 10180, 9390],
  );
  assert.ok(
    map.data.states
      ?.filter((s) => !s.available)
      .every((s) => s.count === undefined),
  );
  const yearlyMap = await api.getMapData({
    ...APP_DEFAULT,
    dateRange: { from: "2024-01-01", to: "2024-12-31" },
  });
  assert.equal(
    yearlyMap.data.states?.find((s) => s.source === "NSW")?.count,
    3784,
  );
  const times = await api.getTimeSeries(APP_DEFAULT, "yearly");
  assert.equal(times.data.length, 15);
  assert.equal(
    times.data
      .filter((t) => t.source === "NSW")
      .reduce((sum, t) => sum + t.crashes!, 0),
    18420,
  );
  const severities = await api.getSeverityDistribution(APP_DEFAULT);
  assert.equal(severities.data.length, 12);
  assert.ok(severities.data.every((s) => s.source));
  const empty = {
    ...APP_DEFAULT,
    dateRange: { from: "2025-01-01", to: "2025-12-31" },
  };
  assert.ok(
    (await api.getMapData(empty)).data.states?.every(
      (s) => !s.available && s.count === undefined,
    ),
  );
  assert.equal((await api.getOverview(empty)).meta.availability, "no_results");
});
