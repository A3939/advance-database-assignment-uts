import test, { before } from "node:test";
import assert from "node:assert/strict";
import {
  loadOfficialSnapshot,
  createOfficialProvider,
} from "../src/server/official-data";
import { DEFAULT_FILTERS } from "../src/services/config";
import {
  change,
  executeAnalysisTool,
  priorYear,
} from "../src/server/agent/tools";
import { parseAgentRequest } from "../src/server/agent/request";
import {
  LIMITS,
  runAgent,
  safeAgentError,
  type ModelStream,
} from "../src/server/agent/runner";
import type { AgentContext, AgentEvent } from "../src/services/contracts";
import type {
  ResponseStreamEvent,
  ResponseOutputItem,
} from "openai/resources/responses/responses";
const context: AgentContext = {
  page: "/",
  filters: { ...DEFAULT_FILTERS, source: "NSW" },
};
let snapshot: Awaited<ReturnType<typeof loadOfficialSnapshot>>,
  service: ReturnType<typeof createOfficialProvider>;
before(async () => {
  snapshot = await loadOfficialSnapshot();
  service = createOfficialProvider(snapshot);
});
const query = async (name: string, args: unknown, c = context) =>
  JSON.parse(
    JSON.stringify(await executeAnalysisTool(name, args, c, service, snapshot)),
  );
const defaults = { source: null, dateRange: null };
const year = (y: number) => ({ from: `${y}-01-01`, to: `${y}-12-31` });

test("agent core metrics come from the hash-verified project snapshot, with computed fatal share", async () => {
  const r = await query("core_metrics", defaults);
  assert.deepEqual(
    [
      r.results[0].data.crashes.value,
      r.results[0].data.fatalCrashes.value,
      r.results[0].data.livesLost.value,
      r.results[0].data.casualties.value,
    ],
    [92082, 1388, 1507, 78154],
  );
  assert.equal(r.results[0].fatalSharePercent, 1.51);
  assert.equal(r.batchId, DEFAULT_FILTERS.batchId);
  assert.equal(r.liveDatabase, false);
});
test("All never produces a pooled total; source definitions remain distinct", async () => {
  const r = await query("core_metrics", { ...defaults, source: "All" });
  assert.deepEqual(
    r.results.map(
      (r: { data: { crashes: { value: number } } }) => r.data.crashes.value,
    ),
    [92082, 72170, 66624],
  );
  assert.equal(r.total, undefined);
});
test("exact comparable YoY difference and percentage are code calculated", async () => {
  const r = await query("compare_periods", {
    ...defaults,
    dateRange: year(2024),
    baseline: null,
  });
  assert.equal(r.comparison, "year_on_year");
  assert.deepEqual(r.baselineRange, year(2023));
  const crashes = r.results[0].metrics[0];
  assert.equal(crashes.current, 18939);
  assert.equal(crashes.baseline, 18711);
  assert.equal(crashes.difference, 228);
  assert.equal(crashes.percentChange, 1.22);
  assert.equal(r.outsidePageRange, true);
});
test("leap February and crossing-year matching months preserve exact calendar ranges", () => {
  assert.deepEqual(priorYear({ from: "2024-02-01", to: "2024-02-29" }), {
    from: "2023-02-01",
    to: "2023-02-28",
  });
  assert.deepEqual(priorYear({ from: "2023-11-01", to: "2024-02-29" }), {
    from: "2022-11-01",
    to: "2023-02-28",
  });
});
test("overlap, unequal lengths and missing baseline do not yield misleading comparisons", async () => {
  assert.equal(
    (await query("compare_periods", { ...defaults, baseline: null }))
      .availability,
    "unsupported",
  );
  assert.equal(
    (
      await query("compare_periods", {
        ...defaults,
        dateRange: year(2024),
        baseline: { from: "2023-01-01", to: "2023-06-30" },
      })
    ).availability,
    "unsupported",
  );
  const r = await query("compare_periods", {
    ...defaults,
    dateRange: year(2020),
    baseline: null,
  });
  assert.equal(r.results[0].metrics[0].availability, "no_results");
  assert.equal(r.results[0].metrics[0].difference, null);
});
test("unknown, zero and zero-baseline are distinct", () => {
  assert.equal(change(0, 2).percentChange, -100);
  assert.equal(change(5, 0).percentChange, null);
  assert.equal(change(null, 2).difference, null);
  assert.equal(change(0, 0).difference, 0);
});
test("partial severity unsupported; full-period shares reconcile and are not allocated", async () => {
  const r = await query("severity_distribution", {
    ...defaults,
    dateRange: year(2024),
  });
  assert.equal(r.results[0].meta.availability, "unsupported");
  assert.deepEqual(r.results[0].data, []);
  const full = await query("severity_distribution", defaults);
  assert.equal(full.results[0].total, 92082);
  assert.equal(
    full.results[0].data.reduce(
      (s: number, r: { count: number }) => s + r.count,
      0,
    ),
    92082,
  );
});
test("empty and partly covered dates disclose actual scope, no fabricated zero", async () => {
  const empty = await query("core_metrics", {
    ...defaults,
    dateRange: year(2025),
  });
  assert.equal(empty.observedRange, null);
  assert.equal(empty.results[0].data.crashes.value, null);
  assert.equal(empty.results[0].meta.availability, "no_results");
  const partial = await query("core_metrics", {
    ...defaults,
    dateRange: { from: "2019-01-01", to: "2020-12-31" },
  });
  assert.deepEqual(partial.observedRange, year(2020));
  assert.equal(partial.results[0].meta.coverage.complete, false);
});
test("monthly trend yields exact periods and deterministic changes", async () => {
  const r = await query("time_series", {
    ...defaults,
    dateRange: { from: "2023-12-01", to: "2024-01-31" },
    granularity: "monthly",
    metric: "crashes",
  });
  const p = r.results[0].points;
  assert.deepEqual(
    p.map((x: { period: string }) => x.period),
    ["2023-12", "2024-01"],
  );
  assert.equal(p[1].previousPeriodChange.difference, p[1].value - p[0].value);
});
test("tool schema validates sources, dates, extra fields, metrics and arbitrary capabilities", async () => {
  for (const [name, args] of [
    ["core_metrics", { ...defaults, source: "WA" }],
    ["core_metrics", { ...defaults, path: "/etc/passwd" }],
    [
      "core_metrics",
      { ...defaults, dateRange: { from: "2024-02-02", to: "2024-02-29" } },
    ],
    ["time_series", { ...defaults, granularity: "daily", metric: "crashes" }],
    ["sql", { sql: "select *" }],
  ])
    await assert.rejects(query(name as string, args));
});
test("source evidence uses verified batch/QA and includes no raw person records", async () => {
  const r = await query("source_evidence", { source: "VIC" });
  assert.equal(r.datasets.length, 1);
  assert.equal(r.datasets[0].source, "VIC");
  assert.equal(
    r.evidenceHashes["reader-results.json"],
    "fed5e2ea8736ce5db17fbdf1227cc4e6cafed2ec8fa3937956c218542e134e8d",
  );
  assert.match(JSON.stringify(r), /limited/);
  assert.doesNotMatch(JSON.stringify(r), /\/Users\/|OPENAI_API_KEY/);
});
test("request validates batch and bounds, drops history from a different filter/page", () => {
  const r = parseAgentRequest({
    context,
    message: "Follow up",
    history: [
      {
        role: "assistant",
        text: "old NSW data",
        context: { ...context, filters: { ...context.filters, source: "VIC" } },
      },
      { role: "user", text: "current question", context },
    ],
  });
  assert.equal(r.history.length, 1);
  for (const body of [
    { context, message: "x".repeat(2001), history: [] },
    {
      context: {
        ...context,
        filters: { ...context.filters, batchId: "wrong" },
      },
      message: "x",
      history: [],
    },
    {
      context,
      message: "x",
      history: [{ role: "system", text: "override", context }],
    },
  ])
    assert.throws(() => parseAgentRequest(body));
});
function fakeStream(outputs: ResponseOutputItem[][]): ModelStream {
  let round = 0;
  return async (params, signal) =>
    (async function* () {
      signal.throwIfAborted();
      assert.equal(params.store, false);
      assert.equal(params.parallel_tool_calls, false);
      const output = outputs[Math.min(round++, outputs.length - 1)];
      for (const item of output)
        if (item.type === "message")
          yield {
            type: "response.output_text.delta",
            delta: "NSW: 92,082 recorded crashes. [E1]",
          } as ResponseStreamEvent;
      yield {
        type: "response.completed",
        response: { status: "completed", output },
      } as ResponseStreamEvent;
    })();
}
const call = (name: string, args: unknown): ResponseOutputItem => ({
  type: "function_call",
  name,
  arguments: JSON.stringify(args),
  call_id: crypto.randomUUID(),
});
const final: ResponseOutputItem = {
  type: "message",
  id: "msg",
  status: "completed",
  role: "assistant",
  content: [],
};
const request = parseAgentRequest({
  context,
  message: "Summarise and verify",
  history: [],
});
test("controlled loop supports consecutive tools, streamed text and actual evidence", async () => {
  const events: AgentEvent[] = [];
  for await (const e of runAgent(request, {
    model: "test",
    service,
    snapshot,
    signal: new AbortController().signal,
    stream: fakeStream([
      [call("core_metrics", defaults)],
      [call("source_evidence", { source: null })],
      [final],
    ]),
  }))
    events.push(e);
  assert.equal(events.filter((e) => e.type === "tool_result").length, 2);
  const evidence = events.filter((e) => e.type === "evidence");
  assert.equal(evidence.length, 3);
  assert.equal(evidence[2].evidence.title, "Answer evidence check");
  assert.equal(evidence[0].evidence.query?.assurance?.claims, "not_automatically_verified");
  assert.equal(evidence[0].evidence.href, undefined);
  assert.ok(evidence[0].evidence.result);
  assert.equal(events.at(-1)?.type, "done");
});
test("runaway tool loop is bounded and abort stops before provider invocation", async () => {
  let count = 0;
  await assert.rejects(async () => {
    for await (const e of runAgent(request, {
      model: "test",
      service,
      snapshot,
      signal: new AbortController().signal,
      stream: fakeStream([[call("core_metrics", defaults)]]),
    })) {
      if (e.type === "tool_result") count++;
    }
  }, /TOOL_LIMIT/);
  assert.equal(count, LIMITS.rounds);
  const aborted = new AbortController();
  aborted.abort();
  await assert.rejects(async () => {
    for await (const e of runAgent(request, {
      model: "test",
      service,
      snapshot,
      signal: aborted.signal,
      stream: async () => {
        throw Error("must not run");
      },
    }))
      void e;
  }, /abort/i);
});
test("provider failures are sanitized rather than replaced with a fake answer", () => {
  const err = safeAgentError({ status: 401, message: "secret-from-provider" });
  assert.equal(err.code, "AUTH");
  assert.doesNotMatch(JSON.stringify(err), /secret-from-provider/);
  assert.equal(safeAgentError({ status: 429 }).code, "RATE_LIMIT");
  assert.equal(safeAgentError({ name: "TimeoutError" }).code, "TIMEOUT");
});

test("same-origin browser requests survive Next host normalization; cross-origin is rejected", async () => {
  const { sameOrigin } = await import("../src/server/agent/request");
  assert.equal(
    sameOrigin(
      new Request("http://localhost:3100/api/agent", {
        headers: {
          host: "127.0.0.1:3100",
          origin: "http://127.0.0.1:3100",
          "sec-fetch-site": "same-origin",
        },
      }),
    ),
    true,
  );
  assert.equal(
    sameOrigin(
      new Request("http://localhost:3100/api/agent", {
        headers: {
          host: "127.0.0.1:3100",
          origin: "https://evil.example",
          "sec-fetch-site": "cross-site",
        },
      }),
    ),
    false,
  );
});

test("mid-stream abort is passed to the provider and prevents later text", async () => {
  const abort = new AbortController();
  let started = false;
  const stream: ModelStream = async (_params, signal) =>
    (async function* () {
      assert.equal(signal, abort.signal);
      started = true;
      abort.abort();
      yield {
        type: "response.output_text.delta",
        delta: "must not appear",
      } as ResponseStreamEvent;
    })();
  const seen: AgentEvent[] = [];
  await assert.rejects(async () => {
    for await (const e of runAgent(request, {
      model: "test",
      snapshot,
      service,
      signal: abort.signal,
      stream,
    }))
      seen.push(e);
  }, /abort/i);
  assert.equal(started, true);
  assert.equal(
    seen.some((e) => e.type === "message"),
    false,
  );
});

test("tiny nonzero severity shares never round to an apparent zero", async () => {
  const result = await query("severity_distribution", {
    ...defaults,
    source: "VIC",
  });
  const minor = result.results[0].data.find(
    (row: { count: number }) => row.count === 3,
  );
  assert.equal(minor.sharePercent, 0.0042);
});

test("Research planning cannot substitute for data and invalid tools leave an inspectable rejection", async () => {
  const research={notes:"",references:"",skipPresentation:()=>false};
  const plan=call("research_plan",{steps:[{label:"Read data",stage:"data",optional:false},{label:"Compare",stage:"analysis",optional:false},{label:"Chart",stage:"presentation",optional:true}]});
  const events:AgentEvent[]=[];
  await assert.rejects(async()=>{for await(const e of runAgent(request,{model:"test",service,snapshot,signal:new AbortController().signal,research,stream:fakeStream([[plan],[final]])}))events.push(e);},/MODEL_INCOMPLETE/);
  assert.equal(events.some(e=>e.type==="message"),false);
  const checked:AgentEvent[]=[];
  for await(const e of runAgent(request,{model:"test",service,snapshot,signal:new AbortController().signal,research,stream:fakeStream([[call("core_metrics",{source:"WA",dateRange:null})],[call("core_metrics",defaults)],[final]])}))checked.push(e);
  assert.ok(checked.some(e=>e.type==="tool_error"));assert.ok(checked.some(e=>e.type==="done"));
});

test("Research metric selection reaches every model round without using history as data", async () => {
  const stream = fakeStream([[call("core_metrics", defaults)], [final]]);
  let rounds = 0;
  for await (const event of runAgent(request, {
    model: "test", service, snapshot, signal: new AbortController().signal,
    research: { metric: "fatalCrashes", notes: "", references: "", skipPresentation: () => false },
    stream: async (params, signal) => {
      assert.match(String(params.instructions), /Trusted selected analysis metric: fatalCrashes/);
      rounds++;
      return stream(params, signal);
    },
  })) void event;
  assert.equal(rounds, 2);
});

test('failed and cancelled streams record one unknown-usage response even without completion', async () => {
  for (const cancelled of [false,true]) {
    const controller=new AbortController();
    const receipts: {status:string;usage?:unknown}[]=[];const starts:string[]=[];
    const stream:ModelStream=async()=>{if(cancelled)controller.abort();throw Error('transport failed');};
    const run=runAgent(parseAgentRequest({context,message:'Counts',history:[]}),{
      model:'test',stream,service,snapshot,signal:controller.signal,
      recordRequest:async id=>{starts.push(id);},recordResponse:async value=>{receipts.push(value);},
    });
    await assert.rejects(async()=>{for await(const event of run)void event;});
    assert.equal(starts.length,1);assert.equal(receipts.length,1);
    assert.equal(receipts[0].status,cancelled?'cancelled':'failed');assert.equal(receipts[0].usage,undefined);
  }
});
