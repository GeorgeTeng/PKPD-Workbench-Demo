"""Actual LangGraph PK control tests with explicit synthetic provider/numerical doubles."""
import copy
from pathlib import Path
import pytest
from research_pipeline.adequacy import file_ref, check_ref
from research_pipeline.common import read_json, write_json, PipelineError
from research_pipeline.animal_pk import build_plan, digest
from research_pipeline.animal_pk_control import (save_qualification,make_agent_request,execute_agent,
    control_snapshot,review_bundle)
from research_pipeline.animal_pk_comparison import compare_results, begin_review, finish_review
from research_pipeline.workflow_runtime import make_plan
from test_animal_pk_nlmixr2 import synthetic_qualification


@pytest.fixture
def fixture(tmp_path_factory):
    # Short paths also exercise the Windows runtime without relying on long-path policy.
    folder=tmp_path_factory.mktemp('pkc')
    q=synthetic_qualification(folder/'data')
    normalized=read_json(q['normalized_data_ref']['path'])
    metadata={**normalized['metadata'],'role':'PK_OBSERVATIONS'}
    sidecar=file_ref(write_json(folder/'meta.json',{'dataset_id':'D1','data_file':q['normalized_data_ref'],'metadata':metadata}))
    csv=folder/'source.csv';csv.write_text('Synthetic normalized events are in data/synthetic.json.\n')
    item={'dataset_id':'D1','role':'PK_OBSERVATIONS','data':q['normalized_data_ref'],
        'metadata':sidecar,'csv':file_ref(csv),'excluded_records':file_ref(write_json(folder/'excluded.json',{'records':[]}))}
    ref=file_ref(write_json(folder/'context.json',{'module':'pk','drug':'Synthetic test only','data_files':[item],
        'data_access':{'human_pk':False},'rules':[],'tasks':[],'clinical_questions':{'exposure_basis':'total'}}))
    plan=build_plan(ref);plan_ref=file_ref(write_json(folder/'plan.json',plan))
    approval=file_ref(write_json(folder/'dispatch.json',{'status':'ROUTING_APPROVED_NOT_MODEL_RELEASE','synthetic':True}))
    return {'root':folder,'plan':plan,'plan_ref':plan_ref,'data':q,'approval':approval,'control':folder/'control'}


def qualified(fixture,candidate,configurations=1):
    unit=fixture['plan']['analysis_units'][0]
    base=synthetic_qualification(fixture['root']/('source_'+candidate['id']),candidate['compartments'])
    # Use the exact assigned synthetic event table, with model-specific parameter initialization.
    base.update(candidate_id=candidate['id'],analysis_id=unit['analysis_id'],species=unit['species'],
        normalized_data_ref=unit['data']['data'],input_refs=[unit['data']['data']],
        source_provenance={'assigned_dataset_ref':unit['data']['data'],'transformation_description':'Synthetic events already normalized.',
            'dose_evidence':'Synthetic dose event for every simulated ID.','identity_evidence':'Synthetic subject IDs explicitly generated.'})
    configs=[]
    for i in range(configurations):
        config=copy.deepcopy(base);config['configuration_id']='config_'+str(i+1)
        config['fit_config']['initial']['CL']+=i*0.02
        configs.append(config)
    envelope={'configurations':configs,'max_attempts':configurations,'reviewer':'Synthetic reviewer','confirmed':True}
    return save_qualification(fixture['plan'],candidate['id'],envelope,fixture['control'],fixture['approval'])


def completed_upstream(fixture):
    runs=[];lookup={}
    for agent in fixture['plan']['agents']:
        if agent['role'] not in {'species_coordinator','input_qualification','model_review'}:continue
        identifier='run_'+str(len(runs)+1)
        result={'status':'AGENT_COMPLETED','upstream_run_ids':{a:lookup[a] for a in agent['depends_on']},'model_release':False}
        ref=file_ref(write_json(fixture['root']/'upstream'/(identifier+'.json'),result))
        runs.append({'id':identifier,'agent_id':agent['id'],'status':'COMPLETED','created_at':str(len(runs)),
            'result':result,'result_ref':ref})
        lookup[agent['id']]=identifier
    return runs


def numerical(q,proposal_ref,folder,failed=False):
    check_ref(proposal_ref)
    assert read_json(proposal_ref['path'])['decision']=='CONTINUE'
    refs={name:file_ref(write_json(Path(folder)/(name+'.json'),{'synthetic':True}))
          for name in ['execution','model_code','diagnostics']}
    return {'candidate_id':q['candidate_id'],'species':q['species'],'analysis_id':q['analysis_id'],
        'status':'FITTED','converged':not failed,'diagnostic_status':'FAILED_PRESET_CHECKS' if failed else 'PASSED_PRESET_CHECKS',
        'diagnostic_rule_signature':'synthetic-checks','observation_signature':q['normalized_data_ref']['sha256'],
        'response_scale':'concentration','response_unit':'mg/L','matrix':'plasma','exposure_basis':'total',
        'likelihood_definition':'synthetic exact Gaussian','likelihood_constants':'INCLUDED',
        'estimation_method':'MAXIMUM_LIKELIHOOD','n_observations':64,'bic_n_definition':'observations',
        'log_likelihood':-30.0+q['compartments'],'n_parameters':q['compartments']*2+1,
        **{name+'_ref':ref for name,ref in refs.items()},'issues':[]}


def answer(decision='CONTINUE'):
    return {'decision':decision,'summary':'Synthetic review only.','issues':[],
        'requested_changes':['Investigate the configured assumptions.'] if decision=='REVISE' else []}


def request_for(fixture,candidate,runs=None):
    return make_agent_request(fixture['plan'],candidate['model_agent'],fixture['control'],'',
        completed_upstream(fixture) if runs is None else runs,fixture['approval'])


def test_actual_langgraph_retains_multiple_successful_configurations_and_fresh_calls(fixture):
    candidate=fixture['plan']['analysis_units'][0]['candidates'][0]
    qualified(fixture,candidate,2);request=request_for(fixture,candidate)
    calls=[]
    def generator(request,diagnostics_dir):
        calls.append((request,diagnostics_dir));return answer()
    result=execute_agent(request,fixture['root']/'fit',generator,numerical)
    assert result['status']=='CANDIDATE_SEARCH_COMPLETED' and result['fit_calls']==2 and result['llm_calls']==7
    assert len(result['fit_refs'])==2 and result['search_checkpoint_id']
    assert len({str(path) for _,path in calls})==7
    assert len({call['invocation_id'] for call in result['agent_calls']})==7
    assert [request['payload']['stage'] for request,_ in calls]==[
        'animal_pk_configuration_selection','animal_pk_estimation_configuration','animal_pk_fit_self_check',
        'animal_pk_configuration_selection','animal_pk_estimation_configuration','animal_pk_fit_self_check','animal_pk_attempt_summary']
    assert all('messages' not in request['payload'] and 'history' not in request['payload'] for request,_ in calls)
    assert all(request['payload']['task']['session_policy']=='FRESH_CALL_NO_CONVERSATION_REUSE' for request,_ in calls)
    fits=[read_json(ref['path']) for ref in result['fit_refs']]
    assert len({fit['configuration_id'] for fit in fits})==2
    assert all(row['status']=='ELIGIBLE_FOR_WITHIN_GROUP_RANKING' for row in compare_results(fits)['rows'])
    assert not result['model_release'] and not result['scientific_accepted']


def test_failed_numerical_checks_cannot_be_overridden_by_model(fixture):
    candidate=fixture['plan']['analysis_units'][0]['candidates'][0]
    qualified(fixture,candidate,2)
    def adapter(q,proposal_ref,folder):return numerical(q,proposal_ref,folder,failed=q['configuration_id']=='config_1')
    result=execute_agent(request_for(fixture,candidate),fixture['root']/'fit',lambda *a,**k:answer(),adapter)
    fits=[read_json(ref['path']) for ref in result['fit_refs']]
    rows=compare_results(fits)['rows']
    assert result['fit_calls']==2 and rows[0]['status']=='NOT_COMPARABLE' and rows[1]['status']=='ELIGIBLE_FOR_WITHIN_GROUP_RANKING'
    assert fits[0]['converged'] is False and fits[0]['diagnostic_status']=='FAILED_PRESET_CHECKS'


def test_selection_revise_skips_fit_and_summary_revise_blocks_release(fixture):
    candidate=fixture['plan']['analysis_units'][0]['candidates'][0]
    qualified(fixture,candidate,2)
    def generator(request,diagnostics_dir):
        stage=request['payload']['stage'];inputs=request['payload']['upstream']
        revise=stage=='animal_pk_attempt_summary' or (stage=='animal_pk_configuration_selection' and inputs['configuration_number']==1)
        return answer('REVISE' if revise else 'CONTINUE')
    result=execute_agent(request_for(fixture,candidate),fixture['root']/'fit',generator,numerical)
    assert result['fit_calls']==1 and len(result['fit_refs'])==2
    assert read_json(result['fit_refs'][0]['path'])['status']=='NOT_FITTED_AGENT_REQUESTED_CHANGES'
    assert result['status']=='NEEDS_REVIEW'


def test_stale_upstream_and_managed_child_cannot_be_run_directly(fixture):
    candidate=fixture['plan']['analysis_units'][0]['candidates'][0]
    qualified(fixture,candidate)
    runs=completed_upstream(fixture)
    stale=copy.deepcopy(runs[0]);stale['id']='new_coordinator';stale['created_at']='9';runs.append(stale)
    states=control_snapshot(fixture['plan'],fixture['control'],runs)['agent_states']
    assert states[fixture['plan']['analysis_units'][0]['input_agent']]['status']=='STALE'
    assert not states[candidate['model_agent']]['can_run']
    with pytest.raises(PipelineError,match='upstream'):request_for(fixture,candidate,runs)
    for child in candidate['steps']:
        assert not states[child['agent_id']]['can_run']
        with pytest.raises(PipelineError):make_agent_request(fixture['plan'],child['agent_id'],fixture['control'],'',[],fixture['approval'])


def test_qualification_needs_confirmation_source_mapping_and_bound_normalized_data(fixture):
    candidate=fixture['plan']['analysis_units'][0]['candidates'][0]
    value=qualified(fixture,candidate);envelope=value['qualification']
    unconfirmed={**envelope,'confirmed':False}
    with pytest.raises(PipelineError,match='Confirm'):save_qualification(fixture['plan'],candidate['id'],unconfirmed,fixture['control'],fixture['approval'])
    bad=copy.deepcopy(envelope);bad['configurations'][0]['source_provenance']['identity_evidence']=''
    with pytest.raises(PipelineError,match='identities'):save_qualification(fixture['plan'],candidate['id'],bad,fixture['control'],fixture['approval'])
    approval=read_json(envelope['configurations'][0]['approval_ref']['path'])
    assert approval['scope']=='DATA_AND_CONFIGURATION_ONLY_NOT_MODEL_ACCEPTANCE'
    assert approval['normalized_data_ref']==fixture['data']['normalized_data_ref']
    with open(fixture['data']['normalized_data_ref']['path'],'a') as handle:handle.write(' ')
    with pytest.raises(PipelineError):make_agent_request(fixture['plan'],candidate['model_agent'],fixture['control'],'',completed_upstream(fixture),fixture['approval'])


@pytest.mark.parametrize('field,value,code',[('matrix','serum','PK_DATA_DEFINITION_CHANGED'),
    ('exposure_basis','free','PK_DATA_DEFINITION_CHANGED'),('record_level','GROUP_MEAN','PK_UNSUPPORTED_SAMPLING_DESIGN')])
def test_qualification_cannot_relabel_source_definitions(fixture,field,value,code):
    context=read_json(fixture['plan']['context_ref']['path']);item=context['data_files'][0]
    metadata=read_json(item['metadata']['path']);metadata['metadata'][field]=value
    item['metadata']=file_ref(write_json(fixture['root']/'revised_metadata.json',metadata))
    context_ref=file_ref(write_json(fixture['root']/'revised_context.json',context))
    fixture['plan']=build_plan(context_ref)
    candidate=fixture['plan']['analysis_units'][0]['candidates'][0]
    with pytest.raises(PipelineError) as rejected:qualified(fixture,candidate)
    assert rejected.value.code==code


def test_comparison_revision_prevents_human_review_bundle(fixture):
    plan=fixture['plan'];unit=plan['analysis_units'][0]
    contract=next(a for a in plan['agents'] if a['id']==unit['comparison_agent'])
    upstream={};runs=[]
    for i,candidate in enumerate(unit['candidates']):
        qualified_value=qualified(fixture,candidate)['qualification'];q=qualified_value['configurations'][0]
        proposal=file_ref(write_json(fixture['root']/('proposal'+str(i)+'.json'),answer()))
        result=numerical(q,proposal,fixture['root']/('numerical'+str(i)))
        result.update(base_candidate_id=candidate['id'],candidate_id=candidate['id']+'__config_1')
        fit=file_ref(write_json(fixture['root']/('fit'+str(i)+'.json'),result))
        ref=file_ref(write_json(fixture['root']/('up'+str(i)+'.json'),{'fit_refs':[fit]}))
        upstream[candidate['model_agent']]=ref
        runs.append({'id':'candidate_'+str(i),'agent_id':candidate['model_agent'],'status':'COMPLETED','created_at':str(i)})
    request=file_ref(write_json(fixture['root']/'compare_request.json',{'agent':contract,'plan_signature':plan['plan_signature'],
        'upstream_refs':upstream,'upstream_run_ids':{r['agent_id']:r['id'] for r in runs},'instruction':'',
        'source_refs':list(upstream.values()),'approval_ref':fixture['approval']}))
    result=execute_agent(request,fixture['root']/'comparison',lambda *a,**k:answer('REVISE'))
    assert result['status']=='NEEDS_REVIEW'
    runs.append({'id':'compare','agent_id':contract['id'],'status':'COMPLETED','created_at':'3','result':result,
        'result_ref':file_ref(fixture['root']/'comparison/report.json')})
    assert review_bundle(plan,fixture['control'],runs,unit['species']) is None


def test_snakemake_plan_has_independent_candidate_jobs_then_join_and_binds_sources(fixture):
    requests=[]
    for candidate in fixture['plan']['analysis_units'][0]['candidates']:
        qualified(fixture,candidate);requests.append(request_for(fixture,candidate))
    spec={'mode':'animal_pk_execution','pk_plan':fixture['plan_ref'],'agent_requests':requests,
        'job_dir':str(fixture['root']/'job'),'out':str(fixture['root']/'run')}
    workflow=make_plan(spec)
    steps=workflow['steps'];workers=[name for name in steps if name.startswith('pk_execute_')]
    assert len(workers)==2 and all(steps[name]['depends']==[] for name in workers)
    assert set(steps['animal_pk_batch']['depends'])==set(workers)
    assert workflow['targets']['animal_pk_execution']=='animal_pk_batch'
    for name in workers:
        contract=read_json(steps[name]['contract'])
        assert contract['kind']=='animal_pk_execution' and contract['options']['request_ref'] in requests
    # Changed scientific source cannot silently reuse the scheduler's previous plan.
    with open(fixture['data']['normalized_data_ref']['path'],'a') as handle:handle.write(' ')
    with pytest.raises(PipelineError):make_plan({**spec,'job_dir':str(fixture['root']/'changed_job')})


def test_signed_human_selection_reaches_species_and_animal_handoffs_without_model_invented_parameters(fixture):
    """Two fits -> comparison -> real interrupt/resume -> two scoped reporting agents."""
    plan=fixture['plan'];unit=plan['analysis_units'][0];species=plan['species'][0]
    runs=completed_upstream(fixture);calls=[]
    def generator(request,diagnostics_dir):
        calls.append((request,diagnostics_dir))
        # Structured numerical handoffs must not parse parameter claims out of agent prose.
        return {**answer(),'summary':'Synthetic agent prose proposes CL=999; this text cannot edit tool parameters.'}
    def fit(q,proposal_ref,folder):
        value=numerical(q,proposal_ref,folder)
        value['parameters']=[{'parameter':'CL','estimate':0.4,'unit':'L/h'},
            {'parameter':'VC','estimate':1.2,'unit':'L'}]
        if q['compartments']==2:value['parameters'] += [{'parameter':'Q','estimate':0.8,'unit':'L/h'},
            {'parameter':'VP','estimate':2.0,'unit':'L'}]
        return value
    def execute_and_track(agent_id,name):
        request=make_agent_request(plan,agent_id,fixture['control'],'',runs,fixture['approval'])
        folder=fixture['root']/name
        result=execute_agent(request,folder,generator,fit)
        runs.append({'id':name,'agent_id':agent_id,'status':'COMPLETED','created_at':'2026-09-22T00:00:'+str(len(runs)).zfill(2)+'Z',
            'finished_at':result['finished_at'],'result':result,'result_ref':file_ref(folder/'report.json')})
        return result
    for index,candidate in enumerate(unit['candidates']):
        qualified(fixture,candidate)
        execute_and_track(candidate['model_agent'],'fit_'+str(index))
    comparison=execute_and_track(unit['comparison_agent'],'comparison')
    assert comparison['status']=='PENDING_HUMAN_REVIEW'
    report=review_bundle(plan,fixture['control'],runs,species['species'])
    assert report and len(report['rows'])==2
    selected=unit['candidates'][1]['id']+'__config_1'
    selected_row=next(row for row in report['rows'] if row['candidate_id']==selected)
    assert selected_row['status']=='ELIGIBLE_FOR_WITHIN_GROUP_RANKING'
    review_folder=fixture['control']/'reviews'/digest(species['species'])[:16]/report['output_signature'][:16]
    checkpoint=begin_review(report,review_folder,'synthetic',species['species'])
    assert checkpoint['status']=='INTERRUPTED'
    release=finish_review(review_folder,{'decision':'APPROVE','confirmed':True,'reviewer':'Synthetic reviewer',
        'rationale':'','selected_candidates':[selected],'output_signature':report['output_signature']})
    assert release['langgraph']['status']=='APPROVED' and release['model_release'] is True
    assert release['human_prediction_validated'] is False
    species_result=execute_and_track(species['report_agent'],'species_report')
    check_ref(species_result['handoff_ref'])
    species_handoff=read_json(species_result['handoff_ref']['path'])
    assert species_handoff['module']=='animal_pk_species' and species_handoff['model_release'] is True
    assert species_handoff['human_prediction_validated'] is False
    assert species_handoff['selected_models']==[selected_row]
    assert species_handoff['selected_models'][0]['parameters'][0]['estimate']==0.4
    fit_ref=species_handoff['selected_models'][0]['evidence_refs']['fit_result_ref']
    check_ref(fit_ref)
    assert read_json(fit_ref['path'])['parameters']==selected_row['parameters']
    accepted_ref=species_handoff['human_review_refs'][0];check_ref(accepted_ref)
    assert read_json(accepted_ref['path'])['review_decision']['decision']['selected_candidates']==[selected]
    report_agent=next(agent for agent in plan['agents'] if agent['role']=='animal_pk_report')
    animal_result=execute_and_track(report_agent['id'],'animal_report')
    animal_handoff=read_json(animal_result['handoff_ref']['path'])
    assert animal_handoff['module']=='animal_pk' and animal_handoff['model_release'] is True
    assert animal_handoff['human_prediction_validated'] is False
    assert animal_handoff['species_handoffs']==[species_result['handoff_ref']]
    assert len(calls)==11 and len({str(path) for _,path in calls})==11
    final_request=calls[-1][0]['payload']['upstream']['upstream']
    assert list(final_request)==[species['report_agent']]
    assert final_request[species['report_agent']]['handoff_ref']==species_result['handoff_ref']
    # A distant upstream rerun invalidates the old review and both releases.
    changed=copy.deepcopy(runs[0]);changed.update(id='new_coordinator',created_at='9999')
    runs.append(changed)
    assert review_bundle(plan,fixture['control'],runs,species['species']) is None
    states=control_snapshot(plan,fixture['control'],runs)['agent_states']
    assert not states[species['report_agent']]['can_run'] and states[species['report_agent']]['status']=='STALE'
    assert not states[report_agent['id']]['can_run'] and states[report_agent['id']]['status']=='STALE'
    with pytest.raises(PipelineError):make_agent_request(plan,report_agent['id'],fixture['control'],'',runs,fixture['approval'])
