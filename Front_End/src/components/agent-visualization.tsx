"use client";
import { useEffect, useRef } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  AriaComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { useTheme } from "./theme-provider";
import type { AnalysisView } from "@/services/analysis-contracts";
echarts.use([
  BarChart,
  LineChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  AriaComponent,
  CanvasRenderer,
]);
const format = (v: unknown) =>
  typeof v === "number"
    ? v.toLocaleString("en-AU", { maximumFractionDigits: 2 })
    : v === null
      ? "Unknown"
      : String(v);
export default function AgentVisualization({ view }: { view: AnalysisView }) {
  const host = useRef<HTMLDivElement>(null),
    chart = useRef<echarts.EChartsType | null>(null);
  const { theme } = useTheme();
  useEffect(() => {
    if (view.kind === "table" || !host.current) return;
    const instance = echarts.init(host.current);
    chart.current = instance;
    const observer = new ResizeObserver(() => instance.resize());
    observer.observe(host.current);
    return () => {
      observer.disconnect();
      instance.dispose();
      chart.current = null;
    };
  }, [view.kind]);
  useEffect(() => {
    if (!chart.current || !host.current) return;
    const css = getComputedStyle(host.current),
      token = (name: string) => css.getPropertyValue(name).trim();
    const labels = [...new Set(view.rows.map((r) => String(r[view.x])))];
    const groups = view.series
      ? [...new Set(view.rows.map((r) => String(r[view.series!])))]
      : [view.y];
    chart.current.setOption(
      {
        animation: !matchMedia("(prefers-reduced-motion: reduce)").matches,
        animationDuration: 200,
        color: [token("--chart-trend"), token("--coral"), "#79a5c9"],
        textStyle: {
          fontFamily: "Inter, system-ui, sans-serif",
          color: token("--text-secondary"),
        },
        aria: {
          enabled: true,
          description: `${view.title}. Exact values in the data table below.`,
        },
        tooltip: {
          trigger: view.kind === "line" ? "axis" : "item",
          renderMode: "richText",
          confine: true,
          backgroundColor: token("--surface-elevated"),
          borderColor: token("--border"),
          textStyle: { color: token("--text-primary") },
        },
        legend: {
          show: groups.length > 1,
          top: 0,
          textStyle: { color: token("--text-secondary") },
        },
        grid: {
          top: groups.length > 1 ? 36 : 18,
          left: 12,
          right: 18,
          bottom: 20,
          outerBoundsMode: "same",
          outerBoundsContain: "axisLabel",
        },
        xAxis: {
          type: "category",
          data: labels,
          axisLabel: {
            color: token("--text-secondary"),
            hideOverlap: true,
            overflow: "truncate",
            width: 72,
            formatter: (label: string) => {
              const year = /^(\d{4})-01-01 – \1-12-31$/.exec(label);
              return year ? year[1] : label;
            },
          },
          axisLine: { lineStyle: { color: token("--border") } },
          axisTick: { show: false },
        },
        yAxis: {
          type: "value",
          axisLabel: { color: token("--text-secondary") },
          splitLine: { lineStyle: { color: token("--chart-grid") } },
        },
        series: groups.map((group) => ({
          name: group,
          type: view.kind,
          data: labels.map(
            (label) =>
              view.rows.find(
                (r) =>
                  String(r[view.x]) === label &&
                  (!view.series || String(r[view.series]) === group),
              )?.[view.y] ?? null,
          ),
          connectNulls: false,
          barMaxWidth: 32,
          symbolSize: 5,
          emphasis: { focus: "series" },
        })),
      },
      { notMerge: true },
    );
  }, [view, theme]);
  const columns = Object.keys(view.rows[0] || {});
  const unknownMetric = view.kind !== 'table' && view.rows.length > 0 && view.rows.every(row => row[view.y] === null);
  return (
    <figure className="agent-viz">
      <figcaption>
        <strong>{view.title}</strong>
        <small>
          {view.source} · {view.period}
        </small>
      </figcaption>
      {view.kind !== "table" && (
        <div
          ref={host}
          className="agent-chart"
          role="img"
          aria-label={view.title}
        />
      )}
      {unknownMetric && <p role="status">No known values for {view.y}. Unknown observations are not zero.</p>}
      <details open={view.kind === "table" || unknownMetric}>
        <summary>View data{view.truncated ? " · partial result" : ""}</summary>
        <div
          className="agent-table-scroll"
          tabIndex={0}
          aria-label="Analysis data table"
        >
          <table>
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c}>{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {view.rows.map((r, i) => (
                <tr key={i}>
                  {columns.map((c) => (
                    <td key={c}>{format(r[c])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}
