import test from 'node:test';
import assert from 'node:assert/strict';
import { createPublicationCache } from '../src/server/publication-cache';
import { sourceDisplayName, SNAPSHOT_CATALOG, type CatalogSource } from '../src/services/catalog-contracts';
const release = 'aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa';
test('concurrent reports share pinned queries, retain identity and do not share mutable objects',async()=>{
 const read=createPublicationCache();let calls=0;
 const load=async()=>{calls++;await new Promise(r=>setTimeout(r,10));return {count:12};};
 const query={release_id:release,source_id:'sa',from:'2020-01-01',to:'2024-12-31'};
 const results=await Promise.all(Array.from({length:4},()=>read('query',query,load)));
 assert.equal(calls,1);results[0].count=99;assert.equal(results[1].count,12);
 assert.equal((await read('query',query,load)).count,12);assert.equal(calls,1);
 await read('query',{...query,release_id:'bbbbbbbb-1111-4111-8111-aaaaaaaaaaaa'},load);
 await read('query',{...query,from:'2021-01-01'},load);assert.equal(calls,3);
});
test('failed reads are retryable, latest is uncached, and pinned entries expire',async()=>{
 let time=0,calls=0;const read=createPublicationCache(()=>time),q={release_id:release};
 await assert.rejects(read('query',q,async()=>{throw Error('temporary');}));
 const load=async()=>++calls;
 assert.equal(await read('query',q,load),1);time=30001;assert.equal(await read('query',q,load),2);
 assert.equal(await read('catalog',{},load),3);assert.equal(await read('catalog',{},load),4);
});
test('distinct pinned queries keep database concurrency bounded',async()=>{
 const read=createPublicationCache();let active=0,max=0;
 await Promise.all(Array.from({length:7},(_,i)=>read('query',{release_id:release,source_id:String(i)},async()=>{
  active++;max=Math.max(max,active);await new Promise(r=>setTimeout(r,5));active--;return i;
 })));
 assert.equal(max,2);assert.equal(active,0);
});
test('source labels use jurisdiction and distinguish fixtures without changing identities',()=>{
 const sa:CatalogSource={...SNAPSHOT_CATALOG.sources[0],source:'sa_road_crash_data',sourceId:'sa_road_crash_data',jurisdiction:'SA',title:'Road crash data'};
 const act={...sa,source:'act_open_data_6jn4_m8rx',sourceId:'act_open_data_6jn4_m8rx',jurisdiction:'ACT',title:'ACT Road Crash Data'};
 const fixture={...sa,source:'browser_fixture',sourceId:'browser_fixture',jurisdiction:'BROWSER_FIXTURE',title:'browser fixture'};
 const catalog={...SNAPSHOT_CATALOG,sources:[...SNAPSHOT_CATALOG.sources,sa,act,fixture]};
 assert.equal(sourceDisplayName(sa,catalog),'SA');assert.equal(sourceDisplayName(act,catalog),'ACT');
 assert.equal(sourceDisplayName(fixture,catalog),'Browser test sample');assert.equal(sa.source,'sa_road_crash_data');
 const second={...sa,sourceId:'sa2',source:'sa2',title:'Another SA source'};
 assert.equal(sourceDisplayName(sa,{...catalog,sources:[sa,second]}),'SA · Road crash data');
});
