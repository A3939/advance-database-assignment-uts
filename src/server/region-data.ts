/** Derived, read-only LGA extension. Never changes canonical point eligibility. */
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { join } from "node:path";
import type { Filters, MapRegion, Overview, Provenance, Source, TimePoint } from "../services/contracts";
import type { OfficialReadService } from "./official-data";
import { canonicalSnapshotBytes } from "./snapshot-bytes";

type Counts = [number, number | null, number | null, number | null];
type Row = [string, string, ...Counts, number[]];
export interface RegionSnapshot {
  extensionVersion: string; batchId: string; datasetVersion: string;
  coverage: { from: string; to: string };
  sources: Record<Source, {
    regions: { id: string; name: string }[];
    severityLabels: string[]; rows: Row[];
    localities: [string, string, string, number][];
    unmatched: [string, string, string, number][];
    audit: { crashes: number; matched: number; unmatched: number };
  }>;
}
const SHA = "93a1a8cdb889c17bee7e144ed49e9439d1a0d8cc8904fa43cec1a4fc45e1ad36";
let pending: Promise<RegionSnapshot> | undefined;
export function loadRegionSnapshot() {
  return pending ??= readFile(join(process.cwd(), "data/regions/aggregates.json")).then(bytes => {
    const canonicalBytes = canonicalSnapshotBytes(bytes);
    if (createHash("sha256").update(canonicalBytes).digest("hex") !== SHA) throw Error("Regional snapshot integrity failure.");
    return JSON.parse(canonicalBytes.toString()) as RegionSnapshot;
  }).catch(error => { pending = undefined; throw error; });
}
export async function regionEvidence() {
  // Fixed path, no caller-supplied filesystem input. Integrity verified against aggregate loader.
  await loadRegionSnapshot();
  const evidence = JSON.parse(await readFile(join(process.cwd(), "data/regions/provenance.json"), "utf8"));
  if (evidence.aggregateSha256 !== SHA) throw Error("Regional provenance mismatch.");
  return evidence;
}
const keys = ["crashes", "fatalCrashes", "livesLost", "casualties"] as const;
const sum = (rows: Row[], index: number) => rows.some(r => r[index + 2] === null) ? null : rows.reduce((n, r) => n + (r[index + 2] as number), 0);
const definition = "Source-reported LGA names matched to ABS 2024 reference areas. LGA is not a city or accident point. Historical labels have not been spatially reallocated; counts are not risk rates. Unmatched records stay in source totals. Derived frontend extension lga-name-v1; canonical QA07 and point restrictions are unchanged.";
const evidence = { id: "lga-name-v1", title: "LGA matching & reconciliation", description: definition, href: "/api/data/region-evidence" };

export function createRegionalProvider(base: OfficialReadService, snapshot: RegionSnapshot): OfficialReadService {
  function valid(f: Filters) { return f.batchId === snapshot.batchId && f.datasetVersion === snapshot.datasetVersion; }
  function data(f: Filters) {
    if (f.source === "All") throw Error("Select one source for an LGA.");
    const d = snapshot.sources[f.source];
    if (f.regionId && !d.regions.some(r => r.id === f.regionId)) throw Error("Unknown LGA for the selected source.");
    return d;
  }
  function periods(f: Filters) {
    const result: string[] = [];
    for (let y = 2020; y <= 2024; y++) for (let m = 1; m <= 12; m++) {
      const p = `${y}-${String(m).padStart(2, "0")}`;
      if (p >= f.dateRange.from.slice(0, 7) && p <= f.dateRange.to.slice(0, 7)) result.push(p);
    }
    return valid(f) ? result : [];
  }
  function rows(f: Filters, selection = true) {
    const d = data(f), months = new Set(periods(f));
    return d.rows.filter(r => months.has(r[0]) && (!selection || !f.regionId || r[1] === f.regionId));
  }
  function meta(f: Filters, original: Provenance): Provenance {
    const region = f.regionId ? data(f).regions.find(r => r.id === f.regionId) : undefined;
    return { ...original, definition: `${region ? `${region.name} LGA (${region.id}). ` : ""}${definition}`, evidence: [...original.evidence, evidence] };
  }
  const service: OfficialReadService = {
    ...base,
    async getOverview(f) {
      const original = await base.getOverview(f);
      if (!f.regionId) return original;
      const observations = rows(f), available = valid(f) && periods(f).length > 0;
      const result = { fatalShare: null } as Overview;
      keys.forEach((key, i) => {
        const value = available ? sum(observations, i) : null;
        result[key] = { ...original.data[key], value, bySource: undefined,
          availability: available ? value === null ? "unknown" : "available" : original.meta.availability,
          definition: `${original.data[key].definition} Restricted to ${data(f).regions.find(r => r.id === f.regionId)!.name} LGA by reported name.`,
        };
      });
      result.fatalShare = result.crashes.value && result.fatalCrashes.value !== null ? result.fatalCrashes.value / result.crashes.value : null;
      return { data: result, meta: meta(f, original.meta) };
    },
    async getTimeSeries(f, granularity) {
      const original = await base.getTimeSeries(f, granularity);
      if (!f.regionId) return original;
      const observations = rows(f), groups = new Map<string, Row[]>();
      for (const p of periods(f)) {
        const group = granularity === "yearly" ? p.slice(0, 4) : p;
        groups.set(group, [...(groups.get(group) || []), ...observations.filter(r => r[0] === p)]);
      }
      return { data: [...groups].map(([period, list]) => ({ period, ...Object.fromEntries(keys.map((k, i) => [k, sum(list, i)])) } as TimePoint)), meta: meta(f, original.meta) };
    },
    async getSeverityDistribution(f) {
      if (!f.regionId) return base.getSeverityDistribution(f);
      const original = await base.getOverview(f), d = data(f), observations = rows(f);
      return { data: periods(f).length ? d.severityLabels.map((label, i) => ({ label, count: observations.reduce((n, r) => n + r[6][i], 0), definition: "Native source severity, counted from individual crash records within the selected LGA and months; derived regional extension, not a proportional allocation of the official severity export." })) : [], meta: meta(f, original.meta) };
    },
    async getMapData(f) {
      const original = await base.getMapData(f);
      if (f.source === "All") return original;
      const d = data(f), observations = rows(f, false), months = new Set(periods(f));
      const total = sum(observations, 0) || 0, unmatched = sum(observations.filter(r => r[1] === "__unmatched__"), 0) || 0;
      const localities = new Map<string, Map<string, number>>();
      // Only selected-area top localities are sent to the browser.
      if (f.regionId) for (const [p, id, name, count] of d.localities) if (id === f.regionId && months.has(p)) {
        const group = localities.get(id) || new Map<string, number>();
        group.set(name, (group.get(name) || 0) + count); localities.set(id, group);
      }
      const regions: MapRegion[] = months.size ? d.regions.map(region => {
        const selected = observations.filter(r => r[1] === region.id), group = localities.get(region.id);
        return { ...region, count: sum(selected, 0) || 0, fatalCrashes: sum(selected, 1),
          ...(group ? { localities: [...group].sort((a,b) => b[1]-a[1] || a[0].localeCompare(b[0])).slice(0,8).map(([name,count]) => ({name,count})), localityTotal: [...group.values()].reduce((a,b) => a+b,0) } : {}) };
      }).sort((a,b) => b.count-a.count || a.name.localeCompare(b.name)) : [];
      const overview = await base.getOverview(f);
      return { meta: meta(f, overview.meta), data: { ...original.data, regionMode: "lga", selectedRegionId: f.regionId, regions, legendLabel: "Recorded crashes · LGA", unavailableReason: undefined, coverage: { total, matched: total-unmatched, unmatched, percentage: total ? Math.round((total-unmatched)/total*100000)/1000 : null } } };
    },
    async getCrashRecords(f, pagination, sort) {
      const original = await base.getCrashRecords(f, pagination, sort);
      if (!f.regionId) return original;
      return { ...original, data: { ...original.data, aggregateCount: (await service.getOverview(f)).data.crashes.value } };
    },
    async getDatasetMetadata() {
      return (await base.getDatasetMetadata()).map(d => ({ ...d, evidence: [...(d.evidence || []), evidence], limitations: [...d.limitations, definition], metricDefinitions: [...(d.metricDefinitions || []), { label: "Regional extension", value: `${snapshot.sources[d.source].audit.matched.toLocaleString("en-AU")} name-matched crashes; ${snapshot.sources[d.source].audit.unmatched.toLocaleString("en-AU")} unmatched. Regional monthly metrics and severity are derived from hash-verified native records and reconcile to the project snapshot.` }] }));
    },
  };
  return service;
}
