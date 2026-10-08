import test, { type TestContext } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { DatabaseSync } from 'node:sqlite';
import { StudioStore, uuid } from '../src/server/studio/store';
import { DEFAULT_FILTERS } from '../src/services/config';
import { createStudy } from '../src/server/studio/create';
import { exportStudy } from '../src/server/studio/export';
const ctx = {filters: DEFAULT_FILTERS, metric: 'crashes' as const, notes:'',references:''};
function fixture(t: TestContext) {
  const root = mkdtempSync(join(tmpdir(), 'arsia-studio-boundary-'));
  const path = join(root, 'test.sqlite');
  const store = new StudioStore(path);
  t.after(() => { try { store.close(); } catch {} rmSync(root, {recursive:true,force:true}); });
  return {store,path,root};
}
test('quota counts UTF-8 bytes, replacement net growth, and leaves export available at capacity', t => {
  const {store} = fixture(t);
  let s = store.create('中文 🚗', ctx, 'é');
  const bytes = Buffer.byteLength(JSON.stringify(s));
  assert.equal(store.capacity().usedBytes, bytes);
  const cap = store.capacity().limitBytes;
  store.db.prepare('INSERT INTO files VALUES(?,?,zeroblob(?))').run(uuid(), s.id, cap-bytes-128);
  // Revision and timestamp remain the same encoded width; this replaces, not appends, the document.
  s = store.action(s.id,{type:'rename',title:'车辆 🚗',revision:s.revision});
  assert.equal(store.capacity().usedBytes,cap-128);
  assert.throws(() => store.action(s.id,{type:'draft',text:'车'.repeat(100),revision:s.revision}), /storage limit/);
  assert.equal(store.get(s.id).draft,'é');
  assert.ok(exportStudy(store,store.get(s.id)).byteLength>0);
  assert.equal(store.capacity().usedBytes,cap-128);
});
test('the 64th incomplete run can retry in place, but a 65th run is rejected', t => {
  const {store} = fixture(t); const s=store.create('Retry',ctx); let last='';
  for(let i=0;i<64;i++) { const {run}=store.beginRun(s.id,uuid(),'Question'); run.status='failed'; store.updateRun(s.id,run); last=run.id; }
  assert.throws(()=>store.beginRun(s.id,uuid(),'65'),/64 analyses/);
  const key=uuid(); const retry=store.beginRun(s.id,key,'Retry',false,last);
  assert.equal(retry.run.attempt,2); assert.equal(retry.study.runs.length,64);
  assert.equal(store.beginRun(s.id,key,'Retry',false,last).replay,true);
});
test('restore at 49 versions preserves pre-restore state in slot 50 without a redundant snapshot', t=> {
  const {store}=fixture(t);let s=store.create('Restore',ctx,'original');
  for(let i=0;i<49;i++) s=store.action(s.id,{type:'snapshot',label:`V${i}`,revision:s.revision});
  const target=store.versions(s.id)[0];
  s=store.action(s.id,{type:'draft',text:'before restore',revision:s.revision});
  s=store.action(s.id,{type:'restore',versionId:target.id,revision:s.revision});
  assert.equal(s.draft,'original');assert.equal(store.versions(s.id).length,50);
  assert.ok(store.versions(s.id).some(v=>store.version(s.id,v.id).draft==='before restore'));
  assert.throws(()=>store.action(s.id,{type:'restore',versionId:target.id,revision:s.revision}),/50-version/);
  assert.ok(exportStudy(store,s).length>0);
});
test('transfer reservation survives process death before collection and never creates a duplicate', async t=> {
  const {store,path}=fixture(t); const id=uuid();
  store.saveTransfer({id,context:{page:'/',filters:ctx.filters},question:'Persist this response',createdAt:new Date().toISOString(),events:[]});
  const script = `const {StudioStore}=require('./src/server/studio/store.ts');const s=new StudioStore(process.argv[1]);const c=s.claimTransfer(process.argv[2]);console.log(c.study.id);process.exit(0);`;
  const studyId=execFileSync(process.execPath,['--require','tsx/cjs','-e',script,path,id],{encoding:'utf8',stdio:['ignore','pipe','pipe']}).trim();
  const result=await createStudy(store,{transferId:id});assert.equal(result.id,studyId);
  assert.equal(store.list().length,1);assert.equal(result.runs.length,0);assert.equal(result.draft,'Persist this response');
  store.db.prepare('UPDATE transfers SET created=0 WHERE id=?').run(id);
  assert.equal((await createStudy(store,{transferId:id})).id,studyId);
});
test('legacy reads do not migrate; explicit migration backs up and preserves documents across restart', t=> {
  const {store,path,root}=fixture(t);const s=store.create('Legacy 中文',ctx);
  store.db.exec('PRAGMA user_version=0');store.close();
  const raw=new DatabaseSync(path);raw.prepare('UPDATE studies SET doc=? WHERE id=?').run(JSON.stringify({...s,schemaVersion:undefined}),s.id);raw.close();
  const old=new StudioStore(path);t.after(()=>old.close());
  assert.equal(old.get(s.id).title,s.title);assert.equal(old.capacity().migrationRequired,true);
  assert.throws(()=>old.create('No implicit migration',ctx),/upgrade required/);
  const backup=join(root,'pre-migration.sqlite');old.migrateAfterBackup(backup);
  assert.equal(old.capacity().schemaVersion,1);assert.equal(old.get(s.id).schemaVersion,1);
  const copy=new DatabaseSync(backup,{readOnly:true});assert.equal((copy.prepare('PRAGMA user_version').get() as {user_version:number}).user_version,0);copy.close();
  old.action(s.id,{type:'draft',text:'after migration',revision:s.revision});
  const reopened=new StudioStore(path);assert.equal(reopened.get(s.id).draft,'after migration');reopened.close();
});
test('unknown document versions refuse migration with atomic rollback and a retained backup', t=> {
  const {store,path,root}=fixture(t);const s=store.create('Future',ctx);
  store.db.prepare('UPDATE studies SET doc=? WHERE id=?').run(JSON.stringify({...s,schemaVersion:999}),s.id);store.db.exec('PRAGMA user_version=0');store.close();
  const old=new StudioStore(path);t.after(()=>old.close());
  assert.throws(()=>old.migrateAfterBackup(join(root,'backup.sqlite')),/newer Studio version/);
  assert.equal(old.capacity().schemaVersion,0);
  assert.equal((old.db.prepare('PRAGMA user_version').get() as {user_version:number}).user_version,0);
});
