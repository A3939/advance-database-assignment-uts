"use client";

import { useState, type CSSProperties } from "react";
import dynamic from "next/dynamic";
import { ArrowUpRight, CircleHelp, Heart, PieChart, Siren, Users } from "lucide-react";
import type { AnalyticsData } from "@/services/analytics";
import { fatalPercentage } from "@/services/analytics-insights";
import styles from "./analytics.module.css";

const Chart = dynamic(() => import("./analytics-chart"), { ssr: false });
const n = (value: number | null | undefined) => value == null ? "—" : value.toLocaleString("en-AU");
const pct = (value: number | null) => value === null ? "—" : `${value.toFixed(2)}%`;
type Props = { data: AnalyticsData; evidence: (title: string, description: string, rows?: {label: string; value: string}[]) => void; resetDates: () => void };

export default function AnalyticsSeverity({ data, evidence, resetDates }: Props) {
  const [mode, setMode] = useState<"count" | "share">("count");
  const [category, setCategory] = useState<string | null>(null);
  const { overview } = data;
  const selected = data.severity.find(row => row.label === category) ?? data.severity[0];
  const share = overview.fatalShare == null ? null : overview.fatalShare * 100;
  const years = data.yearly.map(row => ({ ...row, share: fatalPercentage(row.crashes, row.fatalCrashes) }));
  const max = Math.max(...years.map(row => row.share ?? 0), 1);
  const definition = () => evidence("Severity definitions & values", data.severityReason || "Source categories classify crash events. They are not equivalent across sources.", data.severity.map(row => ({label: row.label, value: `${n(row.count)} crashes · ${row.definition}`})));
  return <>
    <div className={styles.metrics} aria-label="Severity summary">
      {[
        { label: "Fatal crashes", value: n(overview.fatalCrashes.value), note: "Crash events", Icon: Siren },
        { label: "Fatal crash share", value: pct(share), note: "Among crashes with known fatal status", Icon: PieChart },
        { label: "Lives lost", value: n(overview.livesLost.value), note: "People killed", Icon: Heart },
        { label: "Casualties", value: n(overview.casualties.value), note: "People · source definition applies", Icon: Users },
      ].map(({ label, value, note, Icon }) => <div key={label}><Icon size={20} className={styles.coralIcon}/><span>{label}</span><strong>{value}</strong><small>{note}</small></div>)}
    </div>
    <section className={styles.severityGrid} aria-label="Severity composition">
      <article className={styles.card}>
        <div className={styles.cardHeading}><div><h2>Native severity distribution</h2><p>{data.source} · original source classifications</p></div><div className={styles.segment} aria-label="Severity measure">{(["count", "share"] as const).map(value => <button key={value} aria-pressed={mode === value} onClick={() => setMode(value)} disabled={data.severityAvailability !== "available"}>{value === "count" ? "Count" : "Share"}</button>)}</div></div>
        <div className={styles.severityChart} data-mode={mode}>
          {data.severityAvailability === "available" ? <Chart kind="severity" rows={[]} severity={data.severity} mode={mode}/> : <div className={styles.chartLoading} role="status"><p>{data.severityReason || "No category breakdown is available for this selection."}</p><button className={styles.textButton} onClick={resetDates}>Use full-period selection</button></div>}
        </div>
        <div className={styles.cardFoot}><span>Counts and shares of recorded crashes</span><button onClick={definition}>Definitions <ArrowUpRight size={14}/></button></div>
      </article>
      <article className={styles.card}>
        <div className={styles.cardHeading}><div><h2>Fatal crash proportion</h2><p>Fatal status · source-defined denominator</p></div><button className={styles.info} aria-label="Fatal proportion definition" onClick={() => evidence("Fatal crash proportion", "The service supplies this share using crashes with known fatal status. Unknown status is not relabelled non-fatal. This is an outcome proportion, not a population or travel risk rate.")}><CircleHelp size={17}/></button></div>
        <div className={styles.donutPanel}>
          <div className={styles.donut} role="img" aria-label={`${pct(share)} fatal crash share; known status denominator`} style={{ "--share": `${share ?? 0}%`, ...(share === null ? {background:"var(--surface-elevated)"} : {}) } as CSSProperties}><div><strong>{pct(share)}</strong><span>Fatal share</span></div></div>
          <div className={styles.donutLegend}><p><i style={{background:"var(--coral)"}}/>Fatal<strong>{pct(share)}</strong></p><p><i style={{background:"var(--severity-non-injury)"}}/>Other known outcomes<strong>{pct(share === null ? null : 100 - share)}</strong></p><small>Unknown status stays outside this proportion.</small></div>
        </div>
      </article>
    </section>
    <section className={styles.balancedGrid} aria-label="Outcome interpretation">
      <article className={styles.card}>
        <div className={styles.cardHeading}><div><h2>Fatal outcomes by year</h2><p>Fatal crashes as a percentage of all recorded crashes</p></div></div>
        <div className={styles.outcomeRows}>{years.map(row => <div key={row.year}><span>{row.year}{!row.fullYear && <small>Selected months</small>}</span><div className={styles.outcomeTrack}><i style={{width:`${(row.share ?? 0) / max * 100}%`}}/></div><strong>{pct(row.share)}</strong><small>{n(row.fatalCrashes)} / {n(row.crashes)}</small></div>)}</div>
        <div className={styles.cardFoot}><span>All-crash denominator; may differ from the known-status proportion above.</span></div>
      </article>
      <article className={styles.card}>
        <div className={styles.cardHeading}><div><h2>Accidents and human consequences</h2><p>Different units, kept separate</p></div></div>
        <div className={styles.consequences}><div><span>Crash events</span><strong>{n(overview.crashes.value)}</strong><small>Recorded crashes</small></div><div><span>People</span><strong>{n(overview.casualties.value)}</strong><small>Casualties · includes source-defined injuries</small></div></div>
        <div className={styles.definitionBox}><label htmlFor="severity-category">Explore a source category</label><select id="severity-category" value={selected?.label ?? ""} onChange={e => setCategory(e.target.value)} disabled={!data.severity.length}>{data.severity.map(row => <option key={row.label}>{row.label}</option>)}</select><p>{selected?.definition || data.severityReason}</p><button className={styles.textButton} onClick={() => evidence("Measure definitions", "Crash counts and person counts measure different things and must not be added together.", Object.values(overview).filter(value => value && typeof value === "object" && "definition" in value).map(value => ({label:value.label, value:value.definition})))}>View source definitions <ArrowUpRight size={13}/></button></div>
      </article>
    </section>
    <article className={styles.card}><div className={styles.cardHeading}><div><h2>Severity detail</h2><p>Source-specific categories are retained</p></div><button className={styles.info} aria-label="Severity table definitions" onClick={definition}><CircleHelp size={17}/></button></div><div className={styles.tableScroll}><table className={styles.dataTable}><caption className="sr-only">Source severity categories, counts, shares and definitions</caption><thead><tr><th scope="col">Source category</th><th scope="col">Crashes</th><th scope="col">Share of all crashes</th><th scope="col">Source definition</th></tr></thead><tbody>{data.severity.map(row => <tr key={row.label}><th scope="row">{row.label}</th><td>{n(row.count)}</td><td>{pct(row.share == null ? null : row.share * 100)}</td><td className={styles.definitionCell}>{row.definition}</td></tr>)}</tbody></table>{!data.severity.length && <p className={styles.emptyDetail}>{data.severityReason || "No severity breakdown is available."}</p>}</div></article>
  </>;
}
