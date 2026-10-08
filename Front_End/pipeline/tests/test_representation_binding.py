"""Derived fixture wrappers; same keys and every raw value, never a new official version."""
import csv
import hashlib
import io
import json
from pathlib import Path
import pytest

from test_limited_geography import source_fixture
from source_binding_fixture import add_reference
from arsia_pipeline import config
from arsia_pipeline.adapter_reuse import ADAPTER
from arsia_pipeline.errors import NeedsInput,ValidationFailure
from arsia_pipeline.isolated_executor import run_python
from arsia_pipeline.representation_binding import compare_csv
from arsia_pipeline.trusted_qa import validate_candidate


def source(root):
    c,files=source_fixture(root)
    original='ID,DATE,Event_X,Event_Y,Note\n001,2024-01-01,123,456,"café, detail"\n002,2024-02-02,,,second\n'
    Path(files[0]['path']).write_text(original)
    update(files[0]);add_reference(files,root)
    return c,files,original


def update(file):
    path=Path(file['path']);file.update(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),size=path.stat().st_size)


@pytest.mark.parametrize('variant',['rename','bom','utf16','columns','line_endings','row_order','delimiter','cp1252'])
def test_complete_representation_replay_and_fresh_qa_accept_lossless_wrappers(tmp_path,monkeypatch,variant):
    monkeypatch.setattr(config,'ROOT',tmp_path)
    c,files,original=source(tmp_path);upload=files[0];reference=files[1]
    encoding='utf-8';delimiter=',';newline='\n'
    reader=csv.DictReader(io.StringIO(original));rows=list(reader);fields=reader.fieldnames
    if variant=='rename':upload['name']='an-unrelated-filename.csv'
    if variant=='bom':encoding='utf-8-sig'
    if variant=='utf16':encoding='utf-16'
    if variant=='columns':fields=list(reversed(fields))
    if variant=='line_endings':newline='\r\n'
    if variant=='row_order':rows.reverse()
    if variant=='delimiter':delimiter=';'
    if variant=='cp1252':
        encoding='cp1252';c['resources'][0]['table']['encoding']='cp1252'
    stream=io.StringIO(newline='');writer=csv.DictWriter(stream,fieldnames=fields,delimiter=delimiter,lineterminator=newline)
    writer.writeheader();writer.writerows(rows);Path(upload['path']).write_bytes(stream.getvalue().encode(encoding));update(upload)
    before=hashlib.sha256(Path(reference['path']).read_bytes()).hexdigest()
    run=run_python(ADAPTER,files,tmp_path/'runs',source_contract=c,mode='full',limits={'seconds':15,'memory_mb':128})
    assert run['status']=='succeeded',run
    result=validate_candidate(run,c,files,run['code_sha256'],tmp_path)
    candidate=[json.loads(line) for line in Path(result['canonical_path']).read_text().splitlines()]
    assert {tuple(r['raw_key']):(r['occurrence_date'],r['extensions']['Note']) for r in candidate}=={
        ('001',):('2024-01-01','café, detail'),('002',):('2024-02-02','second')}
    assert result['summary']['crash_count']==2 and result['summary']['fatalities'] is None
    proof=result['admission']['evidence']['upload_bindings'][0]
    assert proof['reference']['sha256']==before==hashlib.sha256(Path(reference['path']).read_bytes()).hexdigest()
    assert proof['reference']['fetched_at']=='2026-10-03T00:00:00+00:00'
    assert proof['rule'] in {'exact_resource_bytes','replayed_csv_representation'}


@pytest.mark.parametrize('mutation',['key_loss','character_loss','drop','duplicate','note_change'])
def test_same_schema_and_count_or_sample_do_not_bind_changed_content(tmp_path,monkeypatch,mutation):
    monkeypatch.setattr(config,'ROOT',tmp_path)
    c,files,original=source(tmp_path)
    edited=original
    if mutation=='key_loss':edited=edited.replace('001,','1,')
    elif mutation=='character_loss':edited=edited.replace('café','caf?')
    elif mutation=='drop':edited='\n'.join(edited.splitlines()[:-1])+'\n'
    elif mutation=='duplicate':edited+=edited.splitlines()[-1]+'\n'
    elif mutation=='note_change':edited=edited.replace('second','changed')
    Path(files[0]['path']).write_text(edited);update(files[0])
    comparison=compare_csv(files[1],files[0],tmp_path/'comparison')
    assert not comparison['equivalent']
    from arsia_pipeline.trusted_qa import _proof
    with pytest.raises(NeedsInput) as caught:_proof(c,tmp_path,files)
    assert caught.value.details['grounding']['issues'][0]['code']=='OFFICIAL_UPLOAD_UNBOUND'


@pytest.mark.parametrize('corruption',['bytes','receipt_hash','receipt_url','time','outside_registry'])
def test_forged_or_unregistered_reference_never_authorizes_content(tmp_path,monkeypatch,corruption):
    monkeypatch.setattr(config,'ROOT',tmp_path)
    c,files,_=source(tmp_path);ref=files[1];receipt=Path(ref['receipt_path'])
    value=json.loads(receipt.read_text())
    if corruption=='bytes':Path(ref['path']).write_bytes(b'altered')
    elif corruption=='receipt_hash':value['sha256']='0'*64
    elif corruption=='receipt_url':value['final_url']='https://data.example.gov.au/another.csv'
    elif corruption=='time':value.pop('fetched_at')
    else:files.pop() # Putting a receipt in the proposed contract creates no host authority.
    receipt.write_text(json.dumps(value))
    c['source_binding']={'receipt_path':str(receipt),'confirmed':True}
    from arsia_pipeline.trusted_qa import _proof
    with pytest.raises((NeedsInput,ValidationFailure)):_proof(c,tmp_path,files)
