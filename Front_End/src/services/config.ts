import type { Filters, SourceSelection } from "./contracts";

/** Pinned successful project build, not a rolling government feed. */
export const IS_DEMO = false;
export const DEFAULT_FILTERS: Filters = {
  source: "All",
  dateRange: { from: "2020-01-01", to: "2024-12-31" },
  datasetVersion: "official-v1",
  batchId: "bcc5da57-25f2-41ec-9925-bef421b02671",
};

export function selectSource(
  filters: Filters,
  source: SourceSelection,
): Filters {
  return {
    ...filters,
    source,
    regionId: source === filters.source ? filters.regionId : undefined,
    batchId:
      filters.datasetVersion === "demo-v1.0"
        ? `demo-${source.toLowerCase()}-v1`
        : filters.batchId,
  };
}
