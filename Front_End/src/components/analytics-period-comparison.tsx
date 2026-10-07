"use client";

import { useState } from "react";
import { Info } from "lucide-react";
import type { AnalyticsMonth, MetricKey } from "@/services/analytics";
import type { Source } from "@/services/contracts";
import { comparisonAverage, comparisonChange, comparisonPeriods } from "@/services/period-comparison";
import styles from "./analytics.module.css";

const labels: Record<MetricKey, string> = {
  crashes: "Crashes", fatalCrashes: "Fatal crashes", livesLost: "Lives lost", casualties: "Casualties",
};
const metrics = Object.keys(labels) as MetricKey[];
const mean = (value: number | null) => value === null ? "—" : value.toLocaleString("en-AU", { maximumFractionDigits: 1 });
const changeLabel = (value: number | null) => value === null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(1)}%`;

export default function AnalyticsPeriodComparison({ sources, metric, evidence }: {
  sources: { source: Source; monthly: AnalyticsMonth[] }[];
  metric: MetricKey;
  evidence: (title: string, description: string, rows?: { label: string; value: string }[]) => void;
}) {
  const [firstKey, setFirstKey] = useState("");
  const [secondKey, setSecondKey] = useState("");
  const [chosenMetric, setChosenMetric] = useState<MetricKey | null>(null);
  const selectedMetric = chosenMetric ?? metric;
  const periods = comparisonPeriods(sources.flatMap(source => source.monthly));
  const possibleFirst = periods.filter(first => periods.some(second => second.start > first.end));
  const first = possibleFirst.find(period => period.label === firstKey) ?? possibleFirst[0];
  const possibleSecond = periods.filter(period => first && period.start > first.end);
  const second = possibleSecond.find(period => period.label === secondKey) ?? possibleSecond.at(-1);

  const rows = first && second ? sources.map(({ source, monthly }) => {
    const a = comparisonAverage(monthly, selectedMetric, first);
    const b = comparisonAverage(monthly, selectedMetric, second);
    return { source, a, b, change: comparisonChange(a, b) };
  }) : [];
  const largest = Math.max(5, ...rows.map(row => Math.abs(row.change ?? 0)));
  const axis = Math.ceil(largest / 5) * 5;

  return <article className={`${styles.card} ${styles.periodComparison}`} aria-label="Compare two periods by source">
    <div className={`${styles.cardHeading} ${styles.periodComparisonHeading}`}>
      <div>
        <div className={styles.periodComparisonTitle}><h2>Compare two periods (All states)</h2><button className={styles.info} aria-label="Period comparison definitions" onClick={() => evidence("Compare two periods (All states)", "Each state is compared with itself using its own recorded monthly counts within the selected date range. A and B are averages of known months. A relative change is shown only when every selected month in both periods has a known value and A is greater than zero. Different source definitions prevent an interstate total or direct risk comparison.", rows.map(row => ({ label: row.source, value: `${first?.label}: ${mean(row.a.average)} (${row.a.observed}/${row.a.selected} months); ${second?.label}: ${mean(row.b.average)} (${row.b.observed}/${row.b.selected} months); change: ${changeLabel(row.change)}` })))}><Info size={16}/></button></div>
        <p>Monthly averages within each state · Source definitions differ</p>
      </div>
      <div className={styles.periodComparisonControls}>
        <label>Period A<select aria-label="Period A" value={first?.label ?? ""} onChange={event => { setFirstKey(event.target.value); setSecondKey(""); }} disabled={!first}>{possibleFirst.map(period => <option key={period.label} value={period.label}>{period.label}</option>)}</select></label>
        <label>Period B<select aria-label="Period B" value={second?.label ?? ""} onChange={event => setSecondKey(event.target.value)} disabled={!second}>{possibleSecond.map(period => <option key={period.label} value={period.label}>{period.label}</option>)}</select></label>
        <label>Metric<select aria-label="Comparison metric" value={selectedMetric} onChange={event => setChosenMetric(event.target.value as MetricKey)}>{metrics.map(key => <option key={key} value={key}>{labels[key]}</option>)}</select></label>
      </div>
    </div>
    {first && second ? <div className={styles.periodComparisonScroll}><div className={styles.periodComparisonTable}>
      <div className={`${styles.periodComparisonRow} ${styles.periodComparisonHeader}`}><span>State</span><span>Period averages ({labels[selectedMetric].toLowerCase()} per month)</span><span>Change in monthly average (Period B vs A)</span><span>Relative change</span></div>
      {rows.map(row => <div className={styles.periodComparisonRow} key={row.source}>
        <strong className={styles.periodComparisonSource}>{row.source}</strong>
        <span className={styles.periodComparisonAverages}>A {mean(row.a.average)} <span aria-hidden="true">→</span> B {mean(row.b.average)}</span>
        <div className={styles.periodComparisonPlot} role="img" aria-label={`${row.source}: ${changeLabel(row.change)} change from ${first.label} to ${second.label}`}>
          <span className={styles.periodComparisonZero}/>
          {row.change !== null && <span className={styles.periodComparisonBar} data-source={row.source} style={{width:`${Math.abs(row.change) / axis * 50}%`,[row.change >= 0 ? "left" : "right"]:"50%"}}/>}
        </div>
        <strong className={styles.periodComparisonValue} data-source={row.source}>{changeLabel(row.change)}</strong>
      </div>)}
      <div className={styles.periodComparisonAxis}><span>−{axis}%</span><span>0%</span><span>+{axis}%</span></div>
    </div></div> : <p className={styles.emptyDetail}>Select at least two non-overlapping years to compare periods.</p>}
    <p className={styles.periodComparisonNote}>Selected date range only · Missing months are never counted as zero · Change requires complete values in both periods.</p>
  </article>;
}
