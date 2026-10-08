/** Reuse the reviewed LGA extension only for the same native inputs and measures. */
import type { CatalogSource } from '../services/catalog-contracts';
import type { publicationRead } from './data-catalog';
import { loadOfficialSnapshot } from './official-data';
import { loadRegionSnapshot, regionEvidence, type RegionSnapshot } from './region-data';

type Input = { resourceId: string; sourceId: string; sha256: string };
export interface RegionalPublicationReport {
  source_id: string; batch_id: string; release_id: string; profile_version: string;
  files: {resource_id: string; sha256: string}[];
  qa: {code: string; status: string}[];
  monthly_trend: {year: number; month: number; crash_count: number; fatal_crash_count: number|null; fatalities: number|null; casualties: number|null}[];
  severity: {label: string; count: number}[];
}
interface Evidence { aggregateSha256: string; inputs: Input[] }
const metrics = ['crash_count','fatal_crash_count','fatalities','casualties'] as const;
export function verifyRegionalPublication(report: RegionalPublicationReport, source: CatalogSource, releaseId: string,
  regional: RegionSnapshot, evidence: Evidence, officialInputs: Input[]): CatalogSource['regionalProvider'] {
  if (source.publicationStatus?.admission_level !== 'fixed_native' || report.source_id !== source.sourceId ||
    report.batch_id !== source.batchId || report.release_id !== releaseId || report.profile_version !== 'local-native-sqlite-v1') return;
  if (source.coverage.from !== regional.coverage.from || source.coverage.to !== regional.coverage.to ||
    !source.completeIntervals?.some(i=>i.from===regional.coverage.from && i.to===regional.coverage.to)) return;
  const data = regional.sources[source.source];
  if (!data) return;
  const inputs = officialInputs.filter(i=>i.sourceId===source.sourceId);
  const spatialInputs = evidence.inputs.filter(i=>i.sourceId===source.sourceId);
  if (!inputs.length || !spatialInputs.length || !Array.isArray(report.files)) return;
  // Every original role must still match, including relationship-supporting tables.
  if (![...inputs,...spatialInputs].every(i=>report.files.filter(f=>f.resource_id===i.resourceId).length===1 &&
    report.files.some(f=>f.resource_id===i.resourceId && f.sha256===i.sha256))) return;
  if (report.files.some(f=>f.resource_id && !inputs.some(i=>i.resourceId===f.resource_id))) return;
  if (!['QA01_INPUT','QA02_RAW','QA03_PROJECTED','QA04_AUXILIARY','QA05_SEMANTICS','QA06_RECONCILIATION']
    .every(code=>report.qa?.filter(q=>q.code===code).length===1 && report.qa.some(q=>q.code===code && q.status==='pass'))) return;
  const months = new Map<string, typeof data.rows>();
  for (const row of data.rows) { const rows=months.get(row[0]) || []; rows.push(row); months.set(row[0],rows); }
  if (!Array.isArray(report.monthly_trend) || report.monthly_trend.length!==months.size) return;
  const seen = new Set<string>();
  for (const row of report.monthly_trend) {
    const period=`${row.year}-${String(row.month).padStart(2,'0')}`, values=months.get(period);
    if (!values || seen.has(period)) return;
    seen.add(period);
    if (!metrics.every((key,index)=>row[key]===(values.some(v=>v[index+2]===null) ? null : values.reduce((n,v)=>n+(v[index+2] as number),0)))) return;
  }
  if (!Array.isArray(report.severity)) return;
  const severity = new Map(data.severityLabels.map((label,index)=>[label,data.rows.reduce((n,row)=>n+row[6][index],0)]));
  if (new Set(report.severity.map(r=>r.label)).size!==report.severity.length ||
    ![...severity].every(([label,count])=>report.severity.some(r=>r.label===label && r.count===count)) ||
    report.severity.some(r=>!severity.has(r.label) && r.count!==0)) return;
  return {kind:'verified-lga-snapshot',releaseId,sourceBatchId:source.batchId,sourceId:source.sourceId,
    datasetVersion:regional.datasetVersion,batchId:regional.batchId,aggregateSha256:evidence.aggregateSha256,
    coverage:{...regional.coverage},inputs:inputs.map(i=>({resourceId:i.resourceId,sha256:i.sha256}))};
}

export async function bindRegionalPublication(source: CatalogSource, releaseId: string, read: typeof publicationRead) {
  if (source.publicationStatus?.admission_level !== 'fixed_native') return;
  const [official, regional, evidence] = await Promise.all([loadOfficialSnapshot(),loadRegionSnapshot(),regionEvidence()]);
  const inputs=official.provenance.inputs as Input[];
  if (!inputs.some(i=>i.sourceId===source.sourceId) || !regional.sources[source.source]) return;
  const report=await read<RegionalPublicationReport>('reports',{release_id:releaseId,source_id:source.sourceId});
  return verifyRegionalPublication(report,source,releaseId,regional,evidence,inputs);
}
