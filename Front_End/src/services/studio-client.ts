import { analysisHref, DEFAULT_VIEW } from "./analysis-state";
import type { Study, StudioEvent } from "./studio-contracts";
export async function studioRequest<T>(
  path: string,
  method = "GET",
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`/api/studio${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
    signal,
  });
  const data = await response
    .json()
    .catch(() => ({ error: "The research service is unavailable." }));
  if (!response.ok)
    throw Object.assign(
      new Error(data.error || "Unable to save this research."),
      { status: response.status },
    );
  return data as T;
}
export async function* streamStudy(
  id: string,
  body: unknown,
  signal: AbortSignal,
): AsyncGenerator<StudioEvent> {
  const response = await fetch(`/api/studio/${id}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
    cache: "no-store",
  });
  if (!response.ok) {
    const e = await response.json().catch(() => ({}));
    throw Error(e.error || "Analysis is unavailable. Please retry.");
  }
  if (!response.body) throw Error("Missing analysis stream.");
  const reader = response.body.getReader(),
    decoder = new TextDecoder();
  let pending = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      pending += decoder.decode(value, { stream: true });
      let newline;
      while ((newline = pending.indexOf("\n")) >= 0) {
        const line = pending.slice(0, newline);
        pending = pending.slice(newline + 1);
        if (line.trim()) yield JSON.parse(line) as StudioEvent;
      }
    }
  } finally {
    await reader.cancel().catch(() => {});
    reader.releaseLock();
  }
}
export async function openStudyFromPage(input: unknown): Promise<Study> {
  return studioRequest<Study>("", "POST", input);
}

/** Use the saved study scope, rather than discovering an unrelated current release. */
export function studyHref(study: Pick<Study, "id" | "context">): string {
  return `${analysisHref("/studio", study.context.filters, { ...DEFAULT_VIEW, metric: study.context.metric })}&study=${encodeURIComponent(study.id)}`;
}
