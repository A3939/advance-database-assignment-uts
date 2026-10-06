"use client";
import { LOCAL_DATE_BOUNDS } from "@/services/date-range";

import { monthRangeLabel, timePointLabel } from "@/services/periods";
import { wholeMonthRange } from "@/services/date-range";
import { sourceCoverage, coverageMonthRange } from "@/services/catalog-contracts";
import { regionsForSource } from "@/services/regions";
import {
  useEffect,
  useCallback,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
} from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import AnalyticsSeverity from "./analytics-severity";
import AnalyticsSpatial from "./analytics-spatial";
import AnalyticsAllSources from "./analytics-all-sources";
import AnalyticsMetricCard from "./analytics-metric-card";
import MapAreaSearch from "./map-area-search";
import { arsia } from "@/services";
import { monthlyInsights } from "@/services/analytics-insights";
import {
  ArrowDownRight,
  ArrowUpRight,
  ArrowUpDown,
  CalendarDays,
  CarFront,
  ChevronLeft,
  ChevronRight,
  Download,
  Info,
  Heart,
  RotateCcw,
  Sparkles,
  Siren,
  TrendingUp,
  Users,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useWorkspace } from "@/components/workspace";
import { getAnalytics } from "@/services/analytics";
import { IS_DEMO, selectSource } from "@/services/config";
import type { Filters, TimePoint, MapData, Response, SourceSelection } from "@/services/contracts";
import styles from "./analytics.module.css";

const Chart = dynamic(() => import("@/components/analytics-chart"), {
  ssr: false,
  loading: () => (
    <div className={styles.chartLoading} role="status">
      Loading chart…
    </div>
  ),
});
const MONTHS = [
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
const METRICS = {
  crashes: "Crashes",
  fatalCrashes: "Fatal crashes",
  livesLost: "Lives lost",
  casualties: "Casualties",
} as const;
const METRIC_ICONS = { crashes: CarFront, fatalCrashes: Siren, livesLost: Heart, casualties: Users };
type MetricKey = keyof typeof METRICS;
type Bundle = Awaited<ReturnType<typeof getAnalytics>>;
const number = (value: number | null | undefined, decimals = 0) =>
  value == null
    ? "—"
    : value.toLocaleString("en-AU", { maximumFractionDigits: decimals });
const percentage = (value: number | null | undefined) =>
  value == null ? "—" : `${value > 0 ? "+" : ""}${value.toFixed(1)}%`;
const monthLabel = (period: string) =>
  `${MONTHS[Number(period.slice(5, 7)) - 1]} ${period.slice(0, 4)}`;
const monthEnd = (month: string) =>
  new Date(Date.UTC(Number(month.slice(0, 4)), Number(month.slice(5, 7)), 0))
    .toISOString()
    .slice(0, 10);
const filterKey = (filters: Filters) => JSON.stringify(filters);

export default function Analytics({ dashboard = "trends" }: { dashboard?: "trends" | "severity" | "spatial" }) {
  const { filters, catalog, setFilters, showEvidence, askAI, notify, view, setView, analysisHref } = useWorkspace();
  const actualFilters = filters;
  const areaOptions = useMemo(() => [{id:"", name:"All areas"}, ...catalog.sources.filter(item => filters.source === "All" || item.source === filters.source).flatMap(item => regionsForSource(item.source).map(region => ({ ...region, name: filters.source === "All" ? `${region.name} (${item.source})` : region.name, source:item.source }))).sort((a,b) => a.name.localeCompare(b.name))], [filters.source, catalog.sources]);
  const [result, setResult] = useState<{ key: string; bundle: Bundle; all: Bundle[]; map: Response<MapData> | null; sourceMaps: { source: SourceSelection; response: Response<MapData> }[] } | null>(
    null,
  );
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const { metric } = view;
  const setMetric = (metric: MetricKey) => setView({ ...view, metric });
  const setGranularity = (granularity: "monthly" | "yearly") => setView({ ...view, granularity });
  const [focusedCell, setFocusedCell] = useState(0);
  const [dateOpen, setDateOpen] = useState(false);
  const [draftFrom, setDraftFrom] = useState("");
  const [draftTo, setDraftTo] = useState("");
  const [selection, setSelection] = useState<{
    key: string;
    period: string;
  } | null>(null);
  const [tableGranularity, setTableGranularity] = useState<
    "yearly" | "monthly"
  >("yearly");
  const [sort, setSort] = useState<{
    key: keyof TimePoint;
    ascending: boolean;
  }>({ key: "period", ascending: false });
  const [page, setPage] = useState(1);
  const heatmap = useRef<HTMLDivElement>(null);
  const key = `${dashboard}:${filterKey(actualFilters)}`;
  const loading = result?.key !== key;
  // Never display an old source underneath new filters while a provider resolves.
  const bundle = result?.key === key ? result.bundle : null;
  const data = bundle?.data;
  const granularity = data?.monthlyAvailability === "unsupported" ? "yearly" : view.granularity;
  const isDemo = bundle?.meta.demo ?? IS_DEMO;
  const coverage = bundle?.meta.coverage ?? sourceCoverage(catalog,actualFilters.source);
  const coverageLabel = `${coverage.from.slice(0, 4)}–${coverage.to.slice(0, 4)}`;
  const selected = selection?.key === key ? selection.period : null;
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const sourceFilters = actualFilters.source === "All" ? catalog.sources.map(item => selectSource(actualFilters, item.source)) : [actualFilters];
    Promise.all([
      Promise.all(sourceFilters.map(selected => getAnalytics(selected, undefined, controller.signal))),
      dashboard === "spatial" ? arsia.getMapData(actualFilters, controller.signal) : Promise.resolve(null),
      dashboard === "spatial" && actualFilters.source === "All"
        ? Promise.all(sourceFilters.map(async selected => ({ source: selected.source, response: await arsia.getMapData(selected, controller.signal) })))
        : Promise.resolve([]),
    ])
      .then(([all, map, sourceMaps]) => {
        const bundle = all[0];
        if (!bundle) throw Error("No sources are available.");
        if (!active) return;
        setResult({ key, bundle, all, map, sourceMaps });
        setError("");
      })
      .catch(() => {
        if (active)
          setError("This analysis could not be loaded. Please try again.");
      });
    return () => {
      active = false; controller.abort();
    };
  }, [actualFilters, retry, dashboard, key, catalog.sources]);

  const monthly: TimePoint[] = useMemo(
    () =>
      data?.monthly
        .filter((row) => row.availability === "available")
        .map((row) => ({
          period: row.period,
          crashes: row.crashes,
          fatalCrashes: row.fatalCrashes,
          livesLost: row.livesLost,
          casualties: row.casualties,
        })) ?? [],
    [data],
  );
  const yearly = data?.timeSeriesYearly ?? [];
  const trendRows = useMemo(
    () =>
      granularity === "monthly"
        ? (data?.monthly ?? [])
        : (data?.yearly.map((row) => ({
            period: row.fullYear
              ? String(row.year)
              : `${row.year}\n${MONTHS[row.comparisonMonths[0] - 1]}–${MONTHS[row.comparisonMonths.at(-1)! - 1]}`,
            crashes: row.crashes,
            fatalCrashes: row.fatalCrashes,
            livesLost: row.livesLost,
            casualties: row.casualties,
          })) ?? []),
    [data, granularity],
  );

  const years = [...new Set(data?.monthly.map((row) => row.year) ?? [])];
  const selectedMonth = data?.monthly.find((row) => row.period === selected);
  const latest = data?.yearly.at(-1);
  const comparison = latest?.comparisons[metric];
  const singleMonth = data?.monthly.length === 1;
  const total = data?.overview[metric].value;
  const insights = monthlyInsights(monthly, metric);
  const knownCrashCounts = monthly.flatMap(row => row[metric] === null ? [] : [row[metric]!]);
  const monthlyAverage = insights.average;
  const maxCell = Math.max(...knownCrashCounts, 1);
  const minCell = Math.min(...knownCrashCounts, maxCell);
  const tableRows = useMemo(() => {
    const rows =
      tableGranularity === "yearly" ? (data?.timeSeriesYearly ?? []) : monthly;
    return [...rows].sort((a, b) => {
      const first = a[sort.key],
        second = b[sort.key];
      if (first == null || second == null)
        return first == null ? (second == null ? 0 : 1) : -1;
      const comparison =
        typeof first === "number" && typeof second === "number"
          ? first - second
          : String(first).localeCompare(String(second));
      return sort.ascending ? comparison : -comparison;
    });
  }, [data, monthly, sort, tableGranularity]);
  const totalPages = Math.max(1, Math.ceil(tableRows.length / 8));
  const currentPage = Math.min(page, totalPages);
  const visibleRows = tableRows.slice((currentPage - 1) * 8, currentPage * 8);
  const isEmpty = !loading && monthly.length === 0 && yearly.length === 0;
  const dateLabel = monthRangeLabel(actualFilters);
  const dateBounds = catalog.mode === "local" ? LOCAL_DATE_BOUNDS : {min:"2019-01",max:"2026-12"};
  const availableRange = sourceCoverage(catalog, filters.source);
  const draftPeriod = wholeMonthRange(draftFrom, draftTo, dateBounds);
  function changeFilters(next: Filters) {
    setError("");
    setPage(1);
    setSelection(null);
    setFilters(next);
  }
  function resetDates() {
    changeFilters({
      ...actualFilters,
      dateRange: coverageMonthRange(sourceCoverage(catalog,actualFilters.source)),
    });
  }
  const inspect = useCallback(
    (period: string) => {
      setSelection({ key, period });
    },
    [key],
  );
  function evidence(
    title: string,
    description: string,
    rows?: { label: string; value: string }[],
  ) {
    showEvidence({ title, description, rows: [{ label: "Selected period", value: monthRangeLabel(actualFilters) }, { label: "Source / LGA", value: `${actualFilters.source}${actualFilters.regionId ? ` · ${actualFilters.regionId}` : ""}` }, { label: actualFilters.releaseId ? "Release / version" : "Batch / version", value: `${actualFilters.batchId} / ${actualFilters.datasetVersion}` }, ...(rows || [])], evidence: bundle?.meta.evidence });
  }
  function exportData() {
    if (!bundle) return;
    const payload = {
      demo: bundle.meta.demo,
      exportedAt: new Date().toISOString(),
      filters: actualFilters,
      view: { metric, granularity, dashboard },
      spatial: result?.map ?? undefined,
      spatialBySource: actualFilters.source === "All" && dashboard === "spatial" ? result?.sourceMaps : undefined,
      analysis: actualFilters.source === "All" ? undefined : bundle,
      analyses: actualFilters.source === "All" ? result?.all : undefined,
      note: `${bundle.data.notes.join(" ")} Aggregate values only; no underlying crash records.`,
    };
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(payload, null, 2)], {
        type: "application/json",
      }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `ARSIA-${isDemo ? "DEMO" : "OFFICIAL"}-Analytics-${actualFilters.source}-${actualFilters.dateRange.from}-${actualFilters.dateRange.to}.json`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    notify(
      "Analysis exported with filters, comparison periods and definitions.",
    );
  }
  function keyboardCell(
    event: KeyboardEvent<HTMLButtonElement>,
    index: number,
  ) {
    const delta = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -12, ArrowDown: 12 }[
      event.key
    ];
    const buttons =
      heatmap.current?.querySelectorAll<HTMLButtonElement>(
        "button[data-month]",
      );
    if (delta != null && buttons?.length) {
      event.preventDefault();
      const next = Math.min(Math.max(0, index + delta), buttons.length - 1);
      setFocusedCell(next); buttons[next]?.focus();
    }
  }
  return (
    <div className={styles.page}>
      <nav className={styles.dashboardNav} aria-label="Analytics dashboards">
        <strong>Analytics</strong>
        {([['trends', '/analytics', 'Trends'], ['severity', '/analytics/severity', 'Severity'], ['spatial', '/analytics/spatial', 'Spatial']] as const).map(([id, path, label]) => <Link key={id} href={analysisHref(path)} aria-current={dashboard === id ? "page" : undefined}>{label}</Link>)}
      </nav>
      <div className={styles.toolbar} aria-label="Analytics filters">
        <div className={styles.filters}>
          <div className={styles.sourceGroup} aria-label="Analysis source">
            <span className={styles.areasLabel}>Areas</span>
            {(["All", ...catalog.sources.map(s=>s.source)] as SourceSelection[]).map((source) => (
              <button
                key={source}
                aria-pressed={actualFilters.source === source}
                onClick={() => changeFilters({ ...selectSource(actualFilters, source), ...(catalog.mode === "local" ? {dateRange:coverageMonthRange(sourceCoverage(catalog,source))} : {}) })}
              >
                {source}
              </button>
            ))}
          </div>
          <div className={styles.areaFilter}><div className={styles.areaSearch}><MapAreaSearch direction="down" options={areaOptions} selectedId={actualFilters.regionId} onClear={() => changeFilters({...actualFilters, regionId:undefined})} onSelect={option => {
            const area = areaOptions.find(item => item.id === option.id);
            changeFilters({...selectSource(actualFilters, area && "source" in area ? area.source : actualFilters.source), regionId:option.id || undefined});
          }}/></div></div>
          {actualFilters.regionId && <button className="region-filter-chip" onClick={() => changeFilters({ ...actualFilters, regionId: undefined })} aria-label="Clear LGA filter">
            {regionsForSource(actualFilters.source).find(r => r.id === actualFilters.regionId)?.name} LGA ×
          </button>}
        </div>
        <div className={styles.actions}>
          <Popover
            open={dateOpen}
            onOpenChange={(open) => {
              setDateOpen(open);
              if (open) {
                setDraftFrom(actualFilters.dateRange.from.slice(0, 7));
                setDraftTo(actualFilters.dateRange.to.slice(0, 7));
              }
            }}
          >
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                className="date-trigger"
                aria-label={`Analysis period: ${dateLabel}`}
              >
                <CalendarDays size={16} />
                {dateLabel}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="date-popover" align="end">
              <h3>Analysis period</h3>
              <p>
                Whole months · {isDemo ? "demo" : "snapshot"} coverage{" "}
                {coverageLabel}
              </p>
              <div className="date-inputs">
                <label>
                  From
                  <input
                    type="month"
                    aria-label="Start month"
                    min={dateBounds.min}
                    max={dateBounds.max}
                    value={draftFrom}
                    onChange={(e) => setDraftFrom(e.target.value)}
                  />
                </label>
                <label>
                  To
                  <input
                    type="month"
                    aria-label="End month"
                    min={dateBounds.min}
                    max={dateBounds.max}
                    value={draftTo}
                    onChange={(e) => setDraftTo(e.target.value)}
                  />
                </label>
              </div>
              <div className="date-presets">
                {[
                  [availableRange.from.slice(0,7),availableRange.to.slice(0,7),"Full coverage"],
                  [`${Number(availableRange.to.slice(0,4))-1}-01`,availableRange.to.slice(0,7),`${Number(availableRange.to.slice(0,4))-1}–${availableRange.to.slice(0,4)}`],
                  [`${availableRange.to.slice(0,4)}-01`,availableRange.to.slice(0,7),availableRange.to.slice(0,4)],
                ].map(([from, to, label]) => (
                  <button
                    key={label}
                    onClick={() => {
                      setDraftFrom(from);
                      setDraftTo(to);
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>
              {draftPeriod.error && <p role="alert">{draftPeriod.error}</p>}
              <Button
                className="ask-ai-button"
                disabled={!!draftPeriod.error}
                onClick={() => {
                  if (draftPeriod.error || !draftPeriod.dateRange) return;
                  changeFilters({ ...actualFilters, dateRange: draftPeriod.dateRange });
                  setDateOpen(false);
                }}
              >
                Apply period
              </Button>
            </PopoverContent>
          </Popover>
          <Button
            className={styles.exportButton}
            variant="outline"
            onClick={exportData}
            disabled={loading || !data || isEmpty}
          >
            <Download size={16} />
            Export
          </Button>
          <Button className="ask-ai-button" onClick={askAI}>
            <Sparkles size={17} />
            Ask AI
          </Button>
        </div>
      </div>
      {error ? (
        <div className={styles.empty} role="alert">
          <h2>Analysis unavailable</h2>
          <p>{error}</p>
          <Button
            variant="outline"
            onClick={() => {
              setError("");
              setRetry((n) => n + 1);
            }}
          >
            Try again
          </Button>
        </div>
      ) : actualFilters.source === "All" ? (loading || !result ? <div className={styles.empty} role="status">Loading source comparisons…</div> : <AnalyticsAllSources bundles={result.all} dashboard={dashboard} metric={metric} granularity={view.granularity} map={result.map?.data ?? null} sourceMaps={result.sourceMaps.map(({source, response}) => ({source, data:response.data}))} evidence={evidence} setMetric={setMetric} setGranularity={setGranularity} onSourceSelect={source => changeFilters(selectSource(actualFilters, source))}/>) : isEmpty ? (
        <div className={styles.empty}>
          <CalendarDays size={32} />
          <h2>No data for this selection</h2>
          <p>
            {bundle?.meta.reason ||
              `Choose a period within the ${coverageLabel} coverage.`}
          </p>
          <Button variant="outline" onClick={resetDates}>
            <RotateCcw size={16} />
            Reset dates
          </Button>
        </div>
      ) : dashboard === "severity" ? (data ? <AnalyticsSeverity key={key} data={data} evidence={evidence} resetDates={resetDates}/> : <div className={styles.empty} role="status">Loading severity analysis…</div>) : dashboard === "spatial" ? (data && result?.key === key && result.map ? <AnalyticsSpatial key={key} data={result.map.data} filters={actualFilters} evidence={evidence} onSelect={id => changeFilters({...actualFilters, regionId:id || undefined})} onSourceSelect={source => changeFilters(selectSource(actualFilters, source))}/> : <div className={styles.empty} role="status">Loading spatial analysis…</div>) : (
        <div aria-busy={loading}>
          <div className={styles.firstScreen}>
            <section className={`metric-grid ${styles.allMetrics} ${styles.singleMetrics}`} aria-label="Analysis summary">
              <AnalyticsMetricCard label={METRICS[metric]} value={number(total)} Icon={METRIC_ICONS[metric]} valueTestId="analytics-total" disabled={!bundle} onDefinition={() => evidence(METRICS[metric], data?.overview[metric].definition || "Selected-period source total.", [{label:"Value",value:number(total)}])}/>
              <AnalyticsMetricCard label="Monthly average" value={number(monthlyAverage, 1)} Icon={CalendarDays} disabled={!bundle} onDefinition={() => evidence("Monthly average", "Average over selected months with known counts. Unobserved months are not recorded zeros.", [{label:"Months with known counts",value:number(knownCrashCounts.length)}, {label:"Unit",value:metric === "livesLost" || metric === "casualties" ? "people" : "events"}])}/>
              <AnalyticsMetricCard label="Latest year-on-year change" value={percentage(comparison?.yoyPct)} Icon={TrendingUp} disabled={!bundle} onDefinition={() => evidence("Latest year-on-year change", latest ? `${latest.year} vs ${latest.previousYear} · matching months` : "Matching periods required", [{label:"Change",value:percentage(comparison?.yoyPct)}])}/>
              <AnalyticsMetricCard label="Peak month" value={insights.peak ? monthLabel(insights.peak.period) : "—"} Icon={CalendarDays} compact disabled={!bundle} onDefinition={() => evidence("Peak month", "The selected month with the highest known count for this metric.", [{label:METRICS[metric],value:number(insights.peak?.[metric])}])}/>
            </section>
            {bundle && !bundle.meta.coverage.complete && (
              <div className={styles.coverageNote}>
                <Info size={15} />
                Partial coverage. Unobserved months stay empty; comparisons
                require matching months.
              </div>
            )}
            <section className={styles.trendGrid} aria-label="Time and change">
              <article className={`${styles.card} ${styles.trendCard}`}>
                <div className={styles.cardHeading}>
                  <div>
                    <h2>Trend over time</h2>
                    <p>
                      {METRICS[metric]} ·{" "}
                      {metric === "livesLost" || metric === "casualties"
                        ? "people"
                        : "events"}
                    </p>
                  </div>
                  <div className={styles.segment} aria-label="Trend interval">
                    {(["monthly", "yearly"] as const).map((mode) => (
                      <button
                        key={mode}
                        aria-pressed={mode === granularity}
                        disabled={mode === "monthly" && data?.monthlyAvailability === "unsupported"}
                        onClick={() => setGranularity(mode)}
                      >
                        {mode === "monthly" ? "Monthly" : "Yearly"}
                      </button>
                    ))}
                  </div>
                </div>
                <div className={styles.metricTabs} aria-label="Trend metric">
                  {Object.entries(METRICS).map(([key, label]) => (
                    <button
                      key={key}
                      aria-pressed={metric === key}
                      onClick={() => setMetric(key as MetricKey)}
                    >
                      {label}
                    </button>
                  ))}
                </div>
                <div className={styles.trendChart}>
                  <Chart
                    kind="trend"
                    rows={trendRows}
                    metric={metric}
                    granularity={granularity}
                    onSelectPeriod={inspect}
                  />
                  {loading && (
                    <div className={styles.chartOverlay} role="status">
                      Loading analysis…
                    </div>
                  )}
                  {!loading && !trendRows.some(row => row[metric] !== null) && <div className={styles.chartOverlay} role="status">{data?.overview[metric].availability === "unsupported" ? data.overview[metric].reason || `${METRICS[metric]} is unsupported for this selection.` : `${METRICS[metric]} unavailable for this selection. Unknown observations are not zero.`}</div>}
                </div>
                <div className={styles.cardFoot}>
                  <span>
                    {granularity === "monthly"
                      ? isDemo
                        ? "Monthly values are synthetically allocated."
                        : "Recorded monthly counts · published snapshot."
                      : "Years reflect the selected calendar months."}
                  </span>
                  <button
                    onClick={() =>
                      evidence(
                        "Trend values",
                        isDemo
                          ? "Aggregate demo values for the current metric and interval. Monthly values are synthetic allocations, not observed seasonality."
                          : "Published aggregate values for the selected source, period and metric. Unknown values remain unavailable.",
                        (granularity === "monthly" ? monthly : yearly).map(
                          (row) => ({
                            label: timePointLabel(row),
                            value: number(row[metric]),
                          }),
                        ),
                      )
                    }
                  >
                    View values <ArrowUpRight size={14} />
                  </button>
                </div>
              </article>
              <article className={`${styles.card} ${styles.comparison}`}>
                <div className={styles.cardHeading}>
                  <div>
                    <h2>{METRICS[metric]} year-on-year</h2>
                    <p>
                      {latest
                        ? `${latest.year} vs ${latest.previousYear}`
                        : "Matching calendar months"}
                    </p>
                  </div>
                  <button
                    className={styles.info}
                    aria-label="Year-on-year definition"
                    onClick={() =>
                      evidence(
                        "Year-on-year comparison",
                        `${METRICS[metric]} for the latest selected year is compared with exactly the same months in the previous year. Missing, unknown or zero baseline values leave the percentage unavailable. Unit: ${metric === "crashes" || metric === "fatalCrashes" ? "crash events" : "people"}.`,
                        latest
                          ? [
                              {
                                label: "Current",
                                value: `${latest.year}: ${number(comparison!.current)}`,
                              },
                              {
                                label: "Previous",
                                value: `${latest.previousYear}: ${number(comparison!.previous)}`,
                              },
                              {
                                label: "Status",
                                value:
                                  comparison!.reason ||
                                  "Matching months available",
                              },
                            ]
                          : [],
                      )
                    }
                  >
                    <Info size={15} />
                  </button>
                </div>
                <div className={styles.changeValue}>
                  {comparison?.yoyPct != null &&
                    (comparison.yoyPct < 0 ? <ArrowDownRight /> : <ArrowUpRight />)}
                  <strong>{percentage(comparison?.yoyPct)}</strong>
                </div>
                <p className={styles.changeExplanation}>
                  {comparison?.yoyPct != null &&
                  comparison!.current != null &&
                  comparison!.previous != null
                    ? `${number(Math.abs(comparison!.current - comparison!.previous))} ${comparison!.current < comparison!.previous ? "fewer" : "more"} ${METRICS[metric].toLowerCase()}`
                    : comparison?.reason || "A comparable baseline is unavailable."}
                </p>
                <div className={styles.comparisonBars}>
                  {latest &&
                    [
                      [latest.previousYear, comparison!.previous],
                      [latest.year, comparison!.current],
                    ].map(([year, count], i) => (
                      <div key={year ?? i}>
                        <div>
                          <span>{year}</span>
                          <strong>{number(count)}</strong>
                        </div>
                        <div className={styles.barTrack}>
                          <i
                            style={{
                              width: `${count == null ? 0 : Math.max(0, (count / Math.max(comparison!.current ?? 0, comparison!.previous ?? 0, 1)) * 100)}%`,
                              background: i
                                ? "var(--chart-trend)"
                                : "var(--chart-neutral)",
                            }}
                          />
                        </div>
                      </div>
                    ))}
                </div>
                <div className={styles.comparisonNote}>
                  <CalendarDays size={15} />
                  <span>
                    {latest?.comparisonMonths?.length
                      ? `${MONTHS[latest.comparisonMonths[0] - 1]}–${MONTHS[latest.comparisonMonths.at(-1)! - 1]} · ${latest.comparisonMonths.length} ${comparison?.reason === null ? "matched" : "selected"} months`
                      : "Matching months required"}
                  </span>
                </div>
              </article>
            </section>
          </div>
          {singleMonth ? <section className={`${styles.card} ${styles.singleMonthDetail}`} aria-label="Selected month details"><div className={styles.cardHeading}><div><h2>{monthLabel(data!.monthly[0].period)} details</h2><p>One selected month; a calendar-month pattern requires a wider period.</p></div></div><div className={styles.inspectionValues}>{Object.entries(METRICS).map(([field, label]) => <span key={field}>{label}<b>{number(data!.monthly[0][field as MetricKey])}</b></span>)}</div><div className={styles.cardFoot}><span>Matching-month comparison appears above. Counts are not risk rates.</span></div></section> : <section className={styles.patternGrid} aria-label="Monthly patterns">
            <article className={`${styles.card} ${styles.heatmapCard}`}>
              <div className={styles.cardHeading}>
                <div>
                  <h2>Monthly distribution</h2>
                  <p>{METRICS[metric]} by year and month</p>
                </div>
                <span className={styles.quietLabel}>
                  Arrow keys to move · Enter to inspect
                </span>
              </div>
              <div className={styles.heatmapScroll} ref={heatmap}>
                <table className={styles.heatmap}>
                  <caption className="sr-only">
                    {isDemo ? "Synthetic" : "Published"} {METRICS[metric].toLowerCase()} counts. Arrow
                    keys move between months; Enter inspects a month.
                  </caption>
                  <thead>
                    <tr>
                      <th aria-label="Year" />
                      {MONTHS.map((month) => (
                        <th key={month}>{month}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {years.map((year, yearIndex) => (
                      <tr key={year}>
                        <th scope="row">{year}</th>
                        {MONTHS.map((month, monthIndex) => {
                          const period = `${year}-${String(monthIndex + 1).padStart(2, "0")}`;
                          const row = data?.monthly.find(
                            (r) => r.period === period,
                          );
                          const value = row?.[metric];
                          const status = !row ? "Not in selected period" : row.availability === "no_results" ? "No coverage" : row.availability === "unsupported" ? "Unsupported" : value == null ? "Unknown count" : `${number(value)} ${isDemo ? "demo " : ""}${METRICS[metric].toLowerCase()}`;
                          const cellStatus = !row ? "outside" : row.availability === "no_results" ? "no-coverage" : row.availability === "unsupported" ? "unsupported" : value == null ? "unknown" : value === 0 ? "zero" : "known";
                          const visibleValue = cellStatus === "outside" ? "Out" : cellStatus === "no-coverage" ? "N/C" : cellStatus === "unsupported" ? "N/S" : cellStatus === "unknown" ? "?" : number(value);
                          const intensity =
                            value == null
                              ? 0
                              : Math.ceil(
                                  ((value - minCell) /
                                    Math.max(maxCell - minCell, 1)) *
                                    5,
                                ) + 1;
                          return (
                            <td key={month}>
                              <button
                                data-month={period}
                                data-status={cellStatus}
                                tabIndex={Math.min(focusedCell, years.length * 12 - 1) === yearIndex * 12 + monthIndex ? 0 : -1}
                                onFocus={() => setFocusedCell(yearIndex * 12 + monthIndex)}
                                data-intensity={intensity}
                                aria-pressed={selected === period}
                                aria-label={`${month} ${year}: ${status}`}
                                title={`${month} ${year}: ${status}`}
                                onKeyDown={(e) =>
                                  keyboardCell(e, yearIndex * 12 + monthIndex)
                                }
                                onClick={() => inspect(period)}
                                className={
                                  selected === period ? styles.selectedCell : ""
                                }
                                style={
                                  {
                                    "--cell-color": intensity
                                      ? `var(--map-ramp-${intensity})`
                                      : "var(--surface-elevated)",
                                  } as CSSProperties
                                }
                              >
                                {visibleValue}
                              </button>
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className={styles.heatmapLegend}>
                <span>
                  {isDemo
                    ? "Synthetic monthly allocation"
                    : `Recorded monthly ${METRICS[metric].toLowerCase()}`}
                </span>
                <div>
                  <span>Fewer</span>
                  {[1, 2, 3, 4, 5, 6].map((n) => (
                    <i key={n} style={{ background: `var(--map-ramp-${n})` }} />
                  ))}
                  <span>More</span>
                </div>
              </div>
              <div className={styles.statusLegend} aria-label="Monthly observation states"><span><b>Out</b> Not selected</span><span><b>N/C</b> No coverage</span><span><b>?</b> Unknown count</span><span><b>0</b> Recorded zero</span>{data?.monthly.some(row => row.availability === "unsupported") && <span><b>N/S</b> Unsupported</span>}</div>
              <div className={styles.monthInspection} aria-live="polite">
                {selected ? (
                  <>
                    <div>
                      <strong>{monthLabel(selected)}</strong>
                      <button
                        className={styles.info}
                        aria-label="Clear inspected month"
                        onClick={() => setSelection(null)}
                      >
                        <X size={14} />
                      </button>
                    </div>
                    {selectedMonth?.crashes != null ? (
                      <>
                        <div className={styles.inspectionValues}>
                          {Object.entries(METRICS).map(([field, label]) => (
                            <span key={field}>
                              {label}
                              <b>{number(selectedMonth[field as MetricKey])}</b>
                            </span>
                          ))}
                        </div>
                        <button
                          className={styles.inlineAction}
                          onClick={() =>
                            changeFilters({
                              ...actualFilters,
                              dateRange: {
                                from: `${selected}-01`,
                                to: monthEnd(selected),
                              },
                            })
                          }
                        >
                          Analyze this month <ArrowUpRight size={14} />
                        </button>
                      </>
                    ) : (
                      <p>
                        {selectedMonth ? selectedMonth.availability === "no_results" ? "No coverage for this month." : "Unknown count for this month." : "Not in selected period."}
                      </p>
                    )}
                  </>
                ) : (
                  <p>
                    <Info size={15} />
                    Select a month for its crash and casualty breakdown.
                  </p>
                )}
              </div>
            </article>
            <article className={styles.card}>
              <div className={styles.cardHeading}>
                <div>
                  <h2>Typical month</h2>
                  <p>Average {METRICS[metric].toLowerCase()} by calendar month</p>
                </div>
                <button
                  className={styles.info}
                  aria-label="Monthly average values"
                  onClick={() =>
                    evidence(
                      "Calendar-month averages",
                      isDemo
                        ? "Each mean uses observed instances of that month within the selection. Missing months are excluded. The repeated shape is a property of fixed synthetic weights, not real seasonality."
                        : "Each mean uses months with known counts for the selected metric. Missing and unknown months are excluded. This descriptive average does not establish seasonality or explain causation.",
                      insights.calendar.map((row) => ({
                        label: MONTHS[row.month - 1],
                        value: `${number(row.average, 1)} ${METRICS[metric].toLowerCase()} · ${row.observed} observed months`,
                      })),
                    )
                  }
                >
                  <Info size={15} />
                </button>
              </div>
              <div className={styles.patternChart}>
                <Chart kind="seasonality" rows={monthly} metric={metric} />
              </div>
              <div className={styles.cardFoot}>
                <span>
                  {isDemo
                    ? "Observed months only · synthetic pattern"
                    : "Known monthly counts · descriptive average"}
                </span>
              </div>
            </article>
          </section>}
          <section className={styles.fullWidthData} aria-label="Trend data">
            <article className={`${styles.card} ${styles.dataCard}`}>
              <div className={styles.cardHeading}>
                <div>
                  <h2>Analysis data</h2>
                  <p>Aggregates behind the charts</p>
                </div>
                <div className={styles.segment} aria-label="Table interval">
                  {(["yearly", "monthly"] as const).map((mode) => (
                    <button
                      key={mode}
                      aria-pressed={tableGranularity === mode}
                      onClick={() => {
                        setTableGranularity(mode);
                        setPage(1);
                      }}
                    >
                      {mode === "monthly" ? "Months" : "Years"}
                    </button>
                  ))}
                </div>
              </div>
              <div className={styles.tableScroll}>
                <table className={styles.dataTable}>
                  <caption className="sr-only">
                    Source-specific {isDemo ? "demo" : "published"} aggregates.
                    Select a column header to sort.
                  </caption>
                  <thead>
                    <tr>
                      {[["period", "Period"], ...Object.entries(METRICS)].map(
                        ([field, label]) => (
                          <th
                            key={field}
                            scope="col"
                            aria-sort={
                              sort.key === field
                                ? sort.ascending
                                  ? "ascending"
                                  : "descending"
                                : "none"
                            }
                          >
                            <button
                              onClick={() => {
                                setSort({
                                  key: field as keyof TimePoint,
                                  ascending:
                                    sort.key === field
                                      ? !sort.ascending
                                      : false,
                                });
                                setPage(1);
                              }}
                            >
                              {label}
                              <ArrowUpDown size={12} />
                            </button>
                          </th>
                        ),
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {visibleRows.map((row) => (
                      <tr
                        key={row.period}
                        className={
                          selected === row.period ? styles.selectedRow : ""
                        }
                      >
                        <th scope="row">
                          {row.period.length > 4 ? (
                            <button
                              className={styles.periodButton}
                              onClick={() => {
                                inspect(row.period);
                                heatmap.current?.scrollIntoView({
                                  behavior: matchMedia(
                                    "(prefers-reduced-motion: reduce)",
                                  ).matches
                                    ? "instant"
                                    : "smooth",
                                  block: "center",
                                });
                              }}
                            >
                              {monthLabel(row.period)}
                            </button>
                          ) : (
                            <>
                              {row.period}
                              {data?.yearly.find(
                                (year) =>
                                  String(year.year) === row.period &&
                                  !year.fullYear,
                              ) && (
                                <small className={styles.yearMonths}>
                                  {(() => {
                                    const year = data.yearly.find(
                                      (year) =>
                                        String(year.year) === row.period,
                                    )!;
                                    return `${MONTHS[year.comparisonMonths[0] - 1]}–${MONTHS[year.comparisonMonths.at(-1)! - 1]}`;
                                  })()}
                                </small>
                              )}
                            </>
                          )}
                        </th>
                        {Object.keys(METRICS).map((field) => (
                          <td key={field}>{number(row[field as MetricKey])}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className={styles.tableFooter}>
                <span>
                  {number(tableRows.length)}{" "}
                  {tableGranularity === "monthly" ? "months" : "years"}
                  {tableGranularity === "yearly" &&
                  data?.yearly.some((row) => !row.fullYear)
                    ? " · selected months only"
                    : ""}
                </span>
                <div>
                  <button
                    aria-label="Previous data page"
                    disabled={currentPage === 1}
                    onClick={() => setPage((n) => n - 1)}
                  >
                    <ChevronLeft size={16} />
                  </button>
                  <span>
                    {currentPage} / {totalPages}
                  </span>
                  <button
                    aria-label="Next data page"
                    disabled={currentPage >= totalPages}
                    onClick={() => setPage((n) => n + 1)}
                  >
                    <ChevronRight size={16} />
                  </button>
                </div>
              </div>
            </article>
          </section>
        </div>
      )}
    </div>
  );
}
