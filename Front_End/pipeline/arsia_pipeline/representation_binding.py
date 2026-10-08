"""Replayable CSV representation equality, distinct from publisher authority.

Compares every decoded field and row with multiplicity; ordering and the CSV
wrapper may differ. No trimming, aliasing, type coercion or missing-row tolerance.
The caller must separately authorize the reference's actual receipt and scope.
"""
import hashlib
from contextlib import closing
from pathlib import Path
import sqlite3
from uuid import uuid4

from .canonical import stable_json
from .errors import NeedsInput, ValidationFailure
from .intakereaders import detect_tables, iter_table
from .source_knowledge import file_hash

VERSION='csv-record-multiset-v1'


def json_signature(source):
    """Fixed parser-worker operation: object order/whitespace only may differ.

    All values are typed, arrays stay ordered and number tokens stay exact.
    Duplicate object keys are rejected before the ordinary reader could lose
    them. This digest cannot establish publisher authority on its own.
    """
    import json
    if 'path' in source:
        path=Path(source['path'])
        if path.is_symlink() or path.stat().st_size>32*1024**2:
            raise ValidationFailure('JSON representation exceeds its bounded input size')
        raw=path.read_bytes()
    else:
        raw=source['text'].encode('utf-8')
    if len(raw)>32*1024**2 or hashlib.sha256(raw).hexdigest()!=source['sha256']:
        raise ValidationFailure('JSON representation bytes changed')
    class Number(str):pass
    def pairs(items):
        value={}
        for key,item in items:
            if key in value:raise ValidationFailure('JSON representation has duplicate object properties')
            value[key]=item
        return value
    def constant(_):raise ValidationFailure('Non-finite JSON number is not supported')
    try:
        value=json.loads(raw.decode('utf-8-sig'),object_pairs_hook=pairs,
            parse_int=Number,parse_float=Number,parse_constant=constant)
    except (ValueError,UnicodeError,RecursionError) as exc:
        raise ValidationFailure('JSON representation is not valid bounded UTF-8 JSON') from exc
    digest=hashlib.sha256();nodes=0
    def token(kind,value=''):
        encoded=value.encode('utf-8');digest.update(kind+str(len(encoded)).encode()+b':'+encoded)
    def walk(item,depth=0):
        nonlocal nodes
        nodes+=1
        if depth>128:raise ValidationFailure('JSON representation nesting exceeds its supported depth')
        if isinstance(item,Number):token(b'N',item)
        elif isinstance(item,str):token(b'S',item)
        elif item is None:token(b'Z')
        elif isinstance(item,bool):token(b'B','1' if item else '0')
        elif isinstance(item,list):
            token(b'L',str(len(item)))
            for child in item:walk(child,depth+1)
        elif isinstance(item,dict):
            token(b'D',str(len(item)))
            for key in sorted(item):token(b'K',key);walk(item[key],depth+1)
        else:raise ValidationFailure('Unsupported JSON value')
    walk(value)
    return {'version':'json-object-order-v1','sha256':digest.hexdigest(),'nodes':nodes}


def compare_json_document(file,document,cancelled=lambda:None):
    from . import parser_guard
    raw=document['content_bytes']
    reference=parser_guard.call('json_signature',[{'text':raw.decode('utf-8'),'sha256':document['sha256']}],cancelled)
    uploaded=parser_guard.call('json_signature',[file],cancelled)
    return {'version':'json-object-order-v1','equivalent':reference==uploaded,
        'reference_sha256':document['sha256'],'upload_sha256':file['sha256'],
        'reference':reference,'upload':uploaded,
        'scope':'All typed values; object property order and insignificant whitespace only. Arrays and number tokens remain exact.'}


def csv_table(file, hints=None, cancelled=lambda: None):
    # A previous header/encoding/delimiter cannot dictate a changed wrapper.
    # BOM/UTF-8 and unambiguous delimiters are detected; an explicit non-UTF
    # decoder remains only a proposal, proven later by all-field equality.
    try:
        tables=detect_tables(file,{'format':'csv'},cancelled)
    except NeedsInput as exc:
        if not exc.details.get('requires_encoding_evidence') or not (hints or {}).get('encoding'):
            raise
        tables=detect_tables(file,{'format':'csv','encoding':hints['encoding']},cancelled)
    if len(tables)!=1 or tables[0]['format']!='csv':
        raise ValidationFailure('Representation comparison requires one complete CSV table')
    return tables[0]


def compare_csv(reference, upload, work_dir, *, reference_table=None, upload_table=None, cancelled=lambda: None):
    for f in (reference,upload):
        cancelled()
        path=Path(f['path'])
        if (path.is_symlink() or not path.is_file() or path.stat().st_size>512*1024**2
                or path.stat().st_size!=f['size'] or file_hash(path)!=f['sha256']):
            raise ValidationFailure('Representation input bytes changed or exceed the bounded resource size')
    tables=[csv_table(reference,reference_table,cancelled),csv_table(upload,upload_table,cancelled)]
    if sorted(tables[0]['header'])!=sorted(tables[1]['header']):
        return {'version':VERSION,'equivalent':False,'reason':'field_set_differs',
                'reference_sha256':reference['sha256'],'upload_sha256':upload['sha256']}
    directory=Path(work_dir);directory.mkdir(parents=True,exist_ok=True)
    database=directory/('representation-'+uuid4().hex+'.sqlite')
    scans=[]
    with closing(sqlite3.connect(database)) as db:
        db.execute('PRAGMA temp_store=FILE');db.execute('PRAGMA cache_size=-8192')
        db.execute('CREATE TABLE rows(side INTEGER,hash TEXT)')
        for side,(file,table) in enumerate(zip((reference,upload),tables)):
            count=0
            for _,raw in iter_table(file,table,cancelled):
                db.execute('INSERT INTO rows VALUES(?,?)',(side,hashlib.sha256(stable_json(raw).encode()).hexdigest()))
                count+=1
                if count%1000==0:cancelled()
                if count%5000==0:db.commit()
            db.commit()
            digest=hashlib.sha256(stable_json(sorted(table['header'])).encode())
            for index,(value,) in enumerate(db.execute('SELECT hash FROM rows WHERE side=? ORDER BY hash',(side,))):
                if index%1000==0:cancelled()
                digest.update(value.encode('ascii'))
            scans.append({'rows':count,'records_sha256':digest.hexdigest(),
                          'parser':{k:table[k] for k in ('format','encoding','delimiter','header') if k in table}})
    for f in (reference,upload):
        cancelled()
        if Path(f['path']).is_symlink() or file_hash(f['path'])!=f['sha256']:
            raise ValidationFailure('Representation inputs changed during complete comparison')
    return {'version':VERSION,'equivalent':all(scans[0][key]==scans[1][key] for key in ('rows','records_sha256')),
            'reference_sha256':reference['sha256'],'upload_sha256':upload['sha256'],
            'reference':scans[0],'upload':scans[1],
            'scope':'All decoded fields and record multiplicity; source authority, field meanings and fresh QA remain separate',
            'comparison_index_sha256':file_hash(database)}
