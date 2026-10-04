import { LOCAL_DATE_BOUNDS } from "./date-range";
import { SNAPSHOT_CATALOG, catalogFilters, type DataCatalog, LOCAL_VERSION } from "./catalog-contracts";
import type { Filters, Granularity, SourceSelection } from "./contracts";
import type { MetricKey } from "./analytics";
import { DEFAULT_FILTERS } from "./config";
import regions from "./region-catalog.json";
import { validateWholeDateRange } from "./date-range";

export interface AnalysisViewState {
  metric: MetricKey;
  granularity: Granularity;
  overviewGranularity: Granularity;
}
export const DEFAULT_VIEW: AnalysisViewState = {
  metric: "crashes",
  granularity: "monthly",
  overviewGranularity: "yearly",
};
const PARAMETERS = new Set([
  "source", "from", "to", "regionId", "datasetVersion", "batchId",
  "metric", "interval", "overviewInterval", "releaseId",
]);
/** Invalid links block results; the fallback is only used after explicit reset. */
export function parseAnalysisState(search: string, catalog: DataCatalog = SNAPSHOT_CATALOG): {
  filters: Filters; view: AnalysisViewState; error?: string;
} {
  const p = new URLSearchParams(search);
  const defaults = catalogFilters(catalog);
  const fail = (error: string) => ({ filters: DEFAULT_FILTERS, view: DEFAULT_VIEW, error });
  if ([...p.keys()].some(key => !PARAMETERS.has(key)))
    return fail("Unknown analysis parameter in this link. Results have not been substituted.");
  if ([...PARAMETERS].some(key => p.getAll(key).length > 1))
    return fail("Repeated analysis parameters are not supported.");
  const source = p.get("source") ?? defaults.source;
  const from = p.get("from") ?? defaults.dateRange.from;
  const to = p.get("to") ?? defaults.dateRange.to;
  const regionId = p.get("regionId") || undefined;
  const version = p.get("datasetVersion") ?? defaults.datasetVersion;
  const batch = p.get("batchId") ?? defaults.batchId;
  const metric = p.get("metric") ?? DEFAULT_VIEW.metric;
  const interval = p.get("interval") ?? DEFAULT_VIEW.granularity;
  const overviewInterval = p.get("overviewInterval") ?? DEFAULT_VIEW.overviewGranularity;
  if (!["All", ...catalog.sources.map(s=>s.source)].includes(source))
    return fail("Unknown data source in this analysis link.");
  const dateError = validateWholeDateRange({ from, to }, catalog.mode === "local" ? LOCAL_DATE_BOUNDS : undefined);
  if (dateError) return fail(dateError);
  if (version !== catalog.datasetVersion || batch !== catalog.batchId || (version !== LOCAL_VERSION && p.has("releaseId")) || (version === LOCAL_VERSION && (p.get("releaseId") ?? defaults.releaseId) !== catalog.releaseId))
    return fail("This link requests a dataset version or batch that is not available. Its results have not been replaced with the current snapshot.");
  if (regionId && (source === "All" || !(regions[source as keyof typeof regions] || []).some(region => region.id === regionId)))
    return fail("This LGA does not belong to the selected source.");
  if (!["crashes", "fatalCrashes", "livesLost", "casualties"].includes(metric) ||
      !["monthly", "yearly"].includes(interval) || !["monthly", "yearly"].includes(overviewInterval))
    return fail("Unknown analysis metric or interval.");
  return {
    filters: { source: source as SourceSelection, regionId, dateRange: { from, to }, datasetVersion: version, batchId: batch, ...(catalog.releaseId ? {releaseId:catalog.releaseId} : {}) },
    view: { metric: metric as MetricKey, granularity: interval as Granularity, overviewGranularity: overviewInterval as Granularity },
  };
}
export function analysisHref(path: string, filters: Filters, view: AnalysisViewState): string {
  const p = new URLSearchParams({
    source: filters.source, from: filters.dateRange.from, to: filters.dateRange.to,
    datasetVersion: filters.datasetVersion, batchId: filters.batchId,
    metric: view.metric, interval: view.granularity, overviewInterval: view.overviewGranularity,
  });
  if (filters.releaseId) p.set("releaseId", filters.releaseId);
  if (filters.regionId) p.set("regionId", filters.regionId);
  return `${path}?${p}`;
}
