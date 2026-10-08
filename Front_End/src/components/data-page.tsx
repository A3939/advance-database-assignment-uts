"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowUpRight, Check, Database, FileSpreadsheet, FileText, Layers3, Loader2, UploadCloud } from "lucide-react";
import { Button } from "@/components/ui/button";
import { LocalImportsPage } from "@/components/imports";
import { useWorkspace } from "@/components/workspace";
import { arsia } from "@/services";
import { analysisHref } from "@/services/analysis-state";
import { dataTab, type DataTab } from "@/services/data-navigation";
import type { Dataset } from "@/services/contracts";
import styles from "./data-page.module.css";

export default function DataPage({ initialTab = "library" }: { initialTab?: DataTab }) {
  const [tab, setTab] = useState<DataTab>(initialTab);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const { catalog, catalogReady, catalogError, filters, view, showEvidence } = useWorkspace();
  useEffect(() => {
    const restore = () => setTab(dataTab(new URLSearchParams(window.location.search).get("tab")));
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);
  useEffect(() => {
    if (!catalogReady || catalogError) return;
    const controller = new AbortController();
    void arsia.getDatasetMetadata(controller.signal, filters).then(rows => {
      if (controller.signal.aborted) return;
      setDatasets(rows); setLoading(false); setError("");
    }).catch(() => {
      if (controller.signal.aborted) return;
      setLoading(false); setError("Source metadata could not be loaded. Your import workspace remains available.");
    });
    return () => controller.abort();
  }, [catalogReady, catalogError, filters, retry]);
  function selectTab(next: DataTab) {
    setTab(next);
    const url = new URL(window.location.href);
    if (next === "library") url.searchParams.delete("tab"); else url.searchParams.set("tab", next);
    window.history.pushState(null, "", url);
  }
  function definitions(dataset: Dataset) {
    showEvidence({
      title: `${dataset.source} definitions & source policy`,
      description: dataset.description || "Source-specific definitions, coverage and restrictions.",
      evidence: dataset.evidence,
      rows: [
        { label: "Coverage", value: dataset.coverage },
        { label: "Version", value: dataset.version },
        { label: "Source batch", value: dataset.sourceBatchId || dataset.batchId },
        ...(dataset.releaseId ? [{ label: "Release", value: dataset.releaseId }] : []),
        ...(dataset.metricDefinitions || []),
        ...dataset.limitations.map((value, index) => ({ label: `Source restriction ${index + 1}`, value })),
      ],
    });
  }
  return <div className={styles.page}>
    <header className={styles.heading}>
      <div><h1>Data</h1><p>Your dataset library, source files and import progress.</p></div>
      {tab === "library" && <Button onClick={() => selectTab("imports")}><UploadCloud size={16} />Add a dataset</Button>}
    </header>
    <div className={styles.tabs} role="group" aria-label="Data workspace views">
      <button type="button" aria-pressed={tab === "library"} onClick={() => selectTab("library")}><Database size={15} />Dataset library</button>
      <button type="button" aria-pressed={tab === "imports"} onClick={() => selectTab("imports")}><UploadCloud size={15} />Add data & import jobs</button>
    </div>
    {tab === "imports" ? <LocalImportsPage embedded /> : <>
      <section className={styles.library} aria-labelledby="library-title" aria-busy={!catalogReady || (!catalogError && loading)}>
        <div className={styles.sectionHeading}><div><Database size={18} /><h2 id="library-title">Dataset library</h2>{!loading && !error && !catalogError && <span className={styles.count}>{datasets.length}</span>}</div><span>{catalogError ? "Release unavailable" : catalog.mode === "local" ? "Pinned local release" : "Project snapshot"}</span></div>
        {catalogError ? <div className={styles.libraryMessage} role="status">The selected release could not be loaded. No substitute dataset is shown. You can still add source files or view import jobs.</div> : error ? <div className={styles.libraryMessage} role="alert"><p>{error}</p><Button size="sm" variant="outline" onClick={() => { setLoading(true); setError(""); setRetry(value => value + 1); }}>Try again</Button></div> : loading || !catalogReady ? <div className={styles.libraryMessage} role="status"><Loader2 size={17} className="spin" />Loading source metadata…</div> : <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead><tr><th scope="col">Dataset</th><th scope="col">Coverage</th><th scope="col">Version</th><th scope="col">Status</th><th scope="col"><span className="sr-only">Dataset actions</span></th></tr></thead>
            <tbody>{datasets.map(dataset => {
              const item = catalog.sources.find(source => source.source === dataset.source);
              const published = item?.origin === "publication";
              const href = analysisHref("/", { ...filters, source: dataset.source, regionId: undefined, datasetVersion: dataset.version, batchId: dataset.batchId, ...(dataset.releaseId ? { releaseId: dataset.releaseId } : {}) }, view);
              return <tr key={dataset.source}>
                <td><div className={styles.dataset}><span className={styles.sourceCode}>{item?.jurisdiction || dataset.source}</span><span><strong>{dataset.title}</strong><small>{dataset.description || "Source-specific road crash data"}</small></span></div></td>
                <td>{dataset.coverage}</td><td><span className={styles.version}>{dataset.version}</span></td>
                <td><span className={styles.status}><Check size={13} />{published ? "Local publication" : "Snapshot"}</span></td>
                <td><div className={styles.rowActions}><button type="button" onClick={() => definitions(dataset)} aria-label={`View ${dataset.source} definitions`} title="Definitions & evidence"><FileText size={16} /></button><Link href={href} aria-label={`Explore ${dataset.source}`} title="Explore dataset"><ArrowUpRight size={17} /></Link></div></td>
              </tr>;
            })}</tbody>
          </table>
          {!datasets.length && <p className={styles.libraryMessage}>No datasets are available in this release.</p>}
        </div>}
        <p className={styles.libraryNote}>Sources retain their own definitions, coverage and quality limits. Open source evidence for details; counts are not pooled into a national total.</p>
      </section>
      <section className={styles.newDataset} aria-labelledby="new-dataset-title">
        <div className={styles.uploadColumn}>
          <div className={styles.uploadHeading}><span className={styles.sectionIcon}><UploadCloud size={20} /></span><div><h2 id="new-dataset-title">Add a dataset</h2><p>Bring source files and supporting evidence into the same workspace.</p></div></div>
          <div className={styles.dropzone}><span className={styles.uploadGraphic}><UploadCloud size={30} strokeWidth={1.4} /></span><h3>Your next dataset starts here</h3><p>Review files, follow the Agent’s progress and inspect independent quality checks.</p><Button variant="outline" onClick={() => selectTab("imports")}><UploadCloud size={16} />Open upload workspace</Button><span className={styles.formats}>CSV · XLSX · XLS · ZIP · JSON · GeoJSON</span></div>
          <div className={styles.uploadFooter}><p>Supporting dictionaries and source documentation stay with the import. Publication follows the existing validation and authority checks.</p></div>
        </div>
        <aside className={styles.guide} aria-label="Dataset preparation guide"><h3>Good data starts <br />with good context.</h3><ol><li><span><FileSpreadsheet size={17} /></span><div><strong>Source data</strong><p>Include related tables together.</p></div></li><li><span><FileText size={17} /></span><div><strong>Data dictionary</strong><p>Keep native definitions and unknown values.</p></div></li><li><span><Layers3 size={17} /></span><div><strong>Source context</strong><p>Add provenance, coverage and use restrictions.</p></div></li></ol></aside>
      </section>
    </>}
  </div>;
}
