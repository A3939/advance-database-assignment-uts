"""Trusted parent-death watchdog; never runs model code outside the OS boundary."""
import argparse
import os
import signal
import subprocess
import time
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--parent', type=int, required=True)
    parser.add_argument('--seconds', type=float)
    parser.add_argument('--cpu-seconds', type=float)
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--storage-root', action='append', type=Path, default=[])
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    bounded = args.receipt is not None
    if bounded and (not args.seconds or not args.cpu_seconds or not args.storage_root or
                    not 0 < args.seconds <= 7200 or not 0 < args.cpu_seconds <= 3600):
        raise ValueError('Invalid bounded runtime limits')
    stop = False
    def interrupted(*_):
        nonlocal stop
        stop = True
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    if os.getppid() != args.parent:
        return
    child = subprocess.Popen(args.command, start_new_session=True)
    started = time.monotonic(); previous = {}; usage = {}; limited = None
    if bounded:
        # This module is a fixed trusted sibling, never a task-provided module.
        from codex_resources import group_usage, storage_bytes
    def receipt():
        if bounded:
            temporary = args.receipt.with_suffix('.tmp')
            temporary.write_text(json.dumps({'version':'codex-resource-watch-v1', 'group':child.pid,
                'wall_seconds':time.monotonic()-started, 'usage':usage, 'limit':limited,
                'note':'CPU/RSS/process/storage are sampled once per second; brief overshoot is possible.'}))
            temporary.chmod(0o600);temporary.replace(args.receipt)
    try:
        while child.poll() is None and not stop and os.getppid() == args.parent:
            if bounded:
                try:
                    usage = group_usage(child.pid, previous)
                    usage['storage_bytes'] = storage_bytes(args.storage_root, 512*1024**2)
                    if time.monotonic()-started > args.seconds: limited = 'wall_seconds'
                    elif usage['cpu_seconds'] > args.cpu_seconds: limited = 'compute_seconds'
                    elif usage['rss_bytes'] > 1536*1024**2: limited = 'runtime_memory'
                    elif usage['processes'] > 32: limited = 'runtime_processes'
                except Exception:
                    limited = 'runtime_resource_observation'
                receipt()
                if limited: break
            time.sleep(1 if bounded else .2)
    finally:
        # The group includes generated shell children. Never signal another job.
        try: os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError: pass
        try: child.wait(timeout=3)
        except subprocess.TimeoutExpired: pass
        try: os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError: pass
        child.wait()
        receipt()
    raise SystemExit(124 if limited else child.returncode if child.returncode is not None and child.returncode >= 0 else 130)


if __name__ == '__main__': main()
