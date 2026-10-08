import { hasRegionalProvider, type DataCatalog } from '../services/catalog-contracts';
import type { Filters, Provenance } from '../services/contracts';

interface SnapshotIdentity { batchId:string; datasetVersion:string; extensionVersion:string; coverage:Filters['dateRange'] }
export interface DerivedEvidence extends Omit<SnapshotIdentity, "coverage"> {
  aggregateSha256:string;
  inputs:{sourceId:string;resourceId:string;sha256:string}[];
}
export interface DerivedBinding {
  source:string; sourceBatchId:string; releaseId?:string;
  extensionVersion:string; derivationBatchId:string; derivationDatasetVersion:string;
  aggregateSha256?:string; inputs?:{resourceId:string;sha256:string}[];
}

/** Server-created catalog proof, never a client flag or merely matching totals. */
export function derivedSourceBinding(filters:Filters, source:string, snapshot:SnapshotIdentity,
  catalog?:DataCatalog, evidence?:DerivedEvidence):DerivedBinding|undefined {
  const direct=!filters.releaseId && filters.batchId===snapshot.batchId && filters.datasetVersion===snapshot.datasetVersion;
  const proof={source,sourceBatchId:snapshot.batchId,extensionVersion:snapshot.extensionVersion,
    derivationBatchId:snapshot.batchId,derivationDatasetVersion:snapshot.datasetVersion};
  if (!catalog) return direct ? proof : undefined;
  if (filters.batchId!==catalog.batchId || filters.datasetVersion!==catalog.datasetVersion || filters.releaseId!==catalog.releaseId) return;
  const entry=catalog.sources.find(s=>s.source===source);
  if (!entry) return;
  if (catalog.mode==='snapshot') return direct && entry.batchId===snapshot.batchId ? proof : undefined;
  if (!evidence || evidence.batchId!==snapshot.batchId || evidence.datasetVersion!==snapshot.datasetVersion ||
    evidence.extensionVersion!==snapshot.extensionVersion || !/^[a-f0-9]{64}$/.test(evidence.aggregateSha256)) return;
  const inputs=evidence.inputs.filter(i=>i.sourceId===entry.sourceId);
  if (!inputs.length || new Set(inputs.map(i=>i.resourceId)).size!==inputs.length) return;
  if (entry.origin==='snapshot') {
    if (entry.batchId!==snapshot.batchId) return;
  } else {
    // The reviewed native publication proof already checks every original role,
    // QA01–06, full coverage, 60 monthly metric tuples and native severities.
    // This extra join proves that this particular extension used those inputs.
    const binding=entry.regionalProvider;
    if (!hasRegionalProvider(entry,catalog.releaseId) || !binding ||
      binding.batchId!==snapshot.batchId || binding.datasetVersion!==snapshot.datasetVersion ||
      binding.coverage.from!==snapshot.coverage.from || binding.coverage.to!==snapshot.coverage.to ||
      !inputs.every(i=>binding.inputs.filter(b=>b.resourceId===i.resourceId).length===1 &&
        binding.inputs.some(b=>b.resourceId===i.resourceId && b.sha256===i.sha256))) return;
  }
  return {...proof,sourceBatchId:entry.batchId,releaseId:catalog.releaseId,aggregateSha256:evidence.aggregateSha256,
    inputs:inputs.map(i=>({resourceId:i.resourceId,sha256:i.sha256}))};
}

export function checkDerivedResponse(meta:Provenance, filters:Filters, binding:DerivedBinding) {
  if (meta.source!==binding.source || meta.batchId!==filters.batchId || meta.datasetVersion!==filters.datasetVersion ||
    meta.releaseId!==filters.releaseId || (filters.releaseId && meta.sourceBatchId!==binding.sourceBatchId))
    throw Error('Derived report source identity mismatch.');
}
export function derivedEvidenceLink(report:string, filters:Filters) {
  return `/api/data/${report}?${new URLSearchParams({source:filters.source,from:filters.dateRange.from,to:filters.dateRange.to,
    datasetVersion:filters.datasetVersion,batchId:filters.batchId,...(filters.releaseId?{releaseId:filters.releaseId}:{}),
    ...(filters.regionId?{regionId:filters.regionId}:{})})}`;
}
