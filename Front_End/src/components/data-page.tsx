"use client";

import { useState } from "react";
import { ArrowRight, Check, Database, FileSpreadsheet, FileText, FolderOpen, Layers3, Link2, UploadCloud } from "lucide-react";
import { Button } from "@/components/ui/button";
import styles from "./data-page.module.css";

// Presentation content only. This screen has no upload, import or publication client.
const DATASETS = [
  { code: "NSW", name: "New South Wales", detail: "Recorded road crashes" },
  { code: "VIC", name: "Victoria", detail: "Police-reported injury crashes" },
  { code: "QLD", name: "Queensland", detail: "Reported road crashes" },
];

export default function DataPage() {
  const [mode, setMode] = useState<"files" | "link">("files");
  return (
    <div className={styles.page}>
      <header className={styles.heading}>
        <div><h1>Data</h1></div>
        <span className={styles.previewBadge}>Interface preview</span>
      </header>

      <section className={styles.library} aria-labelledby="library-title">
        <div className={styles.sectionHeading}>
          <div><Database size={18} /><h2 id="library-title">Dataset library</h2><span className={styles.count}>3</span></div>
        </div>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead><tr><th scope="col">Dataset</th><th scope="col">Coverage</th><th scope="col">Version</th><th scope="col">Status</th></tr></thead>
            <tbody>{DATASETS.map(dataset => <tr key={dataset.code}>
              <td><div className={styles.dataset}><span className={styles.sourceCode}>{dataset.code}</span><span><strong>{dataset.name}</strong><small>{dataset.detail}</small></span></div></td>
              <td>2020–2024</td><td><span className={styles.version}>official-v1</span></td>
              <td><span className={styles.status}><Check size={13} />Available</span></td>
            </tr>)}</tbody>
          </table>
        </div>
      </section>

      <section className={styles.newDataset} aria-labelledby="new-dataset-title">
        <div className={styles.uploadColumn}>
          <div className={styles.uploadHeading}><span className={styles.sectionIcon}><UploadCloud size={20} /></span><div><h2 id="new-dataset-title">Add a dataset</h2></div></div>
          <div className={styles.modes} role="group" aria-label="Upload mode">
            <button type="button" aria-pressed={mode === "files"} onClick={() => setMode("files")}><FileSpreadsheet size={16} />Upload files</button>
            <button type="button" aria-pressed={mode === "link"} onClick={() => setMode("link")}><Link2 size={16} />Source link</button>
          </div>
          {mode === "files" ? <div className={styles.dropzone}>
            <span className={styles.uploadGraphic}><UploadCloud size={30} strokeWidth={1.4} /></span>
            <h3>Your next dataset starts here</h3>
            <Button variant="outline" disabled aria-describedby="upload-preview-note"><FolderOpen size={16} />Browse files</Button>
            <span className={styles.formats}>CSV · XLSX · JSON · PDF · TXT</span>
          </div> : <div className={styles.linkPanel}>
            <span className={styles.uploadGraphic}><Link2 size={28} strokeWidth={1.4} /></span>
            <h3>Start from an official source</h3>
            <label htmlFor="source-url">Source URL</label><input id="source-url" type="url" placeholder="https://data.gov.au/…" disabled aria-describedby="upload-preview-note" />
          </div>}
          <div className={styles.uploadFooter}><p id="upload-preview-note">Preview only · uploading and publishing are unavailable.</p><Button disabled>Continue<ArrowRight size={15} /></Button></div>
        </div>
        <aside className={styles.guide} aria-label="Dataset preparation guide">
          <h3>Good data starts <br />with good context.</h3>
          <ol>
            <li><span><FileSpreadsheet size={17} /></span><div><strong>Crash data</strong></div></li>
            <li><span><FileText size={17} /></span><div><strong>Data dictionary</strong></div></li>
            <li><span><Layers3 size={17} /></span><div><strong>Source context</strong></div></li>
          </ol>
        </aside>
      </section>
    </div>
  );
}
