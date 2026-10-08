import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { mkdtempSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { configuredModel } from '../src/server/agent/runtime';
import { routeModel } from '../src/server/agent/model-routing';
import { createModelAudit } from '../src/server/agent/model-audit';
import { ModelBudgetError, modelBudgetView } from '../src/server/agent/model-budget';

/** Uses the installed SDK and production configuredModel options. Only its
 * endpoint is replaced by this owned loopback server, with a dummy credential.
 * No provider, gateway or real model is reached, including on failure/retry. */
async function fixture(surface: 'studio' | 'ask', statuses: number[]) {
  const bodies: { model: string; reasoning?: { effort: string } }[] = [];
  const retryHeaders: string[] = [];
  const server = createServer(async (request, response) => {
    assert.equal(request.url, '/v1/responses');
    assert.equal(request.headers.authorization, 'Bearer local-transport-fixture');
    let bytes = '';
    for await (const chunk of request) bytes += chunk;
    bodies.push(JSON.parse(bytes));
    retryHeaders.push(String(request.headers['x-stainless-retry-count']));
    const status = statuses[Math.min(bodies.length - 1, statuses.length - 1)];
    response.writeHead(status, { 'content-type': 'application/json', 'retry-after-ms': '1' });
    response.end(JSON.stringify(status === 200 ? {
      id: 'local-response', object: 'response', model: bodies.at(-1)!.model,
      status: 'completed', output: [],
      usage: { input_tokens: 9, output_tokens: 3, total_tokens: 12,
        input_tokens_details: { cached_tokens: 2 }, output_tokens_details: { reasoning_tokens: 1 } },
    } : { error: { message: 'Controlled loopback failure', type: 'fixture_error' } }));
  });
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  assert.ok(address && typeof address !== 'string');
  const root = mkdtempSync(join(tmpdir(), 'arsia-studio-transport-'));
  const route = routeModel({ surface, message: 'Show crash counts', source: 'NSW' });
  const oldKey = process.env.OPENAI_API_KEY, oldTest = process.env.NODE_TEST_CONTEXT;
  let config: ReturnType<typeof configuredModel>;
  try {
    process.env.OPENAI_API_KEY = 'local-transport-fixture';
    // The normal no-model test guard is lifted only during object construction.
    // No operation is called until the object has an owned loopback-only URL.
    delete process.env.NODE_TEST_CONTEXT;
    config = configuredModel(route);
  } finally {
    if (oldKey === undefined) delete process.env.OPENAI_API_KEY; else process.env.OPENAI_API_KEY = oldKey;
    if (oldTest === undefined) delete process.env.NODE_TEST_CONTEXT; else process.env.NODE_TEST_CONTEXT = oldTest;
  }
  const client = config.client.withOptions({ baseURL: `http://127.0.0.1:${address.port}/v1` });
  const audit = await createModelAudit(route, surface, root, 'controlled-task');
  async function request() {
    await audit.request('controlled-request');
    try {
      const response = await client.responses.create({ model: config.model, input: 'Fixture only',
        reasoning: { effort: config.reasoningEffort }, max_output_tokens: 64 });
      await audit.response({ id: response.id, requestId: 'controlled-request', model: response.model,
        status: response.status ?? 'unknown', usage: response.usage ?? undefined });
      await audit.finish('completed');
    } catch (error) {
      // Exactly the runner's audit-finalization semantics: no receipt stays unknown.
      await audit.finish('failed');
      throw error;
    }
  }
  return { request, root, route, bodies, retryHeaders, async close() {
    await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
    rmSync(root, { recursive: true, force: true });
  } };
}

for (const status of [503, 429]) test(`Studio SDK HTTP ${status} has one admitted transmission and unknown usage gates the next task`, async () => {
  const f = await fixture('studio', [status]);
  try {
    await assert.rejects(f.request());
    const view = modelBudgetView(f.root);
    console.log(JSON.stringify({ fixture: 'loopback-no-model', status, transports: f.bodies.length,
      admitted: view.totals.requests, usageComplete: view.usageComplete, retryHeaders: f.retryHeaders }));
    assert.equal(f.bodies.length, 1, 'SDK must not hide a second transmission behind one admission');
    assert.deepEqual(f.retryHeaders, ['0']);
    assert.equal(view.totals.requests, 1);
    assert.equal(view.totals.unknownRequests, 1);
    assert.equal(view.usageComplete, false);
    const next = await createModelAudit(f.route, 'studio', f.root, 'different-study');
    await assert.rejects(next.request('next-request'), error => error instanceof ModelBudgetError && error.code === 'MODEL_USAGE_UNKNOWN');
    assert.equal(modelBudgetView(f.root).totals.requests, 1);
  } finally { await f.close(); }
});

test('a potential SDK retry success cannot conceal the first failed Studio transmission', async () => {
  const f = await fixture('studio', [503, 200]);
  try {
    let failure: unknown;
    try { await f.request(); } catch (error) { failure = error; }
    const view = modelBudgetView(f.root);
    console.log(JSON.stringify({ fixture: 'loopback-no-model', scenario: 'failure-then-success',
      transports: f.bodies.length, failed: Boolean(failure), usageComplete: view.usageComplete,
      reportedInput: view.totals.reportedInput, unknownRequests: view.totals.unknownRequests }));
    assert.ok(failure, 'the host must observe the failed request rather than a hidden retry result');
    assert.equal(f.bodies.length, 1);
    assert.equal(view.totals.unknownRequests, 1);
    assert.equal(view.usageComplete, false);
    assert.equal(view.totals.reportedInput, 0, 'reported subtotal is empty; unknown usage is not settled as zero');
  } finally { await f.close(); }
});

for (const surface of ['studio', 'ask'] as const) test(`${surface} SDK success preserves routing, high reasoning and exact receipt accounting`, async () => {
  const f = await fixture(surface, [200]);
  try {
    await f.request();
    assert.equal(f.bodies.length, 1);
    assert.equal(f.bodies[0].model, surface === 'studio' ? 'gpt-6.1-sol' : 'gpt-5.6-terra');
    assert.equal(f.bodies[0].reasoning?.effort, 'high');
    const view = modelBudgetView(f.root);
    assert.equal(view.totals.requests, 1);
    assert.equal(view.totals.reportedInput, 9);
    assert.equal(view.totals.reportedCachedInput, 2);
    assert.equal(view.totals.reportedOutput, 3);
    assert.equal(view.totals.unknownRequests, 0);
    assert.equal(view.usageComplete, true);
  } finally { await f.close(); }
});
