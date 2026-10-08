"""Operate the existing local ARSIA installation without migrations or task recovery.

No database/container is created, no model request is sent, and no build is run.
Unknown ownership, runnable historical jobs and unfinished attempts fail closed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "pipeline"))
ORIGIN = "http://127.0.0.1:3100"


class ServiceError(RuntimeError):
    pass


def command(*args, required=True):
    result = subprocess.run(args, capture_output=True, text=True)
    if required and result.returncode:
        # Never forward subprocess output that might contain connection details.
        raise ServiceError(f"{Path(args[0]).name} failed; inspect local service logs.")
    return result


def runtime():
    if os.environ.get("ARSIA_IMPORT_CONFIG"):
        raise ServiceError("This launcher accepts only the canonical runtime, not an isolated test binding.")
    from arsia_pipeline import dev
    cfg = dev.read_config()
    expected = "arsia-imports-" + hashlib.sha256(str(PROJECT).encode()).hexdigest()[:10]
    if cfg.get("container") != expected or cfg.get("volume") != expected + "-pgdata":
        raise ServiceError("Configured container does not belong to this project.")
    if Path(cfg["data_root"]).resolve() != PROJECT / "artifacts/imports-local":
        raise ServiceError("Configured data root differs from this project.")
    return dev, cfg


def verify_container(cfg, info, volume):
    marker = cfg["instance_id"]
    if (info.get("Config", {}).get("Labels") or {}).get("arsia.imports.instance") != marker:
        raise ServiceError("Container ownership mismatch.")
    if (volume.get("Labels") or {}).get("arsia.imports.instance") != marker:
        raise ServiceError("Volume ownership mismatch.")
    if not any(m.get("Name") == cfg["volume"] and m.get("Destination") == "/var/lib/postgresql/data" for m in info.get("Mounts", [])):
        raise ServiceError("Database volume mount mismatch.")


def database_ready(dev, cfg, start=False):
    if command("docker", "info", required=False).returncode:
        raise ServiceError("Docker Desktop is stopped. Start Docker Desktop, then run npm run services:start.")
    info = json.loads(command("docker", "inspect", cfg["container"]).stdout)[0]
    volume = json.loads(command("docker", "volume", "inspect", cfg["volume"]).stdout)[0]
    verify_container(cfg, info, volume)
    if not info["State"]["Running"]:
        if not start:
            raise ServiceError("The owned database container is stopped.")
        command("docker", "start", cfg["container"])
        info = json.loads(command("docker", "inspect", cfg["container"]).stdout)[0]
    bindings = info["NetworkSettings"]["Ports"].get("5432/tcp") or []
    if len(bindings) != 1 or bindings[0]["HostIp"] != "127.0.0.1":
        raise ServiceError("Database must have exactly one loopback binding.")
    from psycopg.conninfo import make_conninfo
    from arsia_pipeline import store
    updated = {**cfg, "dsn": make_conninfo(cfg["dsn"], host="127.0.0.1", port=bindings[0]["HostPort"])}
    # Wait only for the container just admitted above; this does not initialize it.
    for _ in range(40 if start else 1):
        if command("docker", "exec", cfg["container"], "pg_isready", "-U", "arsia_imports", "-d", cfg["database"], required=False).returncode == 0:
            break
        time.sleep(.25)
    with store.connect(updated) as conn, conn.transaction():
        conn.execute("SET TRANSACTION READ ONLY")
        from arsia_pipeline.migrations import MIGRATIONS
        applied = {r["version"]: r["sha256"] for r in conn.execute("SELECT version,sha256 FROM schema_migrations")}
        if applied != {v: hashlib.sha256(sql.encode()).hexdigest() for v, sql in MIGRATIONS}:
            raise ServiceError("Database schema differs from this code; automatic migration is prohibited.")
    if start and updated["dsn"] != cfg["dsn"]:
        dev.save(updated)
    return updated


def require_quiet_database(cfg):
    from arsia_pipeline import store
    with store.connect(cfg) as conn, conn.transaction():
        conn.execute("SET TRANSACTION READ ONLY")
        pending = conn.execute("SELECT id FROM jobs WHERE status=ANY(%s)", (["queued", *store.ACTIVE],)).fetchall()
        unfinished = conn.execute("SELECT id FROM attempts WHERE finished_at IS NULL").fetchall()
    if pending or unfinished:
        raise ServiceError("Runnable or unfinished imports exist; no worker restart/recovery is authorized by this launcher.")


def require_quiet_studio():
    path = PROJECT / "artifacts/studio/research.sqlite"
    if not path.exists():
        return
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    try:
        leases = db.execute("SELECT count(*) FROM leases").fetchone()[0]
        running = any(r.get("status") == "running" for (doc,) in db.execute("SELECT doc FROM studies") for r in json.loads(doc).get("runs", []))
        if leases or running:
            raise ServiceError("Studio has an active run or lease; finish it before stopping services.")
    finally:
        db.close()


def web_pid():
    found = command("lsof", "-nP", "-iTCP:3100", "-sTCP:LISTEN", "-t", required=False)
    pids = set(found.stdout.split())
    if not pids:
        return None
    if len(pids) != 1:
        raise ServiceError("Port 3100 has ambiguous ownership.")
    pid = int(next(iter(pids)))
    cwd = command("lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn").stdout.splitlines()
    cmd = command("ps", "-p", str(pid), "-o", "command=").stdout
    if "n" + str(PROJECT) not in cwd or "next-server" not in cmd:
        raise ServiceError("Port 3100 belongs to another application; it will not be stopped or replaced.")
    return pid


def get(path):
    try:
        req = urllib.request.Request(ORIGIN + path, headers={"Origin": ORIGIN})
        with urllib.request.urlopen(req, timeout=5) as response:
            return {"http": response.status, "body": json.load(response)}
    except (OSError, ValueError):
        return {"http": None, "body": None}


def runtime_checks():
    result = {"import_executor": False, "analysis_sandbox": False, "agent_runtime": False}
    try:
        _, cfg = runtime()
        result["import_executor"] = command("docker", "image", "inspect", cfg["executor_image"], required=False).returncode == 0
        inspected = command("docker", "image", "inspect", os.environ.get("ARSIA_ANALYSIS_IMAGE", "arsia-analysis:2"), required=False)
        if inspected.returncode == 0:
            config = json.loads(inspected.stdout)[0]["Config"]
            result["analysis_sandbox"] = (config.get("Labels") or {}).get("arsia.analysis.wall_seconds") == "35" and config.get("Entrypoint") == ["/usr/bin/timeout", "--signal=KILL", "35s", "python", "-I", "/opt/arsia/runner.py"]
        if cfg.get("agent_engine") == "codex":
            from arsia_pipeline.codex_sandbox import check_runtime
            check_runtime()
        result["agent_runtime"] = True
    except Exception:
        pass  # Status is diagnostic only; report unavailable without leaking private config.
    return result


def status():
    health = get("/api/imports/health")
    catalog = get("/api/data/catalog")
    studio = get("/api/studio/capabilities")
    h, c, s = (r["body"] or {} for r in [health, catalog, studio])
    result = {"url": ORIGIN, "web_pid": web_pid(), "imports_api": health["http"] == 200,
              "worker_alive": h.get("worker", {}).get("alive", False), "active_import": h.get("worker", {}).get("active_job_id"),
              "catalog_connected": catalog["http"] == 200, "release": c.get("releaseId"),
              "studio_api": studio["http"] == 200, "ai_configured": s.get("assistant", {}).get("available", False),
              "ai_live_check": "not performed by status", "scope": "local single-user installation"}
    result.update(runtime_checks())
    result["services_ready"] = all(result[k] for k in ["web_pid", "imports_api", "worker_alive", "catalog_connected", "studio_api", "ai_configured", "import_executor", "analysis_sandbox", "agent_runtime"])
    return result


def start():
    pid = web_pid()  # Reject an unrelated listener before touching any service.
    if not pid and not (PROJECT / ".next/BUILD_ID").is_file():
        raise ServiceError("No production build. Run npm run build before npm run services:start.")
    dev, cfg = runtime()
    cfg = database_ready(dev, cfg, start=True)
    checks = runtime_checks()
    if not all(checks.values()):
        raise ServiceError("Runtime dependencies unavailable: " + ", ".join(k for k, ready in checks.items() if not ready) + ". For the analysis sandbox, run npm run sandbox:build.")
    worker_live = dev.owned_pid(cfg.get("processes", {}).get("worker", 0), "worker")
    if not worker_live:
        require_quiet_database(cfg)
    dev.launch(cfg, "api")
    dev.launch(cfg, "worker")
    if not pid:
        path = PROJECT / "artifacts/local-services"
        path.mkdir(exist_ok=True, mode=0o700)
        with (path / "web.log").open("ab") as output:
            subprocess.Popen(["npm", "run", "start"], cwd=PROJECT, stdin=subprocess.DEVNULL,
                             stdout=output, stderr=output, start_new_session=True)
    for _ in range(30):
        result = status()
        if result["services_ready"]:
            return result
        time.sleep(.5)
    raise ServiceError("Services did not become ready. Run npm run services:status; existing logs/data are retained.")


def stop():
    pid = web_pid()
    dev, cfg = runtime()
    cfg = database_ready(dev, cfg)
    require_quiet_database(cfg)
    require_quiet_studio()
    dev.stop_processes(cfg)
    if pid:
        # Recheck ownership immediately before sending a targeted signal.
        if web_pid() != pid:
            raise ServiceError("Web process changed; no signal sent.")
        os.kill(pid, signal.SIGTERM)
    # Keep the DB/engine available to read-only tools and other apps. Never stop Docker Desktop.
    return {"web_stopped": bool(pid), "api_worker_stopped": True, "database_retained_running": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop", "status"])
    args = parser.parse_args()
    try:
        result = {"start": start, "stop": stop, "status": status}[args.action]()
        print(json.dumps(result, indent=2))
        if result.get("services_ready") is False:
            return 1
    except Exception as exc:
        message = str(exc) if isinstance(exc, ServiceError) else "Local service verification failed (" + type(exc).__name__ + "); private details were not printed."
        print(json.dumps({"error": message}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
