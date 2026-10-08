import type { ArsiaService, ImportJob } from "./contracts";
const jobs = new Map<string, { job: ImportJob; created: number }>();
/** Metadata-only import preview; separate from all reporting data. */
export const importPreview: Pick<
  ArsiaService,
  "createImportJob" | "getImportJobStatus"
> = {
  async createImportJob(files) {
    if (!files.length) throw new Error("Choose at least one file.");
    const id = `demo-import-${crypto.randomUUID()}`;
    const job: ImportJob = {
      id,
      status: "queued",
      demo: true,
      files,
      steps: [
        { label: "File metadata", status: "complete" },
        { label: "Understand fields", status: "pending" },
        { label: "Review mappings", status: "pending" },
        { label: "Validate & publish", status: "pending" },
      ],
      message:
        "Simulation only. Files stay on your device; no contents are uploaded or processed.",
    };
    jobs.set(id, { job, created: Date.now() });
    return structuredClone(job);
  },
  async getImportJobStatus(id) {
    const entry = jobs.get(id);
    if (!entry) throw new Error("Demo job expired. Start a new preview.");
    const elapsed = Date.now() - entry.created;
    const status =
      elapsed < 600 ? "queued" : elapsed < 1400 ? "running" : "needs_input";
    return {
      ...entry.job,
      status,
      steps: entry.job.steps.map((step, i) => ({
        ...step,
        status: i === 0 ? "complete" : i === 1 ? "active" : "pending",
      })),
      message:
        status === "needs_input"
          ? "Ready for a future mapping review. Real parsing, approval and publication are not connected."
          : entry.job.message,
    };
  },
};
