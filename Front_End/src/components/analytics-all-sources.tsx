"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { ArrowUpRight, ArrowDownWideNarrow, CalendarDays, CarFront, Heart, Info, Map, MapPin, PieChart, Siren, Target, TrendingUp, Users, type LucideIcon } from "lucide-react";
import { allSourceAreaRanking, monthlyInsights, spatialInsights } from "@/services/analytics-insights";
import { timePointLabel } from "@/services/periods";
import type { getAnalytics, MetricKey } from "@/services/analytics";
import type { MapData, SourceSelection } from "@/services/contracts";
import styles from "./analytics.module.css";
import AnalyticsSeverityChange from "./analytics-severity-change";
import AnalyticsSeverityShare from "./analytics-severity-share";
import AnalyticsSpeedZone from "./analytics-speed-zone";
import AnalyticsConcentration from "./analytics-concentration";

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
export default function AnalyticsAllSources({ bundles, dashboard, metric, granularity, map, sourceMaps, evidence, onSourceSelect, onAreaSelect, setMetric, setGranularity }: {
  bundles: Bundle[];
  dashboard: "trends" | "severity" | "spatial";
  metric: MetricKey;
  granularity: "monthly" | "yearly";
  map: MapData | null;
  sourceMaps: { source: SourceSelection; data: MapData }[];
  evidence: (title: string, description: string, rows?: { label: string; value: string }[]) => void;
  onSourceSelect: (source: SourceSelection) => void;
  onAreaSelect: (source: SourceSelection, regionId: string) => void;
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
  const rankedAreas = allSourceAreaRanking(sourceMaps);
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
    {dashboard === "severity" && <section className={`${styles.severityGrid} ${styles.allSeverityGrid}`} aria-label="Severity composition">
      <article className={styles.card}>
        <div className={styles.cardHeading}><div><h2>Severity distribution by source</h2></div><div className={styles.segment} aria-label="Severity measure">{(["count", "share"] as const).map(value => <button key={value} aria-pressed={severityMode === value} onClick={() => setSeverityMode(value)}>{value === "count" ? "Count" : "Share"}</button>)}</div></div>
        <div className={styles.severityChart} data-mode={severityMode}>{bundles.some(({data}) => data.severityAvailability === "available") ? severityMode === "share" ? <AnalyticsSeverityShare sources={bundles.map(({data}) => data.source)} rows={bundles.flatMap(({data}) => data.severityAvailability === "available" ? data.severity.map(row => ({...row, source:data.source})) : [])}/> : <Chart kind="severity" rows={[]} severitySources={bundles.map(({data}) => data.source)} severity={bundles.flatMap(({data}) => data.severityAvailability === "available" ? data.severity.map(row => ({...row, source:data.source})) : [])} mode={severityMode}/> : <div className={styles.chartLoading} role="status">No category breakdown is available for this selection.</div>}</div>
        {bundles.filter(({data}) => data.severityAvailability !== "available").map(({data}) => <p className={styles.severityNotice} key={data.source}>{data.source}: {data.severityReason || "Category breakdown unavailable for this selection."}</p>)}
        <div className={styles.cardFoot}><span>Source definitions differ · N/A ≠ 0</span><button onClick={() => evidence("Severity definitions & values", "Categories are grouped for display only. Share uses each source’s own selected-period crash denominator. These native categories are not an interstate harmonisation.", bundles.flatMap(({data}) => data.severity.map(row => ({label:`${data.source} · ${row.label}`, value:`${number(row.count)} crashes · ${row.share != null && row.share > 0 && row.share < .001 ? "<0.1%" : percentage(row.share == null ? null : row.share * 100)} · ${row.definition}`}))))}>Definitions <ArrowUpRight size={14}/></button></div>
      </article>
      {bundles[0] && <AnalyticsSpeedZone filters={{...bundles[0].data.filters, source:"All", regionId:undefined}} evidence={evidence}/>}
    </section>}
    {dashboard === "spatial" && map && <section className={styles.spatialGrid} aria-label="Geographic distribution">
      <article className={`${styles.spatialMap} spatial-panel seamless-map`} aria-label="Crash map"><SpatialMap data={map} source="All" onSourceSelect={onSourceSelect} onSelect={() => {}} compactLegend/></article>
      <article className={styles.card}>
        <div className={styles.cardHeading}><div><h2>Highest-count areas</h2></div></div>
        <ol className={styles.rankList}>{rankedAreas.slice(0, 10).map(row => <li key={`${row.source}:${row.id}`}><button onClick={() => onAreaSelect(row.source, row.id)}><span className={styles.rankIndex}>{row.rank.toString().padStart(2, "0")}</span><span className={styles.rankName}>{row.name.endsWith(`(${row.source})`) ? row.name : `${row.name} (${row.source})`}<i style={{width:`${row.count / Math.max(rankedAreas[0]?.count ?? 0, 1) * 100}%`}}/></span><strong>{number(row.count)}</strong></button></li>)}</ol>
        {!rankedAreas.length && <p className={styles.emptyDetail}>No mapped areas for this period.</p>}
      </article>
    </section>}
    {dashboard === "spatial" && <article className={`${styles.card} ${styles.concentrationCard}`} aria-label="Crash concentration by area">
      <div className={styles.cardHeading}><div><h2>Crash concentration by area</h2></div>
        <button className={styles.info} aria-label="Crash concentration definitions" onClick={() => evidence("Crash concentration by area", "Each source is ranked separately from highest to lowest crash count. The horizontal axis is the cumulative percentage of supplied mapped areas, including recorded zero-count areas. The vertical axis is the cumulative share of mapped crashes. Unmatched records are excluded. Hover values use the nearest whole number of areas, without interpolating crash counts. The diagonal represents an equal number of crashes in every area; a higher curve indicates more concentration, not greater risk. Source coverage and definitions still differ.", summaries.map(({data,spatial}) => ({label:data.source,value:spatial ? `${number(spatial.ranked.length)} mapped areas · ${number(spatial.total)} mapped crashes` : "Observed LGA data unavailable"})))}><Info size={17}/></button>
      </div>
      <AnalyticsConcentration comparison groups={sourceMaps.map(({source,data}) => ({source,regions:data.regionMode === "lga" && !data.illustrationOnly ? data.regions : []}))}/>
    </article>}
    {dashboard === "trends" && <article className={styles.card} style={{marginBlock:"var(--analysis-gap, 20px)"}} aria-label="Source trend comparison">
      <div className={styles.cardHeading} style={{flexWrap:"wrap"}}>
        <div style={{display:"flex",alignItems:"center",gap:10}}><h2>{labels[metric]} over time</h2><button className={styles.info} aria-label="Source trend values and definitions" onClick={() => evidence(`${labels[metric]} over time`, "Source counts use the same time and value axes and remain separate. Definitions and coverage differ by source. Missing values are gaps, not zeros. Asterisks mark selected-month subtotals.", bundles.flatMap(({data}) => (granularity === "monthly" ? data.monthly : data.timeSeriesYearly).map(row => ({label:`${data.source} · ${timePointLabel(row)}`, value:number(row[metric])}))))}><Info size={16}/></button></div>
        <div className={styles.segment} aria-label="Trend interval">{(["monthly", "yearly"] as const).map(value => <button key={value} aria-pressed={granularity === value} onClick={() => setGranularity(value)}>{value === "monthly" ? "Monthly" : "Yearly"}</button>)}</div>
      </div>
      <div className={styles.metricTabs} aria-label="Trend metric">{Object.entries(labels).map(([key, label]) => <button key={key} aria-pressed={metric === key} onClick={() => setMetric(key as MetricKey)}>{label}</button>)}</div>
      {/* Keep a definite, non-shrinking canvas host even while development styles refresh. */}
      <div style={{height:"clamp(320px, 30vw, 370px)",minHeight:320,flex:"none",margin:"14px clamp(4px, 2vw, 16px) 18px"}}><Chart kind="trend" rows={bundles.flatMap(({data}) => (granularity === "monthly" ? data.monthly : data.timeSeriesYearly).map(row => ({...row, source:data.source})))} trendSources={bundles.map(({data}) => data.source)} granularity={granularity} metric={metric}/></div>
      {granularity === "yearly" && bundles.some(({data}) => data.timeSeriesYearly.some(row => row.fullYear === false)) && <div className={styles.cardFoot}>* Selected months only · not a full-year total</div>}
    </article>}
    {dashboard === "severity" && bundles[0] && <AnalyticsSeverityChange filters={{...bundles[0].data.filters, source:"All", regionId:undefined}} evidence={evidence}/>}
    <article className={styles.card}><div className={styles.cardHeading}><div><h2>Source detail</h2></div></div><div className={styles.tableScroll}><table className={styles.dataTable}><caption className="sr-only">All source counts; no national total</caption><thead><tr><th scope="col">Source</th>{Object.values(labels).map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead><tbody>{bundles.map(({data}) => <tr key={data.source}><th scope="row">{data.source}</th>{(Object.keys(labels) as MetricKey[]).map(key => <td key={key}>{number(data.overview[key].value)}</td>)}</tr>)}</tbody></table></div></article>
  </>;
}
