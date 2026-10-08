"""Host ownership receipts and narrowly scoped sandbox recovery.

This module is not a background watchdog. The worker must call recovery while
holding its global session lock and before claiming any new heavy job. Executor
and worker hooks are intentionally separate from the receipt/validation logic.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from uuid import UUID, uuid4

from .store import LOCK

VERSION = "arsia-adapter-owner-v1"
PREFIX = "arsia.import."
RUN = re.compile(r"^run-([0-9a-f]{32})$")
CONTAINER = re.compile(r"^arsia-adapter-([0-9a-f]{32})$")


class OrphanRecoveryBlocked(RuntimeError):
    """An owned-looking container cannot safely be adopted or deleted."""


def stamp():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def private_json(path,value,exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    flags = os.O_WRONLY|os.O_CREAT|(os.O_EXCL if exclusive else os.O_TRUNC)|getattr(os,"O_NOFOLLOW",0)
    fd = os.open(path,flags,0o600)
    with os.fdopen(fd,"w") as handle:
        os.fchmod(handle.fileno(),0o600)
        json.dump(value,handle,sort_keys=True,indent=2,allow_nan=False)
        handle.write("\n")


def write_ownership(run_dir, *, config, job_id, attempt_id, worker_pid=None):
    """Write once before Docker launch; the receipt is never mounted inside."""
    job_id,attempt_id = str(UUID(str(job_id))),str(UUID(str(attempt_id)))
    root = Path(config["data_root"]).resolve()
    run_dir = Path(run_dir)
    match = RUN.fullmatch(run_dir.name)
    attempt = root/"attempts"/job_id/attempt_id
    if not match or run_dir != attempt/"agent"/run_dir.name or run_dir.resolve()!=run_dir:
        raise OrphanRecoveryBlocked("Sandbox ownership path is not the exact admitted job attempt")
    if not all((run_dir/name).is_dir() and not (run_dir/name).is_symlink() for name in ("input","output")):
        raise OrphanRecoveryBlocked("Sandbox ownership requires its regular input/output directories")
    receipt = {"schema":VERSION,"instance_id":config["instance_id"],"job_id":job_id,"attempt_id":attempt_id,
               "run_id":match[1],"container_name":"arsia-adapter-"+match[1],
               "attempt_work_dir":str(attempt),"input_dir":str(run_dir/"input"),"output_dir":str(run_dir/"output"),
               "created_at":stamp(),"worker_pid":worker_pid or os.getpid()}
    private_json(run_dir/"ownership.json",receipt,exclusive=True)
    return receipt


def ownership_labels(receipt):
    return {PREFIX+"adapter":receipt["container_name"], PREFIX+"instance":receipt["instance_id"],
            PREFIX+"job":receipt["job_id"],PREFIX+"attempt":receipt["attempt_id"],
            PREFIX+"run":receipt["run_id"],PREFIX+"owner-sha256":digest(receipt)}


def require_lock(conn,config):
    marker = conn.execute("SELECT instance_id FROM local_instance WHERE singleton").fetchone()
    locked = conn.execute("""SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory'
        AND pid=pg_backend_pid() AND classid=0 AND objid=%s AND objsubid=1 AND granted) AS locked""",(LOCK,)).fetchone()
    if not marker or marker["instance_id"]!=config["instance_id"] or not locked or not locked["locked"]:
        raise OrphanRecoveryBlocked("Orphan recovery requires the marked database's global worker session lock")


def inspect_owned(info,conn,config):
    """Return trusted ownership, None for unrelated containers, or refuse."""
    root = Path(config["data_root"]).resolve()
    labels = info.get("Config",{}).get("Labels") or {}
    mounts = info.get("Mounts",[])
    local_mounts = [mount for mount in mounts if mount.get("Type")=="bind"
                    and Path(mount.get("Source","/")).resolve().is_relative_to(root/"attempts")]
    # Another workspace's executor tests may use the same generic task label.
    # They are neither removed nor allowed to block this laboratory.
    if not local_mounts:
        if labels.get(PREFIX+"instance")==config["instance_id"]:
            raise OrphanRecoveryBlocked("Instance-labelled sandbox has no valid local attempt mount")
        return None
    name = info.get("Name","").removeprefix("/")
    match = CONTAINER.fullmatch(name)
    if not match or labels.get(PREFIX+"adapter")!=name:
        raise OrphanRecoveryBlocked("Local attempt container lacks its exact adapter ownership label")
    inputs = [mount for mount in mounts if mount.get("Destination")=="/input" and mount.get("Type")=="bind"]
    outputs = [mount for mount in mounts if mount.get("Destination")=="/output" and mount.get("Type")=="bind"]
    if len(inputs)!=1 or len(outputs)!=1 or len([mount for mount in mounts if mount.get("Type")=="bind"])!=2:
        raise OrphanRecoveryBlocked("Local sandbox bind mounts differ from the isolated executor contract")
    source = Path(inputs[0]["Source"])
    try:
        parts = source.relative_to(root).parts
        job_id,attempt_id = str(UUID(parts[1])),str(UUID(parts[2]))
    except (ValueError,IndexError):
        raise OrphanRecoveryBlocked("Local sandbox mount does not identify a valid attempt") from None
    expected = root/"attempts"/job_id/attempt_id/"agent"/("run-"+match[1])
    if parts != ("attempts",job_id,attempt_id,"agent","run-"+match[1],"input") or source.resolve()!=source or Path(outputs[0]["Source"])!=expected/"output" or Path(outputs[0]["Source"]).resolve()!=expected/"output" or inputs[0].get("RW") is not False or outputs[0].get("RW") is not True:
        raise OrphanRecoveryBlocked("Local sandbox paths or mount permissions do not match its run")
    attempt = conn.execute("SELECT id,job_id,work_dir,status FROM attempts WHERE id=%s AND job_id=%s",(attempt_id,job_id)).fetchone()
    if not attempt and labels.get(PREFIX+"instance")!=config["instance_id"]:
        return None  # A separate marked test DB may share the artifact root.
    if not attempt or Path(attempt["work_dir"]).resolve()!=expected.parent.parent:
        raise OrphanRecoveryBlocked("Sandbox run is not bound to an existing exact database attempt")
    path = expected/"ownership.json"
    if not path.is_file() or path.is_symlink():
        raise OrphanRecoveryBlocked("Verified local legacy sandbox has no host ownership receipt; manual scoped review is required")
    if path.stat().st_uid!=os.getuid() or path.stat().st_mode & 0o077 or path.stat().st_size>16384:
        raise OrphanRecoveryBlocked("Sandbox host ownership receipt permissions or size are invalid")
    try:
        receipt = json.loads(path.read_text())
    except (ValueError,OSError):
        raise OrphanRecoveryBlocked("Sandbox host ownership receipt is unreadable") from None
    required = {"schema":VERSION,"instance_id":config["instance_id"],"job_id":job_id,"attempt_id":attempt_id,
                "run_id":match[1],"container_name":name,"attempt_work_dir":str(expected.parent.parent),
                "input_dir":str(expected/"input"),"output_dir":str(expected/"output")}
    if any(receipt.get(key)!=value for key,value in required.items()) or any(labels.get(key)!=value for key,value in ownership_labels(receipt).items()):
        raise OrphanRecoveryBlocked("Sandbox receipt, task labels and database ownership disagree")
    execution = expected/"execution.json"
    if execution.exists() or execution.is_symlink():
        if execution.is_symlink() or execution.stat().st_size>1024**2:
            raise OrphanRecoveryBlocked("Sandbox execution audit is not a bounded regular file")
        try:
            outcome = json.loads(execution.read_text())
        except (ValueError,OSError):
            raise OrphanRecoveryBlocked("Sandbox execution audit is unreadable") from None
        if outcome.get("status") not in {None,"running","interrupted"}:
            if info.get("State",{}).get("Running"):
                raise OrphanRecoveryBlocked("A completed execution audit contradicts its still-running sandbox")
            return None
    return {"container_id":info["Id"],"container_name":name,"job_id":job_id,"attempt_id":attempt_id,
            "run_id":match[1],"ownership_sha256":digest(receipt),"run_dir":str(expected)}


def recover_owned_orphans(conn,config,docker):
    """Clean only proven incomplete runs before new work; preserve all evidence."""
    require_lock(conn,config)
    audit = {"schema":"arsia-scoped-orphan-recovery-v1","at":stamp(),"instance_id":config["instance_id"],"actions":[],"status":"checking"}
    audit_path = Path(config["data_root"])/"audits"/("orphan-recovery-"+uuid4().hex+".json")
    private_json(audit_path,audit)
    try:
        listed = docker(["ps","-aq","--filter","label="+PREFIX+"adapter"])
        if listed.returncode:
            raise OrphanRecoveryBlocked("Cannot inspect task sandbox inventory before claiming work")
        ids = listed.stdout.split()
        if len(ids)>1000 or any(not re.fullmatch(r"[0-9a-f]{12,64}",value) for value in ids):
            raise OrphanRecoveryBlocked("Task sandbox inventory exceeded its bounded identity format")
        for container_id in ids:
            inspected = docker(["inspect",container_id])
            if inspected.returncode:
                continue  # It exited and was removed before inspection.
            values = json.loads(inspected.stdout)
            if len(values)!=1 or not re.fullmatch(r"[0-9a-f]{64}",values[0].get("Id","")) or not values[0]["Id"].startswith(container_id):
                raise OrphanRecoveryBlocked("Sandbox inspection did not return one exact container")
            owned = inspect_owned(values[0],conn,config)
            if not owned:
                continue
            require_lock(conn,config)
            action = {key:value for key,value in owned.items() if key!="run_dir"}
            action.update(status="removing",at=stamp())
            audit["actions"].append(action)
            private_json(audit_path,audit)
            # A full Docker ID cannot be rebound to a newly created container.
            removed = docker(["rm","-f",owned["container_id"]])
            if removed.returncode:
                action["status"]="removal_failed"
                raise OrphanRecoveryBlocked("Owned orphan cleanup failed; refusing new heavy work")
            remaining = docker(["inspect",owned["container_id"]])
            if remaining.returncode==0:
                action["status"]="still_present"
                raise OrphanRecoveryBlocked("Owned orphan remained after cleanup; refusing new heavy work")
            action.update(status="removed",finished_at=stamp())
            private_json(Path(owned["run_dir"])/"orphan-recovery.json",action,exclusive=True)
        audit["status"]="passed"
        return audit
    except Exception as exc:
        audit.update(status="blocked",error_type=type(exc).__name__,message=str(exc)[:500])
        raise
    finally:
        private_json(audit_path,audit)
