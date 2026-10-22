import copy
import json
from types import SimpleNamespace
import pytest
from ctxcomp import providers,context_dispatch,governance
from ctxcomp.io import digest,canonical
from research_pipeline import context_gateway as gateway,context_budget as budget,context_routes as routes
from research_pipeline import data_direct_runtime as rt
from research_pipeline.common import read_json,write_json
from test_context_linear import request


def test_independent_run_scopes_do_not_serialize_model_calls(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    both_started=threading.Barrier(2)
    def transport(req,**kw):
        assert context_dispatch.prepared(req)
        both_started.wait(timeout=3)
        return {'request_sha256':req['request_sha256']}
    monkeypatch.setattr(providers,'_codex_generate_raw',transport)
    with ThreadPoolExecutor(max_workers=2) as pool:
        calls=[pool.submit(providers.codex_generate,request(),context_scope=tmp_path/name)
               for name in ('first','second')]
        assert all(call.result()['request_sha256']==request()['request_sha256'] for call in calls)


def test_other_thread_does_not_enter_an_unrelated_linear_session(tmp_path,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from research_pipeline.context_linear import LinearSession
    monkeypatch.setattr(providers,'_codex_generate_raw',lambda req,**kw:{'request_sha256':req['request_sha256']})
    with LinearSession(tmp_path/'parent').activate():
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(providers.codex_generate,request(),context_scope=tmp_path/'other').result()
        assert read_json(tmp_path/'parent/session.json')['calls']==[]
    assert len(list((tmp_path/'other/contextbuilder').glob('*/response.json')))==1


@pytest.mark.parametrize('stage',sorted(routes.COMPRESSION|routes.DATA))
def test_every_managed_stage_reaches_builder_without_session(stage,tmp_path,monkeypatch):
    p={'stage':stage,'instructions':'Perform this assigned operation only.'}
    if stage in routes.DIRECT or stage=='DR':
        # Direct contracts need their genuine required payload shape; tested in
        # the scoped integration suite. Here cover their route admission explicitly.
        assert routes.managed({'payload':p})
        return
    r=rt.make_request(p,{'type':'object'});calls=[]
    def transport(req,**kw):
        assert context_dispatch.prepared(req)
        calls.append(context_dispatch.model_input(req))
        return {'request_sha256':req['request_sha256']}
    monkeypatch.setattr(providers,'_codex_generate_raw',transport)
    providers.codex_generate(r,context_scope=tmp_path)
    assert len(calls)==1 and 'premise' in calls[0]['payload']
    slot=next(p for p in (tmp_path/'contextbuilder').iterdir() if p.is_dir())
    assert read_json(slot/'budget.json')['status']=='WITHIN_APPLICATION_BUDGET'
    assert read_json(slot/'request.json')==r


def test_default_provider_no_session_and_uuid_changes_cannot_repeat(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(providers,'_codex_generate_raw',lambda r,**kw:calls.append(r) or {})
    r=request()
    providers.codex_generate(r,diagnostics_dir=tmp_path/'attempts/uuid1/model_call')
    changed=request(assessment={'decision':'PASS'})
    with pytest.raises(ValueError,match='repeat'):
        providers.codex_generate(changed,diagnostics_dir=tmp_path/'attempts/uuid2/model_call')
    assert len(calls)==1


def test_historical_data_without_diagnostics_has_durable_receipt(tmp_path,monkeypatch):
    monkeypatch.setattr(gateway,'PROJECT',tmp_path)
    calls=[]
    monkeypatch.setattr(providers,'_codex_generate_raw',lambda r,**kw:calls.append(r) or {})
    providers.codex_generate(request())
    with pytest.raises(ValueError,match='repeat'):providers.codex_generate(request())
    assert len(calls)==1
    assert len(list((tmp_path/'outputs/contextbuilder_calls').glob('*/contextbuilder/*/response.json')))==1


def test_concurrent_process_reservation_cannot_be_overwritten(tmp_path,monkeypatch):
    root=tmp_path/'contextbuilder';root.mkdir();(root/'dispatch.lock').write_text('other process')
    monkeypatch.setattr(providers,'_codex_generate_raw',lambda *a,**k:pytest.fail('No call'))
    with pytest.raises(FileExistsError):providers.codex_generate(request(),context_scope=tmp_path)
    assert (root/'dispatch.lock').read_text()=='other process'


@pytest.mark.parametrize('stage',sorted(routes.REPAIRS))
def test_all_legacy_repairs_block_before_transport(stage,tmp_path,monkeypatch):
    monkeypatch.setattr(providers,'_codex_generate_raw',lambda *a,**k:pytest.fail('No call'))
    r=rt.make_request({'stage':stage,'instructions':'Repair previous output.'},{'type':'object'})
    with pytest.raises(ValueError,match='disabled'):
        providers.codex_generate(r,context_scope=tmp_path)


def test_requirements_revision_with_no_operation_is_also_blocked(tmp_path,monkeypatch):
    monkeypatch.setattr(providers,'_codex_generate_raw',lambda *a,**k:pytest.fail('No call'))
    r=rt.make_request({'stage':'requirements','instructions':'Revise.', 'revision_patch':{'must_change':['R1']}},{'type':'object'})
    with pytest.raises(ValueError,match='disabled'):providers.codex_generate(r,context_scope=tmp_path)


def test_final_prompt_and_cli_schema_both_count_towards_budget(tmp_path,monkeypatch):
    policy=read_json(budget.POLICY);policy['total_characters']=2000
    policy['reserved_output_characters']=0
    monkeypatch.setattr(budget,'POLICY',write_json(tmp_path/'budget.json',policy))
    monkeypatch.setattr(providers,'_codex_generate_raw',lambda *a,**k:pytest.fail('No model dispatch'))
    with pytest.raises(ValueError,match='Final model input'):
        providers.codex_generate(request(),context_scope=tmp_path/'run',cli_schema={'description':'x'*3000})
    slot=next(p for p in (tmp_path/'run/contextbuilder').iterdir() if p.is_dir())
    assert read_json(slot/'status.json')['provider_started'] is False
    assert read_json(slot/'budget.json')['status']=='REJECTED'


def test_utf8_limit_is_separate_from_character_count(tmp_path,monkeypatch):
    policy=read_json(budget.POLICY);policy.update(total_characters=100000,total_utf8_bytes=12,reserved_output_utf8_bytes=0,reserved_output_characters=0)
    monkeypatch.setattr(budget,'POLICY',write_json(tmp_path/'budget.json',policy))
    with pytest.raises(ValueError,match='budget'):budget.check('药'*10,{})


def test_raw_transport_cannot_bypass_builder():
    with pytest.raises(ValueError,match='bypass'):
        providers._codex_generate_raw(request())


def test_low_level_cli_cannot_bypass_builder(monkeypatch):
    monkeypatch.setattr(providers,'monitored_run',lambda *a,**k:pytest.fail('No process'))
    with pytest.raises(ValueError,match='requires a prepared'):
        providers.cli_call(request(),'codex',lambda root:['stub'],lambda *a:{},None,None,None,None)


def test_final_cli_stdin_equals_audited_prompt_without_linear_session(tmp_path,monkeypatch):
    captured=[]
    def process(command,prompt,*a,**kw):
        captured.append(prompt);return SimpleNamespace(returncode=0,stdout='',stderr='')
    monkeypatch.setattr(providers,'monitored_run',process)
    def transport(req,**kw):
        return providers.cli_call(req,'codex',lambda root:['offline'],lambda *a:{'request_sha256':req['request_sha256']},None,None,None,None)
    monkeypatch.setattr(providers,'_codex_generate_raw',transport)
    providers.codex_generate(request(),context_scope=tmp_path)
    slot=next(p for p in (tmp_path/'contextbuilder').iterdir() if p.is_dir())
    assert captured==[(slot/'model_prompt.txt').read_text(encoding='utf-8')]


def test_legacy_summary_has_strict_analyses_route(tmp_path, monkeypatch):
    calls=[]
    monkeypatch.setattr(providers,'_codex_generate_raw',lambda req,**kw:calls.append(context_dispatch.model_input(req)) or {})
    p={'stage':'HUMAN_REVIEW_SUMMARY_ONLY','instructions':'Summarize only the supplied assessment and analyses.',
       'assessment':{'decision':'HOLD'},'analyses':[{'id':'A1','importance':'CURRENT_BLOCKER'}]}
    request=rt.make_request(p,{'type':'object'})
    providers.codex_generate(request,context_scope=tmp_path/'legacy')
    assert calls[0]['payload']['analyses']==p['analyses']
    assert 'action_decisions' not in calls[0]['payload']
    assert 'analyses' in calls[0]['payload']['premise']
    with pytest.raises(ValueError,match='Unexpected sections'):
        providers.codex_generate(rt.make_request({**p,'raw_tables':['forbidden']},{'type':'object'}),context_scope=tmp_path/'bad')


def test_conflicting_legacy_language_stops_before_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(providers,'_codex_generate_raw',lambda *a,**kw:pytest.fail('No provider call'))
    p={'stage':'DP','instructions':'Use concise Chinese explanations with original\nscientific terms.'}
    with pytest.raises(ValueError,match='Chinese output instruction conflicts'):
        providers.codex_generate(rt.make_request(p,{'type':'object'}),context_scope=tmp_path)
    slot=next(p for p in (tmp_path/'contextbuilder').iterdir() if p.is_dir())
    assert read_json(slot/'status.json')['provider_started'] is False


def test_source_language_is_not_mistaken_for_output_instruction(tmp_path, monkeypatch):
    calls=[]
    monkeypatch.setattr(providers,'_codex_generate_raw',lambda req,**kw:calls.append(req) or {})
    p={'stage':'DP','instructions':'Extract the supplied source in English.',
       'source_units':{'S1':'Use concise Chinese explanations with original scientific terms.'}}
    providers.codex_generate(rt.make_request(p,{'type':'object'}),context_scope=tmp_path)
    assert len(calls)==1
