import test, { before } from "node:test";
import assert from "node:assert/strict";
import { AnalysisWorkspace } from "../src/server/analysis/workspace";
import {
  loadOfficialSnapshot,
  createOfficialProvider,
} from "../src/server/official-data";
import {
  loadRegionSnapshot,
  createRegionalProvider,
} from "../src/server/region-data";
import { DEFAULT_FILTERS } from "../src/services/config";
import { readArtifact } from "../src/server/analysis/artifacts";
let workspace: AnalysisWorkspace;
const signal = new AbortController().signal;
const args = {
  dataset: "lga_monthly",
  source: "NSW",
  dateRange: { from: "2024-01-01", to: "2024-12-31" },
  regionId: "all",
  groupBy: ["regionId", "regionName"],
  metrics: ["crashes"],
  where: [],
  orderBy: { field: "crashes", direction: "desc" },
  limit: 1000,
};
before(async () => {
  const regional = await loadRegionSnapshot();
  workspace = new AnalysisWorkspace(
    { page: "/", filters: DEFAULT_FILTERS },
    createRegionalProvider(
      createOfficialProvider(await loadOfficialSnapshot()),
      regional,
    ),
    regional,
  );
});
const query = async (a: unknown) =>
  JSON.parse(
    JSON.stringify(await workspace.execute("workspace_query", a, signal, "E1")),
  );
test("LGA group/ranking is exact and validated, with no multiplication from catalog join", async () => {
  const result = await query({
    ...args,
    where: [{ field: "regionId", operator: "eq", value: "17200" }],
  });
  assert.equal(result.preview[0].regionName, "Sydney");
  assert.equal(result.preview[0].crashes, 641);
  assert.equal(result.resultRows, 1);
  assert.equal(result.batchId, DEFAULT_FILTERS.batchId);
});
test("All forces source grouping, cannot silently produce a national sum", async () => {
  const r = await query({
    ...args,
    dataset: "monthly_metrics",
    source: "All",
    dateRange: null,
    groupBy: ["source"],
  });
  assert.deepEqual(
    r.preview
      .map((r: { crashes: number }) => r.crashes)
      .sort((a: number, b: number) => a - b),
    [66624, 72170, 92082],
  );
  assert.ok(r.preview.every((r: Record<string, unknown>) => r.source));
});
test("full LGA aggregate including unmatched reconciles official source counts", async () => {
  const r = await query({ ...args, dateRange: null, groupBy: ["source"] });
  assert.equal(r.preview[0].crashes, 92082);
});
test("locality definitions and unsupported VIC are explicit, unknown fields and invalid join attempts rejected", async () => {
  const r = await query({
    ...args,
    dataset: "locality_monthly",
    source: "VIC",
  });
  assert.equal(r.availability, "unsupported");
  assert.equal(r.resultRows, 0);
  await assert.rejects(query({ ...args, groupBy: ["ACCIDENT_NO"] }));
  await assert.rejects(query({ ...args, source: "WA" }));
  await assert.rejects(query({ ...args, limit: 10001 }));
  await assert.rejects(query({ ...args, dataset: "raw_people" }));
  await assert.rejects(query({ ...args, join: "vehicle" }));
});
test("valid empty period is no_results and never invented zero rows", async () => {
  const r = await query({
    ...args,
    dateRange: { from: "2019-01-01", to: "2019-12-31" },
  });
  assert.equal(r.availability, "no_results");
  assert.deepEqual(r.preview, []);
});
test("page LGA is inherited, can only be broadened via explicit all", async () => {
  const regional = await loadRegionSnapshot();
  const w = new AnalysisWorkspace(
    {
      page: "/",
      filters: { ...DEFAULT_FILTERS, source: "NSW", regionId: "17200" },
    },
    createRegionalProvider(
      createOfficialProvider(await loadOfficialSnapshot()),
      regional,
    ),
    regional,
  );
  const r = await w.execute(
    "workspace_query",
    { ...args, regionId: null, groupBy: ["source"] },
    signal,
    "E1",
  );
  assert.equal((r.preview as { crashes: number }[])[0].crashes, 641);
});
test("chart data and CSV come from query, download metadata has provenance/hash; arbitrary IDs denied", async () => {
  const q = await query({
    ...args,
    dataset: "monthly_metrics",
    groupBy: ["year"],
  });
  const r = await workspace.execute(
    "present_analysis",
    {
      queryId: q.queryId,
      kind: "line",
      title: "NSW annual crashes",
      x: "year",
      y: "crashes",
      series: null,
    },
    signal,
    "E2",
  );
  const artifact = (r.artifacts as { id: string }[])[0];
  const stored = await readArtifact(artifact.id);
  assert.ok(stored);
  assert.match(stored.bytes.toString(), /18939/);
  assert.equal(stored.artifact.sha256.length, 64);
  assert.ok(stored.provenance);
  assert.equal(await readArtifact("../../.env.local"), null);
  await assert.rejects(
    workspace.execute(
      "present_analysis",
      {
        queryId: "Q999",
        kind: "line",
        title: "Fake",
        x: "year",
        y: "crashes",
        series: null,
      },
      signal,
      "E3",
    ),
  );
});
test("charts reject duplicate dimensions and pooling sources", async () => {
  const q = await query({
    ...args,
    dataset: "monthly_metrics",
    source: "All",
    groupBy: ["source", "year"],
    dateRange: null,
  });
  await assert.rejects(
    workspace.execute(
      "present_analysis",
      {
        queryId: q.queryId,
        kind: "line",
        title: "Pooled",
        x: "year",
        y: "crashes",
        series: null,
      },
      signal,
      "E2",
    ),
  );
});
test("query retention is explicitly truncated and previews bounded", async () => {
  const r = await query({ ...args, groupBy: [], limit: 15 });
  assert.equal(r.preview.length, 12);
  assert.equal(r.truncated, true);
  assert.equal(r.retainedLocally, 15);
});
