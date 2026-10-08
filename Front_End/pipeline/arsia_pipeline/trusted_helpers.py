"""Exact identities for trusted maintenance helpers (not uploaded adapters).

A local Desktop translation is validated before a created container can run.
The daemon path is an opaque POSIX string, never resolved on the client.
"""
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path, PurePosixPath
from uuid import uuid4
from .storage_lifecycle import StorageError, now

VERSION='trusted-helper-v2'
HELPER_LABEL='arsia.storage.helper'
OPERATION_LABEL='arsia.storage.operation'
_TEST_HELPER_HOOK=None


def fail(message):raise StorageError('STORAGE_OWNER',message)

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def daemon_identity(docker):
    # A remote daemon cannot prove identities of this host's managed files.
    if any(os.environ.get(k) for k in ('DOCKER_HOST','DOCKER_TLS_VERIFY','DOCKER_CERT_PATH')):
        fail('Helper requires an explicit local context without host/TLS overrides')
    name=docker('context','show').decode().strip()
    ctx=json.loads(docker('context','inspect',name))[0]
    host=ctx.get('Endpoints',{}).get('docker',{}).get('Host','')
    if not host.startswith('unix:///') or not Path(host[7:]).is_socket():
        fail('Helper daemon context is not a verified local Unix socket')
    info=json.loads(docker('info','--format','{{json .}}'))
    if not info.get('ID') or info.get('OSType')!='linux':fail('Unconfirmed helper daemon identity')
    desktop=(sys.platform=='darwin' and ctx.get('Metadata',{}).get('Description')=='Docker Desktop'
        and info.get('OperatingSystem')=='Docker Desktop' and info.get('Name')=='docker-desktop'
        and host=='unix://'+str(Path.home()/'.docker/run/docker.sock'))
    return {'context':name,'endpoint':host,'socket_realpath':str(Path(host[7:]).resolve()),
        'daemon_id':info['ID'],'server_version':info['ServerVersion'],'os':info.get('OperatingSystem'),
        'name':info.get('Name'),'client_platform':sys.platform,
        'mapping':'desktop-macos-host-mnt-v1' if desktop else 'direct-local-v1'}


def host_path_identity(source):
    if not isinstance(source,str) or not source.startswith('/') or str(PurePosixPath(source))!=source or '..' in PurePosixPath(source).parts:
        fail('Bind source must be a normalized absolute host path')
    path=Path(source);chain=[]
    for p in [*reversed(path.parents),path]:
        try:s=p.lstat()
        except OSError as exc:raise StorageError('STORAGE_OWNER','Bind source identity unavailable') from exc
        if stat.S_ISLNK(s.st_mode) or not stat.S_ISDIR(s.st_mode):fail('Bind source ancestors must be direct directories')
        chain.append({'path':str(p),'device':s.st_dev,'inode':s.st_ino})
    return chain


def normalized_mounts(actual):
    mounts=[]
    for m in actual.get('Mounts',[]):
        mounts.append({'type':m.get('Type'),'source':m.get('Name') if m.get('Type')=='volume' else m.get('Source'),
                       'target':m.get('Destination'),'readonly':not m.get('RW',False)})
    return sorted(mounts,key=lambda m:str(m['target']))


def validate_mounts(requested,actual,daemon):
    mounts=normalized_mounts(actual)
    if not requested or len(mounts)!=len(requested) or len({m['target'] for m in mounts})!=len(mounts):fail('Helper mount count or targets changed')
    evidence=[]
    for request in requested:
        if request['type'] not in {'bind','volume'}:fail('Unsupported helper mount type')
        found=[m for m in mounts if m['target']==request['target']]
        if len(found)!=1:fail('Helper mount target changed')
        m=found[0]
        if m['type']!=request['type'] or m['readonly']!=request.get('readonly',False):fail('Helper mount type or access changed')
        source=request['source'];rule='exact'
        if m['source']!=source:
            if request['type']!='bind' or daemon.get('mapping')!='desktop-macos-host-mnt-v1' or not source.startswith('/') or m['source']!='/host_mnt'+source:
                fail('Helper mount source has no proven exact correspondence')
            rule='desktop-macos-host-mnt-v1'
        evidence.append({'requested':request,'daemon':m,'rule':rule})
    return evidence


def validate(intent,actual,current_daemon,*,container_id,receipt=None):
    if not isinstance(actual,dict):fail('Helper exact container is unavailable')
    if intent.get('version')!=VERSION or current_daemon!=intent.get('daemon'):fail('Helper daemon/receipt compatibility boundary changed')
    if not re.fullmatch('[0-9a-f]{64}',container_id or '') or actual.get('Id')!=container_id:fail('Helper exact container ID changed')
    if actual.get('Name')!='/'+intent['name']:fail('Helper name changed')
    labels=actual.get('Config',{}).get('Labels') or {}
    expected={'arsia.storage.session':intent['session_id'],'arsia.storage.instance':intent['instance_id'],
              HELPER_LABEL:intent['helper_id'],OPERATION_LABEL:intent['operation_id']}
    if any(labels.get(k)!=v for k,v in expected.items()):fail('Helper session/operation identity changed')
    if actual.get('Image')!=intent['image']:fail('Helper image changed')
    host=actual.get('HostConfig',{});config=actual.get('Config',{})
    if host.get('NetworkMode')!='none' or host.get('ReadonlyRootfs') is not True or config.get('User')!='0:0' or host.get('Privileged'):
        fail('Helper isolation changed')
    if set(host.get('CapDrop') or [])!={'ALL'} or set(host.get('CapAdd') or [])!={c if c.startswith('CAP_') else 'CAP_'+c for c in intent['caps']}:fail('Helper capabilities changed')
    for request in intent['mounts']:
        if request['type']=='bind' and host_path_identity(request['source'])!=intent['host_paths'].get(request['source']):fail('Host bind directory/symlink identity changed')
    mapping=validate_mounts(intent['mounts'],actual,current_daemon)
    result={'version':VERSION,'container_id':container_id,'helper_id':intent['helper_id'],
            'intent_sha256':digest(intent),'daemon':current_daemon,'mounts':normalized_mounts(actual),'mapping':mapping}
    if receipt is not None and receipt!=result:fail('Persistent helper receipt differs from current exact identity')
    return result


def records(session):
    with session.ledger.connect() as db:
        rows=list(db.execute("SELECT event,details FROM journal WHERE event IN ('helper_intent','helper_created','helper_receipt') ORDER BY id"))
    return [(r['event'],json.loads(r['details'])) for r in rows]


def recover(session,docker):
    from .storage_restore import inspect_optional
    rows=records(session);current=None
    for event,intent in rows:
        if event!='helper_intent':continue
        if intent.get('version')!=VERSION:
            if inspect_optional('container',intent['name']) is not None:fail('Legacy helper lacks a v2 exact-ID receipt; recovery refused')
            continue
        if intent['session_id']!=session.cfg['test_session_id'] or intent['instance_id']!=session.cfg['instance_id']:fail('Helper intent belongs to another session')
        if current is None:current=daemon_identity(docker)
        if current!=intent['daemon']:fail('Helper daemon/context changed; absence cannot be inferred')
        created=[v for e,v in rows if e=='helper_created' and v.get('helper_id')==intent['helper_id']]
        receipts=[v for e,v in rows if e=='helper_receipt' and v.get('helper_id')==intent['helper_id']]
        if len(created)!=1:
            if not created and inspect_optional('container',intent['name']) is None:continue
            fail('Helper creation identity incomplete; preserve resources and reservation')
        cid=created[0].get('container_id')
        if not re.fullmatch('[0-9a-f]{64}',cid or ''):fail('Malformed helper creation ID')
        actual=inspect_optional('container',cid)
        named=inspect_optional('container',intent['name'])
        if actual is None:
            if named is not None:fail('Helper name was replaced by another container')
            continue
        if named is None or named['Id']!=cid:fail('Helper name/ID pairing changed')
        if len(receipts)!=1:fail('Helper verified receipt missing or ambiguous; automatic recovery refused')
        envelope=receipts[0]
        receipt=envelope.get('receipt')
        if not isinstance(receipt,dict) or digest(receipt)!=envelope.get('sha256'):fail('Helper receipt damaged or incompletely written')
        validate(intent,actual,current,container_id=cid,receipt=receipt)
        # Reinspect exact ID immediately before mutation, never operate by name.
        validate(intent,inspect_optional('container',cid),daemon_identity(docker),container_id=cid,receipt=receipt)
        if actual['State']['Running']:docker('stop','--time','5',cid)
        remaining=inspect_optional('container',cid)
        if remaining is not None:
            validate(intent,remaining,current,container_id=cid,receipt=receipt)
            if remaining['State']['Running']:fail('Helper did not stop')
            docker('rm',cid)
        session.ledger.journal('helper_recovered',helper_id=intent['helper_id'],container_id=cid,operation_id=intent['operation_id'])
    session.ledger.journal('helpers_reconciled')


def run(session,docker,image,mounts,entrypoint,args,*,caps=(),timeout=60,operation_id=None):
    from .storage_restore import inspect_optional
    helper_id=uuid4().hex;name='arsia-storage-helper-'+helper_id
    daemon=daemon_identity(docker)
    paths={m['source']:host_path_identity(m['source']) for m in mounts if m['type']=='bind'}
    intent={'version':VERSION,'name':name,'helper_id':helper_id,'operation_id':operation_id or helper_id,
        'session_id':session.cfg['test_session_id'],'instance_id':session.cfg['instance_id'],
        'image':image,'mounts':mounts,'caps':list(caps),'daemon':daemon,'host_paths':paths,'created_at':now()}
    session.ledger.journal('helper_intent',**intent)
    def hook(phase):
        if _TEST_HELPER_HOOK:_TEST_HELPER_HOOK(phase,intent)
    hook('helper_intent_saved')
    command=['create','--name',name,'--label','arsia.storage.session='+intent['session_id'],
        '--label','arsia.storage.instance='+intent['instance_id'],'--label',HELPER_LABEL+'='+helper_id,
        '--label',OPERATION_LABEL+'='+intent['operation_id'],'--network=none','--read-only','--user=0:0','--cap-drop=ALL','--pull=never']
    for cap in caps:command.extend(['--cap-add',cap])
    for mount in mounts:
        command.extend(['--mount','type='+mount['type']+',source='+mount['source']+',target='+mount['target']+(',readonly' if mount.get('readonly') else '')])
    if entrypoint=='python':command.extend(['--env','PYTHONPATH=/code'])
    cid=docker(*command,'--entrypoint',entrypoint,image,*args).decode().strip()
    if not re.fullmatch('[0-9a-f]{64}',cid):fail('Docker create did not return an exact container ID')
    session.ledger.journal('helper_created',helper_id=helper_id,container_id=cid)
    hook('helper_created')
    actual=inspect_optional('container',cid)
    if actual is None or actual['State']['Status']!='created':fail('Helper ran before verified receipt')
    receipt=validate(intent,actual,daemon_identity(docker),container_id=cid)
    session.ledger.journal('helper_receipt',helper_id=helper_id,receipt=receipt,sha256=digest(receipt))
    hook('helper_receipted')
    validate(intent,inspect_optional('container',cid),daemon_identity(docker),container_id=cid,receipt=receipt)
    try:
        value=docker('start','--attach',cid,timeout=timeout)
        actual=inspect_optional('container',cid)
        validate(intent,actual,daemon_identity(docker),container_id=cid,receipt=receipt)
        if actual['State']['Running'] or actual['State']['ExitCode']!=0:raise StorageError('STORAGE_HELPER','Trusted helper did not exit successfully')
        return value
    finally:recover(session,docker)
