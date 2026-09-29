"use client";
import regionCatalog from "@/services/region-catalog.json";
import { useEffect, useState } from "react";
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
  SourceSelection,
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
  const { filters, setFilters, askAI, showEvidence, notify } = useWorkspace();
  const [granularity, setGranularity] = useState<Granularity>("yearly"),
    [bundle, setBundle] = useState<Bundle | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(""),
    [dateOpen, setDateOpen] = useState(false),
    [draftFrom, setDraftFrom] = useState("2020-01"),
    [draftTo, setDraftTo] = useState("2024-12"),
    [exporting, setExporting] = useState(false);
  useEffect(() => {
    let active = true;
    Promise.all([
      arsia.getOverview(filters),
      arsia.getTimeSeries(filters, granularity),
      arsia.getSeverityDistribution(filters),
      arsia.getMapData(filters),
    ])
      .then(([overview, trend, severity, map]) => {
        if (active) {
          setBundle({ overview, trend, severity, map });
          setLoading(false);
          setError("");
        }
      })
      .catch(() => {
        if (active) {
          setError(
            "The project snapshot could not be loaded. Please change the selection and try again.",
          );
          setBundle(null);
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [filters, granularity]);
  const change = (next: Filters) => {
    setError("");
    setLoading(true);
    setFilters(next);
  };
  const metricDefs = bundle?.overview.data;
  const cards = [
    {
      key: "crashes",
      label: "Crashes",
      icon: CarFront,
      note: `Recorded crashes · ${filters.dateRange.from.slice(0, 4)}–${filters.dateRange.to.slice(0, 4)}`,
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
          label: "Batch",
          value: bundle?.trend.meta.batchId || filters.batchId,
        },
        {
          label: "Version",
          value: bundle?.trend.meta.datasetVersion || filters.datasetVersion,
        },
        ...trend.map((r) => ({
          label: `${r.source ? `${r.source} · ` : ""}${r.period}`,
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
          : "Read-only project snapshot of official source data. Sources retain their own definitions. Availability, source restrictions and batch provenance are included in every response. Individual crash records and accident coordinates are not included. Any LGA selection is recorded in the filters.",
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
  function applyDates() {
    const end = new Date(
      Date.UTC(Number(draftTo.slice(0, 4)), Number(draftTo.slice(5, 7)), 0),
    )
      .toISOString()
      .slice(0, 10);
    change({ ...filters, dateRange: { from: `${draftFrom}-01`, to: end } });
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
                <p>Choose whole months. Snapshot coverage: 2020–2024.</p>
                <div className="date-inputs">
                  <label>
                    From
                    <input
                      type="month"
                      aria-label="Start month"
                      value={draftFrom}
                      min="2019-01"
                      max="2026-12"
                      onChange={(e) => setDraftFrom(e.target.value)}
                    />
                  </label>
                  <label>
                    To
                    <input
                      type="month"
                      aria-label="End month"
                      value={draftTo}
                      min="2019-01"
                      max="2026-12"
                      onChange={(e) => setDraftTo(e.target.value)}
                    />
                  </label>
                </div>
                <div className="date-presets">
                  {[
                    ["2020-01", "2024-12", "All years"],
                    ["2024-01", "2024-12", "2024"],
                    ["2025-01", "2025-12", "2025 · no data"],
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
                  className="lime-button"
                  disabled={!draftFrom || !draftTo || draftFrom > draftTo}
                  onClick={applyDates}
                >
                  Apply period
                </Button>
              </PopoverContent>
            </Popover>
            {filters.regionId && filters.source !== "All" && <button className="region-filter-chip" onClick={() => change({ ...filters, regionId: undefined })} aria-label="Clear LGA filter">
              {regionCatalog[filters.source].find(r => r.id === filters.regionId)?.name} LGA <span aria-hidden="true">×</span>
            </button>}
          </div>
        </div>
        <div className="filter-actions">
          <label className="source-select">
            Source
            <select
              aria-label="Data source"
              value={filters.source}
              onChange={(e) =>
                change(selectSource(filters, e.target.value as SourceSelection))
              }
            >
              {["All", "NSW", "VIC", "QLD"].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </label>
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
                          label: row.source,
                          value: format(row.value),
                        })),
                        {
                          label: "Value",
                          value: format(metricDefs?.[key].value),
                        },
                        { label: "Unit", value: metricDefs?.[key].unit || "—" },
                        {
                          label: "Availability",
                          value: metricDefs?.[key].availability || "Loading",
                        },
                        {
                          label: "Source",
                          value: `${filters.source} · ${bundle?.overview.meta.demo ? "demo data" : "project snapshot"}`,
                        },
                        {
                          label: "Batch",
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
                      <span>{row.source}</span>
                      <strong
                        title={
                          row.availability === "available"
                            ? undefined
                            : `${row.source}: ${row.availability.replaceAll("_", " ")}; open the metric definition for its source policy.`
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
                "No data for this selection. Choose dates within 2020–2024. Missing data is not zero."}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                change({
                  ...filters,
                  dateRange: { from: "2020-01-01", to: "2024-12-31" },
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
              Partial coverage: totals include available months in 2020–2024
              only.
            </div>
          )}
        <section className="visual-grid">
          <article
            className="spatial-panel seamless-map"
            aria-label="Crash map"
          >
            {bundle ? (
              <SpatialMap
                onShowEvidence={() =>
                  showEvidence({
                    title: filters.regionId ? `${bundle.map.data.regions.find(r => r.id === filters.regionId)?.name} · LGA details` : "Map coverage & source restrictions",
                    description: bundle.map.meta.definition,
                    demo: bundle.map.meta.demo,
                    evidence: bundle.map.meta.evidence,
                    rows: [
                      ...(bundle.map.data.coverage ? [
                        { label: "Matched crashes (source)", value: `${format(bundle.map.data.coverage.matched)} / ${format(bundle.map.data.coverage.total)}` },
                        { label: "Unmatched crashes", value: format(bundle.map.data.coverage.unmatched) },
                        { label: "Association", value: "Reported LGA name → ABS 2024 area. LGA is not a city or accident point; historical boundaries are not reconstructed." },
                      ] : []),
                      ...(filters.regionId ? (() => {
                        const r = bundle.map.data.regions.find(r => r.id === filters.regionId);
                        return [
                          { label: "Selected LGA", value: `${r?.name} (${filters.regionId})` },
                          { label: "Crashes / fatal crashes", value: `${format(r?.count)} / ${format(r?.fatalCrashes)}` },
                          { label: "Source locality labels", value: r?.localities?.length ? `Top ${r.localities.length} Town/Suburb labels; ${format(r.localityTotal)} records have a locality label. These are not city boundaries or precise locations.` : "No admitted town/suburb labels for this area." },
                          ...(r?.localities || []).map(t => ({ label: t.name, value: `${format(t.count)} crashes` })),
                        ];
                      })() : []),
                      {
                        label: "Availability",
                        value: bundle.map.meta.availability.replaceAll(
                          "_",
                          " ",
                        ),
                      },
                      {
                        label: "Map layer",
                        value: bundle.map.data.legendLabel || "Source coverage",
                      },
                      {
                        label: "Limitation",
                        value:
                          bundle.map.data.unavailableReason ||
                          bundle.map.meta.reason ||
                          "Source definitions differ. State totals are not harmonised risk rates.",
                      },
                      { label: "Batch", value: bundle.map.meta.batchId },
                      {
                        label: "Boundaries",
                        value:
                          "ABS ASGS 2021 states and territories / 2024 local government areas · CC BY 4.0. Boundary geometry does not establish accident locations.",
                      },
                    ],
                    href: "/geo/provenance.json",
                  })
                }
                data={bundle.map.data}
                onSourceSelect={(source) =>
                  change(selectSource(filters, source))
                }
                onSelect={(id, name) => bundle.map.data.regionMode === "lga" ? change({ ...filters, regionId: id || undefined }) : notify(`Selected ${name}`)}
              />
            ) : (
              <div className="visual-loading">Preparing the local map…</div>
            )}
          </article>
          <div className="chart-stack">
            <article className="panel trend-panel">
              <div className="panel-heading">
                <div>
                  <h2>Crashes over time</h2>
                  <button
                    className="info-button"
                    aria-label="Trend chart evidence"
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
                            setLoading(true);
                            setGranularity(g);
                          }
                        }}
                      >
                        {g === "yearly" ? "Yearly" : "Monthly"}
                      </button>
                    ))}
                  </div>
                  <button
                    className="compare-button"
                    aria-label="Compare periods"
                    onClick={showTrend}
                  >
                    <ChartNoAxesCombined size={16} />
                    <span>Compare periods</span>
                  </button>
                </div>
              </div>
              {trend.length ? (
                <Chart kind="trend" rows={trend} />
              ) : (
                <div className="empty-visual">
                  {bundle?.trend.meta.reason || "No time series in this range"}
                </div>
              )}
            </article>
            <article className="panel severity-panel">
              <div className="panel-heading">
                <div>
                  <h2>Crash severity</h2>
                  <button
                    className="info-button"
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
                          label: `${r.source ? `${r.source} · ` : ""}${r.label}`,
                          value: `${format(r.count)} crashes · ${r.definition}`,
                        })),
                      })
                    }
                  >
                    <Info size={16} />
                  </button>
                </div>
              </div>
              {bundle?.severity.meta.availability === "available" &&
              bundle.severity.data.length ? (
                <Chart kind="severity" rows={bundle.severity.data} />
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
                </div>
              )}
              <div className="panel-footer">
                <span>
                  <Info size={16} />
                  Source-specific definitions
                </span>
                <button
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
                        label: `${r.source ? `${r.source} · ` : ""}${r.label}`,
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
