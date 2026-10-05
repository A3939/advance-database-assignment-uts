/** Server-side, read-only adapter for the admitted D05/D06 official export. */
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { join } from "node:path";
import type {
  ArsiaService,
  Filters,
  Metric,
  Overview,
  Provenance,
  Source,
  TimePoint,
  StateCoverage,
  Dataset,
  Severity,
  MapData,
} from "../services/contracts";
import regionCatalog from "../services/region-catalog.json";
import { DEFAULT_FILTERS, selectSource } from "../services/config";
import { canonicalSnapshotBytes, canonicalSnapshotText } from "./snapshot-bytes";

interface Observation {
  batch_id: string;
  source_id: string;
  period_year: number;
  period_month: number | null;
  coverage_status: string;
  crash_count: number | null;
  fatal_crash_count: number | null;
  fatality_count: number | null;
  casualty_count: number | null;
  fatal_crash_known_count: number;
  fatality_known_count: number;
  casualty_known_count: number;
  excluded_unknown_month_count: number;
}
interface SeverityRow {
  batch_id: string;
  source_id: string;
  filter_year_from: number;
  filter_year_to: number;
  filter_months: number[] | null;
  definition_version: string;
  severity_code: string;
  severity_label: string;
  definition_text: string;
  crash_count: number;
}
interface Report<T> {
  dataset_kind: string;
  batch_id: string;
  source_id: string;
  status: string;
  reason: string | null;
  rows: T[] | null;
  source_label: string;
  quality_limits: string[];
  coverage_basis: string[];
  comparison_scope: string;
}
export interface OfficialSnapshot {
  reports: Record<string, Report<Observation | SeverityRow>>;
  provenance: {
    version: string;
    batchId: string;
    recordedAt: string;
    runtimeCommit: string;
    coverage: { from: string; to: string };
    publicationStatus: string;
    evidenceHashes: Record<string, string>;
    qa: { check: string; status: string; violations: number }[];
    scope: string;
    [key: string]: unknown;
  };
}
const SOURCES: Source[] = ["NSW", "VIC", "QLD"];
const KEYS = ["crashes", "fatalCrashes", "livesLost", "casualties"] as const;
type Key = (typeof KEYS)[number];
const NATIVE: Record<Key, keyof Observation> = {
  crashes: "crash_count",
  fatalCrashes: "fatal_crash_count",
  livesLost: "fatality_count",
  casualties: "casualty_count",
};
const KNOWN: Partial<Record<Key, keyof Observation>> = {
  fatalCrashes: "fatal_crash_known_count",
  livesLost: "fatality_known_count",
  casualties: "casualty_known_count",
};
const DEFINITIONS = {
  NSW: {
    crashes:
      "Recorded crash events in the pinned NSW Crash file, selected by Year of crash and Month of crash.",
    fatalCrashes:
      "NSW crash events classified Fatal: at least one death within 30 days of injuries from the crash.",
    livesLost:
      "Sum of No. killed from NSW crash-event records; one fatal crash can involve more than one death.",
    casualties:
      "NSW crash-level sum of killed, seriously injured, moderately injured and minor/other injured people.",
  },
  VIC: {
    crashes:
      "Recorded Accident events in the restricted VIC snapshot. Only Accident-level measures are reportable.",
    fatalCrashes:
      "VIC Accident events with native SEVERITY 1 (Fatal). Native classifications remain source-specific.",
    livesLost:
      "Sum of NO_PERSONS_KILLED from VIC Accident records. Restricted Person records are not queried.",
    casualties:
      "VIC Accident-level killed and injured person counts. Restricted Person and Vehicle rows are not used for reporting.",
  },
  QLD: {
    crashes:
      "Recorded casualty-crash events in the pinned QLD snapshot. Export coverage does not represent all crashes on the road.",
    fatalCrashes:
      "QLD crash events classified Fatal by the native source classification.",
    livesLost: "Sum of Count_Casualty_Fatality from QLD crash-level records.",
    casualties:
      "Sum of Count_Casualty_Total from QLD crash-level records; no unit-detail records are available.",
  },
};
const LABELS = {
  crashes: "Crashes",
  fatalCrashes: "Fatal crashes",
  livesLost: "Lives lost",
  casualties: "Casualties",
};
const STATES: Omit<StateCoverage, "available">[] = [
  {
    code: "1",
    label: "NSW",
    name: "New South Wales",
    source: "NSW",
    coordinates: [146.8, -32.4],
  },
  {
    code: "2",
    label: "VIC",
    name: "Victoria",
    source: "VIC",
    coordinates: [144.6, -36.7],
  },
  {
    code: "3",
    label: "QLD",
    name: "Queensland",
    source: "QLD",
    coordinates: [144.6, -22.3],
  },
  {
    code: "4",
    label: "SA",
    name: "South Australia",
    coordinates: [135.1, -30],
  },
  {
    code: "5",
    label: "WA",
    name: "Western Australia",
    coordinates: [122.1, -25.5],
  },
  { code: "6", label: "TAS", name: "Tasmania", coordinates: [146.7, -42] },
  {
    code: "7",
    label: "NT",
    name: "Northern Territory",
    coordinates: [133.4, -19.5],
  },
  {
    code: "8",
    label: "ACT",
    name: "Australian Capital Territory",
    coordinates: [149.12, -35.5],
  },
  {
    code: "9",
    label: "OT",
    name: "Other Territories",
    coordinates: [105.65, -10.5],
  },
];
const BOUNDS: Record<Source, MapData["bounds"]> = {
  NSW: [
    [140.8, -37.6],
    [153.7, -28],
  ],
  VIC: [
    [140.8, -39.2],
    [150, -33.8],
  ],
  QLD: [
    [137.5, -29.2],
    [153.7, -10.5],
  ],
};
const TITLES = { NSW: "New South Wales", VIC: "Victoria", QLD: "Queensland" };
const SNAPSHOT_SHA =
  "fed5e2ea8736ce5db17fbdf1227cc4e6cafed2ec8fa3937956c218542e134e8d";
const PROVENANCE_SHA =
  "7be35242b97f68885321dd0ee6a6b177b22b2d8adbdfcb70fa15b874dc7d4891";
export function decodeOfficialSnapshot(
  bytes: Buffer,
  text: string,
): OfficialSnapshot {
  const canonicalBytes = canonicalSnapshotBytes(bytes);
  const canonicalText = canonicalSnapshotText(text);
  if (createHash("sha256").update(canonicalBytes).digest("hex") !== SNAPSHOT_SHA)
    throw Error("Official snapshot integrity check failed.");
  if (createHash("sha256").update(canonicalText).digest("hex") !== PROVENANCE_SHA)
    throw Error("Official snapshot provenance integrity check failed.");
  const provenance = JSON.parse(canonicalText) as OfficialSnapshot["provenance"];
  if (
    provenance.batchId !== DEFAULT_FILTERS.batchId ||
    provenance.version !== DEFAULT_FILTERS.datasetVersion ||
    provenance.publicationStatus !== "succeeded" ||
    provenance.evidenceHashes["reader-results.json"] !== SNAPSHOT_SHA
  )
    throw Error("Official snapshot provenance mismatch.");
  return { reports: JSON.parse(canonicalBytes.toString("utf8")), provenance };
}
let pending: Promise<OfficialSnapshot> | undefined;
export function loadOfficialSnapshot(): Promise<OfficialSnapshot> {
  // Only admitted, local aggregate files. Never accept a path from an HTTP request.
  pending ??= Promise.all([
    readFile(join(process.cwd(), "data/official/reader-results.json")),
    readFile(join(process.cwd(), "data/official/provenance.json"), "utf8"),
  ])
    .then(([bytes, text]) => decodeOfficialSnapshot(bytes, text))
    .catch((error) => {
      pending = undefined;
      throw error;
    });
  return pending;
}
export type OfficialReadService = Pick<
  ArsiaService,
  | "getOverview"
  | "getTimeSeries"
  | "getSeverityDistribution"
  | "getMapData"
  | "getCrashRecords"
  | "getDatasetMetadata"
>;

export function createOfficialProvider(
  snapshot: OfficialSnapshot,
): OfficialReadService {
  const { reports, provenance } = snapshot;
  function report<T>(source: Source, kind: string): Report<T> {
    return reports[`official_${source.toLowerCase()}:${kind}`] as Report<T>;
  }
  const evidence = [
    {
      id: "official-snapshot",
      title: "Project data snapshot & validation",
      description: `Fixed official-source build ${provenance.batchId}. Published successfully; QA01–QA06 pass, QA07 location limited. Not live data or final platform sign-off.`,
      href: "/api/data/evidence",
    },
  ];
  const identity = (f: Filters) =>
    f.datasetVersion === provenance.version && f.batchId === provenance.batchId;
  const sourceRows = (f: Filters, source: Source) =>
    identity(f)
      ? (report<Observation>(source, "monthly").rows || []).filter((r) => {
          const period = `${r.period_year}-${String(r.period_month).padStart(2, "0")}`;
          return (
            r.coverage_status === "covered" &&
            period >= f.dateRange.from.slice(0, 7) &&
            period <= f.dateRange.to.slice(0, 7)
          );
        })
      : [];
  function meta(f: Filters, unit = "crashes"): Provenance {
    const sources = f.source === "All" ? SOURCES : [f.source];
    const hasRows = sources.some((s) => sourceRows(f, s).length);
    return {
      demo: false,
      source: f.source,
      datasetVersion: f.datasetVersion,
      batchId: f.batchId,
      availability: !identity(f)
        ? "unsupported"
        : hasRows
          ? "available"
          : "no_results",
      reason: !identity(f)
        ? "This dataset version or batch is not the connected project snapshot."
        : hasRows
          ? undefined
          : "No observations in this project snapshot cover the selected months.",
      coverage: {
        ...provenance.coverage,
        granularity: "month",
        complete:
          f.dateRange.from >= provenance.coverage.from &&
          f.dateRange.to <= provenance.coverage.to,
      },
      definition:
        f.source === "All"
          ? "Source-specific project snapshot counts, shown separately. Interstate totals and risk comparisons are not supported."
          : `${report(f.source, "monthly").source_label}. ${report(f.source, "monthly").coverage_basis.join(" ")}`,
      unit,
      evidence,
    };
  }
  function count(rows: Observation[], key: Key): number | null {
    if (!rows.length) return null;
    if (
      rows.some(
        (r) =>
          r[NATIVE[key]] == null ||
          (KNOWN[key] && r[KNOWN[key]!] !== r.crash_count),
      )
    )
      return null;
    return rows.reduce((sum, r) => sum + (r[NATIVE[key]] as number), 0);
  }
  function metric(f: Filters, source: Source, key: Key): Metric {
    const rows = sourceRows(f, source),
      value = count(rows, key),
      status = meta(f).availability;
    return {
      label: LABELS[key],
      value,
      unit: key === "crashes" || key === "fatalCrashes" ? "crashes" : "people",
      availability:
        status !== "available"
          ? status
          : value === null
            ? "unknown"
            : "available",
      reason:
        value === null && rows.length
          ? "Some source records have an unknown measure; no zero substitution is made."
          : meta(f).reason,
      definition: DEFINITIONS[source][key],
    };
  }
  const service: OfficialReadService = {
    async getOverview(f) {
      if (f.source === "All") {
        const data = { fatalShare: null } as Overview;
        for (const key of KEYS)
          data[key] = {
            label: LABELS[key],
            value: null,
            availability: "unsupported",
            unit:
              key === "crashes" || key === "fatalCrashes"
                ? "crashes"
                : "people",
            definition: SOURCES.map((s) => `${s}: ${DEFINITIONS[s][key]}`).join(
              " ",
            ),
            reason:
              "No national total: these sources have different statistical definitions.",
            bySource: SOURCES.map((s) => ({
              source: s,
              value: metric(f, s, key).value,
              availability: metric(f, s, key).availability,
            })),
          };
        return { data, meta: meta(f) };
      }
      const rows = sourceRows(f, f.source),
        fatal = count(rows, "fatalCrashes");
      const known = rows.reduce((sum, r) => sum + r.fatal_crash_known_count, 0);
      return {
        meta: meta(f),
        data: {
          crashes: metric(f, f.source, "crashes"),
          fatalCrashes: metric(f, f.source, "fatalCrashes"),
          livesLost: metric(f, f.source, "livesLost"),
          casualties: metric(f, f.source, "casualties"),
          fatalShare: known > 0 && fatal !== null ? fatal / known : null,
        },
      };
    },
    async getTimeSeries(f, granularity) {
      const data: TimePoint[] = [];
      for (const source of f.source === "All" ? SOURCES : [f.source]) {
        const rows = sourceRows(f, source),
          groups = new Map<string, Observation[]>();
        for (const row of rows) {
          const period =
            granularity === "yearly"
              ? String(row.period_year)
              : `${row.period_year}-${String(row.period_month).padStart(2, "0")}`;
          groups.set(period, [...(groups.get(period) || []), row]);
        }
        for (const [period, observations] of groups)
          data.push({
            ...(f.source === "All" ? { source } : {}),
            period,
            crashes: count(observations, "crashes"),
            fatalCrashes: count(observations, "fatalCrashes"),
            livesLost: count(observations, "livesLost"),
            casualties: count(observations, "casualties"),
          });
      }
      return { data, meta: meta(f) };
    },
    async getSeverityDistribution(f) {
      const base = meta(f);
      if (base.availability !== "available") return { data: [], meta: base };
      if (
        f.dateRange.from !== provenance.coverage.from ||
        f.dateRange.to !== provenance.coverage.to
      )
        return {
          data: [],
          meta: {
            ...base,
            availability: "unsupported",
            reason:
              "Severity was exported for 2020–2024 only. Select the full period to view source classifications; no monthly allocation is inferred.",
          },
        };
      const data: Severity[] = (
        f.source === "All" ? SOURCES : [f.source]
      ).flatMap((source) =>
        (report<SeverityRow>(source, "severity").rows || []).map((r) => ({
          ...(f.source === "All" ? { source } : {}),
          label: r.severity_label,
          count: r.crash_count,
          definition: `${r.definition_text} Definition: ${r.definition_version}.`,
        })),
      );
      return { data, meta: base };
    },
    async getMapData(f) {
      const base = meta(f);
      if (f.source === "All")
        return {
          meta: {
            ...base,
            definition:
              "State/source aggregate counts on ABS reference boundaries. These are not crash locations, regional hotspots, severity rates or harmonised interstate risk measures.",
          },
          data: {
            level: "country",
            boundaryUrl: "/geo/australia-states.geojson",
            bounds: [
              [111, -44.5],
              [155, -9],
            ],
            illustrationOnly: false,
            regions: [],
            legendLabel: "Recorded crashes by source",
            states: STATES.map((s) => {
              const n = s.source
                ? count(sourceRows(f, s.source), "crashes")
                : null;
              return {
                ...s,
                available: n !== null,
                count: n === null ? undefined : n,
              };
            }),
          },
        };
      return {
        meta: {
          ...base,
          availability:
            base.availability === "available"
              ? "unsupported"
              : base.availability,
          reason:
            report(f.source, "map").reason ||
            "Crash locations are unavailable.",
        },
        data: {
          level: "state",
          boundaryUrl: `/geo/${f.source.toLowerCase()}-lga.geojson`,
          bounds: BOUNDS[f.source],
          illustrationOnly: false,
          regions: [],
          legendLabel: "Boundaries only",
          unavailableReason:
            "Crash locations are unavailable under this source’s current policy.",
        },
      };
    },
    async getCrashRecords(f, pagination) {
      return {
        meta: {
          ...meta(f, "records"),
          availability: "unsupported",
          reason:
            "This connection contains validated aggregates only. Crash-level records are not exposed by the snapshot API.",
        },
        data: {
          rows: [],
          total: 0,
          page: pagination.page,
          pageSize: pagination.pageSize,
          aggregateCount: (await service.getOverview(f)).data.crashes.value,
          sampleOnly: false,
        },
      };
    },
    async getDatasetMetadata(): Promise<Dataset[]> {
      return SOURCES.map((source) => ({
        source,
        title: TITLES[source],
        demo: false,
        description: report(source, "monthly").source_label,
        version: provenance.version,
        batchId: provenance.batchId,
        coverage: "2020–2024",
        limitations: [
          ...report(source, "monthly").quality_limits,
          "Fixed project snapshot; not a live government feed.",
          "Severity distribution is available for the full 2020–2024 period only.",
        ],
        evidence,
        metricDefinitions: [
          ...KEYS.map((key) => ({
            label: LABELS[key],
            value: DEFINITIONS[source][key],
          })),
          {
            label: "Coverage",
            value: report(source, "monthly").coverage_basis.join(" "),
          },
          {
            label: "QA",
            value:
              "QA01–QA06 passed; QA07 location limited. Independent member sign-off and final platform acceptance remain pending.",
          },
          { label: "Batch", value: provenance.batchId },
        ],
      }));
    },
  };
  return service;
}

/** Bound validation is shared by all HTTP reports. */
export function parseOfficialFilters(params: URLSearchParams): Filters {
  const source = params.get("source") || DEFAULT_FILTERS.source;
  if (!["All", ...SOURCES].includes(source))
    throw Error("Choose All, NSW, VIC or QLD.");
  const from = params.get("from") || DEFAULT_FILTERS.dateRange.from;
  const to = params.get("to") || DEFAULT_FILTERS.dateRange.to;
  const valid = (s: string) =>
    /^\d{4}-\d{2}-\d{2}$/.test(s) &&
    !Number.isNaN(Date.parse(s)) &&
    new Date(s).toISOString().slice(0, 10) === s;
  if (!valid(from) || !valid(to) || from > to)
    throw Error("Provide a valid, ordered ISO date range.");
  if (
    !from.endsWith("-01") ||
    new Date(Date.parse(to) + 86400000).getUTCDate() !== 1
  )
    throw Error("Select whole calendar months.");
  if (Number(to.slice(0, 4)) - Number(from.slice(0, 4)) > 20)
    throw Error("Select a range of at most 20 years.");
  const regionId = params.get("regionId") || undefined;
  if (regionId && (source === "All" || !regionCatalog[source as Source].some(r => r.id === regionId)))
    throw Error("Choose a valid LGA within the selected source.");
  return {
    ...selectSource(DEFAULT_FILTERS, source as Filters["source"]),
    ...(regionId ? { regionId } : {}),
    dateRange: { from, to },
    datasetVersion:
      params.get("datasetVersion") || DEFAULT_FILTERS.datasetVersion,
    batchId: params.get("batchId") || DEFAULT_FILTERS.batchId,
  };
}
