import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { StudioStore, uuid } from "../src/server/studio/store";
import { resourceRequest, saveResource } from "../src/server/studio/resources";
import { validateStudyReport } from "../src/server/studio/research-contract";
import { DEFAULT_FILTERS } from "../src/services/config";
import type { Study } from "../src/services/studio-contracts";

const context = { filters: DEFAULT_FILTERS, metric: "crashes" as const, notes: "", references: "" };
function setup() {
  const dir = mkdtempSync(join(tmpdir(), "arsia-canvas-store-"));
  const store = new StudioStore(join(dir, "research.sqlite"));
  return { store, close() { store.close(); rmSync(dir, { recursive: true, force: true }); } };
}
function act(store: StudioStore, study: Study, action: Record<string, unknown>) {
  return store.action(study.id, { ...action, revision: study.revision });
}

test("canvas inserts before, between and after existing blocks without changing their identities", () => {
  const x = setup();
  try {
    let s = x.store.create("Document order", context);
    s = act(x.store, s, { type: "block_add", kind: "text", text: "First" });
    const first = s.report[0].id;
    s = act(x.store, s, { type: "block_add", kind: "text", text: "Last" });
    const last = s.report[1].id;
    s = act(x.store, s, { type: "block_add", kind: "text", text: "Middle", afterId: first });
    s = act(x.store, s, { type: "block_add", kind: "section", text: "Heading", afterId: null });
    assert.deepEqual(s.report.map(b => b.text), ["Heading", "First", "Middle", "Last"]);
    assert.equal(s.report[1].id, first);
    assert.equal(s.report[3].id, last);
  } finally { x.close(); }
});

test("canvas chart and writing space commit together with validated resource binding in one revision", async () => {
  const x = setup();
  try {
    let s = await saveResource(x.store, { requestId: uuid(), definitionId: "trend", context });
    assert.equal(s.report.length, 0, "Legacy resource save remains save-only");
    s = act(x.store, s, { type: "block_add", kind: "text", text: "Existing conclusion" });
    const before = structuredClone(s);
    s = act(x.store, s, { type: "block_add", kind: "resource", runId: s.runs[0].id, refId: s.runs[0].resource!.id, withAnalysis: true, afterId: null });
    assert.deepEqual(s.report.map(b => b.kind), ["resource", "text", "text"]);
    assert.equal(s.report[1].text, "");
    assert.equal(s.report[2].id, before.report[0].id);
    assert.equal(s.revision, before.revision + 1);
    assert.match(s.report[0].resultHash!, /^[a-f0-9]{64}$/);
    assert.deepEqual(s.runs, before.runs);
    assert.deepEqual(validateStudyReport(s), s.report);
    assert.deepEqual(x.store.get(s.id), s);
  } finally { x.close(); }
});

test("canvas rejects stale revisions, foreign anchors and unbound results with no partial report or revision writes", async () => {
  const x = setup();
  try {
    let s = await saveResource(x.store, { requestId: uuid(), definitionId: "trend", context });
    let other = x.store.create("Other document", context);
    other = act(x.store, other, { type: "block_add", kind: "text", text: "Other anchor" });
    const base = { type: "block_add", kind: "resource", runId: s.runs[0].id, refId: s.runs[0].resource!.id, withAnalysis: true };
    const original = x.store.get(s.id);
    for (const invalid of [{ afterId: other.report[0].id }, { afterId: "wrong" }, { refId: uuid() }, { runId: uuid() }, { withAnalysis: "true" }, { kind: "text", runId: undefined, refId: undefined }]) {
      assert.throws(() => act(x.store, s, { ...base, ...invalid }));
      assert.deepEqual(x.store.get(s.id), original);
    }
    s = act(x.store, s, { type: "block_add", kind: "text", text: "Concurrent text" });
    assert.throws(() => x.store.action(s.id, { ...base, revision: original.revision }), /changed/);
    assert.deepEqual(x.store.get(s.id), s);
  } finally { x.close(); }
});

test("canvas counts both inserted blocks toward capacity and does not leave a figure without its writing space", async () => {
  const x = setup();
  try {
    let s = await saveResource(x.store, { requestId: uuid(), definitionId: "trend", context });
    for (let n = 0; n < 99; n++) s = act(x.store, s, { type: "block_add", kind: "text", text: "" });
    assert.throws(() => act(x.store, s, { type: "block_add", kind: "resource", runId: s.runs[0].id, refId: s.runs[0].resource!.id, withAnalysis: true }), /limit/);
    assert.deepEqual(x.store.get(s.id), s);
    s = act(x.store, s, { type: "block_add", kind: "text", text: "Last allowed block" });
    assert.equal(s.report.length, 100);
  } finally { x.close(); }
});

test("explicit resource document save is atomic, idempotent and bound to the requested insertion intent", async () => {
  const x = setup();
  try {
    const request = { requestId: uuid(), definitionId: "trend", context, document: {} };
    const [created, replay] = await Promise.all([saveResource(x.store, request), saveResource(x.store, request)]);
    assert.equal(created.id, replay.id);
    assert.equal(x.store.list().length, 1);
    assert.equal(replay.runs.length, 1);
    assert.deepEqual(replay.report.map(b => b.kind), ["resource", "text"]);
    assert.equal(replay.report[0].runId, replay.runs[0].id);
    assert.equal(replay.report[0].refId, replay.runs[0].resource!.id);
    const next = { requestId: uuid(), definitionId: "severity", context, target: { studyId: replay.id, revision: replay.revision }, document: { afterId: replay.report[0].id } };
    const added = await saveResource(x.store, next);
    assert.deepEqual(added.report.map(b => b.kind), ["resource", "resource", "text", "text"]);
    assert.equal(added.report[3].id, replay.report[1].id);
    assert.equal(added.revision, replay.revision + 1);
    const persisted = x.store.get(added.id);
    assert.equal((await saveResource(x.store, next)).revision, added.revision);
    await assert.rejects(() => saveResource(x.store, { ...next, document: { afterId: null } }), /already bound/);
    await assert.rejects(() => saveResource(x.store, { ...request, document: undefined }), /already bound/);
    assert.deepEqual(validateStudyReport(added), added.report);
    assert.deepEqual(x.store.get(added.id), persisted);
  } finally { x.close(); }
});

test("resource document failures do not persist studies, runs, blocks or request identities", async () => {
  const x = setup();
  try {
    const base = { requestId: uuid(), definitionId: "trend", context };
    for (const document of [null, { afterId: false }, { afterId: "invalid" }, { withAnalysis: false }, { verified: true }]) assert.throws(() => resourceRequest({ ...base, document }));
    await assert.rejects(() => saveResource(x.store, { ...base, document: { afterId: uuid() } }), /anchor/);
    assert.equal(x.store.list().length, 0);
    assert.equal(x.store.db.prepare("SELECT count(*) AS n FROM run_requests").get()!.n, 0);
    let s = x.store.create("Existing", context);
    s = act(x.store, s, { type: "block_add", kind: "text", text: "Keep this" });
    await assert.rejects(() => saveResource(x.store, { ...base, target: { studyId: s.id, revision: s.revision }, document: { afterId: uuid() } }), /anchor/);
    assert.deepEqual(x.store.get(s.id), s);
    await assert.rejects(() => saveResource(x.store, { ...base, target: { studyId: s.id, revision: s.revision - 1 }, document: {} }), /changed/);
    assert.deepEqual(x.store.get(s.id), s);
    assert.equal(x.store.db.prepare("SELECT count(*) AS n FROM run_requests").get()!.n, 0);
  } finally { x.close(); }
});

test("document title edits preserve study identity and metadata while synchronizing only the matching first title", () => {
  const x = setup();
  try {
    let s = x.store.create("Study name", context);
    s = act(x.store, s, { type: "report_template", metadata: { template: "full", language: "bilingual", title: "Original document", author: "Researcher", date: "2026-10-08" } });
    const before = structuredClone(s);
    s = act(x.store, s, { type: "report_title", title: "New document title" });
    assert.equal(s.title, before.title);
    assert.deepEqual(s.reportMeta, { ...before.reportMeta, title: "New document title" });
    assert.equal(s.report[0].text, "New document title");
    assert.deepEqual(s.report.slice(1), before.report.slice(1));
    s = act(x.store, s, { type: "block_edit", id: s.report[0].id, text: "Deliberate independent heading" });
    s = act(x.store, s, { type: "report_title", title: "Next title" });
    assert.equal(s.report[0].text, "Deliberate independent heading");
    for (const title of [undefined, null, "", " ", "x".repeat(121)]) {
      assert.throws(() => act(x.store, s, { type: "report_title", title }));
      assert.deepEqual(x.store.get(s.id), s);
    }
  } finally { x.close(); }
});

test("explicit blank templates retain section structure and historical placeholder templates remain unchanged", () => {
  const x = setup();
  try {
    let s = x.store.create("Blank writing template", context);
    s = act(x.store, s, { type: "report_template", metadata: { template: "brief", language: "en" } });
    const previous = structuredClone(s);
    assert.ok(s.report.filter(b => b.kind === "text").every(b => b.text));
    s = act(x.store, s, { type: "report_template", replace: true, blank: true, metadata: { template: "brief", language: "en" } });
    assert.deepEqual(s.report.map(b => b.kind), previous.report.map(b => b.kind));
    assert.ok(s.report.filter(b => b.kind === "text").every(b => b.text === ""));
    assert.deepEqual(s.report.filter(b => b.kind !== "text").map(b => b.text), previous.report.filter(b => b.kind !== "text").map(b => b.text));
    const backup = x.store.versions(s.id).find(v => v.label === "Before report template")!;
    assert.deepEqual(x.store.version(s.id, backup.id).report, previous.report);
  } finally { x.close(); }
});

test("document detail edits preserve the latest title and reject title-bearing or unknown metadata", () => {
  const x = setup();
  try {
    let s = x.store.create("Research name", context);
    s = act(x.store, s, { type: "report_title", title: "Current title" });
    s = act(x.store, s, { type: "report_details", metadata: { template: "full", language: "zh", author: "Author", date: "2026-10-08" } });
    assert.deepEqual(s.reportMeta, { contractVersion: 1, title: "Current title", template: "full", language: "zh", author: "Author", date: "2026-10-08" });
    assert.equal(s.title, "Research name");
    for (const metadata of [{ title: "Stale form title" }, { contractVersion: 1 }, { template: "unknown" }, { arbitrary: true }]) {
      assert.throws(() => act(x.store, s, { type: "report_details", metadata }));
      assert.deepEqual(x.store.get(s.id), s);
    }
  } finally { x.close(); }
});
