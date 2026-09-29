"use client";
import dynamic from "next/dynamic";
import type {
  AnalysisArtifact,
  AnalysisView,
} from "@/services/analysis-contracts";
const AgentVisualization = dynamic(() => import("./agent-visualization"), {
  ssr: false,
});
import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import {
  ArrowUpRight,
  Plus,
  Download,
  ChartNoAxesCombined,
  Code2,
  Layers,
  FileText,
  Loader2,
  RotateCcw,
  Send,
  Sparkles,
  Square,
} from "lucide-react";
import { Button } from "./ui/button";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "./ui/sheet";
import { useWorkspace } from "./workspace";
import { arsia } from "@/services";
import type { AgentContext, AgentTurn, Evidence } from "@/services/contracts";
interface Message {
  id: string;
  role: "user" | "assistant";
  text: string;
  evidence: Evidence[];
  artifacts: AnalysisArtifact[];
  views: AnalysisView[];
  status: "complete" | "streaming" | "error" | "stopped";
  error?: string;
  question?: string;
}
export function AgentPanel({
  open,
  setOpen,
}: {
  open: boolean;
  setOpen: (open: boolean) => void;
}) {
  const { filters, showEvidence } = useWorkspace(),
    path = usePathname();
  const [input, setInput] = useState(""),
    [messages, setMessages] = useState<Message[]>([]),
    [busy, setBusy] = useState(false),
    [progress, setProgress] = useState("");
  const controller = useRef<AbortController | null>(null),
    bottom = useRef<HTMLDivElement>(null),
    mounted = useRef(true);
  const context: AgentContext = { filters, page: path };
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "instant", block: "nearest" });
  }, [messages, progress]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      controller.current?.abort();
    };
  }, []);
  useEffect(() => {
    if (!open) controller.current?.abort();
  }, [open]);
  async function send(question: string, retryId?: string) {
    if (!question.trim() || controller.current) return;
    const abort = new AbortController();
    controller.current = abort;
    const id = crypto.randomUUID();
    const previous = retryId
      ? messages.slice(
          0,
          Math.max(0, messages.findIndex((m) => m.id === retryId) - 1),
        )
      : messages;
    // Only completed question/answer pairs enter the next turn, and this component is
    // remounted for every source/date/version/batch/page change.
    const history: AgentTurn[] = [];
    for (let i = 0; i < previous.length - 1; i++) {
      if (
        previous[i].role === "user" &&
        previous[i + 1].role === "assistant" &&
        previous[i + 1].status === "complete"
      ) {
        history.push(
          { role: "user", text: previous[i].text, context },
          { role: "assistant", text: previous[i + 1].text, context },
        );
        i++;
      }
    }
    let chars = 0;
    const bounded = history
      .slice(-10)
      .reverse()
      .filter((m) => {
        chars += m.text.length;
        return chars <= 22000;
      })
      .reverse();
    if (bounded[0]?.role === "assistant") bounded.shift();
    setMessages([
      ...previous,
      {
        id: crypto.randomUUID(),
        role: "user",
        text: question,
        evidence: [],
        artifacts: [],
        views: [],
        status: "complete",
      },
      {
        id,
        role: "assistant",
        text: "",
        question,
        evidence: [],
        artifacts: [],
        views: [],
        status: "streaming",
      },
    ]);
    setInput("");
    setBusy(true);
    setProgress("Planning a read-only query…");
    const update = (fn: (m: Message) => Message) => {
      if (mounted.current)
        setMessages((all) => all.map((m) => (m.id === id ? fn(m) : m)));
    };
    try {
      for await (const event of arsia.sendAgentMessage(
        context,
        question,
        abort.signal,
        bounded,
      )) {
        if (abort.signal.aborted || !mounted.current) break;
        if (event.type === "progress") setProgress(event.text);
        if (event.type === "message") {
          setProgress("Writing the answer…");
          update((m) => ({ ...m, text: m.text + event.text }));
        }
        if (event.type === "evidence")
          update((m) => ({ ...m, evidence: [...m.evidence, event.evidence] }));
        if (event.type === "artifact")
          update((m) => ({
            ...m,
            artifacts: [...m.artifacts, event.artifact],
          }));
        if (event.type === "visualization")
          update((m) => ({ ...m, views: [...m.views, event.view] }));
        if (event.type === "error")
          update((m) => ({ ...m, status: "error", error: event.message }));
        if (event.type === "done")
          update((m) => ({ ...m, status: "complete" }));
      }
      if (abort.signal.aborted) update((m) => ({ ...m, status: "stopped" }));
    } catch {
      update((m) => ({
        ...m,
        status: abort.signal.aborted ? "stopped" : "error",
        error: abort.signal.aborted
          ? undefined
          : "The response was interrupted. Please retry. No simulated answer was substituted.",
      }));
    } finally {
      controller.current = null;
      if (mounted.current) {
        setBusy(false);
        setProgress("");
      }
    }
  }
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetContent className="agent-sheet">
        <SheetHeader className="agent-header">
          <div className="agent-identity">
            <Sparkles size={22} />
            <SheetTitle>ARSIA Assistant</SheetTitle>
          </div>
          <SheetDescription className="sr-only">
            Explore project data, create analyses and inspect evidence.
          </SheetDescription>
          <button
            className="agent-new-chat"
            aria-label="New chat"
            title="New chat"
            disabled={busy || !messages.length}
            onClick={() => setMessages([])}
          >
            <Plus size={18} />
          </button>
        </SheetHeader>
        <div
          className="agent-messages"
          role="log"
          aria-label="Analysis conversation"
          aria-live="polite"
          aria-relevant="additions text"
        >
          {!messages.length && (
            <div className="agent-welcome">
              <div className="agent-orb">
                <Sparkles size={26} />
              </div>
              <h3>Where should we look next?</h3>
              <p>Find patterns. Compare places. Build an analysis.</p>
              <div className="suggestions">
                {[
                  {
                    label: "Understand the data",
                    detail: "Fields, coverage & definitions",
                    icon: Layers,
                    question:
                      "Discover the analysis workspace and summarise its datasets, fields and limitations.",
                  },
                  {
                    label: "Explore a trend",
                    detail: "An interactive view over time",
                    icon: ChartNoAxesCombined,
                    question:
                      "Use workspace_query and present_analysis to chart yearly crashes for this selection. Keep sources separate.",
                  },
                  {
                    label: "Compare areas",
                    detail: "Rank local government areas",
                    icon: ArrowUpRight,
                    question:
                      "Rank the top 10 NSW LGAs by crashes within the selected dates. Use a bar chart and show unmatched coverage. This is not a risk ranking.",
                  },
                  {
                    label: "Create an analysis",
                    detail: "Python, report & downloadable code",
                    icon: Code2,
                    question:
                      "Use Python to calculate year-on-year crash changes for NSW over the selected dates. Export a CSV and concise Markdown report with provenance and limitations. Do not infer causes.",
                  },
                ].map(({ label, detail, icon: Icon, question }) => (
                  <button key={label} onClick={() => void send(question)}>
                    <Icon size={18} />
                    <span>
                      <strong>{label}</strong>
                      <small>{detail}</small>
                    </span>
                    <ArrowUpRight size={14} />
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((m) => (
            <div key={m.id} className={`chat-message ${m.role}`}>
              <span>{m.role === "assistant" ? "ARSIA" : "You"}</span>
              {m.text && <p>{m.text}</p>}
              {m.error && (
                <p role="alert" className="agent-error">
                  {m.error}
                </p>
              )}
              {m.status === "stopped" && (
                <p className="agent-status">
                  Generation stopped. Any partial answer is incomplete.
                </p>
              )}
              {m.status === "error" && m.text && (
                <small>Partial answer · incomplete</small>
              )}
              {m.views.map((view, i) => (
                <AgentVisualization key={`${view.id}-${i}`} view={view} />
              ))}
              {!!m.artifacts.length && (
                <div className="agent-artifacts">
                  {m.artifacts.map((a) => (
                    <a
                      key={a.id}
                      href={a.href}
                      download={a.name}
                      className="agent-artifact"
                    >
                      <FileText size={17} />
                      <span>
                        <strong>{a.name}</strong>
                        <small>
                          {a.kind.toUpperCase()} ·{" "}
                          {Math.max(1, Math.ceil(a.bytes / 1024))} KB ·
                          available for 24h
                        </small>
                      </span>
                      <Download size={16} />
                    </a>
                  ))}
                </div>
              )}
              {!!m.evidence.length && (
                <details className="agent-evidence">
                  <summary>
                    <FileText size={14} />
                    {m.evidence.length}{" "}
                    {m.evidence.length === 1 ? "source" : "sources"} &
                    calculations
                  </summary>
                  {m.evidence.map((e) => (
                    <button
                      className="evidence-link"
                      key={e.id}
                      onClick={() => showEvidence(e)}
                    >
                      {e.title}
                      <ArrowUpRight size={13} />
                    </button>
                  ))}
                </details>
              )}
              {(m.status === "error" || m.status === "stopped") && (
                <Button
                  variant="outline"
                  className="agent-retry"
                  disabled={busy}
                  onClick={() => void send(m.question || "", m.id)}
                >
                  <RotateCcw size={14} />
                  Retry
                </Button>
              )}
            </div>
          ))}
          {busy && (
            <div className="agent-progress" role="status">
              <Loader2 size={15} className="spin" />
              {progress}
            </div>
          )}
          <div ref={bottom} />
        </div>
        <form
          className="agent-input"
          onSubmit={(e) => {
            e.preventDefault();
            void send(input);
          }}
        >
          <label className="sr-only" htmlFor="agent-message">
            Message ARSIA assistant
          </label>
          <textarea
            id="agent-message"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask a question, or describe an analysis…"
            rows={2}
            maxLength={2000}
            onKeyDown={(e) => {
              if (
                e.key === "Enter" &&
                !e.shiftKey &&
                !e.nativeEvent.isComposing
              ) {
                e.preventDefault();
                void send(input);
              }
            }}
          />
          {busy ? (
            <Button
              type="button"
              className="send-button"
              aria-label="Stop generating"
              onClick={() => controller.current?.abort()}
            >
              <Square size={14} />
            </Button>
          ) : (
            <Button
              type="submit"
              className="send-button"
              disabled={!input.trim()}
              aria-label="Send message"
            >
              <Send size={17} />
            </Button>
          )}
        </form>
        <p className="agent-footnote">
          Check conclusions against the evidence.
        </p>
      </SheetContent>
    </Sheet>
  );
}
