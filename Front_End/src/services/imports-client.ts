import type { LocalImportAdvice, LocalImportCatalog, LocalImportHealth, LocalImportJob, LocalImportStorage } from "./imports-contracts";

export function createImportsClient(base: "/api/imports" | "/api/imports-test") {
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${base}${path}`, { ...init, cache: "no-store" });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw Error(data.error || data.detail || "The local import service could not complete this request.");
  return data as T;
}
const post = <T>(path: string, body: unknown = {}, signal?: AbortSignal) => request<T>(path, {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal,
});
return {
  health: (signal?: AbortSignal) => request<LocalImportHealth>("/health", { signal }),
  storage: (signal?: AbortSignal) => request<LocalImportStorage>("/storage", { signal }),
  jobStorage: (id: string, signal?: AbortSignal) => request<LocalImportStorage>(`/jobs/${encodeURIComponent(id)}/storage`, { signal }),
  jobs: (signal?: AbortSignal) => request<{ jobs: LocalImportJob[] }>("/jobs", { signal }),
  job: (id: string, signal?: AbortSignal) => request<LocalImportJob>(`/jobs/${encodeURIComponent(id)}`, { signal }),
  create: (label: string, source_hint: string, request_id: string, signal?: AbortSignal) => post<LocalImportJob>("/jobs", { label, source_hint: source_hint || undefined, request_id }, signal),
  submit: (id: string, profile?: unknown, answers?: string) => post<LocalImportJob>(`/jobs/${encodeURIComponent(id)}/submit`, { ...(profile ? { profile } : {}), ...(answers?.trim() ? {answers:answers.trim()} : {}) }),
  cancel: (id: string) => post<LocalImportJob>(`/jobs/${encodeURIComponent(id)}/cancel`),
  retry: (id: string) => post<LocalImportJob>(`/jobs/${encodeURIComponent(id)}/retry`),
  evidence: (id: string) => request<Record<string, unknown>>(`/jobs/${encodeURIComponent(id)}/evidence`),
  catalog: (signal?: AbortSignal) => request<LocalImportCatalog>("/catalog", { signal }),
  report: (source_id: string, release_id: string) => request<Record<string, unknown>>(`/reports?${new URLSearchParams({ source_id, release_id })}`),
  assist: (job_id: string, source_context: string) => post<LocalImportAdvice>("/assist", { job_id, source_context }),
  /** XHR sends the File as binary and exposes actual transferred-byte progress. */
  upload(id: string, file: File, signal: AbortSignal, progress: (sent: number) => void) {
    return new Promise<LocalImportJob>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      const abort = () => xhr.abort();
      const cleanup = () => signal.removeEventListener("abort", abort);
      xhr.open("PUT", `${base}/jobs/${encodeURIComponent(id)}/files?${new URLSearchParams({ filename: file.name })}`);
      xhr.setRequestHeader("Content-Type", "application/octet-stream");
      xhr.upload.onprogress = event => progress(event.loaded);
      xhr.onerror = () => { cleanup(); reject(Error("Upload connection failed. Completed files are retained; the incomplete file was not admitted.")); };
      xhr.onabort = () => { cleanup(); reject(new DOMException("Upload stopped", "AbortError")); };
      xhr.onload = () => {
        cleanup();
        try {
          const data = JSON.parse(xhr.responseText);
          if (xhr.status < 200 || xhr.status >= 300) throw Error(data.error || data.detail || "The file could not be admitted.");
          resolve(data);
        } catch (error) { reject(error instanceof Error ? error : Error("Invalid upload response.")); }
      };
      signal.addEventListener("abort", abort, { once: true });
      if (signal.aborted) { cleanup(); reject(new DOMException("Upload stopped", "AbortError")); return; }
      xhr.send(file);
    });
  },
};

}
export const localImports = createImportsClient("/api/imports");
export const isolatedImports = createImportsClient("/api/imports-test");
