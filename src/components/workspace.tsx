"use client";
import {
  createContext,
  useContext,
  useState,
  useEffect,
  type ReactNode,
} from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Sun,
  Moon,
  Settings2,
  ArrowUpRight,
  FileText,
  Check,
  CircleHelp,
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
}
interface WorkspaceState {
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
  ["/data", "Data"],
  ["/imports", "Imports"],
  ["/reports", "Reports"],
];
export function Workspace({ children }: { children: ReactNode }) {
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS),
    [agentOpen, setAgentOpen] = useState(false),
    [evidence, setEvidence] = useState<EvidenceView | null>(null),
    [notice, setNotice] = useState("");
  const path = usePathname();
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
            <Link className="brand" href="/" aria-label="ARSIA overview">
              <span className="brand-symbol">
                A<span />
              </span>
              <span>ARSIA</span>
            </Link>
            <nav className="navigation" aria-label="Main navigation">
              {NAV.map(([href, label]) => (
                <Link
                  key={href}
                  href={href}
                  className={path === href ? "nav-item active" : "nav-item"}
                  aria-current={path === href ? "page" : undefined}
                >
                  {path === href && (
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
          <main id="main">{children}</main>
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
