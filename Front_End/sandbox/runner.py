"""Trusted container harness. No host paths, credentials, network or Docker socket."""
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import resource
import stat
import traceback

resource.setrlimit(resource.RLIMIT_CPU, (20, 22))
resource.setrlimit(resource.RLIMIT_FSIZE, (4 * 1024 * 1024, 4 * 1024 * 1024))
resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))

class BoundedOutput(io.TextIOBase):
    def __init__(self):
        self.parts, self.remaining = [], 12000
    def write(self, s):
        self.parts.append(s[:self.remaining])
        self.remaining = max(0, self.remaining - len(s))
        return len(s)
    def value(self):
        return ''.join(self.parts)

out = BoundedOutput()
status = 'succeeded'
error = None
try:
    code = Path('/data/analysis.py').read_text()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        exec(compile(code, '/data/analysis.py', 'exec'), {'__name__': '__main__'})
except BaseException:
    status = 'failed'
    error = traceback.format_exc(limit=6)[-5000:]

files, total = [], 0
allowed = {'.csv', '.json', '.md', '.txt', '.png', '.pdf'}
for p in sorted(Path('/analysis').iterdir()):
    if len(files) >= 8 or p.suffix.lower() not in allowed or not p.name.isascii() or len(p.name) > 80:
        continue
    try:
        # Refuse symlinks, pipes, sockets and directories, including on a race.
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as f:
            info = os.fstat(f.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 4 * 1024 * 1024:
                continue
            content = f.read(4 * 1024 * 1024 + 1)
        total += len(content)
        if total > 8 * 1024 * 1024:
            break
        if p.suffix.lower() == '.md' and b'\\n' in content and b'\n' not in content:
            status = 'failed'
            error = 'Markdown report contains literal backslash-n instead of line breaks. Correct the Python string escaping and run again.'
            continue
        files.append({'name': p.name, 'data': base64.b64encode(content).decode()})
    except OSError:
        continue
print(json.dumps({'status': status, 'stdout': out.value(), 'error': error, 'files': files}, allow_nan=False))
