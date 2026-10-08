"""Opt-in local API acceptance against the existing, independently recorded oracle.

Reads the seven originals without altering them. Uploads bytes ONLY to this
workspace's private Unix socket and publishes ONLY to its isolated test DB.
Never updates the website snapshot. Reports exact integer differences, not an
adjustable tolerance. Run after freezing/restarting the processing worker.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import http.client
import json
from pathlib import Path
import socket
import sys
import time
from urllib.parse import quote
from uuid import uuid4
from local_resources import ResourceSampler

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PROJECT/'pipeline'))
CONFIG = PROJECT / "artifacts/imports-local/runtime.json"
TERMINAL = {"succeeded","no_change","failed","needs_input","cancelled"}
SOURCE_FILES = {
    "nsw":["nsw_crash_2020_2024.xlsx","nsw_traffic_unit_2020_2024.xlsx"],
    "vic":["vic_accident.csv","vic_vehicle.csv","vic_person.csv","vic_node.csv"],
    "qld":["qld_crash_locations.csv"],
}
METRICS = {"crash_count":"crash_count","fatal_crash_count":"fatal_crash_count",
           "fatalities":"fatality_count","casualties":"casualty_count"}
VIA_WEBSITE = False


class LocalConnection(http.client.HTTPConnection):
    def __init__(self):
        super().__init__("localhost", timeout=240)

    def connect(self):
        cfg=json.loads(CONFIG.read_text())
        if cfg.get("mode")!="local-test":
            raise RuntimeError("Refusing a non-local-test API")
        self.sock=socket.socket(socket.AF_UNIX)
        self.sock.settimeout(self.timeout)
        self.sock.connect(cfg["socket_path"])


def api(method,path,body=None,file=None):
    conn=http.client.HTTPConnection("127.0.0.1",3100,timeout=240) if VIA_WEBSITE else LocalConnection()
    path="/api/imports"+path if VIA_WEBSITE else path
    headers={"Origin":"http://127.0.0.1:3100"} if VIA_WEBSITE else {}
    try:
        if file:
            with file.open("rb") as stream:
                conn.request(method,path,stream,{**headers,"Content-Type":"application/octet-stream","Content-Length":str(file.stat().st_size)})
        else:
            encoded=json.dumps(body).encode() if body is not None else None
            conn.request(method,path,encoded,{**headers,"Content-Type":"application/json"})
        response=conn.getresponse(); data=json.loads(response.read())
        if response.status>=400:
            raise RuntimeError(f"Local API {response.status}: {data}")
        return data
    finally:
        conn.close()


def compare(state,result,oracle,provenance):
    source="official_"+state
    checks=[]
    def equal(label,actual,expected):
        checks.append({"check":label,"actual":actual,"expected":expected,"passed":actual==expected})
    for actual_key,expected_key in METRICS.items():
        equal("summary."+actual_key,result["summary"].get(actual_key),provenance["totals"][source][expected_key])
    equal("raw_record_count",result["summary"]["raw_record_count"],sum(i["rawCount"] for i in provenance["inputs"] if i["sourceId"]==source))
    equal("canonical_unit_count",result["summary"].get("canonical_unit_count"),provenance["totals"][source]["canonical_unit_count"])
    for suffix,key,period in [("trend","trend",lambda r:r["year"]),
                              ("monthly","monthly_trend",lambda r:(r["year"],r["month"]))]:
        rows={period(r):r for r in result.get(key,[])}
        expected_rows=oracle[f"{source}:{suffix}"]["rows"]
        equal(key+".row_count",len(rows),len(expected_rows))
        for expected in expected_rows:
            point=expected["period_year"] if suffix=="trend" else (expected["period_year"],expected["period_month"])
            actual=rows.get(point,{})
            for a,e in METRICS.items():
                equal(f"{key}.{point}.{a}",actual.get(a),expected[e])
    actual_severity={r["code"]:r["count"] for r in result["severity"]}
    expected_severity={r["severity_code"]:r["crash_count"] for r in oracle[source+":severity"]["rows"]}
    for code in sorted(actual_severity.keys() | expected_severity.keys()):
        equal("severity."+code,actual_severity.get(code,0),expected_severity.get(code,0))
    # The retained source contract lists defined categories even when unobserved;
    # the historical query returns observed groups only. Keep this distinction
    # visible rather than changing the oracle or tolerating numerical drift.
    from arsia_pipeline.native import _profile, _references
    _, definitions, _, _ = _profile(state.upper(), _references()[1])
    equal("severity.all_codes_defined",set(actual_severity).issubset({d["code"] for d in definitions}),True)
    expected_units=oracle[source+":units"]
    if state=="nsw":
        equal("units",{r["unit_type"]:r["count"] for r in result["units"]["rows"]},
              {r["unit_type_code"]:r["unit_count"] for r in expected_units["rows"]})
    else:
        equal("units.unavailable",result["units"]["status"],"unavailable")
        equal("units.no_fake_zero",result["summary"]["unit_count"],None)
    equal("qa.no_block",any(q["status"]=="block" for q in result["qa"]),False)
    equal("qa.location_limited",[q["code"] for q in result["qa"] if q["status"]=="limited"],["QA07_LOCATION"])
    return checks


def main():
    global VIA_WEBSITE
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root",type=Path,default=PROJECT.parent/"Resources/source/raw")
    parser.add_argument("--states",nargs="+",choices=list(SOURCE_FILES),default=list(SOURCE_FILES))
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--timeout",type=int,default=3600)
    parser.add_argument("--via-website",action="store_true",help="Upload/poll through the real Next.js loopback bridge on 3100")
    parser.add_argument("--measure",action="store_true",help="Sample this worker/API, its PostgreSQL container, and host memory/disk counters")
    args=parser.parse_args()
    VIA_WEBSITE=args.via_website
    provenance_path=PROJECT/"data/official/provenance.json"
    oracle_path=PROJECT/"data/official/reader-results.json"
    provenance=json.loads(provenance_path.read_text());oracle=json.loads(oracle_path.read_text())
    receipt={"mode":"local-test","started_at":datetime.now(timezone.utc).isoformat(),
             "reference_batch":provenance["batchId"],"reference_runtime":provenance["runtimeCommit"],
             "oracle_sha256":hashlib.sha256(oracle_path.read_bytes()).hexdigest(),
             "comparison":"Exact integer equality by category union; declared but unobserved severity categories are recorded separately. Oracle is never rewritten.",
             "transport":"Next.js 127.0.0.1:3100 HTTP bridge" if VIA_WEBSITE else "private Unix socket", "runs":[]}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    def save():args.output.write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+"\n")
    if not api("GET","/health")["worker"]["alive"]:
        raise RuntimeError("The isolated worker is not running")
    for state in args.states:
        before=api("GET","/catalog")
        previous={r["source_id"]:r["batch_id"] for r in before["sources"]}
        job=api("POST","/jobs",{"label":f"Full-volume {state.upper()} regression","source_hint":state.upper(),"request_id":str(uuid4())})
        print(json.dumps({"state":state,"job":job["id"],"stage":"uploading"}),flush=True)
        for name in SOURCE_FILES[state]:
            api("PUT",f"/jobs/{job['id']}/files?filename={quote(name)}",file=args.raw_root/name)
        started=time.monotonic()
        sampler=ResourceSampler(json.loads(CONFIG.read_text())) if args.measure else None
        if sampler:sampler.start()
        api("POST",f"/jobs/{job['id']}/submit",{})
        last=None
        while time.monotonic()-started<args.timeout:
            job=api("GET",f"/jobs/{job['id']}")
            current=(job["status"],job["message"])
            if current!=last:
                print(json.dumps({"state":state,"status":job["status"],"message":job["message"],"seconds":round(time.monotonic()-started,1)}),flush=True)
                last=current
            if job["status"] in TERMINAL:break
            time.sleep(3)
        run={"state":state,"job_id":job["id"],"status":job["status"],"seconds":round(time.monotonic()-started,3)}
        if sampler:run["resources"]=sampler.finish()
        if job["status"] in {"succeeded","no_change"}:
            run["checks"]=compare(state,job["result"],oracle,provenance)
            run["summary"]=job["result"]["summary"]
            expected_codes={r["severity_code"] for r in oracle["official_"+state+":severity"]["rows"]}
            run["representation_difference"]={"additional_defined_zero_categories":[r["code"] for r in job["result"]["severity"] if r["code"] not in expected_codes and r["count"]==0],
                "assessment":"Acceptable: complete source-defined categories; no changed accident or injury counts, no inferred category."}
            after=api("GET","/catalog")
            current={r["source_id"]:r["batch_id"] for r in after["sources"]}
            run["other_sources_preserved"]=all(current.get(k)==v for k,v in previous.items() if k!="official_"+state)
            run["passed"]=all(c["passed"] for c in run["checks"]) and run["other_sources_preserved"]
            print(json.dumps({"state":state,"passed":run["passed"],"checks":len(run["checks"]),"differences":[c for c in run["checks"] if not c["passed"]]}),flush=True)
        else:
            run.update(passed=False,error=job.get("error"),qa=job.get("qa"),questions=job.get("questions"))
            print(json.dumps(run),flush=True)
        receipt["runs"].append(run);save()
    receipt["finished_at"]=datetime.now(timezone.utc).isoformat()
    receipt["passed"]=all(r["passed"] for r in receipt["runs"])
    receipt["oracle_unchanged"]=hashlib.sha256(oracle_path.read_bytes()).hexdigest()==receipt["oracle_sha256"]
    save()
    raise SystemExit(0 if receipt["passed"] and receipt["oracle_unchanged"] else 1)


if __name__=="__main__":main()
