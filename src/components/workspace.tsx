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
  House,
  ChartNoAxesCombined,
  ChartBar,
  MapPin,
  ShieldCheck,
  Menu,
  ArrowUpRight,
  FileText,
  Check,
  CircleHelp,
} from "lucide-react";
import { MotionConfig } from "motion/react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
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
  { href: "/", label: "Overview", icon: House },
  { href: "/analytics", label: "Trends", icon: ChartNoAxesCombined },
  { href: "/severity", label: "Severity", icon: ChartBar },
  { href: "/map", label: "Map", icon: MapPin },
  { href: "/data", label: "Data & Quality", icon: ShieldCheck },
];
export function Workspace({ children }: { children: ReactNode }) {
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS),
    [menuOpen, setMenuOpen] = useState(false),
    [evidence, setEvidence] = useState<EvidenceView | null>(null),
    [notice, setNotice] = useState("");
  const path = usePathname();
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
        showEvidence: setEvidence,
        notify: setNotice,
      }}
    >
      <MotionConfig reducedMotion="user">
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <div className={`app-shell independent-shell${path === "/" || path === "/analytics" || path === "/map" || path === "/severity" ? " is-dashboard" : ""}`}>
          <button className="mobile-menu-button" aria-label="Open navigation" aria-expanded={menuOpen} onClick={() => setMenuOpen(true)}>
            <Menu size={22} />
          </button>
          {menuOpen && <button className="mobile-nav-shade" aria-label="Close navigation" onClick={() => setMenuOpen(false)} />}
          <aside className={`topbar product-sidebar${menuOpen ? " is-open" : ""}`}>
            <Link className="brand" href="/" aria-label="ARSIA overview" onClick={() => setMenuOpen(false)}>
              <strong>ARSIA</strong>
              <small>Road Safety Intelligence</small>
            </Link>
            <nav className="navigation" aria-label="Main navigation">
              {NAV.map(({ href, label, icon: Icon }) => (
                <Link
                  key={href}
                  href={href}
                  className={path === href ? "nav-item active" : "nav-item"}
                  aria-current={path === href ? "page" : undefined}
                  onClick={() => setMenuOpen(false)}
                >
                  <Icon size={19} aria-hidden="true" />
                  <span>{label}</span>
                </Link>
              ))}
            </nav>
            <div className="sidebar-footnote">
              <span aria-hidden="true" />
              Evidence for safer roads
            </div>
          </aside>
          <div className="product-content">
            <header className="product-header">
              <div>
                <strong>Australian Road Crash Analytics</strong>
                <span>Evidence for safer roads</span>
              </div>
              <p>NSW · VIC · QLD <span>Project snapshot · 2020–2024</span></p>
            </header>
            <main id="main">{children}</main>
          </div>
        </div>
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
