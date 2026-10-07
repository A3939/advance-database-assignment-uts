/** Read-only, source-bound speed-zone extension; never reads raw files at runtime. */
import { readFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { join } from "node:path";
import type { Filters, Response, Source } from "../services/contracts";
import type { SpeedZoneBand, SpeedZoneData, SpeedZoneGroup } from "../services/speed-zone";
import type { OfficialReadService } from "./official-data";

type Row = [period: string, band: string, crashes: number, fatalCrashes: number, fatalKnown: number];
export interface SpeedZoneSnapshot {
  extensionVersion: string;
  batchId: string;
  datasetVersion: string;
  coverage: Filters["dateRange"];
  bands: SpeedZoneBand[];
  sources: Record<Source, { field: string; rows: Row[]; excluded: Row[] }>;
}
const SHA = "15dc6ea6000b982aec809cb300a9884c0d1fb77b087f8eccc2c4b38476a58422";
const PROVENANCE_SHA = "29ff822cead5dab369e2add2df765b663919abc2ca67a93b76ca0e12de57dd1c";
let pending: Promise<SpeedZoneSnapshot> | undefined;
export function decodeSpeedZoneSnapshot(bytes: Buffer): SpeedZoneSnapshot {
  if (createHash("sha256").update(bytes).digest("hex") !== SHA) throw Error("Speed-zone snapshot integrity failure.");
  return JSON.parse(bytes.toString()) as SpeedZoneSnapshot;
}
export function loadSpeedZoneSnapshot() {
  return pending ??= readFile(join(process.cwd(), "data/speed-zones/aggregates.json"))
    .then(decodeSpeedZoneSnapshot).catch(error => {pending = undefined; throw error;});
}
export async function speedZoneEvidence() {
  await loadSpeedZoneSnapshot();
  const bytes = await readFile(join(process.cwd(), "data/speed-zones/provenance.json"));
  if (createHash("sha256").update(bytes).digest("hex") !== PROVENANCE_SHA) throw Error("Speed-zone evidence integrity failure.");
  const evidence = JSON.parse(bytes.toString());
  if (evidence.aggregateSha256 !== SHA) throw Error("Speed-zone evidence binding failure.");
  return evidence;
}

export async function getSpeedZones(filters: Filters, service: Pick<OfficialReadService, "getOverview">, snapshot: SpeedZoneSnapshot): Promise<Response<SpeedZoneData>> {
  const original = await service.getOverview(filters);
  const reason = filters.batchId !== snapshot.batchId || filters.datasetVersion !== snapshot.datasetVersion
    ? "This batch has no verified speed-zone breakdown."
    : filters.regionId ? "Speed-zone breakdowns are available for whole sources only."
    : filters.dateRange.from < snapshot.coverage.from || filters.dateRange.to > snapshot.coverage.to
      ? "Speed-zone data covers January 2020 to December 2024; select dates within this period."
      : !filters.dateRange.from.endsWith("-01") || new Date(Date.parse(filters.dateRange.to) + 86400000).getUTCDate() !== 1 || filters.dateRange.from > filters.dateRange.to
        ? "Select an ordered range of whole calendar months." : null;
  const sources: Source[] = filters.source === "All" ? ["NSW", "VIC", "QLD"] : [filters.source];
  const groups = await Promise.all(sources.map(async (source): Promise<SpeedZoneGroup> => {
    const data = snapshot.sources[source];
    const empty = {source, field:data.field, rows:[], excluded:[]};
    if (reason) return {...empty, availability:"unsupported", reason};
    const overview = await service.getOverview({...filters, source});
    if (overview.meta.source !== source || overview.meta.batchId !== filters.batchId || overview.meta.datasetVersion !== filters.datasetVersion) throw Error("Speed-zone source identity mismatch.");
    if (overview.meta.availability !== "available" || overview.data.crashes.value === null) return {...empty, availability:"unknown", reason:"Verified source counts are unavailable for this selection."};
    const selected = (rows: Row[]) => rows.filter(row => row[0] >= filters.dateRange.from.slice(0, 7) && row[0] <= filters.dateRange.to.slice(0, 7));
    const rows = selected(data.rows), excluded = selected(data.excluded);
    for (const list of [rows, excluded]) {
      const seen = new Set<string>();
      for (const row of list) {
        const key = JSON.stringify(row.slice(0, 2));
        if (seen.has(key) || row.slice(2).some(n => !Number.isSafeInteger(n) || Number(n) < 0) || row[3] > row[4] || row[4] > row[2]) throw Error("Invalid speed-zone counts.");
        seen.add(key);
      }
    }
    if (rows.some(row => !snapshot.bands.some(band => band.id === row[1]))) throw Error("Unknown speed-zone band.");
    const all = [...rows, ...excluded];
    if (all.reduce((n, r) => n + r[2], 0) !== overview.data.crashes.value ||
      (overview.data.fatalCrashes.value !== null && all.reduce((n, r) => n + r[3], 0) !== overview.data.fatalCrashes.value)) throw Error("Speed-zone counts do not reconcile with source totals.");
    const excludedValues = [...new Set(excluded.map(row => row[1]))].sort().map(nativeValue => ({nativeValue,
      crashes:excluded.filter(r => r[1] === nativeValue).reduce((n,r) => n+r[2],0),
      fatalCrashes:excluded.filter(r => r[1] === nativeValue).reduce((n,r) => n+r[3],0)}));
    const values = snapshot.bands.map(band => {
      const bucket = rows.filter(row => row[1] === band.id);
      const crashes = bucket.reduce((n,r) => n+r[2],0), fatalCrashes = bucket.reduce((n,r) => n+r[3],0), fatalKnown = bucket.reduce((n,r) => n+r[4],0);
      return {band:band.id, crashes, fatalCrashes, fatalKnown, share:crashes > 0 && fatalKnown === crashes ? fatalCrashes / crashes * 100 : null};
    });
    return {source, field:data.field, availability:values.some(row => row.share !== null) ? "available" : overview.data.crashes.value ? "unknown" : "no_results",
      reason:values.some(row => row.crashes !== row.fatalKnown) ? "Some fatal-status observations are unknown; affected shares are withheld." : null,
      rows:values, excluded:excludedValues};
  }));
  return {data:{bands:snapshot.bands, groups, reason}, meta:{...original.meta,
    availability:reason ? "unsupported" : groups.some(group => group.availability === "available") ? "available" : groups.some(group => group.availability === "unknown") ? "unknown" : "no_results",
    ...(reason ? {reason} : {}), unit:"percent",
    definition:"Fatal crash events / all recorded crash events within each source, selected months and posted speed band. Entire published QLD ranges are preserved. Unknown/special and other unmatched speed values remain excluded and auditable. Source coverage differs; these shares are not traffic-exposure risk or safety rankings.",
    evidence:[...original.meta.evidence, {id:snapshot.extensionVersion, title:"Speed-zone derivation", description:"Hash-bound native crash inputs; monthly crash and fatal totals reconcile to the admitted project snapshot. No vehicle speeds or person-level measures are used.", href:"/api/data/speed-zone-evidence"}],
  }};
}
