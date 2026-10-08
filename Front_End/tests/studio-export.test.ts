import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync, mkdirSync, readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { StudioStore, uuid } from "../src/server/studio/store";
import { createStudy } from "../src/server/studio/create";
import { exportStudy, exportStudyBundle, savedExportSnapshot, exportRevision } from "../src/server/studio/export";
import { renderStudyReport, resourceFigure, studyResourceSvg } from "../src/server/studio/report-renderer";
import { renderStudioFigure } from "../src/services/studio-figure";
import { saveResource } from "../src/server/studio/resources";
import type { Study } from "../src/services/studio-contracts";
import { DEFAULT_FILTERS } from "../src/services/config";

export function zipEntries(bytes: Buffer) {
  const entries = new Map<string, Buffer>();
  for (let pos = 0; bytes.readUInt32LE(pos) === 0x04034b50;) {
    const size = bytes.readUInt32LE(pos + 18), nameSize = bytes.readUInt16LE(pos + 26), extra = bytes.readUInt16LE(pos + 28);
    const start = pos + 30 + nameSize + extra;
    entries.set(bytes.subarray(pos + 30, pos + 30 + nameSize).toString(), bytes.subarray(start, start + size));
    pos = start + size;
  }
  return entries;
}
const context = { filters: { ...DEFAULT_FILTERS, source: "NSW" }, metric: "crashes" as const, notes: "", references: "" };
test("G07 a report chart exports its actual graphic, not only a CSV hyperlink", async () => {
  const dir = mkdtempSync(join(tmpdir(), "arsia-export-test-")), store = new StudioStore(join(dir, "study.sqlite"));
  try {
    let study = await createStudy(store, { kind: "analytics", title: "Actual snapshot trend", context, granularity: "yearly" });
    study = store.action(study.id, { type: "block_add", revision: study.revision, kind: "chart", runId: study.runs[0].id, refId: study.runs[0].views[0].id });
    const entries = zipEntries(exportStudy(store, study));
    const figures = [...entries.keys()].filter(name => /^figures\/.+\.svg$/.test(name));
    assert.ok(figures.length, "A CSV download is not an embedded report figure");
    assert.match(entries.get(figures[0])!.toString(), /<svg[\s>]/);
    const markdown = entries.get("report.md")!.toString();
    assert.ok(markdown.includes("![") && markdown.includes(`](${figures[0]})`), "The exported figure is embedded as a Markdown image");
  } finally { store.close(); rmSync(dir, { recursive: true, force: true }); }
});

function setup() {
  const dir = mkdtempSync(join(tmpdir(), "arsia-report-test-")), store = new StudioStore(join(dir, "study.sqlite"));
  return { dir, store, close() { store.close(); rmSync(dir, { recursive: true, force: true }); } };
}
function action(store: StudioStore, study: Study, value: Record<string, unknown>) {
  return store.action(study.id, { ...value, revision: study.revision });
}
async function add(store: StudioStore, study: Study, definitionId: string, all = false) {
  return saveResource(store, { requestId: uuid(), definitionId, context: all ? { ...context, filters: { ...context.filters, source: "All" } } : context,
    target: { studyId: study.id, revision: study.revision } });
}
test("saved reports reject missing, cross-study and tampered references without mutating the study", async () => {
  const x = setup(); try {
    let study = await add(x.store, x.store.create("Reference binding", context), "trend");
    study = action(x.store, study, { type: "block_add", kind: "resource", runId: study.runs[0].id, refId: study.runs[0].resource!.id });
    const original = structuredClone(study);
    for (const mutate of [
      (s: Study) => { s.report[0].runId = uuid(); },
      (s: Study) => { s.report[0].resultHash = "0".repeat(64); },
      (s: Study) => { s.runs[0].views[0].rows[0].value = 99999999; },
      (s: Study) => { s.runs[0].status = "failed"; },
    ]) { const copy = structuredClone(study); mutate(copy); assert.throws(() => renderStudyReport(copy)); }
    const other = x.store.create("Different study", context);
    assert.throws(() => studyResourceSvg(other, study.runs[0].id), /does not belong/);
    assert.throws(() => savedExportSnapshot(x.store, study, study.revision - 1), /revision/);
    assert.throws(() => exportRevision(new URLSearchParams("revision=0")), /saved report revision/);
    assert.deepEqual(x.store.get(study.id), original);
  } finally { x.close(); }
});

test("report text, SVG labels and source strings cannot create executable or file-reading elements", () => {
  const x = setup(); try {
    let study = x.store.create("安全研究 <script>alert(1)</script>", context);
    study = action(x.store, study, { type: "block_add", kind: "text", text: '<img src="file:///private/secret"><script>fetch("https://outside.invalid")</script>' });
    const report = renderStudyReport(study);
    assert.ok(report.html.includes("&lt;script&gt;"));
    assert.ok(!report.html.includes("<script>")); assert.ok(!report.html.includes('<img src="file:'));
    const svg = renderStudioFigure({ title: '<script>alert("x")</script>', kind: "bar", rows: [{ label: '<image href="file:///private/secret"/>', count: 3 }], x: "label", y: "count", series: null, unit: "crashes" });
    assert.ok(!svg.includes("<script>")); assert.ok(!svg.includes("<image ")); assert.ok(svg.includes("&lt;script&gt;"));
    // SVG moveto requires distinct x/y coordinates; joined digits silently hide the axis.
    const axis = /<path d="M([\d.-]+) ([\d.-]+)V([\d.-]+)" stroke="#85939f"/.exec(svg);
    assert.ok(axis, "The bar baseline must have an explicit x/y coordinate separator");
    assert.deepEqual(axis.slice(1).map(Number), [260, 68, 184]);
    assert.ok(report.html.includes("default-src 'none'"));
  } finally { x.close(); }
});

test("numeric line axes preserve positions across unequal group sizes and missing values remain gaps", () => {
  const svg = renderStudioFigure({ title: "Concentration", kind: "line", rows: [
    { source: "A", area: 0, share: 0 }, { source: "A", area: 50, share: 70 }, { source: "A", area: 100, share: 100 },
    { source: "B", area: 0, share: 0 }, { source: "B", area: 25, share: 50 }, { source: "B", area: 50, share: 80 }, { source: "B", area: 75, share: 95 }, { source: "B", area: 100, share: 100 },
  ], x: "area", y: "share", series: "source", unit: "percent" });
  const centers = [...svg.matchAll(/data-x="50" data-series="[AB]" cx="([\d.]+)"/g)].map(match => Number(match[1]));
  assert.deepEqual(centers, [411, 411]);
  const quarter = /data-x="25" data-series="B" cx="([\d.]+)"/.exec(svg)!; assert.equal(Number(quarter[1]), 247.5);
  const gaps = renderStudioFigure({ title: "Unknown", kind: "line", rows: [{ period: "a", value: 1 }, { period: "b", value: null }, { period: "c", value: 3 }], x: "period", y: "value", series: null, unit: "crashes" });
  assert.match(gaps, /<path d="M[^"]+M[^"]+" fill="none"/);
});

test("real saved map uses its copied geometry and counts; a geometry mutation fails binding", async () => {
  const x = setup(); try {
    const study = await add(x.store, x.store.create("Real map", context), "spatial-map");
    const run = study.runs[0], figure = resourceFigure(run), svg = studyResourceSvg(study, run.id);
    assert.equal(figure.kind, "map"); assert.ok(figure.map?.geojson);
    assert.match(svg, /<path d="M/); assert.match(svg, /North up/); assert.match(svg, /No external basemap/);
    assert.ok(figure.map!.counts!.some(row => row.value !== null && row.value > 0));
    const changed = structuredClone(study);
    (changed.runs[0].evidence[0].result as { boundaries: { geojson: unknown }[] }).boundaries[0].geojson = { type: "FeatureCollection", features: [] };
    assert.throws(() => studyResourceSvg(changed, run.id), /integrity|binding/);
  } finally { x.close(); }
});

test("A4 full and brief PDFs embed real plots, Chinese text and long tables; ZIP hashes bind the same revision", { timeout: 90000 }, async () => {
  const x = setup(); try {
    let study = x.store.create("道路事故研究报告 / Road crash research", context);
    for (const id of ["trend", "severity", "spatial-map", "monthly-matrix"]) study = await add(x.store, study, id, id === "monthly-matrix");
    study = action(x.store, study, { type: "report_meta", metadata: { contractVersion: 1, template: "full", language: "bilingual", title: "道路事故研究报告 / Road crash research", author: "ARSIA isolated acceptance / 隔离验收", date: "2026-10-08" } });
    study = action(x.store, study, { type: "block_add", kind: "section", text: "Methods / 方法" });
    study = action(x.store, study, { type: "block_add", kind: "text", text: "This is a zero-model report of actual admitted snapshot queries. 本报告仅用于验证导出功能，不推断因果关系。Unknown values remain unknown; no source is pooled into a national risk measure." });
    for (const run of study.runs) study = action(x.store, study, { type: "block_add", kind: "resource", runId: run.id, refId: run.resource!.id, caption: `${run.views[0].title} / 已保存的实际查询`, pageBreakBefore: run.resource!.definitionId === "monthly-matrix" });
    const fullRevision = study.revision, pending = exportStudyBundle(x.store, study, fullRevision);
    // Editing during browser rendering must not mix the later revision into output.
    study = action(x.store, study, { type: "block_add", kind: "text", text: "LATER REVISION ONLY" });
    const bundle = await pending, entries = zipEntries(bundle.zip), manifest = JSON.parse(entries.get("manifest.json")!.toString());
    assert.equal(bundle.revision, fullRevision); assert.equal(manifest.reportRevision, fullRevision);
    assert.equal(manifest.study.revision, fullRevision); assert.ok(!entries.get("report.html")!.includes(Buffer.from("LATER REVISION ONLY")));
    assert.ok(entries.get("report.pdf")!.equals(bundle.pdf)); assert.equal(bundle.pdf.subarray(0,5).toString(), "%PDF-");
    for (const file of manifest.files as { name: string; sha256: string; bytes: number }[]) {
      const data = entries.get(file.name)!; assert.ok(data); assert.equal(data.length, file.bytes); assert.equal(createHash("sha256").update(data).digest("hex"), file.sha256);
    }
    const file = join(x.dir, "full.pdf"); writeFileSync(file, bundle.pdf);
    const textPath = join(x.dir, "full.txt"); execFileSync("pdftotext", ["-layout", file, textPath]);
    const extracted = readFileSync(textPath, "utf8");
    assert.match(extracted, /道路事故研究报告/); assert.match(extracted, /Contents/); assert.match(extracted, /Figure/); assert.match(extracted, /Table/); assert.match(extracted, /NSW/); assert.match(extracted, /2024-12/);
    assert.match(extracted, new RegExp(`Revision ${fullRevision}`)); assert.ok(!extracted.includes("LATER REVISION ONLY"));
    const pages = extracted.split("\f").length - 1; assert.ok(pages >= 5, `Expected long table and cover pagination; got ${pages}`);
    const metadata = execFileSync("pdfinfo", [file], { encoding: "utf8" }); assert.match(metadata, /Page size:.*\(A4\)/);
    const dimensions = /Page size:\s+([\d.]+) x ([\d.]+)/.exec(metadata)!;
    assert.ok(Math.abs(Number(dimensions[1]) - 210 / 25.4 * 72) < 1);
    assert.ok(Math.abs(Number(dimensions[2]) - 297 / 25.4 * 72) < 1);
    // A second request for the same saved rendering inputs reuses identical PDF bytes.
    const brief = action(x.store, study, { type: "report_meta", metadata: { ...study.reportMeta!, template: "brief", language: "zh" } });
    const briefBundle = await exportStudyBundle(x.store, brief, brief.revision);
    const again = await exportStudyBundle(x.store, brief, brief.revision); assert.ok(again.pdf.equals(briefBundle.pdf));
    const evidence = process.env.ARSIA_PDF_EVIDENCE_DIR;
    if (evidence) { mkdirSync(evidence, { recursive: true }); for (const [name, bytes] of [["full.pdf", bundle.pdf], ["full.zip", bundle.zip], ["brief.pdf", briefBundle.pdf], ["brief.zip", briefBundle.zip]] as const) writeFileSync(join(evidence,name),bytes); writeFileSync(join(evidence,"full.txt"),extracted); writeFileSync(join(evidence,"manifest.json"),JSON.stringify(manifest,null,2)); writeFileSync(join(evidence,"pdf-checks.json"),JSON.stringify({ fixture: "Actual platform snapshot queries with developer-authored report text; no Agent", fullRevision, briefRevision: brief.revision, pages, fullPdfHash: bundle.pdfHash, briefPdfHash: briefBundle.pdfHash, reportHash: bundle.reportHash, pdfinfo: metadata, providerRequests: 0 },null,2)); }
  } finally { x.close(); }
});
