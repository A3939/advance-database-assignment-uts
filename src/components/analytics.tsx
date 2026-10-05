"use client";

import regionCatalog from "@/services/region-catalog.json";
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
import {
  ArrowDownRight,
  ArrowUpRight,
  ArrowUpDown,
  CalendarDays,
  CarFront,
  ChevronLeft,
  ChevronRight,
  Download,
  Heart,
  Info,
  RotateCcw,
  TriangleAlert,
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
import { analyticsFilters, getAnalytics } from "@/services/analytics";
import { DEFAULT_FILTERS, IS_DEMO, selectSource } from "@/services/config";
import type { Filters, Source, TimePoint } from "@/services/contracts";
import styles from "./analytics.module.css";

const Chart = dynamic(() => import("@/components/analytics-chart"), {
  ssr: false,
  loading: () => (
    <div className={styles.chartLoading} role="status">
      Loading chart…
    </div>
  ),
});
const SOURCES: Source[] = ["NSW", "VIC", "QLD"];
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

export default function Analytics() {
  const { filters, setFilters, showEvidence, notify } = useWorkspace();
  const actualFilters = useMemo(() => analyticsFilters(filters), [filters]);
  const [result, setResult] = useState<{ key: string; bundle: Bundle } | null>(
    null,
  );
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [granularity, setGranularity] = useState<"monthly" | "yearly">(
    "monthly",
  );
  const [metric, setMetric] = useState<MetricKey>("crashes");
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
  const key = filterKey(actualFilters);
  const loading = result?.key !== key;
  // Never display an old source underneath new filters while a provider resolves.
  const bundle = result?.key === key ? result.bundle : null;
  const data = bundle?.data;
  const isDemo = bundle?.meta.demo ?? IS_DEMO;
  const coverage = bundle?.meta.coverage ?? { ...DEFAULT_FILTERS.dateRange };
  const coverageLabel = `${coverage.from.slice(0, 4)}–${coverage.to.slice(0, 4)}`;
  const selected = selection?.key === key ? selection.period : null;
  useEffect(() => {
    let active = true;
    getAnalytics(actualFilters)
      .then((bundle) => {
        if (!active) return;
        setResult({ key: filterKey(actualFilters), bundle });
        setError("");
        if (filters.source === "All") setFilters(actualFilters);
      })
      .catch(() => {
        if (active)
          setError("This analysis could not be loaded. Please try again.");
      });
    return () => {
      active = false;
    };
  }, [actualFilters, filters.source, retry, setFilters]);

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
  const total = data?.summary.total;
  const knownCrashCounts = monthly.flatMap((row) =>
    row.crashes === null ? [] : [row.crashes],
  );
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
  const isEmpty = !loading && monthly.length === 0;
  const dateLabel =
    actualFilters.dateRange.from.endsWith("01-01") &&
    actualFilters.dateRange.to.endsWith("12-31")
      ? `${actualFilters.dateRange.from.slice(0, 4)} – ${actualFilters.dateRange.to.slice(0, 4)}`
      : `${monthLabel(actualFilters.dateRange.from)} – ${monthLabel(actualFilters.dateRange.to)}`;
  function changeFilters(next: Filters) {
    setError("");
    setPage(1);
    setSelection(null);
    setFilters(next);
  }
  function resetDates() {
    changeFilters({
      ...actualFilters,
      dateRange: { ...DEFAULT_FILTERS.dateRange },
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
    showEvidence({ title, description, rows });
  }
  function exportData() {
    if (!bundle) return;
    const payload = {
      demo: bundle.meta.demo,
      exportedAt: new Date().toISOString(),
      filters: actualFilters,
      view: { metric, granularity },
      analysis: bundle,
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
      buttons[
        Math.min(Math.max(0, index + delta), buttons.length - 1)
      ]?.focus();
    }
  }
  const methodology = () =>
    evidence(
      "How this analysis is built",
      isDemo
        ? "All views use the same source-specific demo aggregates. Monthly values are allocated from annual totals using fixed illustrative weights; repeated monthly patterns are constructed, not findings about real roads."
        : "Views use published source-specific aggregates from one fixed ARSIA batch. Monthly counts are recorded observations from the pinned source exports. Only available outputs are displayed; source definitions and coverage limits remain in force.",
      [
        {
          label: "Source / version",
          value: `${actualFilters.source} · ${actualFilters.datasetVersion}`,
        },
        { label: "Batch", value: actualFilters.batchId },
        {
          label: "Comparison",
          value:
            "Same calendar months in the previous year. Missing periods or a zero baseline do not produce a percentage.",
        },
        {
          label: "Fatal crash share",
          value:
            "Fatal crashes / crashes with known fatal status. Unknown status is excluded from the denominator. This is not a travel-risk rate.",
        },
        {
          label: "Severity",
          value:
            data?.severityReason ||
            "Source-defined crash categories. Shares use this selection's crash total; categories are not harmonised across states.",
        },
        {
          label: "People",
          value: isDemo
            ? "Lives lost and casualties are independent demo aggregates, not reconstructed from crash samples."
            : "Lives lost and casualties are source-defined person counts from published crash aggregates. They are distinct from the number of fatal crashes.",
        },
        {
          label: "Monthly average",
          value:
            "Sum of known monthly crash counts / months with known crash counts. Missing and unknown months are excluded, not zero-filled.",
        },
        ...(bundle?.meta.evidence.map((item) => ({
          label: item.title,
          value: item.description,
        })) ?? []),
      ],
    );

  return (
    <div className={styles.page}>
      <div className={styles.heading}>
        <div className={styles.title}>
          <div>
            <span className={styles.eyebrow}>REPORT 01 · D05</span>
            <h1>Trend Analysis</h1>
            <p>Track recorded crash outcomes over time using verified D05 aggregates.</p>
          </div>
          <button className={styles.demo} onClick={methodology}>
            {isDemo ? "Demo data" : "Official snapshot"} <Info size={13} />
          </button>
        </div>
        <div className={styles.actions}>
          <Button
            variant="outline"
            onClick={exportData}
            disabled={loading || !data || isEmpty}
          >
            <Download size={16} />
            Export
          </Button>
        </div>
      </div>
      <div className={styles.toolbar} aria-label="Analytics filters">
        <div className={styles.sourceGroup} aria-label="Analysis source">
          <span className={styles.filterLabel}>Source</span>
          {SOURCES.map((source) => (
            <button
              key={source}
              aria-pressed={actualFilters.source === source}
              onClick={() => changeFilters(selectSource(actualFilters, source))}
            >
              {source}
            </button>
          ))}
        </div>
        {actualFilters.regionId && <button className="region-filter-chip" onClick={() => changeFilters({ ...actualFilters, regionId: undefined })} aria-label="Clear LGA filter">
          {regionCatalog[actualFilters.source].find(r => r.id === actualFilters.regionId)?.name} LGA ×
        </button>}
        <div className={styles.toolbarRight}>
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
                    min="2019-01"
                    max="2026-12"
                    value={draftFrom}
                    onChange={(e) => setDraftFrom(e.target.value)}
                  />
                </label>
                <label>
                  To
                  <input
                    type="month"
                    aria-label="End month"
                    min="2019-01"
                    max="2026-12"
                    value={draftTo}
                    onChange={(e) => setDraftTo(e.target.value)}
                  />
                </label>
              </div>
              <div className="date-presets">
                {[
                  ["2020-01", "2024-12", "Full coverage"],
                  ["2023-01", "2024-12", "2023–2024"],
                  ["2024-01", "2024-12", "2024"],
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
              {draftFrom > draftTo && (
                <p role="alert">Start month must not follow end month.</p>
              )}
              <Button
                className="ask-ai-button"
                disabled={!draftFrom || !draftTo || draftFrom > draftTo}
                onClick={() => {
                  changeFilters({
                    ...actualFilters,
                    dateRange: {
                      from: `${draftFrom}-01`,
                      to: monthEnd(draftTo),
                    },
                  });
                  setDateOpen(false);
                }}
              >
                Apply period
              </Button>
            </PopoverContent>
          </Popover>
          <button className={styles.methodButton} onClick={methodology}>
            <Info size={15} />
            Methodology
          </button>
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
      ) : isEmpty ? (
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
      ) : (
        <div aria-busy={loading}>
          <div className={styles.metrics} aria-label="Analysis summary">
            <div>
              <i className={styles.metricIcon}><CarFront size={20} /></i>
              <span>Recorded crashes</span>
              <strong data-testid="analytics-total">{number(total)}</strong>
              <small>{actualFilters.source} · source-defined events</small>
            </div>
            <div>
              <i className={`${styles.metricIcon} ${styles.metricCoral}`}><TriangleAlert size={20} /></i>
              <span>Fatal crashes</span>
              <strong>{number(data?.overview.fatalCrashes.value)}</strong>
              <small>{data?.summary.fatalShare == null ? "Known-status denominator" : `${(data.summary.fatalShare * 100).toFixed(2)}% of known crashes`}</small>
            </div>
            <div>
              <i className={`${styles.metricIcon} ${styles.metricAmber}`}><Heart size={20} /></i>
              <span>Lives lost</span>
              <strong>{number(data?.overview.livesLost.value)}</strong>
              <small>Recorded fatalities</small>
            </div>
            <div>
              <i className={`${styles.metricIcon} ${styles.metricGreen}`}><Users size={20} /></i>
              <span>Casualties</span>
              <strong>{number(data?.overview.casualties.value)}</strong>
              <small>{dateLabel}</small>
            </div>
          </div>
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
                  <h2>Recorded crashes over time</h2>
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
                          label: row.period,
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
                  <h2>Year-on-year change</h2>
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
                      "The latest selected year's crash count is compared with exactly the same calendar months in the previous year, including a baseline outside the selected window. A missing month or zero baseline leaves the percentage unavailable.",
                      latest
                        ? [
                            {
                              label: "Current",
                              value: `${latest.year}: ${number(latest.crashes)}`,
                            },
                            {
                              label: "Previous",
                              value: `${latest.previousYear}: ${number(latest.previousCrashes)}`,
                            },
                            {
                              label: "Status",
                              value:
                                latest.comparisonReason ||
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
                {latest?.yoyPct != null &&
                  (latest.yoyPct < 0 ? <ArrowDownRight /> : <ArrowUpRight />)}
                <strong>{percentage(latest?.yoyPct)}</strong>
              </div>
              <p className={styles.changeExplanation}>
                {latest?.yoyPct != null &&
                latest.crashes != null &&
                latest.previousCrashes != null
                  ? `${number(Math.abs(latest.crashes - latest.previousCrashes))} ${latest.crashes < latest.previousCrashes ? "fewer" : "more"} recorded crashes`
                  : "A comparable baseline is unavailable."}
              </p>
              <div className={styles.comparisonBars}>
                {latest &&
                  [
                    [latest.previousYear, latest.previousCrashes],
                    [latest.year, latest.crashes],
                  ].map(([year, count], i) => (
                    <div key={year ?? i}>
                      <div>
                        <span>{year}</span>
                        <strong>{number(count)}</strong>
                      </div>
                      <div className={styles.barTrack}>
                        <i
                          style={{
                            width: `${count == null ? 0 : Math.max(0, (count / Math.max(latest.crashes ?? 0, latest.previousCrashes ?? 0, 1)) * 100)}%`,
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
                    ? `${MONTHS[latest.comparisonMonths[0] - 1]}–${MONTHS[latest.comparisonMonths.at(-1)! - 1]} · ${latest.comparisonMonths.length} ${latest.complete && latest.previousCrashes != null ? "matched" : "selected"} months`
                    : "Matching months required"}
                </span>
              </div>
            </article>
          </section>
          <section className={styles.patternGrid} aria-label="Monthly patterns">
            <article className={`${styles.card} ${styles.heatmapCard}`}>
              <div className={styles.cardHeading}>
                <div>
                  <h2>Monthly distribution</h2>
                  <p>Crashes by year and month</p>
                </div>
                <span className={styles.quietLabel}>
                  Select a cell to inspect
                </span>
              </div>
              <div className={styles.heatmapScroll} ref={heatmap}>
                <table className={styles.heatmap}>
                  <caption className="sr-only">
                    {isDemo ? "Synthetic" : "Published"} crash counts. Arrow
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
                          const value = row?.crashes;
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
                                data-intensity={intensity}
                                aria-pressed={selected === period}
                                aria-label={`${month} ${year}: ${value == null ? "no observation" : `${number(value)} ${isDemo ? "demo " : ""}crashes`}`}
                                title={`${month} ${year}: ${value == null ? "No observation" : `${number(value)} crashes`}`}
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
                                {number(value)}
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
                    : "Recorded monthly crashes"}
                </span>
                <div>
                  <span>Fewer</span>
                  {[1, 2, 3, 4, 5, 6].map((n) => (
                    <i key={n} style={{ background: `var(--map-ramp-${n})` }} />
                  ))}
                  <span>More</span>
                </div>
              </div>
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
                        No observation for this month in the current selection.
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
                  <p>Average crashes by calendar month</p>
                </div>
                <button
                  className={styles.info}
                  aria-label="Monthly average values"
                  onClick={() =>
                    evidence(
                      "Calendar-month averages",
                      isDemo
                        ? "Each mean uses observed instances of that month within the selection. Missing months are excluded. The repeated shape is a property of fixed synthetic weights, not real seasonality."
                        : "Each mean uses months with known crash counts within the selection. Missing and unknown months are excluded. This descriptive average does not establish seasonality or explain why crashes occurred.",
                      data?.calendarMonths.map((row) => ({
                        label: row.label,
                        value: `${number(row.average, 1)} crashes · ${row.observedMonths} observed months`,
                      })),
                    )
                  }
                >
                  <Info size={15} />
                </button>
              </div>
              <div className={styles.patternChart}>
                <Chart kind="seasonality" rows={monthly} />
              </div>
              <div className={styles.cardFoot}>
                <span>
                  {isDemo
                    ? "Observed months only · synthetic pattern"
                    : "Known monthly counts · descriptive average"}
                </span>
              </div>
            </article>
          </section>
          <section className={styles.detailGrid} aria-label="D05 analysis data">
            <article className={`${styles.card} ${styles.dataCard}`}>
              <div className={styles.cardHeading}>
                <div>
                  <h2>D05 verified result table</h2>
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
