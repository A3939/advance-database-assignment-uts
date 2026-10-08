/** Read-only by default. --live explicitly makes two model calls and saves a validation study. */
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import {createHash,randomUUID} from 'node:crypto';
import assert from 'node:assert/strict';
const args=process.argv.slice(2),value=(flag)=>args[args.indexOf(flag)+1];
if(!args.includes('--source'))throw Error('Pass --source with an exact catalog source ID. Add --live to exercise Ask AI and Studio.');
const base='http://127.0.0.1:3100',headers={'Content-Type':'application/json',Origin:base};
const requestedSource=value('--source');
async function get(path){const r=await fetch(base+path,{headers,cache:'no-store'});if(!r.ok)throw Error(`HTTP ${r.status}: ${path.split('?')[0]}`);return r.json();}
async function post(path,body){const r=await fetch(base+path,{method:'POST',headers,body:JSON.stringify(body),signal:AbortSignal.timeout(250000)});if(!r.ok)throw Error(`HTTP ${r.status}: ${path}`);return r;}
async function events(response){let pending='';const out=[],decoder=new TextDecoder();for await(const chunk of response.body){pending+=decoder.decode(chunk,{stream:true});let at;while((at=pending.indexOf('\n'))>=0){const line=pending.slice(0,at);pending=pending.slice(at+1);if(!line.trim())continue;const item=JSON.parse(line);out.push(item);if(['error','done'].includes(item.type))console.log(JSON.stringify({event:item.type,code:item.code}));}}return out;}
const catalog=await get('/api/data/catalog'+(args.includes('--release')?'?releaseId='+encodeURIComponent(value('--release')):''));
assert.equal(catalog.mode,'local');
const source=catalog.sources.find(s=>s.source===requestedSource||s.sourceId===requestedSource);
assert.ok(source,'Source must already be published in the selected release.');assert.equal(source.origin,'publication');
const dateRange={from:source.coverage.from.slice(0,7)+'-01',to:source.coverage.to.slice(0,7)+'-'+new Date(Date.UTC(Number(source.coverage.to.slice(0,4)),Number(source.coverage.to.slice(5,7)),0)).getUTCDate()};
const filters={source:source.source,dateRange,datasetVersion:catalog.datasetVersion,batchId:catalog.batchId,releaseId:catalog.releaseId};
const query=new URLSearchParams({source:filters.source,from:filters.dateRange.from,to:filters.dateRange.to,datasetVersion:filters.datasetVersion,batchId:filters.batchId,releaseId:filters.releaseId});
const [overview,trend,metadata]=await Promise.all([get('/api/data/overview?'+query),get('/api/data/timeseries?'+query+'&granularity=yearly'),get('/api/data/metadata?'+query)]);
assert.equal(overview.meta.releaseId,catalog.releaseId);assert.equal(overview.meta.sourceBatchId,source.batchId);
assert.equal(trend.meta.releaseId,catalog.releaseId);assert.ok(metadata.some(d=>d.source===source.source&&d.sourceBatchId===source.batchId));
const keys=['crashes','fatalCrashes','livesLost','casualties'];
let expected=Object.fromEntries(keys.map(k=>[k,overview.data[k].value]));
const output={verifiedAt:new Date().toISOString(),mode:args.includes('--live')?'live-model':'read-only',catalog,filters,expected,overview,trend};
const directory='artifacts/analysis-verification/local-'+source.source.replace(/[^A-Za-z0-9_-]/g,'_');await mkdir(directory,{recursive:true});
try{
 if(args.includes('--oracle')){
  const oraclePath=value('--oracle'),oracleBytes=await readFile(oraclePath),oracle=JSON.parse(oracleBytes);
  const fields={crashes:'crash_count',fatalCrashes:'fatal_crash_count',livesLost:'fatalities',casualties:'casualties'};
  expected=Object.fromEntries(keys.map(key=>{const count=oracle.summary?.[fields[key]];assert.ok(count===null || Number.isSafeInteger(count),`Oracle must establish ${key} or explicitly preserve null`);return [key,count];}));
  for(const key of keys)assert.equal(overview.data[key].value,expected[key],`Independent oracle ${key}`);
  const monthly=await get('/api/data/timeseries?'+query+'&granularity=monthly');
  assert.equal(monthly.meta.releaseId,catalog.releaseId);assert.equal(monthly.meta.sourceBatchId,source.batchId);
  for(const [frequency,result] of [['yearly',trend],['monthly',monthly]]){
   assert.deepEqual(result.data.map(row=>row.period).sort(),Object.keys(oracle[frequency]).sort(),`Independent oracle ${frequency} periods`);
   for(const row of result.data)for(const key of keys)assert.equal(row[key],oracle[frequency][row.period][fields[key]],`Independent oracle ${frequency} ${row.period} ${key}`);
  }
  output.expected=expected;output.oracle={path:oraclePath,sha256:createHash('sha256').update(oracleBytes).digest('hex'),version:oracle.oracle_version,inputSha256:oracle.input_upload_sha256,summary:oracle.summary,yearlyPoints:trend.data.length,monthlyPoints:monthly.data.length,status:'passed'};
  output.monthly=monthly;
  output.geography=await get('/api/data/map?'+query);
  console.log(JSON.stringify({event:'independent_oracle_passed',expected,yearlyPoints:trend.data.length,monthlyPoints:monthly.data.length}));
 }
 if(args.includes('--live')){
  const question='请只按当前来源、日期和固定 release 调用 core_metrics 工具，报告事故数、致命事故数、死亡人数、伤亡人数。明确区分 null 和零；保留来源及 release。不要扩大日期、切换数据来源或估算未知指标。';
  output.askAI=await events(await post('/api/agent',{context:{page:'/',filters},message:question,history:[]}));
  assert.ok(!output.askAI.some(e=>e.type==='error'),'Ask AI must complete without errors');
  const evidence=output.askAI.find(e=>e.type==='tool_result'&&e.name==='core_metrics');assert.ok(evidence,'Ask AI must execute the trusted core_metrics tool');
  assert.equal(evidence.data.releaseId,catalog.releaseId);
  const measured=evidence.data.results.find(r=>r.source===source.source);assert.ok(measured);
  for(const key of keys)assert.equal(measured.data[key].value,expected[key],`Ask AI ${key}`);
  const study=await (await post('/api/studio',{kind:'analytics',title:`Local release validation · ${source.source}`,question:'Pinned annual crash counts',granularity:'yearly',context:{filters,metric:'crashes',notes:'Explicit local integration validation; preserve this source release.',references:''}})).json();
  output.studyId=study.id;
  assert.equal(study.context.filters.releaseId,catalog.releaseId);
  assert.equal(study.runs[0].context.filters.releaseId,catalog.releaseId);
  output.studioEvents=await events(await post(`/api/studio/${study.id}/runs`,{requestId:randomUUID(),question,skipPresentation:true}));
  const saved=await get(`/api/studio/${study.id}`);output.study=saved;
  const run=saved.runs.at(-1);assert.equal(run.status,'complete');assert.equal(run.context.filters.releaseId,catalog.releaseId);
  const studioMetric=run.evidence.find(e=>e.query?.tool==='core_metrics');assert.ok(studioMetric,'Studio must retain validated metric evidence');
  assert.equal(studioMetric.result.releaseId,catalog.releaseId);
  const studioMeasured=studioMetric.result.results.find(r=>r.source===source.source);assert.ok(studioMeasured);
  for(const key of keys)assert.equal(studioMeasured.data[key].value,expected[key],`Studio ${key}`);
  const exported=await fetch(`${base}/api/studio/${study.id}/export`,{headers});assert.ok(exported.ok);const bytes=Buffer.from(await exported.arrayBuffer());
  assert.ok(bytes.includes(Buffer.from(catalog.releaseId)),'Export must preserve release identity');
  await writeFile(`${directory}/study.zip`,bytes);
 }
 output.status='passed';
}catch(error){output.status='failed';output.error=error instanceof Error?error.message:String(error);process.exitCode=1;}
await writeFile(`${directory}/verification.json`,JSON.stringify(output,null,2));
console.log(JSON.stringify({status:output.status,mode:output.mode,source:source.source,release:catalog.releaseId,expected,studyId:output.studyId,evidence:`${directory}/verification.json`,error:output.error}));
