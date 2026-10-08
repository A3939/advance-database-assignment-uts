"""Container bootstrap for a separate LOCAL TEST Compose project only."""
import argparse
import os
import secrets
from pathlib import Path
from uuid import uuid4

from psycopg.conninfo import make_conninfo

from .config import CONFIG, ROOT, read_config
from .dev import save, serve
from . import store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["bootstrap", "api", "worker"])
    args = parser.parse_args()
    if args.command == "bootstrap":
        if CONFIG.exists():
            cfg = read_config()
        else:
            password = Path("/run/secrets/import_database_password").read_text().strip()
            if len(password) < 24:
                raise RuntimeError("Use a private random password of at least 24 characters")
            cfg = {"mode": "local-test", "instance_id": uuid4().hex,
                   "database": "arsia_imports_compose", "data_root": str(ROOT),
                   "socket_path": "/run/arsia/api.sock", "processes": {},
                   "dsn": make_conninfo(host="db", dbname="arsia_imports_compose", user="arsia_imports",
                                        password=password, connect_timeout=5)}
            save(cfg)
        if not cfg.get("agent_gateway_token"):
            cfg["agent_gateway_token"] = secrets.token_urlsafe(48)
            save(cfg)
        store.initialize(cfg)
        print("Isolated Compose local-test database initialized and marker verified")
    elif args.command == "api":
        serve()
    else:
        from .worker import run
        run()


if __name__ == "__main__":
    main()
