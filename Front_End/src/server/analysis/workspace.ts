import { hasRegionalProvider } from '../../services/catalog-contracts';
import { parseDataFilters } from "../data-catalog";
import { SNAPSHOT_CATALOG, type DataCatalog } from "../../services/catalog-contracts";
/** Authorized, aggregate-only analytical workspace. No SQL or caller-selected file paths. */
import type { FunctionTool } from "openai/resources/responses/responses";
import type { AgentContext, Filters, Provenance } from "../../services/contracts";
import type {
  AnalysisArtifact,
  AnalysisRow,
  AnalysisView,
} from "../../services/analysis-contracts";
import {
  type OfficialReadService,
} from "../official-data";
import type { RegionSnapshot } from "../region-data";
import { saveArtifact } from "./artifacts";
import { runPython } from "./sandbox";

const metrics = ["crashes", "fatalCrashes", "livesLost", "casualties"];
const dimensions = [
  "source",
  "period",
  "year",
  "month",
  "regionId",
  "regionName",
  "locality",
  "longitude",
  "latitude",
];
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
const str = (values: string[]) => ({ type: "string", enum: values });
const nullableString = { type: ["string", "null"] };
export const workspaceTools: FunctionTool[] = [
  define(
    "workspace_catalog",
    "Discover the authorized analytical tables, field dictionary, verified joins, coverage and source restrictions before using workspace_query or Python.",
    {},
  ),
  define(
    "workspace_query",
    'Read aggregate tables with validated filters, grouping, sums and rankings. Always separates sources. Source/date null inherit page; regionId null inherits page area, "all" removes area restriction explicitly, or use a discovered ABS code. WHERE filters apply BEFORE grouping. A queryId retains up to 10,000 result rows locally for Python/chart tools; only the first 12 rows go to the model. Empty groupBy returns native rows. Data are sparse: missing rows are not imputed as zeros.',
    {
      dataset: str(["monthly_metrics", "yearly_metrics", "lga_monthly", "locality_monthly", "geographic_cells"]),
      source: { type: ["string", "null"], description: "A source identifier from workspace_catalog, All, or null." },
      dateRange: {
        type: ["object", "null"],
        properties: { from: { type: "string" }, to: { type: "string" } },
        required: ["from", "to"],
        additionalProperties: false,
      },
      regionId: nullableString,
      groupBy: { type: "array", items: str(dimensions), maxItems: 5 },
      metrics: { type: "array", items: str(metrics), minItems: 1, maxItems: 4 },
      where: {
        type: "array",
        maxItems: 6,
        items: {
          type: "object",
          properties: {
            field: str([...dimensions, ...metrics]),
            operator: str(["eq", "contains", "gte", "lte"]),
            value: { type: ["string", "number"] },
          },
          required: ["field", "operator", "value"],
          additionalProperties: false,
        },
      },
      orderBy: {
        type: ["object", "null"],
        properties: {
          field: { type: "string" },
          direction: str(["asc", "desc"]),
        },
        required: ["field", "direction"],
        additionalProperties: false,
      },
      limit: { type: "integer", minimum: 1, maximum: 10000 },
    },
  ),
  define(
    "present_analysis",
    'Display an ECharts bar/line chart or a table from an existing workspace_query result (never model-invented data). Returns CSV download. For All, use series="source" so states remain distinct; never sum states. At most 100 rows are rendered.',
    {
      queryId: { type: "string" },
      kind: str(["bar", "line", "table"]),
      title: { type: "string" },
      x: { type: "string" },
      y: { type: "string" },
      series: nullableString,
    },
  ),
  define(
    "python_analysis",
    'Write/run/repair Python in an isolated, offline container with pandas/numpy/matplotlib. First query data; queryIds must refer to this turn. json.load(open("/data/input.json")) returns {queries:{Q1:{rows,provenance}},context}. /data is read-only. Write named CSV/JSON/PNG/PDF/MD/TXT files ONLY to /analysis. Print computed results for the answer. Code is automatically downloadable. Use present_analysis for ordinary interactive charts. Preserve source distinctions, nulls and provenance; no invented numbers or pooled state totals. On failure use returned error to fix code, maximum 3 runs/turn, 30 seconds/run. No internet, secrets or host filesystem. Read actual evidence IDs from input.evidenceIds and queries[queryId].evidenceId; never guess them. Use real line breaks in reports. Only final successful files are published.',
    {
      queryIds: {
        type: "array",
        items: { type: "string" },
        minItems: 1,
        maxItems: 5,
      },
      title: { type: "string" },
      code: { type: "string" },
    },
  ),
];
export const workspaceTitles: Record<string, string> = {
  workspace_catalog: "Workspace & field dictionary",
  workspace_query: "Aggregate query",
  present_analysis: "Chart & table",
  python_analysis: "Python analysis",
};
export class AnalysisInputError extends Error {}
const invalid = (message: string): never => {
  throw new AnalysisInputError(message);
};
function obj(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value))
    return invalid("Expected an object.");
  return value as Record<string, unknown>;
}
function exact(value: unknown, keys: string[]) {
  const o = obj(value);
  if (
    Object.keys(o).some((k) => !keys.includes(k)) ||
    keys.some((k) => !(k in o))
  )
    invalid("Unexpected or missing tool arguments.");
  return o;
}
function safeText(v: unknown, max = 100): string {
  if (typeof v !== "string" || !v.trim() || v.length > max)
    return invalid(`Text must be 1–${max} characters.`);
  return v;
}
function list(v: unknown, allowed: string[], max: number): string[] {
  if (
    !Array.isArray(v) ||
    v.length > max ||
    v.some((x) => typeof x !== "string" || !allowed.includes(x)) ||
    new Set(v).size !== v.length
  )
    return invalid(`Use distinct fields from: ${allowed.join(", ")}.`);
  return v;
}
function csv(rows: AnalysisRow[]) {
  const fields = Object.keys(rows[0] || {});
  const quote = (v: unknown) =>
    `"${String(v ?? "")
      .replace(/^[=+@\-\t\r]/, (m) => `'${m}`)
      .replaceAll('"', '""')}"`;
  return [
    fields.map(quote).join(","),
    ...rows.map((row) => fields.map((f) => quote(row[f])).join(",")),
  ].join("\n");
}
const sum = (rows: AnalysisRow[], key: string) =>
  rows.some((r) => r[key] === null)
    ? null
    : rows.reduce((n, r) => n + Number(r[key]), 0);
interface SavedQuery {
  rows: AnalysisRow[];
  provenance: Record<string, unknown>;
  truncated: boolean;
  evidenceId: string;
}
export class AnalysisWorkspace {
  private queries = new Map<string, SavedQuery>();
  private pythonRuns = 0;
  private outputs = 0;
  private evidenceIds = new Set<string>();
  recordEvidence(id: string) {
    this.evidenceIds.add(id);
  }
  constructor(
    private context: AgentContext,
    private service: OfficialReadService,
    private regional: RegionSnapshot,
    private dataCatalog: DataCatalog = SNAPSHOT_CATALOG,
  ) {}
  async execute(
    name: string,
    raw: unknown,
    signal: AbortSignal,
    evidenceId: string,
  ): Promise<Record<string, unknown>> {
    signal.throwIfAborted();
    const tool = workspaceTools.find((t) => t.name === name);
    if (!tool) return invalid("Unknown workspace tool.");
    const args = exact(raw, Object.keys(tool.parameters!.properties as object));
    if (name === "workspace_catalog") return this.catalog();
    if (name === "workspace_query") return this.query(args, evidenceId);
    if (name === "present_analysis") return this.present(args, evidenceId);
    return this.python(args, signal, evidenceId);
  }
  private async catalog() {
    return {
      source: this.context.filters.source,
      batchId: this.context.filters.batchId,
      releaseId: this.context.filters.releaseId,
      dataMode: this.context.filters.releaseId ? "pinned local release" : "project data snapshot",
      coverage: this.dataCatalog.coverage,
      datasets: [
        { id: "geographic_cells", grain: "one source + trusted rounded longitude/latitude cell within the requested dates", dimensions: ["source", "longitude", "latitude"], metrics: ["crashes"], definition: "Single-source crash counts at 0.1-degree precision. Not exact crash sites or ABS regions. Returned cells may be truncated; inspect coordinateCoverage before claiming a complete geographic total. Other metrics and region filters are unsupported." },
        { id:"yearly_metrics", grain:"one source and reported year; preserves annual precision without creating months", dimensions:["source","period","year"], metrics, definition:"Direct yearly provider observations; partial coverage is recorded, and months are not inferred." },
        {
          id: "monthly_metrics",
          grain:
            "one source and observed month, scoped to the page LGA when selected",
          dimensions: ["source", "period", "year", "month"],
          metrics,
          definition:
            "Reuses the current official/regional service; counts retain native source definitions.",
        },
        {
          id: "lga_monthly",
          grain: "source + period + regionId; sparse monthly counts",
          dimensions: [
            "source",
            "period",
            "year",
            "month",
            "regionId",
            "regionName",
          ],
          metrics,
          definition:
            "Name-matched LGA aggregates. __unmatched__ is retained; LGA is not a metropolitan city. Do not interpret counts as risk rates.",
        },
        {
          id: "locality_monthly",
          grain: "source + period + regionId + locality; sparse monthly counts",
          dimensions: dimensions.slice(0, 7),
          metrics: ["crashes"],
          definition:
            "NSW Town and QLD Loc_Suburb native text labels. VIC locality is not connected. These are not validated geographic city polygons.",
        },
      ],
      fieldDictionary: {
        source: "An identifier from sources; never pool overlapping datasets or incompatible definitions",
        period: "YYYY-MM for monthly data; YYYY for yearly observations",
        year: "YYYY",
        month: "01…12",
        regionId: "ABS 2024 LGA code or __unmatched__",
        regionName: "Verified state-scoped many-to-one name lookup",
        locality: "Source-reported Town/Loc_Suburb text, not geocoded",
        longitude: "Rounded WGS84 cell centre longitude; not an exact crash location",
        latitude: "Rounded WGS84 cell centre latitude; not an exact crash location",
        crashes: "Source-defined crash counts; consult that source's metricDefinitions and retain its event scope",
        fatalCrashes: "Source-defined fatal crash events; never substitute death counts or infer from an unspecified severity label",
        livesLost: "Source-reported deaths, distinct from fatal crashes; retain null when this measure is not established",
        casualties:
          "Native source injury/death definition; preserve null as unknown",
      },
      verifiedJoins: [
        {
          left: "lga_monthly or locality_monthly",
          right: "region catalog",
          keys: ["source", "regionId"],
          cardinality: "many-to-one",
          checks:
            "Unique catalog keys, no fact multiplication, unmatched rows retained",
        },
        {
          left: "VIC Accident",
          right: "VIC Node (precomputed upstream)",
          keys: ["ACCIDENT_NO", "NODE_ID"],
          checks:
            "Conflicting/ambiguous LGAs excluded; agreeing duplicate nodes collapsed before aggregation; monthly totals reconciled",
        },
      ],
      limitations: {
        notConnected: [
          "VIC locality labels",
          "Exposure/population denominators",
          "Weather and causal variables",
        ],
        notVerified: [
          "New or unreviewed datum conversions; geographic_cells only exposes already verified rounded aggregates",
          "Metropolitan city crosswalks",
          "Arbitrary joins",
        ],
        notExposed: ["Raw crash identifiers", "Exact crash coordinates", "Person or vehicle records"],
        noResults:
          "A supported query can return no observations; absence is not automatically zero.",
      },
      sources: await this.service.getDatasetMetadata(),
      sourceCapabilities: this.dataCatalog.sources.map(s=>({source:s.source,origin:s.origin,coverage:s.coverage,capabilities:s.capabilities})),
      python: {
        packages: ["pandas 2.2.3", "numpy 2.2.6", "matplotlib 3.10.3"],
        input: "/data/input.json",
        output: "/analysis",
        limits:
          "3 runs/turn; 30s wall/20s CPU; 512MB; offline; 8MB outputs/run; files expire in 24h",
      },
    };
  }
  private filters(a: Record<string, unknown>): Filters {
    if (a.source !== null && ![...this.dataCatalog.sources.map(s => s.source), "All"].includes(a.source as string))
      return invalid("Unsupported source.");
    const source = (a.source ??
      this.context.filters.source) as Filters["source"];
    const date =
      a.dateRange === null
        ? this.context.filters.dateRange
        : exact(a.dateRange, ["from", "to"]);
    const region =
      a.regionId === null
        ? source === this.context.filters.source
          ? this.context.filters.regionId
          : undefined
        : a.regionId === "all"
          ? undefined
          : safeText(a.regionId, 30);
    try {
      return parseDataFilters(
        new URLSearchParams({
          source,
          from: safeText(date.from, 10),
          to: safeText(date.to, 10),
          batchId: this.context.filters.batchId,
      ...(this.context.filters.releaseId ? { releaseId: this.context.filters.releaseId } : {}),
          datasetVersion: this.context.filters.datasetVersion,
          ...(region ? { regionId: region } : {}),
        }),
      );
    } catch {
      return invalid(
        "Use a valid source, source-specific LGA code and whole-month date range.",
      );
    }
  }
  private async query(a: Record<string, unknown>, evidenceId: string) {
    const dataset = safeText(a.dataset),
      f = this.filters(a);
    if (
      !["monthly_metrics", "yearly_metrics", "lga_monthly", "locality_monthly", "geographic_cells"].includes(dataset)
    )
      return invalid("Unknown dataset; use workspace_catalog.");
    const availableDimensions =
      dataset === "geographic_cells" ? ["source", "longitude", "latitude"] : dataset === "yearly_metrics" ? dimensions.slice(0,3) : dataset === "monthly_metrics"
        ? dimensions.slice(0, 4)
        : dataset === "lga_monthly"
          ? dimensions.slice(0, 6)
          : dimensions.slice(0, 7);
    const selectedMetrics = list(
      a.metrics,
      dataset === "locality_monthly" ? ["crashes"] : metrics,
      4,
    );
    if (!selectedMetrics.length) return invalid("Select at least one metric.");
    if (dataset === "geographic_cells" && (f.source === "All" || f.regionId || selectedMetrics.some(metric => metric !== "crashes"))) return { source: f.source, releaseId: f.releaseId, batchId: f.batchId, datasetVersion: f.datasetVersion, requestedRange: f.dateRange, availability: "unsupported", reason: "Coordinate cells support one source and crash counts only, without an ABS region filter.", preview: [] };
    const group = list(a.groupBy, availableDimensions, 5);
    const predicates = Array.isArray(a.where)
      ? a.where
      : invalid("where must be an array.");
    if (predicates.length > 6) return invalid("At most six predicates.");
    const where = predicates.map((raw) => {
      const p = exact(raw, ["field", "operator", "value"]);
      if (
        ![
          ...availableDimensions,
          ...(dataset === "locality_monthly" ? ["crashes"] : metrics),
        ].includes(p.field as string) ||
        !["eq", "contains", "gte", "lte"].includes(p.operator as string) ||
        !["string", "number"].includes(typeof p.value) ||
        String(p.value).length > 100
      )
        invalid("Invalid field or predicate.");
      return p;
    });
    if (
      !Number.isInteger(a.limit) ||
      Number(a.limit) < 1 ||
      Number(a.limit) > 10000
    )
      return invalid("limit must be 1–10,000.");
    const sources = f.source === "All" ? this.dataCatalog.sources.map(s => s.source) : [f.source];
    let rows: AnalysisRow[] = [];
    const sourceAvailability: {source:string;meta:Provenance}[] = [];
    let coordinateCoverage: Omit<NonNullable<import("../../services/contracts").MapData["pointGrid"]>, "cells"> | undefined;
    for (const source of sources) {
      const scope = { ...f, source };
      if (dataset === "geographic_cells") {
        const result = await this.service.getMapData(scope);
        sourceAvailability.push({source,meta:result.meta});
        if (result.data.pointGrid) {
          const {cells, ...coverage} = result.data.pointGrid;
          coordinateCoverage = coverage;
          rows.push(...cells.map(cell => ({source,longitude:cell.longitude,latitude:cell.latitude,crashes:cell.count})));
        }
      } else if (dataset === "monthly_metrics" || dataset === "yearly_metrics") {
        const result = await this.service.getTimeSeries(scope, dataset === "yearly_metrics" ? "yearly" : "monthly");
        sourceAvailability.push({source,meta:result.meta});
        rows.push(
          ...result.data.map((p) => ({
            source,
            period: p.period,
            year: p.period.slice(0, 4),
            month: p.period.slice(5, 7),
            crashes: p.crashes,
            fatalCrashes: p.fatalCrashes,
            livesLost: p.livesLost,
            casualties: p.casualties,
          })),
        );
      } else {
        if (!hasRegionalProvider(this.dataCatalog.sources.find(s => s.source === source),this.dataCatalog.releaseId)) return invalid("Regional aggregate capability is not available for this published source. Use monthly_metrics.");
        // Apply the same publication reconciliation and coverage gate as the map API.
        const proof = await this.service.getMapData(scope);
        if (proof.meta.availability !== "available" || !proof.meta.coverage.complete) return invalid("Regional aggregate coverage is unavailable for this selection.");
        sourceAvailability.push({source,meta:proof.meta});
        const data = this.regional.sources[source];
        if (!data) return invalid("Regional aggregate capability is unavailable.");
        const names = new Map(data.regions.map((r) => [r.id, r.name]));
        if (names.size !== data.regions.length)
          throw Error("Regional join integrity failure");
        names.set("__unmatched__", "Unmatched area");
        const accepted = (p: string, id: string) =>
          p >= f.dateRange.from.slice(0, 7) &&
          p <= f.dateRange.to.slice(0, 7) &&
          (!f.regionId || id === f.regionId);
        const dims = (p: string, id: string) => {
          if (!names.has(id)) throw Error("Unknown regional join key");
          return {
            source,
            period: p,
            year: p.slice(0, 4),
            month: p.slice(5, 7),
            regionId: id,
            regionName: names.get(id)!,
          };
        };
        if (dataset === "lga_monthly")
          rows.push(
            ...data.rows
              .filter((r) => accepted(r[0], r[1]))
              .map(([p, id, crashes, fatalCrashes, livesLost, casualties]) => ({
                ...dims(p, id),
                crashes,
                fatalCrashes,
                livesLost,
                casualties,
              })),
          );
        else
          rows.push(
            ...data.localities
              .filter((r) => accepted(r[0], r[1]))
              .map(([p, id, locality, crashes]) => ({
                ...dims(p, id),
                locality,
                crashes,
              })),
          );
      }
    }
    rows = rows.filter((row) =>
      where.every((p) => {
        const value = row[p.field as string],
          target = p.value as string | number;
        if (value === null || value === undefined) return false;
        if (p.operator === "contains")
          return (
            typeof value === "string" &&
            value.toLowerCase().includes(String(target).toLowerCase())
          );
        if (p.operator === "eq")
          return typeof value === typeof target && value === target;
        if (typeof value !== typeof target) return false;
        return p.operator === "gte" ? value >= target : value <= target;
      }),
    );
    const observedRows = rows.length;
    const observedPeriods = [
      ...new Set(rows.flatMap((r) => typeof r.period === "string" ? [r.period] : [])),
    ].sort();
    const observedRange = observedPeriods.length
      ? { from: observedPeriods[0], to: observedPeriods.at(-1) }
      : null;
    let keys = availableDimensions;
    if (group.length) {
      keys = [...new Set(["source", ...group])]; // source is non-removable: no accidental national aggregation.
      const groups = new Map<string, AnalysisRow[]>();
      for (const row of rows) {
        const key = JSON.stringify(keys.map((k) => row[k]));
        const bucket = groups.get(key) || [];
        bucket.push(row);
        groups.set(key, bucket);
      }
      rows = [...groups.values()].map((bucket) => ({
        ...Object.fromEntries(keys.map((k) => [k, bucket[0][k]])),
        ...Object.fromEntries(selectedMetrics.map((k) => [k, sum(bucket, k)])),
      }));
    } else
      rows = rows.map((row) =>
        Object.fromEntries(
          [...keys, ...selectedMetrics].map((k) => [k, row[k]]),
        ),
      );
    if (a.orderBy !== null) {
      const order = exact(a.orderBy, ["field", "direction"]);
      const field = safeText(order.field);
      if (
        ![...keys, ...selectedMetrics].includes(field) ||
        !["asc", "desc"].includes(order.direction as string)
      )
        return invalid("Sort by a selected dimension or metric.");
      rows.sort((a, b) => {
        if (a.source !== b.source)
          return String(a.source).localeCompare(String(b.source));
        if (a[field] === null) return 1;
        if (b[field] === null) return -1;
        const d =
          typeof a[field] === "number" && typeof b[field] === "number"
            ? Number(a[field]) - Number(b[field])
            : String(a[field]).localeCompare(String(b[field]));
        return (
          d * (order.direction === "desc" ? -1 : 1) ||
          JSON.stringify(a).localeCompare(JSON.stringify(b))
        );
      });
    }
    const resultRows = rows.length;
    rows = rows.slice(0, Number(a.limit));
    const queryId = `Q${this.queries.size + 1}`;
    const notes = [
      "Sources remain separate. Counts are not population/exposure-adjusted risk.",
      ...(dataset === "geographic_cells" ? ["Rounded coordinate cells are not exact crash sites or assigned ABS areas. Only crash counts are available. Aggregates over returned cells are partial when coordinateCoverage.truncated is true; missing totalCells/truncated metadata leaves completeness unknown. Unlocated crashes are excluded."] : []),
      ...(!["monthly_metrics","yearly_metrics","geographic_cells"].includes(dataset)
        ? [
            "LGA names use ABS 2024 reference areas; this is not a metropolitan-city ranking. Sparse rows are not imputed. Unmatched areas are retained unless explicitly filtered.",
          ]
        : []),
      ...(dataset === "locality_monthly"
        ? [
            "VIC locality data is not connected; NSW Town/QLD suburb labels do not imply geocoded points.",
          ]
        : []),
    ];
    const provenance = {
      source: f.source,
      batchId: f.batchId,
      releaseId: f.releaseId,
      sourceAvailability,
      ...(coordinateCoverage ? {coordinateCoverage} : {}),
      sourceBatches: Object.fromEntries(this.dataCatalog.sources.map(s=>[s.source,s.batchId])),
      datasetVersion: f.datasetVersion,
      requestedRange: f.dateRange,
      regionId: f.regionId ?? null,
      coverage: this.dataCatalog.coverage,
      dataset,
      query: a,
      observedRange,
      observedRows,
      resultRows,
      returnedRows: rows.length,
      notes,
      availability:
        dataset === "locality_monthly" && f.source === "VIC"
          ? "unsupported"
          : rows.length
            ? "available"
            : sourceAvailability.some(s=>s.meta.availability==="unsupported") ? "unsupported"
            : sourceAvailability.some(s=>s.meta.availability==="unknown") ? "unknown" : "no_results",
      outsidePageRange:
        JSON.stringify(f.dateRange) !==
        JSON.stringify(this.context.filters.dateRange),
      evidenceRefs: [
        `/api/data/evidence?${new URLSearchParams({source:f.source,from:f.dateRange.from,to:f.dateRange.to,datasetVersion:f.datasetVersion,batchId:f.batchId,...(f.releaseId?{releaseId:f.releaseId}:{})})}`,
        ...(["monthly_metrics","yearly_metrics","geographic_cells"].includes(dataset) && !f.regionId
          ? []
          : ["/api/data/region-evidence"]),
      ],
    };
    this.queries.set(queryId, {
      rows,
      provenance,
      truncated: resultRows > rows.length || coordinateCoverage?.truncated === true,
      evidenceId,
    });
    return {
      ...provenance,
      queryId,
      columns: [...keys, ...selectedMetrics],
      preview: rows.slice(0, 12),
      previewRows: Math.min(12, rows.length),
      truncated: resultRows > rows.length || coordinateCoverage?.truncated === true,
      retainedLocally: rows.length,
    };
  }
  private getQuery(id: unknown) {
    const q = this.queries.get(String(id));
    if (!q)
      return invalid(
        "Unknown queryId. Run workspace_query in this turn first.",
      );
    return q;
  }
  private async present(a: Record<string, unknown>, evidenceId: string) {
    if (++this.outputs > 5)
      return invalid("At most five presentations per turn.");
    const q = this.getQuery(a.queryId),
      title = safeText(a.title),
      x = safeText(a.x),
      y = safeText(a.y),
      kind = safeText(a.kind);
    if (!["bar", "line", "table"].includes(kind))
      return invalid("Choose bar, line or table.");
    const columns = Object.keys(q.rows[0] || {}),
      series = a.series === null ? null : safeText(a.series);
    if (
      !columns.includes(x) ||
      !columns.includes(y) ||
      q.rows.some((r) => r[y] !== null && typeof r[y] !== "number") ||
      (series && !columns.includes(series))
    )
      return invalid(
        "Choose x/series from the query columns and y from numeric metrics.",
      );
    if (new Set(q.rows.map((r) => r.source)).size > 1 && series !== "source")
      return invalid('Use series="source" for multiple states.');
    const combination = q.rows.map((r) =>
      JSON.stringify([r[x], series ? r[series] : null]),
    );
    if (kind !== "table" && new Set(combination).size !== combination.length)
      return invalid(
        "Duplicate chart categories. Group the query to one row per x + series first.",
      );
    const view: AnalysisView = {
      id: `view-${a.queryId}`,
      title,
      kind: kind as AnalysisView["kind"],
      rows: q.rows.slice(0, 100),
      x,
      y,
      series,
      evidenceId,
      source: String(q.provenance.source),
      period: `${(q.provenance.requestedRange as Filters["dateRange"]).from} → ${(q.provenance.requestedRange as Filters["dateRange"]).to}`,
      truncated: q.truncated || q.rows.length > 100,
    };
    const artifacts = [
      await saveArtifact(`query-${a.queryId}.csv`, csv(q.rows), q.provenance),
      await saveArtifact(
        `query-${a.queryId}-provenance.json`,
        JSON.stringify(q.provenance, null, 2),
        q.provenance,
      ),
    ];
    return {
      source: q.provenance.source,
      queryId: a.queryId,
      provenance: q.provenance,
      view,
      artifacts,
    };
  }
  private async python(
    a: Record<string, unknown>,
    signal: AbortSignal,
    evidenceId: string,
  ) {
    if (++this.pythonRuns > 3)
      return invalid("Python execution limit reached: three runs per turn.");
    safeText(a.title);
    if (
      !Array.isArray(a.queryIds) ||
      !a.queryIds.length ||
      a.queryIds.length > 5 ||
      new Set(a.queryIds).size !== a.queryIds.length
    )
      return invalid("Select 1–5 distinct query IDs.");
    const queries: Record<string, SavedQuery> = Object.fromEntries(
      a.queryIds.map((id) => [id, this.getQuery(id)]),
    );
    const code = safeText(a.code, 24000);
    const allowedEvidence = new Set([
      ...this.evidenceIds,
      evidenceId,
      ...Object.values(queries).map((q) => q.evidenceId),
    ]);
    const result = await runPython(
      code,
      { queries, context: this.context, evidenceIds: [...allowedEvidence] },
      signal,
    );
    if (result.status === "succeeded") {
      const texts = [
        result.stdout,
        ...result.files
          .filter((f) => /\.(md|txt|csv|json)$/.test(f.name))
          .map((f) => Buffer.from(f.data, "base64").toString("utf8")),
      ];
      const unknown = [
        ...new Set(
          texts
            .flatMap((text) => text.match(/\bE[1-9]\d*\b/g) || [])
            .filter((id) => !allowedEvidence.has(id)),
        ),
      ];
      if (unknown.length) {
        result.status = "failed";
        result.error = `The report/output references unavailable evidence IDs: ${unknown.join(", ")}. Read actual IDs from /data/input.json evidenceIds and each query's evidenceId, correct the references and run again.`;
        result.files = [];
      }
    }
    const inputSources = [
      ...new Set(
        Object.values(queries).map((q) => String(q.provenance.source)),
      ),
    ];
    const source = inputSources.length === 1 ? inputSources[0] : "All";
    const inputScopes = Object.values(queries).map((q) => ({
      source: q.provenance.source,
      requestedRange: q.provenance.requestedRange,
      regionId: q.provenance.regionId,
      evidenceId: q.evidenceId,
    }));
    const provenance = {
      context: this.context,
      inputScopes,
      queries: Object.fromEntries(
        Object.entries(queries).map(([id, q]) => [id, q.provenance]),
      ),
      image: result.image,
      evidenceId,
      inputEvidenceIds: [...allowedEvidence],
      code,
      status: result.status,
    };
    const artifacts: AnalysisArtifact[] = [];
    if (result.status === "succeeded") {
      artifacts.push(
        await saveArtifact(`analysis-${this.pythonRuns}.py`, code, provenance),
      );
      for (const file of result.files)
        artifacts.push(
          await saveArtifact(
            file.name,
            Buffer.from(file.data, "base64"),
            provenance,
          ),
        );
      artifacts.push(
        await saveArtifact(
          `provenance-${this.pythonRuns}.json`,
          JSON.stringify(provenance, null, 2),
          provenance,
        ),
      );
    }
    return {
      source,
      inputScopes,
      batchId: this.context.filters.batchId,
      releaseId: this.context.filters.releaseId,
      title: a.title,
      status: result.status,
      stdout: result.stdout,
      error: result.error,
      remainingRuns: 3 - this.pythonRuns,
      provenance,
      artifacts,
    };
  }
}
