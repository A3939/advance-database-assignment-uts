"""Actual subprocess limits; inputs and unrelated processes remain untouched."""
import hashlib
import os
import time
import zipfile

import pytest

from arsia_pipeline import parser_guard as guard
from arsia_pipeline.archive_parser import inventory
from arsia_pipeline.errors import ImportCancelled, ValidationFailure
from arsia_pipeline.intakereaders import detect_format, detect_tables, iter_table
from arsia_pipeline.metadata_extractors import MetadataError, resolve_locator


def descriptor(path):
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def track_processes(monkeypatch):
    children=[]
    original=guard.subprocess.Popen
    def tracked(*args, **kwargs):
        child=original(*args,**kwargs)
        if isinstance(args[0],list) and 'arsia_pipeline.parser_worker' in ' '.join(args[0]):children.append(child)
        return child
    monkeypatch.setattr(guard.subprocess,'Popen',tracked)
    return children


def test_early_consumer_close_and_cancel_reap_child(tmp_path,monkeypatch):
    file=tmp_path/'many.csv';file.write_text('ID,Count\n'+'A,1\n'*100_000)
    before=descriptor(file)
    children=track_processes(monkeypatch)
    stream=iter_table(file)
    assert next(stream)==('csv:1',{'ID':'A','Count':'1'})
    stream.close()
    assert children and all(c.poll() is not None for c in children)
    calls=[0]
    def cancelled():
        calls[0]+=1
        if calls[0]>=3:raise ImportCancelled('cancelled')
    start=time.monotonic()
    with pytest.raises(ImportCancelled):list(guard.packets('rows',[str(file),None],cancelled))
    assert time.monotonic()-start<3
    assert all(c.poll() is not None for c in children)
    assert descriptor(file)==before


def test_independent_alarm_stops_large_valid_parse(tmp_path,monkeypatch):
    file=tmp_path/'many.json'
    file.write_text('['+','.join('{"ID":1,"Count":2}' for _ in range(300_000))+']')
    before=descriptor(file);children=track_processes(monkeypatch)
    with pytest.raises(guard.ParserResourceError):list(guard.packets('detect',[str(file),None],seconds=.001))
    assert all(c.poll() is not None for c in children)
    assert descriptor(file)==before


def test_group_signal_failure_still_reaps_the_exact_child(tmp_path,monkeypatch):
    file=tmp_path/'many.csv';file.write_text('ID,Count\n'+'A,1\n'*100_000)
    children=track_processes(monkeypatch)
    def denied(*args):raise PermissionError('fixture group signal restriction')
    monkeypatch.setattr(guard.os,'killpg',denied)
    stream=iter_table(file)
    assert next(stream)[0]=='csv:1'
    stream.close()
    assert children and all(c.poll() is not None for c in children)


@pytest.mark.skipif(guard.sys.platform!='darwin',reason='Darwin uses sampled RSS; Linux uses RLIMIT_AS')
def test_resident_limit_kills_only_owned_child(tmp_path,monkeypatch):
    file=tmp_path/'tiny.csv';file.write_text('ID,Count\nA,1\n')
    children=track_processes(monkeypatch)
    monkeypatch.setattr(guard,'resident_bytes',lambda pid:65*1024**2)
    with pytest.raises(guard.ParserResourceError,match='sampled resident'):
        list(guard.packets('detect',[str(file),None],memory_bytes=64*1024**2))
    assert children and all(c.poll() is not None for c in children)
    assert os.getpid()>0


def test_compressed_shared_strings_are_process_bounded(tmp_path,monkeypatch):
    from openpyxl import Workbook
    path=tmp_path/'shared.xlsx';book=Workbook();book.active.append(['ID','Count']);book.save(path)
    with zipfile.ZipFile(path) as z:entries={n:z.read(n) for n in z.namelist()}
    entries['[Content_Types].xml']=entries['[Content_Types].xml'].replace(b'</Types>',b'<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>')
    entries['xl/sharedStrings.xml']=b'<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'+b'<si><t>abcdefghij</t></si>'*1_000_000+b'</sst>'
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for name,content in entries.items():z.writestr(name,content)
    before=descriptor(path);children=track_processes(monkeypatch)
    with pytest.raises(guard.ParserResourceError):
        list(guard.packets('detect',[str(path),None],memory_bytes=64*1024**2))
    assert all(c.poll() is not None for c in children)
    assert descriptor(path)==before


def test_archive_metadata_is_bounded_before_host_open(tmp_path):
    path=tmp_path/'many.zip'
    with zipfile.ZipFile(path,'w') as archive:
        for i in range(257):archive.writestr(str(i)+'/','')
    assert detect_format(path)=='zip'
    with pytest.raises(ValidationFailure,match='bounded member'):inventory(descriptor(path))


def test_pdf_locator_preserves_semantic_failure_code():
    raw=b'%PDF-not-a-document'
    with pytest.raises(MetadataError) as caught:
        resolve_locator(raw,hashlib.sha256(raw).hexdigest(),{'kind':'pdf-text-range','page_from':1,'page_to':1,'start':0,'end':1})
    assert caught.value.code=='EVIDENCE_LOCATOR_INVALID'
