/** On-demand read-only observation. Never starts, recovers or removes resources. */
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { lstat, opendir, readFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { sandboxRoot, ownershipLabels, type DockerCall, type SandboxReceipt } from './sandbox-ownership';
const exec=promisify(execFile);
const docker: DockerCall=args=>exec('docker',args,{timeout:5000,maxBuffer:2*1024*1024,encoding:'utf8'});
const uuid=/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
type View={status:'observed'|'unconfigured'|'unavailable'|'partial';active:number|null;stopped:number|null;cleanupPending:number|null;note:string};
async function regularJson(path:string,privateFile=false) {
  const stat=await lstat(path);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size>16384 || privateFile && stat.mode&0o077) throw Error('Invalid local resource receipt');
  return JSON.parse(await readFile(path,'utf8'));
}
const unavailable=(note:string):View=>({status:'unavailable',active:null,stopped:null,cleanupPending:null,note});
async function analysisView(root:string,call:DockerCall):Promise<View> {
  const pending:SandboxReceipt[]=[];let scanned=0,cleanupPending=0;
  try {
    const stat=await lstat(root);if(!stat.isDirectory()||stat.isSymbolicLink())throw Error('Invalid receipt root');
    for await (const entry of await opendir(root)) {
      if(!entry.name.endsWith('.json')||!uuid.test(entry.name.slice(0,-5)))continue;
      if(++scanned>2000)return {status:'partial',active:null,stopped:null,cleanupPending:null,note:'Receipt scan reached its 2,000 item bound; totals are unknown.'};
      const receipt=await regularJson(join(root,entry.name),true) as SandboxReceipt;
      if(receipt.version!==1||receipt.token!==entry.name.slice(0,-5)||receipt.name!=='arsia-analysis-'+receipt.token ||
          !/^sha256:[a-f0-9]{64}$/.test(receipt.image)||!Number.isSafeInteger(receipt.ownerPid)||receipt.ownerPid<1 ||
          resolve(receipt.directory)!==join(resolve(root),'inputs',receipt.token) ||
          !['prepared','running','cleaned','cleanup_failed'].includes(receipt.state))throw Error('Invalid receipt');
      if(receipt.state==='cleaned')continue;
      if(receipt.state==='cleanup_failed')cleanupPending++;
      pending.push(receipt);
      if(pending.length>64)return {status:'partial',active:null,stopped:null,cleanupPending:null,note:'Pending receipt scan reached its 64 item bound; totals are unknown.'};
    }
  } catch(error) {
    if((error as NodeJS.ErrnoException).code==='ENOENT'&&scanned===0)return {status:'unconfigured',active:0,stopped:0,cleanupPending:0,note:'No analysis ownership receipts in this workspace.'};
    return unavailable('Analysis ownership receipts are unavailable or invalid.');
  }
  if(!pending.length)return {status:'observed',active:0,stopped:0,cleanupPending:0,note:'No pending analysis ownership receipts.'};
  try {
    const containers=JSON.parse((await call(['inspect',...pending.map(r=>r.name)])).stdout);
    if(!Array.isArray(containers)||containers.length!==pending.length)throw Error('Incomplete observation');
    let active=0;
    for(const receipt of pending){
      const item=containers.find(c=>c.Name==='/'+receipt.name);
      if(!item||item.Image!==receipt.image||receipt.containerId&&item.Id!==receipt.containerId||
          Object.entries(ownershipLabels(receipt)).some(([key,value])=>item.Config?.Labels?.[key]!==value)||
          !item.Mounts?.some((m:{Source:string;Destination:string;RW:boolean})=>m.Source===receipt.directory&&m.Destination==='/data'&&!m.RW)||
          typeof item.State?.Running!=='boolean')throw Error('Ownership observation mismatch');
      if(item.State.Running)active++;
    }
    return {status:'observed',active,stopped:pending.length-active,cleanupPending,note:'Current receipt-matched containers; explicit recovery is required for unfinished cleanup.'};
  } catch{return {...unavailable('Docker observation or exact ownership verification failed; active container count is unknown.'),cleanupPending};}
}
async function importsView(runtimePath:string,call:DockerCall):Promise<View> {
  let instance:string;
  try {
    const cfg=await regularJson(runtimePath,true);
    if(cfg.mode!=='local-test'||!/^[a-f0-9]{32}$/.test(cfg.instance_id))throw Error('Invalid instance');
    instance=cfg.instance_id;
  } catch(error){
    if((error as NodeJS.ErrnoException).code==='ENOENT')return {status:'unconfigured',active:null,stopped:null,cleanupPending:null,note:'No Imports runtime is configured in this workspace.'};
    return unavailable('The private Imports runtime identity is unavailable.');
  }
  try {
    const raw=(await call(['ps','--all','--no-trunc','--filter','label=arsia.import.instance='+instance,'--format','{{json .}}'])).stdout;
    const rows=raw.trim()?raw.trim().split('\n').map(line=>JSON.parse(line)):[];
    if(rows.length>64)return {status:'partial',active:null,stopped:null,cleanupPending:null,note:'Imports observation reached its 64 container bound.'};
    if(rows.some(r=>!/^[a-f0-9]{64}$/.test(r.ID)||!/^arsia-adapter-[a-f0-9]{32}$/.test(r.Names)||!['running','created','exited','dead','paused','restarting','removing'].includes(r.State)))throw Error('Invalid Docker observation');
    const active=rows.filter(r=>['running','paused','restarting'].includes(r.State)).length;
    return {status:'observed',active,stopped:rows.length-active,cleanupPending:null,note:'Containers labelled for this Imports instance. Stopped containers may need worker-owned cleanup; this view does not grant recovery authority.'};
  }catch{return unavailable('Docker is unavailable or returned an invalid Imports observation.');}
}
export async function resourceUsage(options:{analysisRoot?:string;runtimePath?:string;docker?:DockerCall}={}) {
  const call=options.docker||docker;
  const [analysis,imports]=await Promise.all([
    analysisView(options.analysisRoot||sandboxRoot(),call),
    importsView(options.runtimePath||join(process.cwd(),'artifacts/imports-local/runtime.json'),call),
  ]);
  return {observedAt:new Date().toISOString(),analysis,imports,
    limits:{analysis:{memoryMiB:512,cpus:1,hostWallSeconds:30,independentWallSeconds:35},importsWorkerConcurrency:1},
    note:'On-demand observations are separate from model request leases. No container-wide concurrency budget is configured; each executor enforces its own resource and wall-time limits.'};
}
