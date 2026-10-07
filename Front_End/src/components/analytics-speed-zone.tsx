"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { ArrowUpRight, CircleHelp } from "lucide-react";
import type { Filters, Response } from "@/services/contracts";
import type { SpeedZoneData } from "@/services/speed-zone";
import { getSpeedZones } from "@/services/http-provider";
import { formatSeverityShare } from "@/services/severity-comparison";
import styles from "./analytics.module.css";

const Chart = dynamic(() => import("./analytics-chart"), {ssr:false});
const count = (n: number) => n.toLocaleString("en-AU");

export default function AnalyticsSpeedZone({filters, evidence}: {
  filters: Filters;
  evidence: (title: string, description: string, rows?: {label: string; value: string}[]) => void;
}) {
  const key = JSON.stringify(filters);
  const [result, setResult] = useState<{key:string; response?:Response<SpeedZoneData>; error?:string} | null>(null);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    getSpeedZones(JSON.parse(key) as Filters, controller.signal).then(response => {
      if (!controller.signal.aborted) setResult({key, response});
    }).catch(() => {
      if (!controller.signal.aborted) setResult({key, error:"The verified speed-zone data could not be loaded."});
    });
    return () => controller.abort();
  }, [key, retry]);
  const current = result?.key === key ? result : null;
  const response = current?.response;
  const available = response?.meta.availability === "available";
  const excluded = response?.data.groups.map(group => `${group.source} ${count(group.excluded.reduce((n,row) => n + row.crashes,0))}`).join(" · ");
  const definitions = () => response && evidence("Fatal crash share by speed zone", response.meta.definition, [
    {label:"Grouping", value:"QLD publishes combined 0–50, 80–90 and 100–110 km/h intervals. NSW and VIC exact limits are grouped into compatible whole bands; ranges are never split. These are road speed limits, not vehicle travel speeds."},
    {label:"Selection", value:`${filters.dateRange.from} to ${filters.dateRange.to} · ${response.meta.datasetVersion} · batch ${response.meta.batchId}`},
    ...response.data.groups.flatMap(group => [
      {label:`${group.source} · source field`, value:group.field},
      ...(group.reason ? [{label:`${group.source} · availability`, value:group.reason}] : []),
      ...group.rows.map(row => ({label:`${group.source} · ${response.data.bands.find(band => band.id === row.band)?.label} km/h`, value:`${formatSeverityShare(row.share)} · ${count(row.fatalCrashes)} fatal / ${count(row.crashes)} recorded crashes; ${count(row.fatalKnown)} known fatal status`})),
      ...group.excluded.map(row => ({label:`${group.source} · excluded native limit ${row.nativeValue || "(missing)"}`, value:`${count(row.crashes)} recorded crashes · ${count(row.fatalCrashes)} fatal crashes; not assigned to a plotted band`})),
    ]),
    {label:"Coverage", value:"QLD records casualty crashes; source inclusion and severity definitions differ. No national total or traffic-exposure risk is calculated."},
  ]);
  return <article className={styles.card} aria-label="Fatal crash share by speed zone">
    <div className={styles.cardHeading}><div><h2>Fatal crash share by speed zone</h2></div><button className={styles.info} aria-label="Speed-zone definitions and values" disabled={!response} onClick={definitions}><CircleHelp size={17}/></button></div>
    <div className={styles.speedZoneChart}>
      {available && response ? <Chart kind="speed-zone" rows={[]} speedZones={response.data}/> : <div className={styles.chartLoading} role="status"><p>{current?.error || response?.data.reason || response?.meta.reason || (current ? "No verified speed-zone observations for this selection." : "Loading speed-zone data…")}</p>{current?.error && <button className={styles.textButton} onClick={() => setRetry(n => n + 1)}>Try again</button>}</div>}
    </div>
    {available && <p className={styles.speedZoneNotice}>Excluded unknown / other limits: {excluded}</p>}
    <div className={styles.cardFoot}><button disabled={!response} onClick={definitions}>Definitions <ArrowUpRight size={14}/></button></div>
  </article>;
}
