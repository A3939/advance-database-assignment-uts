"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts/core";
import { BarChart, LineChart, PieChart } from "echarts/charts";
import {
  AriaComponent,
  GridComponent,
  LegendComponent,
  MarkPointComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import { LabelLayout } from "echarts/features";
import type { EChartsCoreOption } from "echarts/core";
import { useTheme } from "@/components/theme-provider";
import type { Severity, Source, TimePoint } from "@/services/contracts";
import { timePointLabel } from "@/services/periods";
import { severityComparison, severityComposition } from "@/services/severity-comparison";
import type { SpeedZoneData } from "@/services/speed-zone";
import { sourceTrend } from "@/services/analytics-insights";

echarts.use([
  LineChart,
  BarChart,
  PieChart,
  GridComponent,
  LegendComponent,
  MarkPointComponent,
  TooltipComponent,
  AriaComponent,
  CanvasRenderer,
  LabelLayout,
]);

type Metric = "crashes" | "fatalCrashes" | "livesLost" | "casualties";
type ChartKind = "trend" | "seasonality" | "severity" | "fatal-outcomes" | "speed-zone";

export type AnalyticsChartPoint = Omit<TimePoint, Metric> &
  Record<Metric, number | null>;

export interface AnalyticsChartProps {
  kind: ChartKind;
  rows: AnalyticsChartPoint[];
  severity?: (Severity & { share?: number | null })[];
  severitySources?: Source[];
  trendSources?: Source[];
  speedZones?: SpeedZoneData;
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
const formatPieShare = (value: number) =>
  value > 0 && value < 0.1 ? "<0.1%" : formatShare(value);
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
  severitySources,
  trendSources,
  speedZones,
  metric = "crashes",
  granularity = "monthly",
  mode = "count",
  onSelectPeriod,
}: AnalyticsChartProps) {
  const { theme } = useTheme();
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<echarts.EChartsType | null>(null);
  const keyboardIndex = useRef(0);
  const piePin = useRef<{key: string; index: number} | null>(null);
  const [size, setSize] = useState({ width: 640, height: 300, fontSize: 12 });
  const [reducedMotion, setReducedMotion] = useState(false);
  const trend = useMemo(
    () => [...rows].sort((a, b) => a.period.localeCompare(b.period)),
    [rows],
  );
  const trendComparison = useMemo(() => sourceTrend(rows, metric, trendSources), [rows, metric, trendSources]);
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
        share: "share" in row ? row.share == null ? null : row.share * 100 : validValue(row.count) && total > 0 ? (row.count / total) * 100 : null,
      };
    });
  }, [severity]);
  const comparison = useMemo(() => severityComparison(severity, severitySources), [severity, severitySources]);
  const composition = useMemo(() => severityComposition(severity, severitySources), [severity, severitySources]);
  const description =
    kind === "speed-zone"
      ? `Fatal crash share within each source and posted speed band, in percent. ${speedZones?.groups.flatMap(group => group.rows.map(row => `${group.source} ${row.band} km/h: ${row.share === null ? "Unavailable" : formatPieShare(row.share)} (${row.fatalCrashes} fatal / ${row.crashes} recorded crashes)`)).join("; ") ?? ""}. Unknown and other speed values are excluded. Source coverage differs; shares are not risk rates. Use left and right arrows or Definitions for values.`
      : kind === "trend"
      ? `${metricLabels[metric]} by ${granularity === "monthly" ? "month" : "year"}. ${trendComparison.series.length > 1 ? `${trendComparison.series.map(group => group.source).join(", ")} on a shared count axis; source observations remain separate. ` : ""}Use left and right arrow keys to inspect values.${onSelectPeriod && granularity === "monthly" ? " Enter selects a month." : ""} Exact values are available through the chart information or View values.`
      : kind === "seasonality"
        ? `Average ${metricLabels[metric].toLowerCase()} for each calendar month across the supplied monthly observations. Missing months are not zero-filled. This descriptive pattern does not establish seasonality. Exact values are available through View values, Monthly average values or Definitions beside this chart.`
        : kind === "fatal-outcomes"
          ? "Grouped columns compare fatal crash events and lives lost (people) by year. The counts are separate, not stacked or added. Asterisks mark selected-month subtotals. Unknown values are not zero-filled. Use left and right arrow keys to inspect a year, or View annual values for exact counts."
          : `${mode === "share" && !comparison.multiple ? "Pie chart shows native severity shares" : `Vertical ${comparison.multiple ? "grouped " : ""}columns show severity ${mode === "share" ? "shares within each source" : "crash counts"}`}. ${severityData.map(row => `${row.source ? `${row.source} · ` : ""}${row.label}: ${mode === "share" ? row.share == null ? "Unavailable" : formatPieShare(row.share) : formatCount(row.count)}`).join("; ")}. Original categories and definitions remain source-specific. N/A means no corresponding observation, not zero. Exact values and source definitions are available through Definitions.`;

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
    const isSinglePie = kind === "severity" && mode === "share" && !comparison.multiple;
    const pieKey = JSON.stringify(severity);
    if (!isSinglePie || piePin.current?.key !== pieKey) piePin.current = null;
    let bindPieInteraction: ((instance: echarts.EChartsType) => () => void) | undefined;
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
      const multiple = trendComparison.series.length > 1;
      const colors = [token("--chart-trend"), token("--coral"), token("--chart-blue")];
      Object.assign(option, {
        ...(multiple ? {
          grid: { left: 12, right: compact ? 16 : 28, top: 50, bottom: 12, containLabel: true },
          legend: { top: 5, left: compact ? 35 : 52, icon: "circle", itemWidth: 7, itemHeight: 7,
            textStyle: { color: text, fontSize }, selectedMode: false },
        } : {}),
        tooltip: {
          ...tooltip,
          trigger: "axis",
          formatter: (params: unknown) => {
            const index = tooltipIndex(params);
            const period = trendComparison.periods[index];
            if (!period) return "";
            const row = trendComparison.series.find(group => group.points[index])?.points[index];
            return [row ? timePointLabel(row) : period, ...trendComparison.series.map(group => {
              const value = group.values[index];
              return `${multiple ? group.source : metricLabels[metric]}: ${validValue(value) ? formatCount(value) : "Unavailable"}`;
            })].join("\n");
          },
        },
        xAxis: {
          ...categoryAxis,
          data: trendComparison.periods.map((period, index) => `${period}${trendComparison.series.some(group => group.points[index]?.fullYear === false) ? "*" : ""}`),
          boundaryGap: multiple || trendComparison.periods.length === 1,
        },
        series: trendComparison.series.map((group, index) => ({
            id: group.source || "selected",
            name: multiple ? group.source : metricLabels[metric],
            type: "line",
            data: group.values,
            smooth: false,
            connectNulls: false,
            symbol: "circle",
            symbolSize: trendComparison.periods.length > 24 ? (multiple ? 4 : 3) : 7,
            showSymbol: true,
            triggerLineEvent: false,
            cursor:
              onSelectPeriod && granularity === "monthly"
                ? "pointer"
                : "default",
            lineStyle: { color: colors[index % colors.length], width: 2 },
            itemStyle: { color: colors[index % colors.length] },
            areaStyle: multiple ? undefined : {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: token("--chart-area") },
                { offset: 1, color: "transparent" },
              ]),
            },
            emphasis: { focus: multiple ? "series" : "none", scale: 1.4 },
          })),
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
    } else if (kind === "speed-zone") {
      const colors: Record<Source, string> = {NSW:token("--coral"), VIC:token("--severity-other"), QLD:token("--chart-trend")};
      const bands = speedZones?.bands ?? [], groups = speedZones?.groups ?? [];
      Object.assign(option, {
        grid:{left:12, right:16, top:64, bottom:48, containLabel:true},
        legend:{top:8, left:12, icon:"circle", itemWidth:10, itemHeight:10, itemGap:22, selectedMode:false, data:groups.map(g=>g.source), textStyle:{color:text,fontSize}},
        tooltip:{...tooltip, trigger:"axis", axisPointer:{type:"shadow"}, formatter:(params:unknown) => {
          const band = bands[tooltipIndex(params)];
          if (!band) return "";
          return [`${band.label} km/h`, ...groups.map(group => {
            const row = group.rows.find(row => row.band === band.id);
            return `${group.source}: ${row?.share == null ? "N/A" : formatPieShare(row.share)}${row ? ` (${formatCount(row.fatalCrashes)} / ${formatCount(row.crashes)})` : ""}`;
          })].join("\n");
        }},
        xAxis:{...categoryAxis, data:bands.map(b=>b.label), name:"Posted speed limit (km/h)", nameLocation:"middle", nameGap:34, nameTextStyle:{color:text,fontSize:11}, axisLabel:{color:text,fontSize:compact?10:fontSize,interval:0,margin:12}},
        yAxis:{...valueAxis,minInterval:undefined,axisLabel:{color:text,fontSize,formatter:(n:number)=>formatShare(n)}},
        series:groups.map(group=>({name:group.source,type:"bar",barMaxWidth:28,barGap:"18%",barCategoryGap:"28%",emphasis:{focus:"series"},itemStyle:{color:colors[group.source],borderRadius:[3,3,0,0]},
          data:bands.map(band=>group.rows.find(row=>row.band===band.id)?.share ?? null),
          markPoint:{symbol:"circle",symbolSize:1,itemStyle:{color:"transparent"},label:{show:true,formatter:"N/A",position:"top",color:text,fontSize:9},
            data:bands.flatMap(band=>group.rows.find(row=>row.band===band.id)?.share == null ? [{coord:[band.label,0],symbolOffset:[(groups.indexOf(group)-(groups.length-1)/2)*12,0]}] : [])},
        })),
      });
    } else if (kind === "fatal-outcomes") {
      Object.assign(option, {
        grid: { left: 12, right: 16, top: 48, bottom: 12, containLabel: true },
        legend: {
          top: 4, left: "center", itemWidth: 12, itemHeight: 8, itemGap: 18,
          selectedMode: false,
          textStyle: { color: text, fontFamily: "Inter, system-ui, sans-serif", fontSize },
          data: ["Fatal crashes (events)", "Lives lost (people)"],
        },
        tooltip: {
          ...tooltip, trigger: "axis", axisPointer: { type: "shadow" },
          formatter: (params: unknown) => {
            const row = trend[tooltipIndex(params)];
            return row ? `${timePointLabel(row)}\nFatal crashes (events): ${validValue(row.fatalCrashes) ? formatCount(row.fatalCrashes) : "Unavailable"}\nLives lost (people): ${validValue(row.livesLost) ? formatCount(row.livesLost) : "Unavailable"}` : "";
          },
        },
        xAxis: { ...categoryAxis, data: trend.map(row => `${row.period}${row.fullYear === false ? "*" : ""}`), axisLabel: { color: text, fontSize, interval: 0, margin: 12 } },
        series: ([
          { metric: "fatalCrashes", name: "Fatal crashes (events)", color: token("--coral") },
          { metric: "livesLost", name: "Lives lost (people)", color: token("--chart-trend") },
        ] as const).map(item => ({
          name: item.name, type: "bar", barMaxWidth: compact ? 20 : 28,
          data: trend.map(row => validValue(row[item.metric]) ? row[item.metric] : null),
          itemStyle: { color: item.color, borderRadius: [3, 3, 0, 0] },
          emphasis: { focus: "series" },
        })),
      });
    } else if (kind === "severity" && mode === "share" && !comparison.multiple) {
      delete option.grid;
      delete option.xAxis;
      delete option.yAxis;
      const native = composition[0];
      const pieRows = (native?.segments ?? []).map(row => ({label:row.label, count:row.count as number | null, share:row.share, tone:row.tone}));
      // Retain the same supplied shares and unknown remainder as the All view.
      // A partial composition must not inflate known categories to 100%.
      if (native?.unclassifiedShare != null && native.unclassifiedShare > 1e-8) {
        pieRows.push({label:"Unclassified / unavailable", count:null, share:native.unclassifiedShare, tone:5});
      }
      const stacked = size.width < 420;
      const nameWidth = stacked ? 112 : 154;
      const legendColumns = Math.max(1, Math.floor((size.width - 24) / (nameWidth + 28)));
      const legendRows = Math.ceil(pieRows.length / legendColumns);
      const pieHeight = stacked ? Math.max(80, size.height - legendRows * 48 - 16) : size.height;
      const pieWidth = stacked ? size.width : Math.max(80, size.width - nameWidth - 58);
      const radius = Math.max(20, Math.min(pieWidth / 2 - 16, pieHeight / 2 - 12));
      const calloutFontSize = stacked ? 10 : 11;
      const calloutText = (index:number) => {
        const row = pieRows[index];
        return row ? `${row.share == null ? "Unavailable" : formatPieShare(row.share)}\n${row.count == null ? "Count unavailable" : `${formatCount(row.count)} crashes`}` : "";
      };
      const colors = ["--coral", "--severity-serious", "--severity-moderate", "--severity-other", "--severity-non-injury", "--chart-neutral"].map(token);
      Object.assign(option, {
        legend: {
          orient: stacked ? "horizontal" : "vertical",
          ...(stacked ? {left:"center", bottom:8, width:size.width - 24} : {right:12, top:"center"}),
          selectedMode:false, itemWidth:10, itemHeight:10, itemGap:16, icon:"circle",
          data:pieRows.map(row => row.label),
          formatter:(name:string) => {
            const row = pieRows.find(row => row.label === name);
            return `{name|${name}}\n{share|${row?.share == null ? "Unavailable" : formatPieShare(row.share)}}`;
          },
          textStyle:{rich:{
            name:{width:nameWidth, color:text, fontSize, lineHeight:18, overflow:"break"},
            share:{width:nameWidth, color:primary, fontSize, fontWeight:600, lineHeight:18},
          }},
        },
        tooltip:{show:false},
        series:[{
          id:"native-severity-share", name:"Share within source", type:"pie", center:[pieWidth / 2, pieHeight / 2],
          left:0, top:0, width:pieWidth, height:pieHeight,
          radius,
          stillShowZeroSum:false, legendHoverLink:false, animationDurationUpdate:0,
          label:{show:false, position:"outside", color:primary, fontSize:calloutFontSize, lineHeight:16,
            alignTo:"edge", edgeDistance:4, bleedMargin:4, overflow:"none",
            formatter:(params:unknown) => calloutText(tooltipIndex(params))},
          labelLayout:(params:{dataIndex?:number}) => {
            const index = params.dataIndex ?? 0;
            const total = pieRows.reduce((sum,row) => sum + (row.share ?? 0),0) || 100;
            const before = pieRows.slice(0,index).reduce((sum,row) => sum + (row.share ?? 0),0);
            const angle = (before + (pieRows[index]?.share ?? 0) / 2) / total * Math.PI * 2 - Math.PI / 2;
            const cos = Math.cos(angle), sin = Math.sin(angle), right = cos >= 0;
            const cx = pieWidth / 2, cy = pieHeight / 2;
            const width = Math.ceil(echarts.format.getTextRect(calloutText(index), `${calloutFontSize}px Inter, system-ui, sans-serif`).width) + 2;
            const x = right ? pieWidth - 4 : 4;
            const dx = Math.max(0, right ? x - width - cx : cx - x - width);
            // Keep the complete two-line caption outside the circle and inside
            // its allotted area, including tiny top slices and narrow screens.
            const clearance = Math.sqrt(Math.max(0, (radius + 2) ** 2 - dx ** 2));
            const distance = Math.max(Math.abs(sin * (radius + 12)), clearance + 16);
            const y = Math.max(18, Math.min(pieHeight - 18, cy + (sin < 0 ? -distance : distance)));
            return {x,y,width,height:32,fontSize:calloutFontSize,align:right ? "right" : "left",verticalAlign:"middle",hideOverlap:false,
              labelLinePoints:[
                [cx + cos * radius,cy + sin * radius],
                [cx + cos * (radius + 12),cy + sin * (radius + 12)],
                [right ? x - width - 4 : x + width + 4,y],
              ]};
          },
          labelLine:{show:false, length:12, length2:12, lineStyle:{width:1}},
          itemStyle:{borderColor:token("--surface"), borderWidth:2},
          // Hover and pin share one controlled state, so another pointer target
          // cannot override a pinned slice through ECharts' automatic emphasis.
          emphasis:{disabled:true},
          data:pieRows.map(row => ({name:row.label, value:native?.available ? row.share : null, itemStyle:{color:colors[row.tone]}})),
        }],
      });
      bindPieInteraction = instance => {
        const element = host.current!;
        let active: number | null | undefined;
        const paint = (index: number | null) => {
          const row = index == null ? null : pieRows[index];
          element.setAttribute("aria-description", row
            ? `${piePin.current ? "Pinned" : "Highlighted"}: ${row.label}, ${row.share == null ? "share unavailable" : formatPieShare(row.share)}, ${row.count == null ? "count unavailable" : `${formatCount(row.count)} crashes`}. Click blank space or press Escape to clear.`
            : "Hover a slice to inspect its share and count. Click to pin; click blank space or press Escape to clear.");
          if (active === index) return;
          active = index;
          instance.setOption({series:[{id:"native-severity-share", data:pieRows.map((item, i) => ({
            name:item.label, value:native?.available ? item.share : null,
            itemStyle:{color:colors[item.tone], opacity:index == null || i === index ? 1 : .2},
            label:{show:i === index}, labelLine:{show:i === index},
          }))}]});
        };
        const over = (params:unknown) => {
          const index = tooltipIndex(params);
          if (!piePin.current && pieRows[index]?.share != null) paint(index);
        };
        const leave = () => {if (!piePin.current) paint(null);};
        const pin = (params:unknown) => {
          const index = tooltipIndex(params);
          if (!piePin.current && pieRows[index]?.share != null) {
            piePin.current = {key:pieKey, index};
            paint(index);
          }
        };
        const clear = () => {piePin.current = null; paint(null);};
        const blank = (event:{target?:unknown}) => {if (!event.target) clear();};
        const outside = (event:PointerEvent) => {
          if (piePin.current && event.target instanceof Element && !element.contains(event.target) &&
            !event.target.closest("button, a, input, select, textarea, [role=button]")) clear();
        };
        const escape = (event:KeyboardEvent) => {if (event.key === "Escape") clear();};
        instance.on("mouseover", {seriesIndex:0}, over);
        instance.on("mouseout", {seriesIndex:0}, leave);
        instance.on("globalout", leave);
        instance.on("click", {seriesIndex:0}, pin);
        instance.getZr().on("click", blank);
        document.addEventListener("pointerdown", outside);
        document.addEventListener("keydown", escape);
        paint(piePin.current?.index ?? null);
        return () => {
          document.removeEventListener("pointerdown", outside);
          document.removeEventListener("keydown", escape);
          element.removeAttribute("aria-description");
          if (!instance.isDisposed()) {
            instance.off("mouseover", over); instance.off("mouseout", leave);
            instance.off("globalout", leave); instance.off("click", pin);
            instance.getZr().off("click", blank);
          }
        };
      };
    } else {
      const sourceColors = [token("--coral"), token("--severity-other"), token("--chart-trend")];
      const nativeColor = (label: string) => /^fatal/i.test(label) ? token("--coral")
        : /serious|hospitalisation/i.test(label) ? token("--severity-serious")
        : /moderate|medical/i.test(label) ? token("--severity-moderate")
        : /non-casualty|non-injury|towaway/i.test(label) ? token("--severity-non-injury")
        : token("--severity-other");
      Object.assign(option, {
        grid: {left: 12, right: 14, top: comparison.multiple ? 65 : 32, bottom: 12, containLabel: true},
        legend: comparison.multiple ? {
          top: 8, left: 12, icon: "circle", itemWidth: 10, itemHeight: 10,
          itemGap: 24, selectedMode: false,
          data: comparison.sources, textStyle: {color: text, fontSize},
        } : {show: false},
        tooltip: {
          ...tooltip, trigger: "axis", axisPointer: {type: "shadow"},
          formatter: (params: unknown) => {
            const index = tooltipIndex(params);
            const group = comparison.groups[index];
            if (!group) return "";
            return [group.label.replace(/\n/g, " "), ...comparison.series.map(series => {
              const value = (mode === "share" ? series.shares : series.counts)[index];
              return `${series.source ? `${series.source}: ` : ""}${value == null ? "N/A" : mode === "share" ? formatPieShare(value) : `${formatCount(value)} crashes`}`;
            })].join("\n");
          },
        },
        xAxis: {
          ...categoryAxis, data: comparison.groups.map(group => group.label),
          axisLabel: {color: text, fontSize: compact ? 10 : fontSize, interval: 0,
            width: Math.max(55, (size.width - 65) / Math.max(1, comparison.groups.length) - 8),
            overflow: "break", lineHeight: 15, margin: 12, hideOverlap: false},
        },
        yAxis: {
          ...valueAxis, max: mode === "share" ? 100 : undefined,
          axisLabel: {color: text, fontSize, hideOverlap: true,
            formatter: (value: number) => mode === "share" ? formatShare(value) : value >= 1000 ? `${value / 1000}k` : formatCount(value)},
        },
        series: comparison.series.map((series, index) => ({
          name: series.source ?? "Selected source", type: "bar", barMaxWidth: comparison.multiple ? 30 : 54,
          barGap: "22%", barCategoryGap: "28%", emphasis: {focus: "series"},
          itemStyle: {color: sourceColors[index % sourceColors.length], borderRadius: [3, 3, 0, 0]},
          data: comparison.groups.map((group, rowIndex) => ({
            value: (mode === "share" ? series.shares : series.counts)[rowIndex],
            itemStyle: {color: comparison.multiple ? sourceColors[index % sourceColors.length] : nativeColor(group.label)},
          })),
          label: {
            show: !compact || !comparison.multiple, position: "top", distance: 6, color: primary,
            fontSize: comparison.multiple ? 10 : fontSize,
            formatter: (params: unknown) => {
              const value = (mode === "share" ? series.shares : series.counts)[tooltipIndex(params)];
              return value == null ? "N/A" : mode === "share" ? formatPieShare(value) : formatCount(value);
            },
          },
          // A baseline annotation represents absent observations without drawing
          // a fake zero bar. Actual recorded zero remains a numeric zero above.
          markPoint: {
            symbol: "circle", symbolSize: 1, itemStyle: {color: "transparent"},
            label: {show: true, formatter: "N/A", position: "top", distance: 6, color: text, fontSize: 9},
            data: comparison.groups.flatMap((group, rowIndex) =>
              (mode === "share" ? series.shares : series.counts)[rowIndex] == null
                ? [{coord: [group.label, 0], symbolOffset: [(index - (comparison.series.length - 1) / 2) * (compact ? 14 : 24), 0]}] : []),
          },
        })),
      });
    }
    chart.current.setOption(option, { notMerge: true, lazyUpdate: !isSinglePie });
    return bindPieInteraction?.(chart.current);
  }, [
    kind,
    trend,
    trendComparison,
    monthly,
    severityData,
    metric,
    mode,
    granularity,
    theme,
    size,
    reducedMotion,
    description,
    comparison,
    composition,
    severity,
    speedZones,
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
      const period = trendComparison.periods[tooltipIndex(params)];
      if (period && monthlyPeriod.test(period)) onSelectPeriod(period);
    };
    instance.on("click", { seriesIndex: 0 }, select);
    return () => {
      if (!instance.isDisposed()) instance.off("click", select);
    };
  }, [kind, granularity, trendComparison, onSelectPeriod]);

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
        if (kind === "speed-zone") {
          const length = speedZones?.bands.length ?? 0;
          if (length && ["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
            event.preventDefault();
            keyboardIndex.current = event.key === "Home" ? 0 : event.key === "End" ? length - 1 : Math.max(0, Math.min(length - 1, keyboardIndex.current + (event.key === "ArrowRight" ? 1 : -1)));
            chart.current?.dispatchAction({type:"showTip",seriesIndex:0,dataIndex:keyboardIndex.current});
          } else if (event.key === "Escape") chart.current?.dispatchAction({type:"hideTip"});
          return;
        }
        const periods = kind === "trend" ? trendComparison.periods : trend.map(row => row.period);
        if ((kind !== "trend" && kind !== "fatal-outcomes") || !periods.length) return;
        if (
          event.key === "ArrowLeft" ||
          event.key === "ArrowRight" ||
          event.key === "Home" ||
          event.key === "End"
        ) {
          event.preventDefault();
          const current = Math.min(keyboardIndex.current, periods.length - 1);
          keyboardIndex.current =
            event.key === "Home"
              ? 0
              : event.key === "End"
                ? periods.length - 1
                : Math.max(
                    0,
                    Math.min(
                      periods.length - 1,
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
          const period = periods[Math.min(keyboardIndex.current, periods.length - 1)];
          if (period && monthlyPeriod.test(period)) {
            event.preventDefault();
            onSelectPeriod(period);
          }
        } else if (event.key === "Escape") {
          chart.current?.dispatchAction({ type: "hideTip" });
        }
      }}
    />
  );
}
