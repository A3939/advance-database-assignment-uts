"use client";
import { SelectField } from "./ui/select-field";

import { useState } from "react";
import dynamic from "next/dynamic";
import { ArrowDownWideNarrow, ChevronLeft, ChevronRight, Map, MapPin, Search, Target } from "lucide-react";
import type { Filters, MapData, SourceSelection } from "@/services/contracts";
import { spatialInsights } from "@/services/analytics-insights";
import AnalyticsMetricCard from "./analytics-metric-card";
import AnalyticsConcentration from "./analytics-concentration";
import styles from "./analytics.module.css";

const SpatialMap = dynamic(() => import("./spatial-map"), { ssr: false, loading: () => <div className={styles.chartLoading}>Loading local boundaries…</div> });
const n = (value: number | null | undefined) => value == null ? "—" : value.toLocaleString("en-AU");
const pct = (value: number | null) => value === null ? "—" : `${value.toFixed(1)}%`;
type Props = { data: MapData; filters: Filters; onSelect: (id: string) => void; onSourceSelect: (source: SourceSelection) => void; evidence: (title: string, description: string, rows?: {label: string; value: string}[]) => void };

export default function AnalyticsSpatial({ data, filters, onSelect, onSourceSelect, evidence }: Props) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"count" | "fatalShare" | "name">("count");
  const [page, setPage] = useState(1);
  const { total, represented, topFiveShare, ranked } = spatialInsights(data.regions);
  const selected = ranked.find(row => row.id === filters.regionId);
  const visible = ranked.filter(row => row.name.toLowerCase().includes(query.toLowerCase())).sort((a, b) => sort === "name" ? a.name.localeCompare(b.name) : sort === "fatalShare" ? (b.fatalShare ?? -1) - (a.fatalShare ?? -1) : a.rank - b.rank);
  const pages = Math.max(1, Math.ceil(visible.length / 8));
  const current = Math.min(page, pages);
  const pointRows = ranked.filter(row => row.fatalShare !== null && row.count > 0);
  const maxX = Math.max(1, ...pointRows.map(row => row.count));
  const maxY = Math.max(1, ...pointRows.map(row => row.fatalShare!));
  const coverage = () => evidence("Spatial scope & coverage", "Local government areas use ABS 2024 boundaries and the snapshot's recorded LGA crosswalk. Counts show recorded crashes, not exposure-adjusted risk or precise crash locations. Rankings and concentration use mapped records only. A missing match is not a crash-free area.", [{label:"Mapped records",value:n(data.coverage?.matched ?? total)}, {label:"Records outside the map",value:n(data.coverage?.unmatched)}, {label:"Boundary / aggregation",value:"ABS 2024 LGA · selected source and period"}]);
  if (data.pointGrid) return <>
    <section className={`metric-grid ${styles.allMetrics} ${styles.singleMetrics}`} aria-label="Spatial summary">
      <AnalyticsMetricCard label="Located crashes" value={n(data.pointGrid.locatedCrashCount)} Icon={MapPin} onDefinition={() => evidence("Trusted coordinate aggregates", "Rounded coordinate cells preserve the current release's spatial evidence. They are not LGA areas or exact crash locations.", [{label:"Unlocated crashes",value:n(data.pointGrid?.unlocatedCrashCount)}, {label:"Cell precision",value:`${data.pointGrid?.precisionDegrees}°`}])}/>
    </section>
    <article className={`${styles.spatialMap} spatial-panel seamless-map`} aria-label="Crash map"><SpatialMap data={data} source={filters.source} onSelect={onSelect} onSourceSelect={onSourceSelect} compactLegend/></article>
    <p className={styles.emptyDetail}>LGA rankings and area concentration are unavailable for coordinate cells.</p>
  </>;
  if (data.regionMode !== "lga" || data.illustrationOnly) return <div className={styles.empty}><h2>LGA analysis unavailable</h2><p>{data.unavailableReason || "This selection does not provide observed LGA aggregates."}</p></div>;
  return <>
    <section className={`metric-grid ${styles.allMetrics} ${styles.singleMetrics}`} aria-label="Spatial summary">{[
      {label:"Mapped crashes",value:n(total),note:`${filters.source} · selected period`,Icon:MapPin},
      {label:"Areas with records",value:n(represented),note:`Of ${n(ranked.length)} observed LGAs`,Icon:Map},
      {label:"Top 5 concentration",value:pct(topFiveShare),note:"Share of mapped crashes",Icon:Target},
      {label:selected ? "Selected area rank" : "Highest-count area",value:selected ? `#${selected.rank}` : ranked[0]?.name ?? "—",note:selected?.name ?? `${n(ranked[0]?.count)} recorded crashes`,Icon:ArrowDownWideNarrow},
    ].map(({label,value,note,Icon}) => <AnalyticsMetricCard key={label} label={label} value={value} Icon={Icon} areaName={label === "Highest-count area"} onDefinition={() => label === "Mapped crashes" ? coverage() : evidence(label, note, [{label:filters.source,value}])}/> )}</section>
    <section className={styles.spatialGrid} aria-label="Geographic distribution">
      <article className={`${styles.spatialMap} spatial-panel seamless-map`} aria-label="Crash map"><SpatialMap data={data} source={filters.source} onSelect={onSelect} onSourceSelect={onSourceSelect} compactLegend/></article>
      <article className={styles.card}><div className={styles.cardHeading}><div><h2>Highest-count areas</h2></div></div><ol className={styles.rankList}>{ranked.slice(0,10).map(row => <li key={row.id}><button aria-pressed={selected?.id === row.id} onClick={() => onSelect(row.id)}><span className={styles.rankIndex}>{row.rank.toString().padStart(2,"0")}</span><span className={styles.rankName}>{row.name}<i style={{width:`${row.count / Math.max(ranked[0]?.count ?? 0,1) * 100}%`}}/></span><strong>{n(row.count)}</strong></button></li>)}</ol></article>
    </section>
    <section className={styles.balancedGrid} aria-label="Spatial comparisons">
      <article className={styles.card}><div className={styles.cardHeading}><div><h2>How concentrated are crashes?</h2></div></div>
        <AnalyticsConcentration groups={[{source:filters.source,regions:data.regions}]}/>
      </article>
      <article className={styles.card}><div className={styles.cardHeading}><div><h2>Volume and fatal outcomes</h2></div></div>
        {pointRows.length > 0 ? <svg className={styles.plot} viewBox="0 0 600 250" role="group" aria-label="LGA crash volume versus fatal share; same values in area table">{[0,0.5,1].map(step => <g key={step}><line x1="58" x2="578" y1={210-step*165} y2={210-step*165}/><text x="48" y={214-step*165} textAnchor="end">{(step*maxY).toFixed(1)}%</text></g>)}<text x="58" y="20">Fatal crashes / all crashes</text>{pointRows.map(row => <circle key={row.id} role="button" tabIndex={0} aria-label={`${row.name}: ${n(row.count)} crashes, ${pct(row.fatalShare)} fatal share`} aria-pressed={selected?.id === row.id} cx={58+row.count/maxX*510} cy={210-row.fatalShare!/maxY*165} r={selected?.id === row.id ? 7 : 4.5} className={selected?.id === row.id ? styles.selectedDot : styles.scatterDot} onClick={() => onSelect(row.id)} onKeyDown={e => {if(e.key === "Enter" || e.key === " "){e.preventDefault();onSelect(row.id);}}}><title>{row.name} · {n(row.count)} crashes · {pct(row.fatalShare)} fatal share</title></circle>)}<text x="58" y="238">0 crashes</text><text x="578" y="238" textAnchor="end">{n(maxX)} crashes</text></svg> : <p className={styles.emptyDetail}>Comparable fatal counts are unavailable.</p>}
      </article>
    </section>
    {selected && <article className={`${styles.card} ${styles.localDetail}`}><div className={styles.cardHeading}><div><h2>{selected.name}</h2><p>Rank #{selected.rank} · {n(selected.count)} crashes · {pct(selected.share)} of mapped records</p></div><button className={styles.textButton} onClick={() => onSelect("")}>Clear selection</button></div><div className={styles.localityList}>{selected.localities?.length ? selected.localities.map(row => <span key={row.name}>{row.name}<strong>{n(row.count)}</strong></span>) : <p>No locality detail is available.</p>}</div>{selected.localities?.length ? <div className={styles.cardFoot}><span>Locality totals · not exact crash locations</span></div> : null}</article>}
    <article className={styles.card}><div className={styles.cardHeading}><div><h2>Area detail</h2></div><div className={styles.tableControls}><label className={styles.search}><Search size={14}/><input aria-label="Search LGAs" value={query} placeholder="Find an area…" onChange={e => {setQuery(e.target.value);setPage(1);}}/></label><SelectField aria-label="Sort LGAs" compact value={sort} onValueChange={value=>{setSort(value as typeof sort);setPage(1);}} options={[{value:"count",label:"Most crashes"},{value:"fatalShare",label:"Highest fatal share"},{value:"name",label:"Area name"}]}/></div></div><div className={styles.tableScroll}><table className={styles.dataTable}><caption className="sr-only">LGA counts, mapped shares and fatal outcomes</caption><thead><tr><th scope="col">Rank</th><th scope="col">Local government area</th><th scope="col">Crashes</th><th scope="col">Mapped share</th><th scope="col">Fatal crashes</th><th scope="col">Fatal share</th></tr></thead><tbody>{visible.slice((current-1)*8,current*8).map(row => <tr key={row.id} className={selected?.id === row.id ? styles.selectedRow : ""}><td>#{row.rank}</td><th scope="row"><button className={styles.textButton} onClick={() => onSelect(row.id)}>{row.name}</button></th><td>{n(row.count)}</td><td>{pct(row.share)}</td><td>{n(row.fatalCrashes)}</td><td>{pct(row.fatalShare)}</td></tr>)}</tbody></table>{!visible.length && <p className={styles.emptyDetail}>No areas match this search.</p>}</div><div className={styles.tableFooter}><span>{visible.length} areas</span><div><button aria-label="Previous area page" disabled={current === 1} onClick={() => setPage(current-1)}><ChevronLeft size={16}/></button><span>{current} / {pages}</span><button aria-label="Next area page" disabled={current === pages} onClick={() => setPage(current+1)}><ChevronRight size={16}/></button></div></div></article>
  </>;
}
