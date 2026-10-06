"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { ArrowUpRight, ArrowDownWideNarrow, CalendarDays, CarFront, Heart, Info, Map, MapPin, PieChart, Siren, Target, TrendingUp, Users, type LucideIcon } from "lucide-react";
import { monthlyInsights, spatialInsights } from "@/services/analytics-insights";
import type { getAnalytics, MetricKey } from "@/services/analytics";
import type { MapData, SourceSelection } from "@/services/contracts";
import styles from "./analytics.module.css";
import AnalyticsSeverityChange from "./analytics-severity-change";

const Chart = dynamic(() => import("./analytics-chart"), { ssr: false });
const SpatialMap = dynamic(() => import("./spatial-map"), { ssr: false });
const labels = { crashes: "Crashes", fatalCrashes: "Fatal crashes", livesLost: "Lives lost", casualties: "Casualties" };
const number = (value: number | null | undefined, decimals = 0) => value == null ? "—" : value.toLocaleString("en-AU", { maximumFractionDigits: decimals });
const percentage = (value: number | null | undefined, signed = false) => value == null ? "—" : `${signed && value > 0 ? "+" : ""}${value.toFixed(1)}%`;
const metricIcons = { crashes: CarFront, fatalCrashes: Siren, livesLost: Heart, casualties: Users };
type Bundle = Awaited<ReturnType<typeof getAnalytics>>;
type SummaryCard = {
  label: string;
  Icon: LucideIcon;
  description: string;
  compact?: boolean;
  values: { source: SourceSelection; value: string; note?: string }[];
};

/** All retains separate source observations; it never invents a national total. */
export default function AnalyticsAllSources({ bundles, dashboard, metric, granularity, map, sourceMaps, evidence, onSourceSelect, setMetric, setGranularity }: {
  bundles: Bundle[];
  dashboard: "trends" | "severity" | "spatial";
  metric: MetricKey;
  granularity: "monthly" | "yearly";
  map: MapData | null;
  sourceMaps: { source: SourceSelection; data: MapData }[];
  evidence: (title: string, description: string, rows?: { label: string; value: string }[]) => void;
  onSourceSelect: (source: SourceSelection) => void;
  setMetric: (metric: MetricKey) => void;
  setGranularity: (interval: "monthly" | "yearly") => void;
}) {
  const [severityMode, setSeverityMode] = useState<"count" | "share">("count");
  const summaries = bundles.map(({ data }) => {
    const monthly = monthlyInsights(data.monthly.filter(row => row.availability === "available"), metric);
    const latest = data.yearly.at(-1);
    const sourceMap = sourceMaps.find(item => item.source === data.source)?.data;
    // Country totals include unmapped records. LGA summaries require actual source-scoped LGA data.
    const spatial = sourceMap?.regionMode === "lga" && !sourceMap.illustrationOnly ? spatialInsights(sourceMap.regions) : null;
    return { data, monthly, latest, spatial };
  });
  const cards: SummaryCard[] = dashboard === "trends" ? [
    { label: labels[metric], Icon: metricIcons[metric], description: "Selected-period totals remain separate for each source. Source definitions and availability apply.", values: summaries.map(({data}) => ({source:data.source, value:number(data.overview[metric].value), note:data.overview[metric].definition})) },
    { label: "Monthly average", Icon: CalendarDays, description: "Average over selected months with known counts. Unobserved or unknown months are not recorded zeros.", values: summaries.map(({data, monthly}) => ({source:data.source, value:number(monthly.average, 1), note:`${monthly.observed} months with known counts`})) },
    { label: "Latest year-on-year change", Icon: TrendingUp, description: "The latest selected year compared with the previous year using matching months. Unavailable comparisons remain empty.", values: summaries.map(({data, latest}) => ({source:data.source, value:percentage(latest?.comparisons[metric].yoyPct, true), note:latest ? `${latest.year} vs ${latest.previousYear} · matching months` : "Matching periods required"})) },
    { label: "Peak month", Icon: CalendarDays, compact:true, description: "The selected month with the highest known count for this metric in each source.", values: summaries.map(({data, monthly}) => ({source:data.source, value:monthly.peak ? new Date(`${monthly.peak.period}-01T00:00:00Z`).toLocaleDateString("en-AU", {month:"short",year:"numeric",timeZone:"UTC"}) : "—", note:`${number(monthly.peak?.[metric])} ${labels[metric].toLowerCase()}`})) },
  ] : dashboard === "severity" ? [
    { label:"Fatal crashes", Icon:Siren, description:"Fatal crash events. Each source retains its own recorded crash definition.", values:summaries.map(({data}) => ({source:data.source,value:number(data.overview.fatalCrashes.value),note:data.overview.fatalCrashes.definition})) },
    { label:"Fatal crash share", Icon:PieChart, description:"Fatal crashes as a share of crashes with known fatal status in each source. Unknown status is excluded from the denominator.", values:summaries.map(({data}) => ({source:data.source,value:percentage(data.overview.fatalShare == null ? null : data.overview.fatalShare * 100)})) },
    { label:"Lives lost", Icon:Heart, description:"People killed, counted separately from fatal crash events.", values:summaries.map(({data}) => ({source:data.source,value:number(data.overview.livesLost.value),note:data.overview.livesLost.definition})) },
    { label:"Casualties", Icon:Users, description:"People injured or killed according to each source's casualty definition. Definitions are not assumed equivalent.", values:summaries.map(({data}) => ({source:data.source,value:number(data.overview.casualties.value),note:data.overview.casualties.definition})) },
  ] : [
    { label:"Mapped crashes", Icon:MapPin, description:"Recorded crashes within each source's mapped LGA aggregates, for the selected period. Unmapped records are excluded.", values:summaries.map(({data,spatial}) => ({source:data.source,value:number(spatial?.total)})) },
    { label:"Areas with records", Icon:Map, description:"LGAs with at least one mapped crash in each source, using the same LGA scope as the single-source dashboard.", values:summaries.map(({data,spatial}) => ({source:data.source,value:number(spatial?.represented),note:spatial ? `Of ${number(spatial.ranked.length)} observed LGAs` : "Observed LGA data unavailable"})) },
    { label:"Top 5 concentration", Icon:Target, description:"The five highest-count LGAs' share of mapped crashes in each source. Counts are not exposure-adjusted risk rates.", values:summaries.map(({data,spatial}) => ({source:data.source,value:percentage(spatial?.topFiveShare)})) },
    { label:"Highest-count area", Icon:ArrowDownWideNarrow, compact:true, description:"The LGA with the most mapped crashes in each source, for the selected period.", values:summaries.map(({data,spatial}) => ({source:data.source,value:spatial?.ranked[0]?.name ?? "—",note:`${number(spatial?.ranked[0]?.count)} recorded crashes`})) },
  ];
  return <>
    <section className={`metric-grid ${styles.allMetrics}`} aria-label={`${dashboard === "trends" ? "Trend" : dashboard === "severity" ? "Severity" : "Spatial"} summary by source`}>
      {cards.map(({label, Icon, description, compact, values}) => <article className="panel metric-card" key={label}>
        <div className="metric-label"><Icon size={25} strokeWidth={1.5} aria-hidden="true"/><span>{label}</span><button className="info-button" aria-label={`${label} definition`} onClick={() => evidence(label, description, values.map(row => ({label:row.source,value:`${row.value}${row.note ? ` · ${row.note}` : ""}`})))}><Info size={16}/></button></div>
        <div className={`metric-by-source ${compact ? styles.compactValues : ""} ${compact && dashboard === "spatial" ? styles.areaValues : ""}`}>{values.map(row => <div key={row.source}><span>{row.source}</span><strong title={row.note}>{row.value}</strong></div>)}</div>
      </article>)}
    </section>
    <p className={styles.allSourceNote}><Info size={15}/>All available sources · definitions differ by source; counts are shown separately.</p>
    {dashboard === "trends" && <div className={styles.cardHeading}>
      <div className={styles.metricTabs} aria-label="Trend metric">{Object.entries(labels).map(([key, label]) => <button key={key} aria-pressed={metric === key} onClick={() => setMetric(key as MetricKey)}>{label}</button>)}</div>
      <div className={styles.segment} aria-label="Trend interval">{(["monthly", "yearly"] as const).map(value => <button key={value} aria-pressed={granularity === value} onClick={() => setGranularity(value)}>{value === "monthly" ? "Monthly" : "Yearly"}</button>)}</div>
    </div>}
    {dashboard === "severity" && <div className={styles.cardHeading}><h2>Native severity by source</h2><div className={styles.segment} aria-label="Severity measure">{(["count", "share"] as const).map(value => <button key={value} aria-pressed={severityMode === value} onClick={() => setSeverityMode(value)}>{value === "count" ? "Count" : "Share"}</button>)}</div></div>}
    {dashboard === "spatial" && map && <article className={styles.card}><div className={styles.cardHeading}><div><h2>Recorded crashes by source</h2><p>Select a state to explore its LGA distribution</p></div></div><div className={styles.spatialMap}><SpatialMap data={map} source="All" onSourceSelect={onSourceSelect} onSelect={() => {}}/></div><div className={styles.cardFoot}>State aggregates · available sources only · counts are not risk rates</div></article>}
    <section className={styles.sourceComparison} aria-label="All source comparisons">
      {bundles.map(({data, meta}) => <article className={styles.card} key={data.source}>
        <div className={styles.cardHeading}><div><h2>{data.source}</h2><p>{dashboard === "severity" ? "Original crash severity categories" : dashboard === "trends" ? labels[metric] : "Recorded crashes"}</p></div><button className={styles.textButton} onClick={() => onSourceSelect(data.source)}>Explore <ArrowUpRight size={13}/></button></div>
        {dashboard === "spatial" && <div className={styles.sourceValue}><span>Recorded crashes<strong>{number(data.overview.crashes.value)}</strong></span></div>}
        {dashboard === "trends" && <div className={styles.trendChart}><Chart kind="trend" rows={granularity === "monthly" ? data.monthly : data.timeSeriesYearly} granularity={granularity} metric={metric}/></div>}
        {dashboard === "severity" && <div className={styles.severityChart} data-mode={severityMode}>{data.severityAvailability === "available" ? <Chart kind="severity" rows={[]} severity={data.severity} mode={severityMode}/> : <div className={styles.chartLoading} role="status">{data.severityReason || "No severity categories are available for this selection."}</div>}</div>}
        <div className={styles.cardFoot}>{dashboard === "trends" ? "Individual chart scale · source-specific counts" : dashboard === "severity" ? "Categories retain their source definitions" : meta.definition}</div>
      </article>)}
    </section>
    {dashboard === "severity" && bundles[0] && <AnalyticsSeverityChange filters={{...bundles[0].data.filters, source:"All", regionId:undefined}} evidence={evidence}/>}
    <article className={styles.card}><div className={styles.cardHeading}><div><h2>Source detail</h2><p>Separate source counts for the selected period</p></div></div><div className={styles.tableScroll}><table className={styles.dataTable}><caption className="sr-only">All source counts; no national total</caption><thead><tr><th scope="col">Source</th>{Object.values(labels).map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead><tbody>{bundles.map(({data}) => <tr key={data.source}><th scope="row">{data.source}</th>{(Object.keys(labels) as MetricKey[]).map(key => <td key={key}>{number(data.overview[key].value)}</td>)}</tr>)}</tbody></table></div></article>
  </>;
}
