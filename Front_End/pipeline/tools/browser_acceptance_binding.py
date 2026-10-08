"""Temporary binding of the existing /imports/test route to an owned lab.

No frontend restart, model calls or main-runtime mutation. Restore the exact
previous private test configuration only if it is still our binding.
"""
import hashlib
import json
import os
from pathlib import Path
import threading
import time


class BrowserBinding:
    def __init__(self, app, cfg, output, manual_path, expected_sha256):
        self.app, self.cfg, self.output = app, cfg, output
        self.path = manual_path
        self.expected = expected_sha256
        self.server = self.thread = None
        self.bound = False

    @staticmethod
    def sha(value):
        return hashlib.sha256(value).hexdigest()

    def start(self):
        import uvicorn
        from tools.verify_codex_owned import save
        self.before = self.path.read_bytes()
        assert self.sha(self.before) == self.expected, 'Test configuration changed; no binding attempted'
        assert self.path.stat().st_mode & 0o077 == 0
        backup = self.output / 'previous-manual-test.json'
        backup.write_bytes(self.before)
        backup.chmod(0o600)
        socket = Path(self.cfg['socket_path'])
        socket.parent.mkdir(mode=0o700)
        self.server = uvicorn.Server(uvicorn.Config(self.app, uds=str(socket), log_level='warning'))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                break
            assert self.thread.is_alive(), 'Owned API failed to start'
            time.sleep(.1)
        else:
            raise RuntimeError('Owned API did not become ready')
        assert self.path.read_bytes() == self.before, 'Test configuration changed during setup'
        save(self.path, self.cfg, replace=True)
        self.installed = self.path.read_bytes()
        self.bound = True
        save(self.output / 'browser-ready.json', {'url':'http://127.0.0.1:3100/imports/test',
            'instance_id':self.cfg['instance_id'], 'database':self.cfg['database'],
            'previous_test_configuration_sha256':self.expected,
            'new_test_configuration_sha256':self.sha(self.installed),
            'main_runtime_unchanged':True,
            'note':'Upload using the real UI. This acceptance worker starts once the uploaded job is queued.'})

    def close(self):
        from tools.verify_codex_owned import save
        try:
            restored = False
            if self.bound:
                assert self.path.read_bytes() == self.installed, 'Binding changed by another operator; preserve instead of overwriting'
                temporary = self.path.with_suffix('.restore.tmp')
                temporary.write_bytes(self.before)
                temporary.chmod(0o600)
                os.replace(temporary, self.path)
                restored = self.path.read_bytes() == self.before
            save(self.output / 'browser-binding-restored.json', {'was_bound':self.bound,
                'previous_bytes_restored':restored,'main_runtime_mutated':False})
        finally:
            if self.server:
                self.server.should_exit = True
            if self.thread:
                self.thread.join(timeout=10)
                assert not self.thread.is_alive(), 'Owned API shutdown pending'
