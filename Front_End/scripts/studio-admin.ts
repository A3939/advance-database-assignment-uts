/** Explicit exact-file maintenance. No default database and no removal/reset. */
import { lstatSync, existsSync } from "node:fs";
import { isAbsolute, resolve } from "node:path";
import { DatabaseSync } from "node:sqlite";
import { StudioStore, studioCapacity, STUDIO_SCHEMA_VERSION } from "../src/server/studio/store";

const [command, database, output, ...extra]=process.argv.slice(2);
if (!['capacity','backup','migrate'].includes(command) || !database || !isAbsolute(database) || extra.length || (command==='capacity' ? !!output : !output))
  throw Error('Usage: studio-admin capacity /absolute/research.sqlite | backup /absolute/research.sqlite /absolute/new.sqlite | migrate /absolute/research.sqlite /absolute/pre-migration.sqlite');
if (!lstatSync(database).isFile() || lstatSync(database).isSymbolicLink()) throw Error('Choose an existing regular database file');
if(output && (!isAbsolute(output) || existsSync(output) || resolve(output)===resolve(database))) throw Error('Output must be a new absolute file path');
if(command==='migrate'){
  const store=new StudioStore(database);
  try{store.migrateAfterBackup(output!);process.stdout.write(JSON.stringify({status:'migrated',...store.capacity()})+'\n');}
  finally{store.close();}
}else{
  const db=new DatabaseSync(database,{readOnly:true});
  try{
    const version=(db.prepare('PRAGMA user_version').get() as {user_version:number}).user_version;
    if(command==='backup') {db.prepare('VACUUM INTO ?').run(output!);process.stdout.write(JSON.stringify({status:'backed_up',schemaVersion:version})+'\n');}
    else {
      if(version>STUDIO_SCHEMA_VERSION) throw Error('A newer application is required to inspect this database schema');
      process.stdout.write(JSON.stringify(studioCapacity(db,version))+'\n');
    }
  }finally{db.close();}
}
