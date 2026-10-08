import { parseDataFilters } from "../data-catalog";
/** Pure, bounded read tools. No SQL, filesystem paths, raw records or mutations. */
import type { FunctionTool } from "openai/resources/responses/responses";
import type {
  AgentContext,
  Filters,
  Availability,
} from "../../services/contracts";
import {
  type OfficialReadService,
  type OfficialSnapshot,
} from "../official-data";


export const metricKeys = [
  "crashes",
  "fatalCrashes",
  "livesLost",
  "casualties",
] as const;
type MetricKey = (typeof metricKeys)[number];
const sourceSchema = {
  type: ["string", "null"],
  description:
    "Null uses the current page source. All returns separate source results, never a national sum.",
};
const rangeSchema = {
  type: ["object", "null"],
  properties: {
    from: { type: "string", description: "First day of a month, YYYY-MM-DD." },
    to: {
      type: "string",
      description: "Last day of a month, inclusive YYYY-MM-DD.",
    },
  },
  required: ["from", "to"],
  additionalProperties: false,
  description:
    "Null uses page dates. Explicit ranges do not change page filters.",
};
const filtersSchema = { source: sourceSchema, dateRange: rangeSchema };
const define = (
  name: string,
  description: string,
  properties: Record<string, unknown>,
): FunctionTool => ({
  type: "function",
  name,
  description,
  strict: true,
  parameters: {
    type: "object",
    properties,
    required: Object.keys(properties),
    additionalProperties: false,
  },
});
export const analysisTools: FunctionTool[] = [
  define("monthly_contributions", "Compare each selected month with the same month one year earlier. Returns code-calculated changes and contributions to the net change, plus a chart. Choose one calendar year for a 12-month decomposition. Nulls and unsupported coverage are not zero-filled.", { ...filtersSchema, metric: { type: "string", enum: metricKeys } }),
  define(
    "regional_analysis",
    "Inspect real LGA name-matched crash counts and coverage. regionId null lists LGAs and ABS codes for one source; a returned code queries that area's metrics, monthly trend, severity and top source locality labels. LGA is NOT a whole city or accident point. Do not invent area codes. This query does not change page filters.",
    { ...filtersSchema, regionId: { type: ["string", "null"], description: "An ABS 2024 LGA code returned by this tool, or null to list areas." } },
  ),
  define(
    "dataset_metadata",
    "Get metric definitions, coverage and source restrictions (including unavailable fields, map locations and causal analysis).",
    { source: sourceSchema },
  ),
  define(
    "core_metrics",
    "Read four core metrics, source-specific definitions and code-calculated fatal-crash percentage. No national total.",
    filtersSchema,
  ),
  define(
    "time_series",
    "Read monthly/yearly counts for one metric, with code-calculated adjacent-period changes. Years can be partial; use compare_periods for controlled comparisons.",
    {
      ...filtersSchema,
      granularity: { type: "string", enum: ["monthly", "yearly"] },
      metric: { type: "string", enum: metricKeys },
    },
  ),
  define(
    "compare_periods",
    "Compare four metrics in equal-length, non-overlapping whole-month periods. dateRange is the current period. baseline null means the same months one year earlier (YoY). Results include code-calculated delta and percent; no extrapolation outside coverage.",
    { ...filtersSchema, baseline: rangeSchema },
  ),
  define(
    "severity_distribution",
    "Read native severity counts and code-calculated shares; Capabilities and supported date ranges vary by source; obey returned availability. Never allocate full-period counts proportionally.",
    filtersSchema,
  ),
  define(
    "source_evidence",
    "Read verified batch identity, integrity hashes, QA and publication limitations for the current snapshot.",
    { source: sourceSchema },
  ),
];
export const toolTitles: Record<string, string> = {
  monthly_contributions: "Monthly contributions to change",
  regional_analysis: "LGA counts & location coverage",
  dataset_metadata: "Dataset definitions & coverage",
  core_metrics: "Core metrics",
  time_series: "Trend analysis",
  compare_periods: "Period comparison",
  severity_distribution: "Severity distribution",
  source_evidence: "Snapshot provenance & QA",
};
export function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw Error("Expected an object.");
  return value as Record<string, unknown>;
}
function exact(value: unknown, keys: string[]) {
  const obj = object(value);
  if (
    Object.keys(obj).some((k) => !keys.includes(k)) ||
    keys.some((k) => !(k in obj))
  )
    throw Error("Unexpected or missing tool argument.");
  return obj;
}
function range(
  value: unknown,
  fallback: Filters["dateRange"],
): Filters["dateRange"] {
  if (value === null) return fallback;
  const r = exact(value, ["from", "to"]);
  if (typeof r.from !== "string" || typeof r.to !== "string")
    throw Error("Dates must be ISO strings.");
  return { from: r.from, to: r.to };
}
function selection(value: unknown, context: AgentContext): Filters["source"] {
  if (value === null) return context.filters.source;
  if (typeof value !== "string" || !/^[A-Za-z0-9_.-]{1,100}$/.test(value))
    throw Error("Unsupported source. Choose a source returned by dataset_metadata.");
  return value as Filters["source"];
}
function filters(
  args: Record<string, unknown>,
  context: AgentContext,
): Filters {
  const r = range(args.dateRange, context.filters.dateRange);
  return parseDataFilters(
    new URLSearchParams({
      source: selection(args.source, context),
      ...(context.filters.regionId && selection(args.source, context) === context.filters.source ? { regionId: context.filters.regionId } : {}),
      from: r.from,
      to: r.to,
      datasetVersion: context.filters.datasetVersion,
      batchId: context.filters.batchId,
    }),
  );
}
const monthNumber = (s: string) =>
  Number(s.slice(0, 4)) * 12 + Number(s.slice(5, 7)) - 1;
const months = (r: Filters["dateRange"]) =>
  monthNumber(r.to) - monthNumber(r.from) + 1;
export function priorYear(r: Filters["dateRange"]): Filters["dateRange"] {
  const from = `${Number(r.from.slice(0, 4)) - 1}${r.from.slice(4)}`;
  const end = new Date(
    Date.UTC(Number(r.to.slice(0, 4)) - 1, Number(r.to.slice(5, 7)), 0),
  )
    .toISOString()
    .slice(0, 10);
  return { from, to: end };
}
const round = (value: number, digits = 2) =>
  Math.round(value * 10 ** digits) / 10 ** digits;
export function change(current: number | null, baseline: number | null) {
  return {
    current,
    baseline,
    difference:
      current === null || baseline === null ? null : current - baseline,
    percentChange:
      current === null || baseline === null || baseline === 0
        ? null
        : round(((current - baseline) / baseline) * 100),
    percentReason:
      baseline === 0
        ? "Zero baseline: percentage change is undefined."
        : current === null || baseline === null
          ? "Unknown or unavailable observation."
          : null,
  };
}
function observedRange(f: Filters, coverage: Filters["dateRange"]) {
  const from =
    f.dateRange.from > coverage.from ? f.dateRange.from : coverage.from;
  const to = f.dateRange.to < coverage.to ? f.dateRange.to : coverage.to;
  return from <= to ? { from, to } : null;
}
function calendarMonth(period: string): Filters["dateRange"] {
  return { from: `${period}-01`, to: new Date(Date.UTC(Number(period.slice(0, 4)), Number(period.slice(5, 7)), 0)).toISOString().slice(0, 10) };
}
function coversRange(coverage: Filters["dateRange"], period: Filters["dateRange"]) {
  return coverage.from <= period.from && coverage.to >= period.to;
}
export async function executeAnalysisTool(
  name: string,
  raw: unknown,
  context: AgentContext,
  service: OfficialReadService,
  snapshot: OfficialSnapshot,
) {
  const tool = analysisTools.find((t) => t.name === name);
  if (!tool) throw Error("Unknown read-only tool.");
  const args = exact(raw, Object.keys(tool.parameters!.properties as object));
  const src = selection(args.source, context);
  const datasetsInRelease = await service.getDatasetMetadata();
  const sources = datasetsInRelease.map(d => d.source);
  if (src !== "All" && !sources.includes(src)) throw Error("Source is not in the selected release.");
  const selected = src === "All" ? sources : [src];
  const identity = {
    datasetVersion: snapshot.provenance.version,
    batchId: snapshot.provenance.batchId,
    releaseId: context.filters.releaseId,
    sourceBatches: Object.fromEntries(datasetsInRelease.map(d=>[d.source,d.sourceBatchId || d.batchId])),
    dataMode: context.filters.releaseId ? "pinned local release" : "project data snapshot",
    liveDatabase: false,
  };
  if (name === "dataset_metadata" || name === "source_evidence") {
    const datasets = (await service.getDatasetMetadata()).filter((d) =>
      selected.includes(d.source),
    );
    return {
      ...identity,
      source: src,
      coverage: snapshot.provenance.coverage,
      datasets,
      ...(name === "source_evidence"
        ? {
            qa: snapshot.provenance.qa,
            evidenceHashes: snapshot.provenance.evidenceHashes,
            recordedAt: snapshot.provenance.recordedAt,
            publicationStatus: snapshot.provenance.publicationStatus,
          }
        : {}),
      limitations: [
        "No national pooled counts or exposure-adjusted interstate risk comparisons.",
        "No exact crash coordinates, raw person/vehicle records, or causal evidence are exposed. Rounded coordinate cells require trusted published geographic capability; LGA name-based aggregates are a separate derived extension.",
        "QA location is limited. Independent member sign-off and final platform acceptance are pending.",
      ],
    };
  }
  const f = filters(args, context);
  const scope = {
    ...identity,
    source: f.source,
    regionId: f.regionId || null,
    requestedRange: f.dateRange,
    observedRange: observedRange(f, snapshot.provenance.coverage),
    outsidePageRange:
      f.dateRange.from !== context.filters.dateRange.from ||
      f.dateRange.to !== context.filters.dateRange.to,
    pageRange: context.filters.dateRange,
  };
  if (name === "monthly_contributions") {
    if (!metricKeys.includes(args.metric as MetricKey)) throw Error("Unknown metric.");
    const metric = args.metric as MetricKey;
    const baseline = priorYear(f.dateRange);
    const results = await Promise.all(selected.map(async source => {
      const [current, previous] = await Promise.all([service.getTimeSeries({ ...f, source }, "monthly"), service.getTimeSeries({ ...f, source, dateRange: baseline }, "monthly")]);
      const rows = current.data.map(p => {
        const baselinePeriod = `${Number(p.period.slice(0, 4)) - 1}${p.period.slice(4)}`;
        const b = previous.data.find(q => q.period === baselinePeriod);
        const covered = current.meta.availability === "available" && previous.meta.availability === "available" && coversRange(current.meta.coverage, calendarMonth(p.period)) && coversRange(previous.meta.coverage, calendarMonth(baselinePeriod));
        return { source, period: p.period, baselinePeriod, ...change(p[metric], b?.[metric] ?? null), ...(!covered ? { difference: null, percentChange: null, percentReason: "Both matching months must be fully covered by this source." } : {}) };
      });
      const complete = rows.length === months(f.dateRange) && rows.every(r => r.difference !== null);
      const netChange = complete ? rows.reduce((sum,r) => sum + r.difference!, 0) : null;
      return { source, meta: current.meta, baselineMeta: previous.meta, availability: complete ? "available" : "no_results", netChange, rows: rows.map(r => ({ ...r, contributionToNetPercent: netChange === null || netChange === 0 || r.difference === null ? null : round(r.difference / netChange * 100) })) };
    }));
    return { ...scope, metric, baselineRange: baseline, calculation: "difference = current − matching prior-year month; contribution = difference / netChange × 100. Contributions can be negative or exceed 100%; unavailable values remain null.", results };
  }
  if (name === "regional_analysis") {
    if (src === "All") return { ...scope, availability: "unsupported", reason: "Choose one source; LGA counts are source-specific." };
    if (args.regionId !== null && typeof args.regionId !== "string") throw Error("Invalid region code.");
    const regional = parseDataFilters(new URLSearchParams({
      source: src, from: f.dateRange.from, to: f.dateRange.to,
      datasetVersion: f.datasetVersion, batchId: f.batchId,
      ...(args.regionId ? { regionId: args.regionId as string } : {}),
    }));
    const map = await service.getMapData(regional);
    const region = map.data.regions.find(r => r.id === regional.regionId);
    if (!regional.regionId) return { ...scope, regionId: null, meta: map.meta, matchingCoverage: map.data.coverage, areas: map.data.regions.map(({ id, name, count, fatalCrashes }) => ({ id, name, count, fatalCrashes })) };
    const [overview, trend, severity] = await Promise.all([
      service.getOverview(regional), service.getTimeSeries(regional, "monthly"), service.getSeverityDistribution(regional),
    ]);
    return { ...scope, regionId: regional.regionId, regionName: region?.name, matchingCoverage: map.data.coverage,
      results: [{ source: src, ...overview }], trend, severity, localities: region?.localities || [],
      localityNote: "Top source-reported Town/Suburb labels within this LGA, not city boundaries or accident coordinates. VIC has no admitted locality field.",
    };
  }
  if (name === "core_metrics") {
    const results = await Promise.all(
      selected.map(async (source) => {
        const response = await service.getOverview({ ...f, source });
        return {
          source,
          ...response,
          fatalSharePercent:
            response.data.fatalShare === null
              ? null
              : round(response.data.fatalShare * 100),
        };
      }),
    );
    return { ...scope, results };
  }
  if (name === "time_series") {
    if (args.granularity !== "yearly" && args.granularity !== "monthly")
      throw Error("Invalid granularity.");
    if (!metricKeys.includes(args.metric as MetricKey))
      throw Error("Invalid metric.");
    const granularity = args.granularity,
      metric = args.metric as MetricKey;
    const results = await Promise.all(
      selected.map(async (source) => {
        const response = await service.getTimeSeries(
          { ...f, source },
          granularity,
        );
        const observed = observedRange({ ...f, source }, response.meta.coverage);
        const points = observed ? response.data.map((r) => {
          const periodFrom =
            granularity === "yearly" ? `${r.period}-01-01` : `${r.period}-01`;
          const periodTo =
            granularity === "yearly"
              ? `${r.period}-12-31`
              : new Date(
                  Date.UTC(
                    Number(r.period.slice(0, 4)),
                    Number(r.period.slice(5)),
                    0,
                  ),
                )
                .toISOString()
                .slice(0, 10);
          const requestedPeriod = { from: periodFrom > f.dateRange.from ? periodFrom : f.dateRange.from, to: periodTo < f.dateRange.to ? periodTo : f.dateRange.to };
          return {
            period: r.period,
            value: r[metric],
            from: periodFrom > observed.from ? periodFrom : observed.from,
            to: periodTo < observed.to ? periodTo : observed.to,
            coverageComplete: coversRange(response.meta.coverage, requestedPeriod) && (granularity !== "yearly" || r.observedMonths === undefined || r.observedMonths === months(requestedPeriod)),
          };
        }) : [];
        return {
          source,
          meta: response.meta,
          metric,
          points: points.map((p, i) => {
            const prev = points[i - 1];
            const comparable = !!prev && p.coverageComplete && prev.coverageComplete && months(p) === months(prev) && (granularity !== "yearly" || (p.from.slice(5,7) === prev.from.slice(5,7) && p.to.slice(5,7) === prev.to.slice(5,7)));
            return {
              ...p,
              previousPeriodChange: comparable
                ? change(p.value, prev.value)
                : null,
              comparisonNote: comparable
                ? "Adjacent recorded periods; not a causal or exposure-adjusted estimate."
                : "No equally covered previous period.",
            };
          }),
        };
      }),
    );
    return { ...scope, granularity, results };
  }
  if (name === "severity_distribution") {
    const results = await Promise.all(
      selected.map(async (source) => {
        const response = await service.getSeverityDistribution({
          ...f,
          source,
        });
        const total = response.data.reduce((a, r) => a + r.count, 0);
        return {
          source,
          meta: response.meta,
          data: response.data.map((r) => ({
            ...r,
            sharePercent: total > 0 ? round((r.count / total) * 100, 4) : null,
          })),
          total: response.meta.availability === "available" ? total : null,
        };
      }),
    );
    return { ...scope, results };
  }
  const baseline = range(args.baseline, priorYear(f.dateRange));
  const bf = filters({ ...args, dateRange: baseline }, context);
  const comparable =
    months(f.dateRange) === months(baseline) &&
    (baseline.to < f.dateRange.from || baseline.from > f.dateRange.to);
  if (!comparable)
    return {
      ...scope,
      baselineRange: baseline,
      availability: "unsupported",
      reason:
        "Comparison requires equal-length, non-overlapping whole-month periods. Choose comparable dates.",
    };
  const yoy =
    JSON.stringify(priorYear(f.dateRange)) === JSON.stringify(baseline);
  const results = await Promise.all(
    selected.map(async (source) => {
      const [current, previous] = await Promise.all([
        service.getOverview({ ...f, source }),
        service.getOverview({ ...bf, source }),
      ]);
      return {
        source,
        meta: current.meta,
        baselineMeta: previous.meta,
        metrics: metricKeys.map((metric) => {
          const c = current.data[metric],
            b = previous.data[metric];
          const availability: Availability =
            !current.meta.coverage.complete || !previous.meta.coverage.complete
              ? "no_results"
              : c.availability !== "available"
                ? c.availability
                : b.availability;
          return {
            metric,
            unit: c.unit,
            definition: c.definition,
            availability,
            ...change(
              availability === "available" ? c.value : null,
              availability === "available" ? b.value : null,
            ),
            reason:
              availability === "no_results"
                ? "Both comparison periods must be fully covered; partial coverage is not extrapolated."
                : c.reason || b.reason,
          };
        }),
      };
    }),
  );
  return {
    ...scope,
    baselineRange: baseline,
    comparison: yoy ? "year_on_year" : "equal_month_count",
    seasonalCaveat: !yoy
      ? "Equal duration alone does not control seasonality or exposure."
      : null,
    results,
  };
}
