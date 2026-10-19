"""Synthetic approvals below are test fixtures; production examples remain pending."""
import copy
import math
import subprocess
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from research_pipeline.api import create_app
from research_pipeline.common import BACKEND, PROJECT,PipelineError,read_json,write_json,sha256
from research_pipeline.engine import run_pipeline,validate_request,rscript_path
from research_pipeline.data_preparation import submit_review,check_review,review_template
from research_pipeline.data_rules import precision_assessment,width_assurance,critical_t,assess_study

EXAMPLES=BACKEND/'research_pipeline/examples'


def setup(tmp_path, change=None, rows_change=None):
    request=read_json(EXAMPLES/'preparation_parallel.request.json')
    request['request_id']='initial'
    config=read_json(EXAMPLES/'preparation_synthetic.plan.json')
    if change: change(config)
    if rows_change:
        records=read_json(EXAMPLES/'synthetic_pk.json')
        rows=records.get('records') if isinstance(records,dict) else records
        rows_change(rows)
        data=write_json(tmp_path/'pk.json',records)
        request['attachments'][0]['path']=str(data)
    plan=write_json(tmp_path/'plan.json',config)
    next(a for a in request['attachments'] if a['id']=='plan')['path']=str(plan)
    state=tmp_path/'state'
    result=run_pipeline(request,state,EXAMPLES)
    output=read_json(state/'runs/initial/steps/data/output.json')
    return request,state,result,output


def fixture_approval(output,selected=None):
    result=output['result']
    proposal=review_template(output['request_id'],'data',result)
    proposal.update(decision='APPROVE',reviewer='SYNTHETIC_TEST_FIXTURE',confirm_rules=True,
                    selected_datasets=selected or [g['id'] for g in result['datasets']],
                    acknowledged_issues=[i['id'] for i in result['issues'] if i['severity']=='REVIEW'],
                    rationale='Automated test fixture for exploratory release; not an actual human approval.')
    return proposal


def test_pending_does_not_run_either_branch(tmp_path):
    _,state,main,output=setup(tmp_path)
    assert main['status']=='WAITING_FOR_REVIEW'
    assert [s['status'] for s in main['steps']]==['WAITING_FOR_REVIEW','SKIPPED','SKIPPED']
    assert output['result']['released_datasets']==[]
    assert output['result']['study_assessment']['status']=='EXPLORATORY_FIT_ONLY'
    assert any(i['code']=='PRECISION_NOT_CALCULABLE' for i in output['result']['issues'])
    assert not (state/'runs/initial/steps/pk/input.json').exists()


def test_human_release_then_parallel_modeling(tmp_path):
    request,state,_,output=setup(tmp_path)
    with TestClient(create_app(state)) as client:
        response=client.post('/v1/data-reviews',json=fixture_approval(output))
        assert response.status_code==200,response.text
        upload=response.json()['attachment']
        assert client.get('/v1/schemas/data-review').status_code==200
    request['request_id']='after_review'
    request['attachments'].append({'id':'review','upload_id':upload['upload_id']})
    request['steps'][0]['input']['review_attachment']='review'
    main=run_pipeline(request,state,EXAMPLES)
    assert main['status']=='SUCCEEDED', main
    assert [s['status'] for s in main['steps']]==['SUCCEEDED']*3
    assert read_json(state/'runs/initial/output.json')['status']=='WAITING_FOR_REVIEW'
    assert read_json(state/'runs/after_review/steps/index/output.json')['result']['selection']['best_by_AIC']==['fAUC_MIC_h']


def test_partial_release_does_not_release_other_branch(tmp_path):
    request,state,_,output=setup(tmp_path)
    receipt=submit_review(state,fixture_approval(output,['pk__001']))
    request['request_id']='pk_only'
    request['attachments'].append({'id':'review','upload_id':receipt['attachment']['upload_id']})
    request['steps'][0]['input']['review_attachment']='review'
    main=run_pipeline(request,state,EXAMPLES)
    assert main['status']=='PARTIAL'
    assert [s['status'] for s in main['steps']]==['SUCCEEDED','SUCCEEDED','SKIPPED']


@pytest.mark.parametrize('fault',['unconfirmed','unacknowledged','stale','tamper'])
def test_review_cannot_silently_bypass_conditions(tmp_path,fault):
    _,state,_,output=setup(tmp_path)
    proposal=fixture_approval(output)
    if fault=='unconfirmed': proposal['confirm_rules']=False
    if fault=='unacknowledged': proposal['acknowledged_issues']=[]
    if fault=='stale': proposal['assessment_sha256']='0'*64
    if fault=='tamper':
        output['result']['datasets'][0]['records'][0]['concentration_mg_L']=999
        write_json(state/'runs/initial/steps/data/output.json',output)
    with pytest.raises(PipelineError): submit_review(state,proposal)


def test_changed_data_invalidates_old_approval(tmp_path):
    request,state,_,output=setup(tmp_path,rows_change=lambda rows:None)
    receipt=submit_review(state,fixture_approval(output))
    raw=read_json(tmp_path/'pk.json'); rows=raw.get('records') if isinstance(raw,dict) else raw
    rows[0]['concentration_mg_L']*=1.01
    write_json(tmp_path/'pk.json',raw)
    request['request_id']='changed'
    request['attachments'].append({'id':'review','upload_id':receipt['attachment']['upload_id']})
    request['steps'][0]['input']['review_attachment']='review'
    main=run_pipeline(request,state,EXAMPLES)
    assert main['status']=='FAILED'
    assert read_json(state/'runs/changed/steps/data/output.json')['errors'][0]['code']=='STALE_REVIEW'


def test_invalid_values_block_approval_without_hiding_raw_data(tmp_path):
    _,state,_,output=setup(tmp_path,rows_change=lambda rows:rows[0].update(concentration_mg_L=-1))
    pk=output['result']['datasets'][0]
    assert pk['readiness']=='BLOCKED'
    assert pk['quarantine'][0]['record']['concentration_mg_L']==-1
    assert (state/'runs/initial/steps/data/pk_raw.json').exists()
    with pytest.raises(PipelineError,match='blocking'): submit_review(state,fixture_approval(output))


def test_exact_duplicates_are_proposals_and_do_not_inflate_animals(tmp_path):
    _,_,_,output=setup(tmp_path,rows_change=lambda rows:rows.append(copy.deepcopy(rows[0])))
    pk=output['result']['datasets'][0]
    assert pk['summary']['input_rows']==13 and pk['summary']['candidate_rows']==12
    assert pk['summary']['independent_units']==1
    assert pk['quarantine'][0]['reason']=='EXACT_DUPLICATE'


def test_split_species_and_declared_unit_conversion(tmp_path):
    def config(c):
        c['datasets'][0]['metadata']['time_unit']='min'
        c['datasets'][0]['metadata']['concentration_unit']='ng/mL'
    def rows(values):
        second=copy.deepcopy(values)
        for row in values: row['species']='species_A'; row['time_h']*=60; row['concentration_mg_L']*=1000
        for row in second: row['species']='species_B'; row['time_h']*=60; row['concentration_mg_L']*=1000
        values.extend(second)
    _,_,_,output=setup(tmp_path,config,rows)
    groups=[g for g in output['result']['datasets'] if g['kind']=='pk']
    assert len(groups)==2
    assert {g['metadata']['species'] for g in groups}=={'species_A','species_B'}
    assert all(g['metadata']['time_unit']=='h' and g['summary']['independent_units']==1 for g in groups)
    original=read_json(EXAMPLES/'synthetic_pk.json'); original=original.get('records') if isinstance(original,dict) else original
    assert groups[0]['records'][0]['concentration_mg_L']==pytest.approx(original[0]['concentration_mg_L'])


def test_no_raw_branch_bypass_with_data_block(tmp_path):
    request=read_json(EXAMPLES/'preparation_parallel.request.json')
    request['steps'][1]['input']={'data_attachment':'data'}
    with pytest.raises(PipelineError) as exc: validate_request(request)
    assert exc.value.code=='PREPARATION_BYPASS'


def test_null_identity_is_reported_as_missing(tmp_path):
    _,_,_,output=setup(tmp_path,rows_change=lambda rows:rows[0].update(species=None))
    assert any(i['code']=='IDENTITY_MISSING' for i in output['result']['issues'])


def test_summary_pk_cannot_count_as_animals(tmp_path):
    _,_,_,output=setup(tmp_path,change=lambda c:c['datasets'][0]['metadata'].update(record_level='summary'))
    assert output['result']['datasets'][0]['readiness']=='BLOCKED'
    assert any(i['code']=='INDEPENDENCE_UNVERIFIED' for i in output['result']['issues'])


def test_row_unit_labels_follow_conversion(tmp_path):
    def rows(records):
        for row in records:
            row.update(time_unit='min',concentration_unit='ng/mL')
            row['time_h']*=60; row['concentration_mg_L']*=1000
    _,_,_,output=setup(tmp_path,rows_change=rows)
    row=output['result']['datasets'][0]['records'][0]
    assert row['time_unit']=='h' and row['concentration_unit']=='mg/L'
    assert row['_source']['units']=={'time_unit':'min','concentration_unit':'ng/mL'}


def test_duplicate_csv_headers_do_not_silently_overwrite(tmp_path):
    from research_pipeline.tables import load_table
    path=tmp_path/'bad.csv'; path.write_text('ID,CL,CL\na,1,2\n')
    with pytest.raises(PipelineError,match='unique'): load_table(path)


def precision_fixture(tmp_path):
    scope={'drug':'PMB','analyte':'polymyxin_b','species':'rat','route':'IV','matrix':'plasma',
           'concentration_basis':'total','parameter_definition':'CL'}
    source=write_json(tmp_path/'variance.json',{'note':'Synthetic planning validation only; hypothetical mean and SD.'})
    attachments={'variance':{'path':str(source),'sha256':sha256(source)}}
    groups=[{'metadata':scope,'independent_ids':['a','b','c','d','e','f']}]
    item={'id':'synthetic_precision','scope':scope,'sampling_design':'serial_individual_parameters','variance_type':'arithmetic_sd',
          'mean':1,'sd':.3,'n0':6,'source':{'attachment':'variance','locator':'synthetic test fixture'},
          'target':{'multiplier':1.25,'confidence':.95,'assurance':.9,'source_locator':'test specification, not project threshold'}}
    return item,attachments,groups


def test_precision_formula_matches_independent_r_distribution(tmp_path):
    item,attachments,groups=precision_fixture(tmp_path)
    result=precision_assessment(item,attachments,groups)
    assert result['status']=='CONDITIONAL_PLAN'
    n=result['required_n']; sigma=math.sqrt(math.log1p(.3**2))
    assert width_assurance(n,sigma,1.25,.95)>=.9
    assert width_assurance(n-1,sigma,1.25,.95)<.9
    expression=f'cat(pchisq(({n}-1)*{n}*log(1.25)^2/(qt(.975,{n}-1)^2*log(1+.3^2)),{n}-1))'
    process=subprocess.run([rscript_path(),'--vanilla','-e',expression],capture_output=True,text=True)
    assert process.returncode==0
    assert float(process.stdout.strip())==pytest.approx(width_assurance(n,sigma,1.25,.95),rel=1e-6)


@pytest.mark.parametrize('fault',['residual','rse','missing_target','wrong_drug','terminal','no_source','wrong_ci'])
def test_unsupported_animal_number_inputs_not_calculable(tmp_path,fault):
    item,attachments,groups=precision_fixture(tmp_path)
    if fault=='residual': item['variance_type']='residual_error'
    if fault=='rse': item['variance_type']='TVCL_RSE'
    if fault=='missing_target': del item['target']
    if fault=='wrong_drug': item['scope']=dict(item['scope'],drug='CMS')
    if fault=='terminal': item['sampling_design']='terminal'
    if fault=='no_source': item['source']['attachment']='missing'
    if fault=='wrong_ci': item.update(variance_type='log_t_ci',lower=.8,upper=1.2,source_confidence=.95,ci_method='bootstrap')
    result=precision_assessment(item,attachments,groups)
    assert result['status']=='NOT_CALCULABLE' and result['required_n'] is None


@pytest.mark.parametrize('count,expected,df',[(1,'INSUFFICIENT',0),(2,'INSUFFICIENT',0),(3,'EXPLORATORY_ONLY',1)])
def test_species_count_is_not_a_validation_certificate(count,expected,df):
    target={'drug':'PMB','analyte':'PMB','route':'IV','matrix':'plasma','concentration_basis':'total','parameter_definition':'CL',
            'human_population':'defined target','decision_quantity':'CL'}
    groups=[{'kind':'pk','readiness':'READY_FOR_HUMAN_REVIEW','metadata':dict(target,species='species_'+str(i),species_weight_kg=10**i)} for i in range(count)]
    issues=[]
    report=assess_study({'purpose':'human_translation','target':target,'scaling':{'mode':'unknown_exponent'}},groups,[],lambda *args:issues.append(args))
    assert report['status']==expected and report['species_residual_df']==df
    assert report['human_validation']=='NOT_ESTABLISHED'


def test_pending_template_cannot_be_submitted_as_approval(tmp_path):
    _,state,_,output=setup(tmp_path)
    with TestClient(create_app(state)) as client:
        assert client.post('/v1/data-reviews',json=review_template('initial','data',output['result'])).status_code==422
        assert client.post('/v1/data-reviews',json={}).status_code==422


def test_rejected_review_keeps_modeling_blocked(tmp_path):
    request,state,_,output=setup(tmp_path)
    decision=fixture_approval(output); decision.update(decision='REJECT',selected_datasets=[],confirm_rules=False)
    receipt=submit_review(state,decision)
    request['request_id']='rejected'
    request['attachments'].append({'id':'review','upload_id':receipt['attachment']['upload_id']})
    request['steps'][0]['input']['review_attachment']='review'
    main=run_pipeline(request,state,EXAMPLES)
    assert main['status']=='BLOCKED'
    assert [s['status'] for s in main['steps']]==['BLOCKED','SKIPPED','SKIPPED']


def test_independent_data_module_http_upload_contract(tmp_path):
    request=read_json(EXAMPLES/'preparation_parallel.request.json')
    request['request_id']='http_data_only'
    request['steps']=request['steps'][:1]
    with TestClient(create_app(tmp_path)) as client:
        for attachment in request['attachments']:
            path=EXAMPLES/attachment.pop('path')
            response=client.post('/v1/attachments',files={'file':(path.name,path.read_bytes())})
            assert response.status_code==200
            attachment['upload_id']=response.json()['upload_id']
        response=client.post('/v1/modules/data_preparation/run',json=request)
        assert response.status_code==200,response.text
        assert response.json()['status']=='WAITING_FOR_REVIEW'
        output=client.get('/v1/runs/http_data_only/files/steps/data/output.json').json()
        assert output['module']=='data_preparation'
        assert len(output['result']['datasets'])==2 and output['result']['released_datasets']==[]
