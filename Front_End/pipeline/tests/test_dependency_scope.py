import copy
from arsia_pipeline.dependency_scope import scope, compatible


def record(fmt='csv', lookup=False):
    contract={'resources':[{'role':'crash','table':{'format':fmt}}]}
    if lookup:contract['lookup_tables']=[]
    return {'contract':contract,'dependency_scope':scope(contract),'dependencies':{
        'policy':'same', 'reuse':{'dependency_scope.py':'same'}, 'trusted':{
            'workbook_plan.py':'old','lookup_plan.py':'old','trusted_qa.py':'same','canonical.py':'same','intakereaders.py':'same'}}}


def test_unused_workbook_and_lookup_change_can_replay_but_core_changes_cannot():
    r=record();new=copy.deepcopy(r['dependencies'])
    for name in ('workbook_plan.py','lookup_plan.py'):new['trusted'][name]='new'
    assert compatible(r,new)
    for name in ('trusted_qa.py','canonical.py','intakereaders.py'):
        changed=copy.deepcopy(new);changed['trusted'][name]='new'
        assert not compatible(r,changed)
    changed=copy.deepcopy(new);changed['reuse']['dependency_scope.py']='new'
    assert not compatible(r,changed)


def test_used_capability_and_missing_or_forged_scope_require_exact_dependencies():
    for r,name in ((record('xlsx'),'workbook_plan.py'),(record(lookup=True),'lookup_plan.py')):
        changed=copy.deepcopy(r['dependencies']);changed['trusted'][name]='new'
        assert not compatible(r,changed)
        r['dependency_scope']['unused_trusted_modules'].append(name)
        assert not compatible(r,changed)
    r=record();r.pop('dependency_scope');changed=copy.deepcopy(r['dependencies']);changed['trusted']['workbook_plan.py']='new'
    assert not compatible(r,changed)
