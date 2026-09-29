"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart } from "echarts/charts";
import {
  AriaComponent,
  GridComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsCoreOption } from "echarts/core";
import { useTheme } from "@/components/theme-provider";
import type { Severity, TimePoint } from "@/services/contracts";

echarts.use([
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  AriaComponent,
  CanvasRenderer,
]);

type Metric = "crashes" | "fatalCrashes" | "livesLost" | "casualties";
type ChartKind = "trend" | "seasonality" | "severity";

export type AnalyticsChartPoint = Omit<TimePoint, Metric> &
  Record<Metric, number | null>;

export interface AnalyticsChartProps {
  kind: ChartKind;
  rows: AnalyticsChartPoint[];
  severity?: Severity[];
  metric?: Metric;
  granularity?: "monthly" | "yearly";
  mode?: "count" | "share";
  onSelectPeriod?: (period: string) => void;
}

const metricLabels: Record<Metric, string> = {
  crashes: "Crashes",
  fatalCrashes: "Fatal crashes",
  livesLost: "Lives lost",
  casualties: "Casualties",
};
const months = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];
const monthlyPeriod = /^\d{4}-(0[1-9]|1[0-2])$/;
const emptySeverity: Severity[] = [];
const formatCount = (value: number) =>
  value.toLocaleString("en-AU", { maximumFractionDigits: 0 });
const formatMean = (value: number) =>
  value.toLocaleString("en-AU", { maximumFractionDigits: 1 });
const formatShare = (value: number) =>
  `${value.toLocaleString("en-AU", { maximumFractionDigits: 1 })}%`;
const validValue = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value) && value >= 0;

function tooltipIndex(params: unknown): number {
  const point = Array.isArray(params) ? params[0] : params;
  if (
    point &&
    typeof point === "object" &&
    "dataIndex" in point &&
    typeof point.dataIndex === "number"
  ) {
    return point.dataIndex;
  }
  return -1;
}

export default function AnalyticsChart({
  kind,
  rows,
  severity = emptySeverity,
  metric = "crashes",
  granularity = "monthly",
  mode = "count",
  onSelectPeriod,
}: AnalyticsChartProps) {
  const { theme } = useTheme();
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.EChartsType | null>(null);
  const keyboardIndex = useRef(0);
  const [size, setSize] = useState({ width: 640, height: 300, fontSize: 12 });
  const [reducedMotion, setReducedMotion] = useState(false);
  const trend = useMemo(
    () => [...rows].sort((a, b) => a.period.localeCompare(b.period)),
    [rows],
  );
  const monthly = useMemo(
    () =>
      months.map((label, index) => {
        const observed = rows.flatMap((row) => {
          const value = row[metric];
          return monthlyPeriod.test(row.period) &&
            Number(row.period.slice(5)) === index + 1 &&
            validValue(value)
            ? [{ period: row.period, value }]
            : [];
        });
        return {
          label,
          value: observed.length
            ? observed.reduce((sum, row) => sum + row.value, 0) /
              observed.length
            : null,
          years: [
            ...new Set(observed.map((row) => row.period.slice(0, 4))),
          ].sort(),
          observations: observed.length,
        };
      }),
    [rows, metric],
  );
  const severityData = useMemo(() => {
    const totals = new Map<string, number>();
    severity.forEach((row) => {
      if (validValue(row.count))
        totals.set(
          row.source ?? "selected",
          (totals.get(row.source ?? "selected") ?? 0) + row.count,
        );
    });
    return severity.map((row) => {
      const total = totals.get(row.source ?? "selected") ?? 0;
      return {
        ...row,
        share:
          validValue(row.count) && total > 0 ? (row.count / total) * 100 : null,
      };
    });
  }, [severity]);
  const multipleSeveritySources =
    new Set(severity.map((row) => row.source)).size > 1;
  const description =
    kind === "trend"
      ? `${metricLabels[metric]} by ${granularity === "monthly" ? "month" : "year"}. ${onSelectPeriod && granularity === "monthly" ? "Use left and right arrow keys to inspect a month and Enter to select it. " : ""}Exact values are available in the accompanying data table.`
      : kind === "seasonality"
        ? `Average ${metricLabels[metric].toLowerCase()} for each calendar month across the supplied monthly observations. Missing months are not zero-filled. This descriptive pattern does not establish seasonality. Exact values are available in the accompanying data table.`
        : `Severity ${mode === "share" ? "shares within each source" : "crash counts"}. Categories retain their source definitions. Exact values are available in the accompanying data table.`;

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const instance = echarts.init(element);
    chart.current = instance;
    const observer = new ResizeObserver(() => {
      if (instance.isDisposed()) return;
      instance.resize();
      const next = {
        width: element.clientWidth,
        height: element.clientHeight,
        fontSize: parseFloat(getComputedStyle(element).fontSize) || 12,
      };
      setSize((previous) =>
        previous.width === next.width &&
        previous.height === next.height &&
        previous.fontSize === next.fontSize
          ? previous
          : next,
      );
    });
    observer.observe(element);
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    const updateMotion = () => setReducedMotion(preference.matches);
    updateMotion();
    preference.addEventListener("change", updateMotion);
    return () => {
      observer.disconnect();
      preference.removeEventListener("change", updateMotion);
      instance.dispose();
      chart.current = null;
    };
  }, []);

  useEffect(() => {
    if (!chart.current || !host.current) return;
    const style = getComputedStyle(host.current);
    const token = (name: string) => style.getPropertyValue(name).trim();
    const text = token("--text-secondary");
    const primary = token("--text-primary");
    const grid = token("--chart-grid");
    const compact = size.width <= 520;
    const fontSize = Math.min(14, Math.max(11, size.fontSize));
    const tooltip = {
      renderMode: "richText",
      confine: true,
      backgroundColor: token("--surface-elevated"),
      borderColor: token("--border"),
      textStyle: {
        color: primary,
        fontFamily: "Inter, system-ui, sans-serif",
        fontSize,
      },
      padding: 12,
    };
    const valueAxis = {
      type: "value",
      min: 0,
      minInterval: kind === "seasonality" || mode === "share" ? undefined : 1,
      splitNumber: Math.max(
        2,
        Math.min(5, Math.floor((size.height - 65) / 44)),
      ),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: text, fontSize, hideOverlap: true },
      splitLine: { lineStyle: { color: grid, type: "dashed" } },
    };
    const categoryAxis = {
      type: "category",
      axisLine: { lineStyle: { color: grid } },
      axisTick: { show: false },
      axisLabel: { color: text, fontSize, margin: 12, hideOverlap: true },
    };
    const option: EChartsCoreOption = {
      animation: !reducedMotion,
      animationDuration: 200,
      animationDurationUpdate: 200,
      textStyle: { fontFamily: "Inter, system-ui, sans-serif", fontSize },
      aria: { enabled: true, label: { description } },
      grid: {
        left: 12,
        right: compact ? 16 : 28,
        top: 22,
        bottom: 12,
        containLabel: true,
      },
      tooltip,
      xAxis: categoryAxis,
      yAxis: valueAxis,
    };

    if (kind === "trend") {
      Object.assign(option, {
        tooltip: {
          ...tooltip,
          trigger: "axis",
          formatter: (params: unknown) => {
            const row = trend[tooltipIndex(params)];
            const value = row?.[metric];
            return row
              ? `${row.source ? `${row.source} · ` : ""}${row.period}\n${metricLabels[metric]}: ${validValue(value) ? formatCount(value) : "Unavailable"}`
              : "";
          },
        },
        xAxis: {
          ...categoryAxis,
          data: trend.map((row) => row.period),
          boundaryGap: trend.length === 1,
        },
        series: [
          {
            name: metricLabels[metric],
            type: "line",
            data: trend.map((row) =>
              validValue(row[metric]) ? row[metric] : null,
            ),
            smooth: false,
            connectNulls: false,
            symbol: "circle",
            symbolSize: trend.length > 24 ? 3 : 7,
            showSymbol: true,
            triggerLineEvent: false,
            cursor:
              onSelectPeriod && granularity === "monthly"
                ? "pointer"
                : "default",
            lineStyle: { color: token("--chart-trend"), width: 2 },
            itemStyle: { color: token("--chart-trend") },
            areaStyle: {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: token("--chart-area") },
                { offset: 1, color: "transparent" },
              ]),
            },
            emphasis: { focus: "none", scale: 1.4 },
          },
        ],
      });
    } else if (kind === "seasonality") {
      const maximum = Math.max(...monthly.map((month) => month.value ?? 0));
      Object.assign(option, {
        tooltip: {
          ...tooltip,
          trigger: "axis",
          axisPointer: { type: "shadow" },
          formatter: (params: unknown) => {
            const month = monthly[tooltipIndex(params)];
            return month
              ? `${month.label}\nMean ${metricLabels[metric].toLowerCase()}: ${month.value === null ? "Unavailable" : formatMean(month.value)}\nObserved years: ${month.years.join(", ") || "None"}\nObserved months: ${month.observations}\nDescriptive monthly average; not established seasonality.`
              : "";
          },
        },
        xAxis: {
          ...categoryAxis,
          data: months,
          axisLabel: {
            color: text,
            fontSize: compact ? 11 : fontSize,
            interval: 0,
            hideOverlap: false,
            margin: 12,
          },
        },
        series: [
          {
            name: `Mean ${metricLabels[metric].toLowerCase()}`,
            type: "bar",
            barMaxWidth: compact ? 22 : 32,
            data: monthly.map((month) => ({
              value: month.value,
              itemStyle: {
                color:
                  month.value !== null && month.value === maximum && maximum > 0
                    ? token("--coral")
                    : token("--chart-neutral"),
                borderRadius: [3, 3, 0, 0],
              },
            })),
            emphasis: { focus: "none" },
          },
        ],
      });
    } else {
      Object.assign(option, {
        grid: {
          left: (size.width < 400 ? 98 : compact ? 132 : 164) + 20,
          right: mode === "share" ? 58 : 66,
          top: 8,
          bottom: 36,
          containLabel: false,
        },
        tooltip: {
          ...tooltip,
          trigger: "item",
          axisPointer: { show: false, type: "none" },
          formatter: (params: unknown) => {
            const row = severityData[tooltipIndex(params)];
            return row
              ? `${row.source ? `${row.source} · ` : ""}${row.label}\nCrashes: ${validValue(row.count) ? formatCount(row.count) : "Unavailable"}\nShare within source: ${row.share === null ? "Unavailable" : formatShare(row.share)}${row.definition ? `\n${row.definition}` : ""}`
              : "";
          },
        },
        xAxis: {
          ...valueAxis,
          max: mode === "share" ? 100 : undefined,
          axisPointer: { show: false },
          axisLabel: {
            color: text,
            fontSize,
            hideOverlap: true,
            formatter: (value: number) =>
              mode === "share" ? `${value}%` : formatCount(value),
          },
        },
        yAxis: {
          type: "category",
          inverse: true,
          data: severityData.map(
            (row) =>
              `${multipleSeveritySources && row.source ? `${row.source} · ` : ""}${row.label}`,
          ),
          axisLine: { show: false },
          axisTick: { show: false },
          axisPointer: { show: false },
          axisLabel: {
            color: primary,
            fontSize,
            interval: 0,
            width: size.width < 400 ? 98 : compact ? 132 : 164,
            overflow: size.width < 400 ? "truncate" : "break",
            align: "right",
            verticalAlign: "middle",
            lineHeight: fontSize + 3,
            margin: 12,
          },
        },
        series: [
          {
            name: mode === "share" ? "Share within source" : "Crashes",
            type: "bar",
            barMaxWidth: 20,
            emphasis: { focus: "none" },
            data: severityData.map((row) => ({
              value:
                mode === "share"
                  ? row.share
                  : validValue(row.count)
                    ? row.count
                    : null,
              itemStyle: {
                color: /^(fatal|serious|hospitalisation)/i.test(row.label)
                  ? token("--coral")
                  : token("--chart-neutral"),
                borderRadius: [0, 3, 3, 0],
              },
            })),
            label: {
              show: true,
              position: "right",
              distance: 9,
              color: primary,
              fontSize,
              formatter: (params: unknown) => {
                const row = severityData[tooltipIndex(params)];
                if (!row) return "";
                return mode === "share"
                  ? row.share === null
                    ? "—"
                    : formatShare(row.share)
                  : validValue(row.count)
                    ? formatCount(row.count)
                    : "—";
              },
            },
          },
        ],
      });
    }
    chart.current.setOption(option, { notMerge: true, lazyUpdate: true });
  }, [
    kind,
    trend,
    monthly,
    severityData,
    metric,
    mode,
    granularity,
    theme,
    size,
    reducedMotion,
    description,
    multipleSeveritySources,
    onSelectPeriod,
  ]);

  useEffect(() => {
    const instance = chart.current;
    if (
      !instance ||
      kind !== "trend" ||
      granularity !== "monthly" ||
      !onSelectPeriod
    )
      return;
    const select = (params: unknown) => {
      const row = trend[tooltipIndex(params)];
      if (row && monthlyPeriod.test(row.period)) onSelectPeriod(row.period);
    };
    instance.on("click", { seriesIndex: 0 }, select);
    return () => {
      if (!instance.isDisposed()) instance.off("click", select);
    };
  }, [kind, granularity, trend, onSelectPeriod]);

  return (
    <div
      ref={host}
      className="analytics-chart"
      style={{ width: "100%", height: "100%", minHeight: 0 }}
      role="img"
      tabIndex={0}
      aria-label={description}
      onBlur={() => chart.current?.dispatchAction({ type: "hideTip" })}
      onKeyDown={(event) => {
        if (kind !== "trend" || !trend.length) return;
        if (
          event.key === "ArrowLeft" ||
          event.key === "ArrowRight" ||
          event.key === "Home" ||
          event.key === "End"
        ) {
          event.preventDefault();
          const current = Math.min(keyboardIndex.current, trend.length - 1);
          keyboardIndex.current =
            event.key === "Home"
              ? 0
              : event.key === "End"
                ? trend.length - 1
                : Math.max(
                    0,
                    Math.min(
                      trend.length - 1,
                      current + (event.key === "ArrowRight" ? 1 : -1),
                    ),
                  );
          chart.current?.dispatchAction({
            type: "showTip",
            seriesIndex: 0,
            dataIndex: keyboardIndex.current,
          });
        } else if (
          (event.key === "Enter" || event.key === " ") &&
          granularity === "monthly" &&
          onSelectPeriod
        ) {
          const row = trend[Math.min(keyboardIndex.current, trend.length - 1)];
          if (row && monthlyPeriod.test(row.period)) {
            event.preventDefault();
            onSelectPeriod(row.period);
          }
        } else if (event.key === "Escape") {
          chart.current?.dispatchAction({ type: "hideTip" });
        }
      }}
    />
  );
}
