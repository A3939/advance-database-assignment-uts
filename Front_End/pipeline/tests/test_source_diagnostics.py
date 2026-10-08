import hashlib
from arsia_pipeline.source_diagnostics import diagnose_projection
from test_canonical_v2 import contract


def test_trusted_diagnostic_identifies_bad_date_without_forwarding_person_row(tmp_path):
    path=tmp_path/'events.csv'
    path.write_text('ID,DATE,SEVERITY,DEATHS,INJURED,PERSON_NOTE\n1,31/02/2024 12:00,F,2,1,do-not-send-this-person-row\n')
    file={'id':'file1','name':'events.csv','path':str(path),'size':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    report=diagnose_projection(contract(),[file],mode='full')
    assert report['status']=='mapping_error'
    assert report['issue']['row_locator']=='csv:1'
    assert 'date is invalid' in report['issue']['message']
    assert 'do-not-send-this-person-row' not in str(report)
    assert report['diagnostic_only'] is True


def test_trusted_diagnostic_is_bounded(tmp_path):
    path=tmp_path/'events.csv'
    path.write_text('ID,DATE,SEVERITY,DEATHS,INJURED\n1,30/04/2024 12:00,F,2,1\n2,30/04/2024 12:00,F,2,1\n')
    file={'id':'file1','name':'events.csv','path':str(path),'size':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    report=diagnose_projection(contract(),[file],mode='full',max_rows=1)
    assert report['status']=='bounded'
    assert report['checked_rows']=={'crash':1}
