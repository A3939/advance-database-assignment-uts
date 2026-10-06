import type { MapRegion, TimePoint } from "./contracts";
import type { MetricKey } from "./analytics";

/** Descriptive summaries only. Null is never a recorded zero. */
export function monthlyInsights(rows: TimePoint[], metric: MetricKey) {
  const known = rows.filter(row => row[metric] !== null);
  const peak = known.reduce<TimePoint | null>((best, row) =>
    !best || row[metric]! > best[metric]! ? row : best, null);
  return {
    average: known.length ? known.reduce((sum, row) => sum + row[metric]!, 0) / known.length : null,
    observed: known.length,
    peak,
    calendar: Array.from({ length: 12 }, (_, i) => {
      const matches = known.filter(row => Number(row.period.slice(5, 7)) === i + 1);
      return { month: i + 1, observed: matches.length,
        average: matches.length ? matches.reduce((sum, row) => sum + row[metric]!, 0) / matches.length : null };
    }),
  };
}

export function fatalPercentage(crashes: number | null, fatal: number | null | undefined) {
  return crashes !== null && crashes > 0 && fatal != null && fatal >= 0 && fatal <= crashes
    ? fatal / crashes * 100 : null;
}

/** Concentration always uses mapped records, never the source total including unmatched records. */
export function spatialInsights(regions: MapRegion[]) {
  const ranked = [...regions].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  const total = ranked.reduce((sum, row) => sum + row.count, 0);
  let cumulative = 0;
  return {
    total,
    represented: ranked.filter(row => row.count > 0).length,
    topFiveShare: total > 0 ? ranked.slice(0, 5).reduce((sum, row) => sum + row.count, 0) / total * 100 : null,
    ranked: ranked.map((row, i) => {
      cumulative += row.count;
      return { ...row, rank: i + 1, share: total > 0 ? row.count / total * 100 : null,
        cumulativeShare: total > 0 ? cumulative / total * 100 : null,
        fatalShare: fatalPercentage(row.count, row.fatalCrashes) };
    }),
  };
}
