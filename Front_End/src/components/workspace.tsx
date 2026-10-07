"use client";
import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
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
  FileText,
  Check,
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
import { SNAPSHOT_CATALOG, type DataCatalog } from "@/services/catalog-contracts";
import { analysisHref, parseAnalysisState, DEFAULT_VIEW, type AnalysisViewState } from "@/services/analysis-state";
interface EvidenceView {
  title: string;
  description: string;
  rows?: { label: string; value: string }[];
  href?: string;
  demo?: boolean;
  evidence?: Evidence[];
  result?: unknown;
}
interface WorkspaceState {
  catalog: DataCatalog;
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
export function Workspace({ children }: { children: ReactNode }) {
  const [filters, storeFilters] = useState<Filters>(DEFAULT_FILTERS),
    [agentOpen, setAgentOpen] = useState(false),
    [evidence, setEvidence] = useState<EvidenceView | null>(null),
    [notice, setNotice] = useState("");
  const path = usePathname();
  const [view, storeView] = useState(DEFAULT_VIEW);
  const [ready, setReady] = useState(false);
  const [linkError, setLinkError] = useState("");
  const stateRef = useRef({ filters, view });
  useEffect(() => { stateRef.current = { filters, view }; }, [filters, view]);
  useEffect(() => {
    let active = true;
    const restore = async () => {
      // Restore only this demo's fixed snapshot after hydration.
      await Promise.resolve();
      if (!active) return;
      const parsed = parseAnalysisState(window.location.search);
      storeFilters(parsed.filters); storeView(parsed.view);
      setLinkError(parsed.error || ""); setReady(true);
    };
    void restore();
    window.addEventListener("popstate", restore);
    return () => { active = false; window.removeEventListener("popstate", restore); };
  }, [path]);
  const setFilters = useCallback((next: Filters) => {
    storeFilters(next);
    stateRef.current = { ...stateRef.current, filters: next };
    window.history.pushState(null, "", analysisHref(window.location.pathname, next, stateRef.current.view));
  }, []);
  const setView = useCallback((next: AnalysisViewState) => {
    storeView(next);
    stateRef.current = { ...stateRef.current, view: next };
    window.history.pushState(null, "", analysisHref(window.location.pathname, stateRef.current.filters, next));
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
        catalog: SNAPSHOT_CATALOG,
        view, setView, analysisHref: href,
        setFilters,
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
          className={`app-shell${path === "/" || path === "/explore" ? " is-dashboard" : ""}`}
        >
          <header className="topbar">
            <Link className="brand" href={href("/")} aria-label="ARSIA overview">
              <span className="brand-symbol">
                <Image src="/arsia-logo.png" alt="" width={44} height={44} priority />
              </span>
              <span>ARSIA</span>
            </Link>
            <nav className="navigation" aria-label="Main navigation">
              {NAV.map(([target, label]) => target === "/studio" ? (
                <button key={target} type="button" className="nav-item"><span>Studio</span></button>
              ) : (
                <Link
                  key={target}
                  href={href(target)}
                  className={(path === target || (target === "/analytics" && path.startsWith("/analytics/"))) ? "nav-item active" : "nav-item"}
                  aria-current={(path === target || (target === "/analytics" && path.startsWith("/analytics/"))) ? "page" : undefined}
                >
                  {(path === target || (target === "/analytics" && path.startsWith("/analytics/"))) && (
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
                          : "Project snapshot · official source data · read-only, not live",
                      },
                      { label: "Snapshot batch", value: filters.batchId },
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
          <main id="main">{path === "/data" ? children : !ready ? <div className="visual-loading">Loading workspace…</div> : linkError ? <div className="demo-link-error" role="alert"><p>{linkError}</p><Link href="/">Return to overview</Link></div> : children}</main>
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
