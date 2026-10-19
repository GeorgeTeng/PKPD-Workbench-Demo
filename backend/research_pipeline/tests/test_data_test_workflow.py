"""Synthetic isolated test runner checks; no live model or scientific qualification."""
import copy
import pytest
from research_pipeline import data_agents as production, data_test_workflow as testflow
from research_pipeline.common import read_json,write_json,PipelineError
from research_pipeline.adequacy import check_ref
from test_data_agents import case


def source_without_rules(case):
    tmp,_,main,_,model,calls=case
    value=read_json(main);value.pop('project_rules_ref');value['rule_publication']='PROJECT_RULES_AGENT'
    write_json(main,value)
    return tmp,main,model,calls


def test_all_data_stages_keep_main_immutable_and_block_production_preparation(case):
    tmp,main,model,calls=source_without_rules(case);run=tmp/'isolated';original=main.read_bytes()
    for stage in testflow.STAGES:
        result=testflow.run_stage(main,run,stage,generator=model)
        assert result['status']=='COMPLETED_TEST_STAGE'
        assert main.read_bytes()==original
        for ref in result['artifacts']:check_ref(ref)
    assert calls and all(p['test_scope']['status']==testflow.SCOPE for p in calls)
    assert all(p['processing_rules'] for p in calls)  # Real DR/DC rules still delivered.
    assert all(p['test_scope']['project_rules_status']==testflow.RULES_STATUS for p in calls)
    for p in calls:
        if p['stage']=='DC-label':
            assert 'quantity=NOT_FOUND, value="7", unit="weeks"' in p['instructions']
            assert 'Never replace a known value with NOT_FOUND' in p['instructions']
        if p['stage']=='DC-review':assert 'cannot by itself establish measurement coverage' in p['instructions']
    assert 'HUMAN_HOLDOUT_SECRET_98342' not in str(calls)
    report=read_json(run/'assessment/adequacy.json');checkpoint=read_json(run/'assessment/checkpoint.json')
    assert report['technical_can_enter_qc'] is True and report['can_enter_qc'] is False
    assert checkpoint['can_enter_qc'] is False and checkpoint['confirmation_required'] is True
    check_ref(checkpoint['assessment'])
    with pytest.raises(PipelineError,match='Requirements and labels need correction'):
        production.prepared_input(run/'assessment/qc_context.json')
    count=len(calls)
    assert testflow.run_stage(main,run,'define',generator=model)['status']=='ALREADY_COMPLETED_TEST_STAGE'
    assert len(calls)==count


def test_production_rules_gate_and_globals_unchanged(tmp_path):
    main=write_json(tmp_path/'main.json',{'objective':'Test','data':{'files':[]},'rule_publication':'PROJECT_RULES_AGENT'})
    original=production.rules_for
    scope={'source_main_ref':production.file_ref(main)}
    private=testflow.private_agents(main,scope)
    assert production.rules_for is original and private.rules_for is not original
    assert private.rules_for(read_json(main),[])==[]
    with pytest.raises(PipelineError) as error:production.rules_for(read_json(main),[])
    assert error.value.code=='DATA_RULES_REQUIRED'
    with pytest.raises(PipelineError):private.rules_for({'objective':'Different'},[])


@pytest.mark.parametrize('fault',['source_changed','artifact_changed','missing_dependency','has_rules','wrong_model'])
def test_scope_and_prerequisite_integrity_fail_closed(case,fault):
    tmp,main,model,_=source_without_rules(case);run=tmp/'isolated'
    if fault=='has_rules':
        value=read_json(main);value['project_rules_ref']={'path':'not_real','sha256':'not_real'};write_json(main,value)
    elif fault not in ('missing_dependency','wrong_model'):
        testflow.run_stage(main,run,'inventory',generator=model)
        if fault=='source_changed':
            value=read_json(main);value['objective']='Changed';write_json(main,value)
        else:(run/'inventory.json').write_text('{}',encoding='utf-8')
    with pytest.raises((PipelineError,ValueError)):
        testflow.run_stage(main,run,'access' if fault in ('artifact_changed','missing_dependency') else 'define',
            generator=model,model='other' if fault=='wrong_model' else 'gpt-6-sol')


def test_bad_source_evidence_still_rejected(case):
    tmp,main,model,_=source_without_rules(case)
    def bad(req,**kwargs):
        result=model(req,**kwargs);result['tasks'][0]['evidence'][0]['quote']='INVENTED'
        return result
    with pytest.raises(PipelineError) as error:testflow.run_stage(main,tmp/'isolated','define',generator=bad)
    assert error.value.code=='DATA_EVIDENCE_INVALID'


@pytest.mark.parametrize('stage',['define','access'])
def test_test_rule_namespace_is_empty_and_processing_ids_are_rejected(case,stage):
    tmp,main,model,calls=source_without_rules(case);run=tmp/'isolated'
    original_definition=copy.deepcopy(production.DEFINITION)
    original_access=copy.deepcopy(production.ACCESS_DEFINITION)
    if stage=='access':
        testflow.run_stage(main,run,'inventory',generator=model)
        testflow.run_stage(main,run,'define',generator=model)
    def bad(req,**kwargs):
        p=req['payload'];collection='requirements' if stage=='define' else 'access'
        assert p['project_rules']==[]
        assert p['schema']['properties'][collection]['items']['properties']['rule_ids']['maxItems']==0
        assert 'never DR/DC/G processing or governance IDs' in p['instructions']
        result=model(req,**kwargs);result[collection][0]['rule_ids']=['DR002','G002']
        return result
    with pytest.raises(ValueError):testflow.run_stage(main,run,stage,generator=bad)
    assert not (run/'receipts'/f'{stage}.json').exists()
    assert production.DEFINITION==original_definition and production.ACCESS_DEFINITION==original_access
    # Explicit corrected call passes; the rejected response is not silently stripped or reused.
    assert testflow.run_stage(main,run,stage,generator=model)['status']=='COMPLETED_TEST_STAGE'


def test_access_receives_exact_registry_metadata_without_changing_inventory_or_body(case):
    tmp,main,model,calls=source_without_rules(case);run=tmp/'isolated'
    source=read_json(main)
    for f in source['data']['files']:f['name']='Registered resource '+f['id']
    write_json(main,source);main_bytes=main.read_bytes()
    for stage in ('inventory','define'):testflow.run_stage(main,run,stage,generator=model)
    inventory_bytes=(run/'inventory.json').read_bytes()
    testflow.run_stage(main,run,'access',generator=model)
    payload=next(p for p in calls if p['stage']=='DR-access')
    access_schema=payload['schema']['properties']['access']['items']['properties']
    assert access_schema['item_id']['enum']==[i['id'] for i in payload['inventory']]
    assert access_schema['requirement_ids']['items']['enum']==[r['id'] for r in payload['requirements']]
    by_id={f['id']:f for f in source['data']['files']}
    for item in payload['inventory']:
        registered=by_id[item['file_id']]
        assert item['descriptor']['registered_file']=={k:registered[k] for k in ('id','name','role')}
    assert 'A file name does not establish scientific content, relevance or permission' in payload['instructions']
    assert 'HUMAN_HOLDOUT_SECRET_98342' not in str(payload)
    assert main.read_bytes()==main_bytes and (run/'inventory.json').read_bytes()==inventory_bytes


@pytest.mark.parametrize('wrong_path',['main:/study/drug','/study','/missing_information/items/0'])
def test_access_context_paths_schema_exactly_matches_host_leaf_namespace(case,wrong_path):
    tmp,main,model,_=source_without_rules(case);run=tmp/'isolated'
    for stage in ('inventory','define'):testflow.run_stage(main,run,stage,generator=model)
    production_schema=copy.deepcopy(production.ACCESS_DEFINITION)
    def bad(req,**kwargs):
        payload=req['payload']
        allowed=payload['schema']['properties']['access']['items']['properties']['context_paths']['items']['enum']
        assert allowed==[k.removeprefix('main:') for k in payload['context_sources'] if k.startswith('main:')]
        assert '/study/drug' in allowed and wrong_path not in allowed
        response=model(req,**kwargs);response['access'][0]['context_paths']=[wrong_path]
        return response
    with pytest.raises(ValueError):testflow.run_stage(main,run,'access',generator=bad)
    assert production.ACCESS_DEFINITION==production_schema
    assert testflow.run_stage(main,run,'access',generator=model)['status']=='COMPLETED_TEST_STAGE'


@pytest.mark.parametrize('field',['item_id','requirement_ids'])
def test_access_other_fixed_ids_cannot_leave_supplied_namespace(case,field):
    tmp,main,model,_=source_without_rules(case);run=tmp/'isolated'
    for stage in ('inventory','define'):testflow.run_stage(main,run,stage,generator=model)
    def bad(req,**kwargs):
        result=model(req,**kwargs)
        result['access'][0][field]='UNKNOWN' if field=='item_id' else ['UNKNOWN']
        return result
    with pytest.raises(ValueError):testflow.run_stage(main,run,'access',generator=bad)
    assert not (run/'receipts/access.json').exists()


def correction_fixture(tmp_path):
    main=write_json(tmp_path/'main.json',{'objective':'Synthetic'})
    scope={'source_main_ref':production.file_ref(main)}
    payload={'item_id':'T23','page':1,'pages':1,'source_units':{'T23:B415':'Index coordinate',
        'T23:C415':'X unit','T23:C416':'h'},'instructions':'Original instruction'}
    old={**payload,'stage':'DC-label','test_scope':scope}
    req=write_json(tmp_path/'request.json',{'request_sha256':testflow.digest(old),'payload':old})
    res=write_json(tmp_path/'response.json',{'request_sha256':testflow.digest(old),'original_failure':'ambiguous header'})
    correction={'item_id':'T23','page':1,'failed_request_ref':production.file_ref(req),
        'failed_response_ref':production.file_ref(res),'source_units_sha256':testflow.digest(payload['source_units']),
        'page_sha256':testflow.digest({k:payload[k] for k in ('item_id','page','pages','source_units')}),
        'instruction':'Retain one own header for column position; keep source-supported unit evidence.'}
    write_json(tmp_path/'label_corrections.json',{'source_main_ref':scope['source_main_ref'],'corrections':[correction]})
    return payload,scope


def test_correction_only_changes_failed_page_and_leaves_other_cache_payload_identical(tmp_path):
    payload,scope=correction_fixture(tmp_path);before=copy.deepcopy(payload)
    fixed=testflow.label_correction(tmp_path,payload,scope)
    assert payload==before and fixed['source_units']==payload['source_units']
    assert fixed['contract_correction']['authority']=='NON_EVIDENCE_TEST_CONTRACT_CORRECTION'
    for field,value in [('item_id','T22'),('page',2)]:
        other={**payload,field:value};original_hash=testflow.digest(other)
        assert testflow.label_correction(tmp_path,other,scope) is other
        assert testflow.digest(other)==original_hash


@pytest.mark.parametrize('fault',['source','request','response','main','page','duplicate'])
def test_targeted_correction_rejects_changed_bindings(tmp_path,fault):
    payload,scope=correction_fixture(tmp_path)
    if fault=='source':payload['source_units']['T23:C416']='Changed'
    elif fault in ('request','response','main'):
        p=tmp_path/(fault+'.json');p.write_bytes(p.read_bytes()+b' ')
    elif fault=='page':payload['pages']=2
    else:
        p=tmp_path/'label_corrections.json';v=read_json(p);v['corrections'].append(v['corrections'][0]);write_json(p,v)
    with pytest.raises((PipelineError,ValueError)):testflow.label_correction(tmp_path,payload,scope)
