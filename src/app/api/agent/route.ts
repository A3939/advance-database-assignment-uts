import "server-only";
import OpenAI from "openai";
import { createRegionalProvider, loadRegionSnapshot } from "@/server/region-data";
import {
  createOfficialProvider,
  loadOfficialSnapshot,
} from "@/server/official-data";
import { parseAgentRequest, sameOrigin } from "@/server/agent/request";
import { LIMITS, runAgent, safeAgentError } from "@/server/agent/runner";
import type { AgentEvent } from "@/services/contracts";
export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 250;
import { AnalysisWorkspace } from "@/server/analysis/workspace";
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
  // This independent preview never spends another account's AI quota.
  if (process.env.ARSIA_AI_ENABLED !== "true")
    return Response.json(
      { error: "ARSIA Assistant is disabled in this edition." },
      { status: 503, headers },
    );
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
  let snapshot, regional;
  try {
    snapshot = await loadOfficialSnapshot();
    regional = await loadRegionSnapshot();
  } catch {
    return Response.json(
      { error: "The verified project snapshot is unavailable." },
      { status: 503, headers },
    );
  }
  const model = process.env.OPENAI_MODEL?.trim() || "gpt-6-luna";
  const client = new OpenAI({
    apiKey: process.env.OPENAI_API_KEY,
    baseURL: "https://api.openai.com/v1",
    timeout: 45000,
    maxRetries: 1,
    logLevel: "off",
  });
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
        for await (const event of runAgent(parsed, {
          model,
          snapshot,
          service: createRegionalProvider(createOfficialProvider(snapshot), regional),
          workspace: new AnalysisWorkspace(parsed.context, createRegionalProvider(createOfficialProvider(snapshot), regional), regional),
          signal,
          stream: (params, s) => client.responses.create(params, { signal: s }),
        }))
          emit(event);
      } catch (error) {
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
