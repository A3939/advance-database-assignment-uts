import type { MapData, MapRegion, Source, SourceSelection, TimePoint } from "./contracts";
import type { MetricKey } from "./analytics";

/** Align separate source observations; an absent point is a gap, never a zero or a sum. */
export function sourceTrend(rows: TimePoint[], metric: MetricKey, sources?: readonly Source[]) {
  const periods = [...new Set(rows.map(row => row.period))].sort();
  const order = sources ?? [...new Set(rows.map(row => row.source ?? ""))];
  const series = order.map(source => {
    const byPeriod = new Map(rows.filter(row => (row.source ?? "") === source).map(row => [row.period, row]));
    const points = periods.map(period => byPeriod.get(period) ?? null);
    return { source, points, values: points.map(point => {
      const value = point?.[metric];
      return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
    }) };
  });
  return { periods, series };
}

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

/** Exact cumulative observations; recorded zero-count areas stay in the area
 * denominator. Unmatched crashes are not part of the supplied mapped regions. */
export function spatialConcentration(regions: MapRegion[]) {
  const { ranked, total } = spatialInsights(regions);
  let crashes = 0;
  const points = total > 0 ? [
    { areas: 0, areaShare: 0, crashes: 0, crashShare: 0 },
    ...ranked.map((row, index) => {
      crashes += row.count;
      return { areas: index + 1, areaShare: (index + 1) / ranked.length * 100,
        crashes, crashShare: crashes / total * 100 };
    }),
  ] : [];
  return { areaCount: ranked.length, total, points };
}

/** Inspect the nearest whole-area observation, never interpolated crash counts. */
export function concentrationAtShare(series: ReturnType<typeof spatialConcentration>, share: number) {
  if (!series.points.length || !Number.isFinite(share)) return null;
  const index = Math.round(Math.max(0, Math.min(100, share)) / 100 * series.areaCount);
  return series.points[index];
}

/** One area ranking across observed LGA maps; source identities remain separate. */
export function allSourceAreaRanking(sourceMaps: { source: SourceSelection; data: MapData }[]) {
  return sourceMaps
    .filter(({ source, data }) => source !== "All" && data.regionMode === "lga" && !data.illustrationOnly)
    .flatMap(({ source, data }) => data.regions.map(region => ({ ...region, source })))
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name) || a.source.localeCompare(b.source) || a.id.localeCompare(b.id))
    .map((region, index) => ({ ...region, rank: index + 1 }));
}
