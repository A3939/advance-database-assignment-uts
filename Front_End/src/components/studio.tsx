"use client";
import { SelectField } from "./ui/select-field";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, useId, useMemo } from "react";
import {
  Archive,
  BarChart3,
  LayoutTemplate,
  Compass,
  ChevronDown,
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronLeft,
  Download,
  FileText,
  Loader2,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Send,
  Settings2,
  Sparkles,
  Square,
  X,
} from "lucide-react";
import type {
  ReportMetadata,
  ResearchContext,
  ResearchFinding,
  ResearchRun,
  Study,
  StudySummary,
  StudyVersion,
} from "@/services/studio-contracts";
import type { Evidence, Filters } from "@/services/contracts";
import { studioRequest, streamStudy } from "@/services/studio-client";
import { useWorkspace } from "./workspace";
import { Button } from "./ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "./ui/sheet";
import { regionsForSource } from "@/services/regions";
import { fetchCatalog, SNAPSHOT_CATALOG, hasRegionalProvider } from "@/services/catalog-contracts";
import { wholeMonthRange } from "@/services/date-range";
import styles from "./studio.module.css";
import researchStyles from "./studio-research.module.css";
import StudioExplore from "./studio-explore";
import { StudyLibraryList, StudySearch, type StudyLibraryAction, type StudyLibraryTarget } from "./studio-library";
import StudioDocument from "./studio-document";
import canvasStyles from "./studio-canvas-shell.module.css";
import StudioResourcePicker from "./studio-resource-picker";
import type { ResourceCatalogEntry, ResourceId } from "@/services/studio-resources";
import { FindingComposer } from "./studio-finding-composer";
import { EditableText, StudioDraftContext, useStudioFormDraft } from "./studio-editable-text";
import { StudioEditBuffer, StudioFieldDrafts, acknowledgeStudioFields, requireStudioWritesSaved, type PendingStudioEdit } from "@/services/studio-edit-buffer";
type Action = Record<string, unknown>;
type Panel = "assistant" | "context" | "evidence" | "history" | "settings" | null;
const metricNames = {
  crashes: "Crashes",
  fatalCrashes: "Fatal crashes",
  livesLost: "Lives lost",
  casualties: "Casualties",
};
const scope = (c: ResearchContext) =>
  `${c.filters.source}${c.filters.regionId ? ` · ${regionName(c.filters)}` : ""} · ${c.filters.dateRange.from.slice(0, 7)} – ${c.filters.dateRange.to.slice(0, 7)}`;
function regionName(f: Filters) {
  return f.source !== "All"
    ? regionsForSource(f.source).find((r) => r.id === f.regionId)?.name ||
        f.regionId
    : "All areas";
}
const timestamp = (at: string) =>
  new Date(at).toLocaleString("en-AU", {
    dateStyle: "medium",
    timeStyle: "short",
  });
function IconButton({
  label,
  onClick,
  children,
  disabled = false,
}: {
  label: string;
  onClick: () => void;
  children: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      className={styles.icon}
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  );
}

export default function Studio() {
  const { filters } = useWorkspace();
  const shellRef = useRef<HTMLDivElement>(null);
  const [studies, setStudies] = useState<StudySummary[]>([]),
    [study, setStudy] = useState<Study | null>(null),
    [loading, setLoading] = useState(true);
  const [sidebar, setSidebar] = useState(true),
    [showArchived, setShowArchived] = useState(false);
  const [view, setView] = useState<"Explore" | "Findings" | "Report">(
      "Report",
    ),
    [panel, setPanel] = useState<Panel>(null),
    [evidence, setEvidence] = useState<{
      run: ResearchRun;
      item: Evidence;
    } | null>(null);
  const [status, setStatus] = useState("Saved"),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [draft, setDraft] = useState(""),
    [progress, setProgress] = useState("");
  const [creating, setCreating] = useState(false),
    [versions, setVersions] = useState<StudyVersion[]>([]),
    [historical, setHistorical] = useState<Study | null>(null),
    [catalog, setCatalog] = useState<unknown>(null);
  const [historicalVersionId,setHistoricalVersionId]=useState("");
  const [resourcePicker, setResourcePicker] = useState(false);
  const [pickerIntent,setPickerIntent] = useState<"document"|"explore">("document");
  const [pickerSelection,setPickerSelection] = useState<ResourceId|undefined>();
  const [insertAfter,setInsertAfter] = useState<string|null|undefined>(undefined);
  const [pickerContext,setPickerContext] = useState<ResearchContext|null>(null);
  const [recovery,setRecovery] = useState<Study|null>(null);
  const [editorEpoch,setEditorEpoch] = useState(0);
  const conflict = useRef(false), edits = useRef(new StudioEditBuffer());
  const [fieldDrafts]=useState(()=>new StudioFieldDrafts());
  const [recoveryEdits,setRecoveryEdits]=useState<PendingStudioEdit[]>([]);
  const [recoveryFields,setRecoveryFields]=useState("");
  const [findingRun, setFindingRun] = useState<ResearchRun | null | undefined>(undefined);
  const [assistantAvailable, setAssistantAvailable] = useState(false);
  const viewportStudyId = study?.id;
  useLayoutEffect(() => {
    if (view !== "Explore" || !viewportStudyId || loading) return;
    const node = shellRef.current;
    if (!node) return;
    window.scrollTo({ top: 0, behavior: "instant" });
    const resize = () => {
      const viewport = window.visualViewport;
      const bottom = viewport ? viewport.height + viewport.offsetTop : window.innerHeight;
      node.style.setProperty("--studio-chat-height", `${Math.max(240, bottom - node.getBoundingClientRect().top)}px`);
    };
    resize();
    const observer = new ResizeObserver(resize);
    const topbar = document.querySelector(".topbar");
    if (topbar) observer.observe(topbar);
    window.addEventListener("resize", resize);
    window.visualViewport?.addEventListener("resize", resize);
    return () => { observer.disconnect(); window.removeEventListener("resize", resize); window.visualViewport?.removeEventListener("resize", resize); };
  }, [view, viewportStudyId, loading]);

  const [researchMode, setResearchMode] = useState<"explore" | "analyze" | "draft" | "revise">("explore");
  const [selectedRunIds, setSelectedRunIds] = useState<string[]>([]);
  const [targetBlockId, setTargetBlockId] = useState("");
  useEffect(() => { void studioRequest<{assistant:{available:boolean}}>("/capabilities").then(v => setAssistantAvailable(v.assistant.available)).catch(() => {}); }, []);
  const current = useRef<Study | null>(null),
    controller = useRef<AbortController | null>(null),
    queue = useRef<Promise<unknown>>(Promise.resolve()),
    pendingWrites = useRef(0),
    draftTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeId = useRef(""), panelRequest=useRef(0), historyRequest=useRef(0);
  const apply = useCallback((s: Study) => {
    current.current = s;
    setStudy(s);
    setStudies((all) => [
      {
        id: s.id,
        title: s.title,
        archived: s.archived,
        updatedAt: s.updatedAt,
      },
      ...all.filter((v) => v.id !== s.id),
    ]);
  }, []);
  const load = useCallback(
    async (id: string) => {
      controller.current?.abort();
      if (draftTimer.current) clearTimeout(draftTimer.current);
      await queue.current.catch(() => {});
      activeId.current = id; panelRequest.current++;historyRequest.current++;
      setLoading(true);
      const savedView=new URLSearchParams(location.search).get("studioView");
      setView(savedView==="explore"?"Explore":savedView==="findings"?"Findings":"Report");
      setError("");
      setHistorical(null);
      setCatalog(null);
      setEvidence(null); setPanel(null);
      setSelectedRunIds([]); setTargetBlockId("");
      try {
        const s = await studioRequest<Study>(`/${id}`);
        if (activeId.current !== id) return;
        apply(s);
        setDraft(s.draft === "Explore the selected data and its definitions." ? "" : s.draft);
        fieldDrafts.clear(); edits.current.clear(id); conflict.current=false; setRecovery(null); setEditorEpoch(e=>e+1);
        setStatus("Saved");
        setBusy(false);
        const url = new URL(location.href);
        url.searchParams.set("study", id);
        history.replaceState(null, "", url);
        localStorage.setItem("arsia-studio-last", id);
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setLoading(false);
      }
    },
    [apply,fieldDrafts],
  );
  useEffect(() => {
    let mounted = true;
    studioRequest<StudySummary[]>("")
      .then((list) => {
        if (!mounted) return;
        if (matchMedia("(max-width: 767px)").matches) setSidebar(false);
        setStudies(list);
        const id =
          new URLSearchParams(location.search).get("study") ||
          localStorage.getItem("arsia-studio-last");
        if (id && list.some((s) => s.id === id)) void load(id);
        else setLoading(false);
      })
      .catch((e) => {
        setError(e.message);
        setLoading(false);
      });
    return () => {
      mounted = false;
      controller.current?.abort();
    };
  }, [load]);
  const updateSaveStatus = useCallback(() => {
    setStatus(edits.current.entries(activeId.current).length || fieldDrafts.size || draftTimer.current ? "Unsaved" : pendingWrites.current ? "Saving…" : "Saved");
  }, [fieldDrafts]);
  const discardField = useCallback(async(key:string)=>{
    const id=activeId.current;
    // A request already sent cannot be unsent. Settle it before discarding only remaining local intentions.
    await queue.current.catch(()=>{});
    if(activeId.current!==id)return;
    edits.current.discardField(id,key);fieldDrafts.discard(key);
    if(!edits.current.entries(id).length)setError("");updateSaveStatus();
  },[fieldDrafts,updateSaveStatus]);
  const fieldSession = useMemo(() => ({fields:fieldDrafts,changed:updateSaveStatus,discard:discardField}),[updateSaveStatus,fieldDrafts,discardField]);
  const sendEdit = useCallback((record:PendingStudioEdit):Promise<void> => {
    pendingWrites.current++;
    setStatus("Saving…");
    const work=async()=>{
      try {
        if(activeId.current!==record.studyId) throw Error("This local edit belongs to another study.");
        if(!edits.current.owns(record))return;
        if(conflict.current)throw Error("Review the latest saved revision before reapplying your local edits.");
        let next:Study;
        try {next=await studioRequest<Study>(`/${record.studyId}`,"PATCH",{...record.action,revision:current.current?.revision});}
        catch(e){if((e as {status?:number}).status===409){conflict.current=true;throw Error("A newer revision exists. Local edits are retained. Review the saved revision, then choose whether to reapply or discard them.");}throw e;}
        edits.current.acknowledge(record); acknowledgeStudioFields(fieldDrafts,record);
        if(activeId.current===record.studyId){apply(next);if(!edits.current.entries(record.studyId).length)setError("");}
      }catch(e){edits.current.fail(record,(e as Error).message);if(activeId.current===record.studyId)setError((e as Error).message);throw e;}
      finally{pendingWrites.current--;if(activeId.current===record.studyId)updateSaveStatus();}
    };
    const pending=queue.current.catch(()=>{}).then(work);queue.current=pending;return pending;
  },[apply,updateSaveStatus,fieldDrafts]);
  const mutate=useCallback((action:Action):Promise<void> => {
    if(!activeId.current)return Promise.reject(Error("No current study."));
    if(historical)return Promise.reject(Error("Saved history is read only. Return to the current study to edit."));
    const pending=sendEdit(edits.current.stage(activeId.current,action,fieldDrafts));void pending.catch(()=>{});return pending;
  },[sendEdit,historical,fieldDrafts]);
  async function reviewLocalEdits(){
    try{
      if(draftTimer.current){clearTimeout(draftTimer.current);draftTimer.current=null;edits.current.stage(activeId.current,{type:"draft",text:draft});}
      const waitedTail=queue.current;
      await waitedTail.catch(()=>{});
      const id=activeId.current,latest=await studioRequest<Study>(`/${activeId.current}`);
      if(activeId.current!==id)return;
      if(queue.current!==waitedTail||pendingWrites.current){setError("A save changed while the revision was being read. Wait for it to settle, then review again.");return;}
      if(activeId.current===id){setRecoveryEdits(edits.current.entries(id));setRecoveryFields(JSON.stringify(fieldDrafts.snapshot()));setRecovery(latest);}
    }catch(e){setError((e as Error).message);}
  }
  async function resolveLocalEdits(reapply:boolean){
    if(!recovery||recovery.id!==activeId.current)return;
    if(pendingWrites.current){setError("A save is still in progress. Wait for it to settle, then review again.");setRecovery(null);return;}
    const held=edits.current.entries(recovery.id);
    if(JSON.stringify(held.map(e=>e.token))!==JSON.stringify(recoveryEdits.map(e=>e.token)) || JSON.stringify(fieldDrafts.snapshot())!==recoveryFields){setRecovery(null);setError("Local edits changed after this review. Review the saved revision again before reapplying or discarding.");return;}
    apply(recovery);conflict.current=false;queue.current=Promise.resolve();
    setRecovery(null);
    if(!reapply){edits.current.clear(recovery.id);fieldDrafts.clear();setDraft(recovery.draft);setEditorEpoch(e=>e+1);setError("");updateSaveStatus();return;}
    // This button is the user's explicit decision. The fetched revision is still checked by the host.
    try{for(const edit of held)await sendEdit(edit);setError("");}
    catch{/* New conflicts stay local and require a fresh review. */}
    updateSaveStatus();
  }

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setPanel(null);
        if (matchMedia("(max-width: 767px)").matches) setSidebar(false);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  useEffect(() => {
    const before = (event: BeforeUnloadEvent) => {
      if (status !== "Saved") {
        event.preventDefault();
        event.returnValue = "";
      }
    };
    window.addEventListener("beforeunload", before);
    return () => window.removeEventListener("beforeunload", before);
  }, [status]);
  const hasRunning = study?.runs.some((r) => r.status === "running") ?? false;
  useEffect(() => {
    if (!study || !hasRunning || controller.current) return;
    const id = study.id;
    const timer = setInterval(() => {
      void studioRequest<Study>(`/${id}`)
        .then((s) => {
          if (activeId.current === id) {
            apply(s);
            setBusy(s.runs.some((r) => r.status === "running"));
          }
        })
        .catch(() => {});
    }, 1500);
    return () => clearInterval(timer);
  }, [study, hasRunning, apply]);
  const act = (a: Action) => { void mutate(a).catch(() => {}); };
  function changeDraft(text: string) {
    setDraft(text);
    setStatus("Unsaved");
    if (draftTimer.current) clearTimeout(draftTimer.current);
    draftTimer.current = setTimeout(() => {
      draftTimer.current = null;
      void mutate({ type: "draft", text }).catch(() => {});
    }, 400);
  }
  async function flushDraft() {
    try{await fieldDrafts.flush();}catch(e){setError((e as Error).message);setStatus("Unsaved");throw e;}
    if (draftTimer.current) {
      clearTimeout(draftTimer.current);
      draftTimer.current = null;
      await mutate({ type: "draft", text: draft });
    }
    await requireStudioWritesSaved(queue.current,()=>!!edits.current.entries(activeId.current).length || !!fieldDrafts.size);
  }
  async function selectView(next:typeof view) {
    try {await flushDraft();setView(next);if(next==="Explore")setPanel(null);const url=new URL(location.href);url.searchParams.set("studioView",next==="Explore"?"explore":next==="Report"?"document":"findings");history.replaceState(null,"",url);} catch {/* Preserve local writing in its current view. */}
  }
  async function openResourcePicker(context?:ResearchContext, afterId?:string|null, intent:"document"|"explore"="document", definitionId?:ResourceId) {
    if(historical)return;
    try { await flushDraft(); setPickerContext(context||null); setPickerIntent(intent);setPickerSelection(definitionId);setInsertAfter(afterId); setResourcePicker(true); } catch { /* Retain unsaved edits. */ }
  }
  async function switchStudy(id: string) {
    try {
      await flushDraft();
      await load(id);
    } catch {
      /* Keep unsaved content visible. */
    }
  }
  async function inspectLibraryStudy(id: string): Promise<StudyLibraryTarget> {
    await flushDraft();
    if (historical && id === activeId.current) throw Error("Return to the current study before changing it.");
    return studioRequest<Study>(`/${id}`);
  }
  async function manageLibraryStudy(target: StudyLibraryTarget, action: StudyLibraryAction) {
    await flushDraft();
    if (historical && target.id === activeId.current) throw Error("Saved history is read only.");
    if (action.type === "delete") {
      await studioRequest(`/${target.id}`, "DELETE", { revision: target.revision });
      setStudies(all => all.filter(item => item.id !== target.id));
      if (activeId.current === target.id) {
        controller.current?.abort();activeId.current = "";current.current = null;
        edits.current.clear(target.id);fieldDrafts.clear();setStudy(null);setDraft("");setHistorical(null);setPanel(null);setError("");setStatus("Saved");setView("Report");
        const url = new URL(location.href);url.searchParams.delete("study");url.searchParams.delete("studioView");history.replaceState(null,"",url);
      }
      if (localStorage.getItem("arsia-studio-last") === target.id) localStorage.removeItem("arsia-studio-last");
    } else {
      const saved = await studioRequest<Study>(`/${target.id}`, "PATCH", { ...action, revision: target.revision });
      if (activeId.current === target.id) {apply(saved);setStatus("Saved");}
      else setStudies(all => all.map(item => item.id === saved.id ? {id:saved.id,title:saved.title,archived:saved.archived,updatedAt:saved.updatedAt} : item).sort((a,b)=>b.updatedAt.localeCompare(a.updatedAt)));
    }
  }
  async function create(
    question: string,
    context: ResearchContext,
    title?: string,
    template?: "brief"|"full",
    explore = false,
  ) {
    setCreating(true);
    setError("");
    try {
      const s = await studioRequest<Study>("", "POST", {
        question,
        context,
        title: title || question.slice(0, 120),
      });
      activeId.current = s.id;
      apply(s);
      setDraft(s.draft === "Explore the selected data and its definitions." ? "" : s.draft);
      setPanel(null);
      setView(explore?"Explore":"Report");
      setStatus("Saved");
      setLoading(false);
      const url = new URL(location.href);
      url.searchParams.set("study", s.id);
      url.searchParams.set("studioView",explore?"explore":"document");
      history.replaceState(null, "", url);
      localStorage.setItem("arsia-studio-last", s.id);
      // Show the owned study before initialization, so a failed second write can be recovered here.
      if(!explore)await mutate(template ? {type:"report_template",blank:true,metadata:{template,language:"en",title:s.title,author:"",date:new Date().toISOString().slice(0,10)}} : {type:"block_add",kind:"text",text:""});
      if(activeId.current!==s.id)return;
      // Creating a research record never spends model budget. Run is explicit.
      setPanel(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCreating(false);
    }
  }
  async function newStudy() {
    try {
      await flushDraft();
      controller.current?.abort();
      activeId.current = "";
      current.current = null;
      setStudy(null);
      setView("Report");
      setPanel(null);
      setHistorical(null);
      setError("");
      const url = new URL(location.href);
      url.searchParams.delete("study");
      url.searchParams.delete("studioView");
      history.replaceState(null, "", url);
      localStorage.removeItem("arsia-studio-last");
    } catch {}
  }
  async function run(question: string, retryId?: string, options?:{mode:"explore";selectedRunIds:string[]}) {
    const study = current.current;
    if (!study || busy || historical || !question.trim() || !assistantAvailable) return;
    try {
      await flushDraft();
    } catch {
      return;
    }
    if (activeId.current !== study.id) return;
    const id = study.id,
      abort = new AbortController();
    controller.current = abort;
    setBusy(true);
    setError("");
    setProgress("Preparing analysis…");
    setView("Explore");
    setHistorical(null);
    try {
      let firstUpdate = true;
      for await (const e of streamStudy(
        id,
        { requestId: crypto.randomUUID(), question, retryId, mode: options?.mode || researchMode, selectedRunIds:options?.selectedRunIds || selectedRunIds, ...(!options && targetBlockId ? {targetBlockId} : {}) },
        abort.signal,
      )) {
        if (activeId.current !== id) break;
        if (e.type === "study") {
          apply(e.study);
          if (firstUpdate) {
            setDraft(e.study.draft);
            firstUpdate = false;
          }
        }
        if (e.type === "progress") setProgress(e.text);
        if (e.type === "message")
          setStudy((s) =>
            s
              ? {
                  ...s,
                  runs: s.runs.map((r) =>
                    r.status === "running"
                      ? { ...r, answer: r.answer + e.text }
                      : r,
                  ),
                }
              : s,
          );
        if (e.type === "error") {
          setError(e.message);
          if (e.code === "UNSAVED") setStatus("Unsaved");
        }
      }
    } catch (e) {
      if (!abort.signal.aborted) setError((e as Error).message);
    } finally {
      controller.current = null;
      setBusy(false);
      setProgress("");
      if (activeId.current === id) {
        try {
          apply(await studioRequest<Study>(`/${id}`));
        } catch {
          setStatus("Unsaved");
        }
      }
    }
  }
  async function stop() {
    if (!study || historical) return;
    try {
      await studioRequest(`/${study.id}/runs`, "DELETE");
    } catch {}
    controller.current?.abort();
  }
  async function togglePanel(next: Panel) {
    setPanel((p) => (p === next ? null : next));
    const id=activeId.current,request=++panelRequest.current;
    if(!id)return;
    try{
      if(next==="history"){
        const saved=await studioRequest<StudyVersion[]>(`/${id}?history=1`);
        if(activeId.current===id&&panelRequest.current===request)setVersions(saved);
      }
      if(next==="context"){
        const saved=await studioRequest(`/${id}?catalog=1`);
        if(activeId.current===id&&panelRequest.current===request)setCatalog(saved);
      }
    }catch(e){if(activeId.current===id&&panelRequest.current===request)setError((e as Error).message);}
  }
  async function viewHistory(versionId:string){
    const id=activeId.current,request=++historyRequest.current;
    try{
      await flushDraft();
      if(activeId.current!==id)return;
      const saved=await studioRequest<Study>(`/${id}?version=${versionId}`);
      if(activeId.current!==id||historyRequest.current!==request)return;
      setHistoricalVersionId(versionId);setHistorical(saved);setEvidence(null);setView("Report");
    }catch(e){if(activeId.current===id&&historyRequest.current===request)setError((e as Error).message);}
  }
  function showEvidence(run: ResearchRun, item?: Evidence) {
    if (!item) return;
    setEvidence({ run, item });
    setPanel("evidence");
  }
  function saveFinding(run: ResearchRun) { setFindingRun(run); }
  async function download(format: "pdf" | "zip" = "zip") {
    if (!study || historical) return;
    try {
      await flushDraft();
      const response = await fetch(`/api/studio/${study.id}/export?format=${format}&revision=${current.current?.revision}`);
      if (!response.ok) {
        const e = await response.json();
        throw Error(e.error);
      }
      const url = URL.createObjectURL(await response.blob()),
        a = document.createElement("a");
      a.href = url;
      a.download = `ARSIA-${study.title.replace(/[^a-z0-9-]/gi, "-")}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function previewReport(){
    if(historical)return;
    try{await flushDraft();const saved=current.current;if(saved)window.open(`/api/studio/${saved.id}/preview?revision=${saved.revision}`,"_blank","noopener");}catch(e){setError((e as Error).message);}
  }
  const displayed = historical || study;
  const sideContent =
    panel && study ? (
      <>
        <div className={styles.panelTabs}>
          {(["assistant", "context", "history", "settings"] as const).map((p) => (
            <button
              key={p}
              aria-pressed={panel === p}
              onClick={() => void togglePanel(p)}
            >
              {p === "assistant"
                ? "Assistant"
                : p === "context"
                  ? "Context"
                  : p === "history" ? "History" : "Details"}
            </button>
          ))}
          <IconButton
            label="Close research panel"
            onClick={() => setPanel(null)}
          >
            <X size={17} />
          </IconButton>
        </div>
        <div className={styles.sideBody}>
          {panel === "assistant" && (
            <>
              <h2 className={styles.panelTitle}>
                <Sparkles size={17} /> ARSIA Assistant
              </h2>
              {!assistantAvailable && <p className={researchStyles.notice}>Assistant is unavailable in this environment. You can add platform resources, organize findings and export reports without AI.</p>}
              <p className={researchStyles.note}>Closing this page stops active research. Partial results remain saved.</p>
              <label className={researchStyles.field}>Research mode<SelectField aria-label="Research mode" disabled={!!historical} value={researchMode} onValueChange={value=>setResearchMode(value as typeof researchMode)} options={[{value:"explore",label:"Explore — understand the question"},{value:"analyze",label:"Analyze — query and compare"},{value:"draft",label:"Draft — use saved evidence"},{value:"revise",label:"Revise — selected paragraph only"}]}/></label>
              <fieldset className={researchStyles.notice}><legend>Selected research resources</legend>{(displayed || study).runs.filter(r => r.status === "complete" && r.evidence.length).map(r => <label className={researchStyles.field} key={r.id}><span><input type="checkbox" disabled={!!historical} checked={selectedRunIds.includes(r.id)} onChange={e => setSelectedRunIds(ids => e.target.checked ? [...ids,r.id] : ids.filter(id => id !== r.id))}/> {r.question}</span></label>)}</fieldset>
              {researchMode === "revise" && <label className={researchStyles.field}>Paragraph to revise<SelectField aria-label="Paragraph to revise" disabled={!!historical} value={targetBlockId} onValueChange={setTargetBlockId} options={[{value:"",label:"Select a report paragraph"},...(displayed || study).report.filter(b=>b.kind==="text"||b.kind==="title"||b.kind==="section").map(b=>({value:b.id,label:b.text.slice(0,80)||"Empty paragraph"}))]}/></label>}
              {(displayed || study).runs.length === 0 ? (
                <p className={styles.muted}>Ask a question about this study.</p>
              ) : (
                (displayed || study).runs.map((r) => (
                  <div className={styles.conversation} key={r.id}>
                    <strong>{r.question}</strong>
                    <details>
                      <summary>
                        {r.status === "complete" ? "View response" : r.status}
                      </summary>
                      <p>{r.answer || r.error || r.progress}</p>
                    </details>
                    <button
                      className={styles.textButton}
                      onClick={() => showEvidence(r, r.evidence[0])}
                      disabled={!r.evidence.length}
                    >
                      {r.evidence.length} evidence records
                    </button>
                  </div>
                ))
              )}
            </>
          )}
          {panel === "evidence" && evidence && (
            <>
              <button
                className={styles.textButton}
                onClick={() => setPanel("assistant")}
              >
                <ChevronLeft size={14} /> Assistant
              </button>
              <h2 className={styles.panelTitle}>{evidence.item.title}</h2>
              <p>{scope(evidence.run.context)}</p>
              <p className={styles.muted}>{evidence.item.description}</p>
              <div className={styles.evidencePicker}>
                {evidence.run.evidence.map((e) => (
                  <button
                    key={e.id}
                    aria-pressed={evidence.item.id === e.id}
                    onClick={() => setEvidence({ ...evidence, item: e })}
                  >
                    {e.id}
                  </button>
                ))}
              </div>
              <dl className={styles.details}>
                {evidence.item.rows?.map((r, i) => (
                  <div key={i}>
                    <dt>{r.label}</dt>
                    <dd>{r.value}</dd>
                  </div>
                ))}
              </dl>
              <div className={styles.actions}>
                <button
                  disabled={!!historical || evidence.run.status !== "complete"}
                  onClick={() =>
                    act({
                      type: "block_add",
                      kind: "evidence",
                      runId: evidence.run.id,
                      refId: evidence.item.id,
                    })
                  }
                >
                  Add evidence to report
                </button>
              </div>
              <details>
                <summary>Technical details · query and calculations</summary>
                <pre>
                  {JSON.stringify(
                    {
                      query: evidence.item.query,
                      result: evidence.item.result,
                    },
                    null,
                    2,
                  )}
                </pre>
              </details>
            </>
          )}
          {panel === "settings" && <><h2 className={styles.panelTitle}>Document details</h2><p className={researchStyles.note}>These details appear in your exported report. Edit the title directly on the document.</p>{!historical ? <ReportMetadataEditor key={`${study.id}-${editorEpoch}`} study={study} action={mutate}/> : <p>Saved history is read only.</p>}</>}
          {panel === "context" && (
            <ContextEditor
              key={`${study.id}-${editorEpoch}`}
              context={historical?.context || study.context}
              disabled={busy || !!historical}
              onSave={(context) => mutate({ type: "context", context })}
              fieldKey={`${study.id}:context`}
              catalog={catalog}
            />
          )}
          {panel === "history" && (
            <>
              <h2 className={styles.panelTitle}>Research history</h2>
              <Button
                variant="outline"
                disabled={!!historical}
                onClick={() =>
                  void flushDraft().then(()=>mutate({
                    type: "snapshot",
                    label: `Snapshot · ${timestamp(new Date().toISOString())}`,
                  }))
                    .then(async () => {
                      const saved=await studioRequest<StudyVersion[]>(`/${study.id}?history=1`);
                      if(activeId.current===study.id)setVersions(saved);
                    })
                    .catch(() => {})
                }
              >
                <Plus size={15} /> Save version
              </Button>
              {versions.length === 0 && (
                <p className={styles.muted}>
                  Context changes create a version automatically.
                </p>
              )}
              {versions.map((v) => (
                <article className={styles.version} key={v.id}>
                  <strong>{v.label}</strong>
                  <small>{timestamp(v.createdAt)}</small>
                  <p>{scope(v.context)}</p>
                  <p className={styles.muted}>
                    {v.runs} analyses · {v.findings} findings
                  </p>
                  <div className={styles.actions}>
                    <button disabled={busy || !!historical} onClick={() => void flushDraft().then(()=>mutate({type:"report_undo",versionId:v.id})).catch(()=>{})}>Restore report only</button>
                    <button
                      onClick={() => void viewHistory(v.id)}
                    >
                      View
                    </button>
                    <button
                      disabled={busy || !!historical}
                      onClick={() =>
                        void flushDraft().then(()=>mutate({ type: "restore", versionId: v.id }))
                          .then(() => {
                            setHistorical(null);
                            void togglePanel("history");
                          })
                          .catch(() => {})
                      }
                    >
                      Restore as new version
                    </button>
                  </div>
                </article>
              ))}
            </>
          )}
        </div>
        {panel === "assistant" && (
          <Composer
            value={historical?.draft ?? draft}
            onChange={changeDraft}
            busy={busy}
            available={assistantAvailable && !historical}
            readOnly={!!historical}
            onSend={() => void run(draft)}
            onStop={() => void stop()}
          />
        )}
      </>
    ) : null;
  return (
    <StudioDraftContext.Provider value={fieldSession}><div
      ref={shellRef} className={`${styles.studio} ${canvasStyles.shell} ${view === "Explore" && study && !loading ? styles.chatMode : ""} ${sidebar ? styles.withSidebar : ""} ${panel ? styles.withPanel : ""}`}
    >
      {sidebar && (
        <aside className={styles.library} aria-label="Studies">
          <div className={styles.libraryHead}>
            <strong>{showArchived ? "Archived studies" : "Studies"}</strong>
            <div className={styles.libraryTools}><StudySearch studies={studies} onSelect={async id => {setShowArchived(studies.find(item=>item.id===id)?.archived ?? false);await switchStudy(id);}}/>
            <IconButton
              label="Collapse studies"
              onClick={() => setSidebar(false)}
            >
              <PanelLeftClose size={17} />
            </IconButton></div>
          </div>
          <Button variant="outline" onClick={() => void newStudy()}>
            <Plus size={16} /> New study
          </Button>
          <StudyLibraryList studies={studies.filter(item => item.archived === showArchived)} activeId={study?.id} disabledId={historical ? study?.id : undefined} onSelect={switchStudy} onInspect={inspectLibraryStudy} onAction={manageLibraryStudy}/>
          {view === "Report" && displayed && <div className={canvasStyles.outline}><h3>In this document</h3>{displayed.report.filter(b=>b.kind==="section" || b.kind==="title").map(b=><button key={b.id} onClick={()=>{requestAnimationFrame(()=>document.getElementById(`report-${b.id}`)?.scrollIntoView({block:"center"}));}}>{b.text||"Untitled section"}</button>)}{!displayed.report.some(b=>b.kind==="section")&&<p>Add headings to build an outline.</p>}</div>}
          <button
            className={styles.archiveToggle}
            onClick={() => setShowArchived((v) => !v)}
          >
            <Archive size={15} />
            {showArchived ? "Show active studies" : "Archived studies"}
          </button>
        </aside>
      )}
      <section className={styles.workspace} aria-label="Research workspace">
        {loading ? (
          <div className={styles.empty}>
            <Loader2 className="spin" /> Loading research…
          </div>
        ) : !study ? (
          <div className={styles.newStudy}>
            {!sidebar && (
              <IconButton label="Show studies" onClick={() => setSidebar(true)}>
                <PanelLeftOpen size={19} />
              </IconButton>
            )}
            <span className={canvasStyles.eyebrow}>ARSIA STUDIO</span><h1>Make a report worth sharing.</h1><p className={canvasStyles.intro}>Start with a chart or a template. Write your analysis right beside the evidence.</p>
            <NewStudy key={JSON.stringify(filters)} filters={filters} busy={creating} onCreate={create} onResources={(context) => void openResourcePicker(context)} onExplore={context=>void create("",context,"New exploration",undefined,true)} />
          </div>
        ) : (
          <>
            <header className={styles.toolbar}>
              <div className={styles.titleRow}>
                {!sidebar && (
                  <IconButton
                    label="Show studies"
                    onClick={() => setSidebar(true)}
                  >
                    <PanelLeftOpen size={18} />
                  </IconButton>
                )}
                <div className={canvasStyles.workspaceSwitch} aria-label="Workspace mode"><button aria-pressed={view==="Explore"} onClick={()=>void selectView("Explore")}><Compass size={16}/>Explore</button><button aria-pressed={view==="Report"} onClick={()=>void selectView("Report")}><FileText size={16}/>Document</button><button aria-pressed={view==="Findings"} onClick={()=>void selectView("Findings")}><BookOpen size={16}/>Findings</button></div>
                <div className={styles.toolbarActions}>
                  <IconButton
                    disabled={!!historical}
                    label={displayed?.archived ? "Restore study" : "Archive study"}
                    onClick={() =>
                      act({ type: "archive", archived: !study.archived })
                    }
                  >
                    <Archive size={17} />
                  </IconButton>
                  <button className={canvasStyles.detailsButton} aria-pressed={panel==="settings"} onClick={()=>void togglePanel("settings")}><Settings2 size={16}/><span>Details</span></button>
                  <details className={canvasStyles.exportMenu}><summary><Download size={16}/> Export <ChevronDown size={13}/></summary><div>
                    <button disabled={!!historical} onClick={()=>void download("pdf")}>Download PDF</button>
                    <button disabled={!!historical} onClick={()=>void previewReport()}>Print preview</button>
                    <button disabled={!!historical} onClick={()=>void download("zip")}>Download materials ZIP</button>
                    <small>Includes document content and its linked sources.</small>
                  </div></details>
                  {view!=="Explore" && <Button
                    variant="outline"
                    className={styles.assistantToggle}
                    aria-pressed={panel === "assistant"}
                    onClick={() => void togglePanel("assistant")}
                  >
                    <Sparkles size={16} />
                    <span>Assistant</span>
                  </Button>}
                </div>
              </div>
              <div className={styles.viewRow}>
                <div className={canvasStyles.studyIdentity}>
                <EditableText
                  key={`${study.id}-${editorEpoch}`}
                  fieldKey={`${study.id}:title`}
                  disabled={!!historical}
                  value={displayed?.title || study.title}
                  label="Study title"
                  onSave={(text) => mutate({ type: "rename", title: text })}
                  single
                  max={120}
                  onDirty={() => setStatus("Unsaved")}
                />
                <span
                  className={`${styles.saveStatus} ${status === "Unsaved" ? styles.unsaved : ""}`}
                  role="status"
                >
                  {status === "Saved" && <Check size={12} />} {status}
                </span>
                </div>
                <button
                  className={styles.scope}
                  onClick={() => void togglePanel("context")}
                >
                  <Settings2 size={14} />
                  {scope(historical?.context || study.context)}
                </button>
              </div>
            </header>
            {historical && (
              <div className={styles.banner}>
                Viewing saved history · read only. Return to the current study before editing or exporting.{" "}
                <button onClick={() => {setHistorical(null);setEvidence(null);setPanel(null);}}>
                  Return to current study
                </button>
              </div>
            )}
            {displayed?.archived && (
              <div className={styles.banner}>
                Archived study{" "}
                <button
                  disabled={!!historical}
                  onClick={() => act({ type: "archive", archived: false })}
                >
                  Restore study
                </button>
              </div>
            )}
            <div className={styles.content}>
              {view === "Explore" && displayed && (
                <StudioExplore key={`${displayed.id}-${historicalVersionId}-${!!historical}`} study={displayed} draft={historical?.draft??draft} selectedRunIds={selectedRunIds} onSelectionChange={setSelectedRunIds} onDraft={changeDraft} onSend={(q,retryId,ids)=>run(q,retryId,{mode:"explore",selectedRunIds:ids||[]})} onStop={()=>void stop()} busy={busy} progress={progress} assistantAvailable={assistantAvailable} readOnly={!!historical} versionId={historical?historicalVersionId:undefined} onDocument={()=>void selectView("Report")} onResource={id=>void openResourcePicker(undefined,undefined,"explore",id)} onEvidence={showEvidence} onAction={mutate} onFinding={saveFinding}/>
              )}
              {view === "Findings" && displayed && (
                <Findings
                  study={displayed}
                  readOnly={!!historical}
                  action={(a)=>mutate(a)}
                  editorEpoch={editorEpoch}
                  dirty={() => setStatus("Unsaved")}
                  evidence={showEvidence}
                  onNew={() => setFindingRun(null)}
                />
              )}
              {view === "Report" && displayed && (
                <StudioDocument study={displayed} readOnly={!!historical} action={mutate} editorEpoch={editorEpoch} onEvidence={showEvidence} onAddChart={afterId=>void openResourcePicker(undefined,afterId)} onAsk={blockId=>{setTargetBlockId(blockId||"");setResearchMode(blockId?"revise":"draft");setPanel("assistant");}} versionId={historical?historicalVersionId:undefined}/>
              )}
            </div>
          </>
        )}
        {!!error && (
          <div className={styles.errorBanner} role="alert">
            <span>{error}</span>
            {status === "Unsaved" && (
              <button
                onClick={() => void reviewLocalEdits()}
              >
                Review unsaved edits
              </button>
            )}
            <IconButton label="Dismiss error" onClick={() => setError("")}>
              <X size={15} />
            </IconButton>
          </div>
        )}
        {recovery && <section className={researchStyles.notice} aria-label="Review unsaved edits">
          <h2>Review unsaved edits</h2><p>Saved revision {recovery.revision} was read without changing your local edits. Reapply sends them against this revision; another change will require a new review.</p>
          <p>Saved study: <strong>{recovery.title}</strong> · {scope(recovery.context)}</p>
          <h3>Your pending changes</h3>
          {recoveryEdits.length===0&&<p>No submitted edits are waiting. Save or discard any open context or report-details form before continuing.</p>}
          {recoveryEdits.map(edit=><article key={edit.token} className={researchStyles.pendingEdit}><strong>{editLabel(edit.action)}</strong><dl><dt>Your change</dt><dd>{editValue(edit.action)}</dd><dt>Saved value</dt><dd>{savedEditValue(recovery,edit.action)}</dd></dl></article>)}
          <details><summary>Technical details · pending actions and saved revision</summary><pre>{JSON.stringify({pending:recoveryEdits.map(v=>v.action),saved:{title:recovery.title,context:recovery.context,report:recovery.report,reportMeta:recovery.reportMeta}},null,2)}</pre></details>
          <div className={researchStyles.tools}><button onClick={()=>void resolveLocalEdits(true)}>Reapply my edits to reviewed revision</button><button onClick={()=>void resolveLocalEdits(false)}>Discard my local edits and use saved revision</button><button onClick={()=>setRecovery(null)}>Keep editing locally</button></div>
        </section>}
      </section>
      <StudioResourcePicker open={resourcePicker} onClose={() => setResourcePicker(false)} context={pickerContext || study?.context || {filters,metric:"crashes",notes:"",references:""}} target={study || undefined} initialSelection={pickerSelection} lockTarget={!!study} document={pickerIntent==="document"?{...(insertAfter!==undefined?{afterId:insertAfter}:{})}:undefined} onSaved={s => {activeId.current=s.id; apply(s); setDraft(s.draft === "Explore the selected data and its definitions." ? "" : s.draft); setLoading(false);setView(pickerIntent==="document"?"Report":"Explore"); const url=new URL(location.href);url.searchParams.set("study",s.id);url.searchParams.set("studioView",pickerIntent==="document"?"document":"explore");history.replaceState(null,"",url);}} />
      {study && findingRun !== undefined && <FindingComposer study={study} initialRun={findingRun} close={() => setFindingRun(undefined)} save={async a => {await mutate(a); setFindingRun(undefined);setView("Findings");}}/>}
      {panel && (
        <>
          <aside className={styles.desktopPanel} aria-label="Research details">
            {sideContent}
          </aside>
          <ResponsiveDrawer panel={panel} close={() => setPanel(null)}>
            {sideContent}
          </ResponsiveDrawer>
        </>
      )}
    </div></StudioDraftContext.Provider>
  );
}
function ResponsiveDrawer({
  panel,
  close,
  children,
}: {
  panel: Panel;
  close: () => void;
  children: React.ReactNode;
}) {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const media = matchMedia("(max-width: 1199px)");
    const update = () => setNarrow(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  return (
    <Sheet
      open={narrow && !!panel}
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <SheetContent className={styles.drawer}>
        <SheetHeader className="sr-only">
          <SheetTitle>Research panel</SheetTitle>
          <SheetDescription>
            Assistant, context and research evidence
          </SheetDescription>
        </SheetHeader>
        {children}
      </SheetContent>
    </Sheet>
  );
}
function Composer({
  value,
  onChange,
  onSend,
  onStop,
  busy,
  available = true,
  readOnly = false,
}: {
  value: string;
  onChange: (s: string) => void;
  onSend: () => void;
  onStop: () => void;
  busy: boolean;
  available?: boolean;
  readOnly?: boolean;
}) {
  const inputId = useId();
  return (
    <form
      className={styles.composer}
      onSubmit={(e) => {
        e.preventDefault();
        onSend();
      }}
    >
      <label className="sr-only" htmlFor={inputId}>
        Research question
      </label>
      <textarea
        id={inputId}
        placeholder="Ask a question or continue this analysis…"
        value={value}
        readOnly={readOnly}
        maxLength={2000}
        rows={2}
        onChange={(e) => {if(!readOnly)onChange(e.target.value);}}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            if (!busy && available && !readOnly) onSend();
          }
        }}
      />
      {busy ? (
        <IconButton label="Stop analysis" onClick={onStop}>
          <Square size={17} />
        </IconButton>
      ) : (
        <Button
          type="submit"
          disabled={!value.trim() || !available || readOnly}
          title={available ? "Run analysis" : "Assistant unavailable; manual research and export remain available"}
          aria-label="Run analysis"
        >
          <Send size={17} />
        </Button>
      )}
    </form>
  );
}
function NewStudy({filters,busy,onCreate,onResources,onExplore}: {
  filters:Filters;busy:boolean;onResources:(context:ResearchContext)=>void;onExplore:(context:ResearchContext)=>void;
  onCreate:(question:string,context:ResearchContext,title?:string,template?:"brief"|"full")=>Promise<void>;
}) {
  const [context,setContext]=useState<ResearchContext>({filters:structuredClone(filters),metric:"crashes",notes:"",references:""});
  const [entry,setEntry]=useState<"template"|"blank">("template");
  const [title,setTitle]=useState("Trends and periods");
  const [question,setQuestion]=useState("How did recorded counts change across comparable periods, and what coverage limits apply?");
  const [template,setTemplate]=useState<"brief"|"full">("brief");
  const [selected,setSelected]=useState("Trends and periods");
  const templates=[
    {name:"Trends and periods",label:"Follow the change",description:"A focused brief for a trend or period comparison.",question:"How did recorded counts change across comparable periods, and what coverage limits apply?",kind:"brief" as const},
    {name:"Severity profile",label:"Compare severity",description:"Explain native severity categories with their limits.",question:"How are recorded crashes distributed across the source's native severity categories?",kind:"brief" as const},
    {name:"Research report",label:"Build a full report",description:"A longer structure: methods, results and discussion.",question:"What does the selected crash data show, and what limitations affect its interpretation?",kind:"full" as const},
  ];
  return <>
    <div className={canvasStyles.entryChoices}>
      <button aria-pressed={entry==="template"} onClick={()=>setEntry("template")}><LayoutTemplate size={24}/><span><strong>Start with a template</strong><small>A clear structure, ready to write.</small></span></button>
      <button onClick={()=>onResources(context)}><BarChart3 size={24}/><span><strong>Start from a chart</strong><small>Choose a chart, then write beneath it.</small></span><ArrowUpRight size={17}/></button>
    </div>
    <button disabled={busy} className={canvasStyles.exploreEntry} onClick={()=>onExplore(context)}><Compass size={22}/><span><strong>Explore first</strong><small>Ask questions, discover resources, then turn your ideas into a document.</small></span><ArrowUpRight size={18}/></button>
    <div className={canvasStyles.startPanel}>
      <div className={canvasStyles.startHeading}><h2>{entry==="template"?"Choose your starting point":"A blank page"}</h2><button className={styles.textButton} onClick={()=>{setEntry(entry==="blank"?"template":"blank");setTitle(entry==="blank"?selected:"Untitled study");}}> {entry==="blank"?"Use a template":"Start blank instead"}</button></div>
      {entry==="template"&&<div className={canvasStyles.templateGrid}>{templates.map(t=><button key={t.name} aria-pressed={selected===t.name} onClick={()=>{setSelected(t.name);setTitle(t.name);setQuestion(t.question);setTemplate(t.kind);}}><span className={canvasStyles.templateDrawing} aria-hidden="true"><i/><i/><i/><b/></span><strong>{t.label}</strong><small>{t.description}</small></button>)}</div>}
      <form onSubmit={e=>{e.preventDefault();void onCreate(question||"Write a research report.",context,title,entry==="template"?template:undefined);}}>
        <label className={researchStyles.field}>Study name<input aria-label="New study name" maxLength={120} value={title} onChange={e=>setTitle(e.target.value)}/></label>
        <details className={canvasStyles.scopeDetails}><summary><Settings2 size={15}/>{scope(context)}<span>Change data scope</span></summary><ScopeFields value={context} onChange={setContext}/></details>
        <div className={canvasStyles.startFooter}><p>Charts and writing stay together. No AI runs until you ask.</p><Button type="submit" disabled={busy||!title.trim()}>{busy?<Loader2 size={16} className="spin"/>:<FileText size={16}/>}Open document</Button></div>
      </form>
    </div>
  </>;
}
function ScopeFields({
  value,
  onChange,
}: {
  value: ResearchContext;
  onChange: (c: ResearchContext) => void;
}) {
  const f = value.filters;
  const [scopeCatalog,setScopeCatalog] = useState(SNAPSHOT_CATALOG);
  useEffect(() => { const abort = new AbortController(); void fetchCatalog(f.releaseId,abort.signal,!f.releaseId).then(setScopeCatalog).catch(()=>{}); return ()=>abort.abort(); }, [f.releaseId]);
  function dates(from: string, to: string) {
    const range = wholeMonthRange(from, to, f.releaseId ? {min:"1900-01",max:"2100-12"} : undefined);
    if (range.dateRange)
      onChange({ ...value, filters: { ...f, dateRange: range.dateRange } });
  }
  return (
    <div className={styles.fields}>
      <label>
        Source
        <SelectField aria-label="Source" value={f.source}
          onValueChange={source=>onChange({...value,filters:{...f,source:source as Filters["source"],regionId:undefined}})}
          options={["All",...scopeCatalog.sources.map(s=>s.source)].map(source=>({value:source,label:source}))}/>
      </label>
      <label>
        Metric
        <SelectField aria-label="Metric" value={value.metric}
          onValueChange={metric=>onChange({...value,metric:metric as ResearchContext["metric"]})}
          options={Object.entries(metricNames).map(([value,label])=>({value,label}))}/>
      </label>
      <label>
        From
        <input
          type="month"
          min={f.releaseId ? "1900-01" : "2019-01"}
          max={f.dateRange.to.slice(0, 7)}
          value={f.dateRange.from.slice(0, 7)}
          onChange={(e) => dates(e.target.value, f.dateRange.to.slice(0, 7))}
        />
      </label>
      <label>
        To
        <input
          type="month"
          min={f.dateRange.from.slice(0, 7)}
          max={f.releaseId ? "2100-12" : "2026-12"}
          value={f.dateRange.to.slice(0, 7)}
          onChange={(e) => dates(f.dateRange.from.slice(0, 7), e.target.value)}
        />
      </label>
      {f.source !== "All" && hasRegionalProvider(scopeCatalog.sources.find(s=>s.source===f.source), scopeCatalog.releaseId) && (
        <label className={styles.fullField}>
          Area
          <SelectField aria-label="Area" value={f.regionId || ""}
            onValueChange={regionId=>onChange({...value,filters:{...f,regionId:regionId||undefined}})}
            options={[{value:"",label:"All areas"},...regionsForSource(f.source).map(r=>({value:r.id,label:r.name}))]}/>
        </label>
      )}
    </div>
  );
}
function ContextEditor({
  context,
  onSave,
  disabled,
  catalog,
  fieldKey,
}: {
  context: ResearchContext;
  onSave: (c: ResearchContext) => Promise<void>;
  fieldKey:string;
  disabled: boolean;
  catalog: unknown;
}) {
  const form=useStudioFormDraft(fieldKey,context,"research context"), {draft,change}=form;
  return (
    <>
      <h2 className={styles.panelTitle}>Research context</h2>
      <fieldset disabled={disabled}><ScopeFields value={draft} onChange={change} />
      <label className={styles.field}>
        Research notes
        <textarea
          value={draft.notes}
          maxLength={6000}
          rows={4}
          onChange={(e) => change({ ...draft, notes: e.target.value })}
        />
      </label>
      <label className={styles.field}>
        Reference text
        <textarea
          value={draft.references}
          maxLength={10000}
          rows={4}
          onChange={(e) => change({ ...draft, references: e.target.value })}
        />
      </label>
      <Button
        disabled={disabled || !form.dirty}
        onClick={() => void form.commit(onSave).catch(()=>{})}
      >
        Save context
      </Button>
      {form.dirty&&<button type="button" onClick={()=>void form.discard()}>Discard context edits</button>}
      {form.conflicted&&<p role="alert">Saved context changed. Your local context is retained; review it before saving.</p>}
      </fieldset>
      <p className={styles.muted}>
        New analyses use this scope. Earlier results retain theirs.
      </p>
      <Capabilities context={context}/>
      <details>
        <summary>Technical details · dataset definitions</summary>
        <p>Project data snapshot · {context.filters.datasetVersion}</p>
        <p>Batch {context.filters.batchId}</p>
        <pre>
          {catalog
            ? JSON.stringify(catalog, null, 2)
            : "Loading admitted dataset metadata…"}
        </pre>
      </details>
    </>
  );
}
function Findings({
  study,
  readOnly,
  action,
  editorEpoch,
  dirty,
  evidence,
  onNew,
}: {
  study: Study;
  readOnly: boolean;
  action: (a: Action) => Promise<void>;
  dirty: () => void;
  evidence: (r: ResearchRun, e: Evidence) => void;
  onNew: () => void;
  editorEpoch:number;
}) {
  const [archived, setArchived] = useState(false);
  return (
    <>
      <div className={styles.sectionHead}>
        <h2>Findings</h2>
        <div className={styles.actions}>
          <button onClick={() => setArchived((v) => !v)}>
            {archived ? "Active findings" : "Archived"}
          </button>
          {!readOnly && (
            <button
              onClick={onNew}
            >
              <Plus size={14} /> New finding
            </button>
          )}
        </div>
      </div>
      {!study.findings.filter((f) => f.archived === archived).length && (
        <div className={styles.empty}>
          <FileText size={27} />
          <p>No {archived ? "archived " : ""}findings yet.</p>
        </div>
      )}
      {study.findings
        .filter((f) => f.archived === archived)
        .map((f) => (
          <Finding
            key={`${f.id}-${editorEpoch}`}
            finding={f}
            study={study}
            readOnly={readOnly}
            action={action}
            dirty={dirty}
            evidence={evidence}
          />
        ))}
    </>
  );
}
function Finding({
  finding: f,
  study,
  readOnly,
  action,
  dirty,
  evidence,
}: {
  finding: ResearchFinding;
  study: Study;
  readOnly: boolean;
  action: (a: Action) => Promise<void>;
  dirty: () => void;
  evidence: (r: ResearchRun, e: Evidence) => void;
}) {
  const edit = (a: Action) => action({ type: "finding", id: f.id, ...a });
  const run = study.runs.find((r) => r.id === f.runId);
  return (
    <article className={styles.finding}>
      <div className={styles.findingHead}>
        <SelectField aria-label="Finding type" compact value={f.kind} disabled={readOnly}
          onValueChange={kind=>void edit({kind})} options={["Observation","Hypothesis","Open question"].map(value=>({value,label:value}))}/>
        <span className={styles.muted}>
          {f.evidenceIds.length ? "Evidence linked" : "No data evidence"}
        </span>
      </div>
      {readOnly ? (
        <>
          <h3>{f.title}</h3>
          <p>{f.explanation}</p>
        </>
      ) : (
        <>
          <EditableText
            fieldKey={`${study.id}:finding:${f.id}:title`}
            value={f.title}
            label="Finding title"
            single
            onSave={(title) => edit({ title })}
            max={500}
            onDirty={dirty}
          />
          <EditableText
            fieldKey={`${study.id}:finding:${f.id}:explanation`}
            value={f.explanation}
            label="Finding explanation"
            onSave={(explanation) => edit({ explanation })}
            onDirty={dirty}
          />
        </>
      )}
      <div className={researchStyles.checks}>
        <span>{f.checks?.evidenceLinked ? "Evidence linked" : "Evidence unverified"}</span>
        <span>{f.checks?.numericChecked ? "Specified values checked" : "Numbers not checked"}</span>
        <span>{f.checks?.userReviewed ? "User reviewed" : "Review needed"}</span>
        {f.checks?.unsupportedClaim && <span>Claim not established</span>}
      </div>
      {!readOnly && <div className={researchStyles.tools}><button disabled={!f.claims?.length} onClick={() => action({type:"finding_check",id:f.id})}>Check specified values</button><button onClick={() => action({type:"finding_review",id:f.id})}>Mark as reviewed</button></div>}
      <div className={styles.runMeta}>
        {scope(f.context)} · {f.context.filters.datasetVersion}
      </div>
      <div className={styles.actions}>
        {run && f.evidenceIds.length > 0 && (
          <button
            onClick={() =>
              evidence(
                run,
                run.evidence.find((e) => e.id === f.evidenceIds[0])!,
              )
            }
          >
            Evidence <ArrowUpRight size={13} />
          </button>
        )}
        {!readOnly && (
          <>
            <button
              onClick={() =>
                action({ type: "block_add", kind: "finding", refId: f.id })
              }
            >
              Add to report
            </button>
            <button
              onClick={() =>
                action({
                  type: "finding_archive",
                  id: f.id,
                  archived: !f.archived,
                })
              }
            >
              {f.archived ? "Restore" : "Archive"}
            </button>
            <button
              onClick={() => action({ type: "finding_delete", id: f.id })}
            >
              Delete
            </button>
          </>
        )}
      </div>
      <details>
        <summary>Limitations & edit history</summary>
        <p>{f.limitations}</p>
        <p>
          {f.origin === "assistant"
            ? "Saved from an assistant result; wording remains unverified."
            : "User-authored content."}{" "}
          Created {timestamp(f.createdAt)}
        </p>
        {f.edits.map((e, i) => (
          <div className={styles.version} key={i}>
            <small>
              {timestamp(e.at)} · {e.kind}
            </small>
            <strong>{e.title}</strong>
            <p>{e.explanation}</p>
          </div>
        ))}
      </details>
    </article>
  );
}
function Capabilities({context}:{context:ResearchContext}) {
  const [entries,setEntries]=useState<ResourceCatalogEntry[]>([]),[error,setError]=useState("");
  const key=JSON.stringify(context);
  useEffect(()=>{const abort=new AbortController();void studioRequest<ResourceCatalogEntry[]>(`/resources?context=${encodeURIComponent(key)}`,"GET",undefined,abort.signal).then(setEntries).catch(e=>{if(!abort.signal.aborted)setError(e.message);});return()=>abort.abort();},[key]);
  return <section aria-label="Data capabilities"><h3>Available research</h3><p className={researchStyles.note}>Published platform resources for {context.filters.source}. Source definitions remain independent; a saved chart does not establish a causal claim.</p>{error&&<p role="alert">{error}</p>}{entries.map(e=><div className={researchStyles.capability} key={e.id}><strong>{e.label} · {e.availability}</strong>{e.reason&&<span>{e.reason}</span>}<span>{e.limitations.join(" ")}</span></div>)}</section>;
}

function ReportMetadataEditor({study,action}:{study:Study;action:(a:Action)=>Promise<void>}) {
  const meta={template:study.reportMeta?.template||"brief" as const,language:study.reportMeta?.language||"en" as const,author:study.reportMeta?.author||"",date:study.reportMeta?.date||new Date().toISOString().slice(0,10)};
  const form=useStudioFormDraft<Omit<ReportMetadata,"contractVersion"|"title">>(`${study.id}:reportDetails`,meta,"report details"),{draft,change}=form;
  return <section aria-label="Report details">
    <label className={researchStyles.field}>Author<input value={draft.author} onChange={e=>change({...draft,author:e.target.value})}/></label>
    <label className={researchStyles.field}>Date<input type="date" value={draft.date} onChange={e=>change({...draft,date:e.target.value})}/></label>
    <label className={researchStyles.field}>Language<SelectField aria-label="Language" value={draft.language} onValueChange={language=>change({...draft,language:language as typeof draft.language})} options={[{value:"en",label:"English"},{value:"zh",label:"中文"},{value:"bilingual",label:"English / 中文"}]}/></label>
    <button disabled={!form.dirty} onClick={()=>void form.commit(metadata=>action({type:"report_details",metadata})).catch(()=>{})}>Save report details</button>
    {form.dirty&&<button onClick={()=>void form.discard()}>Discard report detail edits</button>}
    {form.conflicted&&<p role="alert">Saved report details changed. Local values are retained for review.</p>}
  </section>;
}

function editLabel(action:Action) {
  return ({rename:"Study title",report_title:"Report title",report_details:"Document details",draft:"Research question",context:"Research context",report_meta:"Report details",block_edit:"Report block",finding:"Finding"} as Record<string,string>)[String(action.type)] || String(action.type).replaceAll("_"," ");
}
function readableEditValue(value:unknown):string {
  if(value===undefined||value===null)return "Not set";
  if(typeof value==="boolean")return value?"Yes":"No";
  if(typeof value!=="object")return String(value)||"Empty";
  if(Array.isArray(value))return value.map(readableEditValue).join("; ");
  return Object.entries(value).map(([key,item])=>`${key.replaceAll("_"," ")}: ${readableEditValue(item)}`).join(" · ");
}
function editValue(action:Action) {
  return Object.entries(action).filter(([key])=>!["type","id"].includes(key)).map(([key,value])=>`${key}: ${readableEditValue(value)}`).join("\n");
}
function savedEditValue(saved:Study,action:Action) {
  const type=String(action.type);
  if(type==="rename")return saved.title;
  if(type==="report_title")return saved.reportMeta?.title||saved.title;
  if(type==="draft")return saved.draft||"Empty";
  if(type==="context")return readableEditValue(saved.context);
  if(type==="report_details")return readableEditValue(saved.reportMeta);
  if(type==="report_meta")return readableEditValue(saved.reportMeta);
  const record=type==="block_edit"?saved.report.find(b=>b.id===action.id):type==="finding"?saved.findings.find(f=>f.id===action.id):undefined;
  if(!record)return "This is a separate action; no matching saved field.";
  return Object.keys(action).filter(key=>!["type","id"].includes(key)).map(key=>`${key}: ${readableEditValue((record as unknown as Record<string,unknown>)[key])}`).join("\n");
}
