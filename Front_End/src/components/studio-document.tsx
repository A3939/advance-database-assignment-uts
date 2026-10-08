"use client";
import { SelectField } from "./ui/select-field";

import { useContext, useEffect, useRef, useState } from "react";
import dynamic from "next/dynamic";
import {
  ArrowDown, ArrowUp, ArrowUpRight, BarChart3, ChevronDown,
  FileText, Heading2, MoreHorizontal, Plus, Sparkles, Trash2, Type,
} from "lucide-react";
import { RESOURCE_DEFINITIONS } from "@/services/studio-resources";
import type { Evidence } from "@/services/contracts";
import type { ReportBlock, ResearchRun, Study } from "@/services/studio-contracts";
import { EditableText, StudioDraftContext } from "./studio-editable-text";
import styles from "./studio-document.module.css";

const Visualization = dynamic(() => import("./agent-visualization"), {
  ssr: false,
  loading: () => <p className={styles.note}>Loading chart…</p>,
});

type Action = Record<string, unknown>;
type Props = {
  study: Study;
  action: (action: Action) => Promise<void>;
  readOnly: boolean;
  onAddChart: (afterId?: string | null) => void;
  onEvidence: (run: ResearchRun, evidence: Evidence) => void;
  onAsk?: (blockId?: string) => void;
  editorEpoch: number;
  versionId?: string;
};

const resourceLabel = (run:ResearchRun) => RESOURCE_DEFINITIONS.find(item=>item.id===run.resource?.definitionId)?.label || run.question;

const kindLabel = (kind: ReportBlock["kind"]) => ({
  text: "Paragraph", title: "Heading", section: "Heading", resource: "Chart",
  chart: "Chart", table: "Table", finding: "Finding", evidence: "Evidence", artifact: "Attachment",
})[kind];

function InsertRow({ afterId, onInsert, onAddChart, disabled }: {
  afterId: string | null;
  onInsert: (kind: "text" | "section", afterId: string | null) => void;
  onAddChart: (afterId: string | null) => void;
  disabled: boolean;
}) {
  return <div className={styles.insertRow} aria-label="Insert into document">
    <span className={styles.insertLine}/>
    <div>
      <button type="button" disabled={disabled} onClick={() => onInsert("text", afterId)}><Type size={13}/>Text</button>
      <button type="button" disabled={disabled} onClick={() => onInsert("section", afterId)}><Heading2 size={14}/>Heading</button>
      <button type="button" disabled={disabled} onClick={() => onAddChart(afterId)}><BarChart3 size={13}/>Chart</button>
    </div>
    <span className={styles.insertLine}/>
  </div>;
}

/** The document is a view of saved report blocks; saved research is never silently migrated. */
export default function StudioDocument({ study, action, readOnly, onAddChart, onEvidence, onAsk, editorEpoch, versionId }: Props) {
  const drafts = useContext(StudioDraftContext);
  const root = useRef<HTMLDivElement>(null);
  const previous = useRef({ studyId: study.id, ids: new Set(study.report.map(block => block.id)) });
  const [working, setWorking] = useState(false);
  const [error, setError] = useState("");
  const runById = new Map(study.runs.map(run => [run.id, run]));
  const usedResources = new Set(study.report.filter(block => block.kind === "resource").map(block => block.runId));
  const unplaced = study.runs.filter(run => run.status === "complete" && run.resource && !usedResources.has(run.id));
  const title = study.reportMeta?.title || study.title;
  // Older templates store the cover title as a block as well as metadata. Render
  // that exact duplicate once, without deleting or migrating its saved record.
  const coverTitle = study.report[0]?.kind === "title" && study.report[0].text === title ? study.report[0] : undefined;
  const body = coverTitle ? study.report.slice(1) : study.report;
  const context = study.context.filters;
  const dirty = () => drafts?.changed();

  // New blocks receive a writing caret only after the server returns their real IDs.
  // Switching studies or reading History never moves focus or creates a block.
  useEffect(() => {
    const prior = previous.current;
    previous.current = { studyId: study.id, ids: new Set(study.report.map(block => block.id)) };
    if (readOnly || prior.studyId !== study.id) return;
    const added = study.report.filter(block => !prior.ids.has(block.id));
    const target = added.find(block => block.kind === "text") || added.find(block => block.kind === "section" || block.kind === "title");
    if (!target) return;
    const field = root.current?.querySelector<HTMLInputElement | HTMLTextAreaElement>(`[data-block-id="${target.id}"] textarea, [data-block-id="${target.id}"] input`);
    field?.focus({ preventScroll: true });
    field?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [study.id, study.report, readOnly]);

  const perform = async (next: Action) => {
    if (working || readOnly) return;
    setWorking(true); setError("");
    try { await action(next); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "The change could not be saved."); }
    finally { setWorking(false); }
  };
  const insert = (kind: "text" | "section", afterId: string | null) => void perform({ type: "block_add", kind, text: "", afterId });

  return <div className={styles.workspace} ref={root}>
    {!readOnly && unplaced.length > 0 && <section className={styles.savedShelf} aria-label="Saved charts not in document">
      <div className={styles.shelfIntro}><span className={styles.shelfIcon}><BarChart3 size={19}/></span><div><strong>{study.report.length ? "Saved charts" : "Your chart is ready"}</strong><p>{study.report.length ? "Bring a saved chart into your writing." : "Add it to the document, then write your analysis directly below it."}</p></div></div>
      <div className={styles.savedList}>{unplaced.map(run => <div className={styles.savedItem} key={run.id}>
        <div><strong>{resourceLabel(run)}</strong><small>{run.context.filters.source} · {run.resource?.unit}</small></div>
        <button type="button" disabled={working} onClick={() => void perform({ type: "block_add", kind: "resource", runId: run.id, refId: run.resource!.id, withAnalysis: true })}><Plus size={14}/>Add to document</button>
      </div>)}</div>
    </section>}

    {error && <p className={styles.error} role="alert">{error}</p>}

    <article className={styles.paper} aria-label="Research document">
      <header className={styles.documentHeader} id={coverTitle ? `report-${coverTitle.id}` : undefined}>
        {readOnly ? <h1>{title}</h1> : <div className={styles.documentTitle}><EditableText
          key={`title-${study.id}-${editorEpoch}`}
          fieldKey={`${study.id}:reportTitle`} label="Document title" value={title}
          rows={1} max={120} placeholder="Untitled research"
          onSave={text => action({ type: "report_title", title: text })} onDirty={dirty}
        /></div>}
        <div className={styles.documentMeta}>
          <span>{context.source === "All" ? "All sources" : context.source}</span>
          <span>{context.dateRange.from.slice(0, 7)} — {context.dateRange.to.slice(0, 7)}</span>
          {study.reportMeta?.author && <span>{study.reportMeta.author}</span>}
        </div>
      </header>

      {!readOnly && <InsertRow afterId={coverTitle?.id || null} onInsert={insert} onAddChart={onAddChart} disabled={working}/>}
      {!body.length && <section className={styles.empty}>
        <span className={styles.emptyIcon}><FileText size={24}/></span>
        <h2>A place for your analysis</h2>
        <p>{readOnly ? "This version has no document content." : "Write a thought, add a chart, and tell the story in one place."}</p>
        {!readOnly && <div className={styles.emptyActions}>
          <button className={styles.primary} type="button" disabled={working} onClick={() => insert("text", coverTitle?.id || null)}><Type size={15}/>Start writing</button>
          <button type="button" disabled={working} onClick={() => onAddChart(coverTitle?.id || null)}><BarChart3 size={15}/>Add a chart</button>
        </div>}
      </section>}

      {body.map((block, index) => {
        const run = block.runId ? runById.get(block.runId) : undefined;
        const answerRun = block.answerSource ? runById.get(block.answerSource.runId) : undefined;
        const answerEvidence = answerRun?.evidence.filter(item => block.citations?.some(ref => ref.runId === answerRun.id && ref.evidenceId === item.id)) || [];
        const view = run?.views.find(item => item.id === block.refId);
        const finding = study.findings.find(item => item.id === block.refId);
        const evidence = run?.evidence.find(item => item.id === block.refId);
        const artifact = study.artifacts.find(item => item.id === block.refId);
        const heading = block.kind === "title" || block.kind === "section";
        const prose = block.kind === "text";
        const figure = block.kind === "resource" || block.kind === "chart" || block.kind === "table";
        const followsFigure = index > 0 && ["resource", "chart", "table"].includes(body[index - 1].kind);
        const nextIsText = body[index + 1]?.kind === "text";
        return <div key={block.id}>
          <section id={`report-${block.id}`} data-block-id={block.id} className={`${styles.block} ${heading ? styles.heading : prose ? styles.prose : styles.resultBlock} ${block.pageBreakBefore ? styles.pageBreak : ""}`} aria-label={`${kindLabel(block.kind)} ${index + 1}`}>
            {!readOnly && <details className={styles.blockMenu}>
              <summary aria-label={`Options for ${kindLabel(block.kind).toLowerCase()} ${index + 1}`} title="Block options"><MoreHorizontal size={18}/></summary>
              <div className={styles.menuContent}>
                <button type="button" disabled={working || index === 0} onClick={() => void perform({ type: "block_move", id: block.id, direction: -1 })}><ArrowUp size={14}/>Move up</button>
                <button type="button" disabled={working || index === body.length - 1} onClick={() => void perform({ type: "block_move", id: block.id, direction: 1 })}><ArrowDown size={14}/>Move down</button>
                {onAsk && <button type="button" onClick={() => onAsk(prose || heading ? block.id : undefined)}><Sparkles size={14}/>{prose || heading ? "Improve with assistant" : "Discuss with assistant"}</button>}
                <label><input type="checkbox" checked={block.pageBreakBefore || false} disabled={working} onChange={event => void perform({ type: "block_edit", id: block.id, pageBreakBefore: event.target.checked })}/>New page in export</label>
                {figure && <label>Export width<SelectField aria-label="Figure export width" compact value={block.size || "full"} disabled={working} onValueChange={value=>void perform({type:"block_edit",id:block.id,size:value})} options={[{value:"full",label:"Full"},{value:"half",label:"Half"}]}/></label>}
                <button className={styles.remove} type="button" disabled={working} onClick={() => void perform({ type: "block_delete", id: block.id })}><Trash2 size={14}/>Remove from document</button>
              </div>
            </details>}

            {(heading || prose) && <>
              {block.answerSource && <div className={styles.answerOrigin}><Sparkles size={13}/><span>AI draft · Review before use</span>{answerRun && answerEvidence.length ? <button type="button" onClick={() => onEvidence(answerRun, answerEvidence[0])}>{answerEvidence.length} linked {answerEvidence.length === 1 ? "source" : "sources"}<ArrowUpRight size={12}/></button> : <span>No linked data evidence</span>}</div>}
              {prose && followsFigure && !block.text && !readOnly && <div className={styles.writingLabel}><Type size={14}/>Your analysis <span>Write directly below the chart</span></div>}
              {readOnly ? (heading ? <h2>{block.text}</h2> : <p className={styles.paragraph}>{block.text}</p>) : <EditableText
                key={`${block.id}-${editorEpoch}`} fieldKey={`${study.id}:block:${block.id}:text`}
                value={block.text} label={heading ? "Section heading" : followsFigure ? "Write your analysis" : "Write paragraph"}
                placeholder={heading ? "Section heading" : followsFigure ? "What does this chart show? Write your analysis here…" : "Start writing…"}
                rows={heading?1:3} max={10000} onDirty={dirty} onSave={text => action({ type: "block_edit", id: block.id, text })}
              />}
            </>}

            {block.kind === "resource" && run?.resource && <figure className={styles.figure}>
              <div className={styles.figureHeading}><BarChart3 size={15}/><span>{resourceLabel(run)}</span></div>
              {/* Saved server-produced figure; native img preserves the same authenticated provenance route as exports. */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <div className={styles.figureViewport} data-kind={run.resource.display.kind} role="region" aria-label={`${resourceLabel(run)} chart`} tabIndex={0}><img src={`/api/studio/${study.id}/resources/${run.id}/figure?revision=${study.revision}${versionId ? `&versionId=${versionId}` : ""}`} alt={resourceLabel(run)}/></div>
              <figcaption><span>{run.resource.unit}</span><span>{run.context.filters.source} · {run.context.filters.dateRange.from.slice(0, 7)}–{run.context.filters.dateRange.to.slice(0, 7)}</span></figcaption>
            </figure>}
            {view && block.kind !== "resource" && <div className={styles.interactiveFigure}><Visualization view={block.kind === "table" ? { ...view, kind: "table" } : view}/></div>}
            {finding && <div className={styles.finding}><span className={styles.smallLabel}>{finding.kind}</span><h3>{finding.title}</h3><p>{finding.explanation}</p><small>{finding.evidenceIds.length ? "Evidence linked" : "No data evidence"} · {finding.checks?.userReviewed ? "Reviewed" : "Review needed"}</small></div>}
            {evidence && run && <button className={styles.evidenceLink} type="button" onClick={() => onEvidence(run, evidence)}><FileText size={15}/>{evidence.title}<ArrowUpRight size={14}/></button>}
            {artifact && <a className={styles.evidenceLink} href={artifact.href} download={artifact.name}><FileText size={15}/>{artifact.name}<ArrowUpRight size={14}/></a>}

            {figure && (readOnly ? (block.caption ? <p className={styles.caption}>{block.caption}</p> : null) : <div className={styles.caption}><EditableText
              key={`caption-${block.id}-${editorEpoch}`} fieldKey={`${study.id}:block:${block.id}:caption`}
              value={block.caption || ""} label="Figure caption" placeholder="Add a caption (optional)…" rows={1} max={2000}
              onDirty={dirty} onSave={caption => action({ type: "block_edit", id: block.id, caption })}
            /></div>)}
            {!heading && !prose && (block.text || !figure) && (readOnly ? (block.text ? <p className={styles.caption}>{block.text}</p> : null) : <div className={styles.caption}><EditableText
              key={`note-${block.id}-${editorEpoch}`} fieldKey={`${study.id}:block:${block.id}:text`}
              value={block.text} label={figure ? "Figure note" : "Block note"} placeholder="Add a note (optional)…" single max={10000}
              onDirty={dirty} onSave={text => action({ type: "block_edit", id: block.id, text })}
            /></div>)}
            {!figure && block.caption && <p className={styles.caption}>{block.caption}</p>}

            {run && (run.evidence.length > 0 || !!run.resource?.limitations.length) && <details className={styles.sourceDetails}>
              <summary><ChevronDown size={12}/>Source & limitations<span>{run.evidence.length} evidence {run.evidence.length === 1 ? "record" : "records"}</span></summary>
              <div><p>{run.context.filters.source} · {run.context.filters.datasetVersion}</p>{run.resource?.limitations.map((limit, limitIndex) => <p key={limitIndex}>{limit}</p>)}
                {run.evidence.map(item => <button key={item.id} type="button" onClick={() => onEvidence(run, item)}>{item.title}<ArrowUpRight size={12}/></button>)}
              </div>
            </details>}
            {figure && !nextIsText && !readOnly && <button className={styles.writeBelow} type="button" disabled={working} onClick={() => insert("text", block.id)}><Type size={15}/><span>Write about this chart</span><Plus size={14}/></button>}
          </section>
          {!readOnly && <InsertRow afterId={block.id} onInsert={insert} onAddChart={onAddChart} disabled={working}/>}
        </div>;
      })}
      {!!study.report.length && <footer className={styles.documentFooter}><span>End of document</span><span>{study.report.length} {study.report.length === 1 ? "block" : "blocks"}</span></footer>}
    </article>
    {!readOnly && <p className={styles.canvasHint}>Click any text to edit. Changes save automatically. Charts keep their sources attached.</p>}
  </div>;
}
