import "server-only";
import { mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { createHash, randomUUID } from "node:crypto";
import { createModelAudit } from "@/server/agent/model-audit";
import { ModelBudgetError } from "@/server/agent/model-budget";
import { routeModel } from "@/server/agent/model-routing";
import { join } from "node:path";
import type { ResponseCreateParamsNonStreaming } from "openai/resources/responses/responses";
import { configuredModel } from "@/server/agent/runtime";
import { importAgentInstructions, validGatewayToken, validateGatewayBody } from "@/server/imports/agent-model";
import { selectImportModelPolicy } from "@/server/imports/agent-policy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 900;
const headers = { "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" };
let active = false;

export async function POST(request: Request) {
  let owns = false;
  let audit: Awaited<ReturnType<typeof createModelAudit>> | undefined;
  try {
    if (!["127.0.0.1:3100", "localhost:3100", "[::1]:3100"].includes(request.headers.get("host") || "") ||
        new URL(request.url).protocol !== "http:") return Response.json({ error: "Local worker only" }, { status: 403, headers });
    const configPath = join(process.cwd(), "artifacts/imports-local/runtime.json");
    const file = await stat(configPath);
    if (!file.isFile() || file.size > 16384 || (file.mode & 0o077)) throw Error("Worker is not configured");
    const config = JSON.parse(await readFile(configPath, "utf8"));
    if (config.mode !== "local-test" || !validGatewayToken(request.headers.get("authorization"), config.agent_gateway_token))
      return Response.json({ error: "Worker authentication required" }, { status: 403, headers });
    if (active) return Response.json({ error: "Import model worker is busy", retryable: true }, { status: 429, headers });
    if (!request.headers.get("content-type")?.startsWith("application/json") || !request.body)
      return Response.json({ error: "JSON body required" }, { status: 400, headers });
    const reader = request.body.getReader(); const chunks: Uint8Array[] = []; let bytes = 0;
    try {
      while (true) {
        const { done, value } = await reader.read(); if (done) break;
        bytes += value.length;
        if (bytes > 2 * 1024 * 1024) { await reader.cancel(); return Response.json({ error: "Model context exceeds its byte budget" }, { status: 413, headers }); }
        chunks.push(value);
      }
    } finally { reader.releaseLock(); }
    let body;
    try { body = validateGatewayBody(JSON.parse(Buffer.concat(chunks).toString("utf8"))); }
    catch { return Response.json({ error: "Invalid model input or tool contract" }, { status: 400, headers }); }
    const configured = configuredModel();
    const catalog = await readFile(join(process.cwd(), "pipeline/arsia_pipeline/profiles/agent-policies.json"), "utf8");
    let modelPolicy;
    try { modelPolicy = selectImportModelPolicy(catalog, body.policy_profile, body.policy_catalog_sha256); }
    catch { return Response.json({ error: "Import policy does not match the durable session", diagnostics: { code: "policy_mismatch" }, retryable: false }, { status: 409, headers }); }
    // The request body was read asynchronously; recheck immediately before
    // claiming the single model slot, before any further await.
    if (active) return Response.json({ error: "Import model worker is busy", retryable: true }, { status: 429, headers });
    active = true; owns = true;
    const sdk = await readFile(join(process.cwd(), "pipeline/AUTONOMOUS_CONTRACT.md"), "utf8");
    if (Buffer.byteLength(sdk) > 64000) throw Error("Adapter SDK instruction budget exceeded");
    const instructions = `${importAgentInstructions}\n\nThe authoritative adapter contract below is already supplied for this request. It remains present after conversation compaction. Do not repeatedly call get_adapter_contract to recover it.\n\n${sdk}`;
    const policyHash = createHash("sha256").update(instructions).digest("hex");
    const policyDirectory = join(process.cwd(), "artifacts/imports-local/model-policies");
    await mkdir(policyDirectory, { recursive: true, mode: 0o700 });
    const policyPath = join(policyDirectory, `${policyHash}.txt`);
    try { await writeFile(policyPath, instructions, { flag: "wx", mode: 0o400 }); }
    catch (failure) {
      if ((failure as NodeJS.ErrnoException).code !== "EEXIST" || await readFile(policyPath, "utf8") !== instructions) throw failure;
    }
    const task = request.headers.get("x-arsia-task");
    if (!task || !/^[a-f0-9:-]{36,160}$/.test(task)) throw Error("Durable model task identity required");
    audit = await createModelAudit(routeModel({surface:"imports"}), "imports-agent", undefined, `imports:${task}`);
    const requestId = randomUUID();
    await audit.request(requestId);
    const result = await configured.client.responses.create({
      model: modelPolicy.model, instructions,
      input: body.input as ResponseCreateParamsNonStreaming["input"],
      tools: body.tools as ResponseCreateParamsNonStreaming["tools"],
      store: false, parallel_tool_calls: false, max_output_tokens: modelPolicy.max_output_tokens,
      reasoning: { effort: modelPolicy.reasoning_effort },
    }, { signal: AbortSignal.any([request.signal, AbortSignal.timeout(modelPolicy.request_timeout_seconds * 1000)]), timeout: modelPolicy.request_timeout_seconds * 1000, maxRetries: 0 });
    await audit.response({requestId,id:result.id,model:result.model,status:result.status ?? "unknown",usage:result.usage});
    await audit.finish("completed");
    return Response.json({ id: result.id, output: result.output, usage: result.usage, status: result.status, model: modelPolicy.model, model_settings: modelPolicy,
      model_policy_sha256: policyHash, sdk_contract_sha256: createHash("sha256").update(sdk).digest("hex") }, { headers });
  } catch (error) {
    await audit?.finish(request.signal.aborted ? "cancelled" : "failed").catch(() => {});
    if (error instanceof ModelBudgetError) return Response.json({error:error.message, diagnostics:{code:error.code}, retryable:error.code === "MODEL_BUSY"}, {status:429,headers});
    // Provider request bodies/messages can contain source rows. Return only
    // protocol classifications; never serialize its request, headers or stack.
    const failure=error as {name?:unknown;status?:unknown;code?:unknown;param?:unknown;request_id?:unknown;headers?:Headers};
    const bounded=(value:unknown)=>typeof value==='string' && /^[A-Za-z0-9_.:[\]-]{1,120}$/.test(value) ? value : undefined;
    const retryValue=failure?.headers?.get?.("retry-after");
    const retrySeconds=retryValue ? (/^\d+(\.\d+)?$/.test(retryValue) ? Number(retryValue) : (Date.parse(retryValue)-Date.now())/1000) : NaN;
    const retryAfter=Number.isFinite(retrySeconds) ? Math.max(1,Math.min(120,Math.ceil(retrySeconds))) : undefined;
    const diagnostics={type:bounded(failure?.name),provider_status:typeof failure?.status==='number'?failure.status:undefined,code:bounded(failure?.code),param:bounded(failure?.param),request_id:bounded(failure?.request_id),retry_after_seconds:retryAfter};
    return Response.json({ error: "Import model service unavailable, timed out or refused the request. The durable worker retains task progress.", diagnostics, retryable: true }, { status: 503, headers });
  } finally { if (owns) active = false; }
}
