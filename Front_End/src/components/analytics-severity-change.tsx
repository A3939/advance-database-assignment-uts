"use client";

import { useEffect, useState } from "react";
import { CircleHelp } from "lucide-react";
import type { Filters, Response } from "@/services/contracts";
import type { SeverityChange, SeverityChangeGroup } from "@/services/severity-change";
import { getSeverityChange } from "@/services/http-provider";
import styles from "./analytics.module.css";

const share = (value: number | null) => value === null ? "—" : `${value.toFixed(1)}%`;
const change = (value: number | null) => value === null ? "—" : `${Math.abs(value) < 0.05 ? "0.0" : `${value > 0 ? "+" : "−"}${Math.abs(value).toFixed(1)}`} pp`;

function SourceDumbbell({ group, periods, max }: { group: SeverityChangeGroup; periods: NonNullable<SeverityChange["periods"]>; max: number }) {
  const largest = group.rows.reduce<SeverityChangeGroup["rows"][number] | null>((best, row) => row.change !== null && (!best || Math.abs(row.change) > Math.abs(best.change!)) ? row : best, null);
  return <section className={styles.changeSource} aria-label={`${group.source} severity share change`}>
    <div className={styles.changeSourceHeading}><strong>{group.source}{group.area ? ` · ${group.area} LGA` : ""}</strong><span>Share of recorded crashes</span></div>
    {group.reason && <p className={styles.changeNotice} role="status">{group.reason}</p>}
    {group.rows.length > 0 && <>
      <div className={styles.changeTableWrap}>
        <table className={styles.changeTable}>
          <caption className="sr-only">{group.source}: native severity shares, {periods[0].label} versus {periods[1].label}. Change in percentage points.</caption>
          <thead><tr><th scope="col"><span className="sr-only">Source category</span></th><th scope="col"><span className="sr-only">Share comparison</span></th><th scope="col">{periods[0].year}</th><th scope="col">{periods[1].year}</th><th scope="col">Change</th></tr></thead>
          <tbody>{group.rows.map(row => <tr key={row.label}>
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
  // A shared scale even in All; source category identities and denominators stay separate.
  const peak = Math.max(0, ...(data?.groups.flatMap(group => group.rows.flatMap(row => [row.startShare ?? 0, row.endShare ?? 0])) ?? []));
  const max = Math.min(100, Math.max(20, Math.ceil(peak / 20) * 20));
  const definitions = () => response && evidence("Severity share change", response.meta.definition, [
    ...(periods ? [{ label: "Comparison", value: `${periods[0].label} vs ${periods[1].label} · identical calendar months` }] : []),
    { label: "Measure", value: "Each category's crash count / all recorded crashes in that source and period. Change is percentage points, not percentage growth." },
    { label: "Provenance", value: `Verified monthly extension · ${response.meta.datasetVersion} · ${response.meta.batchId}. Source-wide counts include unmatched areas.` },
    ...response.data.groups.flatMap(group => group.rows.map(row => ({ label: `${group.source}${group.area ? ` · ${group.area}` : ""} · ${row.label}`, value: `${row.startCount.toLocaleString("en-AU")} / ${group.totals?.[0].toLocaleString("en-AU")} → ${row.endCount.toLocaleString("en-AU")} / ${group.totals?.[1].toLocaleString("en-AU")} crashes · ${change(row.change)}` }))),
  ]);
  return <article className={`${styles.card} ${styles.changeCard}`} aria-label="Severity share change">
    <div className={styles.cardHeading}><div><h2>Severity share change</h2>{periods && <p>{periods[0].label} vs {periods[1].label}</p>}</div><button className={styles.info} aria-label="Severity share change definitions and values" disabled={!response} onClick={definitions}><CircleHelp size={17}/></button></div>
    {!current && <p className={styles.changeNotice} role="status">Loading severity comparison…</p>}
    {current?.error && <div className={styles.changeNotice} role="status"><p>{current.error}</p><button className={styles.textButton} onClick={() => setRetry(value => value + 1)}>Reload comparison</button></div>}
    {data?.reason ? <p className={styles.changeNotice} role="status">{data.reason}</p> : periods && <>
      <div className={styles.changeLegend}><span><i/>{periods[0].year}</span><span><i/>{periods[1].year}</span>{filters.source === "All" && <small>Separate source classifications</small>}</div>
      {data?.groups.map(group => <SourceDumbbell key={group.source} group={group} periods={periods} max={max}/>)}
    </>}
  </article>;
}
