"use client";
import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts/core";
import { LineChart, BarChart } from "echarts/charts";
import {
  GridComponent,
  TooltipComponent,
  AriaComponent,
  LegendComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsCoreOption } from "echarts/core";
import type { TimePoint, Severity } from "@/services/contracts";
import { useTheme } from "@/components/theme-provider";
echarts.use([
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  AriaComponent,
  LegendComponent,
  CanvasRenderer,
]);
export default function Chart({
  kind,
  rows,
}: {
  kind: "trend" | "severity";
  rows: TimePoint[] | Severity[];
}) {
  const { theme } = useTheme();
  const [fontSize, setFontSize] = useState(12);
  const [chartHeight, setChartHeight] = useState(240);
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.EChartsType | null>(null);
  useEffect(() => {
    if (!host.current) return;
    chart.current = echarts.init(host.current);
    const ro = new ResizeObserver(() => {
      chart.current?.resize();
      if (host.current) {
        setFontSize(parseFloat(getComputedStyle(host.current).fontSize));
        setChartHeight(Math.round(host.current.clientHeight));
      }
    });
    ro.observe(host.current);
    return () => {
      ro.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);
  useEffect(() => {
    if (!chart.current || !host.current) return;
    const style = getComputedStyle(host.current);
    const token = (name: string) => style.getPropertyValue(name).trim();
    const text = token("--text-secondary"),
      lime = token("--chart-trend"),
      coral = token("--coral"),
      line = token("--chart-grid");
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const base: EChartsCoreOption = {
      animation: !reduced,
      animationDuration: 200,
      animationDurationUpdate: 200,
      textStyle: { fontFamily: "Inter, system-ui, sans-serif", fontSize },
      aria: { enabled: true },
      tooltip: {
        trigger: "axis",
        backgroundColor: token("--surface-elevated"),
        borderColor: token("--border"),
        textStyle: { color: token("--text-primary"), fontSize: fontSize + 1 },
        confine: true,
      },
      grid: { left: 50, right: 30, top: 32, bottom: 34 },
      xAxis: {
        axisLine: { lineStyle: { color: line } },
        axisTick: { show: false },
        axisLabel: { fontSize, color: text, margin: 14 },
        splitLine: { show: false },
      },
      yAxis: {
        type: "value",
        splitNumber: Math.max(
          2,
          Math.min(5, Math.floor((chartHeight - 60) / 34)),
        ),
        axisLine: { show: false },
        axisLabel: { fontSize, color: text },
        splitLine: { lineStyle: { color: line, type: "dashed" } },
      },
    };
    if (kind === "trend") {
      const data = rows as TimePoint[];
      const periods = [...new Set(data.map((r) => r.period))];
      const groups = [
        ...new Set(data.map((r) => r.source || "Recorded crashes")),
      ];
      const multiple = groups.length > 1;
      const colors = [lime, coral, token("--chart-blue")];
      Object.assign(base, {
        legend: {
          show: multiple,
          top: 5,
          left: 50,
          icon: "circle",
          itemWidth: 7,
          itemHeight: 7,
          textStyle: { color: text, fontSize },
          selectedMode: false,
        },
        grid: {
          left: Math.round((50 * fontSize) / 12),
          right: 30,
          top: multiple ? (chartHeight < 160 ? 28 : 40) : 32,
          bottom: chartHeight < 160 ? 26 : 34,
        },
        xAxis: {
          axisLine: { lineStyle: { color: line } },
          axisTick: { show: false },
          type: "category",
          data: periods,
          boundaryGap: true,
          axisLabel: { fontSize, color: text, margin: 14, hideOverlap: true },
        },
        series: groups.map((source, i) => ({
          id: source,
          name: source,
          type: "line",
          data: periods.map(
            (period) =>
              data.find(
                (r) =>
                  r.period === period &&
                  (r.source || "Recorded crashes") === source,
              )?.crashes ?? null,
          ),
          smooth: 0.2,
          symbol: "circle",
          symbolSize: periods.length > 12 ? 5 : 8,
          lineStyle: { color: colors[i], width: 2 },
          itemStyle: { color: colors[i] },
          areaStyle: multiple
            ? undefined
            : {
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                  { offset: 0, color: token("--chart-area") },
                  { offset: 1, color: "transparent" },
                ]),
              },
          label: {
            show: !multiple && periods.length <= 6,
            position: "top",
            distance: 12,
            color: token("--text-primary"),
            fontSize,
            formatter: (p: { value: unknown }) =>
              Number(p.value).toLocaleString("en-AU"),
          },
        })),
      });
    } else {
      const data = rows as Severity[];
      Object.assign(base, {
        tooltip: {
          backgroundColor: token("--surface-elevated"),
          borderColor: token("--border"),
          textStyle: { color: token("--text-primary"), fontSize: fontSize + 1 },
          confine: true,
          trigger: "item",
          axisPointer: { show: false, type: "none" },
        },
        grid: {
          left: Math.round(
            ((data.some((r) => r.source) ? 174 : 132) * fontSize) / 12,
          ),
          right: Math.round((62 * fontSize) / 12),
          top: 8,
          bottom: 26,
        },
        xAxis: {
          type: "value",
          axisLabel: { fontSize, color: text, hideOverlap: true },
          axisLine: { show: true, lineStyle: { color: line } },
          splitLine: { lineStyle: { color: line, type: "dashed" } },
        },
        yAxis: {
          type: "category",
          inverse: true,
          data: data.map(
            (r) => `${r.source ? `${r.source} · ` : ""}${r.label}`,
          ),
          axisLabel: {
            color: token("--text-primary"),
            interval: 0,
            fontSize,
            width: Math.round(
              ((data.some((r) => r.source) ? 160 : 118) * fontSize) / 12,
            ),
            overflow: "truncate",
          },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        series: [
          {
            name: "Recorded crashes",
            type: "bar",
            stateAnimation: { duration: reduced ? 0 : 180, easing: "cubicOut" },
            emphasis: { focus: "none" },
            barMaxWidth: 18,
            data: data.map((r) => ({
              value: r.count,
              emphasis: {
                itemStyle: {
                  color: token(
                    /^(fatal|serious|hospitalisation)/i.test(r.label)
                      ? "--coral-hover"
                      : "--chart-neutral-hover",
                  ),
                  shadowBlur: 4,
                  shadowColor: token("--chart-hover-shadow"),
                },
              },
              itemStyle: {
                color: /^(fatal|serious|hospitalisation)/i.test(r.label)
                  ? coral
                  : token("--chart-neutral"),
                borderRadius: [0, 2, 2, 0],
              },
            })),
            label: {
              show: true,
              fontSize,
              position: "right",
              distance: 10,
              color: token("--text-primary"),
              formatter: (p: { value: unknown }) =>
                Number(p.value).toLocaleString("en-AU"),
            },
          },
        ],
      });
    }
    chart.current.setOption(base, {
      notMerge: false,
      replaceMerge: ["series"],
      lazyUpdate: true,
    });
  }, [kind, rows, theme, fontSize, chartHeight]);
  return (
    <div
      className="chart"
      ref={host}
      role="img"
      aria-label={
        kind === "trend"
          ? "Recorded crash counts by period. Open chart evidence for accessible values."
          : "Source severity counts. Open severity definitions for accessible values."
      }
    />
  );
}
