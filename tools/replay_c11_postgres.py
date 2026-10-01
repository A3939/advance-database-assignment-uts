#!/usr/bin/env python3
"""Replay the pinned VIC originals in a private PostgreSQL 16 database."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import time
from uuid import NAMESPACE_URL, uuid5

import psycopg
from psycopg.types.json import Jsonb
from arsia_ingest.models import ResourceSpec, ParseStats
from arsia_ingest.readers import iter_native_rows
from arsia_ingest.raw_load import RawLoader

ROOT = Path(__file__).resolve().parents[1]
A_COMMIT = "c0824da06b6e7b3f73c4ddeab2114d10b7156913"
IMAGE = "postgres@sha256:efedf3595f1d6f415c08568ba171029bf54052e754cc9f030e3f2412b21f3d67"
SQL_PATH = ROOT / "sql/evidence/c11_vic_source_model_queries.sql"


def run(args, **kw):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kw).stdout


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")


def queries():
    parts = re.split(r"(?m)^-- (Q[0-9]+[A-Z]?)\. [^\n]*\n", SQL_PATH.read_text(encoding="utf-8"))
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def query_results(conn, files, out):
    # Read every result; cursor fast-start plans are poor for full-file anti joins.
    conn.execute('SET LOCAL cursor_tuple_fraction = 1.0')
    conn.execute('SET LOCAL enable_nestloop = off')
    selected = {f['resource_id'].removeprefix('official_vic_'): f for f in files}
    def identity(role):
        f = selected[role]
        return [f[k] for k in ('source_id','resource_id','file_sha256','parser_version')]
    layouts = {'Q1':['accident','vehicle','person','node'], 'Q2':['vehicle','person'],
               'Q3A':['node'],'Q3B':['node'],'Q3C':['node'],'Q4':['node'],
               'Q5A':['vehicle','person','node'],'Q2B':['person'],
               'Q5C':['vehicle','person'],'Q6':['accident','node']}
    results = {}
    for name in ('Q0','Q1','Q2','Q2B','Q3A','Q3B','Q3C','Q4','Q5A','Q5B','Q5C','Q6'):
        if name == 'Q0':
            params = [Jsonb(files)]
        elif name == 'Q5B':
            example = results['Q5A']['sample'][0]['accident_no']
            params = identity('accident') + [example] + sum((identity(r) for r in ('vehicle','person','node')), [])
        else:
            params = sum((identity(r) for r in layouts[name]), [])
        path = out / (name + '.jsonl')
        total, sample, sums = 0, [], {}
        with conn.cursor(name='c11_' + name) as cur, path.open('w', encoding='utf-8') as dest:
            cur.execute(queries()[name], params)
            for values in cur:
                row = dict(zip([c.name for c in cur.description], values, strict=True))
                if total < 10:
                    sample.append(row)
                if name == 'Q3B':
                    sums['observations_in_repeated_groups'] = sums.get('observations_in_repeated_groups',0) + row['observation_count']
                dest.write(json.dumps(row, default=str) + '\n')
                total += 1
        results[name] = {'row_count':total,'sample':sample,**sums,
                         'detail_file':path.name,'detail_sha256':sha(path.read_bytes()),
                         'query_sha256':sha(queries()[name].encode())}
        print(name, total, 'result rows', flush=True)
    assert results['Q5B']['row_count'] == results['Q5A']['sample'][0]['rows_from_naive_multi_join']
    return results


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--raw-root', type=Path, required=True)
    ap.add_argument('--a-repo', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    spec = json.loads((ROOT/'config/c06-vic-r1.json').read_text(encoding='utf-8'))
    definition = json.loads((ROOT/'config/vic-restricted-inputs-v1.json').read_text(encoding='utf-8'))
    files = spec['files']
    originals = {}
    for f in files:
        name = f['resource_id'].removeprefix('official_') + '.csv'
        path = args.raw_root.resolve()/name
        if sha(path.read_bytes()) != f['file_sha256']:
            raise ValueError('Original file hash mismatch: ' + name)
        originals[f['resource_id']] = path
    def git(path):
        return run(['git','-C',str(args.a_repo),'show',A_COMMIT+':'+path])
    names = run(['git','-C',str(args.a_repo),'ls-tree','-r','--name-only',A_COMMIT,'sql/migrations']).splitlines()
    if [Path(n).name[:3] for n in names] != [f'{i:03}' for i in range(1,12)]:
        raise ValueError('Expected A migrations 001–011')
    migrations = {n:git(n) for n in names}
    audit = git('sql/tests/a03_database_roles.sql')
    receipt = {'c_base':'ad8baeddd3f6d2eeccdc2e31bafd71b687ad4da8', 'a_commit':A_COMMIT,
               'image':IMAGE,'python':sys.version,'files':files,'analysis':spec['analysis'],
               'query_file_sha256':sha(SQL_PATH.read_bytes()),
               'runner_sha256':sha(Path(__file__).read_bytes()),
               'migrations':{n:sha(v.encode()) for n,v in migrations.items()},
               'replay':'B native reader + B08 registration + COPY into empty Raw; diagnostic replay, not a B10 build',
               'publication_performed':False}
    name = 'arsia-c11-' + secrets.token_hex(5)
    password = secrets.token_urlsafe(30)
    started = False
    try:
        with tempfile.TemporaryDirectory() as temp:
            envfile=Path(temp)/'postgres.env'
            envfile.write_text('POSTGRES_USER=arsia_owner\nPOSTGRES_DB=arsia\nPOSTGRES_PASSWORD='+password+'\n')
            envfile.chmod(0o600)
            run(['docker','run','-d','--name',name,'--env-file',str(envfile),'-p','127.0.0.1::5432',
                 '--tmpfs','/var/lib/postgresql/data',IMAGE,'postgres','-c','timezone=UTC'])
        started = True
        for _ in range(150):
            if subprocess.run(['docker','exec',name,'pg_isready','-h','127.0.0.1','-U','arsia_owner','-d','arsia'],capture_output=True).returncode == 0:
                break
            time.sleep(.2)
        else:
            raise RuntimeError('PostgreSQL did not start')
        def sql(statement):
            return run(['docker','exec','-i',name,'psql','-X','-v','ON_ERROR_STOP=1','-U','arsia_owner','-d','arsia'],input=statement)
        (out/'migrations.log').write_text(''.join(sql(v) for v in migrations.values()))
        sql("ALTER ROLE arsia_loader PASSWORD '"+password+"';")
        (out/'a03-before.log').write_text(sql(audit))
        port=run(['docker','port',name,'5432']).strip().rsplit(':',1)[1]
        with psycopg.connect(host='127.0.0.1',port=port,dbname='arsia',user='arsia_loader',password=password) as conn:
            assert conn.info.server_version//10000 == 16
            receipt['environment']=conn.execute("SELECT version(),current_user,session_user,current_setting('server_encoding'),current_setting('TimeZone')").fetchone()
            assert receipt['environment'][1:] == ('arsia_loader','arsia_loader','UTF8','UTC')
            assert conn.execute('SELECT count(*) FROM raw.record').fetchone()==(0,)
            RawLoader(conn,dataset_kind='official',sources=definition['sources'],files=files).register()
            loaded={}
            for f in files:
                path=originals[f['resource_id']]
                resource=ResourceSpec(**{k:f[k] for k in ('source_id','resource_id','resource_role','entity_kind','format','encoding','sheet','header_row')},path=path,header=tuple(f['header']),expected_sha256=f['file_sha256'])
                stats=ParseStats()
                with conn.cursor().copy('COPY raw.record(raw_record_id,resource_id,source_id,file_sha256,parser_version,row_locator,payload) FROM STDIN') as copy:
                    for row in iter_native_rows(path,resource,stats):
                        rid=uuid5(NAMESPACE_URL, f['resource_id']+':'+f['file_sha256']+':'+row.row_locator)
                        copy.write_row((rid,f['resource_id'],f['source_id'],f['file_sha256'],f['parser_version'],row.row_locator,Jsonb(row.payload)))
                assert stats.raw_count==f['raw_count']
                assert sha(path.read_bytes())==f['file_sha256']
                loaded[f['resource_id']]=stats.raw_count
                print('Loaded',f['resource_id'],stats.raw_count,flush=True)
            receipt['loaded_counts']=loaded
            receipt['results']=query_results(conn,files,out)
            assert conn.execute('SELECT count(*) FROM raw.record').fetchone()==(sum(loaded.values()),)
            conn.rollback()
            receipt['raw_after_rollback']=conn.execute('SELECT count(*) FROM raw.record').fetchone()[0]
            assert receipt['raw_after_rollback']==0
        (out/'a03-after.log').write_text(sql(audit))
        receipt['permissions']='Original A03 audit passed before and after; no grants added'
    finally:
        if started:
            run(['docker','rm','-f',name])
            receipt['container_removed']=True
        save(out/'receipt.json',receipt)
    print('C11 replay complete; evidence:',out,flush=True)


if __name__=='__main__':
    main()
