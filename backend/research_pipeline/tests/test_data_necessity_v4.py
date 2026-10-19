"""Action/gap counterexamples and replay tests; no actual data or provider call."""
import copy
from types import SimpleNamespace

import pytest
from ctxcomp.io import digest
from research_pipeline import data_necessity_v4 as n
from research_pipeline.common import PipelineError, read_json, write_json


def fixture(family='MODEL_BASED', status='MISSING', origin='METHOD_CANDIDATE'):
    authority = 'main:/rules/0/text'
    plan = {'version': n.planner.VERSION, 'requirements': [{'id': 'RQ001',
        'description': 'Concentration/time or applicable model output', 'input_fields': ['Value'],
        'method_uses': [family], 'conditions': ['Use group summaries at group level'],
        'required_by': 'BEFORE_MODELING', 'origin': origin, 'method_profile_ids': [],
        'project_source_ids': [authority],
        'evidence': [{'source': authority, 'quote': 'Only individual analysis needs individual IDs.'}]}]}
    catalog = {authority: plan['requirements'][0]['evidence'][0]['quote'],
        'I1:note': {'content': 'Group means, no individual IDs.', 'kind': 'SOURCE_NOTE', 'item_id': 'I1'}}
    c = {'id': 'FIELD_001', 'status': status, 'reason': 'Not provided in the reviewed scope.',
         'needed_material': 'Source-supported input', 'evidence': [{'source': 'I1:note', 'quote': 'Group means'}],
         'counterevidence': [{'source': 'I1:note', 'quote': 'no individual IDs'}],
         'search_state': 'TARGETED_COMPLETE', 'searched_item_ids': ['I1'], 'unread_item_ids': []}
    cov = {'version': 'COVERAGE_FACTS_4.0', 'planning_sha256': digest(plan),
       'scopes': [{'id': 'S1', 'item_ids': ['I1'], 'scientific_scope': {'study': 'A', 'species': 'Mouse',
           'matrix': 'Plasma', 'regimen': 'A', 'window': 'source', 'record_level': 'Group'}, 'method_uses': [family]}],
       'matches': [{'scope_id': 'S1', 'requirement_id': 'RQ001', 'method_uses': [family],
           'criteria': [c], 'deferred_outputs': []}], 'pending_global_gates': ['G008 unresolved'],
       'routing_not_assessed': []}
    return plan, cov, catalog


def rules():
    return [{'id':'R001','text':'Only individual analysis needs individual IDs.',
        'conditions':['Individual analysis is intended'], 'exceptions':['Group summaries may be analysed at group level'],
        'scope':{'record_level':'individual'}, 'requirement':{'action':'Retain verified IDs'},
        'usage':{'required_phase':'BEFORE_MODELING'},'provenance':{'main_pointer':'/rules/0'}}]


def answer(payload):
    registry,lookup=n.evidence_registry(payload)
    raw = {'request_sha256': 'fake', 'decisions': []}
    for g in payload['gaps']:
        action = g['actions'][1]
        raw['decisions'].append({'unit_id': g['unit_id'], 'criterion_ids': [g['criterion_id']],
            'necessity': 'REQUIRED', 'applicability': 'APPLIES',
            'first_dependency_action': action, 'first_dependency_phase': 'BEFORE_MODELING',
            'reason': 'Input is required for the consuming action, not source-preserving preparation.',
            'timing_reason': 'Original action timing is retained.',
            'evidence_refs': [lookup[next((s for s in ('I1:note','I2:note') if (s,'Group means') in lookup)), 'Group means'],lookup['main:/rules/0/text','Only individual analysis needs individual IDs.']], 'exception': None,
            'impacts': [{'action_id': a, 'dependency': 'NOT_YET' if a == n.CURRENT_ACTION else 'REQUIRED_NOW',
                        'reason': 'Task dependency'} for a in g['actions']],
            'disposition': 'EXISTING_SOURCE_REVIEW', 'for_action': 'NONE',
            'new_data': {'needed_for_current_action': False, 'applicability_resolved': True,
                'permitted_search_complete': True, 'existing_material_can_supply': False,
                'definition_pending': False, 'planned_output_pending': False}, 'human_review': False})
    return raw


def wire_answer(payload):
    canonical=answer(payload);units={}
    for d in canonical['decisions']:
        row=units.setdefault(d['unit_id'],{'criterion_groups':{},'groups':[]})
        group={k:copy.deepcopy(v) for k,v in d.items() if k not in ('unit_id','criterion_ids')}
        group['impacts']={i['action_id']:{k:v for k,v in i.items() if k!='action_id'} for i in d['impacts']}
        row['criterion_groups'].update({c:len(row['groups']) for c in d['criterion_ids']})
        row['groups'].append(group)
    return {'request_sha256':'fake','units':units}


def build(*args, **kwargs):
    p,c,s = fixture(*args, **kwargs)
    payload = n.build_payload(p,c,s,project_rules=rules())
    return payload, answer(payload)


def test_future_consuming_action_does_not_block_preparation_and_retains_all_facts():
    payload, raw = build(family='PTA', status='DEFERRED')
    payload['units'][0]['deferred_outputs'] = [{'producer_task': 'PD_TARGET', 'output': 'Qualified target'}]
    raw['decisions'][0]['disposition'] = 'PLANNED_MODEL_OUTPUT'
    original = copy.deepcopy(payload)
    result = n.resolve(raw,payload)
    actions = {a['action_id']: a for a in result['methods'][0]['actions']}
    assert actions[n.CURRENT_ACTION]['input_supported']
    assert not actions['SIMULATE_PER_MIC_PTA']['input_supported']
    assert payload == original and result['coverage_facts'] == payload['units']
    assert result['coverage_facts'][0]['criteria'][0]['counterevidence']
    assert result['pending_global_gates'] == ['G008 unresolved']
    assert not any(result[k] for k in ['scientific_approval','can_enter_qc','fit_ready'])


def test_supported_inputs_do_not_get_rejudged():
    payload, raw = build(status='SUPPORTED')
    assert not payload['gaps'] and not raw['decisions']
    assert n.resolve(raw,payload)['methods'][0]['actions'][0]['input_supported']


@pytest.mark.parametrize('change', ['omit','duplicate','unknown','supported'])
def test_no_gap_disappears_or_supported_criterion_gets_changed(change):
    payload, raw = build()
    if change=='omit': raw['decisions']=[]
    elif change=='duplicate': raw['decisions']*=2
    elif change=='unknown': raw['decisions'][0]['criterion_ids']=['alien']
    else: payload['gaps']=[]
    with pytest.raises(PipelineError): n.resolve(raw,payload)


def test_criterion_grouping_is_expanded_without_multiplying_model_method_rows():
    plan,cov,catalog=fixture()
    plan['requirements'][0]['method_uses'].append('NCA');cov['planning_sha256']=digest(plan)
    cov['matches'][0]['method_uses'].append('NCA')
    c=copy.deepcopy(cov['matches'][0]['criteria'][0]);c['id']='FIELD_002';cov['matches'][0]['criteria'].append(c)
    payload=n.build_payload(plan,cov,catalog,project_rules=rules());raw=answer(payload)
    assert len(payload['gaps'])==2
    raw['decisions'][0]['criterion_ids'].append('FIELD_002');raw['decisions'].pop()
    result=n.resolve(raw,payload)
    assert len(result['decisions'])==2 and len(result['methods'])==2


def test_changed_plan_digest_rejected():
    plan,cov,catalog=fixture();plan['requirements'][0]['required_by']='BEFORE_PTA'
    with pytest.raises(PipelineError): n.build_payload(plan,cov,catalog,project_rules=rules())


def test_other_scope_source_cannot_prove_local_gap():
    plan,cov,catalog=fixture();catalog['I2:note']={'content':'Group means','kind':'SOURCE_NOTE','item_id':'I2'}
    cov['matches'][0]['criteria'][0]['evidence']=[{'source':'I2:note','quote':'Group means'}]
    with pytest.raises(PipelineError): n.build_payload(plan,cov,catalog,project_rules=rules())


def test_decision_cannot_borrow_another_units_evidence():
    payload,raw=build();payload['evidence_catalog']['I2:note']='Individual animals'
    raw['decisions'][0]['evidence_refs']=['E99999']
    with pytest.raises(PipelineError):n.resolve(raw,payload)


def test_timing_correction_preserves_original_required_by():
    payload,raw=build(family='PD_INDEX')
    payload['requirements'][0]['required_by']='BEFORE_PTA'
    raw['decisions'][0]['first_dependency_phase']='BEFORE_INDEX_ANALYSIS'
    result=n.resolve(raw,payload)
    assert result['decisions'][0]['original_required_by']=='BEFORE_PTA'
    assert result['decisions'][0]['timing_discrepancy']
    raw['decisions'][0]['timing_reason']=''
    with pytest.raises(PipelineError):n.resolve(raw,payload)


def make_exception(raw):
    d=raw['decisions'][0];d['applicability']='NOT_APPLICABLE'
    d['first_dependency_action']='NOT_APPLICABLE';d['first_dependency_phase']='NOT_APPLICABLE'
    for i in d['impacts']:i['dependency']='NOT_APPLICABLE'
    d['exception']={'rule_source':'main:/rules/0/text','clause_quote':'Only individual analysis needs individual IDs.',
        'local_evidence_refs':raw['decisions'][0]['evidence_refs'][:1],
        'evidence_clear':True,'scope_matches':True,'conflict':False,'human_required':False}


def test_clear_original_scope_clause_can_apply_without_forced_human():
    payload,raw=build(origin='PROJECT_EXPLICIT');make_exception(raw)
    result=n.resolve(raw,payload)
    assert result['decisions'][0]['applicability']=='NOT_APPLICABLE'
    assert result['decisions'][0]['coverage_status']=='MISSING'
    assert not result['decisions'][0]['human_review']


@pytest.mark.parametrize('flag,value',[('evidence_clear',False),('scope_matches',False),('conflict',True),('human_required',True)])
def test_unclear_or_human_exception_cannot_waive(flag,value):
    payload,raw=build(origin='PROJECT_EXPLICIT');make_exception(raw)
    raw['decisions'][0]['exception'][flag]=value
    with pytest.raises(PipelineError):n.resolve(raw,payload)


def test_required_cannot_be_waived_due_only_to_missingness():
    payload,raw=build();make_exception(raw);raw['decisions'][0]['exception']=None
    with pytest.raises(PipelineError):n.resolve(raw,payload)


def test_method_knowledge_cannot_establish_observed_scope_exception():
    payload,raw=build();make_exception(raw)
    raw['decisions'][0]['exception']['local_evidence_refs']=['E00001']
    with pytest.raises(PipelineError):n.resolve(raw,payload)


def new_data(raw):
    d=raw['decisions'][0];d['for_action']=d['first_dependency_action']
    d['new_data']['needed_for_current_action']=True;d['disposition']='NEW_DATA'


@pytest.mark.parametrize('field,wrong',[('needed_for_current_action',False),('applicability_resolved',False),
    ('permitted_search_complete',False),('existing_material_can_supply',True),('definition_pending',True),('planned_output_pending',True)])
def test_each_new_data_prerequisite_required(field,wrong):
    payload,raw=build();new_data(raw);raw['decisions'][0]['new_data'][field]=wrong
    with pytest.raises(PipelineError):n.resolve(raw,payload)


def test_unfinished_search_cannot_become_new_experiment_advice():
    payload,raw=build();new_data(raw);payload['units'][0]['criteria'][0]['search_state']='TARGETED_INCOMPLETE'
    with pytest.raises(PipelineError):n.resolve(raw,payload)


def test_new_data_advice_never_authorizes_experiment_or_satisfies_input():
    payload,raw=build();new_data(raw);r=n.resolve(raw,payload)
    assert not r['decisions'][0]['experiment_authorized']
    assert not r['decisions'][0]['counts_as_satisfied']
    assert r['groups'][0]['current_action_input_supported']
    assert r['groups'][0]['selected_analysis_status']=='INPUTS_NEED_ATTENTION'


def test_identical_scope_metadata_different_panels_never_merge():
    plan,cov,catalog=fixture()
    scope=copy.deepcopy(cov['scopes'][0]);scope['id']='S2';cov['scopes'].append(scope)
    match=copy.deepcopy(cov['matches'][0]);match['scope_id']='S2';cov['matches'].append(match)
    payload=n.build_payload(plan,cov,catalog,project_rules=rules());r=n.resolve(answer(payload),payload)
    assert len(r['groups'])==2 and len(r['methods'])==2


def test_mb_preferred_nca_alternative_keeps_failed_gaps():
    plan,cov,catalog=fixture();plan['requirements'][0]['method_uses']=['MODEL_BASED','NCA'];cov['planning_sha256']=digest(plan)
    cov['matches'][0]['method_uses']=['MODEL_BASED','NCA']
    payload=n.build_payload(plan,cov,catalog,project_rules=rules());r=n.resolve(answer(payload),payload)
    assert r['groups'][0]['preferred_family']=='MODEL_BASED'
    assert r['groups'][0]['needs_attention'] and r['groups'][0]['current_action_input_supported']


def test_runtime_single_injected_call_and_replay_detects_tampering(tmp_path,monkeypatch):
    plan,cov,catalog=fixture();inputs=tmp_path/'inputs';out=tmp_path/'necessity'
    pp=write_json(inputs/'plan.json',plan);cp=write_json(inputs/'coverage.json',cov)
    monkeypatch.setattr(n,'_verified_inputs',lambda *a:(copy.deepcopy(plan),copy.deepcopy(cov),copy.deepcopy(catalog),rules()))
    monkeypatch.setattr(n,'_review_module',lambda:SimpleNamespace(__file__=n.__file__))
    calls=[]
    def generate(req,**kw):
        calls.append(kw['model']);a=wire_answer(read_json(out/'parts/NEC01/payload.json'));a['request_sha256']=req['request_sha256'];return a
    generate.executor_id='unit-test-necessity'
    r=n.run(pp,cp,out,generator=generate)
    assert calls==['gpt-6-sol'] and n.verify_result(out/'necessity.json')==r
    r['decisions'][0]['coverage_status']='SUPPORTED';write_json(out/'necessity.json',r)
    with pytest.raises(PipelineError):n.verify_result(out/'necessity.json')



def test_structured_original_exception_is_transmitted_and_citable_even_absent_from_rule_text():
    plan,cov,catalog=fixture(origin='PROJECT_EXPLICIT')
    payload=n.build_payload(plan,cov,catalog,project_rules=rules());wire=n.transport_payload(payload)
    source='main:/rules/0/exceptions'
    assert 'Group summaries may be analysed' not in rules()[0]['text']
    assert any(e['source']==source and 'Group summaries may be analysed' in e['quote'] for e in wire['evidence_registry'].values())
    assert len(payload['operative_project_rules'])==1
    raw=answer(payload);make_exception(raw)
    raw['decisions'][0]['exception'].update(rule_source=source,clause_quote='Group summaries may be analysed at group level')
    assert n.resolve(raw,payload)['decisions'][0]['applicability']=='NOT_APPLICABLE'


def test_objective_is_not_an_original_rule_exception():
    payload,raw=build(origin='PROJECT_EXPLICIT');make_exception(raw)
    payload['evidence_catalog']['main:/objective']='Complete this study'
    payload['units'][0]['allowed_source_ids'].append('main:/objective')
    raw['decisions'][0]['exception'].update(rule_source='main:/objective',clause_quote='Complete this study')
    with pytest.raises(PipelineError):n.resolve(raw,payload)


def test_partial_action_waiver_also_requires_a_clear_original_clause():
    payload,raw=build(origin='PROJECT_EXPLICIT');make_exception(raw)
    d=raw['decisions'][0];d['applicability']='APPLIES'
    d['impacts'][1]['dependency']='REQUIRED_NOW';d['first_dependency_action']=d['impacts'][1]['action_id']
    d['exception']['conflict']=True;d['human_review']=True
    with pytest.raises(PipelineError):n.resolve(raw,payload)


def test_routing_unassessed_is_not_silently_counted_as_supported():
    payload,raw=build(status='SUPPORTED')
    payload['routing_not_assessed']=[{'scope_id':'S1','requirement_id':'RQ001','state':'ROUTING_NOT_ASSESSED','reason':'Not routed'}]
    result=n.resolve(raw,payload)
    assert not result['groups'][0]['current_action_input_supported']
    assert result['groups'][0]['needs_attention']
    assert result['methods'][0]['actions'][0]['routing_not_assessed_requirement_ids']==['RQ001']


def test_actual_analysis_fallback_uses_nca_without_erasing_failed_model_route():
    plan,cov,catalog=fixture()
    second=copy.deepcopy(plan['requirements'][0]);second.update(id='RQ002',method_uses=['NCA'])
    plan['requirements'].append(second);cov['planning_sha256']=digest(plan)
    match=copy.deepcopy(cov['matches'][0]);match.update(requirement_id='RQ002',method_uses=['NCA'])
    match['criteria'][0]['status']='SUPPORTED';cov['matches'].append(match)
    payload=n.build_payload(plan,cov,catalog,project_rules=rules());result=n.resolve(answer(payload),payload)
    group=result['groups'][0]
    assert group['preferred_analysis_input_family']=='NCA'
    assert group['preferred_family']=='MODEL_BASED'  # Source preparation is a different action.
    assert result['decisions'][0]['coverage_status']=='MISSING'


def test_transport_deduplicates_original_quotes_and_never_sends_full_data_catalog():
    payload,raw=build()
    payload['evidence_catalog']['I1:entire_table']='DO_NOT_TRANSMIT_UNCITED_BODY'
    wire=n.transport_payload(payload)
    import json
    assert 'DO_NOT_TRANSMIT_UNCITED_BODY' not in json.dumps(wire)
    assert 'evidence_catalog' not in wire and 'gaps' not in wire
    assert wire['units'][0]['gap_criteria']['FIELD_001']['counterevidence_refs']
    assert len({(e['source'],e['quote']) for e in wire['evidence_registry'].values()})==len(wire['evidence_registry'])



def test_preparation_can_continue_while_current_model_action_can_receive_scoped_new_data_advice():
    payload,raw=build();new_data(raw);result=n.resolve(raw,payload)
    assert result['selected_next_actions']==list(n.SELECTED_NEXT_ACTIONS)
    assert result['groups'][0]['current_action_input_supported']
    assert result['groups'][0]['selected_analysis_status']=='INPUTS_NEED_ATTENTION'
    assert result['decisions'][0]['for_action']=='ESTIMATE_ANIMAL_PK_MODEL'
    assert not result['decisions'][0]['experiment_authorized']


def test_future_pta_cannot_request_experiments_now_even_if_its_raw_gap_is_real():
    payload,raw=build(family='PTA');new_data(raw)
    assert raw['decisions'][0]['for_action']=='SIMULATE_PER_MIC_PTA'
    with pytest.raises(PipelineError):n.resolve(raw,payload)
    raw['decisions'][0]['disposition']='EXISTING_SOURCE_REVIEW';raw['decisions'][0]['for_action']='NONE'
    assert n.resolve(raw,payload)['groups'][0]['selected_analysis_status']=='NOT_SELECTED_NEXT'


def test_new_data_must_name_the_actual_first_consuming_selected_action():
    payload,raw=build();new_data(raw)
    raw['decisions'][0]['for_action']='COMPARE_PD_INDICES'
    with pytest.raises(PipelineError):n.resolve(raw,payload)


def test_selected_actions_do_not_turn_nca_into_a_second_mandatory_path():
    plan,cov,catalog=fixture()
    second=copy.deepcopy(plan['requirements'][0]);second.update(id='RQ002',method_uses=['NCA'])
    plan['requirements'].append(second);cov['planning_sha256']=digest(plan)
    match=copy.deepcopy(cov['matches'][0]);match.update(requirement_id='RQ002',method_uses=['NCA'])
    match['criteria'][0]['status']='SUPPORTED';cov['matches'].append(match)
    payload=n.build_payload(plan,cov,catalog,project_rules=rules());result=n.resolve(answer(payload),payload)
    assert result['groups'][0]['selected_analysis_status']=='INPUTS_SUPPORTED'
    assert result['groups'][0]['preferred_analysis_input_family']=='NCA'
    assert result['groups'][0]['needs_attention']



def test_wire_fixed_criterion_map_cannot_omit_or_add_a_gap():
    payload,_=build();raw=wire_answer(payload);uid=next(iter(raw['units']))
    raw['units'][uid]['criterion_groups'].clear()
    with pytest.raises(PipelineError):n.materialize_wire(raw,payload)
    raw=wire_answer(payload);raw['units'][uid]['criterion_groups']['UNKNOWN']=0
    with pytest.raises(PipelineError):n.materialize_wire(raw,payload)


def test_wire_rejects_unknown_group_and_unused_group():
    payload,_=build();raw=wire_answer(payload);uid=next(iter(raw['units']))
    raw['units'][uid]['criterion_groups']['FIELD_001']=1
    with pytest.raises(PipelineError):n.materialize_wire(raw,payload)
    raw=wire_answer(payload);raw['units'][uid]['groups'].append(copy.deepcopy(raw['units'][uid]['groups'][0]))
    with pytest.raises(PipelineError):n.materialize_wire(raw,payload)


@pytest.mark.parametrize('field,value',[('first_dependency_action','ALIEN_ACTION'),('for_action','SIMULATE_PER_MIC_PTA'),('evidence_refs',['E99999'])])
def test_wire_scoped_action_and_evidence_enums_fail_before_host_judgement(field,value):
    payload,_=build();raw=wire_answer(payload);next(iter(raw['units'].values()))['groups'][0][field]=value
    with pytest.raises(PipelineError):n.materialize_wire(raw,payload)


def test_wire_keyed_impacts_cannot_duplicate_or_omit_actions():
    payload,_=build();raw=wire_answer(payload)
    impacts=next(iter(raw['units'].values()))['groups'][0]['impacts'];impacts.pop(n.CURRENT_ACTION)
    with pytest.raises(PipelineError):n.materialize_wire(raw,payload)


def multi_fixture():
    plan,cov,catalog=fixture()
    s2=copy.deepcopy(cov['scopes'][0]);s2['id']='S2';s2['item_ids']=['I2'];cov['scopes'].append(s2)
    m2=copy.deepcopy(cov['matches'][0]);m2['scope_id']='S2'
    for c in m2['criteria']:
        for name in ('evidence','counterevidence'):
            for e in c[name]:e['source']='I2:note'
        c['searched_item_ids']=['I2']
    cov['matches'].append(m2);catalog['I2:note']={**copy.deepcopy(catalog['I1:note']),'item_id':'I2'}
    return plan,cov,catalog


def test_scoped_wire_schema_excludes_other_panel_refs_even_in_same_part():
    plan,cov,catalog=multi_fixture();payload=n.build_payload(plan,cov,catalog,project_rules=rules())
    registry,_=n.evidence_registry(payload)
    foreign=next(k for k,v in registry.items() if v['source']=='I2:note')
    schema=n.wire_schema(payload);group=schema['$defs']['group_0']
    assert foreign not in group['properties']['evidence_refs']['items']['enum']


def setup_runtime(tmp_path,monkeypatch):
    plan,cov,catalog=multi_fixture();out=tmp_path/'necessity'
    pp=write_json(tmp_path/'inputs/plan.json',plan);cp=write_json(tmp_path/'inputs/coverage.json',cov)
    monkeypatch.setattr(n,'_verified_inputs',lambda *a:(copy.deepcopy(plan),copy.deepcopy(cov),copy.deepcopy(catalog),rules()))
    monkeypatch.setattr(n,'_review_module',lambda:SimpleNamespace(__file__=n.__file__))
    monkeypatch.setattr(n,'PART_CRITERIA_LIMIT',1)
    build=n.prepare(pp,cp,out);assert build['planned_provider_calls']==2
    calls=[]
    def generate(req,**kw):
        calls.append(req['request_sha256'])
        part=next(p for p in read_json(out/'build.json')['parts'] if read_json(p['request_ref']['path'])['request_sha256']==req['request_sha256'])
        payload=read_json(part['payload_ref']['path']);raw=wire_answer(payload)
        registry,lookup=n.evidence_registry(payload)
        if 'I1:note' not in payload['evidence_catalog']:
            # Same hypothetical meaning, with the admitted second panel's own source.
            for value in raw['units'].values():
                for d in value['groups']:d['evidence_refs']=[lookup['I2:note','Group means'],lookup['main:/rules/0/text','Only individual analysis needs individual IDs.']]
        raw['request_sha256']=req['request_sha256'];return raw
    generate.executor_id='offline-partition-generator'
    return out,calls,generate


def test_partition_keeps_whole_scope_and_rebases_exact_local_evidence():
    plan,cov,catalog=multi_fixture();payload=n.build_payload(plan,cov,catalog,project_rules=rules())
    parts=n.partition(payload)
    assert {u['unit_id'] for p in parts for u in p['payload']['units']}=={u['unit_id'] for u in payload['units']}
    for scope in cov['scopes']:
        assert sum(any(u['scope_id']==scope['id'] for u in p['payload']['units']) for p in parts)==1


def test_checkpoint_resume_does_not_recall_an_accepted_part(tmp_path,monkeypatch):
    out,calls,generate=setup_runtime(tmp_path,monkeypatch)
    first=n.run_prepared(out,generator=generate,max_new_calls=1)
    assert first['status']=='CHECKPOINTED' and len(calls)==1
    result=n.run_prepared(out,generator=generate,max_new_calls=1)
    assert len(calls)==2 and len(result['groups'])==2
    assert n.run_prepared(out,generator=generate)==result and len(calls)==2
    assert len(read_json(out/'provider_budget_ledger.json')['attempts'])==2


def test_exact_cache_rejects_another_executor(tmp_path,monkeypatch):
    out,calls,generate=setup_runtime(tmp_path,monkeypatch)
    n.run_prepared(out,generator=generate,max_new_calls=1)
    generate.executor_id='different-executor'
    with pytest.raises(PipelineError):n.run_prepared(out,generator=generate)
    assert len(calls)==1


def test_failure_is_retained_and_never_automatically_retried(tmp_path,monkeypatch):
    out,calls,generate=setup_runtime(tmp_path,monkeypatch)
    def invalid(req,**kw):calls.append('bad');return {'request_sha256':req['request_sha256'],'units':{}}
    invalid.executor_id=generate.executor_id
    with pytest.raises(PipelineError):n.run_prepared(out,generator=invalid)
    assert read_json(out/'provider_budget_ledger.json')['attempts'][0]['state']=='FAILED'
    with pytest.raises(PipelineError):n.run_prepared(out,generator=generate)
    assert calls==['bad']
    result=n.run_prepared(out,generator=generate,retry_failed=True)
    assert len(calls)==3 and result['version']==n.VERSION


def test_cumulative_provider_budget_blocks_resume_before_a_new_call(tmp_path,monkeypatch):
    monkeypatch.setattr(n,'MAX_PROVIDER_CALLS',2)
    out,calls,generate=setup_runtime(tmp_path,monkeypatch)
    def invalid(req,**kw):calls.append('bad');return {'request_sha256':req['request_sha256'],'units':{}}
    invalid.executor_id=generate.executor_id
    with pytest.raises(PipelineError):n.run_prepared(out,generator=invalid)
    n.run_prepared(out,generator=generate,retry_failed=True,max_new_calls=1)
    with pytest.raises(PipelineError):n.run_prepared(out,generator=generate)
    assert len(calls)==2


def test_provider_budget_ledger_cannot_be_reset_to_hide_prior_calls(tmp_path,monkeypatch):
    out,calls,generate=setup_runtime(tmp_path,monkeypatch)
    n.run_prepared(out,generator=generate,max_new_calls=1)
    write_json(out/'provider_budget_ledger.json',{'version':n.VERSION,'attempts':[]})
    with pytest.raises(PipelineError):n.run_prepared(out,generator=generate)
    assert len(calls)==1


def test_cache_raw_edit_is_rejected_before_a_resume_provider_call(tmp_path,monkeypatch):
    out,calls,generate=setup_runtime(tmp_path,monkeypatch)
    n.run_prepared(out,generator=generate,max_new_calls=1)
    cached=read_json(out/'parts/NEC01/accepted.json');raw=read_json(cached['raw_ref']['path']);raw['units']={}
    write_json(cached['raw_ref']['path'],raw)
    with pytest.raises((PipelineError,ValueError)):n.run_prepared(out,generator=generate)
    assert len(calls)==1


def test_single_scope_over_transport_budget_fails_without_truncation(monkeypatch):
    payload,_=build()
    monkeypatch.setattr(n.data,'REQUEST_BUDGET',10)
    with pytest.raises(PipelineError):n.partition(payload)


def test_cumulative_preflight_char_budget_fails_without_a_call(monkeypatch):
    payload,_=build()
    monkeypatch.setattr(n,'MAX_TOTAL_PROVIDER_CHARS',10)
    with pytest.raises(PipelineError):n.partition(payload)



def test_transport_hoists_repeated_search_and_definition_without_changing_host_facts():
    plan,cov,catalog=multi_fixture()
    for match in cov['matches']:
        c=match['criteria'][0];c['description']='Original field meaning'
        c['searched_item_ids']=['I1','I2']
        second=copy.deepcopy(c);second['id']='FIELD_002';second['status']='SUPPORTED';match['criteria'].append(second)
    payload=n.build_payload(plan,cov,catalog,project_rules=rules());before=copy.deepcopy(payload)
    wire=n.transport_payload(payload)
    assert len(wire['scope_definitions'])==2 and len(wire['search_profiles'])==1
    assert wire['criterion_definitions']['RQ001']['FIELD_001']=='Original field meaning'
    for unit in wire['units']:
        assert 'scope' not in unit and 'item_ids' not in unit
        assert 'FIELD_002' in unit['supported_criteria'] and 'FIELD_002' not in unit['gap_criteria']
        assert 'searched_item_ids' not in unit['gap_criteria']['FIELD_001']
    assert payload==before



def fake_clock(monkeypatch, start=100.0):
    clock={'mono':start,'wall':1000.0}
    monkeypatch.setattr(n,'_monotonic',lambda:clock['mono'])
    monkeypatch.setattr(n,'_wall_seconds',lambda:clock['wall'])
    def advance(seconds):clock['mono']+=seconds;clock['wall']+=seconds
    return clock,advance


def test_default_cumulative_provider_time_ceiling_is_25_minutes():
    assert n.MODEL_BUDGET_SECONDS==1500


def test_remaining_timeout_and_elapsed_persist_across_checkpoint_resume(tmp_path,monkeypatch):
    clock,advance=fake_clock(monkeypatch)
    out,calls,generate=setup_runtime(tmp_path,monkeypatch);timeouts=[]
    def timed(req,**kw):
        timeouts.append(kw['timeout']);advance(120 if len(timeouts)==1 else 80);return generate(req,**kw)
    timed.executor_id=generate.executor_id
    n.run_prepared(out,generator=timed,max_new_calls=1)
    ledger=read_json(out/'provider_budget_ledger.json')
    assert ledger['provider_elapsed_seconds']==120
    assert ledger['attempts'][0]['provider_elapsed_basis']=='MONOTONIC'
    result=n.run_prepared(out,generator=timed)
    assert timeouts==[1500,1380]
    assert read_json(out/'provider_budget_ledger.json')['provider_elapsed_seconds']==200
    assert n.run_prepared(out,generator=timed)==result and len(timeouts)==2


def test_failed_provider_attempt_consumes_time_and_retry_gets_only_remaining_seconds(tmp_path,monkeypatch):
    monkeypatch.setattr(n,'MODEL_BUDGET_SECONDS',10)
    clock,advance=fake_clock(monkeypatch);out,calls,generate=setup_runtime(tmp_path,monkeypatch)
    def broken(req,**kw):
        assert kw['timeout']==10;advance(7);raise RuntimeError('Provider failed')
    broken.executor_id=generate.executor_id
    with pytest.raises(RuntimeError):n.run_prepared(out,generator=broken)
    ledger=read_json(out/'provider_budget_ledger.json');assert ledger['provider_elapsed_seconds']==7
    def slow(req,**kw):
        assert kw['timeout']==3;advance(4);return generate(req,**kw)
    slow.executor_id=generate.executor_id
    with pytest.raises(PipelineError,match='exceeded'):n.run_prepared(out,generator=slow,retry_failed=True)
    assert (out/'attempts/002/raw.json').exists()
    assert read_json(out/'provider_budget_ledger.json')['provider_elapsed_seconds']==11
    with pytest.raises(PipelineError,match='time budget exhausted'):n.run_prepared(out,generator=generate,retry_failed=True)
    assert len(calls)==1


def test_interrupted_unfinalized_attempt_is_charged_before_resume(tmp_path,monkeypatch):
    monkeypatch.setattr(n,'MODEL_BUDGET_SECONDS',20)
    clock,advance=fake_clock(monkeypatch);out,calls,generate=setup_runtime(tmp_path,monkeypatch)
    original=n._clock_elapsed
    monkeypatch.setattr(n,'_clock_elapsed',lambda *a,**kw:None)  # Simulate process death before duration persistence.
    def interrupted(req,**kw):advance(5);raise KeyboardInterrupt()
    interrupted.executor_id=generate.executor_id
    with pytest.raises(KeyboardInterrupt):n.run_prepared(out,generator=interrupted)
    monkeypatch.setattr(n,'_clock_elapsed',original);advance(7)
    seen=[]
    def resumed(req,**kw):seen.append(kw['timeout']);return generate(req,**kw)
    resumed.executor_id=generate.executor_id
    n.run_prepared(out,generator=resumed,retry_failed=True,max_new_calls=1)
    ledger=read_json(out/'provider_budget_ledger.json')
    assert ledger['attempts'][0]['state']=='FAILED'
    assert ledger['attempts'][0]['provider_elapsed_basis']=='INTERRUPTED_CONSERVATIVE_MAX'
    assert ledger['provider_elapsed_seconds']==12 and seen==[8]


def test_interrupted_clock_reset_uses_conservative_wall_duration(tmp_path,monkeypatch):
    monkeypatch.setattr(n,'MODEL_BUDGET_SECONDS',10)
    clock,advance=fake_clock(monkeypatch);out,calls,generate=setup_runtime(tmp_path,monkeypatch)
    original=n._clock_elapsed;monkeypatch.setattr(n,'_clock_elapsed',lambda *a,**kw:None)
    def interrupted(req,**kw):raise KeyboardInterrupt()
    interrupted.executor_id=generate.executor_id
    with pytest.raises(KeyboardInterrupt):n.run_prepared(out,generator=interrupted)
    monkeypatch.setattr(n,'_clock_elapsed',original)
    clock.update(mono=1,wall=1012)
    with pytest.raises(PipelineError,match='time budget exhausted'):n.run_prepared(out,generator=generate,retry_failed=True)
    assert read_json(out/'provider_budget_ledger.json')['provider_elapsed_seconds']==12
    assert not calls


def test_interrupted_unreliable_clocks_charge_reserved_allowance_instead_of_zero(tmp_path,monkeypatch):
    monkeypatch.setattr(n,'MODEL_BUDGET_SECONDS',10)
    clock,advance=fake_clock(monkeypatch);out,calls,generate=setup_runtime(tmp_path,monkeypatch)
    original=n._clock_elapsed;monkeypatch.setattr(n,'_clock_elapsed',lambda *a,**kw:None)
    def interrupted(req,**kw):raise KeyboardInterrupt()
    interrupted.executor_id=generate.executor_id
    with pytest.raises(KeyboardInterrupt):n.run_prepared(out,generator=interrupted)
    monkeypatch.setattr(n,'_clock_elapsed',original);clock.update(mono=1,wall=900)
    with pytest.raises(PipelineError,match='time budget exhausted'):n.run_prepared(out,generator=generate,retry_failed=True)
    assert read_json(out/'provider_budget_ledger.json')['provider_elapsed_seconds']==10
    assert not calls


def test_duration_tampering_cannot_reset_time_allowance(tmp_path,monkeypatch):
    clock,advance=fake_clock(monkeypatch);out,calls,generate=setup_runtime(tmp_path,monkeypatch)
    def timed(req,**kw):advance(12);return generate(req,**kw)
    timed.executor_id=generate.executor_id
    n.run_prepared(out,generator=timed,max_new_calls=1)
    ledger=read_json(out/'provider_budget_ledger.json')
    ledger['provider_elapsed_seconds']=0;ledger['attempts'][0]['provider_elapsed_seconds']=0
    write_json(out/'provider_budget_ledger.json',ledger)
    with pytest.raises(PipelineError,match='persisted clock interval'):n.run_prepared(out,generator=generate)
    assert len(calls)==1
