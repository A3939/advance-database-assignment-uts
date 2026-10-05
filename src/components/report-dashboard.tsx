"use client";

import dynamic from "next/dynamic";
import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CarFront,
  Database,
  Heart,
  Info,
  MapPinned,
  ShieldCheck,
} from "lucide-react";
import { useWorkspace } from "@/components/workspace";
import { arsia } from "@/services";
import { selectSource } from "@/services/config";
import type {
  Filters,
  MapData,
  MapRegion,
  Overview,
  Response,
  Severity,
  Source,
  SourceSelection,
} from "@/services/contracts";
import styles from "./report-dashboard.module.css";

const SpatialMap = dynamic(() => import("@/components/spatial-map"), {
  ssr: false,
  loading: () => <div className={styles.loading}>Loading local boundaries…</div>,
});

const SOURCES: Source[] = ["NSW", "VIC", "QLD"];
const format = (value: number | null | undefined) =>
  value == null ? "—" : value.toLocaleString("en-AU");
const pct = (value: number | null | undefined) =>
  value == null ? "—" : `${(value * 100).toFixed(1)}%`;

function sumMetric(metric: Overview[keyof Pick<Overview, "crashes" | "fatalCrashes" | "livesLost" | "casualties">]) {
  if (metric.value != null) return metric.value;
  const values = metric.bySource?.flatMap((row) => row.value == null ? [] : [row.value]) ?? [];
  return values.length ? values.reduce((total, value) => total + value, 0) : null;
}

function ReportHeader({
  code,
  title,
  description,
  filters,
  onChange,
  lga,
}: {
  code: string;
  title: string;
  description: string;
  filters: Filters;
  onChange: (filters: Filters) => void;
  lga?: { id: string; name: string }[];
}) {
  return (
    <header className={styles.reportHeader}>
        <div className={styles.reportTitle}>
          <span className={styles.eyebrow}>REPORT {code}</span>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
        <div className={styles.headerActions}>
          <span className={styles.snapshot}><span />Official snapshot</span>
          <section className={styles.filters} aria-label={`${title} filters`}>
            <label>
              Source
              <select
                value={filters.source}
                onChange={(event) => onChange(selectSource(filters, event.target.value as SourceSelection))}
              >
                <option>All</option>
                {SOURCES.map((source) => <option key={source}>{source}</option>)}
              </select>
            </label>
            {lga && filters.source !== "All" && (
              <label>
                LGA
                <select
                  value={filters.regionId ?? ""}
                  onChange={(event) => onChange({ ...filters, regionId: event.target.value || undefined })}
                >
                  <option value="">All LGAs</option>
                  {lga.map((region) => <option key={region.id} value={region.id}>{region.name}</option>)}
                </select>
              </label>
            )}
          <label>
            Period
            <select
              value={`${filters.dateRange.from}|${filters.dateRange.to}`}
              onChange={(event) => {
                const [from, to] = event.target.value.split("|");
                onChange({ ...filters, dateRange: { from, to } });
              }}
            >
              <option value="2020-01-01|2024-12-31">2020–2024</option>
              <option value="2024-01-01|2024-12-31">2024</option>
            </select>
          </label>
          </section>
        </div>
      </header>
  );
}

function MetricCard({ icon: Icon, label, value, note, tone = "blue", breakdown }: {
  icon: typeof CarFront;
  label: string;
  value: string;
  note: string;
  tone?: "blue" | "coral" | "green";
  breakdown?: { label: string; value: string }[];
}) {
  return (
    <article className={styles.metricCard}>
      <div className={`${styles.metricIcon} ${styles[tone]}`}><Icon size={21} /></div>
      <div>
        <span>{label}</span>
        {breakdown ? (
          <div className={styles.metricBreakdown}>
            {breakdown.map((item) => <div key={item.label}><small>{item.label}</small><b>{item.value}</b></div>)}
          </div>
        ) : <strong>{value}</strong>}
        <small>{note}</small>
      </div>
    </article>
  );
}

interface SeverityBundle {
  overview: Response<Overview>;
  severity: Response<Severity[]>;
}

export function SeverityDashboard() {
  const { filters, setFilters, showEvidence } = useWorkspace();
  const [bundle, setBundle] = useState<SeverityBundle | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    Promise.all([arsia.getOverview(filters), arsia.getSeverityDistribution(filters)])
      .then(([overview, severity]) => active && (setBundle({ overview, severity }), setError("")))
      .catch(() => active && setError("Severity results could not be loaded."));
    return () => { active = false; };
  }, [filters]);

  const rows = useMemo(() => bundle?.severity.data ?? [], [bundle]);
  const totals = useMemo(() => {
    const result = new Map<string, number>();
    rows.forEach((row) => result.set(row.source ?? String(filters.source), (result.get(row.source ?? String(filters.source)) ?? 0) + row.count));
    return result;
  }, [filters.source, rows]);
  const maximum = Math.max(...rows.map((row) => row.count), 1);
  const metrics = bundle?.overview.data;
  const sourceCards = SOURCES.map((source) => {
    const crash = metrics?.crashes.bySource?.find((row) => row.source === source)?.value;
    const fatal = metrics?.fatalCrashes.bySource?.find((row) => row.source === source)?.value;
    return { source, crash, fatal, share: crash && fatal != null ? fatal / crash : null };
  }).filter((row) => filters.source === "All" || row.source === filters.source);
  const sourceBreakdown = (metric: Overview["crashes"] | undefined) =>
    filters.source === "All"
      ? metric?.bySource?.map((row) => ({ label: row.source, value: format(row.value) }))
      : undefined;

  return (
    <div className={styles.page}>
      <ReportHeader code="02 · D06" title="Severity Analysis" description="Compare source-specific severity classifications without treating state definitions as equivalent." filters={filters} onChange={setFilters} />
      {error && <div className={styles.error}>{error}</div>}
      <section className={styles.metricGrid}>
        <MetricCard icon={CarFront} label="Recorded crashes" value={format(metrics ? sumMetric(metrics.crashes) : null)} breakdown={sourceBreakdown(metrics?.crashes)} note={filters.source === "All" ? "No national total constructed" : "Source-defined events"} />
        <MetricCard icon={AlertTriangle} label="Fatal crashes" value={format(metrics ? sumMetric(metrics.fatalCrashes) : null)} breakdown={sourceBreakdown(metrics?.fatalCrashes)} note={filters.source === "All" ? "No national total constructed" : "Fatal crash events"} tone="coral" />
        <MetricCard icon={Heart} label="Lives lost" value={format(metrics ? sumMetric(metrics.livesLost) : null)} breakdown={sourceBreakdown(metrics?.livesLost)} note={filters.source === "All" ? "No national total constructed" : "Recorded deaths"} tone="coral" />
        <MetricCard icon={ShieldCheck} label="Fatal share" value={pct(metrics?.fatalShare)} breakdown={filters.source === "All" ? sourceCards.map((row) => ({ label: row.source, value: pct(row.share) })) : undefined} note="Known crash denominator" tone="green" />
      </section>

      <section className={styles.severityTop}>
        <article className={styles.panel}>
          <div className={styles.panelHeading}><div><h2>Source-specific severity distribution</h2><p>Native categories retained from D06</p></div><span>COUNT</span></div>
          <div className={styles.barList}>
            {rows.map((row, index) => {
              const fatal = /fatal/i.test(row.label);
              return <div className={styles.barRow} key={`${row.source}-${row.label}-${index}`}>
                <span>{row.source ? `${row.source} · ` : ""}{row.label}</span>
                <div><i className={fatal ? styles.fatalBar : ""} style={{ width: `${Math.max(2, row.count / maximum * 100)}%` }} /></div>
                <strong>{format(row.count)}</strong>
              </div>;
            })}
          </div>
        </article>
        <article className={styles.panel}>
          <div className={styles.panelHeading}><div><h2>Fatal share by source</h2><p>Separate denominators; no national rate</p></div></div>
          <div className={styles.ringGrid}>
            {sourceCards.map((row) => <div key={row.source}>
              <div className={styles.ring} style={{ "--ring-value": `${(row.share ?? 0) * 360}deg` } as React.CSSProperties}><span><strong>{pct(row.share)}</strong><small>{row.source}</small></span></div>
              <p>{format(row.fatal)} fatal / {format(row.crash)} crashes</p>
            </div>)}
          </div>
          <button className={styles.evidenceButton} onClick={() => showEvidence({ title: "Severity definitions", description: bundle?.severity.meta.definition ?? "Source-specific classifications.", evidence: bundle?.severity.meta.evidence, rows: rows.map((row) => ({ label: `${row.source ?? filters.source} · ${row.label}`, value: `${format(row.count)} · ${row.definition}` })) })}><Info size={15} /> View source definitions</button>
        </article>
        <article className={styles.panel}>
          <div className={styles.panelHeading}><div><h2>Definitions differ</h2><p>Preserved from each source system</p></div></div>
          <div className={styles.definitionCallout}><Info size={20} /><div><strong>Compare with caution</strong><p>Severity labels are not treated as equivalent across jurisdictions. Counts describe recorded crashes, not population-adjusted risk.</p></div></div>
          <div className={styles.definitionList}>
            {sourceCards.map(({ source }) => <div key={source}><b>{source}</b><span>{rows.filter((row) => (row.source ?? filters.source) === source).length} native categories</span></div>)}
          </div>
        </article>
      </section>

      <section className={styles.severityBottom}>
        <article className={styles.panel}>
          <div className={styles.panelHeading}><div><h2>Severity composition</h2><p>Share within each source’s own categories</p></div></div>
          <div className={styles.compositionList}>{sourceCards.map(({ source }) => {
            const sourceRows = rows.filter((row) => (row.source ?? filters.source) === source);
            const total = totals.get(source) ?? 0;
            return <div key={source}><strong>{source}</strong><div>{sourceRows.map((row, index) => <i key={row.label} title={`${row.label}: ${format(row.count)}`} className={/fatal/i.test(row.label) ? styles.fatalBar : index % 2 ? styles.midBar : ""} style={{ width: `${total ? row.count / total * 100 : 0}%` }} />)}</div></div>;
          })}</div>
        </article>
        <article className={styles.panel}>
          <div className={styles.panelHeading}><div><h2>Severity categories ranked</h2><p>Counts remain attached to their source</p></div></div>
          <div className={styles.rankedSeverity}>
            {[...rows].sort((a, b) => b.count - a.count).slice(0, 7).map((row, index) => {
              const source = row.source ?? String(filters.source);
              const total = totals.get(source) ?? 0;
              return <div key={`${source}-${row.label}-${index}`}><span>{row.label}<small>{source}</small></span><i style={{ width: `${maximum ? row.count / maximum * 100 : 0}%` }} /><strong>{total ? `${(row.count / total * 100).toFixed(1)}%` : "—"}</strong></div>;
            })}
          </div>
        </article>
      </section>

      <article className={`${styles.panel} ${styles.resultTable}`}>
        <div className={styles.panelHeading}><div><h2>D06 verified result table</h2><p>Exact published counts used in Report 02</p></div></div>
        <div className={styles.tableScroll}><table><thead><tr><th>Source</th><th>Severity category</th><th>Recorded crashes</th><th>Share within source</th><th>Definition</th></tr></thead><tbody>{rows.map((row, index) => { const source = row.source ?? String(filters.source); const total = totals.get(source) ?? 0; return <tr key={`${source}-${row.label}-${index}`}><td>{source}</td><td>{row.label}</td><td>{format(row.count)}</td><td>{total ? `${(row.count / total * 100).toFixed(1)}%` : "—"}</td><td>{row.definition}</td></tr>; })}</tbody></table></div>
      </article>
    </div>
  );
}

type RankedRegion = MapRegion & { source: Source };
interface SpatialBundle { overview: Response<Overview>; map: Response<MapData>; maps: Response<MapData>[]; }

export function SpatialDashboard() {
  const { filters, setFilters, showEvidence } = useWorkspace();
  const [bundle, setBundle] = useState<SpatialBundle | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    const sourceFilters = filters.source === "All" ? SOURCES.map((source) => selectSource(filters, source)) : [filters];
    Promise.all([arsia.getOverview(filters), arsia.getMapData(filters), Promise.all(sourceFilters.map((item) => arsia.getMapData(item)))])
      .then(([overview, map, maps]) => active && (setBundle({ overview, map, maps }), setError("")))
      .catch(() => active && setError("Spatial results could not be loaded."));
    return () => { active = false; };
  }, [filters]);

  const coverage = useMemo(() => {
    const rows = bundle?.maps.flatMap((map) => map.data.coverage ? [map.data.coverage] : []) ?? [];
    const matched = rows.reduce((sum, row) => sum + row.matched, 0);
    const unmatched = rows.reduce((sum, row) => sum + row.unmatched, 0);
    const total = matched + unmatched;
    return { matched, unmatched, total, percentage: total ? matched / total : null };
  }, [bundle]);
  const ranked = useMemo<RankedRegion[]>(() => (bundle?.maps.flatMap((map, index) => map.data.regions.map((region) => ({ ...region, source: filters.source === "All" ? SOURCES[index] : filters.source as Source }))) ?? []).sort((a, b) => b.count - a.count), [bundle, filters.source]);
  const selectedMap = bundle?.map.data;
  const regionOptions = selectedMap?.regions.map(({ id, name }) => ({ id, name })) ?? [];

  return (
    <div className={styles.page}>
      <ReportHeader code="03 · D07" title="Spatial Analysis" description="Explore official LGA aggregates while preserving unmatched records and location-policy limits." filters={filters} onChange={setFilters} lga={regionOptions} />
      {error && <div className={styles.error}>{error}</div>}
      <section className={styles.metricGrid}>
        <MetricCard icon={Database} label="Matched records" value={coverage.total ? format(coverage.matched) : "—"} note="Records matched to an LGA" tone="green" />
        <MetricCard icon={AlertTriangle} label="Unmatched records" value={coverage.total ? format(coverage.unmatched) : "—"} note="Retained outside mapped result" tone="coral" />
        <MetricCard icon={ShieldCheck} label="Coverage rate" value={pct(coverage.percentage)} note="Proportion matched to an LGA" />
        <MetricCard icon={MapPinned} label="Areas represented" value={format(ranked.length)} note="ABS 2024 reference LGAs" />
      </section>

      <section className={styles.spatialGrid}>
        <article className={`${styles.panel} ${styles.mapPanel}`}>
          <div className={styles.panelHeading}><div><h2>{filters.source === "All" ? "Source jurisdiction coverage" : "LGA crash distribution"}</h2><p>{filters.source === "All" ? "Recorded crashes by source; select a state to enter LGA view" : "Recorded crashes by LGA · not precise crash points"}</p></div><span>OFFICIAL</span></div>
          {selectedMap ? <SpatialMap
            data={selectedMap}
            onSelect={(id) => setFilters({ ...filters, regionId: id || undefined })}
            onSourceSelect={(source) => setFilters(selectSource(filters, source))}
            onShowEvidence={() => showEvidence({ title: "LGA map evidence", description: bundle?.map.meta.definition ?? "Official regional aggregate.", evidence: bundle?.map.meta.evidence, rows: [{ label: "Matched", value: format(coverage.matched) }, { label: "Unmatched", value: format(coverage.unmatched) }, { label: "Limitation", value: "LGA aggregates are not precise crash points or population-adjusted risk rates." }] })}
          /> : <div className={styles.loading}>Loading map…</div>}
        </article>
        <div className={styles.spatialSide}>
          <article className={styles.panel}>
            <div className={styles.panelHeading}><div><h2>Top LGAs by recorded crashes</h2><p>Ranked within the selected scope</p></div></div>
            <ol className={styles.ranking}>{ranked.slice(0, 10).map((region) => <li key={`${region.source}-${region.id}`}><span>{region.name} ({region.source})</span><div><i style={{ width: `${ranked[0] ? region.count / ranked[0].count * 100 : 0}%` }} /></div><strong>{format(region.count)}</strong></li>)}</ol>
          </article>
          <article className={styles.panel}>
            <div className={styles.panelHeading}><div><h2>Location coverage</h2><p>Matched versus retained unmatched records</p></div></div>
            <div className={styles.coverageBox}><div className={styles.coverageRing} style={{ "--coverage": `${(coverage.percentage ?? 0) * 360}deg` } as React.CSSProperties}><span><strong>{pct(coverage.percentage)}</strong><small>Matched</small></span></div><dl><div><dt>Matched to LGA</dt><dd>{format(coverage.matched)}</dd></div><div><dt>Unmatched</dt><dd>{format(coverage.unmatched)}</dd></div><div><dt>Total records</dt><dd>{format(coverage.total)}</dd></div></dl></div>
          </article>
        </div>
      </section>

      <article className={`${styles.panel} ${styles.resultTable}`}>
        <div className={styles.panelHeading}><div><h2>D07 spatial result table</h2><p>LGA aggregates · not precise crash points</p></div></div>
        <div className={styles.tableScroll}><table><thead><tr><th>Source</th><th>LGA</th><th>Recorded crashes</th><th>Fatal crashes</th><th>Matched status</th></tr></thead><tbody>{ranked.slice(0, 25).map((row) => <tr key={`${row.source}-${row.id}`}><td>{row.source}</td><td>{row.name}</td><td>{format(row.count)}</td><td>{format(row.fatalCrashes)}</td><td><span className={styles.matched}>Matched</span></td></tr>)}</tbody></table></div>
      </article>
    </div>
  );
}
