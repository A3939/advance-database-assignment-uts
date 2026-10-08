/** Explicit service acceptance against a newly owned Python harness Unix socket.
 * Never changes the application's import binding or opens the normal Studio DB.
 */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import http from 'node:http';
import {performance} from 'node:perf_hooks';
import {resolveCatalog,type publicationRead} from '../src/server/data-catalog';
import {createPublishedProvider} from '../src/server/published-data';
import {createOfficialProvider,loadOfficialSnapshot} from '../src/server/official-data';
import {catalogFilters,coverageMonthRange,sourceDisplayName} from '../src/services/catalog-contracts';
import {analysisRuntime} from '../src/server/agent/runtime';
import {executeAnalysisTool} from '../src/server/agent/tools';

async function main(){
 const filename=process.argv[2];assert.ok(filename && path.isAbsolute(filename));
 const control=JSON.parse(await fs.readFile(filename,'utf8'));
 assert.match(control.socket,/^\/[^\n]+\/arsia-source-read-[^/]+\/read\.sock$/);
 const socket=await fs.lstat(control.socket);assert.ok(socket.isSocket());
 const folder=await fs.stat(path.dirname(control.socket));assert.equal(folder.mode & 0o777,0o700);
 const calls:{path:string;seconds:number}[]=[];
 const read=(async (endpoint:string,query:Record<string,string>={})=>{
   assert.ok(['catalog','query','__acceptance_identity'].includes(endpoint));
   const started=performance.now();
   const value=await new Promise((resolve,reject)=>{
     const request=http.get({socketPath:control.socket,path:`/${endpoint}?${new URLSearchParams(query)}`},response=>{
       let data='';response.setEncoding('utf8');response.on('data',chunk=>{data+=chunk;if(data.length>16*1024*1024)request.destroy(Error('Read budget exceeded'));});
       response.on('end',()=>{try{assert.equal(response.statusCode,200,`${endpoint} ${JSON.stringify(query)}: ${data.slice(0,1000)}`);resolve(JSON.parse(data));}catch(error){reject(error);}});
     });request.setTimeout(30000,()=>request.destroy(Error('Isolated read timed out')));request.on('error',reject);
   });calls.push({path:endpoint,seconds:(performance.now()-started)/1000});return value;
 }) as typeof publicationRead;
 assert.deepEqual(await read('__acceptance_identity'),{instance_id:control.instance_id,test_session_id:control.test_session_id,marker:control.marker});
 const catalog=await resolveCatalog(control.release_id,false,read);
 const entry=catalog.sources.find(s=>s.sourceId===control.source_id);assert.ok(entry);assert.equal(entry.batchId,control.batch_id);
 const service=createPublishedProvider(catalog,createOfficialProvider(await loadOfficialSnapshot()),read);
 // The product's date picker selects whole months. Observed partial months
 // remain incomplete in provenance; expanding a query does not invent rows.
 const dateRange=coverageMonthRange(control.coverage);
 const filters={...catalogFilters(catalog),source:entry.source,dateRange};
 const [overview,monthly,severity,map,metadata]=await Promise.all([
   service.getOverview(filters),service.getTimeSeries(filters,'monthly'),service.getSeverityDistribution(filters),service.getMapData(filters),service.getDatasetMetadata()]);
 assert.equal(overview.meta.releaseId,control.release_id);assert.equal(overview.meta.sourceBatchId,control.batch_id);
 assert.equal(overview.data.crashes.value,control.expected.rows);
 assert.equal(overview.data.fatalCrashes.value,control.expected.fatal_crashes);
 assert.equal(overview.data.livesLost.value,control.expected.fatalities ?? null);
 assert.equal(overview.data.casualties.value,control.expected.casualties ?? null);
 if(entry.capabilities.severity)assert.equal(severity.data.reduce((sum,row)=>sum+row.count,0),control.expected.rows);
 else assert.equal(severity.meta.availability,'unsupported');
 if(entry.capabilities.monthly)assert.equal(monthly.data.reduce((sum,row)=>sum+(row.crashes ?? 0),0),control.expected.rows);
 else {assert.equal(monthly.meta.availability,'unsupported');assert.deepEqual(monthly.data,[]);}
 const sourceMeta=metadata.find(item=>item.source===entry.source);assert.ok(sourceMeta);
 assert.equal(sourceMeta.releaseId,control.release_id);
 if(entry.capabilities.geography)assert.equal(map.meta.availability,'available');
 else {assert.equal(map.meta.availability,'unsupported');
  if(control.expected.limited){assert.ok(entry.capabilityLimits?.some(item=>item.requested && !item.target_satisfied));assert.ok(JSON.stringify(map.meta.evidence).includes(control.expected.limited));assert.ok(JSON.stringify(sourceMeta.evidence).includes(control.expected.limited));}
 }
 assert.equal(overview.meta.coverage.complete,false,'Observed extent must not silently establish complete population coverage');
 if(control.expected.duplicates!==undefined){assert.equal(entry.rowPreprocessing?.collapsed_duplicate_rows,control.expected.duplicates);assert.ok(sourceMeta.evidence?.some(item=>item.title==='Original row destinations'));}
 const context={page:'/studio',filters};
 const runtime=await analysisRuntime(context,read);
 const askMetadata=await executeAnalysisTool('dataset_metadata',{source:null},context,runtime.service,runtime.snapshot);
 const studioCatalog=await runtime.workspace.execute('workspace_catalog',{},new AbortController().signal,'E1');
 assert.equal(askMetadata.releaseId,control.release_id);assert.equal(studioCatalog.releaseId,control.release_id);
 if(control.expected.manualResearch){
   assert.equal(entry.publicationStatus?.admission_level,'manual_reviewed');
   assert.equal(entry.publicationStatus.official_registration,false);
   assert.match(sourceDisplayName(entry,catalog),/local research/);
   for(const value of [overview.meta.evidence,monthly.meta.evidence,map.meta.evidence,sourceMeta,askMetadata,studioCatalog]){
     assert.match(JSON.stringify(value),/official source identity unverified/);
   }
 }
 if(control.expected.limited){
   assert.ok(JSON.stringify(askMetadata).includes(control.expected.limited));
   assert.ok(JSON.stringify(studioCatalog).includes(control.expected.limited));
 }
 // The immutable metadata path is measured separately from detail aggregates.
 const times=[];for(let i=0;i<20;i++){const tick=performance.now();await resolveCatalog(control.release_id,false,read);times.push(performance.now()-tick);}
 times.sort((a,b)=>a-b);
 await fs.writeFile(control.output,JSON.stringify({status:'passed',instance_id:control.instance_id,test_session_id:control.test_session_id,
   release_id:control.release_id,batch_id:control.batch_id,source_id:control.source_id,api:'real ASGI via private Unix socket',
   browser:'not_run',model_calls:0,catalog,filters,overview,monthly,severity,map,sourceMetadata:sourceMeta,askMetadata,studioCatalog,calls,
   catalogLatencyMs:{n:times.length,p50:times[9],p95:times[18],cache:'injected real transport; no Node publication cache'}},null,2),{flag:'wx'});
}
main().catch(error=>{console.error(error);process.exitCode=1;});
