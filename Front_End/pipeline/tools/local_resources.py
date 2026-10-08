"""Read-only sampled measurements of this lab, not a Linux sizing guarantee."""
import json
import platform
import re
import shutil
import subprocess
import threading
import time


def command(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=10, check=True).stdout.strip()


def byte_size(value):
    match = re.fullmatch(r"([0-9.]+)\s*([KMGT]?i?B)", value.strip())
    units = {"B":1,"kB":1000,"KB":1000,"MB":1000**2,"GB":1000**3,
             "KiB":1024,"MiB":1024**2,"GiB":1024**3,"TiB":1024**4}
    return round(float(match[1])*units[match[2]]) if match else None


class ResourceSampler:
    def __init__(self, config):
        self.config = config
        self.samples = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def run(self):
        while not self.stop.is_set():
            sample = {"time":time.time(), "errors":[]}
            for role in ("worker", "api"):
                try:
                    values = command("ps", "-p", str(self.config["processes"][role]), "-o", "rss=,%cpu=").split()
                    sample[role] = {"rss_bytes":int(values[0])*1024,"cpu_percent":float(values[1])}
                except Exception as exc:
                    sample["errors"].append(role+":"+type(exc).__name__)
            try:
                stat = json.loads(command("docker", "stats", "--no-stream", "--format", "{{json .}}", self.config["container"]))
                sample["postgres_container"] = {"memory_bytes":byte_size(stat["MemUsage"].split("/")[0]),
                    "memory_display":stat["MemUsage"],"cpu_percent":float(stat["CPUPerc"].strip("%"))}
            except Exception as exc:
                sample["errors"].append("docker:"+type(exc).__name__)
            try:
                disk = shutil.disk_usage(self.config["data_root"])
                sample["host_disk_free_bytes"] = disk.free
                if platform.system() == "Darwin":
                    raw = command("vm_stat")
                    page_size = int(re.search(r"page size of (\d+) bytes",raw)[1])
                    sample["host_memory"] = {"physical_bytes":int(command("sysctl","-n","hw.memsize")),
                        "page_size":page_size,"page_counters":{k:int(v) for k,v in re.findall(r"^([^:\n]+):\s*(\d+)\.",raw,re.M)}}
            except Exception as exc:
                sample["errors"].append("host:"+type(exc).__name__)
            self.samples.append(sample)
            self.stop.wait(2)

    def finish(self):
        self.stop.set()
        self.thread.join(timeout=15)
        def peak(role,key):
            return max((s.get(role,{}).get(key) or 0 for s in self.samples),default=None)
        return {"platform":platform.platform(),"sample_count":len(self.samples),
            "method":"Read-only ps RSS and docker stats sampled approximately every 2–4 seconds; observed maxima, not ru_maxrss or a guaranteed peak. Host page counters include all other work. Docker container memory is measured separately and is not process RSS.",
            "worker_rss_observed_max_bytes":peak("worker","rss_bytes"),
            "api_rss_observed_max_bytes":peak("api","rss_bytes"),
            "postgres_container_memory_observed_max_bytes":peak("postgres_container","memory_bytes"),
            "samples":self.samples}
