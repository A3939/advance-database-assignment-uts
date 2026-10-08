import type { LocalImportStorage } from "@/services/imports-contracts";

const size = (n: number | null | undefined) => n == null ? "Unknown" : `${(n / 1024 / 1024).toFixed(2)} MiB`;
const labels: Record<string, string> = { raw_blob: "Original files", upload_receipt: "Upload receipts",
  execution_input: "Processing inputs", candidate_output: "Processed data", qa_work_db: "Temporary quality checks",
  evidence: "Validation evidence", archive: "Archives", container: "Test database", database_volume: "Database storage" };

export function ImportStorage({ storage }: { storage: LocalImportStorage | null }) {
  if (!storage?.managed) return null;
  const archived = storage.resources?.filter(r => r.state === "archived").length || 0;
  const blocked = storage.resources?.filter(r => r.state === "blocked").length || 0;
  return <section aria-label="Import storage">
    <h3>Test storage</h3>
    <p>Original files with identical content share storage. Each upload keeps its own receipt and quality checks.</p>
    <dl>{Object.entries(storage.groups).map(([kind, group]) => <div key={kind}>
      <dt>{labels[kind] || "Other retained files"}</dt>
      <dd>Logical: {group.unknown_sizes ? "Partially measured" : size(group.logical_bytes)} · Allocated: {group.unknown_sizes ? "Partially measured" : size(group.allocated_bytes)} · {group.count} resources</dd>
    </div>)}</dl>
    <p>Shared original content: {size(storage.shared_bytes)}. File allocation: reported separately from logical size. Database size: {size(storage.docker_bytes)}.</p>
    {archived > 0 && <p>{archived} resources archived · restore required before use.</p>}
    {blocked > 0 && <p>{blocked} resources retained because storage maintenance needs attention.</p>}
    <small>{storage.truncated ? "Partial resource list. " : ""}Estimates cover registered test resources; other files may be unmeasured. {storage.measured_at && `Updated ${new Date(storage.measured_at).toLocaleTimeString()}.`}</small>
  </section>;
}
