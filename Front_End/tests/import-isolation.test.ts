import test from 'node:test';
import assert from 'node:assert/strict';
import { isolatedTestSocket } from '../src/server/imports/test-environment';
import { isolatedImports, localImports } from '../src/services/imports-client';
const config = {mode:'local-test',purpose:'manual-upload-isolated',database:'arsia_imports_test_manual_123456789abc',instance_id:'a'.repeat(32),socket_path:'/tmp/arsia-imports-manual-123456789abc/api.sock'};
const main = {database:'arsia_imports_main',instance_id:'b'.repeat(32),socket_path:'/tmp/arsia-imports-1234/api.sock'};
test('manual test routing fails closed for missing or shared runtime identities',()=>{
  assert.equal(isolatedTestSocket(config,main),config.socket_path);
  for (const patch of [{database:main.database},{instance_id:main.instance_id},{socket_path:main.socket_path},{purpose:'ordinary'},{database:undefined},{socket_path:'/tmp/arbitrary.sock'}]) assert.throws(()=>isolatedTestSocket({...config,...patch},main));
  assert.throws(()=>isolatedTestSocket({},main));
});
test('isolated and existing clients preserve separate API destinations',async()=>{
  const calls:string[]=[];const original=globalThis.fetch;
  globalThis.fetch=async(input)=>{calls.push(String(input));return Response.json({});};
  try {
    await isolatedImports.health();await isolatedImports.create('manual','SA','request');await isolatedImports.submit('test-job');await isolatedImports.cancel('test-job');await isolatedImports.report('sa','release');await localImports.health();
    assert.deepEqual(calls,['/api/imports-test/health','/api/imports-test/jobs','/api/imports-test/jobs/test-job/submit','/api/imports-test/jobs/test-job/cancel','/api/imports-test/reports?source_id=sa&release_id=release','/api/imports/health']);
  } finally {globalThis.fetch=original;}
});
test('manual binary upload uses only the isolated endpoint',async()=>{
  const original=globalThis.XMLHttpRequest;let url='';let body:unknown;
  class XHR {
    upload={};status=200;responseText='{}';onload=()=>{};
    open(method:string,path:string){assert.equal(method,'PUT');url=path;}
    setRequestHeader(){} abort(){} send(data:unknown){body=data;this.onload();}
  }
  globalThis.XMLHttpRequest=XHR as unknown as typeof XMLHttpRequest;
  try {
    const file=new File(['official fixture'],'sa.zip');
    await isolatedImports.upload('new-job',file,new AbortController().signal,()=>{});
    assert.equal(url,'/api/imports-test/jobs/new-job/files?filename=sa.zip');assert.equal(body,file);
  } finally {globalThis.XMLHttpRequest=original;}
});
