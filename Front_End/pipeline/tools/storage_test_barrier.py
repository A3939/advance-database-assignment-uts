"""Acceptance-only, request-scoped, bounded parent/child rendezvous."""
import json
import os
import select
import sys
import time
from pathlib import Path
from uuid import uuid4
from arsia_pipeline.storage_lifecycle import atomic_json, now


def read_line(fd, timeout):
    until = time.monotonic() + timeout
    data = bytearray()
    while True:
        left = until - time.monotonic()
        if left <= 0 or not select.select([fd], [], [], left)[0]:
            raise TimeoutError('Barrier handshake timed out')
        byte = os.read(fd, 1)
        if not byte:
            raise EOFError('Barrier peer exited before release')
        if byte == b'\n':
            return json.loads(data)
        data.extend(byte)
        if len(data) > 16384:
            raise ValueError('Oversized barrier message')


class RequestBarrier:
    def __init__(self, *, output, phase, identity, ready_fd, timeout=90,
                 occurrence=1, input_fd=None):
        if occurrence < 1 or timeout <= 0:
            raise ValueError('Positive occurrence and timeout required')
        self.output, self.phase, self.identity = Path(output), phase, dict(identity)
        self.ready_fd, self.input_fd = ready_fd, sys.stdin.fileno() if input_fd is None else input_fd
        self.timeout, self.occurrence, self.counts = timeout, occurrence, {}

    def event(self, state, **fields):
        record = {**self.identity, 'pid': os.getpid(), 'at': now(), 'state': state, **fields}
        path = self.output.with_suffix('.handshake.jsonl')
        with path.open('a') as stream:
            stream.write(json.dumps(record) + '\n'); stream.flush(); os.fsync(stream.fileno())
        return record

    def __call__(self, phase, *, request_id, operation_id=None):
        key = (request_id, phase)
        self.counts[key] = self.counts.get(key, 0) + 1
        count = self.counts[key]
        self.event('callback', phase=phase, request_id=request_id, occurrence=count)
        if phase != self.phase or count != self.occurrence:
            return
        actual = self.event('ready', phase=phase, request_id=request_id, occurrence=count,
                            operation_id=operation_id, barrier_id=uuid4().hex)
        atomic_json(self.output.with_suffix('.barrier.json'), actual)
        if self.ready_fd is None:
            raise RuntimeError('Explicit ready pipe required for selected barrier')
        os.write(self.ready_fd, (json.dumps(actual)+'\n').encode())
        try:
            reply = read_line(self.input_fd, self.timeout)
            expected = {key: actual[key] for key in ('barrier_id','child_id','scenario','request_id','phase','occurrence')}
            if reply != {'command':'CONTINUE', **expected}:
                raise ValueError('Barrier release identity/command mismatch')
            self.event('released', **expected)
        except BaseException as exc:
            self.event('timeout' if isinstance(exc, TimeoutError) else 'release_failed',
                       phase=phase, request_id=request_id, barrier_id=actual['barrier_id'],
                       error_type=type(exc).__name__, message=str(exc))
            raise
