"""Restore one verified operator cold backup into a NEW, networkless SQL lab.

No ARSIA runtime, API, worker, migrations or historic jobs are started. Original
archives are read-only. New containers and volume are stopped and kept in full.
Supports the documented arsia-operator-cold-backup-v1 archive only.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import time
from uuid import UUID, uuid4

MANIFEST='DOCKER-COLD-MANIFEST.json'
HELPER='sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f'


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def save(path,value):
    with Path(path).open('x') as stream:json.dump(value,stream,indent=2)
    Path(path).chmod(0o600)


def docker(*args,timeout=60):
    result=subprocess.run(['docker',*args],capture_output=True,text=True,timeout=timeout)
    if result.returncode:raise RuntimeError('A scoped Docker operation failed: '+args[0])
    return result.stdout.strip()


def verified_members(archive,receipt):
    if archive.is_symlink() or sha(archive)!=receipt['archive_sha256'] or archive.stat().st_size!=receipt['archive_bytes']:
        raise ValueError('Archive identity mismatch')
    with tarfile.open(archive,'r:gz') as tar:
        members=tar.getmembers();names=[m.name for m in members]
        if len(names)!=len(set(names)) or names.count(MANIFEST)!=1:raise ValueError('Duplicate archive members')
        meta=tar.getmember(MANIFEST)
        if not meta.isfile() or meta.size>16*1024**2:raise ValueError('Invalid manifest')
        manifest=json.load(tar.extractfile(meta));rows=manifest['members']
        if manifest['version']!='arsia-operator-cold-backup-v1' or rows!=receipt['members']:raise ValueError('Unsupported or changed manifest')
        expected={r['name']:r for r in rows}
        if len(expected)!=len(rows) or set(names)-{MANIFEST}!=set(expected) or sum(r['size'] for r in rows)>10*1024**3:
            raise ValueError('Invalid or oversized inventory')
        for member in members:
            if member.name==MANIFEST:continue
            name=PurePosixPath(member.name);wanted=expected[member.name]
            if name.is_absolute() or '..' in name.parts or '\\' in member.name or not(member.isfile() or member.isdir()):raise ValueError('Unsafe archive member')
            if (member.size,member.mode,member.uid,member.gid)!=tuple(wanted[k] for k in ('size','mode','uid','gid')):raise ValueError('Changed member metadata')
            if ('file' if member.isfile() else 'directory')!=wanted['type']:raise ValueError('Changed member type')
            if member.isfile() and hashlib.file_digest(tar.extractfile(member),'sha256').hexdigest()!=wanted['sha256']:raise ValueError('Changed member bytes')
        return rows


# Runs only after full host verification, with one new empty destination volume.
EXTRACT=r'''
import hashlib,json,os,tarfile
from pathlib import Path,PurePosixPath
root=Path('/restore');assert not list(root.iterdir())
with tarfile.open('/backup/archive.tar.gz','r:gz') as tar:
 manifest=json.load(tar.extractfile('DOCKER-COLD-MANIFEST.json'))
 for row in manifest['members']:
  name=row['name'];rel=PurePosixPath(name);assert not rel.is_absolute() and '..' not in rel.parts
  member=tar.getmember(name);target=root if name=='.' else root/name
  assert member.isfile() or member.isdir()
  if member.isdir():target.mkdir(parents=True,exist_ok=True)
  else:
   target.parent.mkdir(parents=True,exist_ok=True)
   with tar.extractfile(member) as source,target.open('xb') as output:
    while data:=source.read(1024*1024):output.write(data)
   with target.open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==row['sha256']
  os.chown(target,row['uid'],row['gid']);os.chmod(target,row['mode'])
 for row in manifest['members']:
  target=root if row['name']=='.' else root/row['name'];s=target.stat()
  assert (s.st_mode&0o7777,s.st_uid,s.st_gid)==(row['mode'],row['uid'],row['gid'])
print(json.dumps({'restored_members':len(manifest['members']),'content_and_metadata_verified':True}))
'''


def run(args):
    output=args.output.resolve();output.mkdir(mode=0o700)
    receipt=json.loads(args.receipt.read_text());identity=uuid4().hex
    volume='arsia-sql-restore-'+identity[:12]+'-data'
    helper='arsia-sql-extract-'+identity[:12];server='arsia-sql-restore-'+identity[:12]
    resources=[];started=time.monotonic();success=False;volume_created=False;stage='archive_verification'
    protected={str(p.resolve()):sha(p) for p in (args.archive,args.receipt,args.original_inspect,args.expected_job,args.expected_rows)}
    try:
        rows=verified_members(args.archive.resolve(),receipt)
        assert next(r for r in rows if r['name']=='.')['uid']==999
        original=next(c for c in json.loads(args.original_inspect.read_text()) if c['Id']==receipt['container_id'])
        assert original['Image']==receipt['image_id']
        assert original['Mounts'][0]['Destination']=='/var/lib/postgresql/data'
        values=dict(item.split('=',1) for item in original['Config']['Env'] if '=' in item)
        user=values.get('POSTGRES_USER','postgres');database=values.get('POSTGRES_DB',user)
        assert values.get('PGDATA')=='/var/lib/postgresql/data'
        image=docker('image','inspect',receipt['image_id'],'--format','{{.Id}}')
        assert image==receipt['image_id'] and docker('image','inspect',HELPER,'--format','{{.Id}}')==HELPER
        save(output/'intent.json',{'id':identity,'archive_sha256':receipt['archive_sha256'],'image':image,
            'volume':volume,'containers':[helper,server],'network':'none','application_processes':False,
            'normal_runtime_read':False,'storage_policy':'keep-full'})
        stage='physical_restore'
        docker('volume','create','--label','arsia.sql-restore='+identity,volume);volume_created=True
        mount=['--mount','type=volume,source='+volume+',target=/restore']
        cid=docker('create','--name',helper,'--label','arsia.sql-restore='+identity,'--network','none','--read-only',
            '--cpus','1','--memory','256m','--cap-drop','ALL','--cap-add','CHOWN','--cap-add','FOWNER','--cap-add','DAC_OVERRIDE',
            *mount,'--mount','type=bind,source='+str(args.archive.resolve())+',target=/backup/archive.tar.gz,readonly',
            '--entrypoint','python',HELPER,'-c',EXTRACT)
        resources.append(cid)
        extracted=json.loads(docker('start','--attach',cid,timeout=180));save(output/'physical-restore.json',extracted)
        stage='postgres_startup'
        cid=docker('create','--name',server,'--label','arsia.sql-restore='+identity,'--network','none','--read-only',
            '--user','999:999','--cpus','1','--memory','512m','--pids-limit','100','--cap-drop','ALL',
            '--tmpfs','/tmp:rw,nosuid,nodev,size=16777216,mode=1777',
            '--mount','type=volume,source='+volume+',target=/var/lib/postgresql/data',
            '--entrypoint','postgres',image,'-D','/var/lib/postgresql/data','-c','listen_addresses=',
            '-c','unix_socket_directories=/tmp','-c','default_transaction_read_only=on','-c','autovacuum=off')
        resources.append(cid);docker('start',cid)
        def sql(query):
            return docker('exec',cid,'psql','-h','/tmp','-U',user,'-d',database,'-X','-A','-t','-v','ON_ERROR_STOP=1','-c',query)
        deadline=time.monotonic()+30
        while True:
            try:
                assert sql('SHOW default_transaction_read_only')=='on';break
            except RuntimeError:
                if time.monotonic()>deadline:raise
                time.sleep(.25)
        stage='sql_verification'
        job=json.loads(args.expected_job.read_text());batch=str(UUID(job['batch_id']));release=str(UUID(job['release_id']))
        source=job['source_id'];assert source.replace('_','').isalnum()
        expected=[json.loads(line) for line in args.expected_rows.read_text().splitlines()]
        actual=[json.loads(line) for line in sql("SELECT payload::text FROM canonical_crash WHERE batch_id='"+batch+"' ORDER BY record_id").splitlines()]
        normalized=lambda values:sorted(values,key=lambda r:r['record_id'])
        assert normalized(actual)==normalized(expected),'Restored canonical rows differ from preserved candidate evidence'
        fixed=json.loads(sql("SELECT json_build_object('release',(SELECT release_id FROM current_release),'batch',(SELECT sources->>'"+source+"' FROM releases WHERE id='"+release+"'),'rows',(SELECT count(*) FROM canonical_crash WHERE batch_id='"+batch+"'),'source_version',(SELECT source_version_id FROM batches WHERE id='"+batch+"'),'adapter_version',(SELECT adapter_version_id FROM batches WHERE id='"+batch+"'),'worker_rows',(SELECT count(*) FROM worker_state))::text"))
        assert fixed['release']==release and fixed['batch']==batch and fixed['rows']==len(expected)
        assert fixed['source_version']==job['result']['source_version_id'] and fixed['adapter_version']==job['result']['adapter_version_id']
        orphans=int(sql('''SELECT (SELECT count(*) FROM batches b LEFT JOIN jobs j ON j.id=b.job_id WHERE j.id IS NULL)
          +(SELECT count(*) FROM canonical_crash c LEFT JOIN batches b ON b.id=c.batch_id WHERE b.id IS NULL)
          +(SELECT count(*) FROM batches b LEFT JOIN adapter_versions a ON a.id=b.adapter_version_id WHERE b.adapter_version_id IS NOT NULL AND a.id IS NULL)
          +(SELECT count(*) FROM adapter_versions a LEFT JOIN source_versions s ON s.id=a.source_version_id WHERE s.id IS NULL)
          +(SELECT count(*) FROM releases r CROSS JOIN LATERAL jsonb_each_text(r.sources) s LEFT JOIN batches b ON b.id=s.value::uuid WHERE b.id IS NULL)'''))
        assert orphans==0
        schema=json.loads(sql("SELECT json_agg(tablename ORDER BY tablename)::text FROM pg_tables WHERE schemaname='public'"))
        save(output/'sql-verification.json',{'fixed_query':fixed,'public_tables':schema,'orphan_references':orphans,
            'all_canonical_payloads_equal':True,'compared_rows':len(actual),'read_only_transactions':True,
            'normal_database_accessed':False,'migrations_run':False,'historical_jobs_resumed':False,
            'wall_seconds':time.monotonic()-started})
        success=True
    except BaseException as exc:
        save(output/'failure.json',{'type':type(exc).__name__,'stage':stage,'message':'Cold SQL restoration did not pass. All evidence and new resources retained.'})
    finally:
        stopped=[]
        for cid in reversed(resources):
            item=json.loads(docker('inspect',cid))[0]
            assert item['Config']['Labels'].get('arsia.sql-restore')==identity
            if item['State']['Running']:docker('stop',cid)
            stopped.append({'id':cid,'stopped':not json.loads(docker('inspect',cid))[0]['State']['Running']})
        save(output/'finalize.json',{'status':'passed' if success else 'failed','containers':stopped,'volume_retained':volume if volume_created else None,
            'protected_file_hashes_unchanged':{path:sha(path)==value for path,value in protected.items()},
            'wall_seconds':time.monotonic()-started})
    return 0 if success else 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('archive','receipt','original-inspect','expected-job','expected-rows','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():parser.error('A fresh output directory is required')
    raise SystemExit(run(args))
