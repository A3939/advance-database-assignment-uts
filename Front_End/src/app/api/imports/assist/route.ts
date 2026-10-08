import "server-only";
import { randomUUID } from "node:crypto";
import { configuredModel } from "@/server/agent/runtime";
import { bridgeImport, guardImportRequest, ImportBridgeError } from "@/server/imports/bridge";
import { advisoryInput, importAdviceFormat, importAdviceInstructions, parseImportAdvice } from "@/server/imports/advisor";
import type { LocalImportJob } from "@/services/imports-contracts";
import { ModelBudgetError } from "@/server/agent/model-budget";
import { createModelAudit } from "@/server/agent/model-audit";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 250;
const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
let active = false;
const starts: number[] = [];

export async function POST(request: Request) {
  try {
    guardImportRequest(request);
    if (!request.headers.get("content-type")?.startsWith("application/json"))
      throw new ImportBridgeError(415, "Use a JSON request.");
    if (!request.body) throw new ImportBridgeError(400, "Missing request.");
    const reader = request.body.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        size += value.length;
        if (size > 16000) { await reader.cancel(); throw new ImportBridgeError(413, "Source context is too large."); }
        chunks.push(value);
      }
    } finally { reader.releaseLock(); }
    let body: { job_id?: unknown; source_context?: unknown };
    try { body = JSON.parse(Buffer.concat(chunks).toString("utf8")); }
    catch { throw new ImportBridgeError(400, "Invalid JSON."); }
    if (!body || typeof body.job_id !== "string" || !/^[a-f0-9-]{36}$/.test(body.job_id))
      throw new ImportBridgeError(400, "Choose a local import task.");
    const internalHeaders = new Headers(request.headers);
    internalHeaders.delete("content-length");
    const local = await bridgeImport(new Request(`${new URL(request.url).origin}/api/imports/jobs/${body.job_id}`, {
      method: "GET", headers: internalHeaders, signal: request.signal,
    }), ["jobs", body.job_id]);
    if (!local.ok) return local;
    let input;
    try { input = advisoryInput(await local.json() as LocalImportJob, body.source_context); }
    catch (error) { throw new ImportBridgeError(400, error instanceof Error ? error.message : "Source information is missing."); }
    const now = Date.now();
    while (starts.length && starts[0] < now - 60000) starts.shift();
    if (active || starts.length >= 4) throw new ImportBridgeError(429, "Schema assistance is busy. Wait before retrying.");
    let configured;
    try { configured = configuredModel(); }
    catch { throw new ImportBridgeError(503, "AI is not configured. You can still supply a reviewed mapping profile and run the deterministic pipeline."); }
    active = true;
    starts.push(now);
    let audit: Awaited<ReturnType<typeof createModelAudit>> | undefined;
    try {
      audit = await createModelAudit(configured.selection, "imports-assist");
      const signal = AbortSignal.any([request.signal, AbortSignal.timeout(240000)]);
      for (let attempt = 0; attempt < 2; attempt++) {
        const requestId = randomUUID();
        await audit.request(requestId);
        const response = await configured.client.responses.create({
          model: configured.model,
          instructions: importAdviceInstructions + (attempt ? "\nA previous draft failed structural validation. Recheck required response fields and the direct severity dictionary shape. Repair formatting only; do not invent missing source definitions." : ""),
          input: [{ role: "user", content: JSON.stringify(input) }],
          store: false,
          max_output_tokens: 12000,
          text: { format: importAdviceFormat },
          ...(/^gpt-(5|6)/.test(configured.model) ? { reasoning: { effort: configured.reasoningEffort } } : {}),
        }, { signal });
        await audit.response({requestId,id:response.id,model:response.model,usage:response.usage,status:response.status ?? "unknown"});
        if (response.status !== "completed") throw Error("Incomplete response");
        try {
          const advice = parseImportAdvice(response.output_text, configured.model);
          await audit.finish("completed");
          return Response.json(advice, { headers });
        }
        catch { if (attempt) throw Error("Invalid draft after bounded repair"); }
      }
      throw Error("No complete draft");
    } catch (error) {
      await audit?.finish(request.signal.aborted ? "cancelled" : "failed").catch(() => {});
      if (error instanceof ModelBudgetError) throw new ImportBridgeError(429, error.message);
      throw new ImportBridgeError(502, "AI could not produce a complete schema draft. No task, rule or data was changed.");
    } finally { active = false; }
  } catch (error) {
    return Response.json({ error: error instanceof ImportBridgeError ? error.message : "Schema assistance could not complete." },
      { status: error instanceof ImportBridgeError ? error.status : 500, headers });
  }
}
