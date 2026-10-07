import type { ArsiaService, Filters, AgentEvent, Response } from "./contracts";
import type { SeverityChange } from "./severity-change";
import type { SpeedZoneData } from "./speed-zone";

export const DATA_REQUEST_TIMEOUT_MS = 20_000;

/** Bound both the response and its body. A stalled request must not leave a
 * dashboard loading indefinitely, even if a transport ignores cancellation. */
async function readDataJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  signal?.throwIfAborted();
  const controller = new AbortController();
  let rejectStopped!: (reason: unknown) => void;
  const stopped = new Promise<never>((_, reject) => { rejectStopped = reject; });
  const stop = (reason: unknown) => {
    rejectStopped(reason);
    controller.abort(reason);
  };
  const onAbort = () => stop(signal!.reason);
  signal?.addEventListener("abort", onAbort, { once: true });
  const timeout = setTimeout(() => stop(new DOMException(
    "The data request took too long. Please try again.", "TimeoutError",
  )), DATA_REQUEST_TIMEOUT_MS);
  try {
    return await Promise.race([
      (async () => {
        const response = await fetch(url, { signal: controller.signal, cache: "no-store" });
        if (!response.ok) throw Error(`Project data request failed (${response.status}).`);
        return await response.json() as T;
      })(),
      stopped,
    ]);
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", onAbort);
  }
}

async function get<T>(
  report: string,
  filters?: Filters,
  extra: Record<string, string> = {},
  signal?: AbortSignal,
): Promise<T> {
  const params = new URLSearchParams(extra);
  if (filters) {
    params.set("source", filters.source);
    if (filters.regionId) params.set("regionId", filters.regionId);
    params.set("from", filters.dateRange.from);
    params.set("to", filters.dateRange.to);
    params.set("datasetVersion", filters.datasetVersion);
    params.set("batchId", filters.batchId);
  }
  return readDataJson<T>(`/api/data/${report}?${params}`, signal);
}
export const getSeverityChange = (filters: Filters, signal?: AbortSignal) => get<Response<SeverityChange>>("severity-change", filters, {}, signal);
export const getSpeedZones = (filters: Filters, signal?: AbortSignal) => get<Response<SpeedZoneData>>("speed-zones", filters, {}, signal);

export const httpProvider: ArsiaService = {
  getOverview: (f, signal) => get("overview", f, {}, signal),
  getTimeSeries: (f, granularity, signal) => get("timeseries", f, { granularity }, signal),
  getSeverityDistribution: (f, signal) => get("severity", f, {}, signal),
  getMapData: (f, signal) => get("map", f, {}, signal),
  getCrashRecords: (f, pagination, sort) =>
    get("records", f, {
      page: String(pagination.page),
      pageSize: String(pagination.pageSize),
      search: pagination.search || "",
      sort: sort.field,
      direction: sort.direction,
    }),
  getDatasetMetadata: (signal, filters) => get("metadata", filters, {}, signal),
  async *sendAgentMessage(context, message, signal, history = []) {
    const response = await fetch("/api/agent", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ context, message, history }),
      signal,
      cache: "no-store",
    });
    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      yield {
        type: "error",
        code: String(response.status),
        message:
          error.error || "The analysis service is unavailable. Please retry.",
      };
      return;
    }
    if (!response.body) throw Error("Missing response stream.");
    const reader = response.body.getReader(),
      decoder = new TextDecoder();
    let pending = "",
      completed = false;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        pending += decoder.decode(value, { stream: true });
        let newline;
        while ((newline = pending.indexOf("\n")) >= 0) {
          const line = pending.slice(0, newline);
          pending = pending.slice(newline + 1);
          if (!line.trim()) continue;
          const event = JSON.parse(line) as AgentEvent;
          if (event.type === "done" || event.type === "error") completed = true;
          yield event;
        }
      }
      if (!completed && !signal?.aborted)
        throw Error("The response stream ended early. Please retry.");
    } finally {
      await reader.cancel().catch(() => {});
      reader.releaseLock();
    }
  },
};
