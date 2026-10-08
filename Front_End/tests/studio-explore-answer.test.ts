import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { StudioStore, uuid } from "../src/server/studio/store";
import { ResearchCollector } from "../src/server/studio/collector";
import { evidenceReference, resultHash, validateStudyReport } from "../src/server/studio/research-contract";
import { selectReportMaterials, exportStudyProjection } from "../src/server/studio/report-selection";
import { renderStudyReport } from "../src/server/studio/report-renderer";
import { saveResource } from "../src/server/studio/resources";
import { DEFAULT_FILTERS } from "../src/services/config";
import type { ResearchRun, Study } from "../src/services/studio-contracts";

// Only in-memory collector events are supplied here. No model or provider runs.
const context = { filters: DEFAULT_FILTERS, metric: "crashes" as const, notes: "PRIVATE_CONTEXT", references: "PRIVATE_REFERENCE" };
function fixture() {
  const dir = mkdtempSync(join(tmpdir(), "arsia-explore-answer-"));
  const store = new StudioStore(join(dir, "research.sqlite"));
  return { store, close() { store.close(); rmSync(dir, { recursive: true, force: true }); } };
}
function act(store: StudioStore, study: Study, action: Record<string, unknown>) {
  return store.action(study.id, { ...action, revision: study.revision });
}
async function answer(store: StudioStore, study: Study, text = "Compare definitions before comparing sources.", evidence = false) {
  const begun = store.beginRun(study.id, uuid(), "Explicit zero-model answer fixture", false, undefined, { mode: "explore" });
  const collector = new ResearchCollector(store, study.id, begun.run);
  if (evidence) {
    await collector.accept({ type: "evidence", evidence: { id: "E1", title: "Bound fixture evidence", description: "Synthetic host event for contract verification only", result: { value: 17 }, query: { tool: "workspace_query", parameters: {}, requestedContext: { page: "/studio", filters: context.filters }, assurance: { parameters: "validated", execution: "returned", claims: "not_automatically_verified" } } } });
    await collector.accept({ type: "evidence", evidence: { id: "E2", title: "Unverified fixture evidence", description: "Must not acquire citation authority", result: { value: 23 } } });
  }
  await collector.accept({ type: "message", text, simulated: false });
  await collector.accept({ type: "done", model: "explicit-zero-model-fixture" });
  collector.persist();
  return store.get(study.id);
}
const copy = (run: ResearchRun) => ({ type: "answer_to_document", runId: run.id, attempt: run.attempt });

test("Explore answer transfer uses the saved answer and exact host evidence, without marking the narrative verified", async () => {
  const x = fixture();
  try {
    let s = await answer(x.store, x.store.create("Answer provenance", context), "Recorded fixture value: 17 [E1].", true);
    const run = structuredClone(s.runs[0]);
    s = act(x.store, s, { type: "block_add", kind: "text", text: "Later paragraph" });
    const revision = s.revision;
    s = act(x.store, s, { ...copy(run), afterId: null });
    assert.equal(s.revision, revision + 1);
    assert.equal(s.report[0].text, run.answer);
    assert.equal(s.report[0].kind, "text");
    assert.deepEqual(s.report[0].citations, [evidenceReference(s, run.id, "E1")]);
    assert.deepEqual(s.report[0].answerSource, { runId: run.id, attempt: run.attempt, answerHash: resultHash(run.answer) });
    assert.equal(s.report[1].text, "Later paragraph");
    assert.deepEqual(s.runs[0], run);
    assert.deepEqual(validateStudyReport(s), s.report);
    const selection = selectReportMaterials(s);
    assert.deepEqual([...selection.evidenceIds.get(run.id)!], ["E1"]);
    const report = renderStudyReport(s);
    assert.match(report.html, /AI draft/);
    assert.match(report.html, /review/i);
    assert.match(report.html, /Sources: \[1\] E1/);
    assert.doesNotMatch(report.html, /Unverified fixture evidence|PRIVATE_CONTEXT|PRIVATE_REFERENCE/);
  } finally { x.close(); }
});

test("knowledge-only answer remains an unverified draft and retains its source identity after edits and export", async () => {
  const x = fixture();
  try {
    let s = await answer(x.store, x.store.create("Knowledge draft", context));
    s = act(x.store, s, copy(s.runs[0]));
    const original = structuredClone(s.report[0]);
    assert.deepEqual(original.citations, []);
    s = act(x.store, s, { type: "block_edit", id: original.id, text: "My edited interpretation." });
    assert.deepEqual(s.report[0].answerSource, original.answerSource);
    const selected = selectReportMaterials(s), exported = exportStudyProjection(s, selected);
    assert.equal(exported.runs[0].id, s.runs[0].id);
    assert.deepEqual(exported.runs[0].evidence, []);
    assert.equal(exported.report[0].answerSource?.attempt, 1);
    const report = renderStudyReport(s);
    assert.match(report.html, /No linked data evidence/);
    assert.match(report.markdown, /AI draft/);
    assert.ok(!JSON.stringify(exported).includes("PRIVATE_CONTEXT"));
    assert.deepEqual(x.store.get(s.id), s);
  } finally { x.close(); }
});

test("answer transfer rejects caller text, forged citations, wrong attempt, foreign run and stale revision without side effects", async () => {
  const x = fixture();
  try {
    let s = await answer(x.store, x.store.create("Owned", context));
    const foreign = await answer(x.store, x.store.create("Foreign", context));
    for (const change of [{ text: "Caller answer" }, { citations: [] }, { answerSource: {} }, { attempt: 0 }, { attempt: 1.5 }, { attempt: "1" }, { attempt: 2 }, { runId: foreign.runs[0].id }, { afterId: uuid() }]) {
      assert.throws(() => act(x.store, s, { ...copy(s.runs[0]), ...change }));
      assert.deepEqual(x.store.get(s.id), s);
    }
    const old = structuredClone(s);
    s = act(x.store, s, { type: "block_add", kind: "text", text: "Concurrent work" });
    assert.throws(() => x.store.action(s.id, { ...copy(s.runs[0]), revision: old.revision }), /changed/);
    assert.deepEqual(x.store.get(s.id), s);
  } finally { x.close(); }
});

test("resource saves, unfinished answers and structured report proposals cannot masquerade as completed conversation answers", async () => {
  const x = fixture();
  try {
    const createdResource = await saveResource(x.store, { requestId: uuid(), definitionId: "trend", context });
    const resource = x.store.get(createdResource.id);
    assert.throws(() => act(x.store, resource, copy(resource.runs[0])), /answer/i);
    assert.deepEqual(x.store.get(resource.id), resource);
    for (const status of ["running", "failed", "stopped", "interrupted"] as const) {
      const s = x.store.create(status, context), begun = x.store.beginRun(s.id, uuid(), "Partial question");
      begun.run.answer = "Partial answer";
      begun.run.status = status;
      x.store.updateRun(s.id, begun.run);
      const saved = x.store.get(s.id);
      assert.throws(() => act(x.store, saved, copy(saved.runs[0])), /completed/i);
      assert.deepEqual(x.store.get(s.id), saved);
    }
    let s = await answer(x.store, x.store.create("Empty completed answer", context), "  ");
    assert.throws(() => act(x.store, s, copy(s.runs[0])), /answer/i);
    assert.deepEqual(x.store.get(s.id), s);
    for (const mode of ["draft", "revise"] as const) {
      s = x.store.create(mode, context);
      const begun = x.store.beginRun(s.id, uuid(), "Structured writing request", false, undefined, { mode });
      begun.run.answer = "Draft proposal description";
      begun.run.status = "complete";
      x.store.updateRun(s.id, begun.run);
      s = x.store.get(s.id);
      assert.throws(() => act(x.store, s, copy(s.runs[0])), /answer/i);
      assert.deepEqual(x.store.get(s.id), s);
    }
  } finally { x.close(); }
});

test("retry attempts and source hash changes cannot inherit an older answer binding", async () => {
  const x = fixture();
  try {
    const created = x.store.create("Retry identity", context);
    const first = x.store.beginRun(created.id, uuid(), "Try answer");
    first.run.status = "failed";
    first.run.answer = "Old partial answer";
    x.store.updateRun(created.id, first.run);
    const retry = x.store.beginRun(created.id, uuid(), "Retry answer", false, first.run.id);
    const collector = new ResearchCollector(x.store, created.id, retry.run);
    await collector.accept({ type: "message", text: "New completed answer", simulated: false });
    await collector.accept({ type: "done", model: "explicit-zero-model-fixture" });
    collector.persist();
    let s = x.store.get(created.id);
    assert.throws(() => act(x.store, s, copy(first.run)), /attempt/i);
    assert.deepEqual(x.store.get(s.id), s);
    s = act(x.store, s, copy(s.runs[0]));
    assert.equal(s.report[0].answerSource?.attempt, 2);
    assert.equal(s.runs[0].previousAttempts[0].answer, "Old partial answer");
    for (const tamper of [(v: Study) => { v.runs[0].answer = "Replaced response"; }, (v: Study) => { v.runs[0].attempt += 1; }, (v: Study) => { v.report[0].answerSource!.answerHash = "0".repeat(64); }]) {
      const changed = structuredClone(s);
      tamper(changed);
      assert.throws(() => validateStudyReport(changed), /answer.*binding|answer.*changed/i);
    }
  } finally { x.close(); }
});

test("answer insertion obeys report capacity and strict replay revision without partial writes", async () => {
  const x = fixture();
  try {
    let s = await answer(x.store, x.store.create("Capacity", context));
    const request = { ...copy(s.runs[0]), revision: s.revision };
    s = x.store.action(s.id, request);
    assert.throws(() => x.store.action(s.id, request), /changed/);
    assert.equal(x.store.get(s.id).report.length, 1);
    for (let n = 1; n < 100; n++) s = act(x.store, s, { type: "block_add", kind: "text", text: "" });
    assert.throws(() => act(x.store, s, copy(s.runs[0])), /limit/);
    assert.deepEqual(x.store.get(s.id), s);
  } finally { x.close(); }
});
