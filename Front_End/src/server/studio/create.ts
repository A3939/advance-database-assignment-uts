import { object, executeAnalysisTool } from "../agent/tools";
import { analysisRuntime } from "../agent/runtime";
import { evidenceRows } from "../agent/evidence";
import { evidenceAssurance } from "../agent/claims";
import { ResearchCollector } from "./collector";
import {
  contextValue,
  textValue,
  uuid,
  now,
  type StudioStore,
  StudioError,
} from "./store";
import type { ResearchRun, Study } from "../../services/studio-contracts";
import { readArtifact } from "../analysis/artifacts";
import { saveResource } from "./resources";

const pendingByStore = new WeakMap<StudioStore, Map<string, Promise<Study>>>();
export async function createStudy(store: StudioStore, input: unknown) {
  const inputObject = object(input);
  if (typeof inputObject.transferId !== "string")
    return createStudyInner(store, inputObject);
  const transfers = pendingByStore.get(store) || new Map<string, Promise<Study>>();
  pendingByStore.set(store, transfers);
  const id = inputObject.transferId;
  const pending = transfers.get(id);
  if (pending) return pending;
  const work = createStudyInner(store, inputObject).finally(() =>
    transfers.delete(id),
  );
  transfers.set(id, work);
  return work;
}
async function createStudyInner(store: StudioStore, input: unknown) {
  const a = object(input);
  if (a.kind === "analytics" && a.definitionId !== undefined) {
    const { kind: _kind, granularity, question: _question, ...resource } = a;
    void _kind; void _question;
    if (granularity !== undefined && a.definitionId === "trend" && resource.query === undefined)
      resource.query = { granularity };
    return saveResource(store, resource);
  }
  if (a.transferId) {
    const { transfer, studyId } = store.transfer(String(a.transferId));
    if (studyId) return store.get(studyId);
    const attachments = transfer.events.filter((e) => e.type === "artifact");
    for (const e of attachments)
      if (!(await readArtifact(e.artifact.id)))
        throw new StudioError(
          "A generated attachment has expired. Run the question in Studio again; this response was not imported.",
          410,
        );
    const claim = store.claimTransfer(transfer.id);
    if (!claim.created) return claim.study;
    const s = claim.study;
    const begun = store.beginRun(s.id, uuid(), transfer.question);
    begun.run.origin = "ask-ai";
    const collector = new ResearchCollector(store, s.id, begun.run);
    try {
      for (const event of transfer.events) await collector.accept(event);
      collector.run.status = "complete";
      const saved = collector.persist();
      return saved;
    } catch {
      collector.run.status = "failed";
      collector.run.error =
        "The response could not be imported completely. Rerun this question.";
      collector.persist();
      throw new StudioError(
        "Unable to import the complete response. An incomplete study was retained for recovery.",
        500,
      );
    }
  }
  const context = contextValue(a.context);
  const question = textValue(a.question || a.title, 2000);
  const title = textValue(a.title || question.slice(0, 120), 120);
  if (a.kind !== "analytics") return store.create(title, context, typeof a.question === "string" ? textValue(a.question, 2000, true) : question);
  const granularity = a.granularity;
  if (granularity !== "monthly" && granularity !== "yearly")
    throw new StudioError("Unsupported trend interval.");
  const { service, snapshot } = await analysisRuntime({
    page: "/studio",
    filters: context.filters,
  });
  const scope = { page: "/studio", filters: context.filters };
  const args = {
    source: null,
    dateRange: null,
    granularity,
    metric: context.metric,
  };
  const result = await executeAnalysisTool(
    "time_series",
    args,
    scope,
    service,
    snapshot,
  );
  const trend = await service.getTimeSeries(context.filters, granularity);
  const s = store.create(title, context);
  const run: ResearchRun = {
    id: uuid(),
    question,
    context,
    status: "complete",
    answer:
      trend.meta.availability === "available"
        ? "Saved analysis from Analytics. Counts retain the selected source, dates and metric definitions."
        : `Analysis availability: ${trend.meta.availability}. ${trend.meta.reason || "No values were substituted."}`,
    progress: "",
    createdAt: now(),
    updatedAt: now(),
    attempt: 1,
    previousAttempts: [],
    plan: [],
    skipPresentation: false,
    artifactIds: [],
    changes: [],
    origin: "analytics",
    evidence: [
      {
        id: "E1",
        title: "Trend analysis",
        description:
          "Server-queried project snapshot. No client-supplied values were imported.",
        result,
        rows: evidenceRows(result),
        query: {
          tool: "time_series",
          parameters: args,
          requestedContext: scope,
          assurance: evidenceAssurance("time_series",result),
        },
      },
    ],
    views: [
      {
        id: "trend",
        title: `${context.metric} over time`,
        kind: "line",
        rows: trend.data.map((p) => ({
          source: p.source || context.filters.source,
          period: p.period,
          [context.metric]: p[context.metric],
        })),
        x: "period",
        y: context.metric,
        series: context.filters.source === "All" ? "source" : null,
        evidenceId: "E1",
        source: context.filters.source,
        period: `${context.filters.dateRange.from} – ${context.filters.dateRange.to}`,
        truncated: false,
      },
    ],
  };
  return store.mutate(s.id, (s) => {
    s.runs.push(run);
  });
}
