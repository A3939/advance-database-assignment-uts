import { mkdir, appendFile } from "node:fs/promises";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import type { ResponseUsage } from "openai/resources/responses/responses";
import type { ModelRoute } from "./model-routing";
import { ModelBudgetError, taskBudget, validModelUsage, withModelBudget } from "./model-budget";

/** Records routing and provider usage only; never prompts, keys or data rows. */
export async function createModelAudit(route: ModelRoute, surface: string, root = join(process.cwd(), "artifacts/model-routing"), taskId: string = randomUUID()) {
  await mkdir(root, { recursive: true, mode: 0o700 });
  const path = join(root, `${randomUUID()}.jsonl`);
  const record = async (value: object) => appendFile(path, JSON.stringify({ at: new Date().toISOString(), ...value }) + "\n", { mode: 0o600 });
  await record({ event: "selected", surface, route });
  const budget = taskBudget(surface, taskId);
  const pending = new Set<string>();
  let unknownResponses = 0;
  return {
    request: async (requestId: string) => {
      withModelBudget(root, ledger => ledger.start(budget, requestId));
      pending.add(requestId);
      await record({event:"request_started", requestId, usage:null, usageStatus:"unknown"});
    },
    response: async (value: { id: string; requestId?: string; model: string; usage?: ResponseUsage; status: string }) =>
      {
        if (value.requestId) {
          withModelBudget(root, ledger => ledger.finish(taskId, value.requestId!, value.status, value.usage));
          pending.delete(value.requestId);
        }
        const known = validModelUsage(value.usage);
        if (!known) unknownResponses++;
        await record({ event: "response", ...value, usage: value.usage ?? null, usageStatus:known ? "reported" : "unknown" });
        // Throw only after retaining the raw receipt and durable unknown accounting.
        // runAgent awaits this callback before another round or committed completion.
        if (surface === "studio" && !known) throw new ModelBudgetError("MODEL_USAGE_UNKNOWN", "The Studio model response has no valid usage receipt. This analysis has stopped; its usage remains unknown and is not counted as zero. Review the receipt before another Studio model call.");
      },
    finish: async (status: "completed" | "failed" | "cancelled") => {
      if (pending.size) withModelBudget(root, ledger => { for (const id of pending) ledger.finish(taskId, id, status); });
      await record({ event: "finished", status, taskId, budget, usageComplete: unknownResponses === 0 && pending.size === 0, unknownRequests: unknownResponses + pending.size });
    },
  };
}
