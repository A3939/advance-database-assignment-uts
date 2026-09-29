import { importPreview } from "./import-preview";
import type {
  ArsiaService,
  Filters,
  Provenance,
  Metric,
  Source,
  TimePoint,
  AgentEvent,
  StateCoverage,
  Overview,
} from "./contracts";
import { FIXTURES, MONTHLY, allocate } from "./fixtures";
const sources: Source[] = ["NSW", "VIC", "QLD"];
const stateFilters = (f: Filters, source: Source): Filters => ({
  ...f,
  source,
  batchId:
    f.batchId === "demo-all-v1" ? `demo-${source.toLowerCase()}-v1` : f.batchId,
});
const states: Omit<StateCoverage, "available">[] = [
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
const evidence = [
  {
    id: "fixture",
    title: "Demo fixture & metric definitions",
    description:
      "Independently authored monthly aggregates. Yearly, severity and KPI totals reconcile. Lives lost and casualties are independent aggregate measures; the small illustrative records sample cannot substantiate them.",
  },
  {
    id: "boundaries",
    title: "ABS 2024 local government boundaries",
    description:
      "CC BY 4.0. Real statistical boundaries, locally stored and generalised. Heat and hotspot locations are fictional. No official map or QA result is asserted.",
    href: "/geo/provenance.json",
  },
];
function selected(f: Filters) {
  if (f.source === "All") return [];
  if (
    f.datasetVersion !== "demo-v1.0" ||
    f.batchId !== `demo-${f.source.toLowerCase()}-v1`
  )
    return [];
  return MONTHLY[f.source].filter(
    (r) =>
      r.period >= f.dateRange.from.slice(0, 7) &&
      r.period <= f.dateRange.to.slice(0, 7),
  );
}
function meta(f: Filters, unit = "crashes"): Provenance {
  const hasRows =
    f.source === "All"
      ? sources.some((s) => selected(stateFilters(f, s)).length)
      : selected(f).length > 0;
  return {
    demo: true,
    source: f.source,
    datasetVersion: f.datasetVersion,
    batchId: f.batchId,
    availability: hasRows ? "available" : "no_results",
    reason: hasRows
      ? undefined
      : "No demo observations cover this source, version and date range.",
    coverage: {
      from: "2020-01-01",
      to: "2024-12-31",
      granularity: "month",
      complete:
        f.dateRange.from >= "2020-01-01" && f.dateRange.to <= "2024-12-31",
    },
    definition:
      "Fictional source-specific counts. Date filters use whole calendar months. Not official road safety statistics.",
    unit,
    evidence,
  };
}
function sum(
  f: Filters,
  key: "crashes" | "fatalCrashes" | "livesLost" | "casualties",
) {
  return selected(f).reduce((n, r) => n + r[key], 0);
}
function metric(
  f: Filters,
  key: "crashes" | "fatalCrashes" | "livesLost" | "casualties",
  label: string,
  definition: string,
): Metric {
  return {
    value: selected(f).length ? sum(f, key) : null,
    availability: meta(f).availability,
    label,
    unit: key === "livesLost" || key === "casualties" ? "people" : "crashes",
    definition,
  };
}
export const mockProvider: ArsiaService = {
  async getOverview(f) {
    if (f.source === "All") {
      const results = await Promise.all(
        sources.map((source) => this.getOverview(stateFilters(f, source))),
      );
      const data = { fatalShare: null } as Overview;
      for (const key of [
        "crashes",
        "fatalCrashes",
        "livesLost",
        "casualties",
      ] as const)
        data[key] = {
          ...results[0].data[key],
          value: null,
          availability: "unsupported",
          definition:
            "Source-specific demo counts shown separately; a national total is not supported.",
          bySource: results.map((r, i) => ({
            source: sources[i],
            value: r.data[key].value,
            availability: r.data[key].availability,
          })),
        };
      return {
        meta: {
          ...meta(f),
          definition:
            "Per-state demo series. No national aggregate is calculated.",
        },
        data,
      };
    }
    const total = sum(f, "crashes");
    return {
      meta: meta(f),
      data: {
        crashes: metric(
          f,
          "crashes",
          "Crashes",
          "Number of recorded crash events in the demo aggregate.",
        ),
        fatalCrashes: metric(
          f,
          "fatalCrashes",
          "Fatal crashes",
          "Crash events classified as fatal. One event can involve multiple deaths.",
        ),
        livesLost: metric(
          f,
          "livesLost",
          "Lives lost",
          "Recorded deaths in an independent demo aggregate; not derived from the sample records.",
        ),
        casualties: metric(
          f,
          "casualties",
          "Casualties",
          "Source-defined injured or killed people in an independent demo aggregate.",
        ),
        fatalShare: total ? sum(f, "fatalCrashes") / total : null,
      },
    };
  },
  async getTimeSeries(f, granularity) {
    if (f.source === "All") {
      const results = await Promise.all(
        sources.map((source) =>
          this.getTimeSeries(stateFilters(f, source), granularity),
        ),
      );
      return {
        meta: meta(f),
        data: results.flatMap((r, i) =>
          r.data.map((row) => ({ ...row, source: sources[i] })),
        ),
      };
    }
    const rows = selected(f);
    let data: TimePoint[];
    if (granularity === "monthly")
      data = rows.map(
        ({ period, crashes, fatalCrashes, livesLost, casualties }) => ({
          period,
          crashes,
          fatalCrashes,
          livesLost,
          casualties,
        }),
      );
    else {
      const years = new Map<string, TimePoint>();
      for (const r of rows) {
        const y = r.period.slice(0, 4);
        const item = years.get(y) || {
          period: y,
          crashes: 0,
          fatalCrashes: 0,
          livesLost: 0,
          casualties: 0,
        };
        for (const k of [
          "crashes",
          "fatalCrashes",
          "livesLost",
          "casualties",
        ] as const)
          item[k] = (item[k] ?? 0) + r[k];
        years.set(y, item);
      }
      data = [...years.values()];
    }
    return { meta: meta(f), data };
  },
  async getSeverityDistribution(f) {
    if (f.source === "All") {
      const results = await Promise.all(
        sources.map((source) =>
          this.getSeverityDistribution(stateFilters(f, source)),
        ),
      );
      return {
        meta: meta(f),
        data: results.flatMap((r, i) =>
          r.data.map((row) => ({ ...row, source: sources[i] })),
        ),
      };
    }
    const rows = selected(f);
    return {
      meta: meta(f),
      data: rows.length
        ? FIXTURES[f.source].labels.map((label, i) => ({
            label,
            count: rows.reduce((n, r) => n + r.severity[i], 0),
            definition: `Illustrative ${f.source} source category; not a cross-state standard.`,
          }))
        : [],
    };
  },
  async getMapData(f) {
    if (f.source === "All")
      return {
        meta: {
          ...meta(f),
          definition:
            "Source-specific demo crash counts drive the illustrative coral concentration scale. Not comparable risk rates or national totals. Missing counts remain unknown.",
        },
        data: {
          level: "country",
          boundaryUrl: "/geo/australia-states.geojson",
          bounds: [
            [111, -44.5],
            [155, -9],
          ],
          illustrationOnly: true,
          regions: [],
          states: states.map((s) => ({
            ...s,
            available:
              !!s.source && selected(stateFilters(f, s.source)).length > 0,
            count:
              s.source && selected(stateFilters(f, s.source)).length
                ? sum(stateFilters(f, s.source), "crashes")
                : undefined,
          })),
        },
      };
    const fixture = FIXTURES[f.source];
    const counts = allocate(sum(f, "crashes"), [34, 44, 22]);
    return {
      meta: {
        ...meta(f),
        definition:
          "Three fictional hotspot groups partition the demo crash aggregate; they do not describe actual LGA statistics.",
      },
      data: {
        level: "state",
        boundaryUrl: `/geo/${f.source.toLowerCase()}-lga.geojson`,
        bounds: fixture.bounds,
        illustrationOnly: true,
        regions: selected(f).length
          ? fixture.regions.map((r, i) => ({ ...r, count: counts[i] }))
          : [],
      },
    };
  },
  async getCrashRecords(f, pagination, sort) {
    if (f.source === "All")
      return {
        meta: {
          ...meta(f, "illustrative records"),
          availability: "unsupported",
          reason: "Select one source for illustrative records.",
        },
        data: {
          rows: [],
          total: 0,
          page: pagination.page,
          pageSize: pagination.pageSize,
          aggregateCount: 0,
          sampleOnly: true,
        },
      };
    const source = f.source;
    const months = selected(f);
    const fixture = FIXTURES[source];
    let rows = months.flatMap((month) =>
      Array.from({ length: 3 }, (_, i) => ({
        id: `DEMO-${source}-${month.period}-${i + 1}`,
        date: `${month.period}-${String(6 + i * 8).padStart(2, "0")}`,
        region: fixture.regions[i].name,
        severity:
          fixture.labels[
            (MONTHLY[source].indexOf(month) + i) % fixture.labels.length
          ],
        source: source,
        demo: true as const,
      })),
    );
    const q = pagination.search?.trim().toLowerCase();
    if (q)
      rows = rows.filter((r) =>
        Object.values(r).join(" ").toLowerCase().includes(q),
      );
    rows.sort(
      (a, b) =>
        a[sort.field].localeCompare(b[sort.field]) *
        (sort.direction === "asc" ? 1 : -1),
    );
    const pageSize = Math.max(1, Math.min(50, pagination.pageSize)),
      page = Math.max(1, pagination.page);
    return {
      meta: {
        ...meta(f, "illustrative records"),
        definition:
          "Three independent illustrative records per covered month. This sample is not the underlying population of the aggregate KPIs.",
      },
      data: {
        rows: rows.slice((page - 1) * pageSize, page * pageSize),
        total: rows.length,
        page,
        pageSize,
        aggregateCount: sum(f, "crashes"),
        sampleOnly: true,
      },
    };
  },
  async getDatasetMetadata() {
    return (Object.keys(FIXTURES) as Source[]).map((source) => ({
      source,
      title: FIXTURES[source].title,
      version: "demo-v1.0",
      batchId: `demo-${source.toLowerCase()}-v1`,
      coverage: "2020–2024",
      limitations: [
        "All metrics are fictional, source-specific aggregates.",
        "Hotspots are illustrative, not official crash locations.",
        ...(source === "VIC"
          ? [
              "Production policy: Accident metrics only; vehicle/person reports restricted.",
            ]
          : source === "QLD"
            ? ["Production policy: no unit-detail records."]
            : []),
        "All current official maps remain unavailable.",
      ],
    }));
  },
  async *sendAgentMessage(context, message, signal) {
    const check = () => !signal?.aborted;
    if (!check()) return;
    yield { type: "progress", text: "Reading the selected demo context…" };
    await new Promise((r) => setTimeout(r, 300));
    if (!check()) return;
    const overview = await this.getOverview(context.filters);
    const trend = await this.getTimeSeries(context.filters, "yearly");
    yield {
      type: "tool_result",
      name: "getOverview (mock)",
      data: overview.data,
      simulated: true,
    };
    const source = context.filters.source,
      rows = trend.data;
    let answer =
      overview.meta.availability === "no_results"
        ? `There are no demo observations for ${source} in this range. Select dates between January 2020 and December 2024.`
        : `The selected ${source} demo contains ${overview.data.crashes.value?.toLocaleString("en-AU")} crashes, ${overview.data.fatalCrashes.value} fatal crashes and ${overview.data.livesLost.value} lives lost. These are fictional aggregates, not official statistics.`;
    if (source === "All") {
      answer =
        "All shows NSW, VIC and QLD separately. Their source definitions remain independent; no national total is calculated. Select a covered state on the map to explore its own demo metrics and severity categories.";
    } else if (
      /change|trend|fell|decreas|increas/i.test(message) &&
      rows.length >= 2
    ) {
      const a = rows.at(-2)!,
        b = rows.at(-1)!;
      const change = ((b.crashes! - a.crashes!) / a.crashes!) * 100;
      answer = `Recorded demo crashes ${change < 0 ? "fell" : "rose"} ${Math.abs(change).toFixed(1)}% from ${a.period} to ${b.period} (${a.crashes!.toLocaleString("en-AU")} → ${b.crashes!.toLocaleString("en-AU")}). This describes a count change, not a causal finding or a change in road risk.`;
    } else if (/map|location|hotspot/i.test(message))
      answer =
        "The map uses real ABS administrative boundaries with fictional hotspot groups. The groups partition the selected demo total, but are not actual regional counts. All official ARSIA maps remain unavailable under the current source policies.";
    else if (/quality|source|trust|limit|evidence/i.test(message))
      answer = `${source} uses a versioned demo fixture. Monthly, annual and severity aggregates reconcile; the illustrative records are a separate sample. Lives lost and casualties are independent demo measures. No QA pass rate or real model execution is claimed.`;
    else if (!/summar|overview|crash|fatal|casualt|death|lives/i.test(message))
      answer =
        "This simulated assistant can summarise this demo, explain the trend, describe map limitations and show fixture evidence. It cannot run arbitrary analysis or process your data yet. Try one of the suggested questions.";
    yield {
      type: "message",
      text: answer,
      simulated: true,
    } satisfies AgentEvent;
    yield { type: "evidence", evidence: evidence[0] };
  },
  createImportJob: (files) => importPreview.createImportJob(files),
  getImportJobStatus: (id) => importPreview.getImportJobStatus(id),
};
