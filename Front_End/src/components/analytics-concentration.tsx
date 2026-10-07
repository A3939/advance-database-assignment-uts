"use client";

import { useEffect, useId, useMemo, useRef, useState, type PointerEvent } from "react";
import { concentrationAtShare, spatialConcentration } from "@/services/analytics-insights";
import type { MapRegion, SourceSelection } from "@/services/contracts";
import styles from "./analytics.module.css";

const palette = ["var(--coral)", "var(--severity-other)", "var(--chart-trend)"];
const number = (n: number) => n.toLocaleString("en-AU");
const percent = (n: number) => `${n.toFixed(1)}%`;

/** Shared by the All comparison and the existing single-source area curve. */
export default function AnalyticsConcentration({ groups, comparison = false }: {
  groups: { source: SourceSelection; regions: MapRegion[] }[];
  comparison?: boolean;
}) {
  const root = useRef<HTMLDivElement>(null);
  const tooltipId = useId();
  const hintId = useId();
  const [width, setWidth] = useState(640);
  const [inspection, setInspection] = useState<{ key: string; value: number } | null>(null);
  const series = useMemo(() => groups.map((group, index) => ({
    source: group.source, color: comparison ? palette[index % palette.length] : "var(--chart-trend)",
    ...spatialConcentration(group.regions),
  })), [groups, comparison]);
  const key = JSON.stringify(series);
  const inspected = inspection?.key === key ? inspection.value : null;
  const available = series.filter(group => group.points.length > 0);
  const height = comparison ? 340 : 260;
  const left = 44, right = Math.max(left + 1, width - 16), top = 30, bottom = height - 50;
  const max = comparison ? 100 : (series[0]?.areaCount || 1);
  const xTicks = [...new Set([0, 25, 50, 75, 100].map(tick => Math.round(tick / 100 * max)))];
  const x = (share: number) => left + share / 100 * (right - left);
  const y = (share: number) => bottom - share / 100 * (bottom - top);
  const activeShare = inspected === null ? null : inspected / max * 100;
  const readouts = available.map(group => ({ group, point: concentrationAtShare(group, activeShare ?? 0)! }));
  const setInspectionValue = (value: number) => setInspection({ key, value: Math.max(0, Math.min(max, Math.round(value))) });

  useEffect(() => {
    if (!root.current) return;
    const observer = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width));
    observer.observe(root.current);
    return () => observer.disconnect();
  }, []);

  function inspectPointer(event: PointerEvent<SVGRectElement>) {
    const box = event.currentTarget.getBoundingClientRect();
    setInspectionValue((event.clientX - box.left) / Math.max(1, box.width) * max);
  }
  const spokenValues = readouts.map(({ group, point }) =>
    `${group.source}: top ${point.areas} of ${group.areaCount} areas, ${percent(point.areaShare)} of areas; ${number(point.crashes)} mapped crashes, ${percent(point.crashShare)} of mapped crashes.`).join(" ");
  const tooltipWidth = Math.min(comparison ? 290 : 260, Math.max(0, width - 16));
  const anchor = x(activeShare ?? 0);
  const tooltipLeft = Math.max(8, Math.min(width - tooltipWidth - 8,
    (activeShare ?? 0) > 50 ? anchor - tooltipWidth - 18 : anchor + 18));

  return <div className={styles.concentrationChart} ref={root}>
    {comparison && <div className={styles.concentrationLegend} aria-label="Concentration sources">
      {series.map(group => <span key={group.source}><i style={{ background: group.color }}/>{group.source}{!group.points.length && " · unavailable"}</span>)}
      <span className={styles.concentrationReference}><i/>Even distribution</span>
    </div>}
    {!available.length ? <p className={styles.emptyDetail} role="status">No mapped crashes for this period.</p> : <>
      <div className={styles.concentrationPlot}>
        <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`}>
          <text className={styles.concentrationAxisTitle} x={left} y="13">Cumulative crash share</text>
          {[0, 25, 50, 75, 100].map(tick => <g key={tick} className={styles.concentrationGrid}>
            <line x1={left} x2={right} y1={y(tick)} y2={y(tick)}/>
            <text x={left - 10} y={y(tick) + 4} textAnchor="end">{tick}%</text>
          </g>)}
          {comparison && <path className={styles.concentrationDiagonal} d={`M${left},${bottom} L${right},${top}`}/>}
          {available.map(group => {
            const path = group.points.map((point, i) => `${i ? "L" : "M"}${x(point.areaShare)},${y(point.crashShare)}`).join(" ");
            return <g key={group.source}>
              {!comparison && <path fill="var(--chart-area)" d={`${path} L${right},${bottom} Z`}/>}
              <path d={path} fill="none" stroke={group.color} strokeWidth="2.5" strokeLinejoin="round"/>
            </g>;
          })}
          {xTicks.map(tick => <text className={styles.concentrationTick} key={tick}
            x={x(tick / max * 100)} y={bottom + 22} textAnchor={tick === 0 ? "start" : tick === max ? "end" : "middle"}>
            {comparison ? `${tick}%` : tick}
          </text>)}
          <text className={styles.concentrationAxisTitle} x={(left + right) / 2} y={height - 4} textAnchor="middle">
            {comparison ? "Share of mapped areas · highest counts first" : "Number of areas · highest counts first"}
          </text>
          {activeShare !== null && <g pointerEvents="none">
            <line className={styles.concentrationGuide} x1={x(activeShare)} x2={x(activeShare)} y1={top} y2={bottom}/>
            {readouts.map(({ group, point }) => <g key={group.source}>
              <circle cx={x(point.areaShare)} cy={y(point.crashShare)} r="9" fill={group.color} opacity=".16"/>
              <circle cx={x(point.areaShare)} cy={y(point.crashShare)} r="4.5" fill={group.color} stroke="var(--surface)" strokeWidth="2"/>
            </g>)}
          </g>}
          <rect className={styles.concentrationHitArea} x={left} y={top} width={right - left} height={bottom - top}
            fill="transparent" tabIndex={0} role="slider" aria-label={comparison ? "Inspect crash concentration by source" : "Inspect cumulative crashes by area"}
            aria-valuemin={0} aria-valuemax={max} aria-valuenow={inspected ?? 0}
            aria-valuetext={inspected === null ? "Use left and right arrow keys to inspect values" : spokenValues}
            aria-describedby={hintId} aria-controls={inspected === null ? undefined : tooltipId}
            onPointerMove={inspectPointer} onPointerDown={inspectPointer}
            onPointerLeave={event => { if (event.pointerType !== "touch") setInspection(null); }}
            onBlur={() => setInspection(null)}
            onKeyDown={event => {
              if (event.key === "Escape") { setInspection(null); return; }
              const direction = ["ArrowRight", "ArrowUp"].includes(event.key) ? 1 : ["ArrowLeft", "ArrowDown"].includes(event.key) ? -1 : 0;
              if (direction || event.key === "Home" || event.key === "End") {
                event.preventDefault();
                setInspectionValue(event.key === "Home" ? 0 : event.key === "End" ? max : (inspected ?? 0) + direction);
              }
            }}/>
        </svg>
        {inspected !== null && <div className={styles.concentrationTooltip} role="tooltip" id={tooltipId}
          style={{ left: tooltipLeft, top: comparison ? 48 : 40, width: tooltipWidth }}>
          {comparison && <strong>Near {inspected}% of mapped areas</strong>}
          {readouts.map(({ group, point }) => <div className={styles.concentrationReadout} key={group.source}>
            <span><i style={{ background: group.color }}/><b>{group.source}</b><span>{percent(point.crashShare)}</span></span>
            <p>Top {number(point.areas)} of {number(group.areaCount)} areas · {percent(point.areaShare)}</p>
            <p>{number(point.crashes)} of {number(group.total)} mapped crashes</p>
          </div>)}
        </div>}
      </div>
      <p id={hintId} className="sr-only">Hover, tap or use arrow keys to inspect{comparison ? " · values snap to whole areas" : ""}.</p>
    </>}
  </div>;
}
