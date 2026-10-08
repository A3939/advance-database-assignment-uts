import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { spawnSync } from "node:child_process";
import { DatabaseSync } from "node:sqlite";
import { StudioStore } from "../src/server/studio/store";
import { DEFAULT_FILTERS } from "../src/services/config";

test('capacity and full backup work without altering the source study; explicit migration keeps a recoverable old database',()=>{
  const root=mkdtempSync(join(tmpdir(),'arsia-admin-')),path=join(root,'input.sqlite');
  const store=new StudioStore(path);const study=store.create('保留研究',{filters:DEFAULT_FILTERS,metric:'crashes',notes:'',references:''});store.db.exec('PRAGMA user_version=0');store.close();
  const run=(...args:string[])=>spawnSync(process.execPath,['--import','tsx','scripts/studio-admin.ts',...args],{encoding:'utf8'});
  const capacity=run('capacity',path);assert.equal(capacity.status,0,capacity.stderr);assert.equal(JSON.parse(capacity.stdout).studyCount,1);assert.equal(JSON.parse(capacity.stdout).migrationRequired,true);
  const backup=join(root,'complete.sqlite'),old=join(root,'before-migration.sqlite');
  assert.equal(run('backup',path,backup).status,0);
  assert.equal(run('backup',path,backup).status,1);
  const migrated=run('migrate',path,old);assert.equal(migrated.status,0,migrated.stderr);
  for(const p of [backup,old,path]) {const db=new DatabaseSync(p,{readOnly:true});const row=db.prepare('SELECT doc FROM studies WHERE id=?').get(study.id) as {doc:string};assert.equal(JSON.parse(row.doc).title,'保留研究');assert.equal((db.prepare('PRAGMA user_version').get() as {user_version:number}).user_version,p===path?1:0);db.close();}
  assert.notEqual(run('migrate').status,0);
});
