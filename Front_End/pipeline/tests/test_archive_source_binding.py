"""ZIP membership is replayed, never inferred from the member name or schema."""
import hashlib
import zipfile
from pathlib import Path
import pytest
from arsia_pipeline import config
from arsia_pipeline.errors import NeedsInput,ValidationFailure
from arsia_pipeline.trusted_qa import _proof
from source_binding_fixture import add_reference
from test_limited_geography import source_fixture


@pytest.mark.parametrize('change',['same_member','missing','different_content','duplicate_name'])
def test_archived_official_member_is_bound_independently_of_container_wrapper(tmp_path,monkeypatch,change):
    monkeypatch.setattr(config,'ROOT',tmp_path)
    c,files=source_fixture(tmp_path);upload=files[0]
    source=tmp_path/'official.zip'
    raw=Path(upload['path']).read_bytes()
    with zipfile.ZipFile(source,'w',compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr('records.csv',raw if change!='different_content' else raw.replace(b'001,',b'002,'))
        z.writestr('README.txt','Synthetic source fixture; container members have independent roles.')
        if change=='duplicate_name':
            with pytest.warns(UserWarning):z.writestr('records.csv',raw)
    # The authority scope is the fixture catalog's published resource URL,
    # and format discovery is by registered bytes, not its filename suffix.
    holder=[{'path':str(source)}];ref=add_reference(holder,tmp_path)
    files[:]=[upload,ref];upload['archive_member']='other.csv' if change=='missing' else 'records.csv'
    if change!='same_member':
        with pytest.raises((NeedsInput,ValidationFailure)):_proof(c,tmp_path,files)
    else:
        proof=_proof(c,tmp_path,files)['upload_bindings'][0]
        assert proof['rule']=='exact_archive_member_bytes'
        assert proof['member_receipt']['sha256']==hashlib.sha256(raw).hexdigest()
        assert proof['member_receipt']['archive_sha256']==ref['sha256']
