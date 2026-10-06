import type { Availability, Filters, Source } from "./contracts";

export interface SeverityChangePeriod {
  year: string;
  label: string;
  dateRange: Filters["dateRange"];
}
export interface SeverityChangeRow {
  label: string;
  startCount: number;
  endCount: number;
  /** Percent, not fraction; change is percentage points. */
  startShare: number | null;
  endShare: number | null;
  change: number | null;
}
export interface SeverityChangeGroup {
  source: Source;
  area: string | null;
  availability: Availability;
  reason: string | null;
  totals: [number, number] | null;
  rows: SeverityChangeRow[];
}
export interface SeverityChange {
  periods: [SeverityChangePeriod, SeverityChangePeriod] | null;
  groups: SeverityChangeGroup[];
  reason: string | null;
}

/** Compare the endpoint years using only months selected in BOTH years. */
export function severityChangePeriods(range: Filters["dateRange"]): SeverityChange["periods"] {
  const first = range.from.slice(0, 4), last = range.to.slice(0, 4);
  const fromMonth = Number(range.from.slice(5, 7)), toMonth = Number(range.to.slice(5, 7));
  if (first >= last || fromMonth > toMonth) return null;
  const label = (month: number) => new Date(Date.UTC(2000, month - 1, 1)).toLocaleDateString("en-AU", { month: "short", timeZone: "UTC" });
  return [first, last].map(year => ({
    year,
    label: fromMonth === 1 && toMonth === 12 ? year : `${label(fromMonth)}${fromMonth === toMonth ? "" : `–${label(toMonth)}`} ${year}`,
    dateRange: {
      from: `${year}-${String(fromMonth).padStart(2, "0")}-01`,
      to: `${year}-${String(toMonth).padStart(2, "0")}-${new Date(Date.UTC(Number(year), toMonth, 0)).getUTCDate()}`,
    },
  })) as [SeverityChangePeriod, SeverityChangePeriod];
}
