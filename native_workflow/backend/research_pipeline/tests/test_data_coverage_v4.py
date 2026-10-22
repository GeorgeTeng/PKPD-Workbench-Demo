"""Coverage v4 source-scope and replay boundaries; no provider calls."""
import copy
import pytest
from research_pipeline import data_coverage_v4 as v
from research_pipeline import data_coverage_v4_repair as repair


@pytest.fixture
def payload():
    need={'id':'RQ001','kind':'DATA','task_id':'SOURCE_SCOPE','origin':'METHOD_CANDIDATE',
          'required_by':'BEFORE_MODELING','method_profile_ids':['MP004']}
    return {'version':v.VERSION,'part_id':'COV01','round':'ASSIGNED_ONLY','instructions':v.INSTRUCTIONS,
        'units':[{'unit_id':'U0001','scope_id':'A','method_uses':['MODEL_BASED','NCA'],'requirement':need,
                  'criteria':[{'id':'FULL_REQUIREMENT','description':'Observed concentration'},
                              {'id':'FIELD_001','description':'Concentration'}]}],
        'scopes':[{'id':'A','item_ids':['A'],'scientific_scope':{'species':'Mouse'},'method_uses':['MODEL_BASED','NCA']}],
        'source_rows':[['A:A2','SOURCE_CONTENT','A','4.2',0],['B:A2','SOURCE_CONTENT','B','7.1',1],
                       ['A:A1','SOURCE_HEADER','A','Concentration',2],['main:/objective','MAIN',None,'Estimate animal PK.',3]],
        'visible_item_ids':['A','B'],'permitted_item_ids':['A','B','NOTE'],
        'support_item_ids':[],'permitted_item_overviews':[{'item_id':'NOTE'}],'incomplete_item_ids':[]}


def response(payload,status='SUPPORTED'):
    value={'request_sha256':'test','rows':{'U0001':{'checks':{
        criterion['id']:{'s':status,'e':[0] if status in {'SUPPORTED','PARTIAL','CONFLICT'} else [],'x':[],'ce':[],'cx':[],
         'r':'Original observation.' if status=='SUPPORTED' else 'Not established in this scope.',
         'n':'NONE' if status=='SUPPORTED' else 'Inspect a related permitted source.'} for criterion in payload['units'][0]['criteria']},
        'search_item_ids':[],'search_reason':'Only assigned scope reviewed.','deferred_outputs':[],'source_links':[]}}}
    if payload['round']=='TARGETED_COMPLETE':value['rows']['U0001']['new_counterevidence']=[]
    return value


def test_shared_facts_materialize_once_with_exact_evidence(payload):
    out=v.materialize(response(payload),payload)
    assert len(out)==1 and out[0]['method_uses']==['MODEL_BASED','NCA']
    assert out[0]['coverage_status']=='AVAILABLE_CANDIDATE'
    assert out[0]['criteria'][0]['evidence']==[{'source':'A:A2','quote':'4.2'}]
    assert out[0]['criteria'][0]['description']=='Observed concentration'


def test_explicit_criterion_ids_allow_order_change_without_semantic_position_shift(payload):
    raw=response(payload);raw['rows']['U0001']['checks']['FIELD_001']['r']='Field-specific reason.'
    raw['rows']['U0001']['checks']=dict(reversed(list(raw['rows']['U0001']['checks'].items())))
    result=v.materialize(raw,payload)[0]
    assert result['criteria'][0]['reason']=='Original observation.'
    assert result['criteria'][1]['reason']=='Field-specific reason.'


@pytest.mark.parametrize('mode',['unknown_criterion','implicit_criterion','wrong_row_index','implicit_row','blank_quote'])
def test_explicit_selector_contract_rejects_ambiguous_or_empty_references(payload,mode):
    raw=response(payload)
    if mode=='unknown_criterion':raw['rows']['U0001']['checks']['FIELD_999']=raw['rows']['U0001']['checks'].pop('FIELD_001')
    elif mode=='implicit_criterion':raw['rows']['U0001']['checks'].pop('FIELD_001')
    elif mode=='wrong_row_index':payload['source_rows'][0][4]=1
    elif mode=='implicit_row':payload['source_rows'][0].pop()
    else:payload['source_rows'][0][3]='\n'
    with pytest.raises(Exception):v.materialize(raw,payload)


def test_selected_part_then_resume_uses_checked_cache_and_preserves_budget(payload,tmp_path,monkeypatch):
    plan={'version':v.planning.VERSION};planpath=v.write_json(tmp_path/'plan.json',plan)
    source=v.write_json(tmp_path/'source/source_view.json',{})
    second=copy.deepcopy(payload);second['part_id']='COV02'
    built={'version':v.VERSION,'planning_sha256':v.digest(plan),'bindings':{'source_view':v.file_ref(source)},
           'payloads':[payload,second],'scopes':payload['scopes'],'routing_not_assessed':[],
           'upstream_missing_information':{},'catalog':{}}
    monkeypatch.setattr(v.planning,'verify_plan',lambda _:plan)
    monkeypatch.setattr(v,'build',lambda *_:copy.deepcopy(built))
    calls=[]
    def generator(request,**_):
        calls.append(request['payload']['part_id'])
        raw=response(request['payload']);raw['request_sha256']=request['request_sha256'];return raw
    generator.executor_id='EXPLICIT_SELECTOR_TEST'
    out=tmp_path/'out';v.prepare(planpath,source.parent,out)
    checkpoint=v.run_prepared(out,['COV01'],generator)
    assert checkpoint['status']=='PARTIAL_COVERAGE_CHECKPOINT' and not (out/'coverage.json').exists()
    first_budget=v.read_json(out/'model_budget.json')
    v.run_prepared(out,generator=generator)
    assert calls==['COV01','COV02']
    assert v.read_json(out/'model_budget.json')['elapsed_seconds']>=first_budget['elapsed_seconds']
    assert v.read_json(out/'model_budget.json')['calls']==2
    requestpath=out/'requests/COV01.json';request=v.read_json(requestpath)
    request['payload']['source_rows'][0][3]='tampered';v.write_json(requestpath,request)
    with pytest.raises(Exception,match='Prepared request changed'):v.run_prepared(out,generator=generator)
    assert calls==['COV01','COV02']
    v.write_json(requestpath,v.governed_request(payload))
    kept=next((out/'COV01/data_agents/kept').glob('*.json'));cached=v.read_json(kept)
    cached['rows']['U0001']['checks']['FULL_REQUIREMENT']['e']=[1];v.write_json(kept,cached)
    with pytest.raises(Exception,match='unassigned|is not one of|not valid under any'):v.run_prepared(out,generator=generator)
    assert calls==['COV01','COV02']  # No fresh provider call to replace a corrupt cache.


@pytest.mark.parametrize('mode',['other_primary','header_only','unknown_index','missing_initial','counter_hidden','missing_check','extra_row','heldout_search','read_again'])
def test_invalid_boundaries_rejected(payload,mode):
    raw=response(payload);a=raw['rows']['U0001']
    if mode=='other_primary':a['checks']['FULL_REQUIREMENT']['e']=[1]
    elif mode=='header_only':a['checks']['FULL_REQUIREMENT']['e']=[2]
    elif mode=='unknown_index':a['checks']['FULL_REQUIREMENT']['e']=[99]
    elif mode=='missing_initial':a['checks']['FULL_REQUIREMENT'].update(s='MISSING',e=[],n='Find data')
    elif mode=='counter_hidden':a['checks']['FULL_REQUIREMENT']['x']=[0]
    elif mode=='missing_check':a['checks'].pop('FIELD_001')
    elif mode=='extra_row':raw['rows']['U9999']=copy.deepcopy(a)
    elif mode=='heldout_search':a['search_item_ids']=['HORSE']
    else:a['search_item_ids']=['B']
    with pytest.raises(Exception):v.materialize(raw,payload)


def test_unknown_is_not_globally_missing_and_target_request_retained(payload):
    raw=response(payload,'UNRESOLVED');raw['rows']['U0001'].update(search_item_ids=['NOTE'],search_reason='Related regimen note.')
    result=v.materialize(raw,payload)[0]
    assert result['search_item_ids']==['NOTE']
    assert result['criteria'][0]['search_state']=='ASSIGNED_SCOPE_REVIEWED'
    assert result['criteria'][0]['unread_item_ids']==['NOTE']


def test_target_search_still_cannot_use_foreign_primary_as_support(payload):
    payload['round']='TARGETED_COMPLETE';raw=response(payload)
    raw['rows']['U0001']['checks']['FULL_REQUIREMENT']['e']=[1]
    with pytest.raises(Exception,match='unassigned|is not one of|not valid under any'):v.materialize(raw,payload)


def test_target_search_missing_allowed_only_when_no_remaining_requested_source(payload):
    payload['round']='TARGETED_COMPLETE';raw=response(payload,'MISSING')
    assert v.materialize(raw,payload)[0]['coverage_status']=='MISSING'
    raw['rows']['U0001'].update(search_item_ids=['NOTE'],search_reason='Still unreviewed.')
    with pytest.raises(Exception,match='Incomplete search'):v.materialize(raw,payload)


def test_target_response_cannot_rewrite_frozen_supported_check(payload):
    payload['round']='TARGETED_COMPLETE'
    first=response(payload)['rows']['U0001']['checks']['FULL_REQUIREMENT']
    payload['units'][0].update(response_criterion_ids=['FIELD_001'],fixed_checks={'FULL_REQUIREMENT':first})
    raw=response(payload,'UNRESOLVED');raw['rows']['U0001']['checks'].pop('FULL_REQUIREMENT')
    out=v.materialize(raw,payload)[0]
    assert out['criteria'][0]['status']=='SUPPORTED'
    assert out['criteria'][1]['status']=='UNRESOLVED'
    raw['rows']['U0001']['checks']['FULL_REQUIREMENT']=first
    with pytest.raises(Exception):v.materialize(raw,payload)


def test_deferred_producer_requires_project_source(payload):
    raw=response(payload,'DEFERRED')
    raw['rows']['U0001']['deferred_outputs']=[{'producer_task':'Animal PK','output':'Predicted exposure',
                                              'first_dependency':'Index calculation','source_indices':[0]}]
    with pytest.raises(Exception,match='context/rule|is not one of'):v.materialize(raw,payload)
    raw['rows']['U0001']['deferred_outputs'][0]['source_indices']=[3]
    assert v.materialize(raw,payload)[0]['deferred_dependencies']==['Index calculation']


def test_full_mock_run_replay_rejects_changes(payload,tmp_path,monkeypatch):
    plan={'version':v.planning.VERSION};planpath=v.write_json(tmp_path/'plan.json',plan)
    source=v.write_json(tmp_path/'source/source_view.json',{})
    built={'version':v.VERSION,'planning_sha256':v.digest(plan),'bindings':{'source_view':v.file_ref(source)},
           'payloads':[payload],'scopes':payload['scopes'],'routing_not_assessed':[],
           'upstream_missing_information':{'items':[]},'catalog':{r[0]:{'content':r[3],'kind':r[1],'item_id':r[2]} for r in payload['source_rows']}}
    monkeypatch.setattr(v.planning,'verify_plan',lambda path:plan)
    monkeypatch.setattr(v,'build',lambda *_:copy.deepcopy(built))
    def generator(request,**_):
        raw=response(payload);raw['request_sha256']=request['request_sha256'];return raw
    out=tmp_path/'out';result=v.run(planpath,source.parent,out,generator)
    assert v.verify_result(out/'coverage.json')==result
    assert result['pending_global_gates']==v.PENDING_GLOBAL_GATES
    result['matches'][0]['criteria'][0]['status']='MISSING';v.write_json(out/'coverage.json',result)
    with pytest.raises(Exception,match='raw derivation'):v.verify_result(out/'coverage.json')


def add_notes(payload):
    payload['source_rows'] += [['A:note','SOURCE_NOTE','A','Original record states that B shares the explicitly identified source records.',4],
                               ['B:note','SOURCE_NOTE','B','Original record confirms the A-linked record identities and timing.',5]]


def test_explicit_original_link_can_authorize_target_body_in_same_review(payload):
    add_notes(payload);raw=response(payload)
    raw['rows']['U0001']['source_links']=[{'item_id':'B','relation':'EXPLICIT_RECORD_LINK',
        'scope_basis':'Same recorded subjects and timing explicitly linked in both notes.',
        'reason':'Source-supported link, not rank matching.','evidence_indices':[4,5]}]
    raw['rows']['U0001']['checks']['FULL_REQUIREMENT']['e']=[]
    raw['rows']['U0001']['checks']['FULL_REQUIREMENT']['ce']=[1]
    out=v.materialize(raw,payload)[0]
    assert out['criteria'][0]['evidence'][0]['source']=='B:A2'
    raw['rows']['U0001']['source_links'][0]['relation']='CONTEXT_DEPENDENCY'
    with pytest.raises(Exception,match='unassigned|is not one of|not valid under any'):v.materialize(raw,payload)


def test_link_cannot_be_inferred_from_numeric_body_or_one_sided_note(payload):
    add_notes(payload);raw=response(payload)
    link={'item_id':'B','relation':'EXPLICIT_RECORD_LINK','scope_basis':'Same scope',
          'reason':'Attempted unsupported relation','evidence_indices':[0,1]}
    raw['rows']['U0001']['source_links']=[link]
    with pytest.raises(Exception,match='textual notes'):v.materialize(raw,payload)
    link['evidence_indices']=[4,3]
    with pytest.raises(Exception,match='local and target'):v.materialize(raw,payload)


def test_new_counterevidence_preserves_original_supported_evidence(payload):
    payload['round']='TARGETED_COMPLETE';payload['support_item_ids']=['NOTE'];payload['visible_item_ids'].append('NOTE')
    payload['newly_read_item_ids']=['NOTE']
    payload['source_rows'].append(['NOTE:1','SOURCE_NOTE','NOTE','Reported concentration conflicts with source correction.',4])
    old=response(payload)['rows']['U0001']['checks']['FULL_REQUIREMENT']
    payload['units'][0].update(response_criterion_ids=['FIELD_001'],fixed_checks={'FULL_REQUIREMENT':old})
    raw=response(payload,'UNRESOLVED');raw['rows']['U0001']['checks'].pop('FULL_REQUIREMENT')
    raw['rows']['U0001']['new_counterevidence']=[{'criterion_id':'FULL_REQUIREMENT','source_indices':[4],
        'reason':'New correction contradicts the retained reading.','needed_material':'Reconcile original correction.'}]
    out=v.materialize(raw,payload)[0]
    assert out['criteria'][0]['status']=='CONFLICT'
    assert [x['source'] for x in out['criteria'][0]['evidence']]==['A:A2','NOTE:1']
    assert out['new_counterevidence'][0]['previous_status']=='SUPPORTED'
    payload['newly_read_item_ids']=[]
    with pytest.raises(Exception,match='newly read'):v.materialize(raw,payload)


def test_saved_initial_to_targeted_search_replays_without_rewriting_parent(payload,tmp_path,monkeypatch):
    payload['support_item_ids']=['NOTE']
    plan={'version':v.planning.VERSION};planpath=v.write_json(tmp_path/'plan.json',plan)
    source=v.write_json(tmp_path/'source/source_view.json',{})
    catalog={r[0]:{'content':r[3],'kind':r[1],'item_id':r[2]} for r in payload['source_rows']}
    catalog['NOTE:1']={'content':'Additional source note.','kind':'SOURCE_NOTE','item_id':'NOTE'}
    built={'version':v.VERSION,'planning_sha256':v.digest(plan),'bindings':{'source_view':v.file_ref(source)},
           'payloads':[payload],'scopes':payload['scopes'],'routing_not_assessed':[],
           'upstream_missing_information':{},'catalog':catalog}
    monkeypatch.setattr(v.planning,'verify_plan',lambda _:plan)
    monkeypatch.setattr(v,'build',lambda *_:copy.deepcopy(built))
    def initial(request,**_):
        raw=response(payload,'UNRESOLVED');raw['rows']['U0001']['checks']['FULL_REQUIREMENT']=response(payload)['rows']['U0001']['checks']['FULL_REQUIREMENT']
        raw['rows']['U0001']['checks']=dict(reversed(list(raw['rows']['U0001']['checks'].items())))  # Order must not change which criterion is fixed.
        raw['rows']['U0001'].update(search_item_ids=['NOTE'],search_reason='Inspect additional note.')
        raw['request_sha256']=request['request_sha256'];return raw
    first=tmp_path/'first';v.run(planpath,source.parent,first,initial)
    original_ref=v.file_ref(first/'coverage.json')
    parent_budget=v.read_json(first/'model_budget.json')
    preview=v._search_build(first/'coverage.json')
    assert preview['prior_model_seconds']==parent_budget['elapsed_seconds']
    assert preview['prior_model_calls']==parent_budget['calls']+parent_budget.get('prior_calls',0)
    assert preview['bindings']['parent_model_budget']==v.file_ref(first/'model_budget.json')
    def targeted(request,**_):
        p=request['payload'];assert p['units'][0]['response_criterion_ids']==['FIELD_001']
        assert set(p['units'][0]['fixed_checks'])=={'FULL_REQUIREMENT'}
        raw=response(p);raw['rows']['U0001']['checks'].pop('FULL_REQUIREMENT')
        raw['request_sha256']=request['request_sha256'];return raw
    second=tmp_path/'second';result=v.run_search(first/'coverage.json',second,generator=targeted)
    assert v.verify_result(second/'coverage.json')==result
    assert v.file_ref(first/'coverage.json')==original_ref
    assert result['matches'][0]['criteria'][0]['evidence']==[{'source':'A:A2','quote':'4.2'}]
    assert result['matches'][0]['criteria'][1]['search_state']=='TARGETED_COMPLETE'
    parent_budget['elapsed_seconds']+=1;v.write_json(first/'model_budget.json',parent_budget)
    with pytest.raises(Exception):v.verify_result(second/'coverage.json')


def test_search_reassesses_host_unqualified_full_and_inherits_final_ledger(payload,tmp_path,monkeypatch):
    payload['source_rows'][0][1]='SOURCE_NOTE'
    plan={'version':v.planning.VERSION};planpath=v.write_json(tmp_path/'plan.json',plan)
    source=v.write_json(tmp_path/'source/source_view.json',{})
    catalog={r[0]:{'content':r[3],'kind':r[1],'item_id':r[2]} for r in payload['source_rows']}
    catalog['NOTE:1']={'content':'An additional original note.','kind':'SOURCE_NOTE','item_id':'NOTE'}
    built={'version':v.VERSION,'planning_sha256':v.digest(plan),'bindings':{'source_view':v.file_ref(source)},
        'payloads':[payload],'scopes':payload['scopes'],'routing_not_assessed':[],
        'upstream_missing_information':{},'catalog':catalog,'prior_model_seconds':520.282,'prior_model_calls':4}
    monkeypatch.setattr(v.planning,'verify_plan',lambda _:plan)
    monkeypatch.setattr(v,'build',lambda *_:copy.deepcopy(built))
    def initial(request,**_):
        raw=response(payload);raw['request_sha256']=request['request_sha256']
        raw['rows']['U0001'].update(search_item_ids=['NOTE'],search_reason='Check a relevant note.')
        return raw
    out=tmp_path/'initial';v.run(planpath,source.parent,out,initial)
    search=v._search_build(out/'coverage.json');u=search['payloads'][0]['units'][0]
    assert u['response_criterion_ids']==['FULL_REQUIREMENT'] and set(u['fixed_checks'])=={'FIELD_001'}
    ledger=v.read_json(out/'model_budget.json')
    assert search['prior_model_seconds']==ledger['elapsed_seconds']>=520.282
    assert search['prior_model_calls']==5
    ledger['build_sha256']='wrong';v.write_json(out/'model_budget.json',ledger)
    with pytest.raises(Exception,match='parent budget'):v._search_build(out/'coverage.json')


def test_sparse_printed_selectors_are_not_list_positions(payload):
    payload['source_rows']=payload['source_rows'][1:]
    raw=response(payload);raw['rows']['U0001']['checks']['FULL_REQUIREMENT']['e']=[1]
    with pytest.raises(Exception):v.materialize(raw,payload)
    raw=response(payload,'UNRESOLVED')
    assert v.materialize(raw,payload)[0]['status']=='UNRESOLVED'


def test_omitted_primary_body_cannot_be_cited_from_host_catalog(payload):
    payload['source_rows']=[r for r in payload['source_rows'] if r[0]!='B:A2']
    raw=response(payload);raw['rows']['U0001']['checks']['FULL_REQUIREMENT'].update(e=[],ce=[1])
    with pytest.raises(Exception):v.materialize(raw,payload)


def test_cross_source_path_requires_a_declared_link(payload):
    raw=response(payload);raw['rows']['U0001']['checks']['FULL_REQUIREMENT'].update(e=[],ce=[1])
    with pytest.raises(Exception,match='unassigned'):v.materialize(raw,payload)
    raw['rows']['U0001']['checks']['FULL_REQUIREMENT']['ce']=[0]
    with pytest.raises(Exception,match='distinct explicitly linked|not valid under any'):v.materialize(raw,payload)


def test_repair_locks_unrequested_checks_and_omits_them_from_wire(payload):
    prior=response(payload)['rows']['U0001']['checks']
    unit=payload['units'][0];unit.update(response_criterion_ids=['FULL_REQUIREMENT'],fixed_checks={'FIELD_001':prior['FIELD_001']})
    payload['repair_scope']={'allowed_changes':'named only'}
    transported=v.governed_request(payload)['payload']
    assert 'fixed_checks' not in transported['units'][0]
    assert transported['units'][0]['unchanged_prior_check_count']==1
    raw=response(payload,'UNRESOLVED');raw['rows']['U0001']['checks'].pop('FIELD_001')
    checked=v.materialize(raw,payload)[0]
    assert checked['criteria'][1]['status']=='SUPPORTED'
    raw['rows']['U0001']['checks']['FIELD_001']=prior['FIELD_001']
    with pytest.raises(Exception):v.materialize(raw,payload)


def test_repair_cannot_remove_preserved_deferred_dependency(payload):
    old={'producer_task':'PK','output':'Exposure','first_dependency':'PD','source_indices':[3]}
    payload['units'][0]['preserved_deferred_outputs']=[old]
    raw=response(payload,'UNRESOLVED')
    with pytest.raises(Exception,match='preserved dependency'):v.materialize(raw,payload)


def test_diagnosis_targets_authority_only_claim_and_wrong_scope_not_scientific_verdict(payload):
    class Old:
        @staticmethod
        def materialize(raw,p):
            converted=copy.deepcopy(raw)
            for a in converted['rows'].values():
                a['checks']={x['criterion_id']:{k:value for k,value in x.items() if k!='criterion_id'}|{'ce':[],'cx':[]} for x in a['checks']}
            return v.materialize(converted,p)
    raw=response(payload)
    raw['rows']['U0001']['checks']['FIELD_001']['e']=[3]
    raw['rows']['U0001']['checks']=[{'criterion_id':cid,**{k:val for k,val in c.items() if k not in ('ce','cx')}} for cid,c in raw['rows']['U0001']['checks'].items()]
    diagnosed=repair.diagnose(payload,raw,Old)
    assert 'FIELD_001' in diagnosed['U0001']['targets']
    assert any('Authority is not an observation' in x for x in diagnosed['U0001']['targets']['FIELD_001'])
    assert raw['rows']['U0001']['checks'][1]['s']=='SUPPORTED'


def test_local_field_classification_is_lossless_and_does_not_mutate_model_raw(payload):
    raw=response(payload);raw['rows']['U0001']['checks']['FULL_REQUIREMENT']['ce']=[0,2]
    before=copy.deepcopy(raw)
    derived,audit=repair.classify_references(raw,payload)
    assert raw==before
    check=derived['rows']['U0001']['checks']['FULL_REQUIREMENT']
    assert check['e']==[0,2] and check['ce']==[] and audit
    assert check['s']==before['rows']['U0001']['checks']['FULL_REQUIREMENT']['s']
    assert check['r']==before['rows']['U0001']['checks']['FULL_REQUIREMENT']['r']
    assert check['n']==before['rows']['U0001']['checks']['FULL_REQUIREMENT']['n']


def test_classification_cannot_authorize_foreign_or_unknown_sources(payload):
    raw=response(payload);raw['rows']['U0001']['checks']['FULL_REQUIREMENT']['ce']=[1]
    with pytest.raises(Exception,match='unassigned'):repair.classify_references(raw,payload)
    raw['rows']['U0001']['checks']['FULL_REQUIREMENT']['ce']=[999]
    with pytest.raises(Exception,match='unseen'):repair.classify_references(raw,payload)


def test_classification_preserves_counterevidence_polarity(payload):
    raw=response(payload,'CONFLICT');check=raw['rows']['U0001']['checks']['FULL_REQUIREMENT'];check['cx']=[2]
    derived,_=repair.classify_references(raw,payload)
    actual=derived['rows']['U0001']['checks']['FULL_REQUIREMENT']
    assert actual['s']=='CONFLICT' and actual['e']==[0] and actual['x']==[2] and actual['cx']==[]


def test_full_unit_correction_restores_every_description_without_carrying_fixed_judgments(payload):
    raw=response(payload);before=copy.deepcopy(payload)
    payload['units'][0].update(response_criterion_ids=['FIELD_001'],fixed_checks={'FULL_REQUIREMENT':raw['rows']['U0001']['checks']['FULL_REQUIREMENT']},
        fixed_metadata={'search_item_ids':[]},preserved_deferred_outputs=[{'old':'dependency'}])
    result=repair._correction_payload(payload,raw,{'semantic_spotcheck_flags':[]})
    u=result['units'][0]
    assert u['response_criterion_ids']==['FULL_REQUIREMENT','FIELD_001']
    assert not any(k in u for k in ('fixed_checks','fixed_metadata','preserved_deferred_outputs'))
    assert u['criteria']==before['units'][0]['criteria']
    assert result['source_rows']==before['source_rows'] and result['scopes']==before['scopes']
    assert u['prior_target_checks']==raw['rows']['U0001']['checks']
    assert 'reported numerical fact' in result['instructions'] and 'UNRESOLVED' in result['instructions']
    assert 'adjacent criterion description' in result['instructions']


def test_sol_routing_keeps_original_body_predicate(payload):
    assert v.MODEL=='gpt-6-sol'
    raw=response(payload);payload['source_rows'][0][1]='SOURCE_NOTE'
    materialized=v.materialize(raw,payload)[0]
    assert materialized['criteria'][0]['status']=='UNRESOLVED'
    # The low-level gate still rejects the original positive note-only claim.
    criterion=copy.deepcopy(materialized['criteria'][0]);criterion['status']='SUPPORTED'
    catalog={r[0]:{'content':r[3],'kind':r[1],'item_id':r[2]} for r in payload['source_rows']}
    with pytest.raises(Exception,match='original body evidence'):
        v.c.validate_match(payload['units'][0]['requirement'],{'criteria':[criterion]},
            {'criteria':[payload['units'][0]['criteria'][0]],'allowed_source_ids':list(catalog)},catalog)


def test_note_qualification_preserves_raw_fields_and_exposes_host_origin(payload):
    payload['source_rows'][0][1]='SOURCE_NOTE';raw=response(payload,'PARTIAL');before=copy.deepcopy(raw)
    actual=v.materialize(raw,payload)[0]
    full,field=actual['criteria']
    assert raw==before and full['status']=='UNRESOLVED' and field['status']=='PARTIAL'
    assert full['evidence']==field['evidence']==[{'source':'A:A2','quote':'4.2'}]
    assert full['host_qualification']['original_model_criterion']['status']=='PARTIAL'
    assert 'not absent' in full['needed_material']
    assert 'host_qualification' not in field


def test_note_qualification_cannot_authorize_foreign_source_or_authority_only(payload):
    raw=response(payload);raw['rows']['U0001']['checks']['FULL_REQUIREMENT']['e']=[3]
    with pytest.raises(Exception,match='original body'):v.materialize(raw,payload)
    payload['source_rows'][1][1]='SOURCE_NOTE';raw['rows']['U0001']['checks']['FULL_REQUIREMENT']['e']=[1]
    with pytest.raises(Exception):v.materialize(raw,payload)


@pytest.mark.parametrize('tamper',[None,'raw_binding','source_identity','budget_binding'])
def test_model_correction_replays_actual_parent_and_cumulative_budget(payload,tmp_path,monkeypatch,tamper):
    def save(name,value):return v.file_ref(v.write_json(tmp_path/name,value))
    code=save('code.json',{'frozen':True});request={'request_sha256':'sent'}
    raw=response(payload);raw['request_sha256']='sent'
    parent={'bindings':{'code':code,'repair_code':code},'planning_sha256':'plan','catalog':{'source':'original'},'payloads':[payload]}
    spec={'part_id':'COV01','parent_build':save('build.json',parent),'code_snapshot':code,'repair_snapshot':code,
          'request':save('request.json',request),'response':save('raw.json',raw),
          'budget':save('budget.json',{'build_sha256':v.digest(parent),'elapsed_seconds':391.282,'calls':1,'prior_calls':2}),
          'findings':save('findings.json',{'semantic_spotcheck_flags':[]})}
    class Frozen:
        MODEL='gpt-6-luna'
        @staticmethod
        def governed_request(p):return request
        @staticmethod
        def response_schema(p):return v.response_schema(p)
    monkeypatch.setattr(repair,'_old_module',lambda _:Frozen)
    current=copy.deepcopy(parent)
    if tamper=='raw_binding':raw['request_sha256']='unsent';spec['response']=save('wrongraw.json',raw)
    if tamper=='source_identity':current['catalog']={'source':'changed'}
    if tamper=='budget_binding':spec['budget']=save('badbudget.json',{'build_sha256':'wrong','elapsed_seconds':0,'calls':0})
    if tamper:
        with pytest.raises(Exception):repair._model_correction(current,spec)
    else:
        result=repair._model_correction(current,spec)
        assert result['prior_model_seconds']==391.282 and result['prior_model_calls']==3
        assert result['model_routing']['new_calls_model']=='gpt-6-sol'
        assert result['payloads'][0]['source_rows']==parent['payloads'][0]['source_rows']
