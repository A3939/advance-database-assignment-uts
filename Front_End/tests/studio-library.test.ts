import test, { type TestContext } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { StudioStore, uuid } from "../src/server/studio/store";
import { DEFAULT_FILTERS } from "../src/services/config";
const context = {filters:DEFAULT_FILTERS,metric:"crashes" as const,notes:"",references:""};
function fixture(t: TestContext) {
  const dir = mkdtempSync(join(tmpdir(),"arsia-library-"));
  const store = new StudioStore(join(dir,"research.sqlite"));
  t.after(()=>{store.close();rmSync(dir,{recursive:true,force:true});});
  return store;
}
test("deleting a reviewed study removes only its owned records, including saved history and attachments", t => {
  const store=fixture(t),a=store.create("Remove this",context),b=store.create("Keep this",context);
  for(const s of [a,b]) {
    store.action(s.id,{type:"snapshot",revision:s.revision});
    store.db.prepare("INSERT INTO files VALUES(?,?,?)").run(uuid(),s.id,Buffer.from("owned file"));
    store.db.prepare("INSERT INTO run_requests VALUES(?,?,?)").run(s.id,uuid(),uuid());
    store.db.prepare("INSERT INTO transfers VALUES(?,?,?,?)").run(uuid(),Date.now(),s.id,"{}");
  }
  const kept=store.get(b.id);
  assert.deepEqual(store.deleteStudy(a.id,{revision:store.get(a.id).revision}),{deleted:a.id});
  assert.throws(()=>store.get(a.id),{status:404});
  assert.deepEqual(store.get(b.id),kept);
  assert.equal(store.list().length,1);
  for(const table of ["versions","files","run_requests","transfers"]) {
    assert.equal((store.db.prepare(`SELECT count(*) AS n FROM ${table} WHERE study_id=?`).get(a.id) as {n:number}).n,0);
    assert.equal((store.db.prepare(`SELECT count(*) AS n FROM ${table} WHERE study_id=?`).get(b.id) as {n:number}).n,1);
  }
});
test("delete rejects missing, malformed and stale revisions without changing the study", t => {
  const store=fixture(t),s=store.create("Review me",context);
  for(const revision of [undefined,"1",NaN,Infinity,-1,1.2]) assert.throws(()=>store.deleteStudy(s.id,{revision}),{status:400});
  const renamed=store.action(s.id,{type:"rename",title:"Changed elsewhere",revision:s.revision});
  assert.throws(()=>store.deleteStudy(s.id,{revision:s.revision}),{status:409});
  assert.deepEqual(store.get(s.id),renamed);
  assert.throws(()=>store.deleteStudy(uuid(),{revision:0}),{status:404});
});
test("delete refuses an active run and a remaining lease; a finished run can be deleted", t => {
  const store=fixture(t),s=store.create("Analysis",context);
  const started=store.beginRun(s.id,uuid(),"Read saved evidence");
  assert.throws(()=>store.deleteStudy(s.id,{revision:started.study.revision}),{status:409});
  assert.equal(store.get(s.id).runs[0].status,"running");
  const finished=store.updateRun(s.id,{...started.run,status:"stopped"});
  store.db.prepare("INSERT INTO leases VALUES(?,?,?,?)").run(started.run.id,s.id,process.pid,Date.now()+10000);
  assert.throws(()=>store.deleteStudy(s.id,{revision:finished.revision}),{status:409});
  store.db.prepare("DELETE FROM leases WHERE study_id=?").run(s.id);
  assert.deepEqual(store.deleteStudy(s.id,{revision:finished.revision}),{deleted:s.id});
});
test("a failure during delete rolls back associated records", t => {
  const store=fixture(t),s=store.create("Keep atomic",context);
  const current=store.action(s.id,{type:"snapshot",revision:s.revision});
  store.db.exec("CREATE TRIGGER refuse_delete BEFORE DELETE ON studies BEGIN SELECT RAISE(ABORT,'injected storage failure'); END");
  assert.throws(()=>store.deleteStudy(s.id,{revision:current.revision}),/injected storage failure/);
  assert.deepEqual(store.get(s.id),current);
  assert.equal(store.versions(s.id).length,1);
});
test("rename and archive preserve document content and remain revision bound; restore remains available", t => {
  const store=fixture(t);let s=store.create("Original",context,"Retain this draft");
  s=store.action(s.id,{type:"rename",title:"New name",revision:s.revision});
  const oldRevision=s.revision;
  s=store.action(s.id,{type:"archive",archived:true,revision:s.revision});
  assert.equal(s.draft,"Retain this draft");
  assert.equal(store.list()[0].archived,true);
  assert.throws(()=>store.action(s.id,{type:"rename",title:"Stale",revision:oldRevision}),{status:409});
  s=store.action(s.id,{type:"archive",archived:false,revision:s.revision});
  assert.equal(s.title,"New name");assert.equal(s.archived,false);
});
