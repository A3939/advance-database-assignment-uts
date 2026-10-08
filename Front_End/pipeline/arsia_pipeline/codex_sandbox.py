"""OS boundary for the supplied macOS runtime, including all its descendants.

This is additional to Codex permissions: no project, credentials, DB socket,
Docker socket or raw uploads are readable. Only the task bridge is reachable.
Unsupported hosts fail closed; Linux needs a separate container launcher.
"""
import json
import os
from pathlib import Path
import platform

from .config import PROJECT

BUNDLE = PROJECT / 'codex-0.159.3-macos-arm64'
BINARY = BUNDLE / 'bin/codex'
PYTHON_ROOT = Path('/Library/Frameworks/Python.framework/Versions/3.12')
PYTHON = PYTHON_ROOT / 'bin/python3.12'


def check_runtime():
    """Fail before creating the task bridge when a fixed host dependency is absent."""
    from .errors import ModelUnavailable
    missing = []
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        missing.append('macOS arm64 isolation')
    for label, path in [('supplied Codex runtime', BINARY), ('OS sandbox', Path('/usr/bin/sandbox-exec')),
                        ('sandbox Python', PYTHON)]:
        if not path.is_file() or not os.access(path, os.X_OK):
            missing.append(label)
    if missing:
        raise ModelUnavailable('Required isolated Codex runtime dependencies are unavailable.', {
            'kind': 'environment_dependency', 'responsible_party': 'system', 'missing': missing,
            'resumable_when': 'Restore the reviewed local runtime dependencies and start a new verified attempt.'})


def profile(workspace, home, port):
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('Codex isolation currently requires macOS arm64')
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError('Invalid task bridge port')
    workspace, home = Path(workspace).resolve(), Path(home).resolve()
    q = lambda p: json.dumps(str(p))
    return '\n'.join([
        '(version 1)', '(deny default)',
        '(allow process-exec process-fork)', '(allow signal (target self))',
        '(allow sysctl-read)',
        '(allow mach-lookup (global-name "com.apple.cfprefsd.agent") (global-name "com.apple.cfprefsd.daemon") (local-name "com.apple.cfprefsd.agent") (global-name "com.apple.system.logger") (global-name "com.apple.logd"))',
        '(allow ipc-posix-shm-read* (ipc-posix-name "apple.shm.notification_center") (ipc-posix-name-prefix "apple.cfprefs."))',
        '(allow user-preference-read (preference-domain "com.openai.codex"))',
        '(allow file-read-metadata)',
        '(allow file-read* (literal "/") (literal "/System") (subpath "/System/Library") (subpath "/System/Applications") (subpath "/System/Volumes/Preboot") (subpath "/usr/bin") (subpath "/usr/sbin") (subpath "/usr/lib") (subpath "/usr/libexec") (subpath "/usr/share") (subpath "/bin") (subpath "/sbin")'
        ' (subpath "/Library/Apple") (subpath "/Library/Developer/CommandLineTools")'
        ' (subpath "/private/preboot") (subpath "/private/var/db/dyld") (subpath "/private/var/db/timezone")'
        ' (literal "/private/etc/localtime") (literal "/private/etc/hosts") (literal "/private/etc/passwd")'
        ' (literal "/dev/random") (literal "/dev/urandom"))',
        '(allow file-read* file-write* (literal "/dev/null") (literal "/dev/tty") (subpath "/dev/fd"))',
        f'(allow file-read* (subpath {q(PYTHON_ROOT)}) (subpath {q(BUNDLE.resolve())}) (subpath {q(workspace)}) (subpath {q(home)}))',
        f'(allow file-write* (subpath {q(workspace / "proposals")}) (subpath {q(workspace / "scratch")}) (subpath {q(home)}))',
        f'(allow network-outbound (remote ip "localhost:{port}"))',
    ]) + '\n'


def environment(workspace, home, model_token, tool_token):
    # No inherited auth, proxy, database, Python or shell init configuration.
    return {'PATH':str(PYTHON_ROOT/'bin')+':/usr/bin:/bin:/usr/sbin:/sbin', 'PYTHONNOUSERSITE':'1', 'HOME':str(home),
            'CODEX_HOME':str(home), 'TMPDIR':str(Path(workspace)/'scratch'),
            'LANG':'en_US.UTF-8', 'ARSIA_MODEL_CAPABILITY':model_token,
            'ARSIA_TOOL_CAPABILITY':tool_token}


def command(profile_path, args):
    if not BINARY.is_file() or not os.access('/usr/bin/sandbox-exec', os.X_OK):
        raise RuntimeError('The supplied Codex runtime or required OS sandbox is missing')
    return ['/usr/bin/sandbox-exec', '-f', str(profile_path), str(BINARY), *args]
