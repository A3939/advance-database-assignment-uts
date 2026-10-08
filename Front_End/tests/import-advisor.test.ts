import test from "node:test";
import assert from "node:assert/strict";
import { advisoryInput, parseImportAdvice } from "../src/server/imports/advisor";
import type { LocalImportJob } from "../src/services/imports-contracts";

const job = {
  status: "needs_input", files: [{ path: "/private/raw/person.csv", payload: "private-person-detail" }],
  error: { message: "Need mapping", details: { password: "secret", samples: ["private-person-detail"],
    schemas: [{ filename: "events.csv", format: "csv", sheet: null, columns: ["ID", "YEAR"], rows: ["private-person-detail"] }] } },
} as unknown as LocalImportJob;

test("advisor receives only explicitly selected schema and user-provided definitions", () => {
  const result = advisoryInput(job, "Public source dictionary");
  assert.deepEqual(result, { schemas: [{ filename: "events.csv", format: "csv", sheet: null, columns: ["ID", "YEAR"] }], source_context: "Public source dictionary" });
  assert.doesNotMatch(JSON.stringify(result), /private-person-detail|\/private|secret|password/);
});
test("AI cannot override a native missing-file or policy blocker", () => {
  assert.throws(() => advisoryInput({ ...job, error: { message: "missing VIC files", details: { missing_roles: ["person"] } } }, ""), /cannot override/);
  assert.throws(() => advisoryInput({ ...job, status: "succeeded" }, ""), /needs source information/);
});
test("model approval is forcibly downgraded to a non-executable draft", () => {
  const result = parseImportAdvice(JSON.stringify({ summary: "Review this mapping", questions: ["What does severity mean?"], draft_profile_json: '{"confirmed":true,"profile_version":"unsafe","source_id":"wa"}' }), "test-model");
  assert.equal(result.draft_profile?.confirmed, false);
  assert.equal(result.draft_profile?.profile_version, "generic-v1");
  assert.equal(result.execution_allowed, false);
});
test("invalid and oversized model output is rejected", () => {
  assert.throws(() => parseImportAdvice("not JSON", "test"));
  assert.throws(() => parseImportAdvice("a".repeat(30001), "test"));
  assert.throws(() => parseImportAdvice(JSON.stringify({ summary: "x", questions: [1], draft_profile_json: "" }), "test"));
  assert.throws(() => parseImportAdvice(JSON.stringify({ summary: "x", questions: [], draft_profile_json: JSON.stringify({severity:{native_text:{Fatal:{code:"fatal",label:"Fatal",is_fatal_crash:true}}}}) }), "test"), /Severity must map/);
  assert.throws(() => parseImportAdvice(JSON.stringify({ summary: "x", questions: [], draft_profile_json: JSON.stringify({mapping:{severity:{Fatal:{code:"fatal",label:"Fatal",is_fatal_crash:true}}}}) }), "test"), /Mapping fields/);
});
