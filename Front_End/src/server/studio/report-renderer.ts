import { createHash } from "node:crypto";
import type { AnalysisRow } from "../../services/analysis-contracts";
import type { MapData, Response } from "../../services/contracts";
import type { ReportBlock, ResearchRun, Study } from "../../services/studio-contracts";
import { escapeXml as esc, renderStudioFigure, type StudioFigure } from "../../services/studio-figure";
import { validateStudyReport, reportMetadata, resultHash } from "./research-contract";
import { verifyResearchAsset } from "./resource-integrity";
import { StudioError } from "./store";
import { selectReportMaterials, selectedEvidence, sourceMetadata, publicMaterial } from "./report-selection";

export const REPORT_RENDERER_VERSION = "arsia-report-print-v2";
export const REPORT_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'; sandbox";
export interface ReportFile { name: string; bytes: Buffer }
export interface RenderedReport {
  html: string; markdown: string; files: ReportFile[]; reportHash: string;
  revision: number; warnings: string[]; resources: { runId: string; resultHash: string; context: unknown; query: unknown; limitations: string[] }[];
}
interface SavedResult {
  rows: AnalysisRow[]; responses: Response<unknown>[];
  boundaries?: { url: string; sha256: string; geojson: unknown }[];
}
export function resourceFigure(run: ResearchRun): StudioFigure {
  verifyResearchAsset(run);
  const resource = run.resource!, result = run.evidence.find(e => e.id === "E1")!.result as SavedResult;
  const figure: StudioFigure = { title: run.views[0].title, ...resource.display, rows: result.rows, unit: resource.unit };
  if (figure.kind === "map") {
    const map = result.responses[0]?.data as MapData | undefined;
    if (!map || map.illustrationOnly) throw new StudioError("This map has no verified printable geometry.", 422);
    figure.map = map.pointGrid ? { cells: map.pointGrid.cells, precisionDegrees: map.pointGrid.precisionDegrees }
      : { geojson: result.boundaries?.[0]?.geojson, counts: map.states
        ? map.states.map(state => ({ id: state.code, name: state.name, value: state.available ? state.count ?? null : null }))
        : map.regions.map(region => ({ id: region.id, name: region.name, value: region.count })) };
  }
  return figure;
}
export function studyResourceSvg(study: Study, runId: string): string {
  const run = study.runs.find(r => r.id === runId);
  if (!run) throw new StudioError("This saved resource does not belong to the study.", 404);
  try { return renderStudioFigure(resourceFigure(run)); }
  catch (error) { if (error instanceof StudioError) throw error; throw new StudioError(error instanceof Error ? error.message : "The saved figure cannot be rendered.", 422); }
}
const prose = (value: unknown) => esc(value).replace(/\r?\n/g, "<br>");
function table(rows: AnalysisRow[]): string {
  const columns = [...new Set(rows.flatMap(row => Object.keys(row)))];
  if (columns.length > 16 || rows.length > 10000) throw new StudioError("This table exceeds the supported report capacity.", 422);
  if (!rows.length) return '<p class="note">No observations. No zero values have been substituted.</p>';
  return `<table class="data-table ${columns.length > 8 ? "wide" : ""}"><thead><tr>${columns.map(key => `<th>${esc(key)}</th>`).join("")}</tr></thead><tbody>${rows.map(row => `<tr>${columns.map(key => `<td>${row[key] === null || row[key] === undefined ? '<span class="unknown">Unknown</span>' : esc(row[key])}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}
function checkedBlocks(study: Study): ReportBlock[] {
  try { return validateStudyReport(study); }
  catch (error) { throw new StudioError(error instanceof Error ? error.message : "Invalid report reference.", 409); }
}
const css = `
@page{size:A4;margin:18mm 17mm 20mm}*{box-sizing:border-box}html{color-scheme:light;background:white}body{margin:0;background:white;color:#20313c;font-family:Arial,"PingFang SC","Heiti SC",sans-serif;font-size:10pt;line-height:1.58;-webkit-print-color-adjust:exact;print-color-adjust:exact}main{max-width:176mm;margin:auto}h1,h2,h3{line-height:1.24;color:#102b38;break-after:avoid;overflow-wrap:anywhere}h1{font-size:27pt;letter-spacing:-.025em;margin:18mm 0 7mm}h2{font-size:16pt;margin:9mm 0 4mm;border-bottom:1px solid #becfd5;padding-bottom:2mm}h3{font-size:12pt;margin:5mm 0 2mm}p{margin:3mm 0;orphans:3;widows:3;overflow-wrap:anywhere}.eyebrow{font-size:9pt;color:#286a78;letter-spacing:.12em;font-weight:bold}.cover{padding:7mm 0 13mm;border-bottom:2px solid #286a78}.full .cover{min-height:240mm;break-after:page}.meta{font-size:9pt;color:#526471}.pill{display:inline-block;padding:1.5mm 3mm;border:1px solid #c5d6db;border-radius:2mm;font-size:8pt}.draft{padding:3mm 4mm;background:#fff7e8;border-left:3px solid #b78626;color:#635126;font-size:9pt}.scope{font-size:8pt;overflow-wrap:anywhere}.toc{break-after:page}.toc a{color:#263e4d;text-decoration:none}.toc li{padding:2mm 0;border-bottom:1px dotted #ced8dd}.report-block{margin:0 0 5mm}.break-before{break-before:page}.figure{margin:5mm 0 7mm;break-inside:avoid}.figure svg{width:100%;max-height:155mm;display:block}.half svg{max-height:100mm}.caption{font-size:9pt;color:#263f4c;margin-top:3mm}.note,.limits{font-size:8pt;color:#576876}.limits{margin:2mm 0}.data-table{width:100%;table-layout:fixed;border-collapse:collapse;font-size:8pt;line-height:1.42;margin:4mm 0}.data-table th{background:#e9f0f3;color:#203b48;text-align:left;font-weight:bold}.data-table th,.data-table td{padding:2mm;border-bottom:1px solid #d6e0e5;vertical-align:top;word-break:break-word;overflow-wrap:anywhere}.data-table.wide{font-size:6.8pt}.data-table tr{break-inside:avoid}.data-table thead{display:table-header-group}.unknown{color:#737e88;font-style:italic}.sources{font-size:8pt}.source{margin-bottom:5mm;break-inside:avoid}.source p{margin:1mm 0}.hash{font-family:monospace;font-size:7pt;overflow-wrap:anywhere}blockquote{border-left:2px solid #b6c9d0;margin:4mm 0;padding-left:4mm;color:#405967}code{font-size:8pt}ul{padding-left:6mm}.review{font-size:8pt;color:#725325}.section-block{break-after:avoid}@media screen{body{background:#e9eef1;padding:24px}main{background:#fff;padding:18mm 17mm;max-width:210mm;box-shadow:0 3px 20px #193b481f}}`;

/** Builds a self-contained document only from one already-saved Study snapshot.
 * No template field becomes a path, URL, CSS rule or executable fragment. */
export function renderStudyReport(study: Study): RenderedReport {
  const blocks = checkedBlocks(study), selection = selectReportMaterials(study), meta = reportMetadata(study.reportMeta ?? { template: "brief", language: "en", title: study.title, author: "", date: study.updatedAt.slice(0,10) }, study);
  const bilingual = meta.language === "bilingual", zh = meta.language === "zh";
  const tr = (english: string, chinese: string) => zh ? chinese : bilingual ? `${english} / ${chinese}` : english;
  const files: ReportFile[] = [], markdown: string[] = [`# ${meta.title}`, "", `${meta.author} · ${meta.date} · Revision ${study.revision}`, ""], sections: string[] = [];
  const used = new Map<string, ResearchRun>(), warnings = [tr("Draft research report: user-written interpretations have not been independently verified.", "研究报告草稿：人工撰写的解释尚未独立核验。")];
  let figureNumber = 0, tableNumber = 0;
  const scope = (run: ResearchRun) => { const f = run.context.filters; return `${f.source} · ${f.dateRange.from} - ${f.dateRange.to} · ${f.datasetVersion} · batch ${f.batchId}${f.releaseId ? ` · release ${f.releaseId}` : ""}`; };
  function selectRun(id: string | undefined): ResearchRun {
    const run = study.runs.find(r => r.id === id && r.status === "complete");
    if (!run) throw new StudioError("A report reference has no completed analysis in this study.", 409);
    if (run.resource) verifyResearchAsset(run); used.set(run.id, run); return run;
  }
  const sourceNumber = (runId: string) => [...used.keys()].indexOf(runId) + 1;
  function draw(b: ReportBlock, run: ResearchRun, figure: StudioFigure) {
    const isTable = b.kind === "table" || figure.kind === "table" || figure.kind === "kpi";
    const title = b.text || figure.title, label = isTable ? `${tr("Table", "表")} ${++tableNumber}` : `${tr("Figure", "图")} ${++figureNumber}`;
    const note = `${label}. ${b.caption || title} [${sourceNumber(run.id)}]`;
    if (isTable) { markdown.push(`### ${note}`, `Scope: ${scope(run)}`, ""); return `<div class="report-block"><h3>${esc(note)}</h3><p class="scope">${esc(scope(run))} · ${esc(figure.unit)}</p>${table(figure.rows)}</div>`; }
    // Bars with many categories are printed in explicit contiguous panels, never dropped.
    const chunks = figure.kind === "bar" && figure.rows.length > 22 ? Array.from({ length: Math.ceil(figure.rows.length / 22) }, (_, index) => figure.rows.slice(index * 22, (index + 1) * 22)) : [figure.rows];
    return chunks.map((rows, index) => {
      const name = `figures/${b.id}${chunks.length > 1 ? `-${index + 1}` : ""}.svg`;
      const rendered = renderStudioFigure({ ...figure, title, rows });
      files.push({ name, bytes: Buffer.from(rendered) });
      markdown.push(`![${note}](${name})`, `Scope: ${scope(run)}`, `Unit: ${figure.unit}`, "");
      return `<figure class="figure ${b.size === "half" ? "half" : ""}">${rendered}<figcaption class="caption"><strong>${esc(note)}</strong>${chunks.length > 1 ? ` (${index + 1}/${chunks.length})` : ""}</figcaption><p class="scope">${esc(scope(run))} · ${esc(figure.unit)}</p>${run.resource?.limitations.map(limit => `<p class="limits">${esc(limit)}</p>`).join("") ?? ""}</figure>`;
    }).join("");
  }
  for (const b of blocks) {
    if (b.answerSource) selectRun(b.answerSource.runId);
    for (const citation of b.citations ?? []) selectRun(citation.runId);
    let html = "";
    const blockCitations = [...(b.citations ?? [])];
    if (b.kind === "title" || b.kind === "section") { if (b.kind === "title" && b.text === meta.title) continue; html = `<h2 id="section-${esc(b.id)}">${esc(b.text)}</h2>`; markdown.push(`## ${b.text}`, ""); }
    else if (b.kind === "text") { html = `<p>${prose(b.text)}</p>`; markdown.push(b.text, ""); }
    else if (b.kind === "finding") {
      const finding = study.findings.find(f => f.id === b.refId)!;
      if (finding.runId && finding.evidenceIds.length) selectRun(finding.runId);
      for (const ref of finding.evidenceRefs ?? []) { selectRun(ref.runId); if (!blockCitations.some(item => item.runId === ref.runId && item.evidenceId === ref.evidenceId)) blockCitations.push(ref); }
      if (!(finding.evidenceRefs?.length) && finding.runId) for (const evidenceId of finding.evidenceIds) blockCitations.push({ runId: finding.runId, evidenceId, attempt: study.runs.find(run => run.id === finding.runId)!.attempt, resultHash: "" });
      const checks = finding.checks;
      html = `<h3>${esc(b.text || finding.title)}</h3><span class="pill">${esc(finding.kind)}</span><p>${prose(finding.explanation)}</p><p class="review">${esc(checks ? `Evidence linked: ${checks.evidenceLinked}; numeric checked: ${checks.numericChecked}; review needed: ${checks.reviewNeeded}; user reviewed: ${checks.userReviewed}` : tr("No independent checks recorded.", "未记录独立核验。"))}</p><p class="limits">${prose(finding.limitations)}</p>`;
      markdown.push(`### ${b.text || finding.title}`, finding.kind, finding.explanation, finding.limitations, "");
    } else if (b.kind === "resource") { const run = selectRun(b.runId); html = draw(b, run, resourceFigure(run)); }
    else if (b.kind === "chart" || b.kind === "table") { const run = selectRun(b.runId), view = run.views.find(v => v.id === b.refId)!; const evidence = run.evidence.find(e => e.id === view.evidenceId);
      if (!evidence || !(evidence.query?.validated || evidence.query?.assurance?.parameters === "validated")) throw new StudioError("A report view requires its saved host-validated evidence.", 409);
      html = draw(b, run, run.resource && b.kind === "chart" ? resourceFigure(run) : { ...view, unit: run.resource?.unit ?? run.context.metric });
    } else if (b.kind === "evidence") { const run = selectRun(b.runId), evidence = run.evidence.find(e => e.id === b.refId)!; html = `<h3>${esc(b.text || evidence.title)}</h3><p>${prose(evidence.description)}</p><p class="scope">${esc(scope(run))}</p>`; markdown.push(`### ${b.text || evidence.title}`, evidence.description, ""); }
    else if (b.kind === "artifact") { const artifact = study.artifacts.find(a => a.id === b.refId)!; html = `<h3>${esc(b.text || artifact.name)}</h3><p>${esc(tr("Attached research material", "研究附件"))}: ${esc(artifact.name)} (${esc(artifact.kind)}, ${artifact.bytes} bytes). ${esc(tr("Included in the ZIP material package.", "已包含在 ZIP 材料包中。"))}</p><p class="hash">SHA-256 ${esc(artifact.sha256)}</p>`; markdown.push(`[${b.text || artifact.name}](attachments/${artifact.id}-${artifact.name})`, ""); }
    if (b.answerSource) {
      const note = tr("AI draft — review before using. Linked evidence does not verify the wording or interpretation.", "AI 草稿，请核阅后使用。关联证据不代表文字及解读已经核实。") + (!blockCitations.length ? ` ${tr("No linked data evidence.", "没有关联的数据证据。")}` : "");
      html += `<p class="review">${esc(note)}</p>`;
      markdown.push(note, "");
    }
    const citations = blockCitations.map(ref => `[${sourceNumber(ref.runId)}] ${ref.evidenceId}`).join("; ");
    if (citations) markdown.push(`${tr("Sources", "来源")}: ${citations}`, "");
    sections.push(`<section class="report-block ${b.pageBreakBefore ? "break-before" : ""} ${b.kind === "section" ? "section-block" : ""}">${html}${citations ? `<p class="note">${esc(tr("Sources", "来源"))}: ${esc(citations)}</p>` : ""}</section>`);
  }
  if (!blocks.length) sections.push(`<p class="draft">${esc(tr("No report content selected. Add saved findings and resources before finalising.", "尚未选择报告内容。请加入已保存的发现和资源。"))}</p>`);
  for (const run of selection.runs) if (!used.has(run.id)) used.set(run.id, run);
  const resources = [...used.values()].map(run => ({ runId: run.id, resultHash: run.resource?.resultHash ?? (!selectedEvidence(run, selection).length && blocks.some(b => b.answerSource?.runId === run.id) ? resultHash(run.answer) : resultHash({ evidence: run.evidence, views: run.views })), context: publicMaterial(run.context), query: run.resource?.query ?? selectedEvidence(run, selection).map(e => publicMaterial(e.query)), limitations: run.resource?.limitations ?? [] }));
  const answerOnly = (run: ResearchRun) => !selectedEvidence(run, selection).length && blocks.some(b => b.answerSource?.runId === run.id);
  const sources = [...used.values()].map((run, i) => {
    const raw = sourceMetadata(selectedEvidence(run, selection));
    const refs = raw.flatMap(meta => meta.evidence ?? []);
    const selectedTitle = run.views.find(view => selection.viewIds.get(run.id)?.has(view.id))?.title || selectedEvidence(run, selection)[0]?.title || (answerOnly(run) ? tr("Assistant response — no linked data evidence", "助手回答，没有关联的数据证据") : tr("Saved source evidence", "已保存的来源证据"));
    return `<div class="source"><h3>[${i + 1}] ${esc(selectedTitle)}</h3><p>${esc(scope(run))}</p>${raw.map(meta => `<p>${esc(meta.definition)}</p><p>Source coverage: ${esc(meta.coverage.from)} - ${esc(meta.coverage.to)}; availability: ${esc(meta.availability)}</p>`).join("")}${run.resource?.actualCoverage.map(coverage => `<p>Actual selected coverage: ${esc(coverage.from)} - ${esc(coverage.to)}; complete: ${esc(coverage.complete)}</p>`).join("") ?? ""}${refs.map(ref => `<p>${esc(ref.title)}: ${esc(ref.description)}${ref.href ? ` · ${esc(ref.href)}` : ""}</p>`).join("")}<p class="hash">${answerOnly(run) ? "Response" : "Result"} SHA-256: ${esc(resources[i].resultHash)}</p>${run.resource?.limitations.map(limit => `<p>${esc(limit)}</p>`).join("") ?? ""}<p>${esc(tr("Source retrieval date is not asserted unless present in the saved source evidence.", "如保存证据未提供，本报告不推定来源获取日期。"))}</p></div>`;
  }).join("");
  const title = esc(meta.title), f = study.context.filters;
  const cover = `<header class="cover"><div class="eyebrow">ARSIA · ${esc(tr(meta.template === "full" ? "RESEARCH REPORT" : "RESEARCH BRIEF", meta.template === "full" ? "研究报告" : "研究简报"))}</div><h1>${title}</h1><p>${esc(meta.author || tr("Author not specified", "未填写作者"))}</p><p class="meta">${esc(meta.date)} · ${esc(tr("Saved revision", "保存版本"))} ${study.revision}</p><p class="scope">${esc(f.source)} · ${esc(f.dateRange.from)} - ${esc(f.dateRange.to)}<br>${esc(f.datasetVersion)} · ${esc(f.batchId)}${f.releaseId ? `<br>Release: ${esc(f.releaseId)}` : ""}</p><p class="draft">${esc(warnings[0])}</p><p class="note">${esc(tr("Research use. Not an official government report or a publication approval.", "研究用途。不代表政府官方报告或发布批准。"))}</p></header>`;
  const toc = meta.template === "full" ? `<nav class="toc"><h2>${esc(tr("Contents", "目录"))}</h2><ol>${blocks.filter(b => ["section", "title"].includes(b.kind) && b.text !== meta.title).map(b => `<li><a href="#section-${esc(b.id)}">${esc(b.text)}</a></li>`).join("")}<li><a href="#sources">${esc(tr("Sources and limitations", "来源与限制"))}</a></li></ol></nav>` : "";
  const end = `<section class="sources"><h2 id="sources">${esc(tr("Sources and limitations", "来源与限制"))}</h2><p>${esc(tr("Counts are not exposure-adjusted risk. Sources retain independent definitions. Spatial aggregates are not exact accident locations. Query success does not verify causal explanations.", "数量不等于暴露校正风险。各来源保留独立口径。空间汇总不代表精确事故地点。查询成功不能证明因果解释。"))}</p>${sources || `<p>${esc(tr("No data sources selected in this report.", "本报告未选择数据来源。"))}</p>`}</section>`;
  const html = `<!doctype html><html lang="${zh ? "zh-Hans" : "en"}"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${REPORT_CSP}"><meta name="viewport" content="width=device-width, initial-scale=1"><title>${title}</title><style>${css}</style></head><body class="${meta.template}"><main>${cover}${toc}${sections.join("")}${end}</main></body></html>`;
  if (Buffer.byteLength(html) > 16000000) throw new StudioError("The selected report exceeds the bounded document capacity.", 422);
  const reportHash = createHash("sha256").update(JSON.stringify({ studyId: study.id, revision: study.revision, blocks, meta, resources, renderer: REPORT_RENDERER_VERSION })).digest("hex");
  markdown.push("## Sources and limitations", "Counts are not exposure-adjusted risk. Each source retains its own definitions.", ...resources.map((resource, index) => {
    const run = used.get(resource.runId)!;
    return `[${index + 1}] Run ${resource.runId} · ${answerOnly(run) ? "Response" : "Result"} SHA-256 ${resource.resultHash}\n${scope(run)}\n${sourceMetadata(selectedEvidence(run, selection)).map(meta => `${meta.definition}\nSource coverage: ${meta.coverage.from} - ${meta.coverage.to}\n${meta.evidence.map(ref => `${ref.title}: ${ref.description}${ref.href ? ` · ${ref.href}` : ""}`).join("\n")}`).join("\n")}\n${resource.limitations.join("\n")}`;
  }));
  return { html, markdown: markdown.join("\n"), files, reportHash, revision: study.revision, warnings, resources };
}
