"""Explicit synthetic network-receipt fixture; never used by live source tools."""
import hashlib
import json
from pathlib import Path
from uuid import uuid4

URL='https://data.example.gov.au/events.csv'


def add_reference(files,root,url=URL,index=0):
    original=files[index];raw=Path(original['path']).read_bytes();sha=hashlib.sha256(raw).hexdigest()
    folder=Path(root)/'fixture-network';(folder/'sha256').mkdir(parents=True,exist_ok=True)
    path=folder/'sha256'/sha
    if not path.exists():path.write_bytes(raw)
    receipt=folder/(uuid4().hex+'.json')
    at='2026-10-03T00:00:00+00:00'
    receipt.write_text(json.dumps({'status':'fetched','final_url':url,'sha256':sha,'size':len(raw),
        'fetched_at':at,'final_host_official':True,'fixture':'Synthetic transport receipt; not an actual official download'}))
    file={'id':'public-'+sha[:24],'role':'public_evidence','name':Path(url).name,'path':str(path),
          'sha256':sha,'size':len(raw),'evidence_url':url,'fetched_at':at,'receipt_path':str(receipt)}
    files[:]=[f for f in files if not (f.get('role')=='public_evidence' and f.get('evidence_url')==url)]
    files.append(file)
    return file


def install_references(session,files):
    session.intake.register_files([f for f in files if f.get('role')=='public_evidence'])
    session.files=list(session.intake.files)
