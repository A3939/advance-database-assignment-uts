/** Explicit, small live integration check. No key access or provider logging here. */
import {writeFile, mkdir} from 'node:fs/promises';
const context={page:'/',filters:{source:'NSW',dateRange:{from:'2020-01-01',to:'2024-12-31'},datasetVersion:'official-v1',batchId:'bcc5da57-25f2-41ec-9925-bef421b02671'}};
const message='请查询 NSW 2020–2024 每年事故数，展示折线图。然后用 Python 计算 2024 对 2023 的差值与同比，生成 CSV 和简短 Markdown 报告，保留批次与口径，提供代码下载。';
const response=await fetch('http://127.0.0.1:3103/api/agent',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({context,message,history:[]})});
if(!response.ok) throw Error(`HTTP ${response.status}`);
let buffer='',events=[];for await(const chunk of response.body){buffer+=new TextDecoder().decode(chunk);let line;while((line=buffer.indexOf('\n'))>=0){const e=JSON.parse(buffer.slice(0,line));buffer=buffer.slice(line+1);events.push(e);if(e.type==='progress'||e.type==='error'||e.type==='done')console.log(e);}}
await mkdir('artifacts/analysis-verification',{recursive:true});
await writeFile('artifacts/analysis-verification/live-events.json',JSON.stringify({context,message,events},null,2));
console.log(JSON.stringify({tools:events.filter(e=>e.type==='tool_result').map(e=>({name:e.name,status:e.data.status})),files:events.filter(e=>e.type==='artifact').map(e=>e.artifact.name),reply:events.filter(e=>e.type==='message').map(e=>e.text).join('')}));
if(events.some(e=>e.type==='error')||!events.some(e=>e.type==='done'))process.exitCode=1;
