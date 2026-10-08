import { bindRegionalPublication } from './regional-publication';
import { LOCAL_DATE_BOUNDS } from "../services/date-range";
/** Local composite releases reference immutable snapshots; they never rewrite them. */
import { bridgeImport } from './imports/bridge';
import { localHttpOrigin } from './local-request';
import { LOCAL_VERSION, SNAPSHOT_CATALOG, hasRegionalProvider, type DataCatalog, type CatalogSource } from '../services/catalog-contracts';
import { parseOfficialFilters } from './official-data';
import type { Filters } from '../services/contracts';
import { validateWholeDateRange } from '../services/date-range';
import { createPublicationCache } from './publication-cache';
const cachedPublication = createPublicationCache();
export class PublicationUnavailable extends Error {
  constructor(public status = 503) { super("The local publication service is unavailable. The selected release has not been replaced."); }
}
export async function publicationRead<T>(path: string, query: Record<string,string> = {}): Promise<T> {
  return cachedPublication(path, query, async () => {
  const origin = localHttpOrigin();
  if (!origin) throw new PublicationUnavailable();
  const response = await bridgeImport(new Request(`${origin}/api/imports/${path}?${new URLSearchParams(query)}`, { headers: { host: new URL(origin).host, origin } }), [path]);
  if (!response.ok) throw new PublicationUnavailable(response.status === 404 ? 404 : 503);
  return response.json();
  });
}
interface PublishedSource {
  publication_status?: CatalogSource['publicationStatus'];
  source_id: string; batch_id: string; jurisdiction?: string; source_name?: string; publisher?: string;
  complete_intervals?: {from:string;to:string}[];
  coverage?: {from:string;to:string}; definitions?: Record<string,string>;
  capabilities?: CatalogSource['capabilities']; limitations?: string[];
  licensing?: CatalogSource['licensing'];
  capability_limits?: CatalogSource['capabilityLimits'];
  capability_review?: unknown;
  row_preprocessing?: CatalogSource['rowPreprocessing'];
  retained_resources?: CatalogSource['retainedResources'];
  summary?: {year_from?:number;year_to?:number};
}
export async function resolveCatalog(releaseId?: string, snapshot = false, read: typeof publicationRead = publicationRead): Promise<DataCatalog> {
  if (snapshot) { if (releaseId) throw Error("A snapshot URL cannot request a local release."); return SNAPSHOT_CATALOG; }
  let raw: { release_id: string|null; sources: PublishedSource[] };
  try { raw = await read('catalog', releaseId ? {release_id:releaseId} : {}); }
  catch (error) { throw error instanceof PublicationUnavailable ? error : new PublicationUnavailable(); }
  if (!raw.release_id) { if (releaseId) throw Error('Unknown release.'); return {...SNAPSHOT_CATALOG, localStatus:'empty'}; }
  if (releaseId && raw.release_id !== releaseId) throw Error('Release mismatch.');
  const sources = [...SNAPSHOT_CATALOG.sources];
  for (const item of raw.sources) {
    const baseline = SNAPSHOT_CATALOG.sources.find(s => s.sourceId === item.source_id);
    const source = baseline?.source || item.source_id;
    const coverage = item.coverage || (item.summary?.year_from && item.summary.year_to ? {from:`${item.summary.year_from}-01-01`,to:`${item.summary.year_to}-12-31`} : undefined);
    if (!coverage) continue; // No invented temporal coverage.
    const entry: CatalogSource = {source, sourceId:item.source_id, title:item.source_name || source, jurisdiction:item.jurisdiction || '', publisher:item.publisher || '', batchId:item.batch_id, origin:'publication', coverage, completeIntervals:item.complete_intervals || [], licensing:item.licensing,
      publicationStatus:item.publication_status, capabilityLimits:item.capability_limits || [], capabilityReview:item.capability_review, rowPreprocessing:item.row_preprocessing, retainedResources:item.retained_resources,
      capabilities:item.capabilities ? {...item.capabilities} : {monthly:false,severity:true,geography:false,units:false}, definitions:item.definitions || {}, limitations:item.limitations || []};
    entry.regionalProvider = await bindRegionalPublication(entry, raw.release_id, read);
    if (entry.regionalProvider) entry.capabilities.geography = true;
    const index = sources.findIndex(s => s.sourceId === item.source_id);
    if (index >= 0) sources[index] = entry; else sources.push(entry);
  }
  return {mode:'local',localStatus:'connected',releaseId:raw.release_id,datasetVersion:LOCAL_VERSION,batchId:raw.release_id,sources,
    coverage:{from:sources.map(s=>s.coverage.from).sort()[0],to:sources.map(s=>s.coverage.to).sort().at(-1)!}};
}
/** Syntactic parsing only; authoritative source membership is checked against the pinned catalog. */
export function parseDataFilters(query: URLSearchParams): Filters {
  if (query.get('datasetVersion') !== LOCAL_VERSION) return parseOfficialFilters(query);
  const source = query.get('source') || 'All', releaseId = query.get('releaseId') || query.get('batchId') || '';
  if (!/^[a-f0-9-]{36}$/.test(releaseId) || query.get('batchId') !== releaseId) throw Error('Invalid release identity.');
  if (!/^[A-Za-z0-9_.-]{1,100}$/.test(source)) throw Error('Invalid source identity.');
  const dateRange = {from:query.get('from') || '',to:query.get('to') || ''};
  const error = validateWholeDateRange(dateRange, LOCAL_DATE_BOUNDS); if (error) throw Error(error);
  const regionId = query.get('regionId') || undefined;
  if (regionId && !/^\d{1,10}$/.test(regionId)) throw Error('Invalid region.');
  return {source,dateRange,datasetVersion:LOCAL_VERSION,batchId:releaseId,releaseId,regionId};
}
export function validateCatalogFilters(filters: Filters, catalog: DataCatalog) {
  if (filters.datasetVersion !== catalog.datasetVersion || filters.batchId !== catalog.batchId || (filters.releaseId || undefined) !== catalog.releaseId) throw Error('Release mismatch.');
  if (filters.source !== 'All' && !catalog.sources.some(s=>s.source===filters.source)) throw Error('Source is unavailable in this release.');
  if (filters.regionId) {
    const source = catalog.sources.find(s=>s.source===filters.source);
    if (!hasRegionalProvider(source, catalog.releaseId)) throw Error('Regional filters require a verified ABS area provider for this source.');
    if (source?.regionalProvider && (filters.dateRange.from < source.regionalProvider.coverage.from || filters.dateRange.to > source.regionalProvider.coverage.to)) throw Error('The regional selection is outside verified coverage.');
  }
}
