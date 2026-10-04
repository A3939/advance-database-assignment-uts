"use client";
import { LOCAL_DATE_BOUNDS } from "@/services/date-range";
import Link from "next/link";
import { monthRangeLabel, timePointLabel } from "@/services/periods";
import { wholeMonthRange } from "@/services/date-range";
import { sourceCoverage, coverageMonthRange, sourceDisplayName } from "@/services/catalog-contracts";
import { regionsForSource } from "@/services/regions";
import { useEffect, useState, useMemo } from "react";
import dynamic from "next/dynamic";
import {
  CalendarDays,
  CarFront,
  TriangleAlert,
  Heart,
  Users,
  Info,
  Download,
  Sparkles,
  ArrowUpRight,
  ChartNoAxesCombined,
  Loader2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import SourceSelect from "@/components/source-select";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useWorkspace } from "./workspace";
import { arsia } from "@/services";
import { selectSource } from "@/services/config";
import type {
  Filters,
  Granularity,
  Overview as OverviewData,
  TimePoint,
  Severity,
  MapData,
  Response,
} from "@/services/contracts";
const Chart = dynamic(() => import("./charts"), {
  ssr: false,
  loading: () => (
    <div className="visual-loading">
      <Loader2 className="spin" size={20} />
      Loading chart
    </div>
  ),
});
const SpatialMap = dynamic(() => import("./spatial-map"), {
  ssr: false,
  loading: () => (
    <div className="visual-loading">
      <Loader2 className="spin" size={20} />
      Loading local map
    </div>
  ),
});
interface Bundle {
  overview: Response<OverviewData>;
  trend: Response<TimePoint[]>;
  severity: Response<Severity[]>;
  map: Response<MapData>;
}
const format = (n: number | null | undefined) =>
  n == null ? "—" : n.toLocaleString("en-AU");
export default function Overview({ explore = false }: { explore?: boolean }) {
  const { filters, catalog, setFilters, askAI, showEvidence, notify, view, setView, analysisHref } = useWorkspace();
  const sourceLabels = useMemo(() => Object.fromEntries(catalog.sources.map(source => [source.source, sourceDisplayName(source, catalog)])), [catalog]);
  const displaySource = (id: string) => sourceLabels[id] || id;
  const granularity = view.overviewGranularity;
  const setGranularity = (overviewGranularity: Granularity) => setView({ ...view, overviewGranularity });
  const [result, setResult] = useState<{ key: string; bundle: Bundle } | null>(null),
    [failure, setFailure] = useState<{key: string; message: string} | null>(null),
    [dateOpen, setDateOpen] = useState(false),
    [draftFrom, setDraftFrom] = useState(filters.dateRange.from.slice(0,7)),
    [draftTo, setDraftTo] = useState(filters.dateRange.to.slice(0,7)),
    [exporting, setExporting] = useState(false);
  const [severitySource, setSeveritySource] = useState<string>(catalog.sources[0]?.source || "");
  const [retry, setRetry] = useState(0);
  const key = JSON.stringify([filters, granularity]);
  const bundle = result?.key === key ? result.bundle : null;
  const mapBundle = bundle || result?.bundle;
  const error = failure?.key === key ? failure.message : "";
  const loading = !bundle && !error;
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    Promise.all([
      arsia.getOverview(filters, controller.signal),
      arsia.getTimeSeries(filters, granularity, controller.signal),
      arsia.getSeverityDistribution(filters, controller.signal),
      arsia.getMapData(filters, controller.signal),
    ])
      .then(([overview, trend, severity, map]) => {
        if ([overview, trend, severity, map].some(response => response.meta.source !== filters.source || response.meta.datasetVersion !== filters.datasetVersion || response.meta.batchId !== filters.batchId)) {
          throw new Error("Snapshot response identity mismatch.");
        }
        if (active) {
          setResult({ key, bundle: { overview, trend, severity, map } });
          setFailure(null);
        }
      })
      .catch(() => {
        if (active) {
          setFailure({key, message: `The ${filters.releaseId ? "selected release" : "project snapshot"} could not be loaded for this selection. Retry keeps the same scope.`});
          setResult(null);
        }
      });
    return () => {
      active = false; controller.abort();
    };
  }, [filters, granularity, key, retry]);
  const change = (next: Filters) => {
    setFailure(null);
    setFilters(next);
  };
  const metricDefs = bundle?.overview.data;
  const cards = [
    {
      key: "crashes",
      label: "Crashes",
      icon: CarFront,
      note: `Recorded crashes · ${monthRangeLabel(filters)}`,
    },
    {
      key: "fatalCrashes",
      label: "Fatal crashes",
      icon: TriangleAlert,
      note:
        metricDefs?.fatalShare != null
          ? `${(metricDefs.fatalShare * 100).toFixed(2)}% of recorded crashes`
          : "No ratio available",
    },
    {
      key: "livesLost",
      label: "Lives lost",
      icon: Heart,
      note: "Recorded deaths · source-defined",
    },
    {
      key: "casualties",
      label: "Casualties",
      icon: Users,
      note: "Source-defined casualty count",
    },
  ] as const;
  const yearOnly =
    filters.dateRange.from.endsWith("01-01") &&
    filters.dateRange.to.endsWith("12-31");
  const dateLabel = yearOnly
    ? `${filters.dateRange.from.slice(0, 4)} – ${filters.dateRange.to.slice(0, 4)}`
    : `${filters.dateRange.from.slice(0, 7)} – ${filters.dateRange.to.slice(0, 7)}`;
  const trend = bundle?.trend.data || [];
  const showTrend = () =>
    showEvidence({
      title: "Crashes over time",
      description: bundle?.trend.meta.definition || "Loading trend definition.",
      demo: bundle?.trend.meta.demo,
      rows: [
        {
          label: filters.releaseId ? "Release" : "Batch",
          value: bundle?.trend.meta.batchId || filters.batchId,
        },
        {
          label: "Version",
          value: bundle?.trend.meta.datasetVersion || filters.datasetVersion,
        },
        { label: "Selected period", value: monthRangeLabel(filters) },
        ...trend.map((r) => ({
          label: `${r.source ? `${displaySource(r.source)} · ` : ""}${timePointLabel(r)}`,
          value: `${format(r.crashes)} recorded crashes`,
        })),
      ],
      evidence: bundle?.trend.meta.evidence,
    });
  async function exportData() {
    if (!bundle) return;
    setExporting(true);
    try {
      const payload = {
        demo: bundle.overview.meta.demo,
        exportedAt: new Date().toISOString(),
        filters,
        granularity,
        overview: bundle.overview,
        timeSeries: bundle.trend,
        severity: bundle.severity,
        map: bundle.map,
        notice: bundle.overview.meta.demo
          ? "Demonstration aggregates with response metadata. Individual crash records are not included."
          : "Read-only data at the selected snapshot or local release. Sources retain their own definitions. Availability, source restrictions and batch provenance are included in every response. Individual crash records and exact accident coordinates are not included. Verified rounded coordinate aggregates retain their precision and coverage metadata. Any LGA selection is recorded in the filters.",
      };
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(payload, null, 2)], {
          type: "application/json",
        }),
      );
      const a = document.createElement("a");
      a.href = url;
      a.download = `ARSIA-${bundle.overview.meta.demo ? "DEMO" : "SNAPSHOT"}-${filters.source}-${filters.dateRange.from}-${filters.dateRange.to}.json`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      notify(
        "Export downloaded with filters, definitions and batch provenance.",
      );
    } catch {
      notify("Export could not be prepared. Please try again.");
    } finally {
      setExporting(false);
    }
  }
  const dateBounds = catalog.mode === "local" ? LOCAL_DATE_BOUNDS : {min:"2019-01",max:"2026-12"};
  const availableRange = sourceCoverage(catalog, filters.source);
  const draftPeriod = wholeMonthRange(draftFrom, draftTo, dateBounds);
  function applyDates() {
    if (draftPeriod.error || !draftPeriod.dateRange) return;
    change({ ...filters, dateRange: draftPeriod.dateRange });
    setDateOpen(false);
  }
  return (
    <div
      className={`overview ${filters.source === "All" ? "all-sources" : ""}`}
    >
      <section
        className="page-heading overview-toolbar"
        aria-label="Analysis filters"
      >
        <div className="heading-title">
          <div className="title-line">
            <h1 className="sr-only">{explore ? "Explore" : "Overview"}</h1>
            <Popover
              open={dateOpen}
              onOpenChange={(open) => {
                setDateOpen(open);
                if (open) {
                  setDraftFrom(filters.dateRange.from.slice(0, 7));
                  setDraftTo(filters.dateRange.to.slice(0, 7));
                }
              }}
            >
              <PopoverTrigger asChild>
                <Button variant="outline" className="date-trigger">
                  <CalendarDays size={17} />
                  {dateLabel}
                </Button>
              </PopoverTrigger>
              <PopoverContent className="date-popover" align="start">
                <h3>Analysis period</h3>
                <p>Choose whole months. Coverage: {availableRange.from} → {availableRange.to}.</p>
                <div className="date-inputs">
                  <label>
                    From
                    <input
                      type="month"
                      aria-label="Start month"
                      value={draftFrom}
                      min={dateBounds.min}
                      max={dateBounds.max}
                      onChange={(e) => setDraftFrom(e.target.value)}
                    />
                  </label>
                  <label>
                    To
                    <input
                      type="month"
                      aria-label="End month"
                      value={draftTo}
                      min={dateBounds.min}
                      max={dateBounds.max}
                      onChange={(e) => setDraftTo(e.target.value)}
                    />
                  </label>
                </div>
                <div className="date-presets">
                  {[
                    [availableRange.from.slice(0,7), availableRange.to.slice(0,7), "All years"],
                    [`${availableRange.to.slice(0,4)}-01`, availableRange.to.slice(0,7), availableRange.to.slice(0,4)],
                    [`${Number(availableRange.to.slice(0,4))+1}-01`, `${Number(availableRange.to.slice(0,4))+1}-12`, `${Number(availableRange.to.slice(0,4))+1} · no data`],
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
                  className="lime-button"
                  disabled={!!draftPeriod.error}
                  onClick={applyDates}
                >
                  Apply period
                </Button>
              </PopoverContent>
            </Popover>
            {filters.regionId && filters.source !== "All" && <button className="region-filter-chip" onClick={() => change({ ...filters, regionId: undefined })} aria-label="Clear LGA filter">
              {regionsForSource(filters.source).find(r => r.id === filters.regionId)?.name} LGA <span aria-hidden="true">×</span>
            </button>}
          </div>
        </div>
        <div className="filter-actions">
          <SourceSelect value={filters.source} onChange={source => change({ ...selectSource(filters, source), ...(catalog.mode === "local" ? {dateRange:coverageMonthRange(sourceCoverage(catalog,source))} : {}) })} />
          <Button
            variant="outline"
            disabled={loading || exporting || !bundle}
            onClick={() => void exportData()}
          >
            <Download size={17} />
            {exporting ? "Exporting…" : "Export"}
          </Button>
          <Button className="ask-ai-button" onClick={askAI}>
            <Sparkles size={18} />
            Ask AI
          </Button>
        </div>
      </section>
      {error && (
        <div className="error-banner" role="alert">
          {error}
          <Button variant="outline" onClick={() => { setFailure(null); setRetry(r => r + 1); }}>Retry selection</Button>
        </div>
      )}
      <div
        className={`dashboard-body ${loading && bundle ? "is-updating" : ""}`}
        aria-busy={loading}
      >
        <section className="metric-grid" aria-label="Overview metrics">
          {cards.map(({ key, label, icon: Icon, note }) => (
            <article className="panel metric-card" key={key}>
              <div className="metric-label">
                <Icon size={25} strokeWidth={1.5} />
                <span>{label}</span>
                <button
                  disabled={!bundle}
                  aria-label={`${label} definition`}
                  className="info-button"
                  onClick={() =>
                    showEvidence({
                      title: label,
                      description:
                        metricDefs?.[key].definition ||
                        "Loading metric definition.",
                      demo: bundle?.overview.meta.demo,
                      evidence: bundle?.overview.meta.evidence,
                      rows: [
                        ...(metricDefs?.[key].bySource || []).map((row) => ({
                          label: displaySource(row.source),
                          value: format(row.value),
                        })),
                        {
                          label: "Value",
                          value: format(metricDefs?.[key].value),
                        },
                        { label: "Unit", value: metricDefs?.[key].unit || "—" },
                        { label: "Selected period", value: monthRangeLabel(filters) },
                        {
                          label: "Availability",
                          value: metricDefs?.[key].availability || "Loading",
                        },
                        {
                          label: "Source",
                          value: `${filters.source} · ${bundle?.overview.meta.demo ? "demo data" : filters.releaseId ? "local release" : "project snapshot"}`,
                        },
                        {
                          label: filters.releaseId ? "Release" : "Batch",
                          value:
                            bundle?.overview.meta.batchId || filters.batchId,
                        },
                        ...(metricDefs?.[key].reason
                          ? [
                              {
                                label: "Limitation",
                                value: metricDefs[key].reason,
                              },
                            ]
                          : []),
                      ],
                    })
                  }
                >
                  <Info size={16} />
                </button>
              </div>
              {metricDefs?.[key].bySource ? (
                <div className="metric-by-source">
                  {metricDefs[key].bySource.map((row) => (
                    <div key={row.source}>
                      <span>{displaySource(row.source)}</span>
                      <strong
                        title={
                          row.availability === "available"
                            ? undefined
                            : `${displaySource(row.source)}: ${row.availability.replaceAll("_", " ")}; open the metric definition for its source policy.`
                        }
                      >
                        {format(row.value)}
                      </strong>
                    </div>
                  ))}
                </div>
              ) : (
                <>
                  <div className="metric-value">
                    {format(metricDefs?.[key].value)}
                  </div>
                  <p title={metricDefs?.[key].reason}>
                    {metricDefs?.[key].availability === "unsupported"
                      ? "Unavailable for this source · see definition"
                      : metricDefs?.[key].availability === "unknown"
                        ? "Unknown · see definition"
                        : note}
                  </p>
                </>
              )}
            </article>
          ))}
        </section>
        {bundle?.overview.meta.availability === "no_results" && (
          <div className="empty-banner" role="status">
            <Info size={18} />
            <span>
              {bundle.overview.meta.reason ||
                "No data for this selection. Choose dates within the source coverage. Missing data is not zero."}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                change({
                  ...filters,
                  dateRange: coverageMonthRange(availableRange),
                })
              }
            >
              Reset dates
            </Button>
          </div>
        )}
        {bundle?.overview.meta.availability === "available" &&
          !bundle.overview.meta.coverage.complete && (
            <div className="empty-banner" role="status">
              <Info size={18} />
              Partial coverage: totals include available months in the selected release
              only.
            </div>
          )}
        <section className="visual-grid">
          <article
            className="spatial-panel seamless-map"
            aria-label="Crash map"
            data-loading={!bundle}
            aria-busy={!bundle}
            inert={!bundle}
          >
            {mapBundle ? (
              <SpatialMap
                source={mapBundle.map.meta.source}
                data={mapBundle.map.data}
                onSourceSelect={(source) =>
                  bundle && change(selectSource(filters, source))
                }
                onSelect={(id, name) => {
                  if (!bundle) return;
                  if (mapBundle.map.data.regionMode === "lga") change({ ...filters, regionId: id || undefined });
                  else notify(`Selected ${name}`);
                }}
              />
            ) : (
              <div className="visual-loading">{error ? "Map unavailable. Retry this selection above." : "Loading map for the selected scope…"}</div>
            )}
            {!bundle && mapBundle && <div className="map-scope-loading visual-loading" role="status">{error ? "Map unavailable. Retry this selection above." : "Loading map for the selected scope…"}</div>}
          </article>
          <div className="chart-stack">
            <article className="panel trend-panel">
              <div className="panel-heading">
                <div>
                  <h2>Crashes over time</h2>
                  <button
                    className="info-button"
                    aria-label="Trend chart evidence"
                    disabled={!bundle}
                    onClick={showTrend}
                  >
                    <Info size={16} />
                  </button>
                </div>
                <div className="chart-actions">
                  <div className="segmented" aria-label="Trend granularity">
                    {(["yearly", "monthly"] as const).map((g) => (
                      <button
                        key={g}
                        aria-pressed={granularity === g}
                        className={granularity === g ? "selected" : ""}
                        onClick={() => {
                          if (g !== granularity) {
                            setGranularity(g);
                          }
                        }}
                      >
                        {g === "yearly" ? "Yearly" : "Monthly"}
                      </button>
                    ))}
                  </div>
                  <Link className="compare-button" aria-label="Compare matching months in Analytics" href={analysisHref("/analytics")}>
                    <ChartNoAxesCombined size={16} />
                    <span>Compare in Analytics</span>
                  </Link>
                </div>
              </div>
              {trend.some(row => row.crashes !== null) ? (
                <Chart kind="trend" sourceLabels={sourceLabels} rows={trend.map(row => ({ ...row, period: timePointLabel(row) }))} />
              ) : (
                <div className="empty-visual">
                  {bundle?.trend.meta.reason || (trend.length ? "Crash counts are unknown for this source. Unknown observations are not zero." : "No time series in this range")}
                </div>
              )}
            </article>
            <article className="panel severity-panel">
              <div className="panel-heading">
                <div>
                  <h2>Crash severity</h2>
                  <button
                    className="info-button"
                    disabled={!bundle}
                    aria-label="Severity definitions"
                    onClick={() =>
                      showEvidence({
                        title: "Crash severity definitions",
                        description:
                          bundle?.severity.meta.reason ||
                          bundle?.severity.meta.definition ||
                          "Loading source classifications.",
                        demo: bundle?.severity.meta.demo,
                        evidence: bundle?.severity.meta.evidence,
                        rows: bundle?.severity.data.map((r) => ({
                          label: `${r.source ? `${displaySource(r.source)} · ` : ""}${r.label}`,
                          value: `${format(r.count)} crashes · ${r.definition}`,
                        })),
                      })
                    }
                  >
                    <Info size={16} />
                  </button>
                </div>
              {filters.source === "All" && <div className="severity-source-tabs segmented" aria-label="Severity source">{catalog.sources.map(source => <button key={source.source} className={source.source === severitySource ? "selected" : ""} aria-pressed={source.source === severitySource} onClick={() => setSeveritySource(source.source)}>{sourceDisplayName(source, catalog)}</button>)}</div>}
              </div>
              {bundle?.severity.meta.availability === "available" &&
              bundle.severity.data.length ? (
                <Chart kind="severity" rows={filters.source === "All" ? bundle.severity.data.filter(row => row.source === severitySource) : bundle.severity.data} />
              ) : (
                <div
                  className="empty-visual severity-availability"
                  role="status"
                >
                  <strong>
                    {bundle?.severity.meta.availability === "unsupported"
                      ? "Severity breakdown unavailable"
                      : loading
                        ? "Loading classifications…"
                        : "No severity data"}
                  </strong>
                  <span>
                    {bundle?.severity.meta.reason ||
                      "No severity observations in this range."}
                  </span>
                  {bundle?.severity.meta.availability === "unsupported" && <Button variant="outline" size="sm" onClick={() => change({ ...filters, dateRange: coverageMonthRange(availableRange) })}>Use full-period selection</Button>}
                </div>
              )}
              <div className="panel-footer">
                <span>
                  <Info size={16} />
                  Source-specific · categories differ across states
                </span>
                <button
                  disabled={!bundle}
                  onClick={() =>
                    showEvidence({
                      title: "Classification coverage",
                      description:
                        bundle?.severity.meta.reason ||
                        bundle?.severity.meta.definition ||
                        "Loading classification coverage.",
                      demo: bundle?.severity.meta.demo,
                      evidence: bundle?.severity.meta.evidence,
                      rows: bundle?.severity.data.map((r) => ({
                        label: `${r.source ? `${displaySource(r.source)} · ` : ""}${r.label}`,
                        value: format(r.count),
                      })),
                    })
                  }
                >
                  View definitions
                  <ArrowUpRight size={14} />
                </button>
              </div>
            </article>
          </div>
        </section>
      </div>
    </div>
  );
}
