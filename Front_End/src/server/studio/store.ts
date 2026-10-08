/** Local research records only. Official snapshots and databases are never written. */
import { DatabaseSync } from "node:sqlite";
import { randomUUID, createHash } from "node:crypto";
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import type {
  CompletedTransfer,
  ResearchContext,
  ResearchRun,
  Study,
  StudySummary,
  StudyVersion,
  ReportBlock,
  ResearchFinding,
  StudyArtifact,
  ResearchMode,
} from "../../services/studio-contracts";
import { parseAgentRequest } from "../agent/request";
import type { AnalysisArtifact } from "../../services/analysis-contracts";
import { object } from "../agent/tools";
import { bindReportBlock, evidenceReference, findingChecks, findingContentHash, isCompletedConversationAnswer, parseNumericClaims, reportHash, reportMetadata, reportTemplate, resultHash } from "./research-contract";

export class StudioError extends Error {
  constructor(
    message: string,
    public status = 400,
  ) {
    super(message);
  }
}
const fail = (message: string, status = 400): never => {
  throw new StudioError(message, status);
};
export const now = () => new Date().toISOString();
export const uuid = () => randomUUID();
export function validId(value: unknown): string {
  if (
    typeof value !== "string" ||
    !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(
      value,
    )
  )
    return fail("Invalid research ID.");
  return value;
}
export function textValue(value: unknown, max = 2000, empty = false): string {
  if (
    typeof value !== "string" ||
    value.length > max ||
    (!empty && !value.trim())
  )
    return fail(`Enter ${empty ? "0" : "1"}–${max} characters.`);
  return value;
}
export function contextValue(value: unknown): ResearchContext {
  const v = object(value);
  let filters;
  try {
    filters = parseAgentRequest({
      context: { page: "/studio", filters: v.filters },
      message: "Validate scope",
      history: [],
    }).context.filters;
  } catch {
    return fail(
      "This scope, dataset version or batch is not connected. Choose a supported whole-month range.",
    );
  }
  if (
    !["crashes", "fatalCrashes", "livesLost", "casualties"].includes(
      String(v.metric),
    )
  )
    return fail("Unknown research metric.");
  return {
    filters,
    metric: v.metric as ResearchContext["metric"],
    notes: textValue(v.notes ?? "", 6000, true),
    references: textValue(v.references ?? "", 10000, true),
  };
}
export const contextChanges = (
  a: ResearchContext,
  b: ResearchContext,
): string[] => {
  const changes: string[] = [];
  const fa = a.filters,
    fb = b.filters;
  if (fa.source !== fb.source)
    changes.push(`Source: ${fa.source} → ${fb.source}`);
  if (fa.regionId !== fb.regionId)
    changes.push(
      `Area: ${fa.regionId || "All areas"} → ${fb.regionId || "All areas"}`,
    );
  if (JSON.stringify(fa.dateRange) !== JSON.stringify(fb.dateRange))
    changes.push(
      `Dates: ${fa.dateRange.from} – ${fa.dateRange.to} → ${fb.dateRange.from} – ${fb.dateRange.to}`,
    );
  if (fa.datasetVersion !== fb.datasetVersion || fa.batchId !== fb.batchId)
    changes.push(
      `Dataset: ${fa.datasetVersion} / ${fa.batchId} → ${fb.datasetVersion} / ${fb.batchId}`,
    );
  if (a.metric !== b.metric) changes.push(`Metric: ${a.metric} → ${b.metric}`);
  if (a.notes !== b.notes || a.references !== b.references)
    changes.push("Research notes or reference text changed.");
  return changes;
};
const alive = (pid: number) => {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
};
const MAX_DOCUMENT = 8 * 1024 * 1024;
const MAX_STORAGE = 256 * 1024 * 1024;
/** One user insertion intent is one revision: its figure and writing space cannot split. */
function insertReportBlock(study: Study, block: ReportBlock, options: { afterId?: unknown; withAnalysis?: unknown } = {}) {
  if (options.withAnalysis !== undefined && typeof options.withAnalysis !== "boolean")
    fail("Invalid writing-space option.");
  if (options.withAnalysis && !["resource", "chart", "table"].includes(block.kind))
    fail("A writing space must follow a chart, table or saved resource.");
  let index = study.report.length;
  if (options.afterId === null) index = 0;
  else if (options.afterId !== undefined) {
    const anchor = validId(options.afterId);
    const found = study.report.findIndex(b => b.id === anchor);
    if (found < 0) fail("The insertion anchor is no longer in this report. Reload before inserting.", 409);
    index = found + 1;
  }
  const blocks = [bindReportBlock(study, block)];
  if (options.withAnalysis) blocks.push(bindReportBlock(study, { id: uuid(), kind: "text", text: "" }));
  if (study.report.length + blocks.length > 100) fail("Report block limit reached.");
  study.report.splice(index, 0, ...blocks);
}
export const STUDIO_SCHEMA_VERSION = 1;
export function studioCapacity(db: DatabaseSync, schemaVersion: number) {
  const row = db.prepare("SELECT (SELECT coalesce(sum(length(CAST(doc AS BLOB))),0) FROM studies) + (SELECT coalesce(sum(length(CAST(doc AS BLOB))),0) FROM versions) + (SELECT coalesce(sum(length(bytes)),0) FROM files) + (SELECT coalesce(sum(length(CAST(doc AS BLOB))),0) FROM transfers) AS n, (SELECT count(*) FROM studies) AS studies, (SELECT count(*) FROM versions) AS versions, (SELECT count(*) FROM transfers) AS transfers").get() as {n:number;studies:number;versions:number;transfers:number};
  return {usedBytes:row.n,limitBytes:MAX_STORAGE,documentLimitBytes:MAX_DOCUMENT,studyCount:row.studies,studyLimit:128,versionCount:row.versions,transferCount:row.transfers,schemaVersion,migrationRequired:schemaVersion<STUDIO_SCHEMA_VERSION};
}
function readDocument(doc: string): Study {
  const value = JSON.parse(doc);
  if (![0, 1].includes(value.schemaVersion ?? 0))
    fail("This study was written by a newer Studio version. Export the database before upgrading.", 409);
  return value;
}

export class StudioStore {
  db: DatabaseSync;
  private schemaVersion: number;
  constructor(path: string, connection?: DatabaseSync) {
    mkdirSync(dirname(path), { recursive: true, mode: 0o700 });
    this.db = connection || new DatabaseSync(path);
    this.schemaVersion = (this.db.prepare("PRAGMA user_version").get() as { user_version: number }).user_version;
    const existing = this.db.prepare("SELECT name FROM sqlite_master WHERE type='table' AND name='studies'").get();
    if (this.schemaVersion > STUDIO_SCHEMA_VERSION)
      fail("This Studio database needs a newer application version.", 409);
    // Legacy databases are readable but require an explicit, backed-up migration.
    if (existing && this.schemaVersion === 0) return;
    this.db
      .exec(`PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;
      CREATE TABLE IF NOT EXISTS studies(id TEXT PRIMARY KEY, doc TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY, study_id TEXT NOT NULL, label TEXT NOT NULL, created TEXT NOT NULL, doc TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS files(id TEXT PRIMARY KEY, study_id TEXT NOT NULL, bytes BLOB NOT NULL);
      CREATE TABLE IF NOT EXISTS leases(run_id TEXT PRIMARY KEY, study_id TEXT NOT NULL, pid INTEGER NOT NULL, expires INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS run_requests(study_id TEXT NOT NULL, request_id TEXT NOT NULL, run_id TEXT NOT NULL, PRIMARY KEY(study_id,request_id));
      CREATE TABLE IF NOT EXISTS transfers(id TEXT PRIMARY KEY, created INTEGER NOT NULL, study_id TEXT, doc TEXT NOT NULL);`);
    if (!existing) {
      this.db.exec(`PRAGMA user_version=${STUDIO_SCHEMA_VERSION}`);
      this.schemaVersion = STUDIO_SCHEMA_VERSION;
    }
  }
  close() {
    this.db.close();
  }
  /** Caller must make a SQLite-consistent backup first. Never invoked on normal reads. */
  migrateAfterBackup(backupPath: string) {
    if (this.schemaVersion === STUDIO_SCHEMA_VERSION) return;
    // VACUUM INTO takes a consistent snapshot and refuses to replace an existing file.
    this.db.prepare("VACUUM INTO ?").run(backupPath);
    this.db.exec("BEGIN IMMEDIATE");
    try {
      for (const table of ["studies", "versions"]) {
        const rows = this.db.prepare(`SELECT id,doc FROM ${table}`).all() as { id: string; doc: string }[];
        for (const row of rows) {
          const doc = readDocument(row.doc);
          this.db.prepare(`UPDATE ${table} SET doc=? WHERE id=?`).run(JSON.stringify({ ...doc, schemaVersion: 1 }), row.id);
        }
      }
      this.db.exec(`PRAGMA user_version=${STUDIO_SCHEMA_VERSION}; COMMIT`);
      this.schemaVersion = STUDIO_SCHEMA_VERSION;
    } catch (error) {
      this.db.exec("ROLLBACK");
      throw error;
    }
  }
  capacity() {
    return studioCapacity(this.db, this.schemaVersion);
  }
  private checkCapacity(serialized: string, replacedBytes = 0) {
    if (Buffer.byteLength(serialized) > MAX_DOCUMENT)
      fail("This study reached its 8 MB result limit. Export it and create another study.", 413);
    const before = this.capacity().usedBytes;
    const after = before - replacedBytes + Buffer.byteLength(serialized);
    // An over-quota legacy store can still save changes that do not increase usage.
    if (after > MAX_STORAGE && after > before)
      fail("Studio storage limit reached (256 MB). Export saved studies before changing workspace capacity. No changes were saved.", 507);
  }
  private transaction<T>(fn: () => T): T {
    if (this.schemaVersion !== STUDIO_SCHEMA_VERSION)
      fail("Studio database upgrade required. Export or back up this workspace, then explicitly migrate it.", 409);
    this.db.exec("BEGIN IMMEDIATE");
    try {
      const value = fn();
      this.db.exec("COMMIT");
      return value;
    } catch (e) {
      this.db.exec("ROLLBACK");
      throw e;
    }
  }
  private write(study: Study) {
    study.schemaVersion = 1;
    const serialized = JSON.stringify(study);
    const previous = this.db.prepare("SELECT length(CAST(doc AS BLOB)) AS n FROM studies WHERE id=?").get(study.id) as { n: number } | undefined;
    this.checkCapacity(serialized, previous?.n ?? 0);
    this.db
      .prepare(
        "INSERT INTO studies(id,doc) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET doc=excluded.doc",
      )
      .run(study.id, serialized);
  }
  private raw(id: string): Study {
    validId(id);
    const row = this.db
      .prepare("SELECT doc FROM studies WHERE id=?")
      .get(id) as { doc: string } | undefined;
    if (!row) return fail("Study not found.", 404);
    return readDocument(row.doc);
  }
  get(id: string): Study {
    if (this.schemaVersion === 0) return this.raw(id);
    const leases = this.db
      .prepare("SELECT run_id,pid,expires FROM leases WHERE study_id=?")
      .all(validId(id)) as { run_id: string; pid: number; expires: number }[];
    for (const lease of leases)
      if (lease.expires < Date.now() || !alive(lease.pid)) {
        this.mutate(id, (s) => {
          const r = s.runs.find((r) => r.id === lease.run_id);
          if (r?.status === "running") {
            r.status = "interrupted";
            r.plan = r.plan.map((step) =>
              step.status === "active" || step.status === "pending"
                ? { ...step, status: "incomplete" }
                : step,
            );
            r.error =
              "Execution was interrupted. Retry explicitly to continue.";
            r.updatedAt = now();
          }
        });
        this.db.prepare("DELETE FROM leases WHERE run_id=?").run(lease.run_id);
      }
    return this.raw(id);
  }
  list(): StudySummary[] {
    return (
      this.db.prepare("SELECT doc FROM studies").all() as { doc: string }[]
    )
      .map((r) => readDocument(r.doc))
      .map(({ id, title, archived, updatedAt }) => ({
        id,
        title,
        archived,
        updatedAt,
      }))
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  }
  create(title: string, context: ResearchContext, draft = ""): Study {
    return this.transaction(() => {
      return this.createInside(title, context, draft);
    });
  }
  /** Delete only the explicitly reviewed revision, never an active analysis. */
  deleteStudy(id: string, input: unknown): { deleted: string } {
    const { revision } = object(input);
    if (typeof revision !== "number" || !Number.isSafeInteger(revision) || revision < 0)
      fail("A saved revision is required.");
    return this.transaction(() => {
      const study = this.raw(id);
      if (study.revision !== revision)
        fail("This study changed. Close this dialog and review it before deleting.", 409);
      if (study.runs.some(run => run.status === "running") ||
          this.db.prepare("SELECT 1 FROM leases WHERE study_id=? LIMIT 1").get(id))
        fail("An analysis is still running in this study. Wait for it to finish before deleting.", 409);
      for (const table of ["versions", "files", "run_requests", "transfers"])
        this.db.prepare(`DELETE FROM ${table} WHERE study_id=?`).run(id);
      this.db.prepare("DELETE FROM studies WHERE id=?").run(id);
      return { deleted: id };
    });
  }
  /** Server resource resolver only: callers cannot supply result rows through an API. */
  saveResource(input: { requestId: string; requestHash: string; title: string; context: ResearchContext; run: ResearchRun; target?: {studyId: string; revision: number}; document?: {afterId?: string | null} }): Study {
    return this.transaction(() => {
      validId(input.requestId);
      const rows = this.db.prepare("SELECT study_id,run_id FROM run_requests WHERE request_id=?").all(input.requestId) as {study_id:string;run_id:string}[];
      if (rows.length) {
        if (rows.length !== 1) fail("Ambiguous resource request identity.", 409);
        const saved = this.raw(rows[0].study_id);
        const run = saved.runs.find(r => r.id === rows[0].run_id);
        if (!run?.resource || run.resource.requestHash !== input.requestHash || run.resource.targetStudyId !== input.target?.studyId) fail("Resource request ID is already bound to a different save.", 409);
        return saved;
      }
      const s = input.target ? this.raw(validId(input.target.studyId)) : this.createInside(input.title, input.context);
      if (input.target && s.revision !== input.target.revision) fail("This study changed in another request. Reload before saving your edits.", 409);
      if (s.archived) fail("Restore this archived study before adding resources.", 409);
      if (s.runs.length >= 64) fail("This study reached 64 analyses.", 413);
      if (input.run.status !== "complete" || !input.run.resource || input.run.resource.requestId !== input.requestId || input.run.resource.requestHash !== input.requestHash) fail("Resource save is not bound to a completed server query.");
      s.runs.push(structuredClone(input.run));
      if (input.document) insertReportBlock(s, {
        id: uuid(), kind: "resource", text: "", runId: input.run.id, refId: input.run.resource!.id,
      }, { afterId: input.document.afterId, withAnalysis: true });
      s.revision++;
      s.updatedAt = now();
      this.write(s);
      this.db.prepare("INSERT INTO run_requests VALUES(?,?,?)").run(s.id, input.requestId, input.run.id);
      return s;
    });
  }
  private createInside(title: string, context: ResearchContext, draft = ""): Study {
      if (this.list().length >= 128)
        fail("Local workspace limit: 128 studies.", 413);
      const study: Study = {
        id: uuid(),
        title: textValue(title, 120),
        context: contextValue(context),
        draft: textValue(draft, 2000, true),
        archived: false,
        revision: 1,
        createdAt: now(),
        updatedAt: now(),
        runs: [],
        findings: [],
        report: [],
        artifacts: [],
      };
      this.write(study);
      return study;
  }
  /** Reserve the durable transfer identity in the same transaction as study creation. */
  claimTransfer(id: string): { study: Study; created: boolean } {
    return this.transaction(() => {
      const { transfer, studyId } = this.transfer(id);
      if (studyId) return { study: this.raw(studyId), created: false };
      const study = this.createInside(transfer.question.slice(0, 120), {
        filters: transfer.context.filters, metric: "crashes", notes: "", references: "",
      }, transfer.question);
      this.db.prepare("UPDATE transfers SET study_id=? WHERE id=? AND study_id IS NULL").run(study.id, id);
      return { study, created: true };
    });
  }
  mutate(id: string, fn: (study: Study) => void, expected?: number): Study {
    return this.transaction(() => {
      const s = this.raw(id);
      if (expected !== undefined && s.revision !== expected)
        fail(
          "This study changed in another request. Reload before saving your edits.",
          409,
        );
      fn(s);
      s.revision++;
      s.updatedAt = now();
      this.write(s);
      return s;
    });
  }
  private snapshotInside(s: Study, label: string) {
    const count = this.db
      .prepare("SELECT count(*) AS n FROM versions WHERE study_id=?")
      .get(s.id) as { n: number };
    if (count.n >= 50)
      fail("This study reached its 50-version limit. Create a new study.", 413);
    this.checkCapacity(JSON.stringify(s));
    this.db
      .prepare("INSERT INTO versions VALUES(?,?,?,?,?)")
      .run(uuid(), s.id, label, now(), JSON.stringify(s));
  }
  versions(id: string): StudyVersion[] {
    this.get(id);
    return (
      this.db
        .prepare(
          "SELECT id,label,created,doc FROM versions WHERE study_id=? ORDER BY created DESC",
        )
        .all(id) as {
        id: string;
        label: string;
        created: string;
        doc: string;
      }[]
    ).map((row) => {
      const s = JSON.parse(row.doc) as Study;
      return {
        id: row.id,
        label: row.label,
        createdAt: row.created,
        context: s.context,
        runs: s.runs.length,
        findings: s.findings.length,
      };
    });
  }
  version(id: string, versionId: string): Study {
    this.get(id);
    const row = this.db
      .prepare("SELECT doc FROM versions WHERE study_id=? AND id=?")
      .get(id, validId(versionId)) as { doc: string } | undefined;
    if (!row) return fail("Version not found in this study.", 404);
    return readDocument(row.doc);
  }
  action(id: string, raw: unknown): Study {
    const a = object(raw);
    const expected =
      typeof a.revision === "number"
        ? a.revision
        : fail("A saved revision is required.");
    return this.mutate(
      id,
      (s) => {
        switch (a.type) {
          case "rename":
            s.title = textValue(a.title, 120);
            break;
          case "archive":
            s.archived = a.archived === true;
            break;
          case "draft":
            s.draft = textValue(a.text, 2000, true);
            break;
          case "skip_presentation": {
            const run = s.runs.find((r) => r.id === validId(a.runId));
            if (!run || run.status !== "running")
              fail("No active analysis to update.", 409);
            run!.skipPresentation = true;
            for (const task of run!.plan)
              if (task.optional && task.status === "pending")
                task.status = "skipped";
            break;
          }
          case "context": {
            if (s.runs.some((r) => r.status === "running"))
              fail(
                "Stop the active analysis before changing its context.",
                409,
              );
            const context = contextValue(a.context);
            this.snapshotInside(s, "Before context change");
            s.context = context;
            break;
          }
          case "snapshot":
            this.snapshotInside(
              s,
              textValue(a.label || "Research snapshot", 120),
            );
            break;
          case "restore": {
            if (s.runs.some((r) => r.status === "running"))
              fail("Stop analysis before restoring a version.", 409);
            const row = this.db
              .prepare("SELECT doc FROM versions WHERE study_id=? AND id=?")
              .get(id, validId(a.versionId)) as { doc: string } | undefined;
            if (!row) fail("Version not found in this study.", 404);
            this.snapshotInside(s, "Before restore");
            const old = readDocument(row!.doc);
            Object.assign(s, {
              context: old.context,
              draft: old.draft,
              runs: old.runs.map((r) =>
                r.status === "running" ? { ...r, status: "interrupted" } : r,
              ),
              findings: old.findings,
              report: old.report,
              reportMeta: old.reportMeta,
              artifacts: old.artifacts,
            });
            // The restored document is the current revision. Preserve only the pre-restore snapshot.
            break;
          }
          case "finding": {
            const existing = a.id
              ? s.findings.find((f) => f.id === validId(a.id))
              : undefined;
            if (a.id && !existing)
              fail("Finding not found in this study.", 404);
            const kind = a.kind ?? existing?.kind;
            if (
              !["Observation", "Hypothesis", "Open question"].includes(
                String(kind),
              )
            )
              fail("Unknown finding type.");
            const runId =
              a.runId !== undefined ? (a.runId ? validId(a.runId) : undefined) : existing?.runId;
            const run = runId
              ? s.runs.find((r) => r.id === runId && r.status === "complete")
              : undefined;
            if (runId && !run)
              fail(
                "Only completed results in this study can support a finding.",
              );
            const evidenceIds =
              a.evidenceIds !== undefined ? (Array.isArray(a.evidenceIds) ? a.evidenceIds : fail("Invalid evidence reference.")) : existing?.evidenceIds || [];
            if (
              evidenceIds.length > 16 ||
              evidenceIds.some((e) => !run?.evidence.some((v) => v.id === e))
            )
              fail("Invalid evidence reference.");
            const at = now();
            if (existing && existing.edits.length >= 100)
              fail("Finding edit-history limit reached.");
            const finding: ResearchFinding = {
              id: existing?.id || uuid(),
              title: textValue(a.title ?? existing?.title, 500),
              explanation: textValue(
                a.explanation ?? existing?.explanation ?? "",
                6000,
                true,
              ),
              kind: kind as ResearchFinding["kind"],
              runId,
              evidenceIds,
              evidenceRefs: runId ? evidenceIds.map((e: string) => evidenceReference(s, runId, e)) : [],
              claims: a.claims !== undefined ? parseNumericClaims(a.claims) : existing?.claims || [],
              context:
                structuredClone(run?.context || s.context),
              limitations:
                existing?.limitations ||
                "Project snapshot. Source definitions remain independent; counts are not risk rates. An observed association does not establish a cause.",
              // Linking an analysis does not establish authorship of user-entered text.
              origin: existing?.origin || "user",
              archived: existing?.archived || false,
              createdAt: existing?.createdAt || at,
              updatedAt: at,
              edits: existing
                ? [
                    ...existing.edits,
                    {
                      at: existing.updatedAt,
                      title: existing.title,
                      explanation: existing.explanation,
                      kind: existing.kind,
                      evidenceRefs: structuredClone(existing.evidenceRefs),
                      claims: structuredClone(existing.claims),
                      checks: structuredClone(existing.checks),
                    },
                  ]
                : [],
            };
            const unchanged = existing && findingContentHash(existing) === findingContentHash(finding);
            finding.checks = unchanged && existing.checks ? structuredClone(existing.checks) : findingChecks(s, finding);
            // Editing never silently re-certifies a formerly checked claim, even when the user kept old claims.
            if (existing && !unchanged) {
              finding.checks.numericChecked = false;
              finding.checks.userReviewed = false;
              finding.checks.reviewNeeded = true;
              finding.checks.notes.unshift("Finding content or evidence changed; run the explicit check again.");
            }
            if (existing) s.findings[s.findings.indexOf(existing)] = finding;
            else {
              if (s.findings.length >= 200) fail("Finding limit reached.");
              s.findings.push(finding);
            }
            break;
          }
          case "finding_check":
          case "finding_review": {
            const f = s.findings.find(f => f.id === validId(a.id));
            if (!f) fail("Finding not found.", 404);
            if (f!.edits.length >= 100) fail("Finding edit-history limit reached.");
            f!.edits.push({ at: f!.updatedAt, title: f!.title, explanation: f!.explanation, kind: f!.kind, evidenceRefs: structuredClone(f!.evidenceRefs), claims: structuredClone(f!.claims), checks: structuredClone(f!.checks) });
            if (a.type === "finding_check") f!.checks = findingChecks(s, f!);
            else {
              f!.checks ||= findingChecks(s, f!);
              f!.checks.userReviewed = true;
              f!.checks.reviewNeeded = false;
              f!.checks.checkedAt = now();
            }
            f!.updatedAt = now();
            break;
          }
          case "report_meta":
            s.reportMeta = reportMetadata(a.metadata, s);
            break;
          case "report_title": {
            const previous = s.reportMeta?.title || s.title;
            s.reportMeta = reportMetadata({ template: "brief", language: "en", ...s.reportMeta, title: textValue(a.title, 120) }, s);
            if (s.report[0]?.kind === "title" && s.report[0].text === previous)
              s.report[0].text = s.reportMeta.title;
            break;
          }
          case "report_details": {
            const metadata = object(a.metadata);
            if (Object.keys(metadata).some(key => !["template", "language", "author", "date"].includes(key)))
              fail("Unknown report detail.");
            s.reportMeta = reportMetadata({ template: "brief", language: "en", ...s.reportMeta, ...metadata }, s);
            break;
          }
          case "report_template": {
            if (a.blank !== undefined && typeof a.blank !== "boolean") fail("Invalid blank-template option.");
            if (s.report.length && a.replace !== true) fail("Confirm replacing the current report structure.", 409);
            if (s.report.length) this.snapshotInside(s, "Before report template");
            s.reportMeta = reportMetadata(a.metadata, s);
            s.report = reportTemplate(s.reportMeta);
            if (a.blank === true) s.report = s.report.map(b => b.kind === "text" ? { ...b, text: "" } : b);
            break;
          }
          case "report_apply": {
            const run = s.runs.find(r => r.id === validId(a.runId) && r.status === "complete");
            const draft = run?.reportDraft;
            if (!draft || draft.id !== validId(a.draftId)) fail("Saved report draft not found.", 404);
            if (draft!.status !== "proposed") fail("This report draft was already applied.", 409);
            if (draft!.baseReportHash !== reportHash(s)) fail("The report changed after this draft started. Generate a new draft or keep your current edits.", 409);
            const blocks = draft!.blocks.map(b => bindReportBlock(s, b));
            this.snapshotInside(s, "Before applying report draft");
            if (draft!.mode === "revise") {
              const index = s.report.findIndex(b => b.id === draft!.targetBlockId);
              if (index < 0 || blocks.length !== 1) fail("Selected paragraph no longer exists.", 409);
              s.report[index] = blocks[0];
            } else s.report = blocks;
            draft!.status = "applied";
            draft!.appliedRevision = s.revision + 1;
            break;
          }
          case "report_undo": {
            const row = this.db.prepare("SELECT doc FROM versions WHERE study_id=? AND id=?").get(s.id, validId(a.versionId)) as {doc:string} | undefined;
            if (!row) fail("Report version not found in this study.", 404);
            const old = readDocument(row!.doc);
            const blocks = old.report.map(b => bindReportBlock(s, b));
            this.snapshotInside(s, "Before report undo");
            s.report = blocks;
            s.reportMeta = old.reportMeta;
            break;
          }
          case "finding_archive": {
            const f = s.findings.find((f) => f.id === validId(a.id));
            if (!f) fail("Finding not found.", 404);
            f!.archived = a.archived === true;
            f!.updatedAt = now();
            break;
          }
          case "finding_delete": {
            const id = validId(a.id);
            if (s.report.some((b) => b.kind === "finding" && b.refId === id))
              fail("Remove this finding from the report before deleting it.");
            if (!s.findings.some((f) => f.id === id))
              fail("Finding not found.", 404);
            s.findings = s.findings.filter((f) => f.id !== id);
            break;
          }
          case "answer_to_document": {
            if (Object.keys(a).some(key => !["type", "revision", "runId", "attempt", "afterId"].includes(key)))
              fail("Answer insertion accepts a saved response identity, not caller-supplied content.");
            const runId = validId(a.runId);
            const run = s.runs.find(r => r.id === runId);
            if (!isCompletedConversationAnswer(run))
              return fail("Choose a completed conversation answer in this study.", 409);
            if (!Number.isInteger(a.attempt) || a.attempt !== run.attempt)
              fail("The answer attempt changed. Reload and select its current response.", 409);
            // The answer is editable prose, not a verified claim. Only host-validated
            // evidence can become citations; its exact attempt/result binding survives.
            const citations = run.evidence
              .filter(e => e.result !== undefined && (e.query?.validated || e.query?.assurance?.parameters === "validated"))
              .map(e => evidenceReference(s, run.id, e.id));
            insertReportBlock(s, {
              id: uuid(), kind: "text", text: textValue(run.answer, 10000), citations,
              answerSource: { runId: run.id, attempt: run.attempt, answerHash: resultHash(run.answer) },
            }, { afterId: a.afterId });
            break;
          }
          case "block_add": {
            const block: ReportBlock = {
              id: uuid(),
              kind: a.kind as ReportBlock["kind"],
              text: textValue(a.text ?? "", 10000, true),
              ...(a.runId ? { runId: validId(a.runId) } : {}),
              ...(a.refId ? { refId: textValue(a.refId, 100) } : {}),
              ...(a.caption !== undefined ? {caption: textValue(a.caption, 2000, true)} : {}),
              ...(a.size === "half" || a.size === "full" ? {size: a.size} : {}),
              ...(a.pageBreakBefore === true ? {pageBreakBefore: true} : {}),
            };
            insertReportBlock(s, block, { afterId: a.afterId, withAnalysis: a.withAnalysis });
            break;
          }
          case "block_edit": {
            const block = s.report.find((b) => b.id === validId(a.id));
            if (!block) fail("Block not found.", 404);
            if (a.text !== undefined) block!.text = textValue(a.text, 10000, true);
            if (a.caption !== undefined) block!.caption = textValue(a.caption, 2000, true);
            if (a.pageBreakBefore !== undefined) block!.pageBreakBefore = a.pageBreakBefore === true;
            if (a.size !== undefined) {
              if (a.size !== "full" && a.size !== "half") fail("Invalid figure size.");
              block!.size = a.size as "full" | "half";
            }
            break;
          }
          case "block_move": {
            const index = s.report.findIndex((b) => b.id === validId(a.id));
            if (index < 0 || (a.direction !== -1 && a.direction !== 1))
              fail("Invalid block move.");
            const next = index + Number(a.direction);
            if (next >= 0 && next < s.report.length)
              [s.report[next], s.report[index]] = [
                s.report[index],
                s.report[next],
              ];
            break;
          }
          case "block_delete":
            s.report = s.report.filter((b) => b.id !== validId(a.id));
            break;
          default:
            fail("Unknown research operation.");
        }
      },
      expected,
    );
  }
  beginRun(
    id: string,
    requestId: string,
    question: string,
    skipPresentation = false,
    retryId?: string,
    options: { mode?: ResearchMode; selectedRunIds?: string[]; targetBlockId?: string } = {},
  ): { study: Study; run: ResearchRun; replay: boolean } {
    validId(requestId);
    const prior = this.runRequest(id, requestId);
    if (prior) return { ...prior, replay: true };
    if (options.mode && !["explore", "analyze", "draft", "revise"].includes(options.mode)) fail("Unknown research mode.");
    let replay = false;
    let runId = requestId;
    const study = this.transaction(() => {
      const s = this.raw(id);
      const receipt = this.db
        .prepare(
          "SELECT run_id FROM run_requests WHERE study_id=? AND request_id=?",
        )
        .get(id, requestId) as { run_id: string } | undefined;
      if (receipt) {
        runId = receipt.run_id;
        replay = true;
        return s;
      }
      const existing = s.runs.find((r) => r.id === requestId);
      if (existing) {
        replay = true;
        return s;
      }
      // Wording-only work verifies saved immutable evidence; it does not re-query a disappeared live release.
      if (!["draft", "revise"].includes(options.mode || "")) contextValue(s.context);
      if (s.archived)
        fail("Restore this archived study before running analysis.");
      if (s.runs.some((r) => r.status === "running"))
        fail("An analysis is already running in this study.", 409);
      let run: ResearchRun;
      if (retryId) {
        const old = s.runs.find((r) => r.id === validId(retryId));
        if (!old || old.status === "complete" || old.status === "running")
          fail("Only an incomplete run can be retried.");
        if (old!.attempt >= 3)
          fail("Retry limit reached. Start a new question.", 429);
        run = old!;
        runId = run.id;
        run.previousAttempts.push({
          status: run.status,
          answer: run.answer,
          evidence: run.evidence,
          error: run.error,
          views: run.views,
          artifactIds: run.artifactIds,
        });
        Object.assign(run, {
          status: "running",
          answer: "",
          evidence: [],
          views: [],
          artifactIds: [],
          toolErrors: [],
          error: undefined,
          plan: [],
          updatedAt: now(),
          attempt: run.attempt + 1,
        });
        // Retry uses the original scope and question, not the study's subsequently edited scope.
        if (!["draft", "revise"].includes(run.mode || "")) contextValue(run.context);
      } else {
        if (s.runs.length >= 64)
          fail("This study reached 64 analyses. Export it or create a new study; incomplete runs can still be retried.", 413);
        run = {
          id: requestId,
          question: textValue(question, 2000),
          context: structuredClone(s.context),
          status: "running",
          answer: "",
          progress: "Preparing analysis…",
          createdAt: now(),
          updatedAt: now(),
          attempt: 1,
          previousAttempts: [],
          plan: [],
          skipPresentation,
          evidence: [],
          views: [],
          artifactIds: [],
          changes: s.runs.length
            ? contextChanges(s.runs.at(-1)!.context, s.context)
            : [],
          origin: "assistant",
          mode: options.mode || "analyze",
          selectedRunIds: options.selectedRunIds,
          targetBlockId: options.targetBlockId,
        };
        s.runs.push(run);
        s.draft = "";
      }
      this.db
        .prepare("INSERT OR REPLACE INTO leases VALUES(?,?,?,?)")
        .run(run.id, s.id, process.pid, Date.now() + 255000);
      this.db
        .prepare("INSERT INTO run_requests VALUES(?,?,?)")
        .run(id, requestId, run.id);
      s.revision++;
      s.updatedAt = now();
      this.write(s);
      return s;
    });
    return { study, run: study.runs.find((r) => r.id === runId)!, replay };
  }
  runRequest(id: string, requestId: string): { study: Study; run: ResearchRun } | undefined {
    const study = this.get(id);
    const receipt = this.db.prepare("SELECT run_id FROM run_requests WHERE study_id=? AND request_id=?").get(validId(id), validId(requestId)) as {run_id: string} | undefined;
    const run = study.runs.find(r => r.id === (receipt?.run_id || requestId));
    return run ? {study, run} : undefined;
  }
  updateRun(id: string, run: ResearchRun): Study {
    const saved = this.get(id);
    const current = saved.runs.find(r => r.id === run.id);
    if (current && current.attempt !== run.attempt) return saved;
    if (current?.status === "complete") {
      // A late stream/audit callback has no authority to rewrite a committed completion or another attempt.
      const warnings = [...new Set([...(current.completionWarnings || []), ...(run.completionWarnings || []), ...(run.status !== "complete" && run.error ? [run.error] : [])])].slice(0, 16);
      if (JSON.stringify(warnings) !== JSON.stringify(current.completionWarnings || []))
        return this.mutate(id, s => { s.runs.find(r => r.id === run.id)!.completionWarnings = warnings; });
      return saved;
    }
    if (current && current.status !== "running" && current.status !== run.status) return saved;
    return this.mutate(id, (s) => {
      const i = s.runs.findIndex((r) => r.id === run.id);
      if (i < 0) fail("Run not found.", 404);
      s.runs[i] = structuredClone(run);
      s.runs[i].updatedAt = now();
      if (run.status !== "running")
        this.db.prepare("DELETE FROM leases WHERE run_id=?").run(run.id);
    });
  }
  saveFile(
    id: string,
    runId: string,
    file: { artifact: AnalysisArtifact; bytes: Buffer; provenance: unknown },
  ): StudyArtifact {
    const a = file.artifact,
      bytes = file.bytes;
    if (
      !/^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$/.test(a.name) ||
      !["csv", "json", "md", "txt", "png", "pdf", "py"].includes(a.kind) ||
      a.name.split(".").at(-1) !== a.kind ||
      bytes.length !== a.bytes ||
      bytes.length > 4194304 ||
      createHash("sha256").update(bytes).digest("hex") !== a.sha256
    )
      fail("Invalid generated attachment.");
    if (
      a.kind === "png" &&
      !bytes
        .subarray(0, 8)
        .equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))
    )
      fail("Invalid image attachment.");
    if (a.kind === "pdf" && bytes.subarray(0, 5).toString() !== "%PDF-")
      fail("Invalid PDF attachment.");
    if (a.kind === "json") {
      try {
        JSON.parse(bytes.toString("utf8"));
      } catch {
        fail("Invalid JSON attachment.");
      }
    }
    if (
      !["png", "pdf"].includes(a.kind) &&
      (bytes.includes(0) || bytes.toString("utf8").includes("\uFFFD"))
    )
      fail("Invalid text attachment.");
    const fileId = uuid();
    const saved: StudyArtifact = {
      id: fileId,
      runId,
      name: a.name,
      kind: a.kind,
      bytes: a.bytes,
      sha256: a.sha256,
      href: `/api/studio/${id}/artifacts/${fileId}`,
      createdAt: now(),
      provenance: file.provenance,
    };
    this.mutate(id, (s) => {
      if (!s.runs.some((r) => r.id === runId)) fail("Invalid attachment run.");
      saved.attempt = s.runs.find((r) => r.id === runId)!.attempt;
      if (
        s.artifacts.length >= 100 ||
        s.artifacts.reduce((n, a) => n + a.bytes, 0) + bytes.length >
          64 * 1024 * 1024
      )
        fail("Study attachment limit reached (100 files / 64 MB).", 413);
      this.db.prepare("INSERT INTO files VALUES(?,?,?)").run(fileId, id, bytes);
      s.artifacts.push(saved);
    });
    return saved;
  }
  file(id: string, fileId: string) {
    const s = this.get(id);
    validId(fileId);
    const historical = this.db
      .prepare("SELECT doc FROM versions WHERE study_id=?")
      .all(id) as { doc: string }[];
    const a =
      s.artifacts.find((a) => a.id === fileId) ||
      historical
        .flatMap((v) => (JSON.parse(v.doc) as Study).artifacts)
        .find((a) => a.id === fileId);
    if (!a) return fail("Attachment not found in this study.", 404);
    const row = this.db
      .prepare("SELECT bytes FROM files WHERE study_id=? AND id=?")
      .get(id, fileId) as { bytes: Uint8Array } | undefined;
    if (
      !row ||
      createHash("sha256").update(row.bytes).digest("hex") !== a.sha256
    )
      return fail("Saved attachment failed its integrity check.", 404);
    return { artifact: a, bytes: Buffer.from(row.bytes) };
  }
  saveTransfer(transfer: CompletedTransfer) {
    this.transaction(() => {
      validId(transfer.id);
      const serialized = JSON.stringify(transfer);
      const existing = this.db.prepare("SELECT doc FROM transfers WHERE id=?").get(transfer.id) as { doc: string } | undefined;
      if (existing) {
        if (existing.doc !== serialized) fail("Transfer identity already belongs to another response.", 409);
        return;
      }
      const count = this.db.prepare("SELECT count(*) AS n FROM transfers").get() as { n: number };
      if (count.n >= 64) fail("Transfer storage limit reached. Export saved studies before changing workspace capacity.", 413);
      this.checkCapacity(serialized);
      this.db.prepare("INSERT INTO transfers VALUES(?,?,NULL,?)").run(transfer.id, Date.now(), serialized);
    });
  }
  transfer(id: string): { transfer: CompletedTransfer; studyId?: string } {
    const row = this.db
      .prepare("SELECT doc,study_id,created FROM transfers WHERE id=?")
      .get(validId(id)) as
      | { doc: string; study_id?: string; created: number }
      | undefined;
    if (!row || (!row.study_id && Date.now() - row.created > 86400000))
      return fail(
        "This completed response has expired. Run the question in Studio again.",
        410,
      );
    return { transfer: JSON.parse(row.doc), studyId: row.study_id };
  }

}
const globalStore = globalThis as typeof globalThis & {
  arsiaStudioStore?: StudioStore;
};
export function studioStore() {
  // Refresh methods and additive schema after HMR while preserving the live connection.
  const connection = globalStore.arsiaStudioStore?.db;
  if (!(globalStore.arsiaStudioStore instanceof StudioStore))
    globalStore.arsiaStudioStore = new StudioStore(
      join(process.cwd(), "artifacts/studio/research.sqlite"),
      connection,
    );
  return globalStore.arsiaStudioStore;
}
