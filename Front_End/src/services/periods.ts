import type { Filters, TimePoint } from "./contracts";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export function monthRangeLabel(filters: Filters): string {
  const label = (date: string) => `${MONTHS[Number(date.slice(5, 7)) - 1]} ${date.slice(0, 4)}`;
  return filters.dateRange.from.slice(0, 7) === filters.dateRange.to.slice(0, 7)
    ? label(filters.dateRange.from) : `${label(filters.dateRange.from)} – ${label(filters.dateRange.to)}`;
}
export function selectedMonths(filters: Filters, year: number): number[] {
  return Array.from({ length: 12 }, (_, i) => i + 1).filter(month => {
    const period = `${year}-${String(month).padStart(2, "0")}`;
    return period >= filters.dateRange.from.slice(0, 7) && period <= filters.dateRange.to.slice(0, 7);
  });
}
export function yearScope(filters: Filters, year: number, observedMonths: number) {
  const months = selectedMonths(filters, year);
  return { selectedMonths: months, observedMonths, fullYear: months.length === 12 && observedMonths === 12 };
}
export function timePointLabel(point: TimePoint): string {
  if (!point.selectedMonths || point.fullYear) return point.period;
  const months = point.selectedMonths;
  const range = months.length === 1 ? MONTHS[months[0] - 1] : `${MONTHS[months[0] - 1]}–${MONTHS[months.at(-1)! - 1]}`;
  return `${point.period} · ${range} subtotal (${point.observedMonths === undefined ? "monthly precision unavailable" : `${point.observedMonths}/${months.length} months`})`;
}
