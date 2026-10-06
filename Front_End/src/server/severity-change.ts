import type { Filters, Response, Source } from "../services/contracts";
import { severityChangePeriods, type SeverityChange, type SeverityChangeGroup } from "../services/severity-change";
import type { OfficialReadService } from "./official-data";
import type { RegionSnapshot } from "./region-data";

/** A separate derived report: never allocate the five-year D06 export to years. */
export async function getSeverityChange(
  filters: Filters,
  service: Pick<OfficialReadService, "getOverview">,
  snapshot: RegionSnapshot,
): Promise<Response<SeverityChange>> {
  const periods = severityChangePeriods(filters.dateRange);
  const original = await service.getOverview(filters);
  const identityMatches = filters.batchId === snapshot.batchId && filters.datasetVersion === snapshot.datasetVersion;
  const covered = periods?.every(period => period.dateRange.from >= snapshot.coverage.from && period.dateRange.to <= snapshot.coverage.to);
  const reason = !identityMatches ? "This batch has no verified monthly severity comparison."
    : !periods ? "Select at least two years with matching calendar months to compare severity shares."
    : !covered ? "Both comparison periods must be fully covered by this snapshot."
    : null;
  const sources = filters.source === "All" ? Object.keys(snapshot.sources) as Source[] : [filters.source];
  const groups = await Promise.all(sources.map(async (source): Promise<SeverityChangeGroup> => {
    const data = snapshot.sources[source];
    const area = filters.regionId ? data.regions.find(region => region.id === filters.regionId)?.name : null;
    if (filters.regionId && !area) throw Error("Unknown comparison area.");
    const empty = { source, area: area ?? null, totals: null, rows: [] };
    if (reason || !periods) return { ...empty, availability: "unsupported", reason };
    const results = await Promise.all(periods.map(async period => {
      // Source-wide includes __unmatched__; selecting an LGA intentionally restricts it.
      const rows = data.rows.filter(row => row[0] >= period.dateRange.from.slice(0, 7) && row[0] <= period.dateRange.to.slice(0, 7) && (!filters.regionId || row[1] === filters.regionId));
      const scoped = { ...filters, source, dateRange: period.dateRange };
      const overview = await service.getOverview(scoped);
      if (overview.meta.source !== source || overview.meta.batchId !== filters.batchId || overview.meta.datasetVersion !== filters.datasetVersion) throw Error("Severity comparison identity mismatch.");
      if (overview.meta.availability !== "available" || overview.data.crashes.availability !== "available" || overview.data.crashes.value === null) return null;
      const counts = data.severityLabels.map(() => 0);
      let total = 0;
      for (const row of rows) {
        if (row[6].length !== counts.length || !Number.isSafeInteger(row[2]) || row[2] < 0 || row[6].some(count => !Number.isSafeInteger(count) || count < 0) || row[6].reduce((sum, count) => sum + count, 0) !== row[2]) throw Error("Invalid monthly severity observations.");
        total += row[2];
        row[6].forEach((count, i) => { counts[i] += count; });
      }
      if (total !== overview.data.crashes.value) throw Error("Monthly severity does not reconcile with the selected crash total.");
      return { counts, total };
    }));
    const [start, end] = results;
    if (!start || !end) return { ...empty, availability: "unknown", reason: "Verified crash totals are unavailable for a comparison period." };
    return {
      source, area: area ?? null, availability: start.total && end.total ? "available" : "no_results",
      reason: start.total && end.total ? null : "A comparison period has no recorded crashes; its severity shares are undefined.",
      totals: [start.total, end.total],
      rows: data.severityLabels.map((label, i) => {
        const startShare = start.total ? start.counts[i] / start.total * 100 : null;
        const endShare = end.total ? end.counts[i] / end.total * 100 : null;
        return { label, startCount: start.counts[i], endCount: end.counts[i], startShare, endShare, change: startShare === null || endShare === null ? null : endShare - startShare };
      }),
    };
  }));
  return {
    data: { periods, groups, reason },
    meta: {
      ...original.meta, availability: reason ? "unsupported" : groups.some(group => group.availability === "available") ? "available" : groups.some(group => group.availability === "unknown") ? "unknown" : "no_results",
      ...(reason ? { reason } : {}), unit: "percentage points",
      definition: "Native severity shares in the first and last selected years, using matching calendar months and all recorded crashes in each period. Derived from hash-verified monthly observations, including unmatched areas in source-wide totals. Source classifications remain separate; no national total or inferred monthly allocation.",
      evidence: [...original.meta.evidence, { id: snapshot.extensionVersion, title: "Monthly severity derivation", description: "Monthly category counts reconcile to the selected crash totals. This derived comparison does not alter the official five-year severity export.", href: "/api/data/region-evidence" }],
    },
  };
}
