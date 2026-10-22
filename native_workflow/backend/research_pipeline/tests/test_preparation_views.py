"""Source-bound cleaning operators: no invented identity, units or time choice."""
import copy
import pytest
from research_pipeline import preparation_views as v


def column(header, meaning, unit, qualifiers=()):
    return {'header': header, 'meaning': meaning, 'unit': unit,
            'qualifiers': list(qualifiers), 'evidence': [{'source': 'F1:T1:A3', 'quote': unit}]}


def test_inherit_reviewed_unit_but_reject_conflict_and_mass_dimension():
    assert v.conversion(column('Mouse 1', 'CONCENTRATION', 'mg/L'), 'concentration_mg_L') == 1
    assert v.conversion(column('C (ng/mL)', 'CONCENTRATION', 'mg/L'), 'concentration_mg_L') is None
    assert v.conversion(column('Kidney (ug/g)', 'CONCENTRATION', 'ug/g'), 'concentration_mg_L') is None
    c=column('Mouse 1', 'CONCENTRATION', 'mg/L');c['evidence']=[]
    assert v.conversion(c, 'concentration_mg_L') is None


def test_statistics_censoring_and_missing_are_distinct():
    c=column('Serum', 'CONCENTRATION', 'mg/L', ['Summary mean ± SD'])
    assert v.typed_value('1.46 ± 0.38', c, 'SOURCE_TEXT_REQUIRES_REVIEW') == {
        'kind': 'SUMMARY', 'value': 1.46, 'spread': .38, 'spread_type': 'SD'}
    assert v.typed_value('1 ± 2', column('C','CONCENTRATION','mg/L'), '')['spread_type']=='UNRESOLVED'
    assert v.typed_value('<LLOQ', c, 'BLQ')['limit'] is None
    assert v.typed_value('<0.1', c, '')['limit']==.1
    assert 'value' not in v.typed_value('5', c, 'CENSORED')
    assert v.typed_value('No sampling',c,'NOT_SAMPLED')['kind']=='MISSING'
    assert v.typed_value('Mean',c,'')['kind']=='SUMMARY_LABEL'
    assert v.typed_value('-1',c,'')['kind']=='INVALID'
    assert v.typed_value('<1e999',c,'')['kind']=='INVALID'
    assert v.typed_value('Bound',column('Reported measure','BINDING','NOT_FOUND'),'')['kind']=='CATEGORY'


def fixture():
    cols=[column('Time (h)','TIME','h'),column('Mouse 1','CONCENTRATION','mg/L'),
          column('Mouse 2','CONCENTRATION','mg/L')]
    metadata={'source_item_id':'F1:T1','columns':cols,'record_category':'NOT_FOUND',
              'source_table':{'column_map':{'a':'Time (h)','b':'Mouse 1','c':'Mouse 2'},'notes':''}}
    r={'record_id':'T0001_R2','source_file_id':'F1','source_sha256':'abc','source_sheet':'Mouse',
       'source_row':2,'source_raw_values':{'a':0,'b':2,'c':'<LLOQ'},'source_cells':{'a':'A2','b':'B2','c':'C2'},
       'value_status':{'a':'QUANTIFIED','b':'QUANTIFIED','c':'BLQ'},'qc_reasons':[]}
    return metadata,[r]


def test_long_view_accounts_for_cells_without_inventing_animals():
    meta,records=fixture();view=v.build_view(meta,records)
    assert len(view['observations'])==2
    assert [o['source_cell'] for o in view['observations']]==['B2','C2']
    assert view['observations'][0]['normalized']['value']==2
    assert view['observations'][1]['typed_value']['kind']=='CENSORED'
    assert all(o['animal_id'] is None for o in view['observations'])
    assert v.verify_view(view,meta,records)==[]
    bad=copy.deepcopy(view);bad['observations'].pop()
    assert v.verify_view(bad,meta,records)
    bad=copy.deepcopy(view);bad['observations'][0]['animal_id']='Mouse 1'
    assert v.verify_view(bad,meta,records)


def test_alternative_times_preserved_without_canonical_choice():
    meta,records=fixture()
    meta['columns'].append(column('Pixel time (h)','TIME','h'))
    meta['source_table']['column_map']['d']='Pixel time (h)'
    records[0]['source_raw_values']['d']=.01;records[0]['source_cells']['d']='D2'
    records[0]['value_status']['d']='QUANTIFIED'
    view=v.build_view(meta,records);obs=view['observations'][0]
    assert [t['time_h'] for t in obs['times']]==[0,.01]
    assert obs['canonical_time_h'] is None
    assert obs['times'][1]['kind']=='DIGITIZED'


def test_local_restriction_does_not_block_other_dataset():
    datasets=[{'id':'T0001','metadata':{'source_item_id':'F1:T1'}},
              {'id':'T0002','metadata':{'source_item_id':'F1:T2'}}]
    qc={'decision':'PASS','errors':[],'datasets':[{'dataset_id':d['id'],'decision':'PASS'} for d in datasets]}
    reviews=[{'dataset_id':d['id'],'review':{'decision':'PASS'}} for d in datasets]
    response={'decision':'REVISE','checks':[{'id':x,'decision':'PASS'} for x in ['T0001','T0002','COMPLETENESS','HANDOFF_SCOPE']]}
    findings=[{'affected_id':'T0001','severity':'BLOCK','required_by':'BEFORE_EDA','code':'SOURCE_UNRESOLVED','reason':'Unresolved source.'}]
    states=v.action_readiness(datasets,qc,reviews,response,findings)
    assert states[0]['actions']['DESCRIPTIVE_EDA']['status']=='RESTRICTED'
    assert states[1]['actions']['DESCRIPTIVE_EDA']['status']=='READY'
    assert all(s['actions']['PK_MODELING']['status']=='RESTRICTED' for s in states)
    ledger=[{'id':'DP-U001','record':{'affected_id':'T0001'},'field':'T0001'}]
    findings[0]['affected_id']='DP-U001'
    scoped=v.action_readiness(datasets,qc,reviews,response,findings,ledger)
    assert scoped[1]['actions']['DESCRIPTIVE_EDA']['status']=='READY'
    findings[0]['affected_id']='T0001, T0002'
    assert all(s['actions']['DESCRIPTIVE_EDA']['status']=='RESTRICTED'
               for s in v.action_readiness(datasets,qc,reviews,response,findings))
    findings[0]['affected_id']='T0001'
    response['checks'][-1]['decision']='REVISE'
    assert all(s['actions']['DESCRIPTIVE_EDA']['status']=='RESTRICTED'
               for s in v.action_readiness(datasets,qc,reviews,response,findings))


def test_summary_row_is_not_an_observation_and_tissue_is_not_volume_concentration():
    meta,rows=fixture()
    meta['columns'][2]=column('Kidney (ug/g)','CONCENTRATION','ug/g',['Summary mean ± SD'])
    meta['source_table']['column_map']['c']='Kidney (ug/g)'
    rows[0]['source_raw_values']['c']='10.57 ± 1.21'
    rows[0]['value_status']['c']='SOURCE_TEXT_REQUIRES_REVIEW'
    view=v.build_view(meta,rows)
    assert view['observations'][1]['normalized'] is None
    assert view['observations'][1]['typed_value']['value']==10.57
    summary=copy.deepcopy(rows[0]);summary['record_id']='T0001_R3';summary['source_row']=3
    summary['source_raw_values']['b']='Mean';summary['value_status']['b']='SOURCE_TEXT_REQUIRES_REVIEW'
    view=v.build_view(meta,rows+[summary])
    assert len(view['observations'])==2 and len(view['summary_rows'])==1


def test_ledger_schema_preserves_mutually_exclusive_outcomes():
    from research_pipeline.handoff_review import ledger_schema
    from research_pipeline.data_agents import HANDOFF_REVIEW
    import jsonschema
    schema=ledger_schema(HANDOFF_REVIEW,['MI1'])['properties']['ledger_outcomes']['items']
    valid={'item_id':'MI1','outcome':'CARRIED','reason':'Retain restriction.',
           'evidence':[],'carried_to':'BEFORE_MODELING','limitation':'NONE'}
    # The source schema may require additional fields; validate a real minimal
    # outcome with exactly its declared keys.
    for key in schema['anyOf'][0]['required']:
        if key not in valid: valid[key]='Source bound explanation.'
    jsonschema.validate(valid,schema)
    valid['limitation']='An inappropriate limitation.'
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(valid,schema)


def test_dosing_interval_is_not_an_observation_time():
    c=column('Interval (h)','TIME','h')
    assert v.time_kind(c)=='INTERVAL'
    assert not v.scalar_eligible(c,'time_h')
    assert v.mapping_factor({'preparation_policy':v.POLICY},{'columns':[c]},
        {'source_header':c['header'],'target':'time_h'}) is None


def test_summary_label_in_spiked_group_column():
    meta,rows=fixture()
    meta['columns'][0]=column('PMB concn (ug/mL)','GROUP_OR_TREATMENT','ug/mL')
    meta['source_table']['column_map']['a']='PMB concn (ug/mL)'
    rows[0]['source_raw_values']['a']='Mean'
    view=v.build_view(meta,rows)
    assert view['observations']==[] and len(view['summary_rows'])==1


def test_explicit_event_schema_keeps_exposure_separate_and_applies_censoring_to_response():
    cols=[column('ID','GROUP_OR_TREATMENT','NOT_FOUND'),column('AMT','CONCENTRATION','mg/L',['nominal exposure']),
          column('AMT_CMT','OTHER','NOT_FOUND'),column('TIME','TIME','h'),
          column('Y','RESPONSE','log10 CFU/mL'),column('CENS','BLQ_OR_FLAG','NOT_FOUND')]
    fields={str(i):c['header'] for i,c in enumerate(cols)}
    meta={'source_item_id':'F1:T1','columns':cols,'source_table':{'column_map':fields,
        'notes':'AMT_CMT=2 rows carry nominal exposure AMT (mg/L); observation rows use AMT_CMT=1. CENS=1 flags censored Y.'}}
    rows=[]
    for i,values in enumerate(([1,1e-8,2,0,'.',0],[1,'.',1,2,3,1]),2):
        rows.append({'record_id':f'T_R{i}','source_row':i,'source_sheet':'S','source_file_id':'F','source_sha256':'h',
            'source_cells':{str(j):f'{chr(65+j)}{i}' for j in range(6)},
            'source_raw_values':dict(zip(fields,values)),
            'value_status':{k:('CENSORED' if k=='4' and i==3 else 'QUANTIFIED') for k in fields}})
    view=v.build_view(meta,rows)
    assert len(view['observations'])==1 and len(view['exposure_events'])==1
    assert view['observations'][0]['source_header']=='Y'
    assert view['observations'][0]['typed_value']['kind']=='CENSORED'
    assert view['exposure_events'][0]['typed_value']['value']==1e-8
    assert not v.scalar_eligible(cols[1],'concentration_mg_L')
    assert all(o['animal_id'] is None for o in view['observations'])


def test_host_aggregates_checks_without_overriding_independent_findings(monkeypatch,tmp_path):
    from research_pipeline import data_agents as d, handoff_review
    import jsonschema
    checks=[{'id':k,'decision':'NEEDS_REVIEW' if k=='T0001' else 'PASS','reason':'Scope-specific result.'}
            for k in ['T0001','T0002','COMPLETENESS','GLOBAL_HANDOFF_CONSTRAINTS']]
    raw={'request_sha256':'hash','checks':checks,'findings':[],'ledger_outcomes':[]}
    original=copy.deepcopy(raw)
    def invoke(run,stage,payload,schema,check,**kwargs):
        assert 'decision' not in schema['properties']
        jsonschema.validate(raw,schema);check(raw);return raw
    monkeypatch.setattr(d,'invoke',invoke)
    result=handoff_review.review(tmp_path,{'preparation_policy':v.POLICY,'due_item_ids':[],
        'expected_check_ids':[c['id'] for c in checks],'supplied_record_scope':[]},d.HANDOFF_REVIEW,lambda:None)
    assert raw==original and 'decision' not in raw
    assert result['decision']=='REVISE' and result['checks']==checks
    assert result['decision_origin']=='HOST_AGGREGATION_OF_INDEPENDENT_CHECKS'


@pytest.mark.parametrize('raw,status,direction,limit', [
    (0,'CENSORED','UNRESOLVED',None), (5,'MISSING_CENSORED_OBSERVATION','UNRESOLVED',None),
    ('<LLOQ','BLQ','LEFT',None), ('>10','CENSORED','RIGHT',10),
    ('<=0.1','CENSORED','LEFT',0.1)])
def test_censor_direction_requires_source_support(raw,status,direction,limit):
    parsed=v.typed_value(raw,column('Y','CONCENTRATION','mg/L'),status)
    assert parsed['kind']=='CENSORED' and parsed['direction']==direction and parsed['limit']==limit
    assert 'value' not in parsed


def test_unspecified_censor_direction_remains_an_operation_restriction():
    meta,rows=fixture();rows[0]['source_raw_values']['b']=0;rows[0]['value_status']['b']='CENSORED'
    view=v.build_view(meta,rows)
    assert 'CENSORING_DIRECTION_UNRESOLVED' in view['operation_restrictions']
    assert view['observations'][0]['raw']==0 and view['observations'][0]['normalized']['limit'] is None


def operation_case(operations, phase='BEFORE_MODELING', decision='NEEDS_REVIEW'):
    datasets=[{'id':'T1','role':'PK_OBSERVATIONS','metadata':{'source_item_id':'F1:T1',
        'normalized_fields':{'time_h':{'source_header':'Time (h)','factor':1}}},
        'observation_summary':{'observation_cells':1},'observation_restrictions':[]}]
    qc={'decision':'PASS','errors':[],'datasets':[{'dataset_id':'T1','decision':'PASS'}]}
    reviews=[{'dataset_id':'T1','review':{'decision':'PASS'}}]
    finding={'code':'SOURCE_GAP','affected_id':'T1','severity':'BLOCK', 'required_by':phase,
             'reason':'A source definition is unresolved.', 'affected_operations':operations}
    response={'operation_policy':v.OPERATION_POLICY,'decision':'REVISE',
        'checks':[{'id':i,'decision':decision if i=='T1' else 'PASS','reason':'Scoped check.'}
                  for i in ['T1','COMPLETENESS','GLOBAL_HANDOFF_CONSTRAINTS']], 'findings':[finding]}
    return datasets,qc,reviews,response,[finding]


@pytest.mark.parametrize('operation,phase', [
    ('LONGITUDINAL_JOIN','BEFORE_MODELING'), ('DOSE_RESPONSE_LINKAGE','BEFORE_INDEX_ANALYSIS'),
    ('CROSS_MATRIX_CONVERSION','BEFORE_MODELING'), ('MIC_WEIGHTED_PTA','BEFORE_PTA'),
    ('TIME_AXIS_SELECTION','BEFORE_EDA'), ('CENSORED_VALUE_CALCULATION','BEFORE_MODELING')])
def test_computation_restrictions_do_not_veto_separate_source_display(operation,phase):
    args=operation_case([operation],phase)
    v.validate_operation_review(args[3],['T1'])
    state=v.action_readiness(*args)[0]
    assert state['actions']['DESCRIPTIVE_EDA']['status']=='READY'
    assert state['operation_restrictions'][0]['operation']==operation
    assert state['other_operations_authorized'] is False
    assert state['actions']['PK_MODELING']['status']=='RESTRICTED'
    assert state['actions']['NCA']['status']=='RESTRICTED'
    assert state['actions']['DESCRIPTIVE_EDA']['conditions']


def test_actual_display_restriction_still_blocks_and_remains_local():
    args=operation_case(['DESCRIPTIVE_EDA'])
    v.validate_operation_review(args[3],['T1'])
    assert v.action_readiness(*args)[0]['actions']['DESCRIPTIVE_EDA']['status']=='RESTRICTED'
    args[0].append({'id':'T2','metadata':{'source_item_id':'F1:T2'}})
    args[1]['datasets'].append({'dataset_id':'T2','decision':'PASS'})
    args[2].append({'dataset_id':'T2','review':{'decision':'PASS'}})
    args[3]['checks'].append({'id':'T2','decision':'PASS'})
    assert v.action_readiness(*args)[1]['actions']['DESCRIPTIVE_EDA']['status']=='READY'


def test_unexplained_or_conflicting_independent_decision_is_rejected():
    from research_pipeline.common import PipelineError
    args=operation_case(['DESCRIPTIVE_EDA'],decision='PASS')
    with pytest.raises(PipelineError,match='conflicts'):v.validate_operation_review(args[3],['T1'])
    args=operation_case(['LONGITUDINAL_JOIN']);args[3]['findings']=[]
    with pytest.raises(PipelineError,match='Unexplained'):v.validate_operation_review(args[3],['T1'])
    args=operation_case([])
    with pytest.raises(PipelineError,match='needs affected_operations'):v.validate_operation_review(args[3],['T1'])
    args=operation_case(['LONGITUDINAL_JOIN','LONGITUDINAL_JOIN'])
    with pytest.raises(PipelineError,match='Invalid operation'):v.validate_operation_review(args[3],['T1'])
    args=operation_case(['MADE_UP_OPERATION'])
    with pytest.raises(PipelineError,match='Invalid operation'):v.validate_operation_review(args[3],['T1'])


def test_legacy_current_phase_gap_does_not_silently_disappear():
    args=operation_case(['LONGITUDINAL_JOIN'],'BEFORE_EDA')
    del args[4][0]['affected_operations']
    assert v.action_readiness(*args)[0]['actions']['DESCRIPTIVE_EDA']['status']=='RESTRICTED'


def test_host_censor_limit_restricts_calculation_not_typed_preservation():
    args=operation_case(['LONGITUDINAL_JOIN'])
    args[0][0]['observation_restrictions']=['CENSORED_LIMIT_UNRESOLVED','CENSORING_DIRECTION_UNRESOLVED']
    state=v.action_readiness(*args)[0]
    assert state['actions']['DESCRIPTIVE_EDA']['status']=='READY'
    assert state['actions']['NORMALIZED_TIME_CONCENTRATION_VIEW']['status']=='READY'
    restriction=next(r for r in state['operation_restrictions'] if r['operation']=='CENSORED_VALUE_CALCULATION')
    assert len(restriction['reasons'])==2


def test_operation_schema_and_decision_checks_run_before_cache(monkeypatch,tmp_path):
    import jsonschema
    from research_pipeline import data_agents as d,handoff_review as h
    from research_pipeline.common import PipelineError
    args=operation_case(['LONGITUDINAL_JOIN'])
    raw={k:copy.deepcopy(args[3][k]) for k in ['checks','findings']}
    raw['findings'][0]['needed_material']='Source linkage evidence.'
    raw.update(request_sha256='hash',ledger_outcomes=[])
    def invoke(run,stage,payload,schema,check,**kwargs):
        item=schema['properties']['findings']['items']
        assert 'affected_operations' in item['required']
        assert 'uniqueItems' not in item['properties']['affected_operations']
        jsonschema.validate(raw,schema);check(raw);return raw
    monkeypatch.setattr(d,'invoke',invoke)
    payload={'preparation_policy':v.POLICY,'operation_policy':v.OPERATION_POLICY,
        'due_item_ids':[],'expected_check_ids':[c['id'] for c in raw['checks']],'supplied_record_scope':[]}
    result=h.review(tmp_path,payload,d.HANDOFF_REVIEW,lambda:None)
    assert result['operation_policy']==v.OPERATION_POLICY
    raw['checks'][0]['decision']='PASS';raw['findings'][0]['affected_operations']=['DESCRIPTIVE_EDA']
    with pytest.raises(PipelineError,match='conflicts'):h.review(tmp_path,payload,d.HANDOFF_REVIEW,lambda:None)


def test_operation_findings_export_preserves_scope_and_original_objects(tmp_path):
    import csv
    from research_pipeline.data_agents import write_findings
    findings=[{'code':'A','affected_id':'T1','reason':'Scope gap','needed_material':'Source evidence',
        'required_by':'BEFORE_MODELING','severity':'BLOCK','affected_operations':['LONGITUDINAL_JOIN','PK_MODELING']}]
    original=copy.deepcopy(findings)
    write_findings(tmp_path,findings)
    with (tmp_path/'evidence_gaps.csv').open(encoding='utf-8-sig',newline='') as handle:
        rows=list(csv.DictReader(handle))
    assert rows[0]['affected_operations']=='LONGITUDINAL_JOIN;PK_MODELING' and findings==original
