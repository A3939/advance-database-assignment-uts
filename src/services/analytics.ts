import { arsia } from "./index";
import type {
  ArsiaService,
  Availability,
  Filters,
  Overview,
  Provenance,
  Response,
  Severity,
  Source,
  TimePoint,
} from "./contracts";

const METRICS = ["crashes", "fatalCrashes", "livesLost", "casualties"] as const;
type MetricKey = (typeof METRICS)[number];
type Counts = Record<MetricKey, number | null>;
type AnalyticsProvider = Pick<
  ArsiaService,
  | "getOverview"
  | "getTimeSeries"
  | "getSeverityDistribution"
  | "getDatasetMetadata"
>;

export interface AnalyticsMonth extends Counts {
  period: string;
  year: number;
  month: number;
  availability: Availability;
}

export interface AnalyticsYear extends Counts {
  year: number;
  observedMonths: number;
  requestedMonths: number;
  /** Complete for the selected months, which may be less than a full year. */
  complete: boolean;
  fullYear: boolean;
  previousYear: number;
  comparisonMonths: number[];
  previousCrashes: number | null;
  /** Percentage change, e.g. 6.1 for +6.1%; share fields use a 0–1 scale. */
  yoyPct: number | null;
  comparisonReason: string | null;
}

export interface CalendarMonth {
  month: number;
  label: string;
  total: number | null;
  average: number | null;
  observedMonths: number;
}

export interface AnalyticsData {
  filters: Filters & { source: Source };
  source: Source;
  monthly: AnalyticsMonth[];
  yearly: AnalyticsYear[];
  timeSeriesYearly: TimePoint[];
  heatmap: AnalyticsMonth[];
  calendarMonths: CalendarMonth[];
  severity: (Severity & { share: number | null })[];
  severityAvailability: Availability;
  severityReason: string | null;
  overview: Overview;
  summary: {
    total: number | null;
    latestYear: number | null;
    /** Null if the latest selected year cannot be compared; never a fallback. */
    latestComparableYear: number | null;
    yoyPct: number | null;
    fatalShare: number | null;
    peakMonth: { period: string; crashes: number } | null;
  };
  notes: string[];
}

const NO_COUNTS: Counts = {
  crashes: null,
  fatalCrashes: null,
  livesLost: null,
  casualties: null,
};
const MONTH_LABELS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

/** The aggregate landing selection becomes an explicitly source-scoped view. */
export function analyticsFilters(
  filters: Filters,
): Filters & { source: Source } {
  const source = filters.source === "All" ? "NSW" : filters.source;
  return {
    ...filters,
    source,
    dateRange: { ...filters.dateRange },
    batchId:
      filters.source === "All" && filters.batchId === "demo-all-v1"
        ? "demo-nsw-v1"
        : filters.batchId,
  };
}

function daysInMonth(year: number, month: number): number {
  if (month === 2)
    return year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0) ? 29 : 28;
  return [4, 6, 9, 11].includes(month) ? 30 : 31;
}

function monthIndex(date: string): number {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (!match) throw new Error("Analytics requires ISO calendar dates.");
  const [, yearText, monthText, dayText] = match;
  const year = Number(yearText),
    month = Number(monthText),
    day = Number(dayText);
  if (
    year < 2 ||
    month < 1 ||
    month > 12 ||
    day < 1 ||
    day > daysInMonth(year, month)
  )
    throw new Error(
      "Analytics requires valid calendar dates from year 0002 onward.",
    );
  return year * 12 + month - 1;
}

function periodAt(index: number): string {
  return `${String(Math.floor(index / 12)).padStart(4, "0")}-${String((index % 12) + 1).padStart(2, "0")}`;
}

function requestedPeriods(filters: Filters): string[] {
  const from = monthIndex(filters.dateRange.from),
    to = monthIndex(filters.dateRange.to);
  if (filters.dateRange.from > filters.dateRange.to)
    throw new Error("Analytics date range must start before it ends.");
  return Array.from({ length: to - from + 1 }, (_, index) =>
    periodAt(from + index),
  );
}

function sameIdentity(meta: Provenance, filters: Filters) {
  if (
    meta.source !== filters.source ||
    meta.datasetVersion !== filters.datasetVersion ||
    meta.batchId !== filters.batchId
  )
    throw new Error(
      "Analytics responses must use the same source, dataset version and batch.",
    );
}

function observations(
  response: Response<TimePoint[]>,
  filters: Filters,
): Map<string, TimePoint> {
  sameIdentity(response.meta, filters);
  const result = new Map<string, TimePoint>();
  if (response.meta.availability !== "available") return result;
  for (const row of response.data) {
    if (row.source && row.source !== filters.source)
      throw new Error(
        "Analytics cannot combine observations from different sources.",
      );
    if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(row.period) || result.has(row.period))
      throw new Error("Analytics requires unique calendar-month observations.");
    if (
      METRICS.some((key) => {
        const value = row[key];
        return value !== null && (!Number.isSafeInteger(value) || value < 0);
      })
    )
      throw new Error(
        "Analytics observations must contain non-negative integer counts or null.",
      );
    if (
      row.period >= filters.dateRange.from.slice(0, 7) &&
      row.period <= filters.dateRange.to.slice(0, 7)
    )
      result.set(row.period, row);
  }
  return result;
}

function missingAvailability(meta: Provenance, period: string): Availability {
  if (meta.availability !== "available") return meta.availability;
  if (
    period < meta.coverage.from.slice(0, 7) ||
    period > meta.coverage.to.slice(0, 7)
  )
    return "no_results";
  return "unknown";
}

function total(rows: readonly Counts[], key: MetricKey): number | null {
  if (!rows.length || rows.some((row) => row[key] === null)) return null;
  return rows.reduce((sum, row) => sum + row[key]!, 0);
}

function unavailableOverview(
  overview: Overview,
  availability: Availability,
): Overview {
  return {
    crashes: { ...overview.crashes, value: null, availability },
    fatalCrashes: { ...overview.fatalCrashes, value: null, availability },
    livesLost: { ...overview.livesLost, value: null, availability },
    casualties: { ...overview.casualties, value: null, availability },
    fatalShare: null,
  };
}

/**
 * Derived analysis over the public service boundary, never over fixture imports.
 * The reference query shifts the selected calendar months back one year, keeping
 * the exact source, version and batch. It does not expand the displayed totals.
 */
export async function getAnalytics(
  requestedFilters: Filters,
  service: AnalyticsProvider = arsia,
): Promise<Response<AnalyticsData>> {
  const filters = analyticsFilters(requestedFilters);
  const periods = requestedPeriods(filters);
  const referenceFrom = periodAt(monthIndex(filters.dateRange.from) - 12);
  const referenceTo = periodAt(monthIndex(filters.dateRange.to) - 12);
  const referenceFilters: Filters = {
    ...filters,
    dateRange: {
      from: `${referenceFrom}-01`,
      to: `${referenceTo}-${daysInMonth(Number(referenceTo.slice(0, 4)), Number(referenceTo.slice(5)))}`,
    },
  };
  const [
    overviewResponse,
    monthlyResponse,
    severityResponse,
    referenceResponse,
    datasets,
  ] = await Promise.all([
    service.getOverview(filters),
    service.getTimeSeries(filters, "monthly"),
    service.getSeverityDistribution(filters),
    service.getTimeSeries(referenceFilters, "monthly"),
    service.getDatasetMetadata(),
  ]);
  for (const response of [
    overviewResponse,
    monthlyResponse,
    severityResponse,
    referenceResponse,
  ])
    sameIdentity(response.meta, filters);
  const supported = datasets.some(
    (dataset) =>
      dataset.source === filters.source &&
      dataset.version === filters.datasetVersion &&
      dataset.batchId === filters.batchId,
  );
  const meta: Provenance = supported
    ? { ...overviewResponse.meta }
    : {
        ...overviewResponse.meta,
        availability: "unsupported",
        reason:
          "This source, dataset version and batch are not supported by the connected service.",
      };
  const overview =
    meta.availability === "available"
      ? overviewResponse.data
      : unavailableOverview(overviewResponse.data, meta.availability);
  const current = observations(
    {
      ...monthlyResponse,
      meta: {
        ...monthlyResponse.meta,
        availability: supported
          ? monthlyResponse.meta.availability
          : "unsupported",
      },
    },
    filters,
  );
  const reference = observations(
    {
      ...referenceResponse,
      meta: {
        ...referenceResponse.meta,
        availability: supported
          ? referenceResponse.meta.availability
          : "unsupported",
      },
    },
    referenceFilters,
  );
  const monthly: AnalyticsMonth[] = periods.map((period) => {
    const row = current.get(period);
    return {
      ...NO_COUNTS,
      ...(row ? Object.fromEntries(METRICS.map((key) => [key, row[key]])) : {}),
      period,
      year: Number(period.slice(0, 4)),
      month: Number(period.slice(5)),
      availability: row
        ? "available"
        : missingAvailability(supported ? monthlyResponse.meta : meta, period),
    };
  });
  const yearly: AnalyticsYear[] = [
    ...new Set(monthly.map((row) => row.year)),
  ].map((year) => {
    const selected = monthly.filter((row) => row.year === year);
    const observed = selected.filter((row) => row.availability === "available");
    const complete = observed.length === selected.length;
    const prior = selected.map((row) =>
      reference.get(
        `${String(year - 1).padStart(4, "0")}-${String(row.month).padStart(2, "0")}`,
      ),
    );
    const previousComplete = prior.every((row) => row !== undefined);
    const previousCrashes = previousComplete
      ? total(
          prior.filter((row): row is TimePoint => row !== undefined),
          "crashes",
        )
      : null;
    const crashes = complete ? total(observed, "crashes") : null;
    const comparisonReason = !complete
      ? "Some selected months have no observations."
      : crashes === null
        ? "Some selected months have unknown crash counts."
        : !previousComplete
          ? "The same months in the previous year are not fully covered."
          : previousCrashes === null
            ? "Some matching months in the previous year have unknown crash counts."
            : previousCrashes === 0
              ? "Percentage change is undefined because the previous count is zero."
              : null;
    return {
      year,
      crashes,
      fatalCrashes: complete ? total(observed, "fatalCrashes") : null,
      livesLost: complete ? total(observed, "livesLost") : null,
      casualties: complete ? total(observed, "casualties") : null,
      observedMonths: observed.length,
      requestedMonths: selected.length,
      complete,
      fullYear: selected.length === 12,
      previousYear: year - 1,
      comparisonMonths: selected.map((row) => row.month),
      previousCrashes,
      yoyPct:
        comparisonReason === null
          ? ((crashes! - previousCrashes!) / previousCrashes!) * 100
          : null,
      comparisonReason,
    };
  });
  const calendarMonths: CalendarMonth[] = MONTH_LABELS.map((label, index) => {
    const observed = monthly.filter(
      (row) =>
        row.month === index + 1 &&
        row.availability === "available" &&
        row.crashes !== null,
    );
    const sum = observed.length ? total(observed, "crashes") : null;
    return {
      month: index + 1,
      label,
      total: sum,
      average: sum === null ? null : sum / observed.length,
      observedMonths: observed.length,
    };
  });
  const severityAvailability = supported
    ? severityResponse.meta.availability
    : "unsupported";
  const severityReason = supported
    ? (severityResponse.meta.reason ?? null)
    : (meta.reason ?? null);
  const severity =
    severityAvailability === "available"
      ? severityResponse.data.map((row) => {
          if (
            (row.source && row.source !== filters.source) ||
            !Number.isSafeInteger(row.count) ||
            row.count < 0
          )
            throw new Error(
              "Analytics requires source-specific severity counts.",
            );
          return {
            ...row,
            share:
              overview.crashes.availability === "available" &&
              overview.crashes.value !== null &&
              overview.crashes.value > 0
                ? row.count / overview.crashes.value
                : null,
          };
        })
      : [];
  // An available provider must not mix totals from different selections.
  if (
    meta.availability === "available" &&
    monthlyResponse.meta.availability === "available"
  ) {
    for (const key of METRICS) {
      const metric = overview[key];
      const observedTotal = total(
        monthly.filter((row) => row.availability === "available"),
        key,
      );
      if (
        metric.availability === "available" &&
        metric.value !== null &&
        observedTotal !== null &&
        metric.value !== observedTotal
      )
        throw new Error(
          "Analytics monthly observations do not reconcile with the overview.",
        );
    }
    if (
      severityResponse.meta.availability === "available" &&
      overview.crashes.availability === "available" &&
      overview.crashes.value !== null &&
      severity.reduce((sum, row) => sum + row.count, 0) !==
        overview.crashes.value
    )
      throw new Error(
        "Analytics severity counts do not reconcile with the overview.",
      );
  }
  const latest = yearly.at(-1);
  const peak = monthly
    .filter((row) => row.crashes !== null)
    .reduce<AnalyticsMonth | null>(
      (best, row) => (!best || row.crashes! > best.crashes! ? row : best),
      null,
    );
  const notes = [
    "Single-source analysis. Source definitions remain independent; no interstate total or risk rate is calculated.",
    "Date filters select whole calendar months. Each year is compared with exactly the same months one year earlier, in the same dataset version and batch.",
    "Calendar-month averages use only observed months, including observed zeros. Missing months are not replaced with zero.",
  ];
  if (meta.demo)
    notes.unshift(
      "Monthly counts are synthetically allocated demo aggregates. Their peaks and calendar-month patterns do not establish real seasonal behaviour.",
    );
  else
    notes.unshift(
      "Monthly values are published source-specific aggregates from a fixed ARSIA batch. Descriptive patterns do not establish causation or changes in travel risk.",
    );
  if (severityAvailability !== "available" && severityReason)
    notes.push(severityReason);
  if (
    monthly.some(
      (row) =>
        row.availability === "available" &&
        METRICS.some((key) => row[key] === null),
    )
  )
    notes.push(
      "Unknown metric values remain unavailable. Yearly metric totals require known values for every selected month; monthly averages use known crash counts only.",
    );
  if (monthly.some((row) => row.availability !== "available"))
    notes.push(
      "Some requested months are unavailable. Totals describe available observations; incomplete yearly subtotals and comparisons are withheld.",
    );
  return {
    meta,
    data: {
      filters,
      source: filters.source,
      monthly,
      yearly,
      timeSeriesYearly: yearly
        .filter((row) => row.complete)
        .map((row) => ({
          period: String(row.year),
          crashes: row.crashes,
          fatalCrashes: row.fatalCrashes,
          livesLost: row.livesLost,
          casualties: row.casualties,
        })),
      heatmap: monthly.map((row) => ({ ...row })),
      calendarMonths,
      severity,
      severityAvailability,
      severityReason,
      overview,
      summary: {
        total: overview.crashes.value,
        latestYear: latest?.year ?? null,
        latestComparableYear:
          latest?.yoyPct !== null && latest?.yoyPct !== undefined
            ? latest.year
            : null,
        yoyPct: latest?.yoyPct ?? null,
        fatalShare: overview.fatalShare,
        peakMonth: peak
          ? { period: peak.period, crashes: peak.crashes! }
          : null,
      },
      notes,
    },
  };
}
