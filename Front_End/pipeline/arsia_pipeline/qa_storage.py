"""Trusted QA scratch lifecycle; never changes the validation decision."""
import json
from pathlib import Path

from .storage_lifecycle import Ledger, StorageError, atomic_json, now, sha


def begin(work_dir, dbpath, run):
    from .config import read_config
    # No config file is needed by stand-alone verifier unit tests.
    try:cfg=read_config()
    except StorageError:raise
    except (OSError,RuntimeError):return None
    if not cfg.get('storage_policy',{}).get('enabled') or not cfg.get('storage_features',True):return None
    ledger=Ledger(cfg)
    path=Path(dbpath)
    if not path.is_relative_to(ledger.root):raise StorageError('STORAGE_OWNER','QA work file escaped its session')
    identity=ledger.register('qa_work_db',str(path.relative_to(ledger.root)),run_id=run['run_id'])
    ledger.journal('qa_work_intent',identity,run_id=run['run_id'])
    return ledger,identity,path


def finish(token, *, result_path=None, error=None):
    if token is None:return
    ledger,identity,path=token
    # Caller has already closed ALL connections. Failure diagnosis is unique
    # per work file, so reruns cannot overwrite the only error evidence.
    try:
        ledger.refresh(identity)
        if error is not None:
            diagnostic=path.with_suffix('.diagnostic.json')
            atomic_json(diagnostic,{'status':'failed','type':type(error).__name__,
                'qa':getattr(error,'qa',None),'code':getattr(error,'code',None),'at':now()})
            ledger.register('evidence',str(diagnostic.relative_to(ledger.root)))
            ledger.state(identity,'retained',reason='unique failed QA diagnostic and work database')
            return
        if result_path is None or not Path(result_path).is_file():
            ledger.state(identity,'blocked',reason='QA result was not durably persisted');return
        # A trusted signed result survives work database reclamation.
        ledger.register('evidence',str(Path(result_path).relative_to(ledger.root)))
        with ledger.lock():
            ledger.journal('qa_work_eviction_intent',identity,result_sha256=sha(result_path))
            for candidate in [path,*[Path(str(path)+suffix) for suffix in ('-journal','-wal','-shm')]]:
                if candidate.is_symlink():raise StorageError('STORAGE_SYMLINK','Indirect QA scratch refused')
            for candidate in [path,*[Path(str(path)+suffix) for suffix in ('-journal','-wal','-shm')]]:
                candidate.unlink(missing_ok=True)
            ledger.state(identity,'reclaimed',reason='durable independent QA JSON; all work connections closed')
    except Exception as exc:
        # Maintenance faults must never trigger data processing or a QA rerun.
        try:ledger.journal('qa_maintenance_blocked',identity,code=getattr(exc,'code','QA_STORAGE_FAILED'))
        except Exception:pass  # Retain scratch if even the audit disk is unavailable.
