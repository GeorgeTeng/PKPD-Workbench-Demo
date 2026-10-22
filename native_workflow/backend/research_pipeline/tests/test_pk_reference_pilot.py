"""Synthetic contract tests; no fixture output is a scientific result."""
import copy
from pathlib import Path
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from research_pipeline import pk_reference_pilot as p
from research_pipeline import adequacy as a
from research_pipeline.common import read_json, write_json
from research_pipeline.workflow_runtime import make_plan, execute_contract
from research_pipeline.workbench import create_workbench
from research_pipeline.pk_reference_api import reference_router
from test_adequacy import inputs, assessment, review


def pilot_response(req, **kwargs):
    data=req['payload']; span=[{'path':'/objective','quote':data['main']['objective']}]
    return {'request_sha256':req['request_sha256'],'scope':'IN_SCOPE','scope_reason':'Synthetic scope test',
        'scope_evidence':span,'card_checks':[{'card_id':c['id'],'applicability':'NEEDS_CLARIFICATION',
            'coverage':'NOT_STATED','reason':'Synthetic unresolved information','proposed_action':'Clarify at the assigned step.',
            'missing_information':'Design details','relevant_step':c.get('allowed_steps',['human_pk'])[0],'context_evidence':span,
            'source_evidence':[{'source_id':s['id'],'quote':s['quote']} for s in data['sources'] if s['id'] in c['source_ids']]}
            for c in data['cards']], 'limitations':['Synthetic fixture, not scientific evidence.']}


def prepared(inputs):
    run,path,ip,main,inventory=inputs
    lr=p.snapshot_library(run/'library.json')
    package=p.prepare(a.file_ref(path),lr,run/'reference_input.json')
    return run,package


def test_context_is_scoped_and_main_unmodified(inputs):
    run,package=prepared(inputs); before=inputs[1].read_bytes()
    req=p.model_request(package)
    assert 'SENTINEL_BODY' not in str(req) and 'NEVER_SEND_BENCHMARK' not in str(req)
    assert 'renamable.csv' not in str(req) and 'Freeze MIC' in str(req)
    assert 'files' not in req['payload']['main']['data']
    p.execute(run/'reference_input.json',run/'review',generator=pilot_response)
    advice=p.downstream_context(run/'review/reference_context.json',inputs[3])
    assert inputs[1].read_bytes()==before and not advice['rule_activation']
    assert all(c['origin']=='EXTERNAL_PROPOSED' for c in advice['suggestions'])
    assert read_json(run/'review/reference_report.json')['review_origin']=='TEST_GENERATOR'


def test_index_routing_is_supported_and_wrong_branch_is_rejected(inputs):
    from research_pipeline.clinical_dispatch import project_reference_advice
    run,package=prepared(inputs); req=p.model_request(package)
    response=pilot_response(req)
    expected=[c['id'] for c in package['cards'] if c.get('allowed_steps')==['index']]
    assert expected
    p.execute(run/'reference_input.json',run/'review',generator=pilot_response)
    advice=p.downstream_context(run/'review/reference_context.json',inputs[3])
    assert {c['card_id'] for c in project_reference_advice(advice,'index')['suggestions']}==set(expected)
    assert not set(expected)&{c['card_id'] for c in project_reference_advice(advice,'pk')['suggestions']}
    next(c for c in response['card_checks'] if c['card_id']==expected[0])['relevant_step']='pk'
    with pytest.raises(ValueError,match='routing metadata'):
        p.validate_response(response,req,package)


@pytest.mark.parametrize('mutation',['quote','summary_as_quote','missing_card','drop_counter_evidence','extra_rule','stale_hash'])
def test_rejected_output_never_releases_handoff(inputs,mutation):
    run,_=prepared(inputs)
    def bad(req,**kw):
        r=pilot_response(req)
        if mutation=='quote':r['card_checks'][0]['context_evidence'][0]['quote']='invented dose'
        if mutation=='summary_as_quote':r['card_checks'][0]['source_evidence'][0]['quote']=req['payload']['sources'][1]['summary']
        if mutation=='missing_card':r['card_checks'].pop()
        if mutation=='drop_counter_evidence':r['card_checks'][2]['source_evidence'].pop()
        if mutation=='extra_rule':r['rules']=['Use the source drug parameters']
        if mutation=='stale_hash':r['request_sha256']='old'
        return r
    with pytest.raises(ValueError):p.execute(run/'reference_input.json',run/'review',generator=bad)
    assert not (run/'review/reference_context.json').exists()
    assert (run/'review/audit/response.json').exists()
    assert (run/'review/stopped.json').exists()


def test_out_of_scope_and_changed_proposals(inputs):
    run,package=prepared(inputs); req=p.model_request(package); response=pilot_response(req)
    response['scope']='OUT_OF_SCOPE'
    with pytest.raises(ValueError,match='Out-of-scope'):p.validate_response(response,req,package)
    for c in response['card_checks']:c.update(applicability='NOT_APPLICABLE',coverage='NOT_APPLICABLE')
    p.execute(run/'reference_input.json',run/'review',generator=lambda *a,**k:response)
    assert not p.downstream_context(run/'review/reference_context.json',inputs[3])['suggestions']
    altered=copy.deepcopy(package);altered['context']['objective']='Only describe rat observations; do not predict humans.'
    assert p.model_request(altered)['request_sha256']!=req['request_sha256']


def test_advice_tamper_and_changed_library_are_rejected(inputs):
    run,package=prepared(inputs);p.execute(run/'reference_input.json',run/'review',generator=pilot_response)
    path=run/'review/reference_context.json';v=read_json(path);v['suggestions'][0]['proposed_action']='Mandatory new rule'
    write_json(path,v)
    with pytest.raises(ValueError,match='differs'):p.downstream_context(path,inputs[3])
    Path(package['library']['path']).write_text('{}')
    with pytest.raises(ValueError):p.execute(run/'reference_input.json',run/'other',generator=pilot_response)


def test_full_file_chain_into_existing_adequacy(inputs,monkeypatch):
    run,path,ip,main,inventory=inputs
    app=create_workbench(run.parent,run.parent/'state');store=app.state.canvas
    s=store.create();sid=s['session_id'];session=store.load(sid)
    record=write_json(run.parent/'manifest.json',{'fixture':True})
    store.record_completion(session,'intake',[{'name':'manifest.json',**a.file_ref(record)}])
    store.record_completion(session,'context',[{'name':'main.json',**a.file_ref(path)}]);write_json(store.path(sid),session)
    client=TestClient(app)
    assert client.post(f'/ui-api/workflow/sessions/{sid}/nodes/context/review',json={
        'decision':'APPROVE','reviewer':'Synthetic test','output_signature':session['nodes']['context']['output_signature'],'confirmed':True,'objective_decision':'CONFIRMED'}).status_code==200
    approval=write_json(run.parent/'approval.json',{'context':store.load(sid)['nodes']['context']})
    plan=make_plan({'id':'pilot_fixture','mode':'reviewed_context','approved_context':a.file_ref(approval),
        'pk_reference_pilot':True,'out':str(run),'job_dir':str(run.parent/'job')})
    monkeypatch.setattr(p,'codex_generate',pilot_response)
    seen=[]
    def downstream(req,**kw):
        seen.append(req)
        return assessment(req) if req['payload']['stage']=='adequacy_assessment' else review(req)
    monkeypatch.setattr(a,'codex_generate',downstream)
    for name in ['reviewed_context','adequacy_inventory','pk_reference_prepare','pk_reference_review','adequacy_assessment','adequacy_review']:
        execute_contract(plan['steps'][name]['contract'])
    assert len(seen)==2 and all('external_reference_advice' in r['payload'] for r in seen)
    assert read_json(run/'adequacy/adequacy.json')['can_enter_qc']
    assert not read_json(run/'adequacy/adequacy.json')['scientific_release']
    assert read_json(run/'B1/main.json')==main
    assert 'objective' not in read_json(run/'adequacy/qc_context.json')


def test_api_configuration_and_download_authorization(inputs):
    run,path,*_=inputs; app=create_workbench(run.parent,run.parent/'state'); store=app.state.canvas
    sid=store.create()['session_id'];client=TestClient(app);base=f'/ui-api/workflow/sessions/{sid}/pk-reference-pilot'
    assert client.get(base).status_code==200
    before=copy.deepcopy(store.load(sid)['nodes'])
    assert client.post(base+'/configuration',json={'enabled':True}).status_code==200
    assert store.load(sid)['nodes']==before
    assert client.post(base+'/start').status_code==409
    assert client.get(base+'/jobs/fake/files/library.json').status_code==404


def test_pending_context_preview_preserves_human_gate(inputs):
    run,path,*_=inputs; app=create_workbench(run.parent,run.parent/'state'); store=app.state.canvas
    sid=store.create()['session_id']; session=store.load(sid)
    store.record_completion(session,'context',[{'name':'main.json',**a.file_ref(path)}])
    write_json(store.path(sid),session)
    launched=[]
    def launch(spec,stop):
        launched.append(spec)
        return {'id':'preview_fixture','status':'QUEUED'}
    api=FastAPI();api.include_router(reference_router(store,launch,lambda _: {'status':'QUEUED'},lambda _:None))
    client=TestClient(api);base=f'/workflow/sessions/{sid}/pk-reference-pilot'
    assert client.post(base+'/start',json={'revise_main':True}).status_code==409
    assert client.get(base).json()['can_preview']
    before=copy.deepcopy(store.load(sid)['nodes'])
    assert client.post(base+'/start',json={'revise_main':True,'allow_unreviewed_context':True}).status_code==202
    assert launched[0]['preview_only'] and launched[0]['input_review_status']=='PENDING_HUMAN_REVIEW'
    assert store.load(sid)['nodes']==before
    assert not store.dependency_ready(store.load(sid),'context')
    path.write_text('{}')
    assert client.post(base+'/start',json={'allow_unreviewed_context':True}).status_code==409


def test_preview_cannot_use_failed_or_missing_context(inputs):
    run,path,*_=inputs;app=create_workbench(run.parent,run.parent/'state');store=app.state.canvas
    sid=store.create()['session_id'];client=TestClient(app)
    base=f'/ui-api/workflow/sessions/{sid}/pk-reference-pilot'
    assert client.post(base+'/start',json={'allow_unreviewed_context':True}).status_code==409
    session=store.load(sid);session['nodes']['context'].update(execution='FAILED',artifacts=[{'name':'main.json',**a.file_ref(path)}])
    write_json(store.path(sid),session)
    assert client.post(base+'/start',json={'allow_unreviewed_context':True}).status_code==409
