"""Manage ONLY this workspace's isolated local-test container and processes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import time
from uuid import uuid4

from psycopg.conninfo import make_conninfo

from .config import CONFIG, PROJECT, ROOT, read_config
from . import store

IMAGE = "sha256:efedf3595f1d6f415c08568ba171029bf54052e754cc9f030e3f2412b21f3d67"
KEY = hashlib.sha256(str(PROJECT.resolve()).encode()).hexdigest()[:10]
NAME = "arsia-imports-" + KEY


def command(*args, check=True):
    result = subprocess.run(args, capture_output=True, text=True)
    if check and result.returncode:
        # Do not echo commands or private config; Docker errors have no secrets.
        raise RuntimeError(result.stderr.strip()[:1200] or "Command failed")
    return result


def save(config):
    if os.environ.get("ARSIA_IMPORT_CONFIG"):
        raise RuntimeError("The lifecycle manager cannot write live runtime from an alternate test configuration")
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(ROOT, 0o700)
    temporary = CONFIG.with_suffix(".tmp")
    fd = os.open(temporary, os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(config, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, CONFIG)
    os.chmod(CONFIG, 0o600)


def inspect_container():
    value = command("docker", "inspect", NAME, check=False)
    return json.loads(value.stdout)[0] if value.returncode == 0 else None


def ensure_database():
    if CONFIG.exists():
        cfg = read_config()
    else:
        if inspect_container() is not None or command("docker", "volume", "inspect", NAME + "-pgdata", check=False).returncode == 0:
            raise RuntimeError("An unowned laboratory container/volume exists; refusing to adopt or overwrite it")
        cfg = {"mode": "local-test", "instance_id": uuid4().hex, "database": "arsia_imports_" + KEY,
               "data_root": str(ROOT), "container": NAME, "volume": NAME + "-pgdata",
               "socket_path": str(Path("/tmp") / NAME / "api.sock"), "processes": {}}
        password = secrets.token_urlsafe(36)
        cfg["database_password"] = password
        save(cfg)
    if not cfg.get("agent_gateway_token"):
        cfg["agent_gateway_token"] = secrets.token_urlsafe(48)
        save(cfg)
    container = inspect_container()
    if container:
        if container["Config"]["Labels"].get("arsia.imports.instance") != cfg["instance_id"]:
            raise RuntimeError("Container ownership marker mismatch; no action taken")
        if not container["State"]["Running"]:
            command("docker", "start", NAME)
    else:
        command("docker", "image", "inspect", IMAGE)
        existing_volume = command("docker", "volume", "inspect", cfg["volume"], check=False)
        if existing_volume.returncode == 0:
            labels = json.loads(existing_volume.stdout)[0].get("Labels") or {}
            if labels.get("arsia.imports.instance") != cfg["instance_id"]:
                raise RuntimeError("Volume ownership marker mismatch; no action taken")
        else:
            command("docker", "volume", "create", "--label", "arsia.imports.instance=" + cfg["instance_id"], cfg["volume"])
        credentials = ROOT / "postgres.credentials"
        fd = os.open(credentials, os.O_WRONLY|os.O_CREAT|os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(f"POSTGRES_USER=arsia_imports\nPOSTGRES_DB={cfg['database']}\nPOSTGRES_PASSWORD={cfg['database_password']}\n")
        command("docker", "run", "-d", "--name", NAME,
                "--label", "arsia.imports.instance=" + cfg["instance_id"],
                "--env-file", str(credentials), "--publish", "127.0.0.1::5432",
                "--mount", "type=volume,source="+cfg["volume"]+",target=/var/lib/postgresql/data",
                "--memory", "1536m", "--cpus", "1.5", "--restart", "unless-stopped",
                "--log-opt", "max-size=10m", "--log-opt", "max-file=3", IMAGE,
                "postgres", "-c", "timezone=UTC", "-c", "shared_buffers=128MB")
    container = inspect_container()
    port = container["NetworkSettings"]["Ports"]["5432/tcp"][0]["HostPort"]
    cfg["dsn"] = make_conninfo(host="127.0.0.1", port=port, dbname=cfg["database"],
                               user="arsia_imports", password=cfg["database_password"], connect_timeout=5)
    save(cfg)
    for _ in range(60):
        ready = command("docker", "exec", NAME, "pg_isready", "-U", "arsia_imports", "-d", cfg["database"], check=False)
        if ready.returncode == 0:
            break
        time.sleep(0.5)
    else:
        raise RuntimeError("Isolated PostgreSQL did not become ready")
    store.initialize(cfg)
    return cfg


def owned_pid(pid, role):
    result = command("ps", "-p", str(pid), "-o", "command=", check=False)
    expected = "arsia_pipeline.worker" if role == "worker" else "arsia_pipeline.dev serve"
    if result.returncode != 0 or expected not in result.stdout:
        return False
    if sys.platform == "linux":
        try:
            return Path(f"/proc/{pid}/cwd").resolve() == PROJECT / "pipeline"
        except OSError:
            return False
    cwd = command("lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn", check=False)
    return "n" + str(PROJECT / "pipeline") in cwd.stdout.splitlines()


def launch(cfg, role):
    previous = cfg.get("processes", {}).get(role)
    if previous and owned_pid(previous, role):
        return
    module = "arsia_pipeline.worker" if role == "worker" else "arsia_pipeline.dev"
    args = [str(PROJECT / "pipeline/.venv/bin/python"), "-m", module] + ([] if role == "worker" else ["serve"])
    log = ROOT / (role + ".log")
    fd = os.open(log, os.O_WRONLY|os.O_CREAT|os.O_APPEND, 0o600)
    with os.fdopen(fd, "ab") as output:
        process = subprocess.Popen(args, cwd=PROJECT / "pipeline", stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=output, start_new_session=True)
    cfg.setdefault("processes", {})[role] = process.pid
    save(cfg)


def serve():
    import uvicorn
    cfg = read_config()
    with store.connect():
        pass
    path = Path(cfg["socket_path"])
    if path.parent.exists() and path.parent.stat().st_uid != os.getuid():
        raise RuntimeError("Socket directory is not owned by this user")
    path.parent.mkdir(mode=0o700, exist_ok=True)
    os.chmod(path.parent, 0o700)
    if path.exists():
        probe = socket.socket(socket.AF_UNIX)
        try:
            probe.connect(str(path))
        except (ConnectionRefusedError, FileNotFoundError):
            path.unlink(missing_ok=True)
        else:
            raise RuntimeError("The local import API socket is already active")
        finally:
            probe.close()
    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(path))
    os.chmod(path, 0o600)
    server = uvicorn.Server(uvicorn.Config("arsia_pipeline.api:app", log_level="warning", access_log=False))
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()
        path.unlink(missing_ok=True)


def stop_processes(cfg):
    for role, pid in cfg.get("processes", {}).items():
        if owned_pid(pid, role):
            os.kill(pid, signal.SIGTERM)
    for _ in range(60):
        if not any(owned_pid(pid, role) for role, pid in cfg.get("processes", {}).items()):
            return
        time.sleep(0.5)
    raise RuntimeError("Local processes are still shutting down; database was left running")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["up", "stop", "restart", "status", "serve", "worker-once"])
    args = parser.parse_args()
    if args.action == "serve":
        serve()
        return
    if args.action in {"up", "restart"}:
        if args.action == "restart" and CONFIG.exists():
            stop_processes(read_config())
        cfg = ensure_database()
        launch(cfg, "api")
        launch(cfg, "worker")
        print(json.dumps({"mode": "local-test", "socket_path": cfg["socket_path"], "container": NAME,
                          "message": "Only this laboratory was started; no preview port was opened"}))
    elif args.action == "worker-once":
        from .worker import run
        run(once=True)
    else:
        cfg = read_config()
        statuses = {role: owned_pid(pid, role) for role, pid in cfg.get("processes", {}).items()}
        if args.action == "stop":
            stop_processes(cfg)
            container = inspect_container()
            if container and container["Config"]["Labels"].get("arsia.imports.instance") == cfg["instance_id"]:
                command("docker", "stop", NAME)
            print("Stopped only the isolated import laboratory; all data retained")
        else:
            print(json.dumps({"mode": "local-test", "processes": statuses, "socket_path": cfg["socket_path"]}))


if __name__ == "__main__":
    main()
