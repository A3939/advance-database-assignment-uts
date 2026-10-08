"""Runtime config is bound before business imports; secrets are never logged."""
import json
import os
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
DEFAULT_ROOT = PROJECT / 'artifacts/imports-local'

class RuntimeConfigurationError(RuntimeError):
    code = 'RUNTIME_ISOLATION'
    kind = 'system_configuration'


def _load(path):
    try:
        path=Path(path)
        if not path.is_absolute() or not path.is_file() or path.is_symlink():
            raise RuntimeConfigurationError('Explicit runtime must be an absolute regular configuration file')
        cfg=json.loads(path.read_text())
        if cfg.get('mode')!='local-test' or not cfg.get('instance_id'):
            raise RuntimeConfigurationError('Runtime instance marker is missing')
        root=Path(cfg['data_root'])
        if not root.is_absolute():raise RuntimeConfigurationError('Runtime data root must be absolute')
        if cfg.get('storage_policy',{}).get('enabled') is True:
            from .storage_lifecycle import validate_managed
            validate_managed(cfg)
            for p in [path,root,Path(cfg['storage_home'])]:
                if any(x.is_symlink() for x in [p,*p.parents]):raise RuntimeConfigurationError('Indirect managed runtime path refused')
            if path.parent.resolve()!=root.resolve():raise RuntimeConfigurationError('Managed configuration is outside its data root')
        elif root.resolve()!=DEFAULT_ROOT.resolve():
            raise RuntimeConfigurationError('Non-default runtime requires explicit managed ownership')
        return cfg
    except RuntimeConfigurationError:raise
    except Exception as exc:
        raise RuntimeConfigurationError('Runtime configuration/ownership could not be verified ('+type(exc).__name__+')') from None


# Establish the binding once on the FIRST config import. Every `from config
# import ROOT` thereafter captures this same validated root. No reload/rebind.
_explicit=os.environ.get('ARSIA_IMPORT_CONFIG')
CONFIG=Path(_explicit) if _explicit else DEFAULT_ROOT/'runtime.json'
_initial=_load(CONFIG) if _explicit else None
ROOT=Path(_initial['data_root']).resolve() if _initial else DEFAULT_ROOT


def read_config():
    requested=Path(os.environ.get('ARSIA_IMPORT_CONFIG',str(CONFIG)))
    if requested.resolve()!=CONFIG.resolve():
        raise RuntimeConfigurationError('Runtime configuration changed after import; start a fresh process')
    cfg=_load(requested)
    if Path(cfg['data_root']).resolve()!=ROOT.resolve():
        raise RuntimeConfigurationError('Runtime ROOT differs from the validated instance')
    return cfg


def explicit_executor_image():
    return _initial.get('executor_image') if _initial else None


def output_path(kind,*parts):
    """Resolve actual writable destinations; never accept escaped symlinks."""
    names={'registry':'registry','attempts':'attempts','trace':'codex-tasks','evidence':'evidence','output':'output'}
    if kind not in names:raise RuntimeConfigurationError('Unknown runtime output role')
    if any(not isinstance(p,str) or Path(p).name!=p or p in {'','.','..'} for p in parts):
        raise RuntimeConfigurationError('Output identity must be one path component')
    base=ROOT/names[kind];path=base.joinpath(*parts)
    if not path.resolve().is_relative_to(ROOT.resolve()):raise RuntimeConfigurationError('Runtime output escaped instance root')
    for p in [path,*path.parents]:
        if p==ROOT.parent:break
        if p.is_symlink():raise RuntimeConfigurationError('Indirect runtime output refused')
    return path


def inside(path, root):
    resolved, boundary = Path(path).resolve(), Path(root).resolve()
    if not resolved.is_relative_to(boundary):
        raise ValueError('File is outside its isolated working directory')
    return resolved
