"use client";

import { useEffect, useState } from "react";
import { CircleHelp } from "lucide-react";
import type { Filters, Response } from "@/services/contracts";
import type { SeverityChange, SeverityChangeGroup } from "@/services/severity-change";
import { getSeverityChange } from "@/services/http-provider";
import { groupSeverityCategories } from "@/services/severity-comparison";
import styles from "./analytics.module.css";
import unified from "./analytics-severity-change.module.css";

const share = (value: number | null) => value === null ? "—" : `${value.toFixed(1)}%`;
const change = (value: number | null) => value === null ? "—" : `${Math.abs(value) < 0.05 ? "0.0" : `${value > 0 ? "+" : "−"}${Math.abs(value).toFixed(1)}`} pp`;

function ChangeLegend({ groups, periods }: { groups: SeverityChangeGroup[]; periods: NonNullable<SeverityChange["periods"]> }) {
  return <div className={unified.legend} aria-label="Chart legend">
    <div className={unified.legendSources}>{groups.map(group => <span key={group.source} data-source={group.source}><i className={unified.sourceDot}/>{group.source}</span>)}</div>
    <div className={unified.legendYears}><span><i className={unified.yearStart}/>{periods[0].year}</span><span><i className={unified.yearEnd}/>{periods[1].year}</span></div>
  </div>;
}

function CombinedDumbbell({ groups, periods, max }: { groups: SeverityChangeGroup[]; periods: NonNullable<SeverityChange["periods"]>; max: number }) {
  const comparison = groupSeverityCategories(groups.flatMap(group => group.rows.map(row => ({ ...row, source: group.source }))), groups.map(group => group.source));
  return <>
    {groups.filter(group => group.reason).map(group => <p className={styles.changeNotice} role="status" key={group.source}>{group.source}: {group.reason}</p>)}
    {comparison.groups.length > 0 && <>
      <div className={unified.scroll} tabIndex={0} role="region" aria-label="Severity share comparison across sources">
        <table className={unified.table}>
          <caption className="sr-only">Native severity shares by category and source, {periods[0].label} versus {periods[1].label}. Display groups do not imply equivalent source definitions. Change in percentage points.</caption>
          <colgroup><col className={unified.categoryColumn}/><col className={unified.sourceColumn}/><col className={unified.nativeColumn}/><col/><col className={unified.valueColumn}/><col className={unified.valueColumn}/><col className={unified.changeColumn}/></colgroup>
          <thead><tr>
            <th scope="col">Category</th><th scope="col">State</th><th scope="col">Source category</th>
            <th scope="col"><span className="sr-only">Share of recorded crashes</span><div className={unified.axis} aria-hidden="true">{[0, 1, 2, 3, 4].map(tick => <span key={tick} style={{ left: `${tick * 25}%` }}>{max * tick / 4}%</span>)}</div></th>
            <th scope="col">{periods[0].year}</th><th scope="col">{periods[1].year}</th><th scope="col">Change (pp)</th>
          </tr></thead>
          {comparison.groups.map(category => <tbody key={category.label}>
            {comparison.sources.map((source, index) => {
              const row = category.rows[index];
              const totals = groups.find(group => group.source === source)?.totals;
              return <tr key={source} className={unified.row} data-source={source} tabIndex={0}>
                {index === 0 && <th scope="rowgroup" rowSpan={comparison.sources.length} className={unified.category}>{category.label.replaceAll("\n", " ")}</th>}
                <th scope="row" className={unified.source}><span><i className={unified.sourceDot}/>{source}</span></th>
                <td className={row ? unified.native : unified.unavailable}>{row?.label ?? "Not available"}</td>
                <td className={unified.plot} aria-hidden="true"><div className={unified.track}>
                  {[0, 1, 2, 3, 4].map(tick => <i key={tick} className={unified.gridline} style={{ left: `${tick * 25}%` }}/>)}
                  {row?.startShare != null && row.endShare != null && <i className={unified.connector} style={{ left: `${Math.min(row.startShare, row.endShare) / max * 100}%`, width: `${Math.abs(row.endShare - row.startShare) / max * 100}%` }}/>}
                  {row?.startShare != null && <i className={unified.startDot} style={{ left: `${row.startShare / max * 100}%` }}/>}
                  {row?.endShare != null && <i className={unified.endDot} style={{ left: `${row.endShare / max * 100}%` }}/>}
                </div></td>
                <td className={unified.value} title={row && totals ? `${row.startCount.toLocaleString("en-AU")} / ${totals[0].toLocaleString("en-AU")} crashes` : undefined}>{share(row?.startShare ?? null)}</td>
                <td className={unified.value} title={row && totals ? `${row.endCount.toLocaleString("en-AU")} / ${totals[1].toLocaleString("en-AU")} crashes` : undefined}>{share(row?.endShare ?? null)}</td>
                <td className={unified.value}>{change(row?.change ?? null).replace(" pp", "")}</td>
              </tr>;
            })}
          </tbody>)}
        </table>
      </div>
    </>}
  </>;
}

function SourceDumbbell({ group, periods, max }: { group: SeverityChangeGroup; periods: NonNullable<SeverityChange["periods"]>; max: number }) {
  const largest = group.rows.reduce<SeverityChangeGroup["rows"][number] | null>((best, row) => row.change !== null && (!best || Math.abs(row.change) > Math.abs(best.change!)) ? row : best, null);
  return <section className={styles.changeSource} aria-label={`${group.source} severity share change`}>
    <div className={styles.changeSourceHeading}><strong>{group.source}{group.area ? ` · ${group.area} LGA` : ""}</strong></div>
    {group.reason && <p className={styles.changeNotice} role="status">{group.reason}</p>}
    {group.rows.length > 0 && <>
      <div className={styles.changeTableWrap}>
        <table className={styles.changeTable}>
          <caption className="sr-only">{group.source}: native severity shares, {periods[0].label} versus {periods[1].label}. Change in percentage points.</caption>
          <thead><tr><th scope="col"><span className="sr-only">Source category</span></th><th scope="col"><span className="sr-only">Share comparison</span></th><th scope="col">{periods[0].year}</th><th scope="col">{periods[1].year}</th><th scope="col">Change</th></tr></thead>
          <tbody>{group.rows.map(row => <tr key={row.label} className={styles.changeRow} tabIndex={0}>
            <th scope="row">{row.label}</th>
            <td className={styles.changePlot} aria-hidden="true"><div className={styles.changeTrack}>
              {[0, 1, 2, 3, 4].map(tick => <i className={styles.changeGridline} key={tick} style={{ left: `${tick * 25}%` }}/>) }
              {row.startShare !== null && row.endShare !== null && <i className={styles.changeConnector} style={{ left: `${Math.min(row.startShare, row.endShare) / max * 100}%`, width: `${Math.abs(row.endShare - row.startShare) / max * 100}%` }}/>}
              {row.startShare !== null && <i className={styles.changeStartDot} style={{ left: `${row.startShare / max * 100}%` }}/>}
              {row.endShare !== null && <i className={styles.changeEndDot} style={{ left: `${row.endShare / max * 100}%` }}/>}
            </div></td>
            <td title={`${row.startCount.toLocaleString("en-AU")} / ${group.totals?.[0].toLocaleString("en-AU")} crashes`}>{share(row.startShare)}</td>
            <td className={styles.changeEndValue} title={`${row.endCount.toLocaleString("en-AU")} / ${group.totals?.[1].toLocaleString("en-AU")} crashes`}>{share(row.endShare)}</td>
            <td>{change(row.change)}</td>
          </tr>)}</tbody>
        </table>
        <div className={styles.changeAxis} aria-hidden="true"><div>{[0, 1, 2, 3, 4].map(tick => <span key={tick} style={{ left: `${tick * 25}%` }}>{(max * tick / 4).toLocaleString("en-AU", { maximumFractionDigits: 1 })}%</span>)}</div></div>
      </div>
      {largest && <div className={styles.changeInsight}><span>Largest change</span><strong>{largest.label}</strong><b>{change(largest.change)}</b></div>}
    </>}
  </section>;
}

export default function AnalyticsSeverityChange({ filters, evidence }: {
  filters: Filters;
  evidence: (title: string, description: string, rows?: { label: string; value: string }[]) => void;
}) {
  const key = JSON.stringify(filters);
  const [result, setResult] = useState<{ key: string; response?: Response<SeverityChange>; error?: string } | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    getSeverityChange(JSON.parse(key) as Filters, controller.signal).then(response => {
      if (!controller.signal.aborted) setResult({ key, response });
    }).catch(() => {
      if (!controller.signal.aborted) setResult({ key, error: "The severity comparison could not be loaded." });
    });
    return () => controller.abort();
  }, [key, retry]);
  const current = result?.key === key ? result : null;
  const response = current?.response, data = response?.data, periods = data?.periods;
  const combined = filters.source === "All";
  // A shared scale even in All; source category identities and denominators stay separate.
  const peak = Math.max(0, ...(data?.groups.flatMap(group => group.rows.flatMap(row => [row.startShare ?? 0, row.endShare ?? 0])) ?? []));
  const max = Math.min(100, Math.max(20, Math.ceil(peak / 20) * 20));
  const definitions = () => response && evidence("Severity share change", response.meta.definition, [
    ...(periods ? [{ label: "Comparison", value: `${periods[0].label} vs ${periods[1].label} · identical calendar months` }] : []),
    { label: "Measure", value: "Each category's crash count / all recorded crashes in that source and period. Change is percentage points, not percentage growth." },
    { label: "Provenance", value: response.meta.availability === "available" && response.data.groups.some(group => group.availability === "available" && group.rows.length > 0)
      ? `Verified monthly extension · ${response.meta.datasetVersion} · ${response.meta.batchId}. Source-wide counts include unmatched areas.`
      : `No verified comparison for this selection · ${response.meta.datasetVersion} · ${response.meta.batchId}. ${response.data.reason || response.meta.reason || response.data.groups.find(group => group.reason)?.reason || "Comparison values are unavailable."}` },
    ...response.data.groups.flatMap(group => group.rows.map(row => ({ label: `${group.source}${group.area ? ` · ${group.area}` : ""} · ${row.label}`, value: `${row.startCount.toLocaleString("en-AU")} / ${group.totals?.[0].toLocaleString("en-AU")} → ${row.endCount.toLocaleString("en-AU")} / ${group.totals?.[1].toLocaleString("en-AU")} crashes · ${change(row.change)}` }))),
  ]);
  return <article className={`${styles.card} ${styles.changeCard}`} aria-label="Severity share change">
    <div className={`${styles.cardHeading} ${combined ? unified.heading : ""}`}><div><h2>Severity share change</h2>{periods && <p>{periods[0].label} vs {periods[1].label}</p>}</div>{combined && periods && data && !data.reason && <ChangeLegend groups={data.groups} periods={periods}/>}<button className={styles.info} aria-label="Severity share change definitions and values" disabled={!response} onClick={definitions}><CircleHelp size={17}/></button></div>
    {!current && <p className={styles.changeNotice} role="status">Loading severity comparison…</p>}
    {current?.error && <div className={styles.changeNotice} role="status"><p>{current.error}</p><button className={styles.textButton} onClick={() => setRetry(value => value + 1)}>Reload comparison</button></div>}
    {data?.reason ? <p className={styles.changeNotice} role="status">{data.reason}</p> : periods && (combined ? <CombinedDumbbell groups={data?.groups ?? []} periods={periods} max={max}/> : <>
      <div className={styles.changeLegend}><span><i/>{periods[0].year}</span><span><i/>{periods[1].year}</span></div>
      {data?.groups.map(group => <SourceDumbbell key={group.source} group={group} periods={periods} max={max}/>)}
    </>)}
  </article>;
}
