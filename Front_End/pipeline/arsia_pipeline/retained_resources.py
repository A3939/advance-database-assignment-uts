"""Unverified auxiliary rows retained outside all canonical facts and relations.

This is a capability restriction, not an assertion that the auxiliary data is
valid or an exclusion threshold. Structure/integrity errors still block reading.
"""
import re
from .errors import ValidationFailure

VERSION = 'retained-auxiliary-v1'


def validate(contract, files):
    rows=contract.get('retained_resources',[])
    if not isinstance(rows,list) or len(rows)>24:
        raise ValidationFailure('Retained auxiliary declarations must be a bounded list')
    roles={r['role'] for r in contract.get('resources',[])+contract.get('lookup_tables',[])}
    facts=contract.get('resources',[])
    admitted={f['id'] for f in files}
    for r in rows:
        if (not isinstance(r,dict) or set(r)!={'role','grain','file_id','table','reason','requested'}
                or r.get('grain') not in {'unit','casualty'}
                or not isinstance(r.get('role'),str) or not re.fullmatch('[a-z][a-z0-9_]{0,63}',r['role'])
                or r['role'] in roles or r.get('file_id') not in admitted or not isinstance(r.get('table'),dict)
                or type(r.get('requested')) is not bool or not isinstance(r.get('reason'),str)
                or not 12<=len(r['reason'])<=2000):
            raise ValidationFailure('Retained auxiliary inputs require a unique role, exact input/table, grain, unresolved reason and requested capability')
        if any(f['grain']==r['grain'] for f in facts):
            raise ValidationFailure('A partly unresolved auxiliary grain cannot also claim verified records of that grain')
        if any(rel.get('parent')==r['role'] or rel.get('child')==r['role'] for rel in contract.get('relations',[])):
            raise ValidationFailure('Verified facts cannot depend on an unresolved auxiliary relationship')
        roles.add(r['role'])
    return rows


def limitations(contract):
    return [{'role':r['role'],'capability':'units' if r['grain']=='unit' else 'casualty_records',
             'status':'unverified','requested':r['requested'],'reason':r['reason'],
             'actual':'Original auxiliary records retained; no records, counts or relationships derived from this resource',
             'target_satisfied':not r['requested']}
            for r in contract.get('retained_resources',[])]
