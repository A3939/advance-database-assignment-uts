/** Explicit, short-lived acceptance capability. No HTTP port or normal runtime. */
import {createServer} from 'node:http';
import {readFileSync,lstatSync,chmodSync,mkdirSync,realpathSync,existsSync,writeFileSync} from 'node:fs';
import {join,dirname,resolve} from 'node:path';
import {once} from 'node:events';
import {codexGateway} from '../src/server/imports/codex-gateway';
const [runtimePath,parentValue]=process.argv.slice(2);
if(!runtimePath || resolve(runtimePath)!==runtimePath || lstatSync(runtimePath).isSymbolicLink() || lstatSync(runtimePath).mode & 0o077) throw Error('Private absolute managed runtime required');
const cfg=JSON.parse(readFileSync(runtimePath,'utf8')),gateway=cfg.private_model_gateway;
const parent=Number(parentValue),session=cfg.test_session_id;
if(!Number.isInteger(parent) || process.ppid!==parent || !/^[a-f0-9]{32}$/.test(session) || cfg.mode!=='local-test' || !cfg.storage_policy?.enabled ||
  gateway?.protocol!=='owned-model-gateway-v1' || gateway.instance_id!==cfg.instance_id || gateway.test_session_id!==session || dirname(runtimePath)!==cfg.data_root)
  throw Error('Owned model gateway identity mismatch');
const owner=JSON.parse(readFileSync(join(cfg.data_root,'.storage-owner.json'),'utf8'));
const receipt=JSON.parse(readFileSync(join(cfg.storage_home,'session.json'),'utf8'));
for(const key of ['instance_id','test_session_id','purpose']) if(!cfg[key] || cfg[key]!==owner[key] || cfg[key]!==receipt[key]) throw Error('Managed session marker mismatch');
if(owner.version!==cfg.storage_policy.version || receipt.version!==owner.version)throw Error('Managed session version mismatch');
const directory=join(realpathSync('/tmp'),'arsia-model-'+session.slice(0,12)),socket=join(directory,'gateway.sock');
if(gateway.socket_path!==socket || existsSync(directory)) throw Error('Owned socket directory must be new');
if(!process.env.OPENAI_API_KEY?.trim()) throw Error('Model credential is unavailable');
mkdirSync(directory,{mode:0o700});
const active=new Set<AbortController>();
const server=createServer(async(incoming,outgoing)=>{
  const abort=new AbortController();active.add(abort);
  outgoing.on('close',()=>{if(!outgoing.writableFinished)abort.abort();});
  try {
    if(incoming.method!=='POST' || incoming.url!=='/api/imports/codex-model') {outgoing.writeHead(404);outgoing.end();return;}
    const chunks:Buffer[]=[];let size=0;
    for await(const data of incoming) {size+=data.length;if(size>4*1024*1024)throw Error('Request byte limit');chunks.push(data);}
    const headers=new Headers();for(const [key,value] of Object.entries(incoming.headers)) if(typeof value==='string')headers.set(key,value);
    const request=new Request('http://127.0.0.1:3100'+incoming.url,{method:'POST',headers,body:Buffer.concat(chunks),signal:abort.signal});
    const response=await codexGateway(request,{runtimeConfig:async()=>({mode:cfg.mode,agent_gateway_token:cfg.agent_gateway_token}),auditRoot:join(cfg.data_root,'model-usage')});
    outgoing.writeHead(response.status,Object.fromEntries(response.headers));
    if(response.body) {
      const reader=response.body.getReader();let ended=false;
      try {while(true) {const {value,done}=await reader.read();if(done){ended=true;break;}if(!outgoing.write(value))await once(outgoing,'drain',{signal:abort.signal});}}
      finally {if(!ended)await reader.cancel().catch(()=>{});reader.releaseLock();}
    }
    outgoing.end();
  } catch {if(!outgoing.headersSent)outgoing.writeHead(503);outgoing.end();}
  finally {active.delete(abort);}
});
let stopping=false;
function stop(){if(stopping)return;stopping=true;for(const abort of active)abort.abort();server.close(()=>process.exit(0));setTimeout(()=>process.exit(1),2000).unref();}
process.on('SIGTERM',stop);process.on('SIGINT',stop);
// Lifetime guard only for this explicitly running experiment, not an automation.
setInterval(()=>{if(process.ppid!==parent)stop();},500).unref();
setTimeout(stop,7260000).unref(); // Existing 7200s task ceiling plus bounded shutdown.
server.listen(socket,()=>{chmodSync(socket,0o600);writeFileSync(join(cfg.data_root,'model-gateway-ready.json'),JSON.stringify({protocol:gateway.protocol,instance_id:cfg.instance_id,test_session_id:session,pid:process.pid,owner_pid:parent,socket_path:socket,model:'gpt-6.1-sol',reasoning:'high',normal_runtime_access:false}),{flag:'wx',mode:0o600});});
