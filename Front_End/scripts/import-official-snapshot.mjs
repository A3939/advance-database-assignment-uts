/** Read-only admission of the project's pinned official reader export. */
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { resolve, basename, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const workspaceRoot = resolve(projectRoot, "..");
const input = resolve(
  process.argv[2] || resolve(workspaceRoot, "artifacts/role-e-completion-20260928/official-v1"),
);
const indexPath = resolve(
  process.argv[3] ||
    resolve(workspaceRoot, "artifacts/pr49-pr50-review-20260928/current-evidence.json"),
);
const output = resolve(projectRoot, "data/official");
const batch = "bcc5da57-25f2-41ec-9925-bef421b02671";
const pinnedReaderHash =
  "fed5e2ea8736ce5db17fbdf1227cc4e6cafed2ec8fa3937956c218542e134e8d";
const digest = (bytes) => createHash("sha256").update(bytes).digest("hex");
const index = JSON.parse(await readFile(indexPath, "utf8"));
const wanted = [
  "reader-results.json",
  "manifest.json",
  "raw-qa.json",
  "source-metrics.json",
  "recovery-cost.json",
];
const admitted = new Map();
for (const name of wanted) {
  const ref = index.runs.official.evidence_files.find(
    (r) => basename(r.path) === name,
  );
  if (!ref) throw Error(`No receipt for ${name}`);
  const bytes = await readFile(resolve(input, ref.path));
  if (digest(bytes) !== ref.sha256)
    throw Error(`Evidence hash mismatch: ${name}`);
  admitted.set(name, {
    bytes,
    hash: ref.sha256,
    data: JSON.parse(bytes.toString("utf8")),
  });
}
if (admitted.get("reader-results.json").hash !== pinnedReaderHash)
  throw Error("Unreviewed reader snapshot");
const recovery = admitted.get("recovery-cost.json").data.result;
if (
  recovery.resolution !== "succeeded" ||
  recovery.observed_batch_status !== "succeeded" ||
  recovery.current_batch_id !== batch
)
  throw Error("Batch was not successfully published");
const receipt = JSON.parse(
  await readFile(resolve(input, "receipt.json"), "utf8"),
);
if (receipt.status !== "passed") throw Error("Official replay did not pass");
const reports = admitted.get("reader-results.json").data;
const measured = admitted.get("source-metrics.json").data.measured;
for (const source of ["nsw", "vic", "qld"]) {
  const id = `official_${source}`;
  for (const suffix of ["trend", "monthly", "severity", "map", "units"]) {
    const report = reports[`${id}:${suffix}`];
    if (
      report.dataset_kind !== "official" ||
      report.batch_id !== batch ||
      report.source_id !== id
    )
      throw Error("Mixed report identity");
    for (const row of report.rows || [])
      if (row.batch_id !== batch || row.source_id !== id)
        throw Error("Mixed row identity");
  }
  const months = reports[`${id}:monthly`].rows;
  if (
    months.length !== 60 ||
    new Set(months.map((r) => `${r.period_year}-${r.period_month}`)).size !== 60
  )
    throw Error("Incomplete month coverage");
  for (const key of [
    "crash_count",
    "fatal_crash_count",
    "fatality_count",
    "casualty_count",
  ]) {
    if (months.reduce((sum, r) => sum + r[key], 0) !== measured[id][key])
      throw Error(`Monthly reconciliation failed: ${id} ${key}`);
    for (const year of reports[`${id}:trend`].rows) {
      if (
        months
          .filter((r) => r.period_year === year.period_year)
          .reduce((sum, r) => sum + r[key], 0) !== year[key]
      )
        throw Error("Annual reconciliation failed");
    }
  }
  if (
    reports[`${id}:severity`].rows.reduce(
      (sum, r) => sum + r.crash_count,
      0,
    ) !== measured[id].crash_count
  )
    throw Error("Severity reconciliation failed");
}
const manifest = admitted.get("manifest.json").data;
const qa = admitted
  .get("raw-qa.json")
  .data.qa.filter((r) => r[1] === "batch")
  .map((r) => ({ check: r[0], status: r[2], violations: r[3] }));
const provenance = {
  version: "official-v1",
  datasetKind: "official",
  mode: "snapshot",
  batchId: batch,
  recordedAt:
    receipt.finished_at ||
    receipt.completed_at ||
    "2026-09-28T12:43:08.025519+00:00",
  runtimeCommit: receipt.versions.runtime_commit,
  inputFingerprint: recovery.input_fingerprint,
  coverage: { from: "2020-01-01", to: "2024-12-31" },
  publicationStatus: recovery.observed_batch_status,
  evidenceHashes: Object.fromEntries(
    [...admitted].map(([name, value]) => [name, value.hash]),
  ),
  inputs: manifest.files.map(
    ({ resource_id, source_id, file_sha256, raw_count, parser_version }) => ({
      resourceId: resource_id,
      sourceId: source_id,
      sha256: file_sha256,
      rawCount: raw_count,
      parserVersion: parser_version,
    }),
  ),
  qa,
  totals: measured,
  independentMemberSignoff: receipt.versions.independent_member_signoff,
  finalPlatformAccepted: receipt.versions.final_platform_accepted,
  scope:
    "Fixed project export from a successful official-data build. Not a live database or current government feed. QA07 location is limited; official crash-location maps are unavailable. Interstate totals are not supported.",
};
await mkdir(output, { recursive: true });
await writeFile(
  resolve(output, "reader-results.json"),
  admitted.get("reader-results.json").bytes,
);
await writeFile(
  resolve(output, "provenance.json"),
  `${JSON.stringify(provenance, null, 2)}\n`,
);
console.log(
  JSON.stringify({
    imported: true,
    batchId: batch,
    sources: 3,
    monthsPerSource: 60,
    readerSha256: pinnedReaderHash,
    output: "data/official",
  }),
);
