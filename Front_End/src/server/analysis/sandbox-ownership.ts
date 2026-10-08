/** Explicit, receipt-scoped recovery. Never searches or prunes Docker resources. */
import { mkdir, readFile, writeFile, rename, lstat, rm } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { randomUUID } from 'node:crypto';
export type DockerCall = (args:string[])=>Promise<{stdout:string}>;
export interface SandboxReceipt {
  version:1; token:string; name:string; image:string; directory:string;
  containerId?:string; ownerPid:number; createdAt:string; state:'prepared'|'running'|'cleaned'|'cleanup_failed';
  cleanupError?:string;
}
export const sandboxRoot=()=>resolve(process.env.ARSIA_ANALYSIS_ROOT || join(process.cwd(),'artifacts/analysis-runs'));
export async function saveSandboxReceipt(path:string, value:SandboxReceipt) {
  await mkdir(dirname(path),{recursive:true,mode:0o700});
  const temporary=path+'.'+randomUUID()+'.tmp';
  await writeFile(temporary,JSON.stringify(value)+'\n',{mode:0o600,flag:'wx'});
  await rename(temporary,path);
}
export function ownershipLabels(receipt:SandboxReceipt) {
  return {'arsia.analysis.owner':receipt.token,'arsia.analysis.name':receipt.name,'arsia.analysis.pid':String(receipt.ownerPid)};
}
function absent(error:unknown,name:string) {
  const stderr=String((error as {stderr?:string}).stderr||'').trim();
  // Unknown daemon/transport errors are never treated as an absent container.
  return stderr===`Error response from daemon: No such container: ${name}` || stderr===`Error: No such object: ${name}`;
}
export async function cleanSandbox(receipt:SandboxReceipt,docker:DockerCall) {
  let container;
  try {container=JSON.parse((await docker(['inspect',receipt.name])).stdout)[0];}
  catch(error){if(!absent(error,receipt.name))throw Error('Sandbox ownership inspection failed; cleanup needs explicit recovery.');}
  if(container) {
    const labels=container.Config?.Labels || {};
    if((receipt.containerId && container.Id!==receipt.containerId) || container.Name!=='/'+receipt.name || container.Image!==receipt.image || Object.entries(ownershipLabels(receipt)).some(([k,v])=>labels[k]!==v) || !container.Mounts?.some((m:{Source:string;Destination:string;RW:boolean})=>m.Source===receipt.directory&&m.Destination==='/data'&&!m.RW))
      throw Error('Sandbox ownership mismatch; no resources were removed.');
    await docker(['rm','-f',receipt.name]);
  }
  await rm(receipt.directory,{recursive:true,force:true});
}
export async function recoverSandbox(path:string,docker:DockerCall,root=sandboxRoot()) {
  const target=resolve(path);
  if(dirname(target)!==resolve(root) || (await lstat(target)).isSymbolicLink())throw Error('Recovery requires an exact local receipt.');
  const receipt=JSON.parse(await readFile(target,'utf8')) as SandboxReceipt;
  if(receipt.version!==1 || !/^[a-f0-9-]{36}$/.test(receipt.token) || receipt.name!==`arsia-analysis-${receipt.token}` || !/^sha256:[a-f0-9]{64}$/.test(receipt.image) || !Number.isSafeInteger(receipt.ownerPid) || receipt.ownerPid<1 || dirname(resolve(receipt.directory))!==join(resolve(root),'inputs') || !resolve(receipt.directory).endsWith('/'+receipt.token))throw Error('Invalid sandbox recovery receipt.');
  if(receipt.state==='cleaned')return 'cleaned';
  let alive=true;try{process.kill(receipt.ownerPid,0);}catch(error){alive=(error as NodeJS.ErrnoException).code!=='ESRCH';}
  if(alive)return 'owner_active';
  try{await cleanSandbox(receipt,docker);receipt.state='cleaned';delete receipt.cleanupError;}
  catch{receipt.state='cleanup_failed';receipt.cleanupError='Ownership, Docker availability or cleanup could not be verified.';await saveSandboxReceipt(target,receipt);throw Error(receipt.cleanupError);}
  await saveSandboxReceipt(target,receipt);return 'cleaned';
}
