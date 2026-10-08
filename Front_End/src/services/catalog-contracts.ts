import type { PreprocessingQuality } from './preprocessing-contracts';
import type { Filters, Source } from './contracts';
import { DEFAULT_FILTERS } from './config';
export const LOCAL_VERSION = 'local-integrated-v1';
export interface ResourceLicensing {
  version: string; scope: string; redistribution: string;
  resources: {role: string; resource_url: string|null; status: 'unknown'|'verified'|'restricted'|'conflicting'; licence_uri?: string; declared_text?: unknown; evidence: unknown[]; limitation: string}[];
}
export interface CatalogSource {
  regionalProvider?: {kind:'verified-lga-snapshot'; releaseId:string; sourceBatchId:string; sourceId:string;
    datasetVersion:string; batchId:string; aggregateSha256:string; coverage:{from:string;to:string};
    inputs:{resourceId:string;sha256:string}[]};
  publicationStatus?: {admission_level: 'official_admitted'|'fixed_native'|'manual_reviewed'|'legacy_unclassified'; label:string; official_registration:boolean; scope:'local_research'; quality_report?:PreprocessingQuality; research_context?:{original_goal?:unknown;target_satisfied:boolean;official_identity_verified?:boolean}};
  capabilityLimits?: {role:string;capability:string;status:string;requested:boolean;reason:string;actual:string;target_satisfied:boolean}[];
  capabilityReview?: unknown;
  retainedResources?: {version:string;canonical_contribution:number;limitation:string;resources:{role:string;records_scanned:number;scan_complete:boolean;semantic_qa:string;reason:string;requested:boolean;file_sha256:string;raw_row_sequence_sha256:string}[]};
  rowPreprocessing?: {version:string;roles:string[];raw_rows:number;collapsed_duplicate_rows:number;lineage_sha256:string;rule:string};
  licensing?: ResourceLicensing;
  source: Source; sourceId: string; title: string; jurisdiction: string; publisher: string;
  batchId: string; origin: 'snapshot' | 'publication';
  coverage: { from: string; to: string };
  completeIntervals?: {from:string;to:string}[];
  capabilities: { monthly: boolean; severity: boolean; geography: boolean; units: boolean };
  definitions: Record<string, string>; limitations: string[];
}
export interface DataCatalog {
  localStatus?: 'not_requested' | 'empty' | 'connected';
  mode: 'snapshot' | 'local'; releaseId?: string; datasetVersion: string; batchId: string;
  coverage: { from: string; to: string }; sources: CatalogSource[];
}
/** Presentation only: persisted source IDs and pinned links remain unchanged. */
export function sourceDisplayName(source: CatalogSource, catalog: DataCatalog): string {
  if (source.publicationStatus?.admission_level === 'manual_reviewed') return `${source.title || source.source} · local research`;
  const fixtures: Record<string, string> = {
    wa_ai_fixture: 'WA AI test sample', browser_fixture: 'Browser test sample',
  };
  if (fixtures[source.sourceId]) return fixtures[source.sourceId];
  const jurisdiction = source.jurisdiction;
  if (['NSW','VIC','QLD','SA','WA','TAS','ACT','NT'].includes(jurisdiction)) {
    if (catalog.sources.filter(item => item.jurisdiction === jurisdiction).length === 1) return jurisdiction;
    const label = `${jurisdiction} · ${source.title}`;
    return catalog.sources.filter(item => item.jurisdiction === jurisdiction && item.title === source.title).length > 1
      ? `${label} · ${source.sourceId}` : label;
  }
  return source.title || source.source;
}
export const SNAPSHOT_CATALOG: DataCatalog = {
  mode: 'snapshot', localStatus: 'not_requested', datasetVersion: DEFAULT_FILTERS.datasetVersion, batchId: DEFAULT_FILTERS.batchId,
  coverage: DEFAULT_FILTERS.dateRange,
  sources: [['NSW','New South Wales'],['VIC','Victoria'],['QLD','Queensland']].map(([source,title]) => ({
    source, sourceId: `official_${source.toLowerCase()}`, title, jurisdiction: source, publisher: 'Official project snapshot',
    batchId: DEFAULT_FILTERS.batchId, origin: 'snapshot', coverage: DEFAULT_FILTERS.dateRange,
    capabilities: { monthly: true, severity: true, geography: true, units: false }, definitions: {}, limitations: [],
  })),
};
export function catalogFilters(catalog: DataCatalog): Filters {
  return { source: 'All', dateRange: coverageMonthRange(catalog.coverage), datasetVersion: catalog.datasetVersion, batchId: catalog.batchId, ...(catalog.releaseId ? { releaseId: catalog.releaseId } : {}) };
}
/** Query whole months without changing the source's exact declared coverage. */
export function coverageMonthRange(coverage: Filters['dateRange']): Filters['dateRange'] {
  const year = Number(coverage.to.slice(0, 4)), month = Number(coverage.to.slice(5, 7));
  return { from: `${coverage.from.slice(0, 7)}-01`, to: `${coverage.to.slice(0, 7)}-${new Date(Date.UTC(year, month, 0)).getUTCDate()}` };
}
export function sourceCoverage(catalog: DataCatalog, source: string) {
  return catalog.sources.find(item => item.source === source)?.coverage || catalog.coverage;
}
export async function fetchCatalog(releaseId?: string, signal?: AbortSignal, snapshot = false): Promise<DataCatalog> {
  const p = new URLSearchParams();
  if (releaseId) p.set('releaseId', releaseId);
  if (snapshot) p.set('datasetVersion', DEFAULT_FILTERS.datasetVersion);
  const r = await fetch(`/api/data/catalog?${p}`, { signal, cache: 'no-store' });
  if (!r.ok) throw Error('The requested data release is unavailable. No newer version has been substituted.');
  return r.json();
}

/** Area filters need an actual area provider; rounded coordinates alone do not qualify. */
export function hasRegionalProvider(source: CatalogSource | undefined, releaseId?: string): boolean {
  if (!source?.capabilities.geography) return false;
  if (source.origin === 'snapshot') return true;
  const binding = source.regionalProvider;
  return !!binding && binding.kind === 'verified-lga-snapshot' && binding.releaseId === releaseId &&
    binding.sourceId === source.sourceId && binding.sourceBatchId === source.batchId;
}
