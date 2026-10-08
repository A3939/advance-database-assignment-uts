import json

from arsia_pipeline.context_memory import build_context_memory,LAYOUT


def step(name,result,arguments=None,status='succeeded'):
    return {'name':name,'result':result,'arguments':arguments or {},'status':status}


def profile(file_id,n=100,complete=True):
    columns=[]
    for name in [f'field_{index}' for index in range(35)]+['ID','Crash Date','Severity','Year','Month','Fatalities','Casualties']:
        value={'name':name,'types':{'text':n},'null_or_empty_count':0,'distinct_nonempty_count':n,'duplicate_nonempty_count':0,
               'numeric_min':None,'numeric_max':None,'date_min':None,'date_max':None,'date_shapes':{},
               'consistent_date_format_candidates':[],'frequencies':[]}
        if name=='Crash Date': value.update(date_min='2020-01-01',date_max='2024-12-31',date_shapes={'slash_date_requires_order_evidence':n},consistent_date_format_candidates=[{'format':'%d/%m/%Y','range':['2020-01-01','2024-12-31']}])
        if name=='Severity': value.update(distinct_nonempty_count=2,duplicate_nonempty_count=n-2,frequencies=[{'value':'Fatal','count':3},{'value':'Injury','count':n-3}])
        if name=='Year': value.update(types={'integer':n},numeric_min=2020,numeric_max=2024)
        columns.append(value)
    return {'file_id':file_id,'table':{'table_id':'default','format':'csv','encoding':'utf-8','header':[c['name'] for c in columns]},
            'row_count':n,'complete':complete,'columns':columns,'unique_column_candidates':[['ID']], 'row_samples':[{'name':'PERSON SECRET'}]}


def test_three_complete_tables_preserve_late_columns_ranges_keys_and_categories():
    records=[]
    for fid in ['crash','unit','person']:
        value=profile(fid)
        records.append(step('inspect_bundle',{'resources':[{'file_id':fid,'name':fid+'.csv','tables':[value['table']]}]}))
        records.append(step('profile_dataset',value))
    memory=build_context_memory(records)
    assert len(memory['profiles'])==3 and not memory['bounded']
    assert len(json.dumps(memory).encode())<25000
    for value in memory['profiles']:
        columns={c[0]:dict(zip(LAYOUT,c)) for c in value['columns']}
        assert set(columns)==set(profile('unused')['table']['header'])
        assert columns['Crash Date']['consistent_date_format_candidates'][0]['format']=='%d/%m/%Y'
        assert columns['Year']['numeric_range']==[2020,2024]
        assert columns['Severity']['frequencies'][0]=={'value':'Fatal','count':3}
        assert value['unique_column_candidates']==[['ID']]
    assert 'PERSON SECRET' not in json.dumps(memory)


def test_latest_complete_profile_is_not_overwritten_by_partial_or_error():
    records=[step('profile_dataset',profile('a')),step('profile_dataset',profile('a',10,False)),step('profile_dataset',{'file_id':'a','status':'error'})]
    memory=build_context_memory(records)
    assert len(memory['profiles'])==1 and memory['profiles'][0]['row_count']==100 and memory['profiles'][0]['complete']


def test_latest_parser_is_retained_per_table_and_different_tables_stay_distinct():
    original=profile('a');changed=profile('a');changed['table']['encoding']='cp1252'
    other=profile('a');other['table']['table_id']='other'
    records=[step('profile_dataset',original),step('profile_dataset',changed,{'parser':{'encoding':'cp1252'}}),step('profile_dataset',other)]
    memory=build_context_memory(records)
    assert len(memory['profiles'])==2
    assert memory['profiles'][0]['table']['encoding']=='cp1252'


def test_relations_keep_aggregate_counts_without_raw_key_diagnostics():
    result={'child_file_id':'units','parent_file_id':'crashes','child_fields':['year','id'],'parent_fields':['year','id'],
            'metrics':{'parent_rows':100,'child_rows':120,'unmatched_children':2,'ambiguous_parent_children':0},'structurally_valid':False,
            'diagnostics':[{'key':'PRIVATE IDENTIFIER'}]}
    memory=build_context_memory([step('inspect_relations',result)])
    assert memory['relations'][0]['metrics']['unmatched_children']==2
    assert 'PRIVATE IDENTIFIER' not in json.dumps(memory)


def test_citations_from_older_completed_steps_stay_exact_with_readable_file_ids():
    span={'document_id':'doc-one','quote':'Exact official fatalities definition.','start':400,'end':436,'url':'https://example.gov.au/dictionary'}
    records=[step('read_document',{'document_id':'doc-one','file_id':'file-doc','citation_spans':[span],'text':'UNNEEDED DOCUMENT BODY'},{'search':'fatalities'})]
    records += [step('inspect_bundle',{'resources':[]}) for _ in range(30)]
    memory=build_context_memory(records)
    assert memory['citations'][0]['quote']==span['quote']
    assert memory['citations'][0]['file_id']=='file-doc'
    assert 'UNNEEDED DOCUMENT BODY' not in json.dumps(memory)


def test_unsafe_field_values_and_internal_paths_never_enter_memory():
    value=profile('a')
    value['columns'][0]['frequencies']=[{'value':'PERSON NAME','count':1}]
    value['table']['path']='/private/secret'
    memory=build_context_memory([step('profile_dataset',value)])
    assert 'PERSON NAME' not in json.dumps(memory) and '/private' not in json.dumps(memory)


def test_extreme_evidence_is_bounded_without_truncating_citation_text():
    records=[]
    for index in range(100):
        quote=f'Quote {index}: '+('official definition '*100)
        records.append(step('read_document',{'document_id':f'doc-{index}','citation_spans':[{'document_id':f'doc-{index}','quote':quote}]}))
    memory=build_context_memory(records,max_bytes=5000)
    assert len(json.dumps(memory,ensure_ascii=False,separators=(',',':')).encode())<=5000
    assert memory['bounded'] and memory['omitted']['citations']>0
    for span in memory['citations']:
        assert span['quote']==records[int(span['document_id'].split('-')[1])]['result']['citation_spans'][0]['quote']


def test_old_explicit_crs_and_late_field_fact_survive_citation_pressure_without_source_branches():
    text='Coordinate reference system: EPSG:2193, authoritative projected coordinates. Crash Date is dd/mm/yyyy. Severity uses documented source categories.'
    records=[step('profile_dataset',profile('a')),step('read_document',{'document_id':'doc-official','file_id':'official-file','citation_spans':[{'document_id':'doc-official','quote':text,'start':500,'end':500+len(text)}]})]
    for index in range(25):
        records.append(step('read_document',{'document_id':f'later-{index}','citation_spans':[{'document_id':f'later-{index}','quote':str(index)+' later unrelated official text '*35}]}))
    memory=build_context_memory(records,max_bytes=10000)
    facts=memory['official_text_facts']
    crs=next(value for value in facts if value['topic']=='coordinate_reference')
    assert 'EPSG:2193' in crs['quote'] and crs['document_id']=='doc-official'
    assert crs['quote']==text[crs['start']-500:crs['end']-500]
    assert any(value['topic']=='date_format' for value in facts)
    assert any(value['field']=='Severity' for value in facts)
    assert len(json.dumps(memory,ensure_ascii=False,separators=(',',':')).encode())<=10000
