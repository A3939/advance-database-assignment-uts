import "server-only";
import { configuredModel, analysisRuntime } from "@/server/agent/runtime";
import { studioStore, uuid, now as researchNow } from "@/server/studio/store";
import { parseAgentRequest, sameOrigin } from "@/server/agent/request";
import { LIMITS, runAgent, safeAgentError } from "@/server/agent/runner";
import type { AgentEvent } from "@/services/contracts";
import { routeModel } from "@/server/agent/model-routing";
import { createModelAudit } from "@/server/agent/model-audit";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 250;
const headers = {
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
};
// Process-local limits for the local preview; production needs authenticated per-user limits.
let active = 0;
const starts: number[] = [];
async function body(request: Request) {
  if (!request.body) throw Error("Missing body");
  const reader = request.body.getReader();
  let size = 0,
    text = "";
  const decoder = new TextDecoder();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 128000) {
        await reader.cancel();
        throw Error("Too large");
      }
      text += decoder.decode(value, { stream: true });
    }
    return JSON.parse(text + decoder.decode());
  } finally {
    reader.releaseLock();
  }
}
export async function POST(request: Request) {
  if (!sameOrigin(request))
    return Response.json(
      { error: "Cross-origin requests are not allowed." },
      { status: 403, headers },
    );
  if (!request.headers.get("content-type")?.startsWith("application/json"))
    return Response.json({ error: "Use JSON." }, { status: 415, headers });
  let parsed;
  try {
    parsed = parseAgentRequest(await body(request));
  } catch {
    return Response.json(
      {
        error:
          "Invalid question, history or filter context. Use the connected batch and whole-month dates.",
      },
      { status: 400, headers },
    );
  }
  if (!process.env.OPENAI_API_KEY?.trim())
    return Response.json(
      { error: "ARSIA Assistant is not configured on the server." },
      { status: 503, headers },
    );
  const now = Date.now();
  while (starts.length && starts[0] < now - 60000) starts.shift();
  if (active >= 2 || starts.length >= 12)
    return Response.json(
      { error: "Too many analysis requests. Please wait and retry." },
      { status: 429, headers },
    );
  let runtimeContext;
  try {
    runtimeContext = await analysisRuntime(parsed.context);
  } catch {
    return Response.json(
      { error: "The verified project snapshot is unavailable." },
      { status: 503, headers },
    );
  }
  const {snapshot, service, workspace} = runtimeContext;
  const selection = routeModel({surface:"ask", message:parsed.message, historyCount:parsed.history.length, source:parsed.context.filters.source});
  const { model, client, reasoningEffort } = configuredModel(selection);
  const audit = await createModelAudit(selection, "ask");
  if (active >= 2 || starts.filter(t => t > Date.now() - 60000).length >= 12) {
    await audit.finish("failed");
    return Response.json({error:"Too many analysis requests. Please wait and retry."}, {status:429, headers});
  }
  const cancel = new AbortController();
  const signal = AbortSignal.any([
    request.signal,
    cancel.signal,
    AbortSignal.timeout(LIMITS.timeoutMs),
  ]);
  active++;
  starts.push(now);
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const emit = (event: AgentEvent) => {
        if (!cancel.signal.aborted && !request.signal.aborted)
          controller.enqueue(encoder.encode(JSON.stringify(event) + "\n"));
      };
      try {
        const completedEvents: AgentEvent[] = [];
        for await (const event of runAgent(parsed, {
          model,
          reasoningEffort,
          recordRequest: audit.request,
          recordResponse: audit.response,
          snapshot,
          service: service,
          workspace: workspace,
          signal,
          stream: (params, s) => client.responses.create(params, { signal: s }),
        })) {
          if (!["progress", "done"].includes(event.type)) completedEvents.push(event);
          if (event.type === "done" && !signal.aborted) {
            try {
              const id = uuid();
              studioStore().saveTransfer({ id, question: parsed.message, context: parsed.context, events: completedEvents, createdAt: researchNow() });
              emit({ type: "transfer", id });
            } catch { /* The answer remains valid; unavailable persistence gets no transfer button. */ }
          }
          emit(event);
        }
        await audit.finish("completed");
      } catch (error) {
        await audit.finish(signal.aborted ? "cancelled" : "failed").catch(() => {});
        if (!cancel.signal.aborted && !request.signal.aborted)
          emit({
            type: "error",
            ...safeAgentError(signal.aborted ? signal.reason : error),
          });
      } finally {
        active--;
        if (!cancel.signal.aborted) controller.close();
      }
    },
    cancel() {
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
}
