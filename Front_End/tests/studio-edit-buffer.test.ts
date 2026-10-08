import test from 'node:test';
import assert from 'node:assert/strict';
import {StudioEditBuffer,StudioFieldDrafts,acknowledgeStudioFields,requireStudioWritesSaved} from '../src/services/studio-edit-buffer';
const noop=async()=>{};
test('figure caption and legacy figure note have independent acknowledgements on the same block',()=>{
 const fields=new StudioFieldDrafts(),edits=new StudioEditBuffer();
 fields.set('one:block:figure:caption','Exported caption',noop);fields.set('one:block:figure:text','Preserved note',noop);
 const caption=edits.stage('one',{type:'block_edit',id:'figure',caption:'Exported caption'},fields);
 const note=edits.stage('one',{type:'block_edit',id:'figure',text:'Preserved note'},fields);
 assert.deepEqual(caption.fields.map(v=>v.key),['one:block:figure:caption']);
 edits.acknowledge(note);acknowledgeStudioFields(fields,note);
 assert.equal(fields.get('one:block:figure:caption'),'Exported caption');assert.equal(fields.get('one:block:figure:text'),undefined);
 fields.set('one:block:figure:caption','Newer caption',noop);edits.acknowledge(caption);acknowledgeStudioFields(fields,caption);
 assert.equal(fields.get('one:block:figure:caption'),'Newer caption');
 const latest=edits.stage('one',{type:'block_edit',id:'figure',caption:'Newer caption'},fields);edits.acknowledge(latest);acknowledgeStudioFields(fields,latest);assert.equal(fields.size,0);
});
test('document title edits own a separate field from study name and report details',()=>{
 const fields=new StudioFieldDrafts(),edits=new StudioEditBuffer();
 fields.set('one:reportTitle','Document title',noop);fields.set('one:title','Study name',noop);fields.set('one:reportMeta',JSON.stringify({author:'Writer'}),noop);
 const document=edits.stage('one',{type:'report_title',title:'Document title'},fields);
 const name=edits.stage('one',{type:'rename',title:'Study name'},fields);
 const details=edits.stage('one',{type:'report_meta',metadata:{author:'Writer'}},fields);
 edits.acknowledge(name);acknowledgeStudioFields(fields,name);edits.acknowledge(details);acknowledgeStudioFields(fields,details);
 assert.equal(fields.get('one:reportTitle'),'Document title');assert.equal(fields.size,1);assert.equal(edits.entries('one')[0].token,document.token);
 edits.acknowledge(document);acknowledgeStudioFields(fields,document);assert.equal(fields.size,0);assert.equal(edits.entries('one').length,0);
});
test('a failed or stale document title receipt preserves newer title drafts and other studies',()=>{
 const fields=new StudioFieldDrafts(),edits=new StudioEditBuffer();fields.set('one:reportTitle','A',noop);fields.set('two:reportTitle','Other',noop);
 const first=edits.stage('one',{type:'report_title',title:'A'},fields);edits.fail(first,'409');
 fields.set('one:reportTitle','B',noop);const second=edits.stage('one',{type:'report_title',title:'B'},fields);
 const currentToken=fields.set('one:reportTitle','A',noop);const final=edits.stage('one',{type:'report_title',title:'A'},fields);
 edits.acknowledge(first);acknowledgeStudioFields(fields,first);edits.acknowledge(second);acknowledgeStudioFields(fields,second);
 assert.equal(edits.entries('one').length,1);assert.equal(edits.entries('one')[0].token,final.token);assert.equal(fields.token('one:reportTitle'),currentToken);assert.equal(fields.get('two:reportTitle'),'Other');
 edits.acknowledge(final);acknowledgeStudioFields(fields,final);assert.equal(fields.get('one:reportTitle'),undefined);assert.equal(fields.get('two:reportTitle'),'Other');
});
test('report details use precise ownership without acknowledging or overwriting the title intention',()=>{
 const fields=new StudioFieldDrafts(),edits=new StudioEditBuffer();
 fields.set('one:reportTitle','Current document title',noop);
 const metadata={template:'brief',language:'en',author:'Writer',date:'2026-10-08'};
 fields.set('one:reportDetails',JSON.stringify(metadata),noop);
 const details=edits.stage('one',{type:'report_details',metadata},fields);
 assert.deepEqual(details.fields.map(v=>v.key),['one:reportDetails']);
 const newer={...metadata,author:'Updated writer'};
 fields.set('one:reportDetails',JSON.stringify(newer),noop);
 acknowledgeStudioFields(fields,details);
 assert.equal(fields.get('one:reportDetails'),JSON.stringify(newer));assert.equal(fields.get('one:reportTitle'),'Current document title');
 const current=edits.stage('one',{type:'report_details',metadata:newer},fields);
 assert.equal(edits.entries('one').length,1);acknowledgeStudioFields(fields,current);edits.acknowledge(current);
 assert.equal(fields.get('one:reportDetails'),undefined);assert.equal(fields.get('one:reportTitle'),'Current document title');
});
test('a successful layout edit cannot acknowledge failed text or caption on the same report block',()=>{
 const edits=new StudioEditBuffer(),fields=new StudioFieldDrafts();fields.set('research:block:p:text','Local text',noop);
 const text=edits.stage('research',{type:'block_edit',id:'p',text:'Local text'},fields);edits.fail(text,'storage failed');
 const size=edits.stage('research',{type:'block_edit',id:'p',size:'half'},fields);edits.acknowledge(size);acknowledgeStudioFields(fields,size);
 assert.deepEqual(edits.entries('research').map(v=>v.action),[{type:'block_edit',id:'p',text:'Local text'}]);assert.equal(fields.get('research:block:p:text'),'Local text');
 edits.acknowledge(text);acknowledgeStudioFields(fields,text);assert.equal(fields.size,0);
});
test('late success of an older field edit cannot clear the newer local value',()=>{
 const edits=new StudioEditBuffer(),fields=new StudioFieldDrafts();fields.set('research:block:p:text','First',noop);
 const old=edits.stage('research',{type:'block_edit',id:'p',text:'First'},fields);fields.set('research:block:p:text','Second',noop);
 const next=edits.stage('research',{type:'block_edit',id:'p',text:'Second'},fields);
 edits.acknowledge(old);acknowledgeStudioFields(fields,old);assert.equal(edits.entries('research')[0].token,next.token);assert.equal(fields.get('research:block:p:text'),'Second');
 edits.acknowledge(next);acknowledgeStudioFields(fields,next);assert.equal(edits.entries('research').length,0);assert.equal(fields.size,0);
});
test('ABA: old A receipt and queued B cannot acknowledge a newly entered A intention',()=>{
 const edits=new StudioEditBuffer(),fields=new StudioFieldDrafts(),key='research:block:p:text';fields.set(key,'A',noop);
 const a=edits.stage('research',{type:'block_edit',id:'p',text:'A'},fields);fields.set(key,'B',noop);
 const b=edits.stage('research',{type:'block_edit',id:'p',text:'B'},fields);const newToken=fields.set(key,'A',noop);
 edits.acknowledge(a);acknowledgeStudioFields(fields,a);assert.equal(fields.token(key),newToken);
 edits.acknowledge(b);acknowledgeStudioFields(fields,b);assert.equal(fields.get(key),'A');
 const final=edits.stage('research',{type:'block_edit',id:'p',text:'A'},fields);acknowledgeStudioFields(fields,final);assert.equal(fields.size,0);
});
test('independent structural intentions and different studies never overwrite pending edits',()=>{
 const edits=new StudioEditBuffer();for(let i=0;i<2;i++)edits.stage('one',{type:'block_add',kind:'text',text:'Two desired copies'});
 const one=edits.stage('one',{type:'rename',title:'First'}),two=edits.stage('two',{type:'rename',title:'Second'});
 edits.acknowledge(two);assert.equal(edits.entries('one').length,3);assert.equal(edits.entries('two').length,0);edits.fail(one,'conflict');edits.clear('two');assert.equal(edits.entries('one').length,3);
});
test('failed local fields retain their intention until precise acknowledgement, including same text re-entered',async()=>{
 const fields=new StudioFieldDrafts();let calls=0;const old=fields.set('study:context','Same',async()=>{calls++;throw Error('Save required');});
 await assert.rejects(fields.flush(),/Save required/);assert.equal(calls,1);const fresh=fields.set('study:context','Same',noop);
 fields.acknowledge('study:context',old);assert.equal(fields.token('study:context'),fresh);fields.acknowledge('study:context',fresh);assert.equal(fields.size,0);
});
test('discarding a failed form removes its pending delta but preserves independent field and study edits',()=>{
 const fields=new StudioFieldDrafts(),edits=new StudioEditBuffer();fields.set('one:context','{"notes":"New"}',noop);fields.set('one:reportMeta','{"author":"New"}',noop);
 const c=edits.stage('one',{type:'context',context:{notes:'New'}},fields);edits.fail(c,'409');edits.stage('one',{type:'report_meta',metadata:{author:'New'}},fields);edits.stage('two',{type:'context',context:{notes:'Other'}});
 edits.discardField('one','one:context');fields.discard('one:context');assert.deepEqual(edits.entries('one').map(v=>v.action.type),['report_meta']);assert.equal(edits.entries('two').length,1);assert.equal(fields.size,1);
});
test('context and metadata acknowledgements do not discard edits made while save was in flight',()=>{
 const fields=new StudioFieldDrafts(),edits=new StudioEditBuffer();fields.set('one:context',JSON.stringify({notes:'First'}),noop);fields.set('one:reportMeta',JSON.stringify({author:'A'}),noop);
 const context=edits.stage('one',{type:'context',context:{notes:'First'}},fields),meta=edits.stage('one',{type:'report_meta',metadata:{author:'A'}},fields);
 fields.set('one:context',JSON.stringify({notes:'Second'}),noop);acknowledgeStudioFields(fields,context);acknowledgeStudioFields(fields,meta);
 assert.equal(fields.get('one:context'),JSON.stringify({notes:'Second'}));assert.equal(fields.get('one:reportMeta'),undefined);
});
test('pending records own snapshots, and review inspection does not acknowledge or rewrite anything',()=>{
 const edits=new StudioEditBuffer(),action={type:'context',context:{notes:'Own'}};const record=edits.stage('a',action);action.context.notes='Changed caller';const review=edits.entries('a');
 (review[0].action.context as {notes:string}).notes='Changed viewer';assert.equal((edits.entries('a')[0].action.context as {notes:string}).notes,'Own');edits.fail(record,'409');assert.equal(edits.entries('a')[0].error,'409');assert.equal(edits.owns(record),true);
});

test('discarded failed writes do not poison later flush, while unresolved or newly queued edits still block it',async()=>{
 const edits=new StudioEditBuffer(),fields=new StudioFieldDrafts();fields.set('one:context','{"notes":"Local"}',noop);
 const edit=edits.stage('one',{type:'context',context:{notes:'Local'}},fields);edits.fail(edit,'409');
 const tail=Promise.reject(Error('Historical 409'));void tail.catch(()=>{});
 const unresolved=()=>!!edits.entries('one').length||!!fields.size;
 await assert.rejects(requireStudioWritesSaved(tail,unresolved),/Resolve unsaved/);
 edits.discardField('one','one:context');fields.discard('one:context');await requireStudioWritesSaved(tail,unresolved);
 edits.stage('one',{type:'rename',title:'A new intention'});await assert.rejects(requireStudioWritesSaved(tail,unresolved),/Resolve unsaved/);
 assert.equal(edits.entries('one').length,1);
});
