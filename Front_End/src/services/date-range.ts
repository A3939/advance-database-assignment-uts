import calendarBounds from "../../pipeline/arsia_pipeline/knowledge/date-range.json";
export const LOCAL_DATE_BOUNDS = {min:`${calendarBounds.min_year}-01`, max:`${calendarBounds.max_year}-12`};
import type { Filters } from "./contracts";

export const MIN_ANALYSIS_MONTH = "2019-01";
export const MAX_ANALYSIS_MONTH = "2026-12";
const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/;
const rangeMessage = (bounds: {min:string;max:string}) => `Choose months from ${bounds.min} to ${bounds.max}.`;

function validCalendarDate(date: string): boolean {
  if (!/^\d{4}-(0[1-9]|1[0-2])-\d{2}$/.test(date)) return false;
  const parsed = new Date(`${date}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === date;
}
export function validateWholeDateRange(range: Filters["dateRange"], bounds = {min:MIN_ANALYSIS_MONTH,max:MAX_ANALYSIS_MONTH}): string | undefined {
  const { from, to } = range;
  if (!validCalendarDate(from) || !validCalendarDate(to)) return "Choose valid calendar months.";
  if (from.slice(0, 7) < bounds.min || to.slice(0, 7) > bounds.max ||
      to.slice(0, 7) < bounds.min || from.slice(0, 7) > bounds.max) return rangeMessage(bounds);
  if (from > to) return "Start month must not follow end month.";
  if (!from.endsWith("-01")) return "Analysis dates must start on the first day of the selected month.";
  const endDay = new Date(Date.UTC(Number(to.slice(0, 4)), Number(to.slice(5, 7)), 0)).getUTCDate();
  if (Number(to.slice(8)) !== endDay) return "Analysis dates must end on the last day of the selected month.";
}
/** Used by both month inputs and URL restoration; invalid input never reaches Date conversion. */
export function wholeMonthRange(from: string, to: string, bounds = {min:MIN_ANALYSIS_MONTH,max:MAX_ANALYSIS_MONTH}):
  | { dateRange: Filters["dateRange"]; error?: undefined }
  | { dateRange?: undefined; error: string } {
  if (!from || !to) return { error: "Choose both a start and an end month." };
  if (!MONTH.test(from) || !MONTH.test(to)) return { error: "Choose valid calendar months." };
  if (from < bounds.min || from > bounds.max || to < bounds.min || to > bounds.max)
    return { error: rangeMessage(bounds) };
  const lastDay = new Date(Date.UTC(Number(to.slice(0, 4)), Number(to.slice(5, 7)), 0)).getUTCDate();
  const dateRange = { from: `${from}-01`, to: `${to}-${lastDay}` };
  const error = validateWholeDateRange(dateRange, bounds);
  return error ? { error } : { dateRange };
}
