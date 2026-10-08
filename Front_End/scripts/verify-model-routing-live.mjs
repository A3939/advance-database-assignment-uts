/** Two small read-only real-provider checks. No imports, publication or saved study. */
import {mkdir, writeFile, readdir, readFile} from 'node:fs/promises';
import {join, resolve} from 'node:path';
const root=resolve('artifacts/model-routing');
const before=new Set(await readdir(root).catch(()=>[]));
const output=resolve('artifacts/autonomous-imports/model-routing-live/'+new Date().toISOString().replace(/[:.]/g,'-'));
await mkdir(output,{recursive:true,mode:0o700});
const context={page:'/',filters:{source:'NSW',dateRange:{from:'2020-01-01',to:'2024-12-31'},datasetVersion:'official-v1',batchId:'bcc5da57-25f2-41ec-9925-bef421b02671'}};
const cases=[{name:'simple',message:'How many crashes are in the selected period?',expected:'gpt-5.6-terra'},
{name:'reasoning',message:'Compare NSW crash counts for 2024 and 2023. State the exact change and keep the two periods explicit.',expected:'gpt-6.1-sol'}];
const results=[];
for(const item of cases){
  const events=[];let status;
  try{
    const response=await fetch('http://127.0.0.1:3100/api/agent',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({context,message:item.message,history:[]}),signal:AbortSignal.timeout(270000)});
    status=response.status;
    if(!response.ok)throw Error('HTTP '+status);
    let buffer='';const decoder=new TextDecoder();
    for await(const chunk of response.body){buffer+=decoder.decode(chunk,{stream:true});let end;while((end=buffer.indexOf('\n'))>=0){events.push(JSON.parse(buffer.slice(0,end)));buffer=buffer.slice(end+1);}}
    if(buffer.trim())events.push(JSON.parse(buffer));
  }catch(error){events.push({type:'verification_error',message:error.name==='TimeoutError'?'timeout':String(error.message).slice(0,200)});}
  const done=events.find(e=>e.type==='done');
  const evidence=events.filter(e=>e.type==='evidence');
  const passed=status===200&&done?.model===item.expected&&evidence.length>0&&!events.some(e=>['error','verification_error'].includes(e.type));
  await writeFile(join(output,item.name+'.json'),JSON.stringify({item,context,events,passed},null,2),{flag:'wx',mode:0o600});
  results.push({case:item.name,expected:item.expected,actual:done?.model??null,passed,evidence_count:evidence.length,errors:events.filter(e=>['error','verification_error'].includes(e.type))});
  console.log(JSON.stringify(results.at(-1)));
}
const receipts=[];
for(const name of await readdir(root).catch(()=>[]))if(!before.has(name)&&name.endsWith('.jsonl')) receipts.push({file:name,events:(await readFile(join(root,name),'utf8')).trim().split('\n').map(JSON.parse)});
await writeFile(join(output,'report.json'),JSON.stringify({results,receipts,passed:results.every(r=>r.passed)},null,2),{flag:'wx',mode:0o600});
console.log(JSON.stringify({output,passed:results.every(r=>r.passed)}));
if(results.some(r=>!r.passed))process.exitCode=1;
