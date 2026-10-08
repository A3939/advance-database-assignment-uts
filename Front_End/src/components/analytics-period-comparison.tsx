"use client";

import { useId, useState } from "react";
import { Check, ChevronDown, Info } from "lucide-react";
import { Select } from "radix-ui";
import type { AnalyticsMonth, MetricKey } from "@/services/analytics";
import type { Source } from "@/services/contracts";
import { comparisonAverage, comparisonChange, comparisonPeriods } from "@/services/period-comparison";
import layout from "./analytics.module.css";
import styles from "./analytics-period-comparison.module.css";

const labels: Record<MetricKey, string> = {
  crashes: "Crashes", fatalCrashes: "Fatal crashes", livesLost: "Lives lost", casualties: "Casualties",
};
const metrics = Object.keys(labels) as MetricKey[];
const mean = (value: number | null) => value === null ? "—" : value.toLocaleString("en-AU", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const changeLabel = (value: number | null) => value === null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(1)}%`;

function ComparisonSelect({ label, value, options, onChange, disabled = false }: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const id = useId();
  return <div className={styles.periodComparisonField}>
    <label htmlFor={id}>{label}</label>
    <Select.Root value={value} onValueChange={onChange} disabled={disabled}>
      <Select.Trigger id={id} className={styles.periodComparisonSelect}>
        <Select.Value placeholder="Unavailable"/>
        <Select.Icon className={styles.periodComparisonChevron}><ChevronDown size={15}/></Select.Icon>
      </Select.Trigger>
      <Select.Portal>
        <Select.Content className={styles.periodComparisonMenu} position="popper" align="end" sideOffset={6} collisionPadding={12}>
          <Select.Viewport>
            {options.map(option => <Select.Item className={styles.periodComparisonOption} key={option.value} value={option.value}>
              <Select.ItemText>{option.label}</Select.ItemText>
              <Select.ItemIndicator><Check size={15}/></Select.ItemIndicator>
            </Select.Item>)}
          </Select.Viewport>
        </Select.Content>
      </Select.Portal>
    </Select.Root>
  </div>;
}

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

  return <article className={`${layout.card} ${styles.periodComparison}`} aria-label="Compare two periods by source">
    <div className={`${layout.cardHeading} ${styles.periodComparisonHeading}`}>
      <div>
        <div className={styles.periodComparisonTitle}><h2>Compare two periods (All states)</h2><button className={layout.info} aria-label="Period comparison definitions" onClick={() => evidence("Compare two periods (All states)", "Each state is compared with itself using its own recorded monthly counts within the selected date range. A and B are averages of known months. A relative change is shown only when every selected month in both periods has a known value and A is greater than zero. Different source definitions prevent an interstate total or direct risk comparison.", rows.map(row => ({ label: row.source, value: `${first?.label}: ${mean(row.a.average)} (${row.a.observed}/${row.a.selected} months); ${second?.label}: ${mean(row.b.average)} (${row.b.observed}/${row.b.selected} months); change: ${changeLabel(row.change)}` })))}><Info size={16}/></button></div>
      </div>
      <div className={styles.periodComparisonControls}>
        <ComparisonSelect label="Period A" value={first?.label ?? ""} onChange={value => { setFirstKey(value); setSecondKey(""); }} disabled={!first} options={possibleFirst.map(period => ({ value: period.label, label: period.label }))}/>
        <ComparisonSelect label="Period B" value={second?.label ?? ""} onChange={setSecondKey} disabled={!second} options={possibleSecond.map(period => ({ value: period.label, label: period.label }))}/>
        <ComparisonSelect label="Metric" value={selectedMetric} onChange={value => setChosenMetric(value as MetricKey)} options={metrics.map(key => ({ value: key, label: labels[key] }))}/>
      </div>
    </div>
    {first && second ? <div className={styles.periodComparisonScroll}><div className={styles.periodComparisonTable} role="table" aria-label="Monthly averages and relative change">
      <div className={`${styles.periodComparisonRow} ${styles.periodComparisonHeader}`} role="row">
        <span role="columnheader">State</span>
        <span role="columnheader">Period A<span className={styles.periodComparisonUnit}>{labels[selectedMetric]} / month</span></span>
        <span role="columnheader">Period B<span className={styles.periodComparisonUnit}>{labels[selectedMetric]} / month</span></span>
        <span className={styles.periodComparisonChangeHeading} role="columnheader" aria-label="Relative change, period B versus A">Relative change</span>
        <span role="columnheader" aria-label="Percentage change"/>
      </div>
      {rows.map(row => <div className={styles.periodComparisonRow} role="row" key={row.source}>
        <strong className={styles.periodComparisonSource} role="rowheader"><span className={styles.periodComparisonDot} data-source={row.source} aria-hidden="true"/>{row.source}</strong>
        <span className={styles.periodComparisonAverage} role="cell">{mean(row.a.average)}</span>
        <span className={styles.periodComparisonAverage} role="cell">{mean(row.b.average)}</span>
        <div role="cell">
          <div className={styles.periodComparisonPlot} role="img" aria-label={`${row.source}: ${changeLabel(row.change)} change from ${first.label} to ${second.label}`}>
            {[0, 25, 75, 100].map(position => <span key={position} className={styles.periodComparisonGridline} style={{left:`${position}%`}} aria-hidden="true"/>)}
            <span className={styles.periodComparisonZero}/>
            {row.change !== null && <span className={styles.periodComparisonBar} data-source={row.source} style={{width:`${Math.abs(row.change) / axis * 50}%`,[row.change >= 0 ? "left" : "right"]:"50%"}}/>}
          </div>
        </div>
        <strong className={styles.periodComparisonValue} role="cell" data-source={row.source}>{changeLabel(row.change)}</strong>
      </div>)}
    </div><div className={`${styles.periodComparisonRow} ${styles.periodComparisonAxisRow}`} aria-hidden="true"><div className={styles.periodComparisonAxis}>
      <span>−{axis}%</span><span>−{axis / 2}%</span><span>0%</span><span>+{axis / 2}%</span><span>+{axis}%</span>
    </div></div></div> : <p className={layout.emptyDetail}>Select at least two non-overlapping years to compare periods.</p>}
  </article>;
}
