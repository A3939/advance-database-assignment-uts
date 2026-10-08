import type { Study } from "../../services/studio-contracts";
import type { AnalysisRow } from "../../services/analysis-contracts";
import { StudioError, type StudioStore } from "./store";
import { createHash } from "node:crypto";
import { renderStudyReport, REPORT_RENDERER_VERSION, type ReportFile } from "./report-renderer";
import { renderReportPdf } from "./report-pdf";
import { verifyResearchAsset } from "./resource-integrity";
import { selectReportMaterials, selectedEvidence, publicMaterial, exportStudyProjection, exportEvidence } from "./report-selection";
const cell = (v: unknown) => {
  const raw =
    v === null || v === undefined
      ? ""
      : typeof v === "object"
        ? JSON.stringify(v)
        : String(v);
  // Downloads opened in spreadsheet software must not execute formulas.
  return `"${(/^[=+@\-\t\r]/.test(raw) && typeof v !== "number" ? "'" : "") + raw.replaceAll('"', '""')}"`;
};
export function csv(rows: AnalysisRow[]) {
  const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))];
  return [
    cols.map(cell).join(","),
    ...rows.map((r) => cols.map((c) => cell(r[c])).join(",")),
  ].join("\r\n");
}
function crc32(bytes: Buffer) {
  let crc = 0xffffffff;
  for (const b of bytes) {
    crc ^= b;
    for (let bit = 0; bit < 8; bit++)
      crc = (crc >>> 1) ^ (crc & 1 ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}
/** Small bounded ZIP writer (stored entries); no executable generators or shell paths. */
export function zip(files: { name: string; bytes: Buffer }[]) {
  const parts: Buffer[] = [],
    central: Buffer[] = [];
  let offset = 0;
  for (const file of files) {
    const name = Buffer.from(file.name),
      crc = crc32(file.bytes),
      h = Buffer.alloc(30),
      d = Buffer.alloc(46);
    h.writeUInt32LE(0x04034b50, 0);
    h.writeUInt16LE(20, 4);
    h.writeUInt16LE(0x800, 6);
    h.writeUInt32LE(crc, 14);
    h.writeUInt32LE(file.bytes.length, 18);
    h.writeUInt32LE(file.bytes.length, 22);
    h.writeUInt16LE(name.length, 26);
    d.writeUInt32LE(0x02014b50, 0);
    d.writeUInt16LE(20, 4);
    d.writeUInt16LE(20, 6);
    d.writeUInt16LE(0x800, 8);
    d.writeUInt32LE(crc, 16);
    d.writeUInt32LE(file.bytes.length, 20);
    d.writeUInt32LE(file.bytes.length, 24);
    d.writeUInt16LE(name.length, 28);
    d.writeUInt32LE(offset, 42);
    parts.push(h, name, file.bytes);
    central.push(d, name);
    offset += h.length + name.length + file.bytes.length;
  }
  const directory = Buffer.concat(central),
    end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(files.length, 8);
  end.writeUInt16LE(files.length, 10);
  end.writeUInt32LE(directory.length, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...parts, directory, end]);
}
const sha = (bytes: Buffer) => createHash("sha256").update(bytes).digest("hex");
export function exportRevision(query: URLSearchParams): number {
  const value = query.get("revision");
  if (!value || !/^[1-9]\d{0,9}$/.test(value)) throw new StudioError("A saved report revision is required.");
  return Number(value);
}
export function savedExportSnapshot(store: StudioStore, study: Study, expectedRevision = study.revision): Study {
  if (!Number.isSafeInteger(expectedRevision) || expectedRevision < 1 || study.revision !== expectedRevision || store.get(study.id).revision !== expectedRevision)
    throw new StudioError("The report revision changed. Save and reopen the requested revision before exporting.", 409);
  return structuredClone(study);
}
function materials(store: StudioStore, study: Study) {
  const selection = selectReportMaterials(study), report = renderStudyReport(study);
  const files: ReportFile[] = [...report.files];
  const add = (name: string, value: string) => files.push({ name, bytes: Buffer.from(value) });
  add("report.md", report.markdown); add("report.html", report.html);
  for (const run of selection.runs) {
    if (run.resource) verifyResearchAsset(run);
    for (const view of run.views.filter(view => selection.viewIds.get(run.id)?.has(view.id))) add(`data/${run.id}-${view.id}.csv`, csv(view.rows));
    const evidence = exportEvidence(run, selection);
    add(`sources/${run.id}.json`, JSON.stringify({ runId: run.id, status: run.status, attempt: run.attempt,
      context: publicMaterial(run.context), resource: run.resource ? publicMaterial(run.resource) : undefined,
      evidence, projectionHash: sha(Buffer.from(JSON.stringify(evidence))),
      originalEvidenceHashes: selectedEvidence(run, selection).map(item => ({ evidenceId: item.id, sha256: sha(Buffer.from(JSON.stringify(item))) })),
      projectionNote: "Private research context and unselected response payloads are omitted. Original evidence hashes identify the saved source; projectionHash and manifest file hashes bind these exported bytes." }, null, 2));
    for (const evidence of exportEvidence(run, selection)) {
      const extract = (value: unknown, path: string, depth = 0) => {
        if (depth > 8) return;
        if (Array.isArray(value) && value.length && value.every(row => row && typeof row === "object" && !Array.isArray(row))) {
          const rows = value as Record<string, unknown>[];
          if (rows.some(row => Object.values(row).some(v => typeof v === "number"))) add(`data/${run.id}-${evidence.id}-${path}.csv`, csv(rows.map(row => Object.fromEntries(Object.entries(row).map(([key,v]) => [key, typeof v === "object" && v !== null ? JSON.stringify(v) : v])) as AnalysisRow)));
        }
        if (value && typeof value === "object") for (const [key, child] of Object.entries(value)) {
          if (typeof child === "object" && child !== null && key !== "boundaries") extract(child, `${path}-${key.replace(/[^a-zA-Z0-9_-]/g,"_")}`.slice(0,120), depth + 1);
        }
      };
      if (evidence.result) extract(evidence.result, "query");
    }
  }
  for (const artifact of selection.artifacts) {
    const f = store.file(study.id, artifact.id);
    if (sha(f.bytes) !== artifact.sha256 || f.bytes.length !== artifact.bytes) throw new StudioError("A saved attachment no longer matches the report snapshot.", 409);
    files.push({ name: `attachments/${artifact.id}-${artifact.name}`, bytes: f.bytes });
    if (artifact.kind === "py") files.push({ name: `code/${artifact.id}-${artifact.name}`, bytes: f.bytes });
  }
  return { report, files: [...new Map(files.map(file => [file.name, file])).values()], selection, projection: exportStudyProjection(study, selection) };
}
function packageFiles(study: Study, value: ReturnType<typeof materials>, pdf?: Buffer) {
  const files = [...value.files, ...(pdf ? [{ name: "report.pdf", bytes: pdf }] : [])];
  if (files.some(file => !/^[a-zA-Z0-9][a-zA-Z0-9._ /-]*$/.test(file.name) || file.name.split("/").some(part => part === ".." || !part))) throw new StudioError("A report material has an unsafe package name.", 409);
  if (files.reduce((bytes,file) => bytes + file.bytes.length,0) > 96000000) throw new StudioError("The report materials exceed the bounded export capacity.", 422);
  const manifest = {
    format: "arsia-studio-v3", exportedAt: new Date().toISOString(), study: value.projection,
    exportScope: { policy: "selected-report-dependencies-v1", blockIds: value.selection.blocks.map(block => block.id), runIds: value.selection.runs.map(run => run.id), findingIds: [...value.selection.findingIds], artifactIds: value.selection.artifacts.map(artifact => artifact.id), excludes: ["unselected research", "private context notes/references", "assistant conversation and tool logs", "edit/attempt/version history"] },
    reportRevision: study.revision, reportHash: value.report.reportHash, rendererVersion: REPORT_RENDERER_VERSION,
    template: study.reportMeta?.template ?? "brief", language: study.reportMeta?.language ?? "en",
    warnings: value.report.warnings, resources: value.report.resources,
    pdfIncluded: Boolean(pdf), files: files.map(file => ({ name: file.name, bytes: file.bytes.length, sha256: sha(file.bytes) })),
    note: "All files bind one saved report revision and its selected dependencies. Hashes exclude manifest.json itself. This is a shareable report projection, not a full Study backup. Original saved result hashes remain historical bindings; exported file/projection hashes bind the privacy-filtered material. Query results do not verify causal conclusions.",
  };
  files.push({ name: "manifest.json", bytes: Buffer.from(JSON.stringify(manifest, null, 2)) });
  return { bytes: zip(files), manifest };
}
/** Synchronous material export retained for existing programmatic callers. The
 * production HTTP download uses exportStudyBundle and includes the real PDF. */
export function exportStudy(store: StudioStore, source: Study) {
  const study = savedExportSnapshot(store, source);
  return packageFiles(study, materials(store, study)).bytes;
}
export async function exportStudyBundle(store: StudioStore, source: Study, expectedRevision: number) {
  const study = savedExportSnapshot(store, source, expectedRevision), value = materials(store, study);
  const pdf = await renderReportPdf(value.report), bundle = packageFiles(study, value, pdf);
  return { pdf, zip: bundle.bytes, manifest: bundle.manifest, revision: study.revision, reportHash: value.report.reportHash, pdfHash: sha(pdf), zipHash: sha(bundle.bytes) };
}
