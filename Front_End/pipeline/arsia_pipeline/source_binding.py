"""Bind official resource receipts to actual uploads, independently of semantics.

Historical host receipts remain usable. A URL, matching columns or sampled rows
do not certify the rest of a file. Receipt descriptors originate in the host
file registry; generated contract fields cannot add receipts to that registry.
"""
from datetime import datetime
import json
from pathlib import Path
import re
from urllib.parse import urlsplit,parse_qs

from .errors import NeedsInput,ValidationFailure
from .source_knowledge import file_hash

VERSION='official-upload-binding-v1'


def provider_export(url, dataset_url):
    from .source_identity import url_identity
    own,source=url_identity(url,preserve_host=True),url_identity(dataset_url,preserve_host=True)
    if not own or own!=source or own['kind']!='socrata':return False
    path=urlsplit(url)
    return (path.path==f"/api/views/{own['dataset']}/rows.csv" and
            parse_qs(path.query)=={'accessType':['DOWNLOAD']})


def authorized_url(url, contract, graph):
    from .evidence_graph import representation
    target=representation(url)
    if not target:return False
    if graph.get('anchors') and provider_export(target,contract['source']['dataset_url']):return True
    for key in graph['authorized']:
        node=graph['nodes'][key]
        if node['publisher'] and any(link['predicate']=='distributes_resource' and link['target_url']==target
                                     for link in node['distributions']):return True
    return False


def reference_receipt(file, root):
    if file.get('role')!='public_evidence' or not file.get('receipt_path'):return None
    receipt_path=Path(file['receipt_path'])
    if receipt_path.is_symlink() or not receipt_path.resolve().is_relative_to(Path(root).resolve()):
        raise ValidationFailure('Public resource receipt escaped the trusted instance')
    if not receipt_path.is_file() or receipt_path.stat().st_size>65536:
        raise ValidationFailure('Public resource receipt is missing or oversized')
    receipt=json.loads(receipt_path.read_text())
    digest=receipt.get('sha256')
    path=receipt_path.parent/'sha256'/str(digest)
    if (receipt.get('status')!='fetched' or not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest)
            or file.get('sha256')!=digest or path.is_symlink() or not path.is_file()
            or Path(file['path']).resolve()!=path.resolve() or Path(file['path']).is_symlink()
            or receipt.get('final_url')!=file.get('evidence_url')
            or receipt.get('size')!=file.get('size') or path.stat().st_size!=file.get('size')
            or file_hash(path)!=digest):
        raise ValidationFailure('Public resource bytes or receipt are inconsistent')
    try:
        if datetime.fromisoformat(receipt['fetched_at'].replace('Z','+00:00')).tzinfo is None:raise ValueError()
    except (KeyError,ValueError,TypeError,AttributeError) as exc:
        raise ValidationFailure('Historical resource receipt requires its actual retrieval time') from exc
    return {'url':receipt['final_url'],'sha256':digest,'receipt_sha256':file_hash(receipt_path),
            'fetched_at':receipt['fetched_at'],'file_id':file['id']}


def bind_uploads(contract,files,graph,root,work_dir,cancelled=lambda:None,*,completeness=None):
    from .arcgis_query import endpoint
    from .intakereaders import detect_format
    from .table_plan import input_resources,physical_resources
    from .representation_binding import compare_csv
    from . import parser_guard
    if files is None:return []
    admitted={f['id']:f for f in files}
    references=[]
    for file in files:
        cancelled()
        if file.get('role')!='public_evidence':continue
        url=file.get('evidence_url')
        if not authorized_url(url,contract,graph):continue
        receipt=reference_receipt(file,root)
        if receipt:references.append((file,receipt))
    result=[]
    for resource in input_resources(contract):
        url=resource.get('source_url') or contract['source']['dataset_url']
        if endpoint(url):continue # Exact ArcGIS query binder owns this protocol.
        # Only the independently replayed host proof is passed here. A proposed
        # contract, cached QA or receipt label cannot supply this capability.
        if any(p.get('role')==resource['role'] and p.get('status')=='verified'
               and p.get('input_sha256')==admitted.get(resource.get('file_id'),{}).get('sha256')
               for p in (completeness or {}).get('resources',[])):
            continue
        for position,part in enumerate(physical_resources(resource)):
            upload=admitted[part['file_id']];matches=[]
            for reference,receipt in references:
                cancelled()
                if resource.get('source_url') and receipt['url']!=resource['source_url']:continue
                proof=None
                if upload['sha256']==reference['sha256'] and upload['size']==reference['size']:
                    proof={'rule':'exact_resource_bytes'}
                elif detect_format(reference,cancelled)=='zip' and upload.get('archive_member'):
                    member=parser_guard.call('zip_member_hash',[reference,upload['archive_member']],cancelled)
                    if member and member['sha256']==upload['sha256'] and member['size']==upload['size']:
                        proof={'rule':'exact_archive_member_bytes','member':upload['archive_member'],'member_receipt':member}
                elif detect_format(reference,cancelled)=='csv' and detect_format(upload,cancelled)=='csv':
                    comparison=compare_csv(reference,upload,Path(work_dir)/'representation-bindings',
                        reference_table=part.get('table'),upload_table=part.get('table'),cancelled=cancelled)
                    if comparison['equivalent']:proof={'rule':'replayed_csv_representation','comparison':comparison}
                if proof:matches.append({'version':VERSION,'role':resource['role'],'partition_index':position,
                    'upload_file_id':upload['id'],'upload_sha256':upload['sha256'],'reference':receipt,**proof,
                    'scope':'Complete uploaded representation; does not establish temporal completeness or deletion authority'})
            # Same resource can have several historical retrieval receipts. All
            # exact receipts remain evidence; competing resource identities need
            # an explicit source_url instead of choosing by a similar schema.
            if not matches or len({m['reference']['url'] for m in matches})!=1:
                raise NeedsInput('Uploaded content lacks one complete binding to a scoped official resource.',[],
                    {'grounding':{'issues':[{'code':'OFFICIAL_UPLOAD_UNBOUND','role':resource['role'],
                        'file_id':upload['id'],'candidate_resources':len({m['reference']['url'] for m in matches}),
                        'message':'Fetch the exact current or historical resource, or replay a supported complete representation conversion; schema, URL and sampled matches are insufficient.'}]}})
            result.append(matches[0])
    return result
