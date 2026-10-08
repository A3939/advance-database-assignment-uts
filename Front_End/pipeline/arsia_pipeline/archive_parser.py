"""Bound ZIP metadata before the host materializes its directory a second time."""
import hashlib
import zipfile
from pathlib import Path

from .errors import ValidationFailure


def inventory(file, max_files=128, max_expanded=1024**3, check_cancelled=lambda: None):
    from . import parser_guard
    if parser_guard.required():
        return parser_guard.call('zip_inventory', [file, max_files, max_expanded], check_cancelled)
    path = Path(file['path'])
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != file['sha256']:
        raise ValidationFailure('Archive bytes changed after registration.')
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if (len(entries) > max_files * 2 or sum(not e.is_dir() for e in entries) > max_files
                    or sum(e.file_size for e in entries) > max_expanded
                    or sum(len(e.filename.encode('utf-8')) + len(e.extra) + len(e.comment) for e in entries) > 1024**2):
                raise ValidationFailure('ZIP exceeds its bounded member, metadata or expanded-size limit.')
            return {'sha256': digest, 'entries': len(entries)}
    except zipfile.BadZipFile as exc:
        raise ValidationFailure('ZIP checksum or structure is invalid.') from exc


def member_hash(file,name):
    """Trusted worker only: retain archive/member relationship without extracting."""
    import stat
    from pathlib import PurePosixPath
    inventory(file)
    with zipfile.ZipFile(file['path']) as archive:
        selected=[entry for entry in archive.infolist() if entry.filename==name]
        if not selected:return None
        if len(selected)!=1:raise ValidationFailure('Archive has ambiguous duplicate member names')
        entry=selected[0];mode=(entry.external_attr>>16)&0xffff
        if (PurePosixPath(name).is_absolute() or any(p in {'','..','.'} for p in name.split('/'))
                or '\\' in name or ':' in name or '\x00' in name or entry.is_dir() or entry.flag_bits&1
                or stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in {0,stat.S_IFREG}
                or entry.file_size>512*1024**2
                or entry.file_size>1024**2 and entry.file_size>max(entry.compress_size,1)*1000):
            raise ValidationFailure('Unsupported or unsafe source archive member')
        digest=hashlib.sha256();size=0
        with archive.open(entry) as stream:
            while chunk:=stream.read(1024**2):
                size+=len(chunk)
                if size>entry.file_size:raise ValidationFailure('Archive member exceeded its declared size')
                digest.update(chunk)
        if size!=entry.file_size:raise ValidationFailure('Archive member is truncated')
        return {'archive_sha256':file['sha256'],'member':name,'sha256':digest.hexdigest(),'size':size}
