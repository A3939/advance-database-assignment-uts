import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { StudioStore, contextValue, uuid } from "../src/server/studio/store";
import {
  ResearchCollector,
  researchHistory,
} from "../src/server/studio/collector";
import { exportStudy } from "../src/server/studio/export";
import { createStudy } from "../src/server/studio/create";
import { DEFAULT_FILTERS } from "../src/services/config";
import type { ResearchContext, Study } from "../src/services/studio-contracts";
import {
  createOfficialProvider,
  loadOfficialSnapshot,
} from "../src/server/official-data";
import { executeAnalysisTool } from "../src/server/agent/tools";
const context: ResearchContext = {
  filters: {
    ...DEFAULT_FILTERS,
    source: "NSW",
    dateRange: { from: "2024-01-01", to: "2024-12-31" },
  },
  metric: "crashes",
  notes: "Research note",
  references: "",
};
function setup() {
  const dir = mkdtempSync(join(tmpdir(), "arsia-studio-test-")),
    path = join(dir, "research.sqlite"),
    store = new StudioStore(path);
  return {
    dir,
    path,
    store,
    close: () => {
      store.close();
      rmSync(dir, { recursive: true, force: true });
    },
  };
}
function action(store: StudioStore, s: Study, a: Record<string, unknown>) {
  return store.action(s.id, { ...a, revision: store.get(s.id).revision });
}
async function completed(store: StudioStore, s: Study) {
  const { run } = store.beginRun(s.id, uuid(), "Compare 2024 with 2023");
  const snapshot = await loadOfficialSnapshot(),
    service = createOfficialProvider(snapshot);
  const args = { source: null, dateRange: null, baseline: null };
  const result = await executeAnalysisTool(
    "compare_periods",
    args,
    { page: "/studio", filters: s.context.filters },
    service,
    snapshot,
  );
  const collector = new ResearchCollector(store, s.id, run);
  await collector.accept({
    type: "evidence",
    evidence: {
      id: "E1",
      title: "Comparison",
      description: "Project snapshot",
      result,
      query: {
        tool: "compare_periods",
        parameters: args,
        requestedContext: { page: "/studio", filters: s.context.filters },
        validated: true,
      },
    },
  });
  await collector.accept({
    type: "message",
    text: "Crashes increased by 228 (1.22%), from 18,711 to 18,939. [E1]",
    simulated: false,
  });
  await collector.accept({ type: "done", model: "test" });
  return collector.persist();
}
test("Studio persists context, drafts, findings and report through a fresh Node process", async () => {
  const x = setup();
  try {
    let s = x.store.create("NSW 2024 changes", context);
    s = action(x.store, s, {
      type: "draft",
      text: "Continue with monthly contributions",
    });
    s = await completed(x.store, s);
    s = action(x.store, s, {
      type: "finding",
      kind: "Observation",
      title: "Observed increase",
      explanation: "228 additional crashes",
      runId: s.runs[0].id,
      evidenceIds: ["E1"],
    });
    s = action(x.store, s, {
      type: "block_add",
      kind: "finding",
      refId: s.findings[0].id,
    });
    const code = `const {StudioStore}=require('./src/server/studio/store.ts');const s=new StudioStore(process.argv[1]);console.log(JSON.stringify(s.get(process.argv[2])));s.close();`;
    const reopened = JSON.parse(
      execFileSync(
        process.execPath,
        ["--require", "tsx/cjs", "-e", code, x.path, s.id],
        { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
      ),
    );
    assert.equal(reopened.title, s.title);
    assert.equal(reopened.runs.length, 1);
    assert.equal(reopened.findings[0].evidenceIds[0], "E1");
    assert.equal(reopened.report.length, 1);
    assert.equal(reopened.context.filters.source, "NSW");
  } finally {
    x.close();
  }
});
test("Studio isolates scopes, rejects unavailable batches and preserves old result/version meanings", async () => {
  const x = setup();
  try {
    let a = await completed(x.store, x.store.create("A", context));
    const b = x.store.create("B", {
      ...context,
      filters: { ...context.filters, source: "VIC" },
    });
    a = action(x.store, a, {
      type: "context",
      context: {
        ...context,
        filters: {
          ...context.filters,
          dateRange: { from: "2023-01-01", to: "2023-12-31" },
        },
      },
    });
    assert.equal(a.runs[0].context.filters.dateRange.from, "2024-01-01");
    assert.equal(x.store.get(b.id).context.filters.source, "VIC");
    const version = x.store.versions(a.id)[0];
    assert.equal(version.context.filters.dateRange.from, "2024-01-01");
    assert.throws(
      () =>
        contextValue({
          ...context,
          filters: { ...context.filters, datasetVersion: "expired" },
        }),
      /not connected/,
    );
    assert.throws(
      () => action(x.store, b, { type: "restore", versionId: version.id }),
      /not found/,
    );
    a = action(x.store, a, { type: "restore", versionId: version.id });
    assert.equal(a.context.filters.dateRange.from, "2024-01-01");
    assert.equal(x.store.versions(a.id).length, 2); // Current restored revision needs no duplicate snapshot.
  } finally {
    x.close();
  }
});
test("Save errors are atomic; optimistic conflicts and invalid evidence/block references fail closed", async () => {
  const x = setup();
  try {
    let s = await completed(x.store, x.store.create("Study", context));
    const b = await completed(x.store, x.store.create("Other", context));
    assert.throws(
      () => x.store.action(s.id, { type: "rename", title: "bad", revision: 0 }),
      /changed/,
    );
    assert.throws(
      () =>
        action(x.store, s, {
          type: "finding",
          kind: "Observation",
          title: "wrong",
          explanation: "",
          runId: b.runs[0].id,
          evidenceIds: ["E1"],
        }),
      /completed results/,
    );
    assert.throws(
      () =>
        action(x.store, s, {
          type: "finding",
          kind: "Observation",
          title: "wrong",
          explanation: "",
          runId: s.runs[0].id,
          evidenceIds: ["E999"],
        }),
      /Invalid evidence/,
    );
    assert.throws(
      () =>
        action(x.store, s, {
          type: "block_add",
          kind: "chart",
          runId: s.runs[0].id,
          refId: "invented",
        }),
      /reference/,
    );
    s = action(x.store, s, {
      type: "finding",
      kind: "Observation",
      title: "Manual observation",
      explanation: "A proposition",
    });
    assert.deepEqual(s.findings[0].evidenceIds, []);
    assert.equal(s.findings[0].origin, "user");
    s = action(x.store, s, {
      type: "finding",
      id: s.findings[0].id,
      kind: "Hypothesis",
      title: "Revised proposition",
      explanation: "Not proven",
    });
    assert.equal(s.findings[0].edits[0].title, "Manual observation");
    x.store.db.exec("PRAGMA query_only=ON");
    assert.throws(() =>
      action(x.store, s, { type: "rename", title: "Cannot save" }),
    );
    assert.equal(x.store.get(s.id).title, "Study");
    x.store.db.exec("PRAGMA query_only=OFF");
  } finally {
    x.close();
  }
});
test("Run request IDs and retries are idempotent; interruption and attempt limits are explicit", () => {
  const x = setup();
  try {
    const s = x.store.create("Retry", context),
      key = uuid();
    let r = x.store.beginRun(s.id, key, "Question");
    assert.equal(x.store.beginRun(s.id, key, "Question").replay, true);
    assert.equal(x.store.get(s.id).runs.length, 1);
    r.run.status = "failed";
    r.run.answer = "Incomplete";
    x.store.updateRun(s.id, r.run);
    const retryKey = uuid();
    r = x.store.beginRun(s.id, retryKey, "Ignored", false, r.run.id);
    assert.equal(r.run.attempt, 2);
    assert.equal(r.run.previousAttempts.length, 1);
    assert.equal(
      x.store.beginRun(s.id, retryKey, "Ignored", false, r.run.id).replay,
      true,
    );
    assert.equal(x.store.get(s.id).runs.length, 1);
    x.store.db
      .prepare("UPDATE leases SET expires=0 WHERE run_id=?")
      .run(r.run.id);
    assert.equal(x.store.get(s.id).runs[0].status, "interrupted");
    r = x.store.beginRun(s.id, uuid(), "Retry", false, r.run.id);
    r.run.status = "stopped";
    x.store.updateRun(s.id, r.run);
    assert.throws(
      () => x.store.beginRun(s.id, uuid(), "Retry", false, r.run.id),
      /Retry limit/,
    );
  } finally {
    x.close();
  }
});
test("Research files outlive temporary URLs, reject cross-study IDs, and export values/provenance/code", async () => {
  const x = setup();
  try {
    let s = await completed(x.store, x.store.create("Export", context));
    const bytes = Buffer.from('print("computed output")\n');
    const saved = x.store.saveFile(s.id, s.runs[0].id, {
      artifact: {
        id: "a".repeat(48),
        name: "analysis.py",
        href: "/api/analysis/artifacts/expired",
        bytes: bytes.length,
        sha256: createHash("sha256").update(bytes).digest("hex"),
        kind: "py",
        expiresAt: "2000-01-01",
      },
      bytes,
      provenance: { context },
    });
    const other = x.store.create("Other", context);
    assert.throws(() => x.store.file(other.id, saved.id), /not found/);
    assert.throws(() => x.store.file(s.id, "../../.env.local"), /Invalid/);
    s = x.store.get(s.id);
    assert.equal(
      x.store.file(s.id, saved.id).bytes.toString(),
      bytes.toString(),
    );
    s = action(x.store, s, {
      type: "block_add",
      kind: "chart",
      runId: s.runs[0].id,
      refId: s.runs[0].views[0].id,
    });
    // Export is a selected-report projection, not an implicit backup of every
    // same-run file. This legacy fixture has no calculation-to-evidence binding.
    assert.ok(!exportStudy(x.store, s).includes(Buffer.from("computed output")));
    s = action(x.store, s, { type: "block_add", kind: "artifact", refId: saved.id });
    const zip = exportStudy(x.store, s),
      entries = new Map<string, string>();
    let pos = 0;
    while (zip.readUInt32LE(pos) === 0x04034b50) {
      const size = zip.readUInt32LE(pos + 18),
        nameSize = zip.readUInt16LE(pos + 26),
        extra = zip.readUInt16LE(pos + 28),
        name = zip.subarray(pos + 30, pos + 30 + nameSize).toString(),
        start = pos + 30 + nameSize + extra;
      entries.set(name, zip.subarray(start, start + size).toString());
      pos = start + size;
    }
    assert.ok(entries.has("report.md"));
    assert.ok(entries.has(`attachments/${saved.id}-analysis.py`));
    const manifest = JSON.parse(entries.get("manifest.json")!);
    assert.equal(manifest.study.runs[0].evidence[0].query.validated, true);
    assert.ok(
      [...entries].some(
        ([name, value]) => name.endsWith(".csv") && value.includes("18939"),
      ),
    );
    assert.ok(!zip.includes(Buffer.from("OPENAI_API_KEY")));
  } finally {
    x.close();
  }
});
test("Monthly contribution arithmetic reconciles with real annual change; no missing-year extrapolation", async () => {
  const snapshot = await loadOfficialSnapshot(),
    service = createOfficialProvider(snapshot),
    ctx = { page: "/studio", filters: context.filters };
  const query = async (from: string, to: string) =>
    JSON.parse(
      JSON.stringify(
        await executeAnalysisTool(
          "monthly_contributions",
          { source: null, dateRange: { from, to }, metric: "crashes" },
          ctx,
          service,
          snapshot,
        ),
      ),
    );
  const r = await query("2024-01-01", "2024-12-31");
  assert.equal(r.results[0].rows.length, 12);
  assert.equal(r.results[0].netChange, 228);
  assert.equal(
    r.results[0].rows.reduce(
      (sum: number, m: { difference: number }) => sum + m.difference,
      0,
    ),
    228,
  );
  assert.equal(r.baselineRange.from, "2023-01-01");
  const empty = await query("2020-01-01", "2020-12-31");
  assert.equal(empty.results[0].netChange, null);
  assert.equal(empty.results[0].availability, "no_results");
});
test("Follow-up history preserves historic scopes and excludes failed answers", async () => {
  const x = setup();
  try {
    let s = await completed(x.store, x.store.create("Conversation", context));
    s = action(x.store, s, {
      type: "context",
      context: { ...context, filters: { ...context.filters, source: "VIC" } },
    });
    const { run } = x.store.beginRun(s.id, uuid(), "Compare this source");
    const history = researchHistory(s, run);
    assert.equal(history.length, 2);
    assert.match(history[1].text, /NSW/);
    assert.equal(run.context.filters.source, "VIC");
  } finally {
    x.close();
  }
});

test("Ask AI imports only durable server receipts, deduplicates imports and rejects expired files", async () => {
  const x = setup();
  try {
    const source = await completed(
      x.store,
      x.store.create("Original", context),
    );
    const run = source.runs[0];
    const id = uuid();
    const receipt = {
      id,
      context: { page: "/", filters: context.filters },
      question: run.question,
      createdAt: new Date().toISOString(),
      events: [
        { type: "evidence" as const, evidence: run.evidence[0] },
        {
          type: "message" as const,
          text: run.answer,
          simulated: false as const,
        },
      ],
    };
    x.store.saveTransfer(receipt);
    const [a, b] = await Promise.all([
      createStudy(x.store, { transferId: id, answer: "Fabricated count: 999" }),
      createStudy(x.store, { transferId: id }),
    ]);
    assert.equal(a.id, b.id);
    assert.equal(a.runs[0].answer, run.answer);
    assert.equal(a.runs[0].origin, "ask-ai");
    assert.equal(a.runs[0].status, "complete");
    assert.equal((await createStudy(x.store, { transferId: id })).id, a.id);
    assert.equal(a.runs[0].evidence[0].query?.validated, true);
    const expiredId = uuid();
    x.store.saveTransfer({ ...receipt, id: expiredId });
    x.store.db
      .prepare("UPDATE transfers SET created=0 WHERE id=?")
      .run(expiredId);
    await assert.rejects(
      createStudy(x.store, { transferId: expiredId }),
      /expired/,
    );
    const fileId = uuid();
    x.store.saveTransfer({
      ...receipt,
      id: fileId,
      events: [
        ...receipt.events,
        {
          type: "artifact",
          artifact: {
            id: "a".repeat(48),
            name: "gone.csv",
            bytes: 1,
            kind: "csv",
            sha256: "0".repeat(64),
            href: "/api/analysis/artifacts/expired",
            expiresAt: "2000-01-01",
          },
        },
      ],
    });
    const count = x.store.list().length;
    await assert.rejects(
      createStudy(x.store, { transferId: fileId }),
      /attachment has expired/,
    );
    assert.equal(x.store.list().length, count);
  } finally {
    x.close();
  }
});
