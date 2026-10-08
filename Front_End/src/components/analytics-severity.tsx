"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { CircleHelp, Heart, PieChart, Siren, Users } from "lucide-react";
import type { AnalyticsData } from "@/services/analytics";
import { fatalPercentage } from "@/services/analytics-insights";
import AnalyticsMetricCard from "./analytics-metric-card";
import AnalyticsSeverityChange from "./analytics-severity-change";
import { timePointLabel } from "@/services/periods";
import styles from "./analytics.module.css";

const Chart = dynamic(() => import("./analytics-chart"), { ssr: false });
const n = (value: number | null | undefined) => value == null ? "—" : value.toLocaleString("en-AU");
const pct = (value: number | null) => value === null ? "—" : `${value.toFixed(2)}%`;
type Props = { data: AnalyticsData; evidence: (title: string, description: string, rows?: {label: string; value: string}[]) => void; resetDates: () => void };

export default function AnalyticsSeverity({ data, evidence, resetDates }: Props) {
  const [mode, setMode] = useState<"count" | "share">("count");
  const { overview } = data;
  const share = overview.fatalShare == null ? null : overview.fatalShare * 100;
  const years = data.yearly.map(row => ({ ...row, share: fatalPercentage(row.crashes, row.fatalCrashes) }));
  const max = Math.max(...years.map(row => row.share ?? 0), 1);
  const definition = () => evidence("Severity definitions & values", data.severityReason || "Source categories classify crash events. They are not equivalent across sources.", data.severity.map(row => ({label: row.label, value: `${n(row.count)} crashes · ${row.definition}`})));
  const annualValues = () => evidence("Fatal crashes & lives lost", "Fatal crashes count events; lives lost counts people. The columns are shown separately, not stacked or added. Partial years include only selected months; unavailable counts remain unknown.", [
    {label:"Fatal crashes",value:overview.fatalCrashes.definition},
    {label:"Lives lost",value:overview.livesLost.definition},
    ...data.timeSeriesYearly.map(row => ({label:timePointLabel(row),value:`${n(row.fatalCrashes)} fatal crashes · ${n(row.livesLost)} lives lost`})),
  ]);
  return <>
    <section className={`metric-grid ${styles.allMetrics} ${styles.singleMetrics}`} aria-label="Severity summary">
      {[
        { label: "Fatal crashes", value: n(overview.fatalCrashes.value), note: "Crash events", Icon: Siren },
        { label: "Fatal crash share", value: pct(share), note: "Among crashes with known fatal status", Icon: PieChart },
        { label: "Lives lost", value: n(overview.livesLost.value), note: "People killed", Icon: Heart },
        { label: "Casualties", value: n(overview.casualties.value), note: "People · source definition applies", Icon: Users },
      ].map(({ label, value, note, Icon }) => <AnalyticsMetricCard key={label} label={label} value={value} Icon={Icon} onDefinition={() => evidence(label, note, [{label:data.source,value}])}/>)}
    </section>
    <section className={styles.severityGrid} aria-label="Severity composition">
      <article className={styles.card}>
        <div className={styles.cardHeading}><div><h2>Native severity distribution</h2></div><div className={styles.segment} aria-label="Severity measure">{(["count", "share"] as const).map(value => <button key={value} aria-pressed={mode === value} onClick={() => setMode(value)} disabled={data.severityAvailability !== "available"}>{value === "count" ? "Count" : "Share"}</button>)}</div></div>
        <div className={`${styles.severityChart} ${styles.singleSeverityChart}`} data-mode={mode}>
          {data.severityAvailability === "available" ? <Chart kind="severity" rows={[]} severity={data.severity} mode={mode}/> : <div className={styles.chartLoading} role="status"><p>{data.severityReason || "No category breakdown is available for this selection."}</p><button className={styles.textButton} onClick={resetDates}>Use full-period selection</button></div>}
        </div>
      </article>
      <article className={styles.card}>
        <div className={styles.cardHeading}><div><h2>Fatal crashes & lives lost</h2></div><button className={styles.info} aria-label="Fatal outcomes definitions and annual values" onClick={annualValues}><CircleHelp size={17}/></button></div>
        <div className={styles.fatalOutcomesChart}><Chart kind="fatal-outcomes" rows={data.timeSeriesYearly} granularity="yearly"/></div>
        {data.timeSeriesYearly.some(row => !row.fullYear) && <div className={styles.cardFoot}><span>Selected months only · not a full-year total</span></div>}
      </article>
    </section>
    <section className={styles.balancedGrid} aria-label="Outcome interpretation">
      <article className={styles.card}>
        <div className={styles.cardHeading}><div><h2>Fatal outcomes by year</h2><p>Fatal crashes / all crashes</p></div></div>
        <div className={styles.outcomeRows}>{years.map(row => <div key={row.year}><span>{row.year}{!row.fullYear && <small>Selected months</small>}</span><div className={styles.outcomeTrack}><i style={{width:`${(row.share ?? 0) / max * 100}%`}}/></div><strong>{pct(row.share)}</strong><small>{n(row.fatalCrashes)} / {n(row.crashes)}</small></div>)}</div>
      </article>
      <AnalyticsSeverityChange filters={data.filters} evidence={evidence}/>
    </section>
    <article className={styles.card}><div className={styles.cardHeading}><div><h2>Severity detail</h2></div><button className={styles.info} aria-label="Severity table definitions" onClick={definition}><CircleHelp size={17}/></button></div><div className={styles.tableScroll}><table className={styles.dataTable}><caption className="sr-only">Source severity categories, counts, shares and definitions</caption><thead><tr><th scope="col">Source category</th><th scope="col">Crashes</th><th scope="col">Share of all crashes</th><th scope="col">Source definition</th></tr></thead><tbody>{data.severity.map(row => <tr key={row.label}><th scope="row">{row.label}</th><td>{n(row.count)}</td><td>{pct(row.share == null ? null : row.share * 100)}</td><td className={styles.definitionCell}>{row.definition}</td></tr>)}</tbody></table>{!data.severity.length && <p className={styles.emptyDetail}>{data.severityReason || "No severity breakdown is available."}</p>}</div></article>
  </>;
}
