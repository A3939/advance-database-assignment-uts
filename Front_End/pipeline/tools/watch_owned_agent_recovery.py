"""Opt-in SIGKILL/recovery watcher for one explicitly designated local SA job.

Default is a dry description: no DB query, Docker call, model call or mutation.
This does not submit/retry jobs, inject adapter sleeps, or change code/QA.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from uuid import UUID

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from arsia_pipeline import store
from arsia_pipeline.config import ROOT,PROJECT,read_config
from arsia_pipeline.dev import owned_pid
from arsia_pipeline.isolated_executor import docker
from arsia_pipeline.scoped_orphans import inspect_owned,private_json

TARGET="8056ec76-da6c-4bfd-afc4-3b7681e426ec"
EXPECTED_ATTEMPT=2
TERMINAL={"succeeded","no_change","failed","needs_input","cancelled"}


def now():return datetime.now(timezone.utc).isoformat()


def sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),default=str).encode()).hexdigest()


def snapshot(config):
    with store.connect(config) as conn:
        conn.execute("SET default_transaction_read_only=on")
        job=conn.execute("SELECT id,status,attempt,source_id,batch_id,release_id FROM jobs WHERE id=%s",(TARGET,)).fetchone()
        if not job:raise RuntimeError("The designated job does not exist in the verified local instance")
        others=conn.execute("SELECT id FROM jobs WHERE id<>%s AND status=ANY(%s)",(TARGET,list(store.ACTIVE)+["queued"])).fetchall()
        session=conn.execute("SELECT id,model_calls,tool_calls,correction_count,checkpoint FROM agent_sessions WHERE job_id=%s",(TARGET,)).fetchone()
        worker=conn.execute("SELECT active_job_id FROM worker_state WHERE singleton").fetchone()
        release=conn.execute("SELECT r.id,r.sources FROM current_release c JOIN releases r ON r.id=c.release_id").fetchone()
    return job,session,worker,release,others


def process_start(pid):
    value=subprocess.run(["ps","-p",str(pid),"-o","lstart="],capture_output=True,text=True,check=False)
    if value.returncode or not value.stdout.strip():raise RuntimeError("Owned worker start identity became unavailable")
    return value.stdout.strip()


def model_counters(session):
    return {key:session[key] for key in ("model_calls","tool_calls","correction_count")}


def wait_trigger(config,deadline):
    while time.monotonic()<deadline:
        job,session,worker,release,others=snapshot(config)
        if others:raise RuntimeError("Another queued/active job exists; refusing any worker interruption")
        if job["attempt"]>EXPECTED_ATTEMPT or (job["attempt"]==EXPECTED_ATTEMPT and job["status"] in TERMINAL):
            raise RuntimeError("The designated attempt ended before a verified sandbox trigger; no injection performed")
        # It is safe to start watching before the operator submits the retry.
        if job["attempt"]==EXPECTED_ATTEMPT and worker and str(worker["active_job_id"])==TARGET:
            listed=docker(["ps","-q","--filter","label=arsia.import.job="+TARGET,
                           "--filter","label=arsia.import.instance="+config["instance_id"]])
            if listed.returncode:raise RuntimeError("Cannot inspect the designated sandbox inventory")
            ids=listed.stdout.split()
            if len(ids)>1:raise RuntimeError("Multiple designated running sandboxes violate the single-heavy-job condition")
            if ids:
                inspected=docker(["inspect",ids[0]])
                if inspected.returncode:
                    continue
                info=json.loads(inspected.stdout)[0]
                if not info.get("State",{}).get("Running"):
                    continue
                with store.connect(config) as conn:
                    conn.execute("SET default_transaction_read_only=on")
                    owned=inspect_owned(info,conn,config)
                if not owned:raise RuntimeError("The designated sandbox has no verified host ownership")
                fresh=read_config()
                pid=fresh.get("processes",{}).get("worker")
                receipt=json.loads((Path(owned["run_dir"])/"ownership.json").read_text())
                if fresh["instance_id"]!=config["instance_id"] or not pid or receipt.get("worker_pid")!=pid or not owned_pid(pid,"worker"):
                    raise RuntimeError("Worker PID, command, cwd, receipt or instance ownership changed")
                start=process_start(pid)
                return owned,pid,start,job,session,release
        time.sleep(.1)
    raise RuntimeError("No verified running sandbox appeared before the watcher deadline; no injection performed")


def validate_completion(config,session_before,release_before,deadline):
    while time.monotonic()<deadline:
        job,session,worker,release,others=snapshot(config)
        if others:raise RuntimeError("Another job became active during the isolated recovery acceptance")
        if job["status"] in TERMINAL and job["attempt"]>=EXPECTED_ATTEMPT+1:
            break
        time.sleep(.5)
    else:raise RuntimeError("Recovered job did not reach a terminal result within the acceptance deadline")
    with store.connect(config) as conn:
        conn.execute("SET default_transaction_read_only=on")
        attempts=conn.execute("SELECT id,number,status FROM attempts WHERE job_id=%s ORDER BY number",(TARGET,)).fetchall()
        steps=conn.execute("SELECT s.kind,s.name,s.status,s.arguments,s.result,a.number FROM agent_steps s JOIN attempts a ON a.id=s.attempt_id WHERE a.job_id=%s ORDER BY s.id",(TARGET,)).fetchall()
        batches=conn.execute("SELECT count(*) AS n FROM batches WHERE job_id=%s",(TARGET,)).fetchone()["n"]
    latest=[row for row in steps if row["number"]==EXPECTED_ATTEMPT+1 and row["status"]=="succeeded"]
    modes={row["arguments"].get("mode","sample") for row in latest if row["name"] in {"run_adapter","run_python"} and row["result"].get("run_id")}
    admissions={row["result"].get("status") for row in latest if row["name"]=="validate_candidate"}
    mapping=release["sources"] if release else {}
    oldmapping=release_before["sources"] if release_before else {}
    other_sources_unchanged=all(mapping.get(source)==batch for source,batch in oldmapping.items() if source!=job.get("source_id"))
    checks={"same_agent_session":str(session["id"])==str(session_before["id"]),
            "counters_preserved":all(session[key]>=session_before[key] for key in model_counters(session_before)),
            "interrupted_attempt_recorded":any(row["number"]==EXPECTED_ATTEMPT and row["status"]=="interrupted" for row in attempts),
            "replacement_attempt_recorded":any(row["number"]==EXPECTED_ATTEMPT+1 for row in attempts),
            "fresh_sample_and_full_runs":{"sample","full"}<=modes,
            "fresh_independent_sample_and_full_qa":{"sample_only","validated"}<=admissions,
            "other_sources_unchanged":other_sources_unchanged,"at_most_one_job_batch":batches<=1,
            "completed_publication":job["status"] in {"succeeded","no_change"}}
    return {"checks":checks,"passed":all(checks.values()),"terminal_status":job["status"],
            "session_id":str(session["id"]),"counters_after":model_counters(session),
            "attempts":[{key:str(value) if key=="id" else value for key,value in row.items()} for row in attempts],
            "release_after":{"id":str(release["id"]),"sources":mapping} if release else None,
            "model_policies":sorted({row["result"]["model_policy_sha256"] for row in steps if row["kind"]=="model" and row["result"] and row["result"].get("model_policy_sha256")})}


def main():
    global TARGET,EXPECTED_ATTEMPT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-owned-agent-interruption",action="store_true")
    parser.add_argument("--hold-owned-container",action="store_true",
        help="After ownership verification, briefly pause that exact sandbox to make the SIGKILL trigger deterministic; unpause if no signal was injected")
    parser.add_argument("--job-id",type=UUID,default=UUID(TARGET))
    parser.add_argument("--expected-attempt",type=int,default=EXPECTED_ATTEMPT)
    parser.add_argument("--watch-seconds",type=int,default=900)
    parser.add_argument("--completion-seconds",type=int,default=1800)
    parser.add_argument("--output",type=Path)
    args=parser.parse_args()
    TARGET,EXPECTED_ATTEMPT=str(args.job_id),args.expected_attempt
    if EXPECTED_ATTEMPT<1:raise ValueError("Expected attempt must be positive")
    if args.output is None:args.output=ROOT/"audits"/("real-agent-worker-recovery-"+TARGET+"-attempt-"+str(EXPECTED_ATTEMPT)+".json")
    if not args.confirm_owned_agent_interruption:
        print(json.dumps({"dry_run":True,"target_job_id":TARGET,"expected_attempt":EXPECTED_ATTEMPT,"action":"Verify one owned running sandbox, SIGKILL only its owning worker, relaunch with dev up, and verify the next attempt recovery"}));return
    if not args.output.resolve().is_relative_to((ROOT/"audits").resolve()):
        raise RuntimeError("Recovery receipt must remain inside the private local audit directory")
    config=read_config()
    receipt={"schema":"arsia-real-agent-worker-recovery-v1","job_id":TARGET,"expected_attempt":EXPECTED_ATTEMPT,"started_at":now(),"injected":False,"passed":False}
    lock_path=ROOT/"audits"/("recovery-watcher-"+TARGET+".lock")
    private_json(lock_path,{"pid":os.getpid(),"at":now()},exclusive=True)
    held_id=None
    try:
        watch_deadline=time.monotonic()+args.watch_seconds
        while True:
            owned,pid,start,job,session,release=wait_trigger(config,watch_deadline)
            receipt.update(worker_pid_before=pid,worker_started_at=start,container_id=owned["container_id"],run_id=owned["run_id"],
                           ownership_sha256=owned["ownership_sha256"],session_id=str(session["id"]),counters_before=model_counters(session),
                           checkpoint_code_sha256=hashlib.sha256(session["checkpoint"].get("code","").encode()).hexdigest(),
                           checkpoint_contract_sha256=sha(session["checkpoint"].get("contract",{})),
                           release_before={"id":str(release["id"]),"sources":release["sources"]} if release else None)
            private_json(args.output,receipt)
            if args.hold_owned_container:
                # Record the exact proven ID before requesting a mutation: a
                # timed-out Docker client does not prove the pause failed.
                held_id=owned["container_id"]
                paused=docker(["pause",owned["container_id"]])
                if paused.returncode:
                    release_uninjected_hold(receipt,held_id)
                    if receipt.get("controlled_hold_release",{}).get("requires_scoped_operator_review"):
                        raise RuntimeError("Cannot confirm release of the exact controlled hold after a failed pause request")
                    held_id=None
                    receipt.setdefault("completed_candidates_skipped",[]).append({"container_id":owned["container_id"],"at":now(),"reason":"could_not_hold_verified_candidate"})
                    private_json(args.output,receipt)
                    continue
                receipt["controlled_container_hold"]={"container_id":held_id,"at":now(),
                    "reason":"Stabilize the fault-injection window after receipt/label/mount/DB/PID ownership verification; generated code is unchanged."}
                private_json(args.output,receipt)
            latest,_,worker,_,others=snapshot(config)
            if others or latest["attempt"]!=EXPECTED_ATTEMPT or not worker or str(worker["active_job_id"])!=TARGET or not owned_pid(pid,"worker") or process_start(pid)!=start:
                raise RuntimeError("Ownership or exact active attempt changed immediately before interruption")
            current_container=docker(["inspect",owned["container_id"]])
            if current_container.returncode:
                receipt.setdefault("completed_candidates_skipped",[]).append({"container_id":owned["container_id"],"at":now(),"reason":"removed_before_signal"})
                private_json(args.output,receipt)
                continue
            current_info=json.loads(current_container.stdout)[0]
            with store.connect(config) as conn:
                conn.execute("SET default_transaction_read_only=on")
                proof=inspect_owned(current_info,conn,config)
            if not current_info.get("State",{}).get("Running"):
                receipt.setdefault("completed_candidates_skipped",[]).append({"container_id":owned["container_id"],"at":now(),"reason":"finished_before_signal"})
                private_json(args.output,receipt)
                continue
            if not proof or proof["ownership_sha256"]!=owned["ownership_sha256"]:
                raise RuntimeError("The sandbox ownership no longer matches the verified candidate; no injection performed")
            receipt["sandbox_running_verified_at"]=now()
            break
        attempted=False
        try:
            attempted=True
            os.kill(pid,signal.SIGKILL)
            receipt.update(injected=True,injected_at=now())
            private_json(args.output,receipt)
        finally:
            if attempted:
                resumed=subprocess.run([sys.executable,"-m","arsia_pipeline.dev","up"],cwd=PROJECT/"pipeline",capture_output=True,text=True,check=False)
                receipt["lifecycle_up_returncode"]=resumed.returncode
                private_json(args.output,receipt)
                if resumed.returncode:raise RuntimeError("Owned lifecycle relaunch failed; private receipt preserves the interruption")
        fresh=read_config()
        receipt["worker_pid_after"]=fresh.get("processes",{}).get("worker")
        if receipt["worker_pid_after"]==pid or not owned_pid(receipt["worker_pid_after"],"worker"):
            raise RuntimeError("A distinct owned replacement worker did not start")
        deadline=time.monotonic()+15
        while time.monotonic()<deadline and docker(["inspect",owned["container_id"]]).returncode==0:
            time.sleep(.1)
        receipt["owned_orphan_reaped"]=docker(["inspect",owned["container_id"]]).returncode!=0
        if not receipt["owned_orphan_reaped"]:raise RuntimeError("Replacement worker did not reap the exact owned orphan")
        reaping=Path(owned["run_dir"])/"orphan-recovery.json"
        if not reaping.is_file():raise RuntimeError("Container absence alone does not prove scoped startup recovery; its reaping audit is missing")
        reaping_evidence=json.loads(reaping.read_text())
        if reaping_evidence.get("container_id")!=owned["container_id"] or reaping_evidence.get("status")!="removed":
            raise RuntimeError("Scoped startup recovery audit does not match the interrupted container")
        receipt["scoped_reaping_audit"]=reaping_evidence
        receipt.update(validate_completion(fresh,session,release,time.monotonic()+args.completion_seconds))
        if not receipt["passed"]:raise RuntimeError("Recovery completed without satisfying every acceptance assertion")
    except BaseException as exc:
        receipt.update(error_type=type(exc).__name__,error=str(exc)[:500])
        raise
    finally:
        release_uninjected_hold(receipt,held_id)
        receipt["finished_at"]=now()
        private_json(args.output,receipt)
        lock_path.unlink(missing_ok=True)
        print(json.dumps({"job_id":TARGET,"injected":receipt["injected"],"passed":receipt["passed"],"receipt":str(args.output)}))


def release_uninjected_hold(receipt,container_id):
    """Never leave a controlled pause behind when the signal was not sent.

    A Docker full ID is immutable; this is exactly the already proven sandbox,
    never a name lookup or an inventory-wide operation. An injected orphan is
    intentionally left to the worker's receipt-verified startup reaper.
    """
    if container_id and not receipt.get("injected"):
        try:
            resumed=docker(["unpause",container_id])
            receipt["controlled_hold_release"]={"container_id":container_id,"returncode":resumed.returncode,"at":now()}
            if resumed.returncode:
                inspected=docker(["inspect",container_id])
                released=False
                if inspected.returncode==0:
                    values=json.loads(inspected.stdout)
                    released=(len(values)==1 and values[0].get("Id")==container_id
                        and values[0].get("State",{}).get("Paused") is False)
                else:
                    # A daemon-confirmed missing exact ID is different from
                    # losing access to Docker, which leaves the outcome unknown.
                    error=getattr(inspected,"stderr","")
                    released=any(message+container_id in error for message in
                        ("No such object: ","No such container: "))
                receipt["controlled_hold_release"].update(
                    released_verified=released,requires_scoped_operator_review=not released)
        except Exception as exc:
            receipt["controlled_hold_release"]={"container_id":container_id,"error_type":type(exc).__name__,"at":now(),
                "requires_scoped_operator_review":True}


if __name__=="__main__":main()
