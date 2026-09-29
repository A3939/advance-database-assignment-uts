import { expect, test, type APIRequestContext } from "@playwright/test";
import type { Response, Overview, TimePoint, Severity, MapData, Records, Dataset } from "../../src/services/contracts";

const batchId = "bcc5da57-25f2-41ec-9925-bef421b02671";
const datasetVersion = "official-v1";
const totals = { NSW: [92082, 1388, 1507, 78154], VIC: [72170, 1182, 1265, 91798], QLD: [66624, 1304, 1424, 88609] } as const;

async function report<T>(request: APIRequestContext, name: string, source = "NSW", overrides: Record<string, string> = {}): Promise<Response<T>> {
  const response = await request.get(`/api/data/${name}`, {
    params: { source, from: "2020-01-01", to: "2024-12-31", datasetVersion, batchId, ...overrides },
  });
  expect(response.ok()).toBe(true);
  const body = await response.json() as Response<T>;
  expect(body.meta).toMatchObject({ demo: false, source, datasetVersion, batchId });
  expect(JSON.stringify(body)).not.toMatch(/demo-v1|demo-(?:nsw|vic|qld)|\/Users\//);
  return body;
}

test("official APIs preserve one verified batch, actual monthly counts and source-specific totals", async ({ request }) => {
  const metadataResponse = await request.get("/api/data/metadata");
  expect(metadataResponse.ok()).toBe(true);
  const metadata = await metadataResponse.json() as Dataset[];
  expect(metadata.map((row) => row.source)).toEqual(["NSW", "VIC", "QLD"]);
  for (const row of metadata) expect(row).toMatchObject({ demo: false, version: datasetVersion, batchId });
  const evidenceResponse = await request.get("/api/data/evidence");
  expect(evidenceResponse.ok()).toBe(true);
  const evidence = await evidenceResponse.json();
  expect(evidence).toMatchObject({ demo: false, batchId, version: datasetVersion, publicationStatus: "succeeded" });
  expect(evidence.evidenceHashes["reader-results.json"]).toBe("fed5e2ea8736ce5db17fbdf1227cc4e6cafed2ec8fa3937956c218542e134e8d");
  expect(evidence.inputs).toHaveLength(7);
  expect(evidence.inputs.reduce((sum: number, row: { rawCount: number }) => sum + row.rawCount, 0)).toBe(2118028);
  expect(evidence.qa).toContainEqual({ check: "QA07_LOCATION", status: "limited", violations: 230876 });
  expect(JSON.stringify(evidence)).not.toContain("/Users/");

  for (const source of ["NSW", "VIC", "QLD"] as const) {
    const overview = await report<Overview>(request, "overview", source);
    expect(overview.meta.availability).toBe("available");
    expect([overview.data.crashes.value, overview.data.fatalCrashes.value, overview.data.livesLost.value, overview.data.casualties.value]).toEqual(totals[source]);
    const months = await report<TimePoint[]>(request, "timeseries", source, { granularity: "monthly" });
    expect(months.data).toHaveLength(60);
    expect(months.data.map((row) => row.period)).toEqual(Array.from({ length: 60 }, (_, index) => `${2020 + Math.floor(index / 12)}-${String(index % 12 + 1).padStart(2, "0")}`));
    for (const [index, key] of (["crashes", "fatalCrashes", "livesLost", "casualties"] as const).entries()) {
      expect(months.data.reduce((sum, row) => sum + row[key]!, 0)).toBe(totals[source][index]);
    }
  }
  const all = await report<Overview>(request, "overview", "All");
  expect(all.data.crashes.value).toBeNull();
  expect(all.data.crashes.availability).toBe("unsupported");
  expect(all.data.crashes.bySource?.map((row) => row.value)).toEqual([92082, 72170, 66624]);
  const halfYear = await report<Overview>(request, "overview", "QLD", { from: "2024-01-01", to: "2024-06-30" });
  expect([halfYear.data.crashes.value, halfYear.data.fatalCrashes.value, halfYear.data.livesLost.value, halfYear.data.casualties.value]).toEqual([7030, 131, 145, 9253]);
});

test("severity has measured full-period categories and never fabricates partial-period counts", async ({ request }) => {
  const counts = { NSW: [1388, 15483, 26115, 29507, 19589], VIC: [1182, 24401, 46584, 3], QLD: [1304, 31922, 22730, 10668] };
  for (const source of ["NSW", "VIC", "QLD"] as const) {
    const full = await report<Severity[]>(request, "severity", source);
    expect(full.meta.availability).toBe("available");
    expect(full.data.map((row) => row.count)).toEqual(counts[source]);
    const partial = await report<Severity[]>(request, "severity", source, { from: "2024-01-01", to: "2024-06-30" });
    expect(partial.meta.availability).toBe("unsupported");
    expect(partial.data).toEqual([]);
    expect(partial.meta.reason).toContain("2020–2024");
  }
});

test("maps expose real LGA aggregates while no crash records or coordinates are invented", async ({ request }) => {
  const country = await report<MapData>(request, "map", "All");
  expect(country.data.level).toBe("country");
  expect(country.data.regions).toEqual([]);
  expect(country.data.states?.filter((row) => row.available).map((row) => [row.source, row.count])).toEqual([["NSW", 92082], ["VIC", 72170], ["QLD", 66624]]);
  expect(country.data.states?.filter((row) => !row.available).every((row) => row.count === undefined)).toBe(true);
  for (const source of ["NSW", "VIC", "QLD"] as const) {
    const map = await report<MapData>(request, "map", source);
    expect(map.meta.availability).toBe("available");
    expect(map.data).toMatchObject({ level: "state", regionMode: "lga", illustrationOnly: false });
    expect(map.data.regions.length).toBeGreaterThan(70);
    expect(map.data.coverage!.matched + map.data.coverage!.unmatched).toBe(totals[source][0]);
    expect(map.data.regions.every(r => r.coordinates === undefined)).toBe(true);
    const records = await report<Records>(request, "records", source);
    expect(records.meta.availability).toBe("unsupported");
    expect(records.data.rows).toEqual([]);
    expect(records.data.total).toBe(0);
    expect(records.data.sampleOnly).toBe(false);
    expect(records.data.aggregateCount).toBe(totals[source][0]);
  }
});

test("data API rejects invalid filters and never falls back for an unknown batch", async ({ request }) => {
  const invalidFilters: Record<string, string>[] = [
    { source: "SA" },
    { from: "2024-02-30" },
    { from: "2024-01-02" },
    { to: "2024-06-29" },
    { from: "2024-12-01", to: "2024-01-31" },
  ];
  for (const params of invalidFilters) {
    const response = await request.get("/api/data/overview", { params });
    expect(response.status()).toBe(400);
    expect(await response.json()).toHaveProperty("error");
  }
  const badGranularity = await request.get("/api/data/timeseries", { params: { granularity: "daily" } });
  expect(badGranularity.status()).toBe(400);
  expect((await request.get("/api/data/not-a-report")).status()).toBe(404);
  expect((await request.post("/api/data/overview")).status()).toBe(405);

  const wrongBatchResponse = await request.get("/api/data/overview", {
    params: { source: "NSW", from: "2020-01-01", to: "2024-12-31", datasetVersion, batchId: "unknown-batch" },
  });
  expect(wrongBatchResponse.ok()).toBe(true);
  const wrongBatch = await wrongBatchResponse.json() as Response<Overview>;
  expect(wrongBatch.meta).toMatchObject({ demo: false, batchId: "unknown-batch", availability: "unsupported" });
  for (const key of ["crashes", "fatalCrashes", "livesLost", "casualties"] as const) {
    expect(wrongBatch.data[key]).toMatchObject({ value: null, availability: "unsupported" });
  }
});
