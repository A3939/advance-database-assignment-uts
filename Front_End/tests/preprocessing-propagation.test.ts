import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { resolveCatalog } from '../src/server/data-catalog';
import { createPublishedProvider } from '../src/server/published-data';
import type { OfficialReadService } from '../src/server/official-data';
import { DEFAULT_FILTERS } from '../src/services/config';
import { StudioStore, uuid } from '../src/server/studio/store';
import { ResearchCollector } from '../src/server/studio/collector';
import { exportStudy } from '../src/server/studio/export';

test('Q01 actual accepted query retains partial identity through provider, Studio and export', async () => {
  assert.ok(process.env.ARSIA_QUALITY_QUERY_FIXTURE && process.env.ARSIA_QUALITY_STUDIO_ROOT);
  const accepted = JSON.parse(readFileSync(process.env.ARSIA_QUALITY_QUERY_FIXTURE!, 'utf8'));
  const q = accepted.query;
  const read = async <T>(path: string): Promise<T> => (path === 'catalog'
    ? {release_id:q.release_id, sources:[{source_id:q.source_id,batch_id:q.batch_id,jurisdiction:'ACT',source_name:'Original ACT research fixture',publisher:'Identity unverified',coverage:q.coverage,capabilities:{monthly:true,severity:true,geography:false,units:false},definitions:{},limitations:q.limitations,publication_status:q.publication_status}]}
    : q) as T;
  const catalog = await resolveCatalog(q.release_id, false, read);
  const provider = createPublishedProvider(catalog, {} as OfficialReadService, read);
  const filters = {...DEFAULT_FILTERS,source:catalog.sources.find(source=>source.sourceId===q.source_id)!.source,releaseId:q.release_id,batchId:catalog.batchId,datasetVersion:catalog.datasetVersion,dateRange:{from:'2015-01-01',to:'2026-12-31'}};
  const result = await provider.getOverview(filters);
  const json = JSON.stringify(result);
  assert.ok(json.includes('"status":"partial"') && json.includes('"target_satisfied":false') && json.includes('"official_registration":false'));
  assert.equal(result.meta.coverage.complete,false);
  const root = resolve(process.env.ARSIA_QUALITY_STUDIO_ROOT!);
  mkdirSync(root);writeFileSync(join(root,'ownership.json'),JSON.stringify({owner:'ARSIA scope coordinator acceptance',normalStudio:false,sourceQuery:q.release_id}));
  const store = new StudioStore(join(root,'research.sqlite'));
  try {
    const s=store.create('Partial original ACT query propagation',{filters,metric:'crashes',notes:'Isolated serialization acceptance only; no model inference',references:''});
    const {run}=store.beginRun(s.id,uuid(),'Preserve partial query metadata');
    const collector=new ResearchCollector(store,s.id,run);
    await collector.accept({type:'evidence',evidence:{id:'E1',title:'Actual accepted query',description:'Unverified local research; missing people counts',result,query:{tool:'get_overview',parameters:{},requestedContext:{page:'/studio',filters},validated:true}}});
    await collector.accept({type:'message',text:'Partial research result; people counts remain unknown. [E1]',simulated:false});
    await collector.accept({type:'done',model:'deterministic-test-substitute'});
    const saved=collector.persist();
    const exported=exportStudy(store,saved);writeFileSync(join(root,'export.zip'),exported);
    // Existing export uses stored ZIP entries. Read the actual manifest bytes.
    let offset=0, manifest: unknown;
    while(exported.readUInt32LE(offset)===0x04034b50){
      const size=exported.readUInt32LE(offset+18),names=exported.readUInt16LE(offset+26),extra=exported.readUInt16LE(offset+28);
      const name=exported.subarray(offset+30,offset+30+names).toString();const start=offset+30+names+extra;
      if(name==='manifest.json')manifest=JSON.parse(exported.subarray(start,start+size).toString());
      offset=start+size;
    }
    const serialized=JSON.stringify(manifest);
    assert.ok(serialized.includes('"status":"partial"') && serialized.includes('"unknown_count":76657') && serialized.includes('"official_registration":false'));
    writeFileSync(join(root,'result.json'),JSON.stringify({passed:true,real_models:0,queryWasSavedActualAPIResult:true,providerTransport:'frozen query substitute; no network',studio:'new independent SQLite',partialMetadataPreserved:true},null,2));
  } finally {store.close();}
});
