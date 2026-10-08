import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { resourceUsage } from '../src/server/analysis/resource-usage';
import { saveSandboxReceipt, ownershipLabels, type SandboxReceipt } from '../src/server/analysis/sandbox-ownership';

async function fixture() {
  const root=await mkdtemp(join(tmpdir(),'arsia-resource-view-'));
  const analysisRoot=join(root,'analysis'),runtimePath=join(root,'runtime.json');
  await mkdir(analysisRoot);
  await writeFile(runtimePath,JSON.stringify({mode:'local-test',instance_id:'a'.repeat(32),dsn:'secret-must-not-leak'}),{mode:0o600});
  const token=randomUUID();
  const receipt:SandboxReceipt={version:1,token,name:'arsia-analysis-'+token,directory:join(analysisRoot,'inputs',token),
    image:'sha256:'+'1'.repeat(64),containerId:'2'.repeat(64),ownerPid:process.pid,createdAt:new Date().toISOString(),state:'running'};
  await saveSandboxReceipt(join(analysisRoot,token+'.json'),receipt);
  const container={Id:receipt.containerId,Name:'/'+receipt.name,Image:receipt.image,Config:{Labels:ownershipLabels(receipt)},
    Mounts:[{Source:receipt.directory,Destination:'/data',RW:false}],State:{Running:true}};
  return {root,analysisRoot,runtimePath,receipt,container};
}
test('resource view observes only exact receipts and the configured Imports label without writes',async()=>{
  const f=await fixture(),calls:string[][]=[];
  const result=await resourceUsage({...f,docker:async args=>{
    calls.push(args);
    if(args[0]==='inspect'){assert.deepEqual(args,['inspect',f.receipt.name]);return {stdout:JSON.stringify([f.container])};}
    assert.deepEqual(args,['ps','--all','--no-trunc','--filter','label=arsia.import.instance='+'a'.repeat(32),'--format','{{json .}}']);
    return {stdout:JSON.stringify({ID:'3'.repeat(64),Names:'arsia-adapter-'+'4'.repeat(32),State:'exited'})+'\n'};
  }});
  assert.equal(result.analysis.active,1);assert.equal(result.imports.active,0);assert.equal(result.imports.stopped,1);
  assert.equal(calls.length,2);assert.equal(JSON.stringify(result).includes('secret-must-not-leak'),false);
});
test('Docker failure preserves unknown active counts and a known cleanup failure',async()=>{
  const f=await fixture();f.receipt.state='cleanup_failed';await saveSandboxReceipt(join(f.analysisRoot,f.receipt.token+'.json'),f.receipt);
  const result=await resourceUsage({...f,docker:async()=>{throw Error('private daemon detail');}});
  assert.equal(result.analysis.active,null);assert.equal(result.analysis.cleanupPending,1);assert.equal(result.imports.active,null);
  assert.equal(JSON.stringify(result).includes('private daemon detail'),false);
});
test('mismatched container ownership never produces a trusted active count',async()=>{
  const f=await fixture();f.container.Config.Labels['arsia.analysis.owner']='different-owner';
  const result=await resourceUsage({...f,docker:async args=>({stdout:args[0]==='inspect'?JSON.stringify([f.container]):''})});
  assert.equal(result.analysis.status,'unavailable');assert.equal(result.analysis.active,null);
});
test('missing workspace configuration does not invoke Docker or create state',async()=>{
  const root=await mkdtemp(join(tmpdir(),'arsia-resource-empty-'));
  const result=await resourceUsage({analysisRoot:join(root,'analysis'),runtimePath:join(root,'runtime.json'),docker:async()=>{throw assert.fail('Unexpected Docker call');}});
  assert.equal(result.analysis.status,'unconfigured');assert.equal(result.imports.status,'unconfigured');
});
test('indirect runtime cannot select another Imports instance',async()=>{
  const f=await fixture();const link=join(f.root,'link.json');await symlink(f.runtimePath,link);
  f.receipt.state='cleaned';await saveSandboxReceipt(join(f.analysisRoot,f.receipt.token+'.json'),f.receipt);
  const result=await resourceUsage({...f,runtimePath:link,docker:async()=>{throw assert.fail('Unexpected Docker call');}});
  assert.equal(result.imports.status,'unavailable');assert.equal(result.analysis.active,0);
});
