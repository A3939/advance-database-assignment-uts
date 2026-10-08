// Explicit real-Docker acceptance. Requires a task-owned root and image override.
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn, execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { mkdir, readdir, readFile, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { recoverSandbox, type SandboxReceipt } from '../src/server/analysis/sandbox-ownership';
const exec=promisify(execFile);
const root=process.env.ARSIA_ANALYSIS_ROOT;
if(!root || !process.env.ARSIA_ANALYSIS_IMAGE)throw Error('An explicit task-owned sandbox root and image are required.');
const docker=(args:string[])=>exec('docker',args,{encoding:'utf8',timeout:10000});
const pause=()=>new Promise(r=>setTimeout(r,200));
test('parent SIGKILL leaves a wall-bounded owned container; exact receipt recovery is repeatable', {timeout:60000}, async()=>{
 await mkdir(root!,{recursive:true});
 const existing=new Set(await readdir(root!));
 const child=spawn(process.execPath,['--require','tsx/cjs','-e',"require('./src/server/analysis/sandbox.ts').runPython('import time; time.sleep(300)',{},new AbortController().signal).then(()=>process.exit(0)).catch(()=>process.exit(1))"],{cwd:process.cwd(),env:process.env,stdio:['ignore','pipe','pipe']});
 let receipt:SandboxReceipt|undefined,path='';
 try {
  const start=Date.now();
  while(Date.now()-start<15000){
   const names=(await readdir(root!)).filter(n=>n.endsWith('.json')&&!existing.has(n));
   if(names.length){path=join(root!,names[0]);receipt=JSON.parse(await readFile(path,'utf8'));if(receipt?.containerId){const v=JSON.parse((await docker(['inspect',receipt.name])).stdout)[0];if(v.State.Running)break;}}
   await pause();
  }
  assert.ok(receipt?.containerId,'owned container started');
  const before=Date.now();child.kill('SIGKILL');await new Promise(r=>child.once('exit',r));
  let state;
  while(Date.now()-before<40000){state=JSON.parse((await docker(['inspect',receipt!.name])).stdout)[0].State;if(!state.Running)break;await pause();}
  assert.equal(state.Running,false,'independent container wall time ends a low-CPU sleep after parent death');
  assert.equal(state.ExitCode,137);
  await assert.rejects(recoverSandbox(path,async()=>{throw Error('daemon unavailable');},root),/could not be verified/);
  assert.equal(JSON.parse(await readFile(path,'utf8')).state,'cleanup_failed');
  assert.equal(await recoverSandbox(path,docker,root),'cleaned');
  assert.equal(await recoverSandbox(path,docker,root),'cleaned');
  await writeFile(join(root!,'parent-death-verification.json'),JSON.stringify({ownerPid:child.pid,container:receipt!.name,image:receipt!.image,containerExitCode:state.ExitCode,elapsedAfterParentDeathMs:Date.now()-before,recovery:'cleaned',unavailableDaemon:'visible_and_retryable'},null,2));
 }finally{
  if(child.exitCode===null && child.signalCode===null)child.kill('SIGKILL');
  if(path){try{await recoverSandbox(path,docker,root);}catch{/* Preserve failed receipt for scoped recovery. */}}
 }
});
