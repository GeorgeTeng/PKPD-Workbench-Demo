"""Per-source dimensions, strict unknown qualification, and versioned consumers."""
import copy
import pytest
from research_pipeline import data_coverage_scoped_v3 as cov, data_necessity_scoped_v5 as nec
from research_pipeline import data_assessment_workflow as workflow, data_human_summary_scoped_v4 as summary
from research_pipeline.common import read_json,write_json,PipelineError
from test_data_scoped_contract import scoped, legacy_case, no_provider, answer as prior_answer


def answer(request,**kwargs):
    raw=prior_answer(request,**kwargs)
    if request['payload']['stage']=='DIRECT_DR_COVERAGE':
        for check in raw['checks'].values():
            for field in check['fields'].values():
                for key in ('support_kind','measurement','relation_source_ids'):field.pop(key)
    return raw


def prepared(scoped):
    b=cov.prepare(*scoped)
    request=read_json(b['parts'][0]['request_ref']['path'])
    return b,request,read_json(b['source_catalog_ref']['path']),answer(request)


def scope(catalog,sid,status='SUPPORTED'):
    row=catalog[sid]
    dims=copy.deepcopy(row['measurement'])
    unknown=sorted(cov.unknown_dimensions(dims))
    return {'item_id':row['item_id'],'scope_note':'This exact source only.','source_ids':[sid],
        'status':status,'support_kind':'MEASUREMENT_RECORDS','measurement':dims,
        'column_header':row['column_header'],'recorded_value_presence':'PRESENT',
        'unresolved_dimensions':unknown,'relation_source_ids':[]}


def measure(raw,catalog,*ids):
    f=raw['checks']['RQ1']['fields']['concentration']
    f.update(status='SUPPORTED',unresolved_information='',source_scopes=[scope(catalog,sid) for sid in ids])
    raw['checks']['RQ1']['status']='PARTIAL'
    return f


def test_heterogeneous_source_dimensions_replay_without_cross_source_conversion(scoped):
    source=read_json(scoped[1])
    source['profiles'][1].update(record_level='INDIVIDUAL',exposure_basis='FREE',
        columns=[{'header':'Concentration','meaning':'CFU','unit':'log10 CFU/mL'}])
    write_json(scoped[1],source)
    b,req,c,raw=prepared(scoped)
    f=measure(raw,c,'F1:mouse:A2','F1:rat:A2')
    cov.validate(raw,b['requirements'],c)
    result=cov.run_prepared(scoped[3],generator=lambda *a,**kw:raw)
    assert cov.verify_result(scoped[3]/'coverage.json')==result
    rows=result['checks']['RQ1']['fields']['concentration']['source_scopes']
    assert rows[0]['measurement']!=rows[1]['measurement']
    assert not {'measurement','support_kind'} & f.keys()


def test_original_values_present_unknown_basis_remains_unresolved_qualification(scoped):
    source=read_json(scoped[1]);source['profiles'][0]['exposure_basis']='NOT_FOUND';write_json(scoped[1],source)
    b,req,c,raw=prepared(scoped)
    f=measure(raw,c,'F1:mouse:A2');f['status']='UNRESOLVED'
    f['unresolved_information']='Original values exist; total/free basis is not established.'
    f['source_scopes'][0]['status']='UNRESOLVED'
    raw['checks']['RQ1']['status']='UNRESOLVED'
    cov.validate(raw,b['requirements'],c)
    gaps=nec.base.collect_gaps({'requirements':b['requirements'],'checks':raw['checks']})
    found=gaps['RQ1:F2']['source_scopes'][0]
    assert found['recorded_value_presence']=='PRESENT'
    assert found['unresolved_dimensions']==['basis'] and found['measurement']['basis']=='NOT_FOUND'
    assert nec.gap_scopes(gaps['RQ1:F2'])=={'F1:mouse'}


def test_supported_mouse_and_unresolved_rat_is_partial_preserving_both_sources(scoped):
    source=read_json(scoped[1]);source['profiles'][1]['record_level']='UNKNOWN';write_json(scoped[1],source)
    b,req,c,raw=prepared(scoped)
    f=measure(raw,c,'F1:mouse:A2','F1:rat:A2')
    f['status']='PARTIAL';f['unresolved_information']='Rat experimental record level remains unknown.'
    f['source_scopes'][1]['status']='UNRESOLVED'
    cov.validate(raw,b['requirements'],c)
    assert len(f['source_scopes'])==2


@pytest.mark.parametrize('damage',['supported_unknown','na_unknown','erase_unknown','relabel_basis',
    'cross_source','header_only','other_column','hide_scope','downgrade','old_field_dims','duplicate_dimension'])
def test_unqualified_measurement_claims_stay_rejected(scoped,damage):
    source=read_json(scoped[1]);source['profiles'][0]['exposure_basis']='NOT_FOUND';write_json(scoped[1],source)
    b,req,c,raw=prepared(scoped)
    f=measure(raw,c,'F1:mouse:A2');f['status']='UNRESOLVED';f['unresolved_information']='Basis unknown.'
    s=f['source_scopes'][0];s['status']='UNRESOLVED';raw['checks']['RQ1']['status']='UNRESOLVED'
    if damage=='supported_unknown':s['status']='SUPPORTED';f['status']='SUPPORTED';f['unresolved_information']='';raw['checks']['RQ1']['status']='PARTIAL'
    elif damage=='na_unknown':s['measurement']['basis']='NOT_APPLICABLE';s['unresolved_dimensions']=[]
    elif damage=='erase_unknown':s['unresolved_dimensions']=[]
    elif damage=='relabel_basis':s['measurement']['basis']='FREE'
    elif damage=='cross_source':s['source_ids']=['F1:rat:A2']
    elif damage=='header_only':s['source_ids']=['F1:mouse:A1']
    elif damage=='other_column':s['column_header']='Dose'
    elif damage=='hide_scope':f['status']='SUPPORTED';f['unresolved_information']='';raw['checks']['RQ1']['status']='PARTIAL'
    elif damage=='downgrade':s.update(support_kind='REPORTED_VALUE',measurement=None,column_header='',unresolved_dimensions=[])
    elif damage=='old_field_dims':f['measurement']=s['measurement']
    else:s['unresolved_dimensions']*=2
    with pytest.raises(ValueError):cov.validate(raw,b['requirements'],c)


def test_note_reported_value_has_own_type_not_measured_records(scoped):
    b,req,c,raw=prepared(scoped)
    f=raw['checks']['RQ1']['fields']['concentration']
    f.update(status='SUPPORTED',unresolved_information='',source_scopes=[{
        'item_id':'F1:notes','scope_note':'Reported note value only.','source_ids':['F1:notes:C10'],
        'status':'SUPPORTED','support_kind':'REPORTED_VALUE','measurement':None,'column_header':'',
        'recorded_value_presence':'PRESENT','unresolved_dimensions':[],'relation_source_ids':[]}])
    raw['checks']['RQ1']['status']='PARTIAL'
    cov.validate(raw,b['requirements'],c)


def test_same_item_multiple_columns_retain_separate_dimensions(scoped):
    source=read_json(scoped[1])
    source['profiles'][0]['columns'].append({'header':'Time','meaning':'time','unit':'h'})
    source['source_units'].update({'F1:mouse:B1':'Time','F1:mouse:B2':'1'})
    write_json(scoped[1],source)
    plan=read_json(scoped[0]);inv=read_json(plan['bindings']['inventory']['path'])
    inv['items'][0]['region']['right']=2
    write_json(plan['bindings']['inventory']['path'],inv)
    plan['bindings']['inventory']=cov.rt.file_ref(plan['bindings']['inventory']['path']);write_json(scoped[0],plan)
    b,req,c,raw=prepared(scoped)
    f=measure(raw,c,'F1:mouse:A2','F1:mouse:B2')
    cov.validate(raw,b['requirements'],c)
    assert len(f['source_scopes'])==2 and f['source_scopes'][1]['measurement']['unit']=='h'
    f['source_scopes'][1]['source_ids']*=2
    with pytest.raises(ValueError,match='Duplicate source reference'):cov.validate(raw,b['requirements'],c)
    f['source_scopes'][1]['source_ids']=list(dict.fromkeys(f['source_scopes'][1]['source_ids']))
    f['source_scopes'].append(copy.deepcopy(f['source_scopes'][1]))
    with pytest.raises(ValueError,match='Duplicate typed'):cov.validate(raw,b['requirements'],c)


@pytest.mark.parametrize('key,value',[
    ('exposure_basis','Plasma fraction unbound for the binding value; concentration basis NOT_FOUND'),
    ('record_level','Columns are labeled Mouse 1, Mouse 2 and Mouse 3; cross-time identity is unverified.')])
def test_explicit_unknown_marker_inside_dimension_retains_full_qualifier(scoped,key,value):
    source=read_json(scoped[1]);source['profiles'][0][key]=value;write_json(scoped[1],source)
    b,req,c,raw=prepared(scoped)
    f=measure(raw,c,'F1:mouse:A2');s=f['source_scopes'][0]
    with pytest.raises(ValueError,match='Unknown measurement'):cov.validate(raw,b['requirements'],c)
    s['status']='UNRESOLVED';f['status']='UNRESOLVED';f['unresolved_information']='Qualification explicitly remains unverified.'
    raw['checks']['RQ1']['status']='UNRESOLVED'
    cov.validate(raw,b['requirements'],c)
    dimension='basis' if key=='exposure_basis' else key
    assert s['measurement'][dimension]==value and s['unresolved_dimensions']==[dimension]


@pytest.mark.parametrize('value',[None,''])
def test_absent_profile_dimension_remains_null_unresolved_not_na(scoped,value):
    source=read_json(scoped[1]);source['profiles'][0]['columns'][0]['unit']=value;write_json(scoped[1],source)
    b,req,c,raw=prepared(scoped)
    f=measure(raw,c,'F1:mouse:A2');s=f['source_scopes'][0]
    s['status']='UNRESOLVED';f['status']='UNRESOLVED';f['unresolved_information']='Source unit not established.'
    raw['checks']['RQ1']['status']='UNRESOLVED'
    cov.validate(raw,b['requirements'],c)
    assert s['measurement']['unit']==value and s['unresolved_dimensions']==['unit']


def test_exact_inherited_condition_keeps_original_rule_authority(scoped):
    plan=read_json(scoped[0]);condition='Eligible paired nonhuman records exist.'
    plan['requirements'][0]['project_source_ids']=['main:/rules/24/text']
    plan['requirements'][0]['inherited_rule_constraints']=[{'source':'main:/rules/24/text',
        'conditions':[condition],'exceptions':['Do not invent matching.']}]
    write_json(scoped[0],plan)
    b,req,c,raw=prepared(scoped)
    raw['checks']['RQ1']['condition_gaps']=[{'condition':condition,'summary':'Pairing is not established.',
        'source_ids':['F1:mouse:A2']}]
    cov.validate(raw,b['requirements'],c)
    cov.run_prepared(scoped[3],generator=lambda *a,**kw:raw)
    result=cov.verify_result(scoped[3]/'coverage.json')
    assert result['checks']['RQ1']['condition_gaps'][0]['inherited_rule_source_ids']==['main:/rules/24/text']
    raw['checks']['RQ1']['condition_gaps'][0]['condition']='Do not invent matching.'
    with pytest.raises(ValueError,match='original DR condition'):cov.validate(raw,b['requirements'],c)


def test_necessity_input_retains_presence_and_unknown_qualification(scoped):
    source=read_json(scoped[1]);source['profiles'][0]['exposure_basis']='NOT_FOUND';write_json(scoped[1],source)
    b,req,c,raw=prepared(scoped)
    f=measure(raw,c,'F1:mouse:A2');f['status']='UNRESOLVED';f['unresolved_information']='Basis unknown.'
    f['source_scopes'][0]['status']='UNRESOLVED';raw['checks']['RQ1']['status']='UNRESOLVED'
    cov.run_prepared(scoped[3],generator=lambda *a,**kw:raw)
    mp=write_json(scoped[3].parent/'mp-current.json',{'profiles':[{'id':'MP004'}]})
    prepared_nec=nec.prepare(scoped[3]/'coverage.json',scoped[2],mp,scoped[3].parent/'necessity-current')
    typed=prepared_nec['request']['payload']['recorded_shortages']['RQ1:F2']['source_scopes'][0]
    assert typed['recorded_value_presence']=='PRESENT' and typed['unresolved_dimensions']==['basis']
    assert typed['evidence'][0]['source']=='F1:mouse:A2' and typed['evidence'][0]['quote']=='2.5'


def test_dr5_current_workflow_consumes_cov3_nec5_and_preserves_summary_opinion(scoped):
    plan,source,main,out=scoped
    p=read_json(plan);p['version']='REQUIREMENT_PLAN_5.0';write_json(plan,p)
    mp=write_json(out.parent/'methods.json',{'profiles':[{'id':'MP004'}]})
    calls=[]
    def generate(request,**kw):calls.append(request['payload']['stage']);return answer(request)
    run=out.parent/'current'
    workflow.run(plan,source,main,mp,run,generator=generate)
    assert cov.verify_result(run/'coverage/coverage.json')['version']=='DIRECT_DR_COVERAGE_3.0'
    assert nec.verify_result(run/'necessity/necessity.json')['version']=='DIRECT_NECESSITY_5.0'
    s=summary.verify_result(run/'human_summary/summary.json')
    assert not s['scientific_approval'] and not s['downstream_executed'] and len(calls)==3
