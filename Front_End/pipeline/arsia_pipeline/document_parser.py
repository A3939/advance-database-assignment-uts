"""Bounded PDF extraction shared by evidence readers and host process boundary."""
from pathlib import Path
from .errors import NeedsInput, ValidationFailure


def pdf_text(path, page=None):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size>16*1024**2:
        raise ValidationFailure('PDF exceeds the regular-file/16-MiB source-document bound.')
    from .parser_guard import required, call
    if required():return call('pdf',[str(path),page])
    from pypdf import PdfReader
    import pypdf.filters
    pypdf.filters.ZLIB_MAX_OUTPUT_LENGTH=16*1024**2
    reader=PdfReader(path)
    if reader.is_encrypted:raise NeedsInput('Encrypted PDF requires an accessible publisher copy; no password bypass is attempted.')
    if len(reader.pages)>300:raise ValidationFailure('PDF exceeds the 300-page document extraction limit.')
    if page is not None and (type(page) is not int or not 0<=page<len(reader.pages)):
        raise ValidationFailure('PDF page is outside the document.')
    values=[];size=0
    for i in [page] if page is not None else range(len(reader.pages)):
        value=reader.pages[i].extract_text() or '';size+=len(value.encode())
        if size>4*1024**2:raise ValidationFailure('PDF exceeds the extracted text byte bound.')
        values.append(value)
    return values
