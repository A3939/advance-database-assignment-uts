"""Opt-in failure injection for ONLY this workspace's dedicated local worker.

Uploads the pinned NSW originals to the loopback test API. Verifies active
cancellation and actual process loss without replacing the current publication.
Never kills a process unless its PID, command, cwd and active job all match.
"""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from uuid import uuid4

import verify_full_volume as verifier
from arsia_pipeline.config import read_config
from arsia_pipeline.dev import owned_pid


def state(job_id):
    return verifier.api("GET","/jobs/"+job_id)


def until(job_id,predicate,timeout=180):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        job=state(job_id)
        if predicate(job):return job
        if job["status"] in verifier.TERMINAL:
            raise RuntimeError("The owned job ended before the requested failure injection")
        time.sleep(.2)
    raise RuntimeError("Owned local job timed out")


def uploaded(label):
    job=verifier.api("POST","/jobs",{"label":label,"source_hint":"NSW","request_id":str(uuid4())})
    for name in verifier.SOURCE_FILES["nsw"]:
        verifier.api("PUT",f"/jobs/{job['id']}/files?filename={name}",file=verifier.PROJECT.parent/"Resources/source/raw"/name)
    verifier.api("POST",f"/jobs/{job['id']}/submit",{})
    return job["id"]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-local-worker-interruption",action="store_true",required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    verifier.VIA_WEBSITE=True
    api=verifier.api
    health=api("GET","/health")
    if health["worker"]["active_job_id"]:
        raise RuntimeError("Another local job is active; do not interrupt it")
    catalog=api("GET","/catalog")
    if "official_nsw" not in {s["source_id"] for s in catalog["sources"]}:
        raise RuntimeError("Run full-volume publication verification first")
    receipt={"mode":"local-test","checks":[],"before_release_id":catalog["release_id"]}
    def check(name,passed):
        receipt["checks"].append({"check":name,"passed":bool(passed)})
        print(json.dumps(receipt["checks"][-1]),flush=True)
        if not passed:raise RuntimeError(name)
    cancelled=uploaded("Full-volume active cancellation regression")
    until(cancelled,lambda j:j["status"]=="processing" and "Validated" in j["message"])
    api("POST",f"/jobs/{cancelled}/cancel",{})
    job=until(cancelled,lambda j:j["status"] in verifier.TERMINAL)
    check("actual_native_processing_cancelled",job["status"]=="cancelled")
    check("cancellation_keeps_release",api("GET","/catalog")["release_id"]==catalog["release_id"])
    receipt["cancelled_job_id"]=cancelled
    recovering=uploaded("Full-volume real worker loss and recovery regression")
    until(recovering,lambda j:j["status"]=="processing" and "Validated" in j["message"])
    config=read_config();pid=config["processes"]["worker"]
    check("worker_pid_command_cwd_owned",owned_pid(pid,"worker"))
    check("worker_active_job_owned",api("GET","/health")["worker"]["active_job_id"]==recovering)
    try:
        os.kill(pid,signal.SIGKILL)
    finally:
        # up retains the owned database and existing API; it relaunches only
        # the dead worker. Do this even if the caller interrupts the verifier.
        time.sleep(.3)
        subprocess.run([sys.executable,"-m","arsia_pipeline.dev","up"],cwd=verifier.PROJECT/"pipeline",check=True,capture_output=True,text=True)
    job=until(recovering,lambda j:j["status"] in verifier.TERMINAL)
    evidence=api("GET",f"/jobs/{recovering}/evidence")
    check("recovery_completes_same_input_without_duplicate_publication",job["status"]=="no_change")
    check("two_attempts_with_interrupted_evidence",[a["status"] for a in evidence["attempts"]]==["interrupted","no_change"])
    check("recovery_keeps_all_published_sources",api("GET","/catalog")["release_id"]==catalog["release_id"])
    check("recovered_worker_alive",api("GET","/health")["worker"]["alive"])
    receipt.update(recovery_job_id=recovering,attempts=evidence["attempts"],passed=True)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(receipt,indent=2)+"\n")


if __name__=="__main__":main()
