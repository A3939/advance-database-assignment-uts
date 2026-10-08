"""Operator-only, explicit managed configuration. Default operation is read-only."""
import argparse
import json
import os
from pathlib import Path

from .storage_lifecycle import Ledger, StorageError, atomic_json, bounded_path, now, sha
from .storage_archive import apply, recover, restore


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True,type=Path)
    parser.add_argument('command',choices=['status','inspect','plan','apply','pin','unpin','restore','recover','restore-db','reconcile-restore','upload-gc','pin-operation','unpin-operation','space-status','reservations-status','reservations-plan','reservations-reconcile'],nargs='?',default='status')
    parser.add_argument('--plan')
    parser.add_argument('--resource')
    parser.add_argument('--reason')
    parser.add_argument('--archive')
    parser.add_argument('--new-target',help='New relative directory under THIS managed root')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--operation')
    parser.add_argument('--purpose',choices=['verify_only','restore_for_use'],default='restore_for_use')
    args=parser.parse_args()
    if args.config.is_symlink() or args.config.stat().st_mode&0o077:
        parser.error('A direct private runtime file is required')
    os.environ['ARSIA_IMPORT_CONFIG']=str(args.config.resolve())
    from .config import read_config
    cfg=read_config();ledger=Ledger(cfg,read_only=args.command in {'status','inspect','space-status','reservations-status','reservations-plan','reservations-reconcile'})
    from .storage_lifecycle import plan
    if args.command in {'status','inspect'}:result=ledger.snapshot()
    elif args.command=='space-status':
        from .storage_catalog import TestSpace
        if not cfg.get('storage_space'):parser.error('Runtime is not enrolled in a space')
        result=TestSpace(cfg['storage_space']).measure()
    elif args.command in {'reservations-status','reservations-plan','reservations-reconcile'}:
        from .storage_catalog import TestSpace
        from .storage_reservations import status,reconcile
        if not cfg.get('storage_space'):parser.error('Runtime is not explicitly enrolled in a space')
        space=TestSpace(cfg['storage_space'])
        row=next((r for r in space.rows() if r['id']==cfg['test_session_id']),None)
        if not row:parser.error('Runtime has no explicit catalog enrollment')
        enrolled,_=space.configuration(row)
        if enrolled!=cfg:parser.error('Explicit runtime differs from enrolled configuration')
        if args.command=='reservations-status':result=status(space)
        else:
            if args.command=='reservations-reconcile' and not args.apply:parser.error('Reconciliation requires --apply')
            result=reconcile(space,apply=args.command=='reservations-reconcile')
    elif args.command=='upload-gc':
        from .upload_gc import reconcile
        result=reconcile(cfg,apply=args.apply)
    elif args.command=='restore-db':
        from .test_session import TestSession
        result=TestSession(cfg).restore_database(purpose=args.purpose)
    elif args.command=='reconcile-restore':
        if not args.operation:parser.error('A registered restore operation is required')
        from .test_session import TestSession
        result=TestSession(cfg).reconcile_restore(args.operation)
    elif args.command in {'pin-operation','unpin-operation'}:
        if not args.operation or (args.command=='pin-operation' and not args.reason):parser.error('Operation and explicit pin reason required')
        with ledger.lock():
            result=ledger.get_operation(args.operation)
            if result.get('version')!='restore-v2':parser.error('Only current restore operations support these pins')
            result['pin']=args.reason if args.command=='pin-operation' else None
            ledger.operation(args.operation,'restore',result)
    elif args.command=='plan':
        if not args.dry_run:parser.error('plan requires --dry-run')
        result=plan(cfg)
    elif args.command=='apply':
        if not args.plan:parser.error('apply requires a persisted --plan ID')
        result=apply(cfg,args.plan)
    elif args.command=='recover':
        from .test_session import TestSession
        state=ledger.session['state']
        if state in {'creating','creation_interrupted'}:result=TestSession(cfg).reconcile_creation()
        elif state=='db_eviction_pending':result=TestSession(cfg).reconcile_database_eviction()
        elif state=='blocked' and (ledger.home/'database-before-stop.json').is_file():result=TestSession(cfg).resume_closed_maintenance()
        else:result=recover(cfg)
    elif args.command in {'pin','unpin'}:
        if not args.resource or (args.command=='pin' and not args.reason):parser.error('Resource and pin reason required')
        ledger.pin(args.resource,args.reason if args.command=='pin' else None);result={'status':'recorded'}
    else:
        if not args.archive or not args.new_target:parser.error('restore requires archive ID and a new registered relative target')
        if not (len(args.archive)==32 and all(c in '0123456789abcdef' for c in args.archive)):
            parser.error('Invalid archive ID')
        target=bounded_path(ledger.root,args.new_target)
        with ledger.lock():
            archive=ledger.home/'archives'/(args.archive+'.tar.gz')
            owners=[r for r in ledger.resources() if r['archive_id']==args.archive and r['relative_path'] is not None]
            if len(owners)!=1:raise StorageError('STORAGE_UNKNOWN','Archive is not registered in this session')
            receipt=json.loads(archive.with_suffix('.verification.json').read_text())
            if sha(archive)!=receipt['sha256']:raise StorageError('ARCHIVE_CHANGED','Recovery archive identity changed')
            from .storage_archive import verify
            verify(archive,expected=receipt['manifest'])
            ledger.journal('restore_intent',owners[0]['id'],target=args.new_target)
            restore(archive,target)
            identity=ledger.register(owners[0]['kind'],args.new_target,metadata={'restored_from':args.archive})
            ledger.state(identity,'restored')
            result={'status':'restored','resource_id':identity}
    print(json.dumps(result,indent=2,default=str))


if __name__=='__main__':main()
