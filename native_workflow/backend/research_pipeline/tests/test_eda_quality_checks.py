import copy,json
from pathlib import Path
import pytest
from jsonschema import Draft202012Validator,ValidationError
from research_pipeline import eda_quality_checks_v3 as qc,eda_display_catalog_v5 as dc
from research_pipeline import eda_display_catalog as old,eda_plot_policy as policy,eda_questions_v6 as q

@pytest.fixture
def cases():
    return json.loads((Path(__file__).parent/'fixtures/eda_quality_cases.json').read_text(encoding='utf8'))

def build(cases,drug):
    c=cases[drug];t={x['dataset_id']:x for x in c['tables']}
    original=policy.normalize({s['id']:s for s in c['plots']},t)
    return t,original,qc.prepare(original,t)

def test_mixed_block_reproduced_and_corrected_losslessly(cases):
    t,oldc,c=build(cases,'meropenem'); before=copy.deepcopy(t)
    key='MERO_STRAIN_MIC__S1'
    assert len(old.materialize(oldc[key],t)[0]['rows'])==14
    p,_=dc.materialize(c[key],t)
    assert len(p['rows'])==6 and all(r['y'] is not None for r in p['rows'])
    assert [r['y'] for r in p['rows']]==[.25,.5,2,4,8,16]
    assert len(p['context_rows'])==4
    assert p['context_rows'][0]['values']['MIC as printed / method']=='0.5 to 1.0 mg/L'
    assert {r['role'] for r in p['semantic_audit']['rows']}=={'OBSERVATION','STRUCTURE','CONTEXT_OBSERVATION'}
    assert len(p['semantic_audit']['rows'])==14 and t==before

@pytest.mark.parametrize('change',['value','status','add','notes','columns'])
def test_mixed_block_changes_fail_closed(cases,change):
    t,original,_=build(cases,'meropenem');table=t['T0036']
    if change=='value':table['records'][-1]['source_raw_values']['c002_meropenem_mg_liter']='changed'
    elif change=='status':table['records'][0]['value_status']['c002_meropenem_mg_liter']='BLQ'
    elif change=='add':table['records'].append(copy.deepcopy(table['records'][-1]))
    elif change=='notes':table['notes']+='changed'
    else:table['columns'][0]['unit']='mg/L'
    with pytest.raises(ValueError,match='table-block'):qc.prepare(original,t)

def test_summary_nd_zero_and_units_retained(cases):
    t,_,c=build(cases,'meropenem');p,_=dc.materialize(c['MERO_REPORTED_PD__S3'],t)
    nd=next(r for r in p['rows'] if r['category']=='AB1137')
    assert nd['y'] is None and nd['status_label']=='ND'
    avg=next(r for r in p['rows'] if r['category']=='Avg')
    assert avg['display_role']=='SOURCE_SUMMARY' and avg['category_label'].endswith('[source summary]')
    t,_,c=build(cases,'voriconazole');p,_=dc.materialize(c['VORI_REPORTED_PD__S4'],t)
    r=p['rows'][-1]
    assert r['raw_y']==r['status_label']=='24 ± 17' and r['y'] is None
    assert 'unit not reported' in ' '.join(p['y_label'].split()) and '24-h' in p['y_label']
    p,_=dc.materialize(c['VORI_PK_LINEAR__S1'],t)
    assert len([r for r in p['rows'] if r['raw_y']==0 and r['zero_qualification']])==2
    assert 'Cmin 0.36' in p['caption'] and '±0.2 mg/L' in p['caption']
    assert all(r['original_status']=='QUANTIFIED' for r in p['rows'] if r['raw_y']==0)

def test_current_plan_retains_final_and_scopes_history():
    p={'analyses':['old'],'open_items':['Images not yet available'],'dataset_dispositions':['old']}
    f={'task_decisions':['new'],'open_items':['Original publication not reviewed'],'dataset_dispositions':['new']}
    result=qc.current_plan(p,f)
    assert result['open_items']==f['open_items'] and result['dataset_dispositions']==['new']
    assert result['historical_EP_open_items']['stage']=='EP_BEFORE_RENDER'
    e=qc.stage_evidence('EI',{'figure_bundle':{'figures':[{'figure_id':'V','image_ref':{'sha256':'abc'},'image_supplied_to_model':True}]}})
    assert e['generated_eda_images'][0]['transported_to_this_call'] is True
    assert e['generated_eda_images'][0]['inspection']=='TO_BE_DECLARED_BY_REVIEWER'
    assert not e['original_publication_images']['provided_in_this_call']

def sample():
    quality={'figures':{'V':{'render_facts':{'elements':['POINTS']},'record_ids':['R1']}}}
    findings={'figure_checks':[{'figure_id':'V','inspection':'INSPECTED','note':'Points inspected'}],
      'findings':[{'record_scope':['R1'],'visual_support':{'status':'OBSERVED','figure_ids':['V'],
                   'element_claims':[{'figure_id':'V','elements':['POINTS']}]}}]}
    return findings,quality

@pytest.mark.parametrize('bad',['CONNECTING_LINES','ERROR_BARS','CONTEXT_TABLE'])
def test_impossible_visual_claims_rejected(bad):
    f,quality=sample();f['findings'][0]['visual_support']['element_claims'][0]['elements']=[bad]
    with pytest.raises(ValueError,match='absent'):qc.validate_consistency(f,quality)

def test_uninspected_and_wrong_records_rejected():
    f,quality=sample();assert qc.validate_consistency(f,quality)['status']=='PASS'
    f['figure_checks'][0]['inspection']='NOT_ASSESSED'
    with pytest.raises(ValueError,match='uninspected'):qc.validate_consistency(f,quality)
    f['figure_checks'][0]['inspection']='INSPECTED';f['findings'][0]['record_scope']=['other']
    with pytest.raises(ValueError,match='no record'):qc.validate_consistency(f,quality)

def test_er_cannot_pass_partial_checks():
    r={'decision':'PASS','quality_checks':{'source_semantics':'PASS','readability':'PASS','figure_text_stage_consistency':'NOT_ASSESSED'}}
    with pytest.raises(ValueError,match='all three'):qc.validate_review(r)
    r['decision']='NEEDS_REVIEW';qc.validate_review(r)

def test_contract_mandatory_checks_survive_wire_conversion():
    schema=q.strict_schema(q.findings_schema({'D':{'records':[{'record_id':'R'}]}},['V']))
    assert 'figure_checks' in schema['required']
    assert all('element_claims' in v['properties']['visual_support']['required'] for v in schema['properties']['findings']['items']['anyOf'])
    rs=q.strict_schema(q.review_schema());assert 'quality_checks' in rs['required']
    assert set(rs['properties']['quality_checks']['required'])=={'source_semantics','readability','figure_text_stage_consistency'}

def test_original_source_facts_are_not_modified_by_labels(cases):
    for drug in cases:
        t,_,c=build(cases,drug)
        for s in c.values():
            p,_=dc.materialize(s,t)
            for r in p['rows']:
                raw=next(x for x in t[r['dataset_id']]['records'] if x['record_id']==r['record_id'])
                assert r['raw_y']==raw['source_raw_values'][r['y_column']]
                assert r['original_status']==raw['value_status'][r['y_column']]

def test_tick_switch_is_not_exposed_as_operation_permission(cases):
    t,_,c=build(cases,'voriconazole');s=c['VORI_MIC__S1']
    assert s['axis_detail']['enabled'] is False
    assert old.brief(s)['axis_detail']['enabled'] is False
    assert 'axis_detail' not in dc.brief(s)
    assert dc.brief(s)['source_fields']==old.brief(s)['source_fields']

def test_dosing_interval_is_not_elapsed_sampling_time(cases):
    t,original,_=build(cases,'voriconazole')
    s=original['VORI_PK_LINEAR__S1'];selector=s['source_recipe']['series'][0]
    for col in t['T0001']['columns']:
        if col['id']==selector['x']:col['header']='Interval (h)'
        if col['id']==selector['y']:col.update(meaning='DOSE',unit='mg/kg',header='Dose (mg/kg)')
    fixed=qc.prepare({'V':s},t)['V']
    assert fixed['x_label']=='Interval (h)'
    assert fixed['source_recipe']['axis_detail']=={'enabled':False,'source_interval_ticks':True}
