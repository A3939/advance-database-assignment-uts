import type { AgentContext, AgentTurn } from "../../services/contracts";
import { DEFAULT_FILTERS } from "../../services/config";
import { object } from "./tools";
import { parseOfficialFilters } from "../official-data";

export const contextKey = (c: AgentContext) =>
  [
    c.page,
    c.filters.source,
    c.filters.regionId || "",
    c.filters.dateRange.from,
    c.filters.dateRange.to,
    c.filters.datasetVersion,
    c.filters.batchId,
  ].join("|");
function parseContext(value: unknown): AgentContext {
  const c = object(value),
    f = object(c.filters),
    r = object(f.dateRange);
  if (
    !["/", "/analytics", "/explore", "/data"].includes(
      String(c.page),
    )
  )
    throw Error("Unknown page context.");
  for (const value of [f.source, f.datasetVersion, f.batchId, r.from, r.to])
    if (typeof value !== "string" || !value || value.length > 100)
      throw Error("Incomplete filter context.");
  const filters = parseOfficialFilters(
    new URLSearchParams({
      source: f.source as string,
      ...(f.regionId !== undefined ? { regionId: String(f.regionId) } : {}),
      from: r.from as string,
      to: r.to as string,
      datasetVersion: f.datasetVersion as string,
      batchId: f.batchId as string,
    }),
  );
  if (
    filters.batchId !== DEFAULT_FILTERS.batchId ||
    filters.datasetVersion !== DEFAULT_FILTERS.datasetVersion
  )
    throw Error(
      "This dataset version or batch is not connected. Refresh the page.",
    );
  return { page: c.page as string, filters };
}
export function parseAgentRequest(value: unknown) {
  const body = object(value),
    context = parseContext(body.context);
  if (
    typeof body.message !== "string" ||
    !body.message.trim() ||
    body.message.length > 2000
  )
    throw Error("Enter a question of 1–2,000 characters.");
  if (!Array.isArray(body.history) || body.history.length > 12)
    throw Error("Conversation history is too long.");
  let size = 0;
  const history: AgentTurn[] = body.history
    .map((item) => {
      const h = object(item);
      if (
        !["user", "assistant"].includes(String(h.role)) ||
        typeof h.text !== "string" ||
        h.text.length > 16000
      )
        throw Error("Invalid conversation turn.");
      size += h.text.length;
      return {
        role: h.role as AgentTurn["role"],
        text: h.text,
        context: parseContext(h.context),
      };
    })
    .filter((turn) => contextKey(turn.context) === contextKey(context));
  if (size > 24000) throw Error("Conversation is too long. Start a new chat.");
  return { context, message: body.message.trim(), history };
}
export type AgentRequest = ReturnType<typeof parseAgentRequest>;

export function sameOrigin(request: Request) {
  if (request.headers.get("sec-fetch-site") === "cross-site") return false;
  const origin = request.headers.get("origin");
  if (!origin) return true;
  try {
    const supplied = new URL(origin),
      target = new URL(request.url);
    // Next may normalize request.url to localhost while the browser uses 127.0.0.1.
    return (
      supplied.protocol === target.protocol &&
      supplied.host === (request.headers.get("host") || target.host)
    );
  } catch {
    return false;
  }
}
