"use client";
import { SelectField } from "./ui/select-field";

import { useEffect, useLayoutEffect, useId, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";
import { ArrowDown, ArrowUpRight, BarChart3, BookOpen, Check, ChevronRight, FileText, Layers3, Library, LineChart, Loader2, Map, Maximize2, MessageCircle, Plus, Search, Send, ShieldCheck, Sparkles, Square, Table2, X } from "lucide-react";
import type { Evidence } from "@/services/contracts";
import type { ResearchRun, Study } from "@/services/studio-contracts";
import { RESOURCE_DEFINITIONS, type ResourceCatalogEntry, type ResourceId } from "@/services/studio-resources";
import { studioRequest } from "@/services/studio-client";
import styles from "./studio-explore.module.css";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "./ui/dialog";

const Visualization = dynamic(() => import("./agent-visualization"), { ssr: false, loading: () => <p className={styles.note}>Loading saved visualization…</p> });
type Action = Record<string, unknown>;
export interface StudioExploreProps {
  study: Study;
  draft: string;
  onDraft: (text: string) => void;
  onSend: (question: string, retryId?: string, selectedRunIds?: string[]) => void | Promise<void>;
  onStop: () => void;
  busy: boolean;
  progress?: string;
  assistantAvailable: boolean;
  readOnly?: boolean;
  versionId?: string;
  onDocument: () => void;
  onResource: (definitionId?: ResourceId) => void;
  onEvidence: (run: ResearchRun, item?: Evidence) => void;
  onAction: (action: Action) => Promise<void>;
  onFinding?: (run: ResearchRun) => void;
  entries?: ResourceCatalogEntry[];
  selectedRunIds?: string[];
  onSelectionChange?: (ids: string[]) => void;
}

const starters = [
  { label: "Understand the trend", question: "How have recorded crashes changed over the selected period? Show the trend and explain the main changes.", icon: LineChart },
  { label: "Compare severity", question: "What does the severity distribution show for this scope, and which comparisons are valid?", icon: BarChart3 },
  { label: "Find a useful comparison", question: "Suggest a meaningful comparison within this data scope, and explain which evidence would support it.", icon: Layers3 },
  { label: "Check the source limits", question: "What are the definitions, coverage and limitations of the data in this study?", icon: ShieldCheck },
];
const resourceTitle = (run: ResearchRun) => run.resource ? RESOURCE_DEFINITIONS.find(entry => entry.id === run.resource?.definitionId)?.label || run.question : run.question;
const scopeLabel = (run: ResearchRun) => `${run.context.filters.source} · ${run.context.filters.dateRange.from.slice(0, 7)} – ${run.context.filters.dateRange.to.slice(0, 7)}`;
const dateLabel = (date: string) => new Date(date).toLocaleString("en-AU", { dateStyle: "medium", timeStyle: "short" });
function ResourceIcon({ kind, size = 17 }: { kind: string; size?: number }) {
  if (kind === "table") return <Table2 size={size} />;
  if (kind === "map") return <Map size={size} />;
  if (kind === "line") return <LineChart size={size} />;
  if (kind === "kpi") return <Layers3 size={size} />;
  return <BarChart3 size={size} />;
}
function extraScopes(run: ResearchRun) {
  const scopes = new Set<string>();
  const add = (range: unknown, source: unknown) => {
    if (!range || typeof range !== "object") return;
    const value = range as { from?: string; to?: string };
    if (typeof value.from !== "string" || typeof value.to !== "string") return;
    const expected = run.context.filters;
    if (value.from < expected.dateRange.from || value.to > expected.dateRange.to || (source && source !== expected.source)) {
      scopes.add(`${typeof source === "string" ? source : expected.source} · ${value.from} – ${value.to}`);
    }
  };
  for (const item of run.evidence) {
    const result = item.result as { source?: string; requestedRange?: unknown; baselineRange?: unknown; inputScopes?: { source?: string; requestedRange?: unknown }[] } | undefined;
    if (!result) continue;
    add(result.requestedRange, result.source);
    add(result.baselineRange, result.source);
    for (const scope of result.inputScopes || []) add(scope.requestedRange, scope.source);
  }
  return [...scopes];
}

export default function StudioExplore({ study, draft, onDraft, onSend, onStop, busy, progress, assistantAvailable, readOnly = false, versionId, onDocument, onResource, onEvidence, onAction, onFinding, entries: suppliedEntries, selectedRunIds, onSelectionChange }: StudioExploreProps) {
  const [catalog, setCatalog] = useState<ResourceCatalogEntry[]>([]);
  const [catalogContext, setCatalogContext] = useState("");
  const [catalogState, setCatalogState] = useState<"loading" | "ready" | "error">("loading");
  const [catalogError, setCatalogError] = useState("");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [shelf, setShelf] = useState<"browse" | "saved">("browse");
  const [localSelected, setLocalSelected] = useState<string[]>([]);
  const selected = selectedRunIds ?? localSelected;
  const [actionKey, setActionKey] = useState("");
  const [actionError, setActionError] = useState("");
  const [retryCatalog, setRetryCatalog] = useState(0);
  const composer = useRef<HTMLTextAreaElement>(null);
  const feed = useRef<HTMLDivElement>(null);
  const followsLatest = useRef(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [resourcesOpen, setResourcesOpen] = useState(false);
  const [below, setBelow] = useState(false);
  useLayoutEffect(() => {
    if (busy && followsLatest.current && feed.current) feed.current.scrollTop = feed.current.scrollHeight;
  }, [study.runs, busy]);
  const mutationPending = useRef(false);
  const mountedStudy = useRef(study.id);
  const questionId = useId();
  const contextKey = JSON.stringify(study.context);
  const catalogMatches = catalogContext === contextKey;
  const entries = suppliedEntries || (catalogMatches ? catalog : []);
  const ready = suppliedEntries !== undefined || (catalogMatches && catalogState === "ready");
  const savedResources = useMemo(() => study.runs.filter(run => run.status === "complete" && (run.resource || run.views.length)), [study.runs]);
  const selectedRuns = study.runs.filter(run => selected.includes(run.id) && run.status === "complete");
  const filtered = entries.filter(entry => {
    const matchesType = filter === "all" || (filter === "charts" ? !["table", "map"].includes(entry.kind) : entry.kind === filter);
    return matchesType && `${entry.label} ${entry.kind}`.toLowerCase().includes(search.toLowerCase());
  });
  const savedFiltered = savedResources.filter(run => resourceTitle(run).toLowerCase().includes(search.toLowerCase()));
  const canMutate = !readOnly && !busy && !actionKey;

  useEffect(() => {
    mountedStudy.current = study.id;
    return () => { mountedStudy.current = ""; };
  }, [study.id]);

  useEffect(() => {
    if (suppliedEntries !== undefined) return;
    const abort = new AbortController();
    studioRequest<ResourceCatalogEntry[]>(`/resources?context=${encodeURIComponent(contextKey)}`, "GET", undefined, abort.signal)
      .then(value => { if (!abort.signal.aborted) { setCatalog(value); setCatalogContext(contextKey); setCatalogState("ready"); setCatalogError(""); } })
      .catch(error => { if (!abort.signal.aborted) { setCatalogContext(contextKey); setCatalogState("error"); setCatalogError((error as Error).message); } });
    return () => abort.abort();
  }, [contextKey, suppliedEntries, retryCatalog]);

  function prepareQuestion(question: string, run?: ResearchRun) {
    if (readOnly || busy) return;
    if (run && !selected.includes(run.id)) selectSources([...selected, run.id]);
    onDraft(question);
    requestAnimationFrame(() => composer.current?.focus());
  }
  function selectSources(ids: string[]) {
    if (onSelectionChange) onSelectionChange(ids);
    else setLocalSelected(ids);
  }
  async function action(key: string, payload: Action, openDocument = false) {
    if (readOnly || actionKey || mutationPending.current || (busy && payload.type !== "skip_presentation")) return;
    const owner = study.id;
    mutationPending.current = true;
    setActionKey(key);
    setActionError("");
    try {
      await onAction(payload);
      if (mountedStudy.current === owner && openDocument) onDocument();
    } catch (error) {
      if (mountedStudy.current === owner) setActionError((error as Error).message);
    } finally {
      mutationPending.current = false;
      if (mountedStudy.current === owner) setActionKey("");
    }
  }
  function send() {
    if (!draft.trim() || busy || readOnly || !assistantAvailable) return;
    followsLatest.current = true;
    setEditorOpen(false);
    void onSend(draft.trim(), undefined, selectedRuns.map(run => run.id));
  }
  function reveal(run: ResearchRun) {
    const item = document.getElementById(`explore-run-${run.id}`), node = feed.current;
    if (item && node) node.scrollTo({ top: node.scrollTop + item.getBoundingClientRect().top - node.getBoundingClientRect().top, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
    setResourcesOpen(false);
  }

  const resourceLibrary = <>
      <div className={styles.shelfHeader}><div><Library size={16} /><h2>Resources</h2></div><p>Real charts and tables, ready when you are.</p></div>
      <div className={styles.shelfTabs} role="group" aria-label="Resource library"><button aria-pressed={shelf === "browse"} onClick={() => setShelf("browse")}>Browse</button><button aria-pressed={shelf === "saved"} onClick={() => setShelf("saved")}>Saved <span>{savedResources.length}</span></button></div>
      <label className={styles.search}><Search size={14} /><input aria-label="Search resources" placeholder="Find a chart or table" value={search} onChange={event => setSearch(event.target.value)} /></label>
      {shelf === "browse" && <label className={styles.typeFilter}><span>Show</span><SelectField aria-label="Resource type" compact value={filter} onValueChange={setFilter} options={[{value:"all",label:"All resources"},{value:"charts",label:"Charts & metrics"},{value:"table",label:"Tables"},{value:"map",label:"Maps"}]}/></label>}
      {shelf === "browse" ? <div className={styles.catalog}>
        {!ready && (!catalogMatches || catalogState === "loading") && <p className={styles.catalogState} role="status"><Loader2 size={14} className="spin" /> Checking available resources…</p>}
        {!ready && catalogMatches && catalogState === "error" && <div className={styles.catalogState} role="alert"><p>{catalogError || "Resources could not be loaded."}</p><button onClick={() => { setCatalogState("loading"); setRetryCatalog(value => value + 1); }}>Try loading resources again</button></div>}
        {ready && !filtered.length && <p className={styles.catalogState}>No resources match this search.</p>}
        {ready && filtered.map(entry => <button key={entry.id} className={styles.catalogItem} disabled={readOnly || busy || entry.availability !== "available"} onClick={() => onResource(entry.id)}><span className={styles.catalogIcon}><ResourceIcon kind={entry.kind} /></span><span><strong>{entry.label}</strong><small>{entry.availability === "available" ? entry.kind === "table" ? "Data table" : entry.kind === "map" ? "Spatial view" : entry.kind === "kpi" ? "Key metrics" : "Chart" : entry.reason || entry.availability}</small></span><ChevronRight size={14} /></button>)}
      </div> : <div className={styles.catalog}>
        {!savedFiltered.length && <p className={styles.catalogState}>{search ? "No saved resources match." : "Charts you collect in this study appear here."}</p>}
        {savedFiltered.map(run => <button key={run.id} className={styles.catalogItem} onClick={() => reveal(run)}><span className={styles.catalogIcon}><ResourceIcon kind={run.resource?.display.kind || run.views[0]?.kind || "bar"} /></span><span><strong>{resourceTitle(run)}</strong><small>{scopeLabel(run)}</small></span><ArrowUpRight size={13} /></button>)}
      </div>}
      <div className={styles.shelfNote}><ShieldCheck size={15} /><p>Resources use this study’s scope. Each saved result keeps its sources and limitations.</p></div>
      <div className={styles.writeCard}><FileText size={20} /><h3>Ready to put it into words?</h3><p>Move a useful answer or chart into your document, then write in your own voice.</p><button onClick={onDocument}>Go to document <ArrowUpRight size={14} /></button></div>
  </>;

  return <div className={styles.workspace}>
    <section className={styles.conversation} aria-label="Explore your research">
      <div className={styles.mobileTools}><button onClick={() => setResourcesOpen(true)}><Library size={15}/>Resources</button></div>
      <div className={styles.feed} ref={feed} role="region" aria-label="Research conversation" tabIndex={0} onScroll={() => {const node=feed.current;if(node){const away=node.scrollHeight-node.scrollTop-node.clientHeight>96;followsLatest.current=!away;setBelow(away);}}}>
      {study.runs.length === 0 && <div className={styles.empty}>
        <div className={styles.emptyIcon}><Sparkles size={25} /></div>
        <h2>Start with a question. Or start with the data.</h2>
        <p>Use a suggestion below, write your own question, or open a chart from Resources. Your document stays one click away.</p>
        <div className={styles.starters}>{starters.map(({ label, question, icon: Icon }) => <button key={label} disabled={readOnly || busy} onClick={() => prepareQuestion(question)}><Icon size={18} /><span>{label}</span><ArrowUpRight size={14} /></button>)}</div>
      </div>}

      <div className={styles.thread}>
        {study.runs.map(run => {
          const resource = run.resource;
          const ranges = extraScopes(run);
          const isQuestion = !resource && run.origin !== "analytics";
          const canAddAnswer = run.status === "complete" && !!run.answer.trim() && isQuestion && !run.reportDraft && run.mode !== "draft" && run.mode !== "revise";
          const canAskAbout = run.status === "complete" && (canAddAnswer || run.evidence.some(item => item.query?.validated || item.query?.assurance?.parameters === "validated"));
          const alreadyInDocument = resource ? study.report.some(block => block.runId === run.id && block.refId === resource.id) : false;
          const answerInDocument = study.report.some(block => block.answerSource?.runId === run.id && block.answerSource.attempt === run.attempt);
          return <article className={styles.exchange} id={`explore-run-${run.id}`} key={`${run.id}-${run.attempt}`}>
            {isQuestion && <div className={styles.question}><span>You asked</span><p>{run.question}</p></div>}
            <div className={styles.response}>
              <div className={styles.responseHeader}><span className={styles.avatar}>{resource ? <ResourceIcon kind={resource.display.kind} size={16} /> : <Sparkles size={15} />}</span><strong>{resource ? "Saved resource" : "Research assistant"}</strong><span className={styles.runStatus} data-status={run.status}>{run.status === "complete" ? "Saved" : run.status === "running" ? "Working" : `${run.status} · incomplete`}</span><time dateTime={run.createdAt}>{dateLabel(run.createdAt)}</time></div>
              {!isQuestion && <h2 className={styles.resourceTitle}>{resourceTitle(run)}</h2>}
              <div className={styles.runScope}>{scopeLabel(run)}{selected.includes(run.id) && <span>Included with your next question</span>}</div>
              {run.answer && !resource && <div className={styles.answer}>{run.answer}</div>}
              {run.status === "running" && <div className={styles.progress} role="status"><Loader2 size={15} className="spin" /><span>{progress || run.progress || "Investigating your question…"}</span>{!readOnly && <button onClick={onStop}><Square size={12} /> Stop</button>}</div>}
              {run.error && <p className={styles.error} role="alert">{run.error}</p>}
              {run.status !== "complete" && run.status !== "running" && <p className={styles.partial}>This attempt is incomplete. Any answer shown above is partial and has not been added to your document.</p>}
              {run.completionWarnings?.map((warning, index) => <p className={styles.notice} key={index}>Completed result retained · {warning}</p>)}
              {ranges.length > 0 && <p className={styles.notice}>Additional query scopes: {ranges.join("; ")}. The study scope above is unchanged.</p>}

              {resource && run.status === "complete" && <figure className={styles.resourceFigure} data-kind={resource.display.kind}>
                {/* Saved result bindings are checked by the host before rendering this figure. */}
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <div className={styles.figureViewport} role="region" aria-label={`${resourceTitle(run)} chart`} tabIndex={0}><img src={`/api/studio/${study.id}/resources/${run.id}/figure?revision=${study.revision}${versionId ? `&versionId=${encodeURIComponent(versionId)}` : ""}`} alt={resourceTitle(run)} /></div>
                <figcaption><span>{resource.unit} · {resource.availability}</span><button onClick={() => onEvidence(run, run.evidence[0])}><ShieldCheck size={13} /> Source & limits</button></figcaption>
                <details className={styles.sourceLimits}><summary>Coverage and limitations</summary>{resource.limitations.map((limit, index) => <p key={index}>{limit}</p>)}</details>
              </figure>}
              {!resource && run.status === "complete" && run.views.map(view => <div className={styles.visualization} key={view.id}><Visualization view={view} /><div className={styles.inlineActions}><button onClick={() => onEvidence(run, run.evidence.find(item => item.id === view.evidenceId) || run.evidence[0])}><ShieldCheck size={13} /> Source</button>{!readOnly && <button disabled={!canMutate} onClick={() => void action(`view-${view.id}`, { type: "block_add", kind: view.kind === "table" ? "table" : "chart", runId: run.id, refId: view.id, withAnalysis: true }, true)}><Plus size={13} /> Add to document</button>}</div></div>)}
              {run.reportDraft && <details className={styles.proposal}><summary><FileText size={15} /> Review proposed document changes · {run.reportDraft.status}</summary><p>Review this proposal before applying it to your document.</p>{run.reportDraft.blocks.map((block, index) => <div key={index}><small>{block.kind}</small><p>{block.text}</p></div>)}{run.reportDraft.status === "proposed" && run.status === "complete" && !readOnly && <button disabled={!canMutate} onClick={() => void action(`draft-${run.id}`, { type: "report_apply", runId: run.id, draftId: run.reportDraft!.id }, true)}>Apply reviewed draft <ArrowUpRight size={14} /></button>}</details>}

              <div className={styles.runActions}>
                {resource && run.status === "complete" && !readOnly && <button className={styles.promote} disabled={!canMutate} onClick={() => alreadyInDocument ? onDocument() : void action(`resource-${run.id}`, { type: "block_add", kind: "resource", runId: run.id, refId: resource.id, withAnalysis: true }, true)}>{alreadyInDocument ? <Check size={14} /> : <Plus size={14} />}{alreadyInDocument ? "Open in document" : "Add to document"}<ArrowUpRight size={13} /></button>}
                {canAddAnswer && !readOnly && <button className={styles.promote} disabled={!canMutate} onClick={() => answerInDocument ? onDocument() : void action(`answer-${run.id}`, { type: "answer_to_document", runId: run.id, attempt: run.attempt }, true)}>{answerInDocument ? <Check size={14} /> : <Plus size={14} />}{answerInDocument ? "Open answer in document" : "Add answer to document"}<ArrowUpRight size={13} /></button>}
                {!!run.evidence.length && <button onClick={() => onEvidence(run, run.evidence[0])}><ShieldCheck size={14} />{run.evidence.length} evidence {run.evidence.length === 1 ? "record" : "records"}</button>}
                {canAskAbout && !readOnly && <button disabled={busy} onClick={() => prepareQuestion(resource ? `What does “${resourceTitle(run)}” show, and what should I be careful about when interpreting it?` : "What evidence supports this answer, and what remains uncertain?", run)}><MessageCircle size={14} /> Ask about this</button>}
                {onFinding && run.status === "complete" && !!run.evidence.length && !readOnly && <button disabled={!canMutate} onClick={() => onFinding(run)}><BookOpen size={14} /> Save finding</button>}
                {run.status !== "complete" && run.status !== "running" && !readOnly && <button disabled={busy || !assistantAvailable || run.attempt >= 3} onClick={() => void onSend(run.question, run.id, run.selectedRunIds)}><ArrowUpRight size={14} /> Retry analysis</button>}
              </div>
              {canAddAnswer && <p className={styles.answerNote}>AI answer · Review the wording and evidence before using it in your document.</p>}
              <details className={styles.execution}><summary>Activity & saved evidence <ChevronRight size={13} /></summary><p>Attempt {run.attempt} · {run.context.filters.datasetVersion} · {scopeLabel(run)}</p>
                {run.plan.length > 0 && <ol>{run.plan.map((step, index) => <li key={index}><span data-status={step.status}>{step.status === "complete" ? <Check size={12} /> : <span className={styles.stepDot} />}{step.label}</span><small>{step.status.replaceAll("_", " ")}</small>{step.optional && step.status === "pending" && run.status === "running" && !readOnly && <button disabled={!!actionKey} onClick={() => void action(`skip-${run.id}`, { type: "skip_presentation", runId: run.id })}>Skip optional presentation</button>}</li>)}</ol>}
                {run.changes.map((change, index) => <p key={index}>Scope change: {change}</p>)}
                {run.evidence.map(item => <button className={styles.evidenceButton} key={item.id} onClick={() => onEvidence(run, item)}><ShieldCheck size={13} />{item.title}<ArrowUpRight size={12} /></button>)}
                {run.toolErrors?.map((error, index) => <details className={styles.toolError} key={index}><summary>Rejected tool · {error.name}</summary><p>{error.message}</p><pre>{JSON.stringify(error.parameters, null, 2)}</pre></details>)}
                {run.previousAttempts.length > 0 && <details><summary>{run.previousAttempts.length} earlier attempts retained</summary>{run.previousAttempts.map((attempt, index) => <div key={index}><strong>Earlier attempt {index + 1} · {attempt.status}</strong>{attempt.error && <p>{attempt.error}</p>}{attempt.answer && <p className={styles.previousAnswer}>{attempt.answer}</p>}<small>{attempt.evidence.length} evidence records</small></div>)}</details>}
                {run.artifactIds.map(id => study.artifacts.find(artifact => artifact.id === id)).filter(artifact => artifact !== undefined).map(artifact => <a key={artifact.id} href={artifact.href} download={artifact.name}><FileText size={13} />{artifact.name}<ArrowDown size={12} /></a>)}
              </details>
            </div>
          </article>;
        })}
      </div>
      {actionError && <p className={styles.error} role="alert">{actionError}</p>}
      {study.runs.length > 0 && !readOnly && <div className={styles.followups}><span>Keep exploring</span>{starters.slice(0, 2).map(({ label, question }) => <button key={label} disabled={busy} onClick={() => prepareQuestion(question)}>{label}<ArrowUpRight size={12} /></button>)}</div>}
      </div>
      <div className={styles.composerDock}>
        {below && <button className={styles.latest} onClick={() => {followsLatest.current=true;feed.current?.scrollTo({top:feed.current.scrollHeight,behavior:"smooth"});}} aria-label="Jump to latest response"><ArrowDown size={15}/></button>}
        {selectedRuns.length > 0 && <div className={styles.contextChips} aria-label="Selected question sources">{selectedRuns.map(run => <span key={run.id}><Library size={12}/>{resourceTitle(run)}{!readOnly && <button type="button" disabled={busy} aria-label={`Remove ${resourceTitle(run)} from question`} onClick={() => selectSources(selected.filter(id => id !== run.id))}><X size={12}/></button>}</span>)}</div>}
        <form className={styles.composer} aria-label="Question composer" onSubmit={event => {event.preventDefault();send();}}>
          {!draft && <div className={styles.inputPlaceholder} aria-hidden="true"><Sparkles size={16}/><span>Ask your research assistant</span></div>}
          <textarea ref={composer} id={questionId} aria-label="Ask your research assistant" rows={2} value={draft} maxLength={2000} readOnly={readOnly || busy} onChange={event => onDraft(event.target.value)} onKeyDown={event => {if(event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing){event.preventDefault();send();}}}/>
          <button type="button" className={styles.expandEditor} aria-label="Expand question editor" title="Expand question editor" onClick={() => setEditorOpen(true)}><Maximize2 size={15}/></button>
          {busy && !readOnly ? <button type="button" className={styles.send} onClick={onStop}><Square size={14}/>Stop</button> : <button type="submit" className={styles.send} disabled={!draft.trim() || !assistantAvailable || readOnly}><Send size={14}/>Ask</button>}
        </form>
        {!assistantAvailable && <p className={styles.connectionNote}>AI is not connected. Resources and document editing are available.</p>}
        {readOnly && <p className={styles.connectionNote}>Saved history · read only</p>}
      </div>
      <Dialog open={editorOpen} onOpenChange={setEditorOpen}>
        <DialogContent className={styles.editorDialog} onCloseAutoFocus={event => {event.preventDefault();composer.current?.focus({preventScroll:true});}}>
          <DialogTitle>Edit your question</DialogTitle><DialogDescription>Your draft stays the same when you close this editor.</DialogDescription>
          <textarea aria-label="Expanded question" autoFocus value={draft} maxLength={2000} readOnly={readOnly || busy} placeholder="Ask your research assistant" onChange={event => onDraft(event.target.value)} onKeyDown={event => {if(event.key === "Enter" && (event.metaKey || event.ctrlKey) && !event.nativeEvent.isComposing){event.preventDefault();send();}}}/>
          <div className={styles.editorFooter}><span>{draft.length} / 2,000</span><button type="button" onClick={() => setEditorOpen(false)}>Done</button><button type="button" className={styles.editorSend} disabled={!draft.trim() || !assistantAvailable || readOnly || busy} onClick={send}><Send size={15}/>Ask</button></div>
        </DialogContent>
      </Dialog>
    </section>

    <aside className={styles.resourceShelf} aria-label="Explore resources">{resourceLibrary}</aside>
    <Dialog open={resourcesOpen} onOpenChange={setResourcesOpen}><DialogContent className={styles.resourceDialog}><DialogTitle>Resources</DialogTitle><DialogDescription>Charts and tables for this study.</DialogDescription><div className={styles.resourceDialogBody}>{resourceLibrary}</div></DialogContent></Dialog>

  </div>;
}
