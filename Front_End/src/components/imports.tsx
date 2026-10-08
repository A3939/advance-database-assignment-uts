"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, CheckCircle2, FileText, Loader2, RefreshCw, Sparkles, UploadCloud, X } from "lucide-react";
import { Button } from "./ui/button";
import { localImports as defaultImports, isolatedImports } from "@/services/imports-client";
import { importAction, importSuggestedAction, importOutcomeLabel, IMPORT_TERMINAL, validateImportFiles, type LocalImportAdvice, type LocalImportCatalog, type LocalImportHealth, type LocalImportJob, type LocalImportQA } from "@/services/imports-contracts";
import Link from "next/link";
import { analysisHref, DEFAULT_VIEW } from "@/services/analysis-state";
import { LOCAL_VERSION, coverageMonthRange } from "@/services/catalog-contracts";
import { ImportPreprocessingQuality } from './import-preprocessing-quality';
import type { PreprocessingQuality } from '../services/preprocessing-contracts';
import styles from "./imports.module.css";
import { ImportAgentProgress } from './import-agent-progress';
import { ImportEvidence } from './import-evidence';
import { ImportStorage } from './import-storage';
import type { LocalImportStorage } from '@/services/imports-contracts';

const bytes = (n: number) => n < 1024 * 1024 ? `${(n / 1024).toFixed(1)} KiB` : `${(n / 1024 / 1024).toFixed(1)} MiB`;
const statusName = (status: string) => status.replaceAll("_", " ");
const value = (v: unknown) => v === null || v === undefined ? "Unknown" : typeof v === "number" ? v.toLocaleString("en-AU") : String(v);
const questionText = (q: NonNullable<LocalImportJob["questions"]>[number]) => typeof q === "string" ? q : q.question || q.message || JSON.stringify(q);
const metrics = [["crash_count", "Crash records"], ["fatal_crash_count", "Fatal crashes"], ["fatalities", "Lives lost"], ["casualties", "Casualties"]] as const;

function ResultView({ result }: { result: Record<string, unknown> }) {
  const summary = (result.summary || result) as Record<string, unknown>;
  const trend = Array.isArray(result.trend) ? result.trend as Record<string, unknown>[] : [];
  const limitations = Array.isArray(result.limitations) ? result.limitations as string[] : [];
  const units = result.units as { status?: string; reason?: string } | undefined;
  return <div className={styles.result}>
    <div className={styles.metrics}>{metrics.map(([key, label]) => <div key={key}><span>{label}</span><strong>{value(summary[key])}</strong></div>)}</div>
    <p className={styles.note}>{value(summary.raw_record_count)} raw records · {units?.status === "unavailable" ? "Unit reporting unavailable" : `${value(summary.unit_count)} unit records`} · {value(summary.excluded_crash_count)} crash records outside the admitted scope. Raw records include different table grains.</p>
    {units?.status === "unavailable" && units.reason && <p className={styles.note}>{units.reason}</p>}
    <ImportPreprocessingQuality report={result.quality_report as PreprocessingQuality | undefined} official={(result.publication_gate as {official_registration?:boolean} | undefined)?.official_registration} goalSatisfied={(result.research_context as {target_satisfied?:boolean} | undefined)?.target_satisfied} />
    {!!trend.length && <div className={styles.tableScroll}><table><caption>Annual LOCAL TEST aggregates · one source</caption><thead><tr><th>Year</th>{metrics.map(([key, label]) => <th key={key}>{label}</th>)}</tr></thead><tbody>{trend.map((row, index) => <tr key={index}><th>{String(row.year ?? "Unknown")}</th>{metrics.map(([key]) => <td key={key}>{value(row[key])}</td>)}</tr>)}</tbody></table></div>}
    {!!limitations.length && <ul className={styles.limitations}>{limitations.map((text, i) => <li key={i}>{text}</li>)}</ul>}
  </div>;
}
function Quality({ qa }: { qa: LocalImportQA[] }) {
  return <ul className={styles.qa}>{qa.map((check, index) => <li key={`${check.code}-${index}`}><span className={styles.badge} data-status={check.status}>{check.status}</span><div><strong>{check.code}</strong><p>{check.message}</p>{check.metrics && <details><summary>Check values</summary><pre>{JSON.stringify(check.metrics, null, 2)}</pre></details>}</div></li>)}</ul>;
}

export function LocalImportsPage({ isolated = false, embedded = false }: { isolated?: boolean; embedded?: boolean }) {
  const localImports = isolated ? isolatedImports : defaultImports;
  const [health, setHealth] = useState<LocalImportHealth | null>(null);
  const [storage, setStorage] = useState<LocalImportStorage | null>(null);
  const [jobs, setJobs] = useState<LocalImportJob[]>([]);
  const [catalog, setCatalog] = useState<LocalImportCatalog | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<LocalImportJob | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [label, setLabel] = useState("");
  const [source, setSource] = useState("");
  const [answers,setAnswers] = useState("");
  const knownRelease = useRef<string | null>(null);
  const [profile, setProfile] = useState("");
  const [reviewed, setReviewed] = useState(false);
  const [sourceContext, setSourceContext] = useState("");
  const [advice, setAdvice] = useState<LocalImportAdvice | null>(null);
  const [busy, setBusy] = useState("");
  const [upload, setUpload] = useState<{ name: string; sent: number; total: number } | null>(null);
  const [error, setError] = useState("");
  const [serviceError, setServiceError] = useState("");
  const [notice, setNotice] = useState("");
  const [evidence, setEvidence] = useState<{ jobId: string; data: Record<string, unknown> } | null>(null);
  const [report, setReport] = useState<{ source: string; release: string; data: Record<string, unknown> } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const mappingEditor = useRef<HTMLDetailsElement>(null);
  const uploadControl = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const requestId = useRef<string | null>(null);
  const refresh = useCallback(async (signal?: AbortSignal) => {
    const outcomes = await Promise.allSettled([localImports.health(signal), localImports.jobs(signal), localImports.catalog(signal)]);
    if (signal?.aborted || !mounted.current) return;
    const [h, j, c] = outcomes;
    if (h.status === "fulfilled") {
      setHealth(h.value);
      const capabilities = h.value.capabilities;
      if (capabilities && typeof capabilities === 'object' && 'storage' in capabilities && capabilities.storage === true) {
        try { const status = await localImports.storage(signal); if (!signal?.aborted && mounted.current) setStorage(status); }
        catch { /* Storage observability never prevents upload on an older backend. */ }
      } else setStorage(null);
    } else { setHealth(null); setStorage(null); }
    if (j.status === "fulfilled") setJobs(j.value.jobs);
    if (c.status === "fulfilled") { setCatalog(c.value); if (c.value.release_id !== knownRelease.current) { knownRelease.current = c.value.release_id; if (!isolated) window.dispatchEvent(new Event("arsia:publication")); } }
    const rejected = outcomes.find(outcome => outcome.status === "rejected");
    setServiceError(rejected?.status === "rejected" ? rejected.reason instanceof Error ? rejected.reason.message : "The local import service is unavailable." : "");
  }, [localImports, isolated]);
  useEffect(() => {
    mounted.current = true;
    const control = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      await refresh(control.signal);
      if (!control.signal.aborted) timer = setTimeout(poll, 3000);
    };
    void poll();
    return () => { mounted.current = false; control.abort(); clearTimeout(timer); uploadControl.current?.abort(); };
  }, [refresh]);
  useEffect(() => {
    if (!selectedId) return;
    const control = new AbortController(); let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const job = await localImports.job(selectedId, control.signal);
        if (!control.signal.aborted) { setSelected(current => current?.id === job.id && current.updated_at > job.updated_at ? current : job); timer = setTimeout(poll, (job.outcome?.terminal_for_task_mode || IMPORT_TERMINAL.has(job.status)) ? 8000 : 1500); }
      } catch (err) {
        if (!control.signal.aborted) { setServiceError(err instanceof Error ? err.message : "Could not read job status."); timer = setTimeout(poll, 5000); }
      }
    };
    void poll();
    return () => { control.abort(); clearTimeout(timer); };
  }, [selectedId, localImports]);
  const schemaDetails = selected?.error && typeof selected.error === "object" && selected.error.details && typeof selected.error.details === "object" ? selected.error.details as Record<string, unknown> : null;
  const systemBlockers = Array.isArray(schemaDetails?.blockers) ? schemaDetails.blockers.filter((value): value is { kind: string; responsible_party: string; message: string } =>
    !!value && typeof value === "object" && value.responsible_party === "system" && typeof value.message === "string" && ["unsupported_capability", "environment_dependency"].includes(value.kind)) : [];
  const editable = selected ? importSuggestedAction(selected, "add_files") && importSuggestedAction(selected, "submit") : false;
  const canAssist = !isolated && selected && importSuggestedAction(selected, "submit") && selected.status === "needs_input" && Array.isArray(schemaDetails?.schemas) && schemaDetails.schemas.length > 0;
  const canCancel = selected && importAction(selected, "cancel");
  function chooseJob(job: LocalImportJob) {
    setSelectedId(job.id); setSelected(job); setFiles([]); setProfile(""); setReviewed(false); setEvidence(null); setError(""); setNotice(""); setAdvice(null); setSourceContext(""); setAnswers("");
  }
  function newBundle() {
    setSelectedId(null); setSelected(null); setFiles([]); setLabel(""); setSource(""); setProfile(""); setReviewed(false); setEvidence(null); setError(""); setNotice(""); setAdvice(null); setSourceContext(""); setAnswers(""); requestId.current = null;
  }
  function addFiles(incoming: FileList | null) {
    if (!incoming) return;
    const next = [...files, ...Array.from(incoming)];
    try { validateImportFiles(next, editable ? selected!.files : []); setFiles(next); setError(""); }
    catch (err) { setError(err instanceof Error ? err.message : "These files cannot be selected."); }
    if (input.current) input.current.value = "";
  }
  function mapping() {
    if (!profile.trim()) return undefined;
    if (new TextEncoder().encode(profile).length > 250 * 1024) throw Error("The mapping profile must fit within 250 KiB.");
    if (!reviewed) throw Error("Review the source mapping and confirm its meaning before submitting it.");
    try {
      const parsed = JSON.parse(profile);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw Error();
      return { ...parsed, confirmed: true };
    } catch { throw Error("The reviewed profile must be a valid JSON object."); }
  }
  async function uploadAndRun() {
    setError(""); setNotice("");
    let admitted: LocalImportJob | null = editable ? selected : null;
    try {
      const approved = mapping();
      validateImportFiles(files, admitted?.files || []);
      const control = new AbortController(); uploadControl.current = control;
      setBusy("upload");
      if (!admitted) {
        requestId.current ||= crypto.randomUUID();
        admitted = await localImports.create(label.trim() || "Untitled import", source, requestId.current, control.signal);
        setSelectedId(admitted.id); setSelected(admitted);
        requestId.current = null;
      }
      for (const file of files) {
        setUpload({ name: file.name, sent: 0, total: file.size });
        admitted = await localImports.upload(admitted.id, file, control.signal, sent => setUpload({ name: file.name, sent, total: file.size }));
        setSelected(admitted); setFiles(current => current.filter(item => item !== file));
      }
      control.signal.throwIfAborted();
      setUpload(null); setBusy("submit");
      const submitted = await localImports.submit(admitted.id, approved, answers);
      setSelected(submitted); setNotice("Bundle submitted. The worker will process it in the background; you can leave this page.");
      await refresh();
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") setNotice("Upload stopped. Completed files remain attached; incomplete files are discarded. The job has not been submitted.");
      else setError(err instanceof Error ? err.message : "The import could not be submitted.");
      if (admitted) { void localImports.job(admitted.id).then(setSelected).catch(() => {}); }
    } finally { setBusy(""); setUpload(null); uploadControl.current = null; }
  }
  async function act(action: "submit" | "cancel" | "retry" | "evidence") {
    if (!selected) return;
    setBusy(action); setError(""); setNotice("");
    try {
      if (action === "evidence") setEvidence({ jobId: selected.id, data: await localImports.evidence(selected.id) });
      else {
        const job = action === "submit" ? await localImports.submit(selected.id, mapping(), answers) : action === "cancel" ? await localImports.cancel(selected.id) : await localImports.retry(selected.id);
        setSelected(job); await refresh();
      }
    } catch (err) { setError(err instanceof Error ? err.message : "The operation could not be completed."); }
    finally { setBusy(""); }
  }
  async function openReport(sourceId: string) {
    if (!catalog?.release_id) return;
    const release = catalog.release_id;
    setBusy("report"); setError("");
    try { setReport({ source: sourceId, release, data: await localImports.report(sourceId, release) }); }
    catch (err) { setError(err instanceof Error ? err.message : "The published result could not be read."); }
    finally { setBusy(""); }
  }
  function downloadEvidence() {
    if (!evidence) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify(evidence.data, null, 2)], { type: "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = `local-test-${evidence.jobId}-evidence.json`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  async function askSchema() {
    if (!selected || !canAssist) return;
    setBusy("assist"); setError("");
    try { setAdvice(await localImports.assist(selected.id, sourceContext)); }
    catch (err) { setError(err instanceof Error ? err.message : "Schema assistance is unavailable. You can still supply a reviewed profile."); }
    finally { setBusy(""); }
  }
  function useDraft() {
    if (!advice?.draft_profile) return;
    setProfile(JSON.stringify({ ...advice.draft_profile, confirmed: false }, null, 2)); setReviewed(false);
    if (mappingEditor.current) { mappingEditor.current.open = true; mappingEditor.current.scrollIntoView({ block: "center" }); }
    setNotice("Draft copied to the mapping editor. Complete missing facts, review the source definitions, then explicitly confirm the profile before running.");
  }

  return <div className={`${embedded ? styles.embedded : "secondary-page"} ${styles.page}`}>
    <ImportStorage storage={storage} />
    <div className={embedded ? styles.embeddedHeading : "page-heading"}><div>{!embedded && <span className="eyebrow">DATA INGESTION · LOCAL TEST</span>}{embedded ? <h2>Add a dataset</h2> : <h1>From source files to evidence.</h1>}<p className={embedded ? styles.note : "page-subtitle"}>Upload related source files and documentation. Existing investigation, validation and publication rules apply.</p></div><Button variant="outline" size="sm" disabled={!!busy} onClick={() => void refresh()}><RefreshCw size={16} /> Refresh status</Button></div>
    <div className={styles.boundary}><div><strong>{isolated ? "ISOLATED UPLOAD TEST · 独立测试环境" : "Local integration environment"}</strong><p>{isolated ? "本页使用独立空数据库。导入结果仅在这里查看，不改变原网站的数据、Overview、Analytics 或 Studio。" : "Successful imports join Overview, Analytics, Ask AI and Studio in a versioned local release. Original data and historical snapshots remain unchanged."}</p></div><span className={styles.badge} data-status={health?.worker?.alive ? "pass" : "limited"}>{health?.worker?.alive ? "Worker online · one heavy job at a time" : "Worker unavailable"}</span></div>
    {!isolated && <p className={styles.note}><Link className="text-link" href="/imports/test">Open isolated upload test · 独立测试，不修改当前网站数据</Link></p>}
    {isolated && <div className={styles.notice}><strong>SA · 2020–2024 官方原始数据</strong><p>先下载 ZIP，再点击 Browse files 选择它，最后点击 Upload &amp; run。无需解压或填写映射。导入后在本页查看结果。</p><a className="text-link" href="/api/imports-test/sample" download>Download SA test ZIP (4.75 MiB)</a></div>}
    {serviceError && <div className={styles.error} role="alert"><strong>Local import service unavailable</strong><p>{serviceError}</p><p>Existing dashboard data remains available. Saved jobs will reappear when the local service returns.</p></div>}
    {error && <div className={styles.error} role="alert">{error}</div>}
    {notice && <div className={styles.notice} role="status">{notice}</div>}
    <div className={styles.layout}>
      <aside className={styles.sidebar}>
        <div className={styles.sectionHeading}><h2>Import jobs</h2><Button variant="outline" size="sm" onClick={newBundle} disabled={!!busy}>New bundle</Button></div>
        <p className={styles.note}>Progress comes from the worker. Closing this page does not cancel a submitted job.</p>
        <div className={styles.jobs}>{jobs.length ? jobs.map(job => <button key={job.id} type="button" className={styles.job} aria-pressed={selectedId === job.id} onClick={() => chooseJob(job)} disabled={!!busy}><div><strong>{job.label || "Untitled import"}</strong><span className={styles.badge} data-status={job.status}>{importOutcomeLabel(job)}</span></div><small>{job.source_id || "Source pending"} · {job.files?.length || 0} files · attempt {job.attempt}</small><small>{new Date(job.updated_at).toLocaleString()}</small></button>) : <p className={styles.empty}>{serviceError ? "The import list is unavailable until the local service returns." : "No local imports yet. Start with a complete single-state bundle."}</p>}</div>
      </aside>
      <section className={styles.detail} aria-label="Import workspace">
        {(!selected || editable) && <section className={styles.card}>
          <div className={styles.sectionHeading}><h2>{selected ? "Complete this bundle" : "Upload a source bundle"}</h2><UploadCloud size={21} /></div>
          {!selected && <div className={styles.formRow}><label>Import name<input value={label} maxLength={120} onChange={e => setLabel(e.target.value)} placeholder="e.g. NSW 2020–2024" disabled={!!busy} /></label><label>Source context (optional)<input value={source} maxLength={100} onChange={e=>setSource(e.target.value)} placeholder="Dataset name or jurisdiction, if known" disabled={!!busy} /></label></div>}
          <div className={styles.drop} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); if (!busy) addFiles(e.dataTransfer.files); }}><UploadCloud size={28} /><strong>Choose data files and supporting documents</strong><p>Include related crash, unit or casualty tables together. A data dictionary or official source link helps establish their meaning.</p><p>CSV, XLSX, XLS, ZIP, JSON or GeoJSON, with optional TXT, Markdown or PDF documentation. 512 MiB per file, 1 GiB and 12 files per bundle. Processing continues in the background.</p><input ref={input} type="file" multiple accept=".csv,.xlsx,.xls,.zip,.json,.geojson,.txt,.md,.pdf" aria-label="Import data files" onChange={e => addFiles(e.target.files)} disabled={!!busy} /><Button variant="outline" onClick={() => input.current?.click()} disabled={!!busy}>Browse files</Button></div>
          {!!files.length && <ul className={styles.files}>{files.map((file, index) => <li key={`${file.name}-${index}`}><FileText size={17} /><span><strong>{file.name}</strong><small>{bytes(file.size)} · ready to upload</small></span><Button variant="ghost" size="icon" aria-label={`Remove ${file.name}`} disabled={!!busy} onClick={() => setFiles(current => current.filter((_, i) => i !== index))}><X size={16} /></Button></li>)}</ul>}
          <details ref={mappingEditor} className={styles.mapping}><summary>Advanced: reviewed manual profile (optional)</summary><p>Normal imports use the autonomous Agent and do not need a profile. This compatibility option accepts an explicitly reviewed generic-v1 mapping; it does not replace trusted validation.</p><label>Mapping profile (JSON)<textarea value={profile} onChange={e => { setProfile(e.target.value); setReviewed(false); }} rows={10} spellCheck={false} placeholder="Paste the complete reviewed generic-v1 profile JSON here. The processor validates the profile and file relationships before publication." disabled={!!busy} /></label><label className={styles.checkbox}><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)} disabled={!!busy || !profile.trim()} />I reviewed this mapping against the source documentation. Unknown facts remain unknown.</label><p className={styles.note}>Checking this box explicitly confirms the submitted profile for a local test. An AI draft alone cannot authorize execution; deterministic checks still apply.</p></details>
          {upload && <div className={styles.uploadProgress} role="status"><span>Uploading {upload.name} · {bytes(upload.sent)} / {bytes(upload.total)}</span><progress value={upload.sent} max={upload.total} /><span>After transfer, the server checks and seals the file.</span></div>}
          <div className={styles.actions}><Button disabled={!files.length || !!busy || !health} onClick={() => void uploadAndRun()}>{busy === "upload" || busy === "submit" ? <Loader2 size={16} className="spin" /> : <ArrowRight size={16} />}{selected ? "Add files & resume" : "Upload & run"}</Button>{busy === "upload" && <Button variant="outline" onClick={() => uploadControl.current?.abort()}>Stop upload</Button>}{selected && !!selected.files.length && <Button variant="outline" disabled={!!busy || !!files.length || !health} onClick={() => void act("submit")}>Run current bundle</Button>}</div>
        </section>}
        {selected && <section className={styles.card} aria-label="Selected job">
          <div className={styles.sectionHeading}><div><span className={styles.eyebrow}>LOCAL TEST JOB</span><h2>{selected.label || "Untitled import"}</h2></div><span className={styles.badge} data-status={selected.status}>{importOutcomeLabel(selected)}</span></div>
          {!selected.agent && <p className={styles.message} role="status">{selected.message || statusName(selected.stage)}</p>}
          {selected.agent ? <ImportAgentProgress agent={selected.agent} systemBlocked={systemBlockers.length > 0} /> : !!selected.events.length && <div className={styles.note}><strong>Recent automatic work</strong><ul>{selected.events.slice(-3).map((event,i)=><li key={`${event.at}-${i}`}>{event.message}</li>)}</ul></div>}
          <dl className={styles.identity}><div><dt>Source</dt><dd>{selected.source_id || "Not identified"}</dd></div><div><dt>Attempt</dt><dd>{selected.attempt}</dd></div><div><dt>Job</dt><dd>{selected.id}</dd></div>{selected.batch_id && <div><dt>Batch</dt><dd>{selected.batch_id}</dd></div>}{selected.release_id && <div><dt>Local release</dt><dd>{selected.release_id}</dd></div>}</dl>
          {selected.error && selected.outcome?.phase !== "candidate_verified" && <div className={styles.error}>{typeof selected.error === "string" ? selected.error : selected.error.message}</div>}
          {!!systemBlockers.length && <div className={styles.questions} role="status"><h3>System update required</h3><ul>{systemBlockers.map((issue, i) => <li key={i}>{issue.message}</li>)}</ul><p>This import is waiting for a supported capability or environment update. Its files and progress are saved. An additional data definition will not resolve this system limitation.</p></div>}
          {importSuggestedAction(selected, "submit") && !systemBlockers.length && !!selected.questions?.length && <div className={styles.questions}><h3>Information needed</h3><ul>{selected.questions.map((q, i) => <li key={i}>{questionText(q)}</li>)}</ul><p>Answer the specific questions below or add supporting files above. The Agent resumes from its saved work; published sources remain available.</p><label>Additional information<textarea rows={4} maxLength={12000} value={answers} onChange={e=>setAnswers(e.target.value)} placeholder="Provide the missing definition, official URL or clarification." disabled={!!busy} /></label><Button disabled={!!busy || !answers.trim()} onClick={()=>void act("submit")}>Send answer & resume</Button></div>}
          {canAssist && <details><summary>Advanced schema assistance</summary><section className={styles.advisor} aria-label="Schema assistance"><h3>Understand the uploaded schema</h3><p>AI can suggest questions and an unconfirmed mapping draft. Only filenames, sheet and column names, plus the public source definitions you enter here, are sent to the model. No uploaded rows are sent.</p><label>Public source definitions (optional)<textarea value={sourceContext} maxLength={6000} rows={4} onChange={e => setSourceContext(e.target.value)} placeholder="Paste relevant public field definitions, source coverage and severity meanings. Do not include personal records or private credentials." disabled={!!busy} /></label><Button variant="outline" disabled={!!busy} onClick={() => void askSchema()}>{busy === "assist" ? <Loader2 size={16} className="spin" /> : <Sparkles size={16} />}Ask AI about this schema</Button>{advice && <div className={styles.advice} role="status"><strong>Draft guidance · not approved for execution</strong><p>{advice.summary}</p>{!!advice.questions.length && <ul>{advice.questions.map((question, i) => <li key={i}>{question}</li>)}</ul>}{advice.draft_profile && <><details><summary>Inspect the unconfirmed draft</summary><pre>{JSON.stringify(advice.draft_profile, null, 2)}</pre></details><Button variant="outline" disabled={!!busy} onClick={useDraft}>Use draft in mapping editor</Button></>}</div>}</section></details>}
          <div className={styles.actions}>{canCancel && <Button variant="outline" disabled={!!busy} onClick={() => void act("cancel")}>Cancel job</Button>}{importSuggestedAction(selected, "retry") && <Button variant="outline" disabled={!!busy || !health} onClick={() => void act("retry")}>Retry job</Button>}<Button variant="outline" disabled={!!busy} onClick={() => void act("evidence")}>View evidence</Button></div>
          {!!selected.files.length && <details className={styles.fileDetails}><summary>{selected.files.length} admitted files · SHA-256 receipts</summary><ul className={styles.files}>{selected.files.map(file => <li key={file.id}><FileText size={16} /><span><strong>{file.name}</strong><small>{bytes(file.size)}{file.role ? ` · ${file.role}` : ""}</small><code>{file.sha256}</code></span></li>)}</ul></details>}
          {!!selected.qa?.length && <details><summary>Detailed quality checks</summary><Quality qa={selected.qa} /></details>}
          {selected.result && <><h3>{["succeeded", "no_change"].includes(selected.status) ? "Published LOCAL TEST result" : "Candidate result · not published"}</h3><ResultView result={selected.result} /></>}
          <details className={styles.events}><summary>Worker event history</summary><ol>{selected.events.map((event, i) => <li key={`${event.at}-${i}`}><time>{new Date(event.at).toLocaleTimeString()}</time><div><strong>{statusName(event.stage)}</strong><p>{event.message}</p></div></li>)}</ol></details>
          {evidence?.jobId === selected.id && <div className={styles.evidence}><div className={styles.sectionHeading}><h3>Local execution evidence</h3><Button variant="outline" size="sm" onClick={downloadEvidence}>Download JSON</Button></div><ImportEvidence key={evidence.jobId} data={evidence.data} /></div>}
        </section>}
      </section>
    </div>
    {!embedded && <section className={styles.catalog} aria-label="Local publication catalog"><div className={styles.sectionHeading}><div><span className={styles.eyebrow}>LOCAL TEST PUBLICATIONS</span><h2>Published sources, kept independent.</h2></div><CheckCircle2 size={22} /></div><p>A successful job replaces only its own source. Failed or incomplete candidates leave the last published release intact. No national total is calculated.</p>{catalog?.release_id && <p className={styles.note}>Current local release: <code>{catalog.release_id}</code></p>}<div className={styles.sources}>{catalog?.sources.length ? catalog.sources.map(item => <article key={item.source_id}><h3>{item.source_id}</h3><strong>{value(item.summary?.crash_count)} <small>crash records</small></strong><p className={styles.note}>Batch <code>{item.batch_id}</code></p><Button variant="outline" disabled={!!busy} onClick={() => void openReport(item.source_id)}>Read local result <ArrowRight size={15} /></Button>{!isolated && catalog.release_id && item.coverage && typeof item.coverage === "object" ? <Link className="text-link" onClick={()=>window.dispatchEvent(new Event("arsia:pin-release"))} href={analysisHref("/", {source:({official_nsw:"NSW",official_vic:"VIC",official_qld:"QLD"} as Record<string,string>)[item.source_id] || item.source_id,dateRange:coverageMonthRange(item.coverage as {from:string;to:string}),datasetVersion:LOCAL_VERSION,batchId:catalog.release_id,releaseId:catalog.release_id},DEFAULT_VIEW)}>Open in Overview</Link> : null}</article>) : <p className={styles.empty}>No local release has been published. The website continues to show the original project snapshot.</p>}</div>{report && <div className={styles.report}><div className={styles.sectionHeading}><h3>{report.source} · LOCAL TEST result</h3><Button variant="ghost" size="icon" aria-label="Close local result" onClick={() => setReport(null)}><X size={17} /></Button></div><p className={styles.note}>Frozen release <code>{report.release}</code></p><ResultView result={report.data} /></div>}</section>}
  </div>;
}
