import copy

from arsia_pipeline.issue_progress import VERSION, host_scope, issue_identity, progress_report

SETTINGS = {'warn_after_tools': 3, 'stop_after_tools': 6}
SCOPE = {'source_id':'source', 'dataset_url':'https://data.example.gov.au/source',
         'roles':{'crash':{'grain':'crash','key':['ID']}}, 'inputs':{'f':'a'*64}, 'policy_version':'policy-test'}


def step(number, name='fetch_public_source', value=None, status='succeeded', mode='sample', scope=None, **args):
    return {'id':number,'name':name,'status':status,'arguments':args,
            'result':{**(value or {}),'host_context':{'run_mode':mode,'progress_scope':scope or SCOPE}}}


def issue(code='CRS_UNGROUNDED', **kwargs):
    return {'code':code,'kind':'evidence_missing','role':'crash','field':'X','claim':'geography',**kwargs}


def blocked(number, issues=None, **kwargs):
    return step(number,'preflight_contract',{'ok':False,'blockers':issues if issues is not None else [issue()]},**kwargs)


def test_new_hashes_urls_quotes_and_unrelated_edits_cannot_renew_issue_allowance():
    steps=[blocked(1)]
    for i in range(2,8):
        steps.append(step(i,'fetch_public_source' if i%2 else 'read_document',
                          {'sha256':str(i)*64,'url':f'https://data.example.gov.au/new/{i}',
                           'document_id':f'doc-{i}','citation_spans':[{'quote':f'Changed quote {i}'}]}))
    report=progress_report(steps,SETTINGS)
    assert report['state']=='stalled' and report['meaningful_events']==0
    assert len(report['unresolved_issues'])==1 and report['tools_without_progress']>=6


def test_only_whole_matching_gate_pass_resolves_issue():
    steps=[blocked(1),step(2,'run_adapter',{'status':'succeeded'})]
    assert progress_report(steps,SETTINGS)['unresolved_issues']
    steps.append(step(3,'preflight_contract',{'ok':True}))
    report=progress_report(steps,SETTINGS)
    assert not report['unresolved_issues'] and report['last_progress_step_id']==3


def test_new_early_failure_does_not_silently_resolve_previous_issue():
    report=progress_report([blocked(1),blocked(2,[issue('COUNT_MEANING_UNGROUNDED',field='TOTAL')])],SETTINGS)
    assert {x['identity']['code'] for x in report['unresolved_issues']}=={'CRS_UNGROUNDED','COUNT_MEANING_UNGROUNDED'}
    assert report['meaningful_events']==0


def test_sample_pass_does_not_renew_or_clear_old_full_block():
    steps=[step(1,'validate_candidate',{'qa':[{'code':'QA06','status':'block'}]},status='failed',mode='full')]
    steps += [step(i) for i in range(2,7)]
    steps.append(step(7,'validate_candidate',{'status':'sample_only','qa':[{'code':'QA06','status':'pass'}]},mode='sample'))
    report=progress_report(steps,SETTINGS)
    assert report['state']=='stalled' and report['global_tools_without_progress']==0
    assert report['unresolved_issues'][0]['identity']['gate']=='validation.full'


def test_success_from_another_source_or_policy_cannot_clear_issue():
    for altered in [{**SCOPE,'source_id':'other'},{**SCOPE,'policy_version':'another'}]:
        report=progress_report([blocked(1),step(2,'preflight_contract',{'ok':True},scope=altered)],SETTINGS)
        assert report['unresolved_issues']


def test_exact_issue_signature_ignores_web_noise_preserves_semantic_scope():
    first=issue_identity(issue(message='one',url='https://a',sha256='a',quote='first'),SCOPE,'preflight')[0]
    assert issue_identity(issue(message='two',url='https://b',sha256='b',quote='second'),SCOPE,'preflight')[0]==first
    for variant in [issue(field='Y'),issue(role='unit'),issue(required_evidence_type='unit'),issue(declared_crs='EPSG:4283')]:
        assert issue_identity(variant,SCOPE,'preflight')[0]!=first
    assert issue_identity(issue(),{**SCOPE,'policy_version':'changed'},'preflight')[0]!=first


def test_three_unchanged_checks_prompt_replan_without_new_stop_budget():
    report=progress_report([blocked(i) for i in range(1,4)],{'warn_after_tools':20,'stop_after_tools':40})
    assert report['state']=='replan' and report['unresolved_issues'][0]['observations']==3
    assert report['tools_without_progress']==3


def test_complete_measurements_before_blockage_count_once_and_copies_are_same_input():
    value={'file_id':'f','table':{'table_id':'default'},'complete':True,'row_count':20,'columns':[]}
    steps=[step(1,'profile_dataset',value),step(2,'profile_dataset',value)]
    renamed={**value,'file_id':'renamed'}
    steps.append(step(3,'profile_dataset',renamed,scope={**SCOPE,'inputs':{'renamed':'a'*64}}))
    assert progress_report(steps,SETTINGS)['meaningful_events']==1
    steps.append(blocked(4))
    steps.append(step(5,'profile_dataset',{**value,'row_count':50},scope={**SCOPE,'inputs':{'f':'b'*64}}))
    assert progress_report(steps,SETTINGS)['meaningful_events']==1


def test_running_step_is_not_counted_and_resume_rebuild_is_deterministic():
    steps=[blocked(1),step(2,status='running')]
    first=progress_report(steps,SETTINGS)
    assert first['completed_tools']==1 and first==progress_report(copy.deepcopy(steps),SETTINGS)
    assert first['version']==VERSION


def test_partial_qa_progress_requires_explicit_pass_and_cannot_mask_other_stale_issue():
    one={'qa':[{'code':'Q1','status':'block'},{'code':'Q2','status':'block'}]}
    two={'qa':[{'code':'Q1','status':'pass'},{'code':'Q2','status':'block'}]}
    steps=[step(1,'validate_candidate',one,status='failed',mode='full'),
           step(2,'validate_candidate',two,status='failed',mode='full')]
    report=progress_report(steps,SETTINGS)
    assert {r['identity']['code'] for r in report['unresolved_issues']}=={'Q2'}
    assert report['last_progress_step_id']==2
    steps.extend(step(i,'validate_candidate',two,status='failed',mode='full') for i in range(3,8))
    assert progress_report(steps,SETTINGS)['state']=='stalled'


def test_same_code_pass_and_block_is_not_resolution():
    steps=[step(1,'validate_candidate',{'qa':[{'code':'Q1','status':'block'}]},status='failed'),
           step(2,'validate_candidate',{'qa':[{'code':'Q1','status':'pass'},{'code':'Q1','status':'block'}]},status='failed')]
    report=progress_report(steps,SETTINGS)
    assert report['meaningful_events']==0 and report['unresolved_issues']


def test_repeated_wording_changes_remain_one_unclassified_failure():
    steps=[step(i,'run_adapter',{'status':'error','type':'ValueError','message':f'Different {i}'},status='failed') for i in range(1,5)]
    report=progress_report(steps,SETTINGS)
    assert len(report['unresolved_issues'])==1 and report['meaningful_events']==0


def test_false_preflight_inside_proposal_is_still_active():
    report=progress_report([step(1,'set_source_contract',{'status':'proposed','preflight':{'ok':False,'blockers':[issue()]}})],SETTINGS)
    assert report['unresolved_issues'] and report['meaningful_events']==0


def test_unidentified_source_problem_can_be_rechecked_for_same_task():
    old={**SCOPE,'source_id':None,'dataset_url':None}
    report=progress_report([blocked(1,scope=old),step(2,'preflight_contract',{'ok':True})],SETTINGS)
    assert not report['unresolved_issues']


def test_host_scope_does_not_throw_while_recording_malformed_proposal():
    assert host_scope({'source':[], 'resources':'bad'},[], 'v')['roles']=={}
    assert host_scope(None,[], 'v')['source_id'] is None


def test_conflicting_values_normalized_without_losing_axis_order():
    one=issue(evidence=[{'crs':'EPSG:4326','url':'one'},{'crs':'EPSG:4283','quote':'two'}])
    two=issue(evidence=[{'crs':'EPSG:4283','url':'renamed'},{'crs':'EPSG:4326','quote':'changed'}])
    assert issue_identity(one,SCOPE,'preflight')[0]==issue_identity(two,SCOPE,'preflight')[0]
    assert issue_identity(issue(axis_order=['x','y']),SCOPE,'preflight')[0]!=issue_identity(issue(axis_order=['y','x']),SCOPE,'preflight')[0]


def test_same_qa_code_for_different_field_cannot_resolve_issue():
    steps=[step(1,'validate_candidate',{'qa':[{'code':'Q1','status':'block','role':'crash','field':'X'}]},status='failed'),
           step(2,'validate_candidate',{'qa':[{'code':'Q1','status':'pass','role':'crash','field':'Y'}]},status='failed')]
    report=progress_report(steps,SETTINGS)
    assert any(r['identity']['subject'].get('field')=='X' for r in report['unresolved_issues'])


def test_late_old_attempt_pass_cannot_clear_current_block():
    steps=[{**blocked(1),'attempt_id':'current'},
           {**step(2,'preflight_contract',{'ok':True}),'attempt_id':'previous'}]
    report=progress_report(steps,SETTINGS,current_attempt='current')
    assert report['unresolved_issues'] and report['meaningful_events']==0


def test_real_admission_receipt_can_clear_required_earlier_gates_only():
    steps=[blocked(1),step(2,'run_adapter',{'status':'failed'},status='failed',mode='full')]
    sample={'status':'sample_only','admission':{'status':'sample_only','policy_version':'policy-test'}}
    steps.append(step(3,'validate_candidate',sample,mode='sample'))
    assert {r['identity']['gate'] for r in progress_report(steps,SETTINGS)['unresolved_issues']}=={'execution.full'}
    full={'status':'validated','admission':{'status':'admitted','policy_version':'policy-test'}}
    steps.append(step(4,'validate_candidate',full,mode='full'))
    assert not progress_report(steps,SETTINGS)['unresolved_issues']


def test_bounded_dispatch_wrappers_do_not_double_count_semantic_no_progress():
    actions=[blocked(1),step(3),step(5)]
    wrapped=[step(0,'codex.exec',{'status':'authorized_for_dispatch'}),actions[0],
             step(2,'codex.exec',{'status':'authorized_for_dispatch'}),actions[1],
             step(4,'codex.wait',{'status':'authorized_for_dispatch'}),actions[2]]
    assert progress_report(wrapped,SETTINGS)==progress_report(actions,SETTINGS)
    # Ignoring transport never grants new progress or bypasses the semantic stop.
    wrapped += [step(i) for i in range(6,12)]
    assert progress_report(wrapped,SETTINGS)['state']=='stalled'
