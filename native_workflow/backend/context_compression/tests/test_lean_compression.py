"""Authored structural and fault tests for the opt-in lean path; no actual model calls."""
import copy
import json
from pathlib import Path
import pytest
from ctxcomp import lean_compression as lean
from ctxcomp.engine import init_run,prepare,accept,load_run,verify_context,stage_status,active_stages
from ctxcomp.io import leaves,read_json,write_json,digest
from ctxcomp.providers import run_model
from test_output_profile import FACT


def setup(tmp_path,attachments=False):
    proposal=tmp_path/'proposal.txt';proposal.write_text(FACT,encoding='utf-8')
    clarification=tmp_path/'clarification.txt';clarification.write_text('Explicit clarification: only intravenous administration.',encoding='utf-8')
    options={}
    if attachments:
        raw=tmp_path/'dataset.csv';raw.write_text('secret\nATTACHMENT_BODY_MUST_NOT_REACH_MODEL\n',encoding='utf-8')
        options={'attachments':[raw]}
    run=tmp_path/'run';init_run(run,proposal,clarifications=[clarification],compression_profile=lean.ID,**options)
    return run


def candidate(request):
    units=request['payload']['source_units'];u=units[0]
    cite={'source_id':u['source_id'],'unit_id':u['id'],'quote':FACT}
    core={'version':'3.0','objective':'Compound Z research',
          'study':{k:'NOT_FOUND' for k in ['drug','regimen','population','system','measurements','methods']},
          'data':{'available':[],'required':[]},'rules':[],'checks':[],'uncertainties':[]}
    scientific={'version':'2.0','items':[{'id':'F001','statement':FACT,'science':{
        'role':'OTHER','evidence_status':'SOURCE_REPORTED','method_refs':[],'adoption_relations':[],'relations':[]}}],
        'potential_questions':[]}
    evidence=[{'id':p,'status':'NOT_FOUND' if v=='NOT_FOUND' else 'EXPLICIT','citations':[] if v=='NOT_FOUND' else [cite],
               'reason':'Authored synthetic evidence'} for p,v in leaves(core) if p!='/version']
    evidence.append({'id':'F001','status':'EXPLICIT','citations':[cite],'reason':'Source-grounded synthetic item'})
    return {'request_sha256':request['request_sha256'],'context':core,'scientific_context':scientific,
            'missing_information':{'schema_version':'1.0','items':[]},'evidence':evidence}


def review(request,decision='PASS'):
    p=request['payload']
    return {'request_sha256':request['request_sha256'],'candidate_sha256':p['candidate_sha256'],
        'review':{'decision':decision,'reviewer':'Synthetic independent call',
            'records':[{'id':i,'faithfulness':'PRESERVED','completeness':'PRESERVED','reason':'Fixture'} for i in p['expected_record_ids']],
            'source_units':[{'unit_id':u['id'],'verdict':'PRESERVED','record_ids':['F001'],'reason':'Fixture unit coverage'} for u in p['source_units']],
            'checks':[{'id':i,'verdict':'PRESERVED','reason':'Fixture'} for i in p['required_check_ids']],
            'critical_errors':[],'fixes':[] if decision=='PASS' else [{'id':'FIX1','target':'/objective','reason':'Make overview exact', 'citations':[]}],
            'limitations':['Synthetic contract verdicts; no semantic accuracy claim.']}}


def test_two_real_stages_only_and_no_attachment_bodies(tmp_path):
    run=setup(tmp_path,attachments=True);calls=[]
    def model(req,**kwargs):
        calls.append(req)
        assert 'ATTACHMENT_BODY_MUST_NOT_REACH_MODEL' not in json.dumps(req)
        assert any('Explicit clarification' in u['text'] for u in req['payload']['source_units'])
        return candidate(req) if req['payload']['stage']=='context' else review(req)
    assert run_model(run,generator=model)['status']=='CONTEXT_READY'
    assert [r['payload']['stage'] for r in calls]==['context','context_review']
    bundle,state=load_run(run)
    assert active_stages(bundle)==('context','context_review')
    assert set(state['accepted'])=={'context','context_review'}
    assert [s['stage'] for s in stage_status(run)]==['context','context_review']
    assert not (run/'critical_requirements.json').exists()
    assert verify_context(run)['status']=='VALID'
    main=read_json(run/'handoff/main.json')
    assert main['version']=='3.2' and len(main['data']['files'])==3
    assert main['data']['available']==main['data']['required']==[]
    assert main['scientific_context']['items'][0]['statement']==FACT
    assert all(k not in main for k in ['evidence','source_units','requirements'])
    registry=read_json(run/'audit/file_registry.json')
    assert next(f for f in registry['files'] if f['original_name']=='clarification.txt')['compression_input']
    assert not next(f for f in registry['files'] if f['original_name']=='dataset.csv')['compression_input']


@pytest.mark.parametrize('fault',['missing_unit','missing_record','false_pass','changed_hash','wrong_quote','bad_relation'])
def test_faults_never_publish(tmp_path,fault):
    run=setup(tmp_path)
    def model(req,**kwargs):
        if req['payload']['stage']=='context':
            result=candidate(req)
            if fault=='wrong_quote': result['evidence'][-1]['citations'][0]['quote']='Fabricated'
            if fault=='bad_relation': result['scientific_context']['items'][0]['science']['method_refs']=['UNKNOWN']
            return result
        result=review(req)
        if fault=='missing_unit':result['review']['source_units'].pop()
        if fault=='missing_record':result['review']['records'].pop()
        if fault=='false_pass':result['review']['records'][0]['completeness']='MISSING'
        if fault=='changed_hash':result['candidate_sha256']='bad'
        return result
    with pytest.raises(ValueError):run_model(run,generator=model)
    assert not (run/'handoff/main.json').exists()


def patch(req,no_change=False):
    p=req['payload'];old=p['candidate']
    evidence=copy.deepcopy(next(e for e in old['evidence'] if e['id']=='/objective'))
    response={'request_sha256':req['request_sha256'],'base_candidate_sha256':p['base_candidate_sha256'],
              'overview':[{'path':'/objective','value':old['context']['objective'] if no_change else 'Study Compound Z','fix_ids':['FIX1']}],
              'uncertainty_refs':old['context']['uncertainties'],'evidence':[evidence]}
    for operation in ['replace','add','remove']:
        for group in ['items','gaps','questions']:response[operation+'_'+group]=[]
    return response


def test_one_targeted_patch_keeps_unmodified_records_and_rechecks_full_sources(tmp_path):
    run=setup(tmp_path);calls=[]
    def model(req,**kwargs):
        p=req['payload'];calls.append(p)
        if p.get('operation')=='TARGETED_PATCH':return patch(req)
        if p['stage']=='context':return candidate(req)
        return review(req,'REVISE' if sum(c['stage']=='context_review' for c in calls)==1 else 'PASS')
    assert run_model(run,generator=model)['status']=='CONTEXT_READY'
    assert len(calls)==4
    proof=read_json(run/'lean/patch_proof.json')
    before=lean.content(read_json(run/proof['original_context']['file']))
    after=lean.content(read_json(run/load_run(run)[1]['accepted']['context']['file']))
    assert before['scientific_context']==after['scientific_context']
    assert before['missing_information']==after['missing_information']
    assert before['context']['objective']!=after['context']['objective']
    assert verify_context(run)['status']=='VALID'
    proof['patch']['overview'][0]['value']='Tampered after review'
    write_json(run/'lean/patch_proof.json',proof)
    with pytest.raises(ValueError,match='recorded targeted changes'):verify_context(run)


def test_no_change_patch_stops_without_repeated_sampling(tmp_path):
    run=setup(tmp_path);calls=[]
    def model(req,**kwargs):
        p=req['payload'];calls.append(p)
        if p.get('operation')=='TARGETED_PATCH':return patch(req,no_change=True)
        return candidate(req) if p['stage']=='context' else review(req,'REVISE')
    with pytest.raises(ValueError,match='No-change'):run_model(run,generator=model)
    assert len(calls)==3
    assert run_model(run,generator=model)['status']=='REVISE'
    assert len(calls)==3 and not (run/'handoff/main.json').exists()


def test_second_revise_stops_and_needs_review_never_patches(tmp_path):
    run=setup(tmp_path);calls=[]
    def model(req,**kwargs):
        p=req['payload'];calls.append(p)
        if p.get('operation')=='TARGETED_PATCH':return patch(req)
        return candidate(req) if p['stage']=='context' else review(req,'REVISE')
    assert run_model(run,generator=model)['status']=='REVISE'
    assert len(calls)==4
    assert run_model(run,generator=model)['status']=='REVISE' and len(calls)==4
    assert not (run/'handoff/main.json').exists()


def test_published_main_hash_tampering_invalidates_review(tmp_path):
    run=setup(tmp_path)
    run_model(run,generator=lambda req,**kw:candidate(req) if req['payload']['stage']=='context' else review(req))
    main=read_json(run/'handoff/main.json');main['objective']='Changed';write_json(run/'handoff/main.json',main)
    with pytest.raises(ValueError,match='publication changed'):verify_context(run)


def test_profileless_stage_sequence_unchanged(tmp_path):
    source=tmp_path/'proposal.txt';source.write_text(FACT,encoding='utf-8')
    init_run(tmp_path/'old',source)
    bundle,_=load_run(tmp_path/'old')
    assert not lean.enabled(bundle)
    assert active_stages(bundle)[:2]==('attachment_plan','attachment_evidence')


def test_needs_review_does_not_patch_or_resample(tmp_path):
    run=setup(tmp_path);calls=[]
    def model(req,**kw):
        calls.append(req)
        return candidate(req) if req['payload']['stage']=='context' else review(req,'NEEDS_REVIEW')
    assert run_model(run,generator=model)['status']=='NEEDS_REVIEW'
    assert run_model(run,generator=model)['status']=='NEEDS_REVIEW'
    assert len(calls)==2 and not (run/'lean/patch_attempt.json').exists()


def test_real_adapter_receives_remaining_budget_and_failure_audit(tmp_path,monkeypatch):
    from ctxcomp import providers
    run=setup(tmp_path);calls=[]
    def real(req,**kwargs):
        calls.append(kwargs)
        if req['payload']['stage']=='context':return candidate(req)
        raise providers.ModelProviderError('MODEL_TIMEOUT','Synthetic timeout')
    monkeypatch.setattr(providers,'codex_generate',real)
    with pytest.raises(providers.ModelProviderError):providers.run_model(run,generator=real,model='gpt-6-sol')
    assert len(calls)==2 and 0<calls[1]['timeout']<=calls[0]['timeout']<=1500
    assert all(c['model']=='gpt-6-sol' and 'audit/model_calls' in str(c['diagnostics_dir']).replace('\\','/') for c in calls)
    stopped=read_json(run/'stopped.json')
    assert stopped['error_code']=='MODEL_TIMEOUT' and stopped['model_call'].endswith('context_review/call.json')
    assert not (run/'handoff/main.json').exists()
