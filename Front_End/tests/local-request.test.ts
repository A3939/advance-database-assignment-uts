import test from 'node:test';
import { NextRequest } from 'next/server';
import assert from 'node:assert/strict';
import { localRequest } from '../src/server/local-request';
import { sameOrigin } from '../src/server/agent/request';
import { guardImportRequest } from '../src/server/imports/bridge';
import { guard } from '../src/server/studio/http';

test('Agent, Imports and Studio enforce the same loopback Host/Origin boundaries',()=>{
 const cases:[Record<string,string>,string,string,boolean][]=[
 [{host:'127.0.0.1:3100',origin:'http://127.0.0.1:3100'},'POST','http://localhost:3100/api',true],
 [{host:'127.0.0.1:3100'},'POST','http://localhost:3100/api',false],
 [{host:'evil.example',origin:'http://evil.example'},'POST','http://evil.example/api',false],
 [{host:'127.0.0.1:3101',origin:'http://127.0.0.1:3101'},'POST','http://localhost:3101/api',false],
 [{host:'127.0.0.1:3100','sec-fetch-site':'same-origin',referer:'http://127.0.0.1:3100/studio'},'GET','http://localhost:3100/api',true],
 [{host:'127.0.0.1:3100',origin:'null'},'POST','http://localhost:3100/api',false],
 ];
 for(const [headers,method,url,ok] of cases){const req=new Request(url,{headers,method});assert.equal(localRequest(req),ok);assert.equal(sameOrigin(req),ok);for(const check of [guard,guardImportRequest]){if(ok)check(req);else assert.throws(()=>check(req));}}
});

function withOrigin(value:string|undefined, run:()=>void) {
 const previous=process.env.ARSIA_LOCAL_HTTP_ORIGIN;
 if(value===undefined) delete process.env.ARSIA_LOCAL_HTTP_ORIGIN;
 else process.env.ARSIA_LOCAL_HTTP_ORIGIN=value;
 try { run(); } finally {
  if(previous===undefined) delete process.env.ARSIA_LOCAL_HTTP_ORIGIN;
  else process.env.ARSIA_LOCAL_HTTP_ORIGIN=previous;
 }
}

test('Explicit isolated loopback origin accepts only the configured server and matching browser origin',()=>{
 for(const origin of ['http://127.0.0.1:3117','http://localhost:4351','http://[::1]:4872']) withOrigin(origin,()=>{
  const host=new URL(origin).host;
  assert.equal(localRequest(new Request(origin+'/api/imports/jobs',{headers:{host,origin},method:'POST'})),true);
  assert.equal(localRequest(new Request(origin+'/api/imports/jobs',{headers:{host,'sec-fetch-site':'same-origin',referer:origin+'/imports'}})),true);
  assert.equal(localRequest(new Request('http://127.0.0.1:3100/api',{headers:{host:'127.0.0.1:3100',origin:'http://127.0.0.1:3100'}})),false);
  for(const patch of ([{origin:'http://evil.example'},{origin:'http://127.0.0.1:4999'},{'sec-fetch-site':'cross-site'},{host:'evil.example'}] as Record<string,string>[])) {
   assert.equal(localRequest(new Request(origin+'/api',{method:'POST',headers:{host,origin,...patch}})),false);
  }
 });
});

test('Invalid explicit server origin fails closed without widening default access',()=>{
 for(const origin of ['http://evil.example:3117','https://127.0.0.1:3117','http://0.0.0.0:3117','http://127.0.0.1:3117/','http://user@127.0.0.1:3117','http://127.1:3117','http://127.0.0.1:80','http://127.0.0.1:65536','']) withOrigin(origin,()=>{
  assert.equal(localRequest(new Request('http://127.0.0.1:3100/api',{headers:{host:'127.0.0.1:3100',origin:'http://127.0.0.1:3100'}})),false);
 });
});

// NextURL canonicalizes loopback URLs, independently of the actual HTTP Host.
test('Actual NextRequest normalization preserves exact configured Host and browser-origin enforcement',()=>{
 for(const origin of ['http://127.0.0.1:3117','http://localhost:4351','http://[::1]:4872']) withOrigin(origin,()=>{
  const host=new URL(origin).host;
  const req=new NextRequest(origin+'/api/imports/jobs',{headers:{host,origin},method:'POST'});
  assert.equal(new URL(req.url).hostname,'localhost');
  assert.equal(localRequest(req),true);
  assert.equal(localRequest(new NextRequest(origin+'/api/imports/jobs',{headers:{host,'sec-fetch-site':'same-origin',referer:origin+'/imports'}})),true);
  for(const patch of ([{host:'localhost:9999'},{host:'evil.example'},{origin:'http://localhost:9999'},{'sec-fetch-site':'cross-site'}] as Record<string,string>[]))
   assert.equal(localRequest(new NextRequest(origin+'/api',{method:'POST',headers:{host,origin,...patch}})),false);
  assert.equal(localRequest(new NextRequest('http://localhost:9999/api',{method:'POST',headers:{host,origin}})),false);
  if(host!=='localhost:'+new URL(origin).port)
   assert.equal(localRequest(new NextRequest(origin+'/api',{method:'POST',headers:{host:'localhost:'+new URL(origin).port,origin}})),false);
 });
});
