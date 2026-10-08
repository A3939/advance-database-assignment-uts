"""Fixed local model transport; an owned test may use a private Unix socket.

No user upload/contract can select a gateway. Normal work always uses the single
3100 server. Test sockets require the immutable managed runtime and exact task
ownership path; they never redirect to an arbitrary HTTP host.
"""
import http.client
import os
from pathlib import Path
import socket
import stat

from .config import RuntimeConfigurationError


class UnixModelConnection(http.client.HTTPConnection):
    def __init__(self,path,timeout):
        super().__init__('127.0.0.1',3100,timeout=timeout)
        self.path=path

    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self.path)


def socket_path(cfg):
    session=cfg.get('test_session_id')
    gateway=cfg.get('private_model_gateway')
    if (not cfg.get('storage_policy',{}).get('enabled') or not isinstance(session,str)
            or len(session)!=32 or any(c not in '0123456789abcdef' for c in session)
            or not isinstance(gateway,dict) or gateway.get('instance_id')!=cfg.get('instance_id')
            or gateway.get('test_session_id')!=session or gateway.get('protocol')!='owned-model-gateway-v1'):
        raise RuntimeConfigurationError('Private model gateway requires exact managed task ownership')
    path=Path(gateway['socket_path'])
    expected=Path('/tmp').resolve()/('arsia-model-'+session[:12])/'gateway.sock'
    if path!=expected or path.is_symlink() or path.parent.is_symlink():
        raise RuntimeConfigurationError('Private model gateway path differs from its owned task')
    parent=path.parent.stat();item=path.lstat()
    if not stat.S_ISDIR(parent.st_mode) or parent.st_uid!=os.getuid() or parent.st_mode&0o077 or not stat.S_ISSOCK(item.st_mode) or item.st_uid!=os.getuid() or item.st_mode&0o077:
        raise RuntimeConfigurationError('Private model gateway socket is not owner-only')
    return str(path)


def connection(cfg,timeout):
    if cfg.get('private_model_gateway') is not None:
        return UnixModelConnection(socket_path(cfg),timeout)
    return http.client.HTTPConnection('127.0.0.1',3100,timeout=timeout)
