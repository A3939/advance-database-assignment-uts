"use client";
import {
  createContext,
  useCallback,
  useContext,
  useState,
  useEffect,
  useRef,
  type ReactNode,
} from "react";
import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import {
  Sun,
  Moon,
  Settings2,
  ArrowUpRight,
  FileText,
  Check,
  CircleHelp,
  Database,
} from "lucide-react";
import { MotionConfig, motion } from "motion/react";
import { Button } from "@/components/ui/button";
import { useTheme } from "@/components/theme-provider";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { AgentPanel } from "./agent-panel";
import { DEFAULT_FILTERS, IS_DEMO } from "@/services/config";
import type { Filters, Evidence } from "@/services/contracts";
interface EvidenceView {
  title: string;
  description: string;
  rows?: { label: string; value: string }[];
  href?: string;
  demo?: boolean;
  evidence?: Evidence[];
  result?: unknown;
  workspaceControls?: boolean;
  presentation?: "summary";
}
import { analysisHref, parseAnalysisState, DEFAULT_VIEW, type AnalysisViewState } from "@/services/analysis-state";
import { fetchCatalog, SNAPSHOT_CATALOG, catalogFilters, type DataCatalog } from "@/services/catalog-contracts";
import { workspaceParameters, preservePageSelection } from "@/services/data-navigation";
interface WorkspaceState {
  catalog: DataCatalog;
  catalogReady: boolean;
  catalogError: string;
  view: AnalysisViewState;
  setView: (view: AnalysisViewState) => void;
  analysisHref: (path: string) => string;
  filters: Filters;
  setFilters: (f: Filters) => void;
  askAI: () => void;
  showEvidence: (e: EvidenceView) => void;
  notify: (message: string) => void;
}
const Context = createContext<WorkspaceState | null>(null);
export function useWorkspace() {
  const c = useContext(Context);
  if (!c) throw Error("Workspace provider missing");
  return c;
}
const NAV = [
  ["/", "Overview"],
  ["/analytics", "Analytics"],
  ["/studio", "Studio"],
  ["/data", "Data"],
];
/** URL updates must keep the independently pinned Studio document selection. */
function currentPageHref(path: string, filters: Filters, view: AnalysisViewState) {
  const href = analysisHref(path, filters, view);
  return preservePageSelection(path, href, window.location.search);
}
export function Workspace({ children }: { children: ReactNode }) {
  const [filters, storeFilters] = useState<Filters>(DEFAULT_FILTERS),
    [agentOpen, setAgentOpen] = useState(false),
    [evidence, setEvidence] = useState<EvidenceView | null>(null),
    [notice, setNotice] = useState("");
  const path = usePathname();
  const [view, storeView] = useState(DEFAULT_VIEW);
  const [linkError, setLinkError] = useState("");
  const [ready, setReady] = useState(false);
  const [catalog, setCatalog] = useState<DataCatalog>(SNAPSHOT_CATALOG);
  const followLatest = useRef<boolean | null>(null);
  const stateRef = useRef({filters,view,catalog});
  useEffect(() => { stateRef.current = {filters,view,catalog}; }, [filters,view,catalog]);
  useEffect(() => {
    const abort = new AbortController();
    let serial = 0;
    const restore = async () => {
      const current = ++serial;
      const params = workspaceParameters(path, window.location.search);
      if (followLatest.current === null) followLatest.current = !params.has("datasetVersion") && !params.has("batchId");
      try {
        const nextCatalog = await fetchCatalog(params.get("releaseId") || undefined, abort.signal, params.get("datasetVersion") === "official-v1");
        if (abort.signal.aborted || current !== serial) return;
        const parsed = parseAnalysisState(params.toString(), nextCatalog);
        setCatalog(nextCatalog); storeFilters(parsed.filters); storeView(parsed.view); setLinkError(parsed.error || ""); setReady(true);
        if (!parsed.error && !params.has("batchId")) window.history.replaceState(null, "", currentPageHref(window.location.pathname, parsed.filters, parsed.view));
      } catch (error) {
        if (!abort.signal.aborted && current === serial) { setLinkError(error instanceof Error ? error.message : "The requested release could not be restored."); setReady(true); }
      }
    };
    void restore();
    const pop = () => { followLatest.current = false; void restore(); };
    const discover = async () => {
      if (!followLatest.current) return;
      try {
        const next = await fetchCatalog(undefined, abort.signal);
        const current = stateRef.current;
        if (abort.signal.aborted || next.batchId === current.catalog.batchId || (current.catalog.mode === "local" && next.mode !== "local")) return;
        const updated = { ...catalogFilters(next), source: next.sources.some(s=>s.source===current.filters.source) ? current.filters.source : "All", dateRange: current.filters.dateRange };
        setCatalog(next); storeFilters(updated);
        window.history.replaceState(null, "", currentPageHref(window.location.pathname, updated, current.view));
        setNotice("A new local release is available. Charts and analysis now use the same updated release.");
      } catch { /* Keep the currently pinned, verified release during transient outages. */ }
    };
    const published = () => { void discover(); };
    const pin = () => { followLatest.current = false; };
    const timer = setInterval(published, 15000);
    window.addEventListener("popstate", pop);
    window.addEventListener("arsia:publication", published);
    window.addEventListener("arsia:pin-release", pin);
    return () => { abort.abort(); clearInterval(timer); window.removeEventListener("popstate", pop); window.removeEventListener("arsia:publication", published); window.removeEventListener("arsia:pin-release", pin); };
  }, [path]);
  const setFilters = useCallback((next: Filters) => {
    storeFilters(next);
    window.history.pushState(null, "", currentPageHref(window.location.pathname, next, stateRef.current.view));
  }, []);
  const setView = useCallback((next: AnalysisViewState) => {
    storeView(next);
    window.history.pushState(null, "", currentPageHref(window.location.pathname, stateRef.current.filters, next));
  }, []);
  const href = (path: string) => analysisHref(path, filters, view);
  const { theme, toggleTheme } = useTheme();
  useEffect(() => {
    if (!notice) return;
    const t = setTimeout(() => setNotice(""), 4500);
    return () => clearTimeout(t);
  }, [notice]);
  return (
    <Context.Provider
      value={{
        filters,
        catalog,
        catalogReady: ready,
        catalogError: linkError,
        setFilters,
        view, setView, analysisHref: href,
        askAI: () => setAgentOpen(true),
        showEvidence: setEvidence,
        notify: setNotice,
      }}
    >
      <MotionConfig reducedMotion="user">
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <div
          className={`app-shell${path === "/" || path === "/explore" ? " is-dashboard" : ""}${path === "/studio" ? " is-studio" : ""}`}
        >
          <header className="topbar">
            <Link className="brand" href={href("/")} aria-label="ARSIA overview">
              <span className="brand-symbol">
                <Image src="/arsia-logo.png" alt="" width={44} height={44} priority />
              </span>
              <span>ARSIA</span>
            </Link>
            <nav className="navigation" aria-label="Main navigation">
              {NAV.map(([href, label]) => (
                <Link
                  key={href}
                  href={analysisHref(href, filters, view)}
                  className={(path === href || (href === "/analytics" && path.startsWith("/analytics/"))) ? "nav-item active" : "nav-item"}
                  aria-current={(path === href || (href === "/analytics" && path.startsWith("/analytics/"))) ? "page" : undefined}
                >
                  {(path === href || (href === "/analytics" && path.startsWith("/analytics/"))) && (
                    <motion.span
                      className="nav-active"
                      layoutId="nav-indicator"
                      transition={{ duration: 0.2 }}
                    />
                  )}
                  <span>{label}</span>
                </Link>
              ))}
            </nav>
            <div className="header-actions">
              <Button
                variant="ghost"
                className="icon-button"
                aria-label="Settings"
                onClick={() =>
                  setEvidence({
                    title: "Workspace settings",
                    workspaceControls: true,
                    description: `This local workspace uses the ${theme} theme and English interface. Use the sun or moon button in the header to switch themes. System reduced-motion preferences are respected automatically.`,
                    rows: [
                      {
                        label: "Appearance",
                        value: theme === "dark" ? "Dark theme" : "Light theme",
                      },
                      {
                        label: "Data provider",
                        value: IS_DEMO
                          ? "Demo fixtures"
                          : catalog.mode === "local" ? "Local integration · immutable release · source-specific publications" : catalog.localStatus === "empty" ? "No local publication yet · showing the project snapshot" : "Project snapshot · official source data · read-only, not live",
                      },
                      { label: filters.releaseId ? "Release" : "Snapshot batch", value: filters.batchId },
                      {
                        label: "Accounts & preferences",
                        value: "Not connected in this preview",
                      },
                      { label: "Font", value: "Inter, served locally" },
                    ],
                  })
                }
              >
                <Settings2 />
              </Button>
              <Button
                variant="ghost"
                className="icon-button theme-toggle"
                aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
                title={`${theme === "dark" ? "Dark" : "Light"} theme · Switch to ${theme === "dark" ? "light" : "dark"} theme`}
                onClick={toggleTheme}
              >
                {theme === "dark" ? (
                  <Sun aria-hidden="true" />
                ) : (
                  <Moon aria-hidden="true" />
                )}
              </Button>
              <Button
                variant="outline"
                className="avatar"
                aria-label="Profile"
                onClick={() =>
                  setEvidence({
                    title: "Local workspace profile",
                    description:
                      "You are exploring ARSIA in a local workspace. Sign-in, teams and account management are not connected.",
                    rows: [
                      {
                        label: "Workspace",
                        value: "Peixian · ARSIA",
                      },
                    ],
                  })
                }
              >
                P
              </Button>
            </div>
          </header>
          <main id="main">{path === "/data" || path === "/studio" ? <>{linkError && <div className="error-banner" role="alert"><p>{linkError} Dataset analysis is unavailable; your data workspace and saved studies remain accessible.</p><Button variant="outline" onClick={() => window.location.assign(preservePageSelection(path, analysisHref(path, DEFAULT_FILTERS, DEFAULT_VIEW), window.location.search))}>Open supported snapshot</Button></div>}{children}</> : !ready ? <div className="visual-loading" role="status">Restoring analysis…</div> : linkError ? <div className="error-banner" role="alert"><p>{linkError}</p><Button onClick={() => window.location.assign(preservePageSelection(path, analysisHref(path, DEFAULT_FILTERS, DEFAULT_VIEW), window.location.search))}>Open supported snapshot</Button></div> : children}</main>
        </div>
        <AgentPanel
          key={[
            path,
            filters.source,
            filters.regionId || "",
            filters.dateRange.from,
            filters.dateRange.to,
            filters.datasetVersion,
            filters.batchId,
          ].join("|")}
          open={agentOpen}
          setOpen={(open) => {
            // Evidence is the top interaction layer; dismiss it before its parent drawer.
            if (!open && evidence) setEvidence(null);
            else setAgentOpen(open);
          }}
        />
        <Dialog
          open={!!evidence}
          onOpenChange={(open) => {
            if (!open) setEvidence(null);
          }}
        >
          <DialogContent className="evidence-dialog">
            <DialogHeader>
              <span className="eyebrow">
                <FileText size={15} />
                DATA & EVIDENCE
              </span>
              <DialogTitle>{evidence?.title}</DialogTitle>
              <DialogDescription>{evidence?.description}</DialogDescription>
            </DialogHeader>
            {evidence?.workspaceControls && <div className="workspace-settings-actions">
              <Button variant="ghost" size="sm" onClick={async () => {
                try {
                  const response=await fetch('/api/model-usage',{cache:'no-store'});
                  if(!response.ok) throw Error('The local usage ledger is unavailable.');
                  const usage=await response.json();
                  setEvidence({title:'Local model usage',description:usage.note,rows:[
                    {label:'Active model requests',value:`${usage.totals.active} / ${usage.policy.concurrentRequests} across all pages; Imports share 1 slot`},
                    {label:'Recorded requests',value:String(usage.totals.requests)},
                    {label:'Reported input / output tokens',value:`${usage.totals.reportedInput} / ${usage.totals.reportedOutput}`},
                    {label:'Cached input (already included)',value:String(usage.totals.reportedCachedInput)},
                    {label:'Requests with unknown usage',value:String(usage.totals.unknownRequests)},
                    {label:'User-wide token budget',value:'Not configured'},
                    ...(['analysis','imports'] as const).map(surface=>({label:`${surface==='analysis'?'Ask AI / Studio':'Imports'} containers`,
                      value:`${usage.resources[surface].active ?? 'Unknown'} active · ${usage.resources[surface].stopped ?? 'Unknown'} stopped · ${usage.resources[surface].cleanupPending ?? 'Unknown'} cleanup pending. ${usage.resources[surface].note}`})),
                    {label:'Execution resource limits',value:`Analysis: 512 MiB, 1 CPU, 30s request / 35s independent wall limit. Imports: 1 worker; limits are fixed by each task runtime. ${usage.resources.note}`},
                    ...usage.tasks.map((task:{surface:string;requests:number;maxRequests:number;requestTimeoutMs:number;lastStop:string|null}) =>
                      ({label:task.surface,value:`${task.requests} / ${task.maxRequests} cumulative requests · ${task.requestTimeoutMs/1000}s request limit${task.lastStop ? ' · '+task.lastStop : ''}`})),
                  ]});
                } catch {setNotice('The local usage ledger is unavailable. Usage is unknown until it can be read.');}
              }}>Model usage</Button>
              <Button variant="ghost" size="sm" className="release-mode-button" aria-label={catalog.mode === "local" ? "Local release" : "Use local data"} onClick={() => { void fetchCatalog().then(next => { if (stateRef.current.catalog.mode === "local" && next.mode !== "local") throw Error("The local release service is unavailable. The current release has been preserved."); followLatest.current = true; setCatalog(next); const f = catalogFilters(next); storeFilters(f); storeView(DEFAULT_VIEW); setLinkError(""); window.history.pushState(null, "", currentPageHref(path,f,DEFAULT_VIEW)); }).catch(error => setNotice(error instanceof Error ? error.message : "Could not open the latest release.")); }} title="Open the latest local integration release; saved links and studies remain pinned"><Database size={16} className="release-mode-icon" aria-hidden="true" /><span className="release-mode-label">{catalog.mode === "local" ? "Local release" : "Use local data"}</span></Button>
            </div>}
            {evidence?.rows && (
              <dl className="evidence-rows">
                {evidence.rows.map((r, i) => (
                  <div key={i}>
                    <dt>{r.label}</dt>
                    <dd>{r.value}</dd>
                  </div>
                ))}
              </dl>
            )}
            {evidence?.presentation !== "summary" && <>
            {evidence?.result !== undefined && (
              <details className="agent-evidence-result">
                <summary>Query result & data basis</summary>
                <pre>{JSON.stringify(evidence.result, null, 2)}</pre>
              </details>
            )}
            {evidence?.href && (
              <a
                className="text-link"
                href={evidence.href}
                target="_blank"
                rel="noreferrer"
              >
                Open source evidence <ArrowUpRight size={15} />
              </a>
            )}
            {!!evidence?.evidence?.length && (
              <div className="evidence-sources">
                {evidence.evidence.map((source) => (
                  <div key={source.id}>
                    {source.href ? (
                      <a
                        className="text-link"
                        href={source.href}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {source.title} <ArrowUpRight size={14} />
                      </a>
                    ) : (
                      <strong>{source.title}</strong>
                    )}
                    <p>{source.description}</p>
                    {!!source.rows?.length && (
                      <dl className="evidence-rows">
                        {source.rows.map((row, index) => (
                          <div key={`${row.label}-${index}`}>
                            <dt>{row.label}</dt>
                            <dd>{row.value}</dd>
                          </div>
                        ))}
                      </dl>
                    )}
                  </div>
                ))}
              </div>
            )}
            <div className="demo-callout">
              <CircleHelp size={17} />
              <span>
                {(evidence?.demo ?? IS_DEMO)
                  ? "Demo evidence describes the frontend fixture; it is not official QA or platform acceptance."
                  : "Project snapshot / metadata. Source restrictions and availability accompany each result. This is a read-only snapshot, not a live database view."}
              </span>
            </div>
            </>}
          </DialogContent>
        </Dialog>
        {notice && (
          <div className="toast" role="status">
            <Check size={17} />
            {notice}
          </div>
        )}
      </MotionConfig>
    </Context.Provider>
  );
}
