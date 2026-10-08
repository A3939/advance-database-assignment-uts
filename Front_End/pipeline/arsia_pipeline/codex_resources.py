"""Trusted resource observations for one supervised CLI process group."""
from pathlib import Path
import subprocess
from uuid import UUID


def runtime_argv_link(path, data_root):
    """Recognize only the bundled CLI's own argv shims for byte accounting.

    This is not a managed input, archive, read, execution or deletion grant.
    The caller must lstat the link itself and must never follow its target.
    """
    from .codex_sandbox import BINARY
    try:
        parts = Path(path).relative_to(data_root).parts
        if len(parts) != 7 or parts[0] != 'codex-tasks' or parts[2:5] != ('home', 'tmp', 'arg0'):
            return False
        if str(UUID(parts[1])) != parts[1] or not parts[5].startswith('codex-arg0'):
            return False
        return parts[6] in {'applypatch', 'apply_patch', 'codex-execve-wrapper'} and Path(path).readlink() == BINARY
    except (ValueError, OSError):
        return False


def cpu_seconds(value):
    days, _, value = value.rpartition('-') if '-' in value else ('0', '', value)
    parts = [float(p) for p in value.split(':')]
    result = 0.0
    for part in parts:
        result = result * 60 + part
    return int(days)*86400 + result


def group_usage(group, previous):
    # Commands/environment are intentionally not requested by ps.
    data = subprocess.check_output(['/bin/ps', '-axo', 'pid=,pgid=,rss=,time='], text=True, timeout=2)
    rows = []
    for line in data.splitlines():
        fields = line.split()
        if len(fields) == 4 and int(fields[1]) == group:
            pid, _, rss, cpu = fields
            previous[int(pid)] = max(previous.get(int(pid), 0), cpu_seconds(cpu))
            rows.append(int(rss)*1024)
    return {'cpu_seconds': sum(previous.values()), 'rss_bytes':sum(rows), 'processes':len(rows)}


def storage_bytes(roots, limit):
    total = entries = 0
    for root in roots:
        for path in Path(root).rglob('*'):
            entries += 1
            if entries > 32768:
                raise ValueError('runtime_files')
            # Codex caches may contain symlinks; never traverse/read their targets.
            if not path.is_symlink() and path.is_file():
                total += path.stat().st_size
            if total > limit:
                raise ValueError('runtime_storage')
    return total
