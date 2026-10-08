"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  ArrowUpRight,
  Database,
  FileBarChart2,
  FileText,
  UploadCloud,
  CheckCircle2,
  Circle,
  Loader2,
  X,
  FolderOpen,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { useWorkspace } from "./workspace";
import { arsia } from "@/services";
import { IS_DEMO, selectSource } from "@/services/config";
import type { Dataset, ImportFile, ImportJob } from "@/services/contracts";
export function DataPage() {
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const { setFilters, filters, catalog, showEvidence, analysisHref } = useWorkspace();
  useEffect(() => {
    let active = true;
    arsia
      .getDatasetMetadata(undefined,filters)
      .then((rows) => {
        if (!active) return;
        setDatasets(rows);
        setLoading(false);
        setError("");
      })
      .catch(() => {
        if (!active) return;
        setLoading(false);
        setError(
          "The source metadata could not be loaded. Please try again.",
        );
      });
    return () => {
      active = false;
    };
  }, [retry,filters]);
  return (
    <div className="secondary-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">YOUR DATA WORKSPACE</span>
          <h1>Know what you’re exploring.</h1>
          <p className="page-subtitle">
            Independent sources from the selected release. Clear definitions. No hidden assumptions.
          </p>
        </div>
        <Link className="button-link primary" href="/imports">
          <UploadCloud size={17} />
          Import data
        </Link>
      </div>
      {error && (
        <div className="error-banner" role="alert">
          <span>{error}</span>
          <Button
            variant="outline"
            onClick={() => {
              setError("");
              setLoading(true);
              setRetry((value) => value + 1);
            }}
          >
            Try again
          </Button>
        </div>
      )}
      {loading && (
        <div className="visual-loading" role="status">
          <Loader2 className="spin" size={18} />
          Loading source metadata…
        </div>
      )}
      {catalog.mode === "snapshot" && <section className="panel evidence-matrix" aria-label="Coverage and interpretation"><h2>Coverage, units & interpretation</h2><p>Fixed 2020–2024 snapshot. Monthly crash events and source-defined people counts are separate measures. No pooled national total or travel-risk rate is calculated.</p><div className="table-scroll"><table><caption className="sr-only">Source coverage and analysis capabilities</caption><thead><tr><th>Source</th><th>Crash coverage</th><th>Severity</th><th>LGA unmatched*</th></tr></thead><tbody><tr><th scope="row">NSW</th><td>Includes non-casualty / towaway events</td><td>Fatal, serious, moderate, minor/other, towaway</td><td>5</td></tr><tr><th scope="row">VIC</th><td>Admitted Accident records; restricted Person/Vehicle detail excluded</td><td>Fatal, serious, other injury, non-injury</td><td>2,365</td></tr><tr><th scope="row">QLD</th><td>Casualty-crash coverage; not all road crashes</td><td>Fatal, hospitalisation, medical treatment, minor injury</td><td>1</td></tr></tbody></table></div><p>*Full pinned batch only. Unmatched events remain in state totals; selected-period matching counts are in map evidence. LGA names map to ABS 2024 reference areas, not crash coordinates or reconstructed historical boundaries.</p><p>State severity is available only for the full five-year export. LGA monthly severity is counted directly in the derived regional extension. Categories are source-specific and cannot be merged into a national injury scale.</p><p>Fatal crash share uses known fatal-status events at state level; unknown measures can withhold the numerator. LGA share uses selected-area crashes and requires known counts. Zero, unknown, no coverage and unsupported are separate states. Neither share is a population or traffic exposure rate.</p><p>QA01–QA06 passed for the published batch; QA07 has location limits. Batch publication and hash checks do not constitute final platform sign-off or a live Lab database connection. Source cards below expose batch/version and evidence.</p></section>}
      <div className="dataset-grid" aria-busy={loading}>
        {datasets.map((d) => {
          const item = catalog.sources.find(source => source.source === d.source);
          const local = Boolean(d.releaseId);
          const published = local && item?.origin === "publication";
          return (
          <article className="panel dataset-card" key={d.source}>
            <div className="dataset-icon">
              <Database size={25} />
              <span className="pill">
                {(d.demo ?? IS_DEMO) ? "Demo data" : published ? "Local publication" : local ? "Snapshot reference" : "Project snapshot"}
              </span>
            </div>
            <span className="eyebrow">{d.source}</span>
            <h2>{d.title}</h2>
            <p>
              {d.description ||
                "Source-specific road crash data with recorded coverage and restrictions."}
            </p>
            <dl>
              <div>
                <dt>Coverage</dt>
                <dd>{d.coverage}</dd>
              </div>
              <div>
                <dt>Version</dt>
                <dd>{d.version}</dd>
              </div>
              <div>
                <dt>Available views</dt>
                <dd>
                  {(d.demo ?? IS_DEMO)
                    ? "Trend · severity · demo map"
                    : published
                      ? ["Annual observations", ...(item?.capabilities.monthly ? ["monthly trends"] : []), ...(item?.capabilities.severity ? ["source classifications"] : []), item?.capabilities.geography ? "rounded coordinate grid" : "geography unavailable"].join(" · ")
                      : "Monthly trends · source classifications · boundary reference"}
                </dd>
              </div>
              <div>
                <dt>{local ? "Source batch" : "Batch"}</dt>
                <dd className="snapshot-batch">{d.sourceBatchId || d.batchId}</dd>
              </div>
              {local && <div><dt>Release</dt><dd className="snapshot-batch">{d.releaseId}</dd></div>}
            </dl>
            <ul>
              {d.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
            <div className="dataset-actions">
              <Link
                className="button-link"
                href={analysisHref("/").replace(/source=[^&]*/, `source=${d.source}`).replace(/&regionId=[^&]*/, "")}
                onClick={() =>
                  setFilters(
                    selectSource(
                      {
                        ...filters,
                        datasetVersion: d.version,
                        batchId: d.batchId,
                      },
                      d.source,
                    ),
                  )
                }
              >
                Explore dataset
                <ArrowUpRight size={16} />
              </Link>
              <button
                className="icon-quiet"
                aria-label={`View ${d.source} definitions`}
                onClick={() =>
                  showEvidence({
                    title: `${d.source} definitions & source policy`,
                    description:
                      d.description ||
                      "Source-specific metric definitions and availability. Categories are not assumed equivalent across states.",
                    demo: d.demo ?? IS_DEMO,
                    evidence: d.evidence,
                    rows: [
                      { label: "Coverage", value: d.coverage },
                      { label: "Version", value: d.version },
                      { label: local ? "Source batch" : "Batch", value: d.sourceBatchId || d.batchId },
                      ...(d.releaseId ? [{ label: "Release", value: d.releaseId }] : []),
                      ...(d.metricDefinitions || []),
                      ...d.limitations.map((limitation, index) => ({
                        label: `Source restriction ${index + 1}`,
                        value: limitation,
                      })),
                    ],
                  })
                }
              >
                <FileText size={18} />
              </button>
            </div>
          </article>
        );})}
      </div>
      <div className="panel data-note">
        <FileText />
        <div>
          <h3>Provenance travels with every result.</h3>
          <p>
            Source, dates, version, definitions and availability are part of
            every service response. {catalog.mode === "local" ? "Published sources are queried from the local database at the fixed release shown on each card; baseline references retain their original snapshot." : "This read-only project snapshot contains official source data; it is not a live database connection."} Source
            restrictions remain in effect when you filter, analyse or export.
          </p>
        </div>
      </div>
    </div>
  );
}
export function ImportsPage() {
  const [files, setFiles] = useState<ImportFile[]>([]),
    [job, setJob] = useState<ImportJob | null>(null),
    [error, setError] = useState(""),
    [creating, setCreating] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!job || job.status === "needs_input") return;
    let active = true;
    const timer = setInterval(() => {
      arsia
        .getImportJobStatus(job.id)
        .then((j) => {
          if (active) setJob(j);
        })
        .catch(() => {
          if (active)
            setError(
              "This preview job is no longer available. Start a new preview.",
            );
        });
    }, 500);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [job]);
  function add(list: FileList | null) {
    if (!list) return;
    const next = Array.from(list);
    if (next.some((f) => f.size > 100 * 1024 * 1024)) {
      setError(
        "Choose files under 100 MB each for this metadata-only preview.",
      );
      return;
    }
    setFiles((old) =>
      [
        ...old,
        ...next.map(({ name, size, type }) => ({ name, size, type })),
      ].filter(
        (f, i, a) =>
          a.findIndex((x) => x.name === f.name && x.size === f.size) === i,
      ),
    );
    setJob(null);
    setError("");
  }
  async function start() {
    setCreating(true);
    try {
      setJob(await arsia.createImportJob(files));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to create preview");
    } finally {
      setCreating(false);
    }
  }
  return (
    <div className="secondary-page imports-page">
      <span className="eyebrow">A NEW START FOR YOUR DATA</span>
      <h1>Bring the context. Keep the control.</h1>
      <p className="page-subtitle">
        Simulated import preview: inspect file metadata and see how a future
        import will flow. No file contents are uploaded or processed.
      </p>
      <div className="import-layout">
        <section className="panel upload-panel">
          <h2>New import</h2>
          <p>Choose crash data, a data dictionary, and any supporting notes.</p>
          <div
            className="dropzone"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              add(e.dataTransfer.files);
            }}
          >
            <div className="upload-symbol">
              <UploadCloud size={34} />
            </div>
            <h3>Drop your files here</h3>
            <p>CSV, XLSX, JSON, PDF or text · metadata preview only</p>
            <input
              ref={input}
              type="file"
              multiple
              accept=".csv,.xlsx,.json,.pdf,.txt,.md"
              aria-label="Import files"
              onChange={(e) => add(e.target.files)}
              className="sr-only"
            />
            <Button variant="outline" onClick={() => input.current?.click()}>
              <FolderOpen size={17} />
              Browse files
            </Button>
          </div>
          <div className="file-list">
            {files.map((f, i) => (
              <div key={`${f.name}-${f.size}`}>
                <FileText size={19} />
                <span>
                  <strong>{f.name}</strong>
                  <small>
                    {(f.size / 1024).toFixed(1)} KB ·{" "}
                    {f.type || "Unknown format"}
                  </small>
                </span>
                <button
                  aria-label={`Remove ${f.name}`}
                  onClick={() => {
                    setFiles(files.filter((_, index) => index !== i));
                    setJob(null);
                  }}
                >
                  <X size={16} />
                </button>
              </div>
            ))}
          </div>
          {error && (
            <p role="alert" className="error-text">
              {error}
            </p>
          )}
          <Button
            className="lime-button"
            disabled={!files.length || creating}
            onClick={() => void start()}
          >
            {creating ? (
              <Loader2 size={17} className="spin" />
            ) : (
              <Sparkles size={17} />
            )}
            Preview import steps
          </Button>
          <small className="privacy-note">
            File names, sizes and types only. No parsing, storage or database
            writes.
          </small>
        </section>
        <section className="panel import-progress">
          <span className="pill">Simulated workflow</span>
          <h2>From files to understanding.</h2>
          <p>A transparent process, with room for your judgement.</p>
          <ol>
            {(
              job?.steps || [
                { label: "File metadata", status: "pending" },
                { label: "Understand fields", status: "pending" },
                { label: "Review mappings", status: "pending" },
                { label: "Validate & publish", status: "pending" },
              ]
            ).map((step, i) => (
              <li key={step.label}>
                <span className={`step-icon ${step.status}`}>
                  {step.status === "complete" ? (
                    <CheckCircle2 size={21} />
                  ) : step.status === "active" ? (
                    <Loader2
                      size={21}
                      className={job?.status === "running" ? "spin" : ""}
                    />
                  ) : (
                    <Circle size={21} />
                  )}
                </span>
                <div>
                  <h3>{step.label}</h3>
                  <p>
                    {
                      [
                        "Inspect files and supporting documents",
                        "Suggest types, keys and relationships",
                        "Resolve uncertain definitions together",
                        "Check quality before a new release",
                      ][i]
                    }
                  </p>
                </div>
              </li>
            ))}
          </ol>
          {job ? (
            <div className="job-state" role="status">
              <strong>{job.status.replaceAll("_", " ")}</strong>
              <p>{job.message}</p>
            </div>
          ) : (
            <div className="empty-inline compact">
              Choose files to start a local preview.
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
export function ReportsPage() {
  return (
    <div className="secondary-page">
      <div className="page-heading">
        <div>
          <span className="eyebrow">YOUR ANALYSIS, WORTH KEEPING</span>
          <h1>Reports</h1>
          <p className="page-subtitle">
            A place for findings, context and the evidence behind them.
          </p>
        </div>
        <span className="pill">Preview</span>
      </div>
      <section className="panel reports-empty">
        <div className="empty-symbol">
          <FileBarChart2 size={40} />
        </div>
        <h2>Your first finding starts with a question.</h2>
        <p>
          Saved report authoring is not connected yet. You can explore the data
          and export the current selection, complete with its source,
          definitions and data version.
        </p>
        <Link href="/" className="button-link primary">
          Explore the overview
          <ArrowRight size={17} />
        </Link>
        <span className="muted">No reports saved in this local preview</span>
      </section>
    </div>
  );
}
