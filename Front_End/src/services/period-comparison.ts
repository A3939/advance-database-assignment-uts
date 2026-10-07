import type { AnalyticsMonth, MetricKey } from "./analytics";

export interface ComparisonPeriod {
  start: number;
  end: number;
  label: string;
}

/** Prefer non-overlapping two-year windows; use single years for shorter selections. */
export function comparisonPeriods(rows: readonly AnalyticsMonth[]): ComparisonPeriod[] {
  const years = [...new Set(rows.map(row => row.year))].sort((a, b) => a - b);
  if (years.length < 4) return years.map(year => ({ start: year, end: year, label: String(year) }));
  return years.slice(0, -1).flatMap((start, index) =>
    years[index + 1] === start + 1
      ? [{ start, end: start + 1, label: `${start}–${start + 1}` }]
      : []);
}

export function comparisonAverage(rows: readonly AnalyticsMonth[], metric: MetricKey, period: ComparisonPeriod) {
  const selected = rows.filter(row => row.year >= period.start && row.year <= period.end);
  const known = selected.filter(row => row.availability === "available" &&
    typeof row[metric] === "number" && Number.isFinite(row[metric]) && row[metric] >= 0);
  return {
    average: known.length ? known.reduce((sum, row) => sum + row[metric]!, 0) / known.length : null,
    observed: known.length,
    selected: selected.length,
    complete: selected.length > 0 && known.length === selected.length,
  };
}

export function comparisonChange(first: ReturnType<typeof comparisonAverage>, second: ReturnType<typeof comparisonAverage>) {
  return first.complete && second.complete && first.average !== null && first.average > 0 && second.average !== null
    ? (second.average / first.average - 1) * 100
    : null;
}
