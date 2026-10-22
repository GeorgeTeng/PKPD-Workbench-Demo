"""Offline current-entry regressions; generators are fixtures, never providers."""
import copy
import pytest
from research_pipeline import data_coverage_scoped as cov, data_necessity_scoped as nec
from research_pipeline import data_assessment_workflow as workflow, data_coverage_direct as legacy
from research_pipeline import data_human_summary_scoped as summary
from research_pipeline.common import read_json, write_json, PipelineError
from test_data_coverage_direct import case as legacy_case, answer as coverage_answer
from test_data_decisions import answer as old_answer


@pytest.fixture(autouse=True)
def no_provider(monkeypatch):
    def forbidden(*a,**kw):
        pytest.fail('Offline tests must never dispatch a provider')
    monkeypatch.setattr(cov.rt.providers,'codex_generate',forbidden)


@pytest.fixture
def scoped(legacy_case):
    plan, source, main, out = legacy_case
    s = read_json(source)
    s['source_units'] = {}
    items = []
    for p in s['profiles']:
        if p['role']=='PK': p['role']='PK_OBSERVATIONS'
        p.update(exposure_basis='TOTAL',record_level='AGGREGATE',
                 columns=[{'header':'Concentration','meaning':'concentration','unit':'mg/L'}])
        item = p['item_id']
        s['source_units'].update({item+':A1':'Concentration',item+':A2':'2.5',item+':C10':'Reported MIC 2 mg/L'})
        items.append({'id':item, 'kind':'NOTE' if item.endswith(':notes') else 'TABLE',
                      'region':{'header_row':1,'end_row':4,'left':1,'right':1}})
    write_json(source,s)
    inv = write_json(out.parent/'inventory.json',{'main':cov.rt.file_ref(main),'items':items})
    p = read_json(plan);p['bindings']['inventory']=cov.rt.file_ref(inv);write_json(plan,p)
    return plan, source, main, out


def answer(request, **kwargs):
    p = request['payload']
    if p['stage'] == 'DIRECT_DR_COVERAGE':
        raw = coverage_answer(request)
        for check in raw['checks'].values():
            for f in check['fields'].values():
                f.update(support_kind='UNRESOLVED',measurement=None,relation_source_ids=[])
        return raw
    raw = old_answer(request)
    if p['stage'] == 'NECESSITY_SCOPED_ASSESSMENT':
        for a in raw['analyses']:
            a['action_scopes']=[{'action_id':'MODEL_BASED_ANIMAL_PK','scope_ids':[nec.UNKNOWN]}]
        for k, d in raw['action_decisions'].items():
            if k != 'MODEL_BASED_ANIMAL_PK':
                d['gap_ids']=[]
            d['scope_readiness']=[{'scope_id':nec.UNKNOWN,'readiness':d['readiness']}]
    return raw


def prepared(scoped):
    build=cov.prepare(*scoped)
    req=read_json(build['parts'][0]['request_ref']['path'])
    catalog=read_json(build['source_catalog_ref']['path'])
    return build,req,catalog,answer(req)


def measurement(raw, source='F1:mouse:A2'):
    f=raw['checks']['RQ1']['fields']['concentration']
    f.update(status='SUPPORTED',unresolved_information='',support_kind='MEASUREMENT_RECORDS',
        measurement={'quantity':'concentration','unit':'mg/L','basis':'TOTAL','record_level':'AGGREGATE'},
        source_scopes=[{'item_id':source.rsplit(':',1)[0],'scope_note':'This exact table only.',
                        'status':'SUPPORTED','column_header':'Concentration','source_ids':[source]}])
    raw['checks']['RQ1']['status']='PARTIAL'
    return f


def test_scoped_measurement_positive_exact_replay_and_no_extra_calls(scoped):
    build,request,catalog,raw=prepared(scoped)
    f=measurement(raw)
    assert catalog['F1:mouse:A2']['evidence_role']=='TABLE_BODY'
    assert catalog['F1:mouse:A1']['evidence_role']=='CONTEXT_ONLY'
    assert catalog['F1:mouse:C10']['evidence_role']=='CONTEXT_ONLY'
    calls=[]
    def generate(request,**kw): calls.append(1);return raw
    result=cov.run_prepared(scoped[3],generator=generate)
    assert cov.verify_result(scoped[3]/'coverage.json')==result
    assert cov.run_prepared(scoped[3],generator=generate)==result and len(calls)==1
    assert result['checks']['RQ1']['fields']['concentration']['measurement']==f['measurement']
    assert len(result['checks'])==2 and not result['scientific_approval']


@pytest.mark.parametrize('source',['F1:notes:A2','F1:mouse:A1','F1:mouse:C10','F1:horse:A2','F1:human:A2','F2:body:A2'])
def test_context_header_note_and_holdout_are_not_measurements(scoped,source):
    b,r,c,raw=prepared(scoped);measurement(raw,source)
    with pytest.raises(ValueError):cov.validate(raw,b['requirements'],c)


@pytest.mark.parametrize('key,value',[('quantity','MIC'),('quantity','CFU'),('basis','FREE'),
                                     ('record_level','INDIVIDUAL'),('unit','ng/mL')])
def test_measurement_dimensions_cannot_be_silently_relabelled(scoped,key,value):
    b,r,c,raw=prepared(scoped);measurement(raw)['measurement'][key]=value
    with pytest.raises(PipelineError,match='dimensions'):cov.validate(raw,b['requirements'],c)


def test_reported_value_is_allowed_without_upgrading_to_measurements(scoped):
    b,r,c,raw=prepared(scoped);f=measurement(raw,'F1:notes:C10')
    f.update(support_kind='REPORTED_VALUE',measurement=None)
    f['source_scopes'][0]['column_header']=''
    cov.validate(raw,b['requirements'],c)
    assert f['support_kind']=='REPORTED_VALUE'


def test_descriptor_and_empty_suffix_are_context_not_cells(scoped):
    source=read_json(scoped[1])
    source['source_units'].update({'F1:mouse':'Descriptor','F1:mouse:':'Empty suffix',
                                 'F1:mouse:descriptor':'Table narrative'})
    write_json(scoped[1],source)
    b,r,c,raw=prepared(scoped)
    for sid in ('F1:mouse','F1:mouse:','F1:mouse:descriptor'):
        assert c[sid]['evidence_role']=='CONTEXT_ONLY'


@pytest.mark.parametrize('role',['REPORTED_PARAMETERS','METHOD_KNOWLEDGE','MODEL_DERIVED','UNKNOWN'])
def test_non_observation_role_cannot_establish_measurement(scoped,role):
    source=read_json(scoped[1]);source['profiles'][0]['role']=role;write_json(scoped[1],source)
    b,r,c,raw=prepared(scoped);measurement(raw)
    with pytest.raises(PipelineError,match='table body'):cov.validate(raw,b['requirements'],c)


@pytest.mark.parametrize('status',['UNRESOLVED','CONFLICT','PARTIAL'])
def test_field_cannot_hide_adverse_source_scope(scoped,status):
    b,r,c,raw=prepared(scoped);f=measurement(raw)
    f['source_scopes'].append({'item_id':'F1:rat','source_ids':['F1:rat:A2'],
        'scope_note':'Rat scope differs.','status':status,'column_header':'Concentration'})
    with pytest.raises(PipelineError,match='scope'):cov.validate(raw,b['requirements'],c)


def test_two_values_do_not_create_relation_evidence(scoped):
    b,r,c,raw=prepared(scoped);f=measurement(raw)
    f.update(support_kind='RELATIONSHIP',measurement=None)
    f['source_scopes'][0]['column_header']=''
    with pytest.raises(PipelineError,match='relation evidence'):cov.validate(raw,b['requirements'],c)


@pytest.fixture
def assessed(scoped):
    plan,source,main,out=scoped
    mp=write_json(out.parent/'mp.json',{'profiles':[{'id':'MP004'}]})
    run=out.parent/'assessed'
    calls=[]
    def generate(request,**kwargs):calls.append(request['payload']['stage']);return answer(request)
    workflow.run(plan,source,main,mp,run,generator=generate)
    return run,(plan,source,main,mp),calls,generate


def test_active_workflow_replays_scoped_contract_and_keeps_three_calls(assessed):
    run,args,calls,generate=assessed
    result=nec.verify_result(run/'necessity/necessity.json')
    summary.verify_result(run/'human_summary/summary.json')
    assert result['version']=='DIRECT_NECESSITY_4.0' and len(calls)==3
    assert not result['scientific_approval'] and not result['downstream_executed']
    workflow.run(*args,run.parent/'reused',reuse_coverage=run/'coverage/coverage.json',
                 reuse_necessity=run/'necessity/necessity.json',generator=generate)
    assert calls[3:]==['HUMAN_REVIEW_SUMMARY_ONLY']


def test_current_three_stage_payloads_are_lossless_contextbuilder_inputs(assessed):
    from research_pipeline.context_linear import assemble
    run,*_=assessed
    build=read_json(run/'coverage/build.json')
    requests=[read_json(part['request_ref']['path']) for part in build['parts']]
    requests += [read_json(run/name/'prepared.json')['request'] for name in ('necessity','human_summary')]
    assert len(requests)==3
    for request in requests:
        assert assemble(request)['request']==request


@pytest.mark.parametrize('damage',['false_ready','scope_missing','unrelated_scope','gap_missing','invented_scope','duplicate_scope','false_aggregate'])
def test_action_details_cannot_disagree_with_ready_or_drop_links(assessed,damage):
    run,*_=assessed;p=read_json(run/'necessity/prepared.json');r=answer(p['request'])
    a=r['analyses'][0];d=r['action_decisions']['MODEL_BASED_ANIMAL_PK']
    a['impact']='BLOCKS_ACTION';d['readiness']='NOT_READY';d['scope_readiness'][0]['readiness']='NOT_READY'
    nec.validate_response(r,p)
    if damage=='false_ready':d['readiness']='READY';d['scope_readiness'][0]['readiness']='READY'
    elif damage=='scope_missing':d['scope_readiness']=[{'scope_id':'F1:mouse','readiness':'NOT_READY'}]
    elif damage=='unrelated_scope':a['action_scopes'][0]['scope_ids']=['F1:mouse']
    elif damage=='gap_missing':d['gap_ids']=[]
    elif damage=='invented_scope':a['action_scopes'][0]['scope_ids']=['invented']
    elif damage=='duplicate_scope':d['scope_readiness']*=2
    else:d['readiness']='READY'
    with pytest.raises(ValueError):nec.validate_response(r,p)


@pytest.mark.parametrize('action,impact,readiness',[('PD_INDEX_COMPARISON','BLOCKS_ACTION','NOT_READY'),
    ('NCA','LIMITS_ANALYSIS','CONDITIONAL'),('PTA','FUTURE_DEPENDENCY','LATER')])
def test_local_consumer_issue_does_not_block_unrelated_pk(assessed,action,impact,readiness):
    run,*_=assessed;p=read_json(run/'necessity/prepared.json');r=answer(p['request'])
    a=r['analyses'][0];a['action_scopes'][0]['action_id']=action;a['impact']=impact
    if impact=='FUTURE_DEPENDENCY':a['importance']='FUTURE_DEPENDENCY';a['recommendation_kind']='WAIT_FOR_UPSTREAM'
    for key,d in r['action_decisions'].items():
        d['gap_ids']=a['gap_ids'] if key==action else []
        d['readiness']=readiness if key==action else 'READY'
        d['scope_readiness'][0]['readiness']=d['readiness']
    nec.validate_response(r,p)
    assert r['action_decisions']['MODEL_BASED_ANIMAL_PK']['readiness']=='READY'


def test_blocked_rat_scope_retains_ready_mouse_subset(assessed):
    run,*_=assessed;p=read_json(run/'necessity/prepared.json');r=answer(p['request'])
    for gap in p['gaps'].values():
        gap['source_scopes']=[{'item_id':'F1:rat','status':'UNRESOLVED'}]
    a=r['analyses'][0];a['impact']='BLOCKS_ACTION'
    a['action_scopes'][0]['scope_ids']=['F1:rat']
    d=r['action_decisions']['MODEL_BASED_ANIMAL_PK']
    d['scope_readiness']=[{'scope_id':'F1:mouse','readiness':'READY'}, {'scope_id':'F1:rat','readiness':'NOT_READY'}]
    d['readiness']='CONDITIONAL'
    nec.validate_response(r,p)
    assert d['scope_readiness'][0]['readiness']=='READY'


def test_all_primary_ready_and_pass_cannot_hide_a_blocking_detail(assessed):
    run,*_=assessed;p=read_json(run/'necessity/prepared.json');r=answer(p['request'])
    r['assessment']['decision']='PASS';r['analyses'][0]['impact']='BLOCKS_ACTION'
    for key in nec.ACTIONS[:3]:
        d=r['action_decisions'][key];d['readiness']='READY'
        d['scope_readiness'][0]['readiness']='READY'
    with pytest.raises(PipelineError,match='contradicts'):nec.validate_response(r,p)


def test_current_contract_rejects_old_result_without_modifying_it(legacy_case):
    legacy.prepare(*legacy_case);legacy.run_prepared(legacy_case[3],generator=coverage_answer)
    path=legacy_case[3]/'coverage.json';before=path.read_bytes()
    with pytest.raises(PipelineError,match='legacy results'):cov.verify_result(path)
    assert path.read_bytes()==before
    assert legacy.verify_result(path)['complete']


def test_legacy_workflow_cannot_dispatch_even_without_a_provider(legacy_case):
    from research_pipeline.data_direct_workflow import run_legacy
    with pytest.raises(PipelineError,match='replay/test-only'):
        run_legacy(*legacy_case[:3],legacy_case[2],legacy_case[3])
    assert not legacy_case[3].exists()


def test_source_changes_during_call_cannot_publish_new_coverage(scoped):
    prepared(scoped)
    def change(req,**kwargs):
        s=read_json(scoped[1]);s['source_units']['F1:mouse:A2']='Changed';write_json(scoped[1],s)
        return answer(req)
    with pytest.raises(PipelineError,match='Active input changed'):cov.run_prepared(scoped[3],generator=change)
    assert not (scoped[3]/'coverage.json').exists()
