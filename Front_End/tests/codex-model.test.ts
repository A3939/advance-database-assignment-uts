import { test } from "node:test";
import assert from "node:assert/strict";
import { codexModelRequest } from "../src/server/imports/codex-model";

test("Codex's additional_tools input is preserved and policy overrides are rejected", () => {
  const input = [{ type: "additional_tools", role: "developer", tools: [] }];
  const result = codexModelRequest({ model: "gpt-6.1-sol", stream: true, input,
    store: true, background: true, reasoning: { effort: "low" }, max_output_tokens: 1,
    callback_url: "https://invalid.example", authorization: "not forwarded" });
  assert.deepEqual(result.input, input);
  assert.equal(result.store, false);
  assert.deepEqual(result.reasoning, { effort: "high", summary: "auto" });
  assert.equal(result.max_output_tokens, 24000);
  assert.equal("authorization" in result, false);
  assert.equal("callback_url" in result, false);
  assert.equal("background" in result, false);
});

test("Codex transport requires the selected model and streaming protocol", () => {
  for (const body of [null, {}, { model: "gpt-5.6-terra", stream: true, input: [] },
    { model: "gpt-6.1-sol", stream: false, input: [] }, { model: "gpt-6.1-sol", stream: true, input: [], tools: {} }])
    assert.throws(() => codexModelRequest(body));
});

test("Task transport cannot add hosted execution, remote MCP or web access", () => {
  for (const type of ["mcp", "web_search", "code_interpreter"]) {
    assert.throws(() => codexModelRequest({ model: "gpt-6.1-sol", stream: true, input: [], tools: [{ type }] }));
    assert.throws(() => codexModelRequest({ model: "gpt-6.1-sol", stream: true,
      input: [{ type: "additional_tools", tools: [{ type: "namespace", tools: [{ type }] }] }] }));
  }
});

test("Compaction preserves native conversation items and cannot redirect the provider", async () => {
  const { codexCompactionRequest } = await import("../src/server/imports/codex-model");
  const input = [{ type: "message", role: "user", content: "saved task" }];
  assert.deepEqual(codexCompactionRequest({ model: "gpt-6.1-sol", input, url: "https://invalid", store: true }),
    { model: "gpt-6.1-sol", input });
  assert.throws(() => codexCompactionRequest({ model: "gpt-5.6-terra", input }));
});

test('an owned task cap preserves its lower remaining output allowance', () => {
  const input = {model:'gpt-6.1-sol',stream:true,input:[],max_output_tokens:730};
  assert.equal(codexModelRequest(input,12000).max_output_tokens,730);
  assert.equal(codexModelRequest({...input,max_output_tokens:24000},12000).max_output_tokens,12000);
  for (const cap of [0,-1,24001,NaN]) assert.throws(()=>codexModelRequest(input,cap));
  assert.throws(()=>codexModelRequest({...input,max_output_tokens:0},12000));
});
