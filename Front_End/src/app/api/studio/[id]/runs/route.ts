import "server-only";
import { configuredModel, analysisRuntime } from "@/server/agent/runtime";
import { runAgent, LIMITS, safeAgentError } from "@/server/agent/runner";
import { object } from "@/server/agent/tools";
import { ResearchCollector, researchHistory, selectedResearchContext } from "@/server/studio/collector";
import {
  studioStore,
  StudioError,
  validId,
  textValue,
} from "@/server/studio/store";
import { guard, jsonBody, errorResponse, headers } from "@/server/studio/http";
import { prepareResearchDraft, validateResearchDraft } from "@/server/studio/research-contract";
import type { ResearchMode, StudioEvent } from "@/services/studio-contracts";
import { routeModel } from "@/server/agent/model-routing";
import { createModelAudit } from "@/server/agent/model-audit";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 250;
const state = globalThis as typeof globalThis & {
  studioRuns?: Map<string, AbortController>;
  studioStarts?: number[];
};
const active = (state.studioRuns ||= new Map<string, AbortController>());
const starts = (state.studioStarts ||= []);
type Params = { params: Promise<{ id: string }> };
export async function DELETE(request: Request, { params }: Params) {
  try {
    guard(request);
    const { id } = await params;
    studioStore().get(id);
    active.get(id)?.abort();
    return Response.json({ stopping: active.has(id) }, { headers });
  } catch (e) {
    return errorResponse(e);
  }
}
export async function POST(request: Request, { params }: Params) {
  try {
    const a = object(await jsonBody(request)),
      { id } = await params,
      store = studioStore();
    const study = store.get(id);
    const requestId = validId(a.requestId);
    const existing = store.runRequest(id, requestId);
    if (existing)
      return new Response(JSON.stringify({ type: "study", study }) + "\n", {
        headers: { ...headers, "Content-Type": "application/x-ndjson" },
      });
    if (Object.keys(a).some(key => !["requestId", "question", "skipPresentation", "retryId", "mode", "selectedRunIds", "targetBlockId"].includes(key)))
      throw new StudioError("Unknown research request field.");
    const retry = a.retryId ? study.runs.find(r => r.id === validId(a.retryId)) : undefined;
    const mode = retry?.mode || (a.mode ?? "analyze");
    if (!["explore", "analyze", "draft", "revise"].includes(String(mode))) throw new StudioError("Unknown research mode.");
    const selectedRunIds = retry?.selectedRunIds || (Array.isArray(a.selectedRunIds) ? a.selectedRunIds.map(validId) : []);
    const targetBlockId = retry?.targetBlockId || (a.targetBlockId ? validId(a.targetBlockId) : undefined);
    const prepared = mode === "draft" || mode === "revise" ? prepareResearchDraft(study, mode, selectedRunIds, targetBlockId) : undefined;
    const selectedContext = prepared ? undefined : selectedResearchContext(study, selectedRunIds);
    while (starts.length && starts[0] < Date.now() - 60000) starts.shift();
    if (active.size >= 2 || starts.length >= 12)
      throw new StudioError("Too many analyses. Wait before retrying.", 429);
    let modelConfig;
    try {
      modelConfig = configuredModel(routeModel({surface:"studio"}));
    } catch {
      throw new StudioError(
        "ARSIA Assistant is not configured on the server.",
        503,
      );
    }
    const begun = store.beginRun(
      id,
      requestId,
      textValue(a.question || "Retry", 2000),
      a.skipPresentation === true,
      a.retryId ? validId(a.retryId) : undefined,
      {mode: mode as ResearchMode, selectedRunIds, targetBlockId},
    );
    if (begun.replay)
      return new Response(
        JSON.stringify({ type: "study", study: begun.study }) + "\n",
        { headers: { ...headers, "Content-Type": "application/x-ndjson" } },
      );
    const collector = new ResearchCollector(store, id, begun.run);
    const cancel = new AbortController();
    active.set(id, cancel);
    starts.push(Date.now());
    const signal = AbortSignal.any([
      request.signal,
      cancel.signal,
      AbortSignal.timeout(LIMITS.timeoutMs),
    ]);
    let disconnected = false;
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      async start(controller) {
        const emit = (event: StudioEvent) => {
          if (!disconnected && !request.signal.aborted)
            try {
              controller.enqueue(encoder.encode(JSON.stringify(event) + "\n"));
            } catch {
              disconnected = true;
              cancel.abort();
            }
        };
        emit({ type: "study", study: begun.study });
        let lastSave = 0;
        let audit: Awaited<ReturnType<typeof createModelAudit>> | undefined;
        try {
          audit = await createModelAudit(modelConfig.selection, "studio", undefined, `studio:${id}:${begun.run.id}`);
          const context = {
            page: "/studio",
            filters: collector.run.context.filters,
          };
          const runtime = prepared ? {} : await analysisRuntime(context);
          for await (const event of runAgent(
            {
              context,
              message: collector.run.question,
              history: prepared ? [] : researchHistory(begun.study, collector.run),
            },
            {
              ...runtime,
              model: modelConfig.model,
              reasoningEffort: modelConfig.reasoningEffort,
              recordRequest: audit.request,
          recordResponse: audit.response,
              signal,
              stream: (params, s) =>
                modelConfig.client.responses.create(params, { signal: s }),
              research: {
                mode: mode as ResearchMode,
                ...(selectedContext ? { selectedContext } : {}),
                ...(prepared ? {draft: {materials: prepared.materials, validate: (value: unknown) => validateResearchDraft(store.get(id), prepared, value)}} : {}),
                metric: collector.run.context.metric,
                notes: collector.run.context.notes,
                references: collector.run.context.references,
                skipPresentation: () =>
                  store.get(id).runs.find((r) => r.id === collector.run.id)
                    ?.skipPresentation ?? collector.run.skipPresentation,
              },
            },
          )) {
            signal.throwIfAborted();
            collector.run.skipPresentation =
              store.get(id).runs.find((r) => r.id === collector.run.id)
                ?.skipPresentation ?? collector.run.skipPresentation;
            if (collector.run.skipPresentation)
              for (const task of collector.run.plan)
                if (task.optional && task.status === "pending")
                  task.status = "skipped";
            await collector.accept(event);
            if (event.type !== "artifact" && event.type !== "done") emit(event);
            if (
              Date.now() - lastSave > 700 ||
              [
                "evidence",
                "artifact",
                "visualization",
                "report_draft",
                "done",
                "plan",
              ].includes(event.type)
            ) {
              emit({ type: "study", study: collector.persist() });
              lastSave = Date.now();
            }
          }
          await audit.finish("completed");
        } catch (error) {
          await audit?.finish(signal.aborted ? "cancelled" : "failed").catch(() => {});
          const committed = store.get(id).runs.find(r => r.id === collector.run.id && r.attempt === collector.run.attempt && r.status === "complete");
          if (committed) {
            collector.run = committed;
            (collector.run.completionWarnings ||= []).push("Analysis completed and saved; a later connection or audit operation failed. Review runtime diagnostics before starting another paid analysis.");
          } else {
          collector.run.status =
            cancel.signal.aborted || request.signal.aborted
              ? "stopped"
              : "failed";
          collector.run.error =
            collector.run.status === "stopped"
              ? "Analysis stopped. Partial output is not a completed result."
              : error instanceof StudioError
                ? error.message
                : safeAgentError(signal.aborted ? signal.reason : error)
                    .message;
          emit({
            type: "error",
            code: "ANALYSIS",
            message: collector.run.error,
          });
          }
        } finally {
          if (collector.run.status === "running") {
            collector.run.status = "interrupted";
            collector.run.error =
              "The stream ended before analysis completed. Retry explicitly.";
          }
          collector.run.progress = "";
          try {
            emit({ type: "study", study: collector.persist() });
          } catch {
            emit({
              type: "error",
              code: "UNSAVED",
              message:
                "The final result could not be saved. Reload the last saved version before retrying.",
            });
          }
          active.delete(id);
          if (!disconnected)
            try {
              controller.close();
            } catch {}
        }
      },
      cancel() {
        disconnected = true;
        cancel.abort();
      },
    });
    return new Response(stream, {
      headers: {
        ...headers,
        "Content-Type": "application/x-ndjson; charset=utf-8",
        "X-Accel-Buffering": "no",
      },
    });
  } catch (e) {
    return errorResponse(e);
  }
}
