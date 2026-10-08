"""Bounded trusted input diagnostics; never forwards adapter exception text."""
from .canonical import ContractError, project
from .table_plan import iter_resource


def diagnose_projection(contract, files, mode='sample', check_cancelled=lambda:None, max_rows=1000000,native_context=None):
    """Find the first deterministic mapping failure without sending a raw row.

    This is troubleshooting, not QA admission. A bad adapter can fail before
    emitting candidates; trusted replay can still identify a date/count/category
    error. Whole-file QA remains mandatory after the error is corrected.
    """
    from .trusted_qa import validate_contract
    roles=validate_contract(contract,files,native_context=native_context)
    admitted={f['id']:f for f in files};counts={};total=0
    for role,resource in roles.items():
        counts[role]=0
        for locator,raw in iter_resource(resource,admitted,check_cancelled=check_cancelled):
            if mode=='sample' and counts[role]>=1000:break
            check_cancelled()
            if total>=max_rows:
                return {'status':'bounded','diagnostic_only':True,'checked_rows':counts,'message':'Diagnostic row budget reached; no admission was attempted.'}
            total+=1;counts[role]+=1
            try:project(contract,role,locator,raw)
            except ContractError as exc:
                return {'status':'mapping_error','diagnostic_only':True,'checked_rows':counts,
                    'issue':{'role':role,'row_locator':locator,'type':'ContractError','message':str(exc)}}
    return {'status':'no_mapping_error_in_checked_rows','diagnostic_only':True,'checked_rows':counts,
        'message':'Trusted projection did not reproduce an input mapping failure. Inspect adapter code at the reported error line. This does not authorize publication.'}
