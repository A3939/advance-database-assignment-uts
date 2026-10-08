import { randomUUID } from "node:crypto";
import { createModelAudit } from "@/server/agent/model-audit";
import { routeModel } from "@/server/agent/model-routing";
import { ModelBudgetError } from "@/server/agent/model-budget";
import { ModelSseAudit } from "@/server/agent/model-sse-audit";
import { validGatewayToken } from "@/server/imports/agent-model";
import { codexModelRequest, codexCompactionRequest } from "@/server/imports/codex-model";

const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
let active = false;

export async function codexGateway(request: Request, options: {
  runtimeConfig: () => Promise<{mode:string;agent_gateway_token:string}>;
  auditRoot?: string;
  fetcher?: typeof fetch;
  trustedOutputCap?: number;
}) {
  let owns = false;
  let audit: Awaited<ReturnType<typeof createModelAudit>> | undefined;
  let finished = false;
  const finish = async (status:"completed"|"failed"|"cancelled") => {
    if (finished) return; finished=true;
    try { await audit?.finish(status); } finally { release(); }
  };
  const release = () => { if (owns) { active = false; owns = false; } };
  try {
    if (!["127.0.0.1:3100", "localhost:3100", "[::1]:3100"].includes(request.headers.get("host") || "") ||
        new URL(request.url).protocol !== "http:") return Response.json({ error: "Local worker only" }, { status: 403, headers });
    const cfg = await options.runtimeConfig();
    if (cfg.mode !== "local-test" || !validGatewayToken(request.headers.get("authorization"), cfg.agent_gateway_token))
      return Response.json({ error: "Worker authentication required" }, { status: 403, headers });
    if (active) return Response.json({ error: "Codex transport busy" }, { status: 429, headers });
    if (!request.body || !request.headers.get("content-type")?.startsWith("application/json"))
      return Response.json({ error: "JSON required" }, { status: 400, headers });
    const reader = request.body.getReader(); const chunks: Uint8Array[] = []; let size = 0;
    try {
      while (true) {
        const { done, value } = await reader.read(); if (done) break;
        size += value.length;
        if (size > 4 * 1024 * 1024) { await reader.cancel(); return Response.json({ error: "Context byte limit" }, { status: 413, headers }); }
        chunks.push(value);
      }
    } finally { reader.releaseLock(); }
    const compact = request.headers.get("x-arsia-operation") === "compact";
    let body;
    try { const value = JSON.parse(Buffer.concat(chunks).toString("utf8")); body = compact ? codexCompactionRequest(value) : codexModelRequest(value, options.trustedOutputCap); }
    catch { return Response.json({ error: "Invalid Codex request" }, { status: 400, headers }); }
    if (!process.env.OPENAI_API_KEY?.trim()) throw Error("Model not configured");
    if (active) return Response.json({ error: "Codex transport busy" }, { status: 429, headers });
    active = true; owns = true;
    const task = request.headers.get("x-arsia-task");
    if (!task || !/^[a-f0-9:-]{36,160}$/.test(task)) throw Error("Durable model task identity required");
    audit = await createModelAudit(routeModel({surface:"imports"}), "imports-codex", options.auditRoot, `imports:${task}`);
    const requestId = randomUUID(); await audit.request(requestId);
    const abort = new AbortController();
    const upstream = await (options.fetcher || fetch)("https://api.openai.com/v1/responses" + (compact ? "/compact" : ""), {
      method: "POST", headers: { "Authorization": `Bearer ${process.env.OPENAI_API_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify(body), signal: AbortSignal.any([request.signal, abort.signal, AbortSignal.timeout(600000)]),
    });
    if (!upstream.ok || !upstream.body) {
      const status = upstream.status; await upstream.body?.cancel(); await finish("failed");
      return Response.json({ error: { type: "provider_error", message: "Codex provider refused request", code: `http_${status}` } }, { status, headers });
    }
    if (compact) {
      const response = await upstream.json();
      await audit.response({requestId,id:response.id || requestId,model:response.model || body.model,status:"completed",usage:response.usage});
      await finish("completed");
      return Response.json(response, { headers });
    }
    const source = upstream.body.getReader();
    const receipts = new ModelSseAudit(async value => { await audit!.response({...value,requestId}); });
    const stream = new ReadableStream<Uint8Array>({
      async pull(controller) {
        try {
          const chunk = await source.read();
          if (chunk.done) { await finish(receipts.status); controller.close(); }
          else {
            await receipts.push(chunk.value);
            if (receipts.terminal) await finish(receipts.status);
            // Commit usage/release before delivering the terminal event, so
            // the next Codex request sees the durable shared slot as free.
            controller.enqueue(chunk.value);
          }
        }
        catch (error) { abort.abort(); await source.cancel().catch(() => {}); await finish(request.signal.aborted ? "cancelled" : "failed"); controller.error(error); }
      },
      async cancel() { abort.abort(); await source.cancel().catch(() => {}); await finish("cancelled"); },
    });
    return new Response(stream, { headers: { ...headers, "Content-Type": "text/event-stream" } });
  } catch (error) {
    await finish(request.signal.aborted ? "cancelled" : "failed").catch(() => {});
    if (error instanceof ModelBudgetError) return Response.json({error:{type:"local_budget",code:error.code,message:error.message}}, {status:429,headers});
    return Response.json({ error: { type: "transport_error", message: "Codex transport unavailable" } }, { status: 503, headers });
  }
}
