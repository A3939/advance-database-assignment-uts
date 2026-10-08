"""Verified archives, resumable eviction and never-overwriting restoration."""
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile
from uuid import uuid4

from .storage_lifecycle import (VERSION, StorageError, atomic_json, assert_budget,
    bounded_path, fsync_dir, maintenance, now, reasons, reference_snapshot, sha)

MANIFEST = 'STORAGE-MANIFEST.json'


def inventory(root):
    root = Path(root)
    if root.is_symlink() or not root.exists():
        raise StorageError('STORAGE_SOURCE','Archive source is missing or indirect')
    paths = [root] + (sorted(root.rglob('*')) if root.is_dir() else [])
    result = []
    for path in paths:
        info = path.lstat()
        name = '.' if path == root else path.relative_to(root).as_posix()
        if name == MANIFEST or name.startswith(MANIFEST+'/'):
            raise StorageError('STORAGE_RESERVED','Source uses reserved archive manifest name')
        if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
            raise StorageError('STORAGE_UNSUPPORTED','Links and special files are not archived')
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise StorageError('STORAGE_HARDLINK','Hardlinked archive input requires explicit review')
        result.append({'name':name,'type':'file' if path.is_file() else 'directory',
            'size':info.st_size if path.is_file() else 0,'mode':stat.S_IMODE(info.st_mode),
            'uid':info.st_uid,'gid':info.st_gid,'mtime_ns':info.st_mtime_ns,
            'sha256':sha(path) if path.is_file() else None})
    return result


def _member_name(value):
    name = value.removeprefix('./').rstrip('/') or '.'
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name:
        raise StorageError('ARCHIVE_PATH','Archive has an unsafe member name')
    return name


def verify(archive, *, expected=None):
    """Reopen compression and read EVERY file, checking types and metadata."""
    try:
        with tarfile.open(archive, 'r:gz') as tar:
            members = tar.getmembers()
            names = [_member_name(m.name) for m in members]
            if len(names) != len(set(names)) or names.count(MANIFEST) != 1:
                raise StorageError('ARCHIVE_MEMBERS','Missing manifest or duplicate archive members')
            manifest_member = members[names.index(MANIFEST)]
            if not manifest_member.isfile() or manifest_member.size > 8*1024**2:
                raise StorageError('ARCHIVE_MANIFEST','Invalid archive manifest')
            manifest = json.load(tar.extractfile(manifest_member))
            if manifest.get('version') != VERSION or (expected is not None and manifest != expected):
                raise StorageError('ARCHIVE_MANIFEST','Archive manifest identity differs')
            wanted = {m['name']:m for m in manifest['members']}
            if len(wanted)!=len(manifest['members']) or set(names)-{MANIFEST} != set(wanted):
                raise StorageError('ARCHIVE_MEMBERS','Archive member set differs from manifest')
            for member, name in zip(members, names):
                if name == MANIFEST: continue
                row = wanted[name]
                if not (member.isfile() or member.isdir()) or member.islnk() or member.issym():
                    raise StorageError('ARCHIVE_TYPE','Special archive member refused')
                actual = {'type':'file' if member.isfile() else 'directory','size':member.size,
                          'mode':member.mode,'uid':member.uid,'gid':member.gid}
                if any(actual[k] != row[k] for k in actual):
                    raise StorageError('ARCHIVE_METADATA','Member ownership, mode, type or size differs')
                if abs(member.mtime-row['mtime_ns']/1e9) > .000001:
                    raise StorageError('ARCHIVE_METADATA','Member modification time differs')
                if member.isfile():
                    import hashlib
                    digest = hashlib.file_digest(tar.extractfile(member),'sha256').hexdigest()
                    if digest != row['sha256']:
                        raise StorageError('ARCHIVE_CONTENT','Member content differs from manifest')
        return manifest
    except StorageError: raise
    except (OSError, ValueError, KeyError, tarfile.TarError, EOFError) as exc:
        raise StorageError('ARCHIVE_INVALID','Compressed archive could not be fully verified') from exc


def create(source, destination, *, context=None, hook=lambda phase:None):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.exists() or destination.is_symlink():
        raise StorageError('ARCHIVE_EXISTS','Archive destination must be new')
    members = inventory(source)
    manifest = {'version':VERSION,'members':members,'context':context or {}}
    partial = destination.with_suffix(destination.suffix+'.partial')
    if partial.is_symlink(): raise StorageError('STORAGE_SYMLINK','Indirect archive staging refused')
    # A previous partial is diagnostic evidence; do not silently replace it.
    if partial.exists(): raise StorageError('ARCHIVE_PARTIAL','An interrupted archive requires recovery')
    with partial.open('xb') as stream:
        os.chmod(partial,0o600)
        hook('partial')
        with tarfile.open(fileobj=stream,mode='w:gz',format=tarfile.PAX_FORMAT) as tar:
            for row in members:
                path = Path(source) if row['name']=='.' else Path(source)/row['name']
                info = tar.gettarinfo(str(path),arcname=row['name'])
                if row['type']=='file':
                    with path.open('rb') as content: tar.addfile(info,content)
                else: tar.addfile(info)
            body = json.dumps(manifest,sort_keys=True).encode()
            info = tarfile.TarInfo(MANIFEST);info.size=len(body);info.mode=0o600
            tar.addfile(info,io.BytesIO(body))
        stream.flush();os.fsync(stream.fileno())
    hook('written')
    verify(partial,expected=manifest)
    if inventory(source)!=members:
        raise StorageError('ARCHIVE_SOURCE_CHANGED','Source changed during archive; originals retained')
    os.rename(partial,destination);fsync_dir(destination.parent)
    hook('published')
    return manifest


def evict(source, manifest, journal=lambda *a,**k:None, hook=lambda phase:None):
    """Remove only verified members; interrupted removal can safely resume."""
    source = Path(source)
    if not source.exists(): return
    remaining = inventory(source)
    wanted = {row['name']:row for row in manifest['members']}
    for row in remaining:
        expected = wanted.get(row['name'])
        # Directory mtimes change during partial eviction; other metadata does not.
        keys = ('type','mode','uid','gid','size','sha256')
        if expected is None or any(row[k]!=expected[k] for k in keys) or (
            row['type']=='file' and row['mtime_ns']!=expected['mtime_ns']):
            raise StorageError('ARCHIVE_SOURCE_CHANGED','Source changed before/during eviction; retained')
    for row in sorted(remaining,key=lambda m:len(PurePosixPath(m['name']).parts),reverse=True):
        path = source if row['name']=='.' else source/row['name']
        journal('evict_member',name=row['name'])
        if row['type']=='file':
            if path.is_symlink() or sha(path)!=row['sha256']:
                raise StorageError('ARCHIVE_SOURCE_CHANGED','Member changed immediately before removal')
            path.unlink()
        else: path.rmdir()
        hook('evicted_member')
    fsync_dir(source.parent)


def restore(archive, target, *, hook=lambda phase:None):
    target = Path(target)
    if target.exists() or target.is_symlink() or any(p.is_symlink() for p in target.parents):
        raise StorageError('RESTORE_EXISTS','Restoration requires a new direct destination')
    manifest = verify(archive)
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    partial = target.with_name(target.name+'.restore-'+uuid4().hex)
    root_row = next(m for m in manifest['members'] if m['name']=='.')
    if root_row['type']=='directory': partial.mkdir(mode=0o700)
    with tarfile.open(archive,'r:gz') as tar:
        for row in manifest['members']:
            path = partial if row['name']=='.' else bounded_path(partial,row['name'])
            if row['type']=='directory': path.mkdir(parents=True,exist_ok=True,mode=0o700)
            else:
                path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                with path.open('xb') as out, tar.extractfile(row['name']) as content:
                    while chunk:=content.read(1024**2): out.write(chunk)
                    out.flush();os.fsync(out.fileno())
            os.chmod(path,row['mode'])
            hook('restored_member')
    for row in reversed(manifest['members']):
        path = partial if row['name']=='.' else partial/row['name']
        os.utime(path,ns=(row['mtime_ns'],row['mtime_ns']))
    observed = inventory(partial)
    # Host restore preserves content/mode/time; uid/gid require privileged DB restore.
    for actual, wanted in zip(observed,manifest['members']):
        if any(actual[k]!=wanted[k] for k in ('name','type','size','mode','mtime_ns','sha256')):
            raise StorageError('RESTORE_CONTENT','Restored members differ; partial retained')
    if len(observed)!=len(manifest['members']): raise StorageError('RESTORE_CONTENT','Missing restored members')
    os.rename(partial,target);fsync_dir(target.parent)
    return manifest


def apply(cfg, plan_id, *, hook=lambda phase:None):
    results = []
    with maintenance(cfg) as (ledger,conn):
        with ledger.connect() as db:
            row = db.execute('SELECT payload FROM plans WHERE id=?',(plan_id,)).fetchone()
        if not row: raise StorageError('STORAGE_PLAN','Plan does not belong to this session')
        plan = json.loads(row['payload'])
        snapshot = reference_snapshot(conn,ledger.root)
        for entry in plan['entries']:
            if not entry['eligible']: continue
            resource = ledger.get(entry['id'])
            blockers = reasons(resource,snapshot,ledger.root)
            if blockers or resource['changed_at']!=entry['changed_at']:
                results.append({'id':resource['id'],'status':'blocked','reasons':blockers or ['plan invalidated']})
                continue
            source = bounded_path(ledger.root,resource['relative_path'],exists=True)
            archive_id = resource['archive_id'] or uuid4().hex
            archive = ledger.home/'archives'/(archive_id+'.tar.gz')
            try:
                ledger.state(resource['id'],'archive_planned',archive_id=archive_id)
                hook('intent')
                assert_budget(ledger,sum(r['size'] for r in inventory(source))+1024**2)
                ledger.state(resource['id'],'archiving')
                manifest = create(source,archive,context={'resource_id':resource['id'],
                    'instance_id':cfg['instance_id'],'test_session_id':cfg['test_session_id']},hook=hook)
                atomic_json(archive.with_suffix('.verification.json'),{'manifest':manifest,'sha256':sha(archive),'verified_at':now()})
                ledger.archive_record(archive_id,archive)
                ledger.state(resource['id'],'verified');hook('verified')
                if reasons(ledger.get(resource['id']),reference_snapshot(conn,ledger.root),ledger.root):
                    raise StorageError('STORAGE_REFERENCED','A new dependency prevents eviction')
                ledger.state(resource['id'],'eviction_pending')
                evict(source,verify(archive,expected=manifest),
                      journal=lambda event,**kw:ledger.journal(event,resource['id'],**kw),hook=hook)
                ledger.state(resource['id'],'archived')
                results.append({'id':resource['id'],'status':'archived','archive_id':archive_id})
            except Exception as exc:
                ledger.state(resource['id'],'blocked',reason=getattr(exc,'code','ARCHIVE_FAILED'))
                results.append({'id':resource['id'],'status':'blocked','code':getattr(exc,'code','ARCHIVE_FAILED')})
        return results


def recover(cfg):
    """Explicit reconciliation only, under the same locks as first execution."""
    results=[]
    with maintenance(cfg) as (ledger,conn):
        for resource in ledger.resources():
            if not resource['archive_id'] or resource['state']=='archived': continue
            archive=ledger.home/'archives'/(resource['archive_id']+'.tar.gz')
            if not archive.is_file():
                results.append({'id':resource['id'],'status':'blocked','code':'ARCHIVE_PARTIAL'})
                continue
            blockers=reasons(resource,reference_snapshot(conn,ledger.root),ledger.root)
            if blockers:
                results.append({'id':resource['id'],'status':'blocked','reasons':blockers});continue
            try:
                receipt=json.loads(archive.with_suffix('.verification.json').read_text())
                if sha(archive)!=receipt['sha256']: raise StorageError('ARCHIVE_CHANGED','Archive identity changed')
                manifest=verify(archive,expected=receipt['manifest'])
                ledger.archive_record(resource['archive_id'],archive)
                ledger.state(resource['id'],'eviction_pending')
                evict(bounded_path(ledger.root,resource['relative_path']),manifest,
                      journal=lambda event,**kw:ledger.journal(event,resource['id'],**kw))
                ledger.state(resource['id'],'archived')
                results.append({'id':resource['id'],'status':'archived'})
            except Exception as exc:
                ledger.state(resource['id'],'blocked',reason=getattr(exc,'code','ARCHIVE_RECOVERY_BLOCKED'))
                results.append({'id':resource['id'],'status':'blocked','code':getattr(exc,'code','ARCHIVE_RECOVERY_BLOCKED')})
    return results
