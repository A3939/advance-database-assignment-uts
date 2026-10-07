import test from "node:test";
import assert from "node:assert/strict";
import { setImmediate } from "node:timers/promises";
import { httpProvider } from "../src/services/http-provider";
import { DEFAULT_FILTERS } from "../src/services/config";

// Exercise the actual public HTTP entry, including JSON body reads. No server,
// database or model is involved; only the network boundary is controlled.
for (const phase of ["headers", "body"] as const) {
  test(`a stalled ${phase} read expires instead of leaving Spatial loading forever`, async (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    const caller = new AbortController();
    t.after(() => caller.abort());
    let transportSignal: AbortSignal | undefined;
    t.mock.method(globalThis, "fetch", async (_url: string, init: RequestInit) => {
      transportSignal = init.signal as AbortSignal;
      // Deliberately ignores cancellation: the UI deadline must still settle.
      if (phase === "headers") return new Promise(() => {});
      return { ok: true, json: () => new Promise(() => {}) };
    });
    let failure: unknown;
    void httpProvider.getMapData(DEFAULT_FILTERS, caller.signal).catch(error => { failure = error; });
    await setImmediate();
    t.mock.timers.tick(20_001);
    await setImmediate();
    assert.equal((failure as Error | undefined)?.name, "TimeoutError");
    assert.equal(transportSignal?.aborted, true, "Expired transport must be cancelled");
    assert.equal(caller.signal.aborted, false, "A timeout must not cancel its owner's next selection");
  });
}

test("cancelling an old selection settles promptly and preserves the cancellation reason", async (t) => {
  const caller = new AbortController();
  let signal: AbortSignal | undefined;
  t.mock.method(globalThis, "fetch", async (_url: string, init: RequestInit) => {
    signal = init.signal as AbortSignal;
    return new Promise(() => {});
  });
  const pending = httpProvider.getMapData(DEFAULT_FILTERS, caller.signal);
  const reason = new DOMException("Selection replaced", "AbortError");
  caller.abort(reason);
  // Explicit settlement check also catches a transport which ignores abort.
  let failure: unknown;
  void pending.catch(error => { failure = error; });
  await setImmediate();
  assert.equal(failure, reason);
  assert.equal(signal?.aborted, true);
});

test("an already cancelled selection sends no request", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => new Response("{}"));
  const caller = new AbortController();
  caller.abort();
  await assert.rejects(httpProvider.getMapData(DEFAULT_FILTERS, caller.signal), { name: "AbortError" });
  assert.equal(fetch.mock.callCount(), 0);
});

test("a fresh retry succeeds after timeout without automatic retries or filter substitution", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const calls: string[] = [];
  const payload = { data: { regions: [{ id: "area-x", count: 12 }] } };
  t.mock.method(globalThis, "fetch", async (url: string) => {
    calls.push(url);
    return calls.length === 1 ? new Promise(() => {}) : Response.json(payload);
  });
  const filters = { ...DEFAULT_FILTERS, source: "VIC" as const, regionId: "area-x" };
  let failure: unknown;
  void httpProvider.getMapData(filters).catch(error => { failure = error; });
  t.mock.timers.tick(20_001);
  await setImmediate();
  assert.equal((failure as Error | undefined)?.name, "TimeoutError");
  assert.equal(calls.length, 1, "No hidden retry");
  assert.deepEqual(await httpProvider.getMapData(filters), payload);
  assert.equal(calls[0], calls[1]);
  const url = new URL(calls[1], "http://localhost");
  for (const [key, value] of Object.entries({ source: filters.source, regionId: filters.regionId,
    from: filters.dateRange.from, to: filters.dateRange.to,
    datasetVersion: filters.datasetVersion, batchId: filters.batchId }))
    assert.equal(url.searchParams.get(key), value);
});

test("successful reads clear their timers and do not abort completed transport", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let signal: AbortSignal | undefined;
  t.mock.method(globalThis, "fetch", async (_url: string, init: RequestInit) => {
    signal = init.signal as AbortSignal;
    return Response.json({ data: [] });
  });
  await httpProvider.getMapData(DEFAULT_FILTERS);
  t.mock.timers.tick(20_001);
  assert.equal(signal?.aborted, false);
});

test("HTTP failure and malformed JSON remain failures, never empty data", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => new Response("unavailable", { status: 503 }));
  await assert.rejects(httpProvider.getMapData(DEFAULT_FILTERS), /503/);
  fetch.mock.mockImplementation(async () => new Response("not JSON"));
  await assert.rejects(httpProvider.getMapData(DEFAULT_FILTERS), { name: "SyntaxError" });
  assert.equal(fetch.mock.callCount(), 2);
});
