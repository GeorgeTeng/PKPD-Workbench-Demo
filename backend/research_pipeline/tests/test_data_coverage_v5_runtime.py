"""Incremental runtime tests use local fake calls, never a provider."""
import copy
import pytest
from types import SimpleNamespace
from pathlib import Path
from research_pipeline import data_coverage_v5 as v
from research_pipeline.common import write_json, read_json
from ctxcomp.schemas import obj, S
from ctxcomp.io import digest


def test_exhausted_import_is_not_new_budget():
    budget = {'elapsed_seconds':1500.407,'calls':4,'prior_calls':4}
    assert v.inherited_budget(budget) == (1500.407,8)
    assert not v.admission(budget,100)['allowed']


def test_prediction_reserves_output_time():
    budget={'elapsed_seconds':1370,'samples':[{'seconds':150,'checks':100}]}
    decision=v.admission(budget,100)
    assert not decision['allowed'] and decision['predicted_seconds'] >= 150


def test_initial_call_bound_is_small():
    assert v.admission({'elapsed_seconds':0},100)['allowed']
    assert not v.admission({'elapsed_seconds':1490},1)['allowed']


@pytest.mark.parametrize('reported,expected', [([], None), (['gpt-6-sol'], 'gpt-6-sol'),
    (['gpt-6-sol', 'gpt-6-luna'], None)])
def test_diagnostics_preserves_provider_served_models(tmp_path, reported, expected):
    write_json(tmp_path/'call.json', {'requested_model': 'gpt-6-sol', 'served_models': reported,
                                   'provider': 'codex', 'status': 'COMPLETED'})
    result = v._diagnostics(tmp_path)
    assert result['served_models'] == reported
    assert result['served_model'] == expected


def test_receipt_keeps_reported_model_identity(prepared):
    v.run_prepared(prepared, generator=good)
    receipt = read_json(prepared/'accepted/P1.json')
    raw_path = Path(receipt['refs']['raw']['path'])
    write_json(raw_path.parent/'model_call/call.json', {'requested_model': 'gpt-6-sol',
        'served_models': ['gpt-6-sol'], 'provider': 'codex', 'status': 'COMPLETED'})
    built = read_json(prepared/'build.json')
    attempt = read_json(prepared/'attempts'/(receipt['attempt_id']+'.json'))
    result = v._accept_raw(prepared, built, built['payloads'][0], attempt, raw_path)
    assert result['served_models'] == ['gpt-6-sol']
    assert result['served_model'] == 'gpt-6-sol'


def test_pause_is_explicit_boundary(tmp_path):
    v.request_pause(tmp_path)
    assert (tmp_path/'PAUSE').exists()


def test_inherited_budget_rejects_unknown_or_negative():
    for b in ({}, {'elapsed_seconds':-1,'calls':0,'prior_calls':0}):
        with pytest.raises(ValueError):v.inherited_budget(b)


@pytest.fixture
def prepared(tmp_path,monkeypatch):
    def build(plan,source_run,**kw):
        return {'planning_sha256':digest(plan),'bindings':{},'catalog':{},'scopes':[],
            'payloads':[{'part_id':pid,'units':[],'facts':{'F1':{}},'instructions':'Test fixture'} for pid in ('P1','P2')],
            'accepted_matches':list(kw.get('accepted_matches',()))}
    def materialize(raw,payload,catalog):
        if raw['value']=='BAD':raise ValueError('bad scoped evidence')
        return [{'unit_id':payload['part_id'],'criteria':[],'value':raw['value']}]
    def assemble(built,parts):
        pending=[p['part_id'] for p in built['payloads'] if p['part_id'] not in parts]
        return {'matches':[m for values in parts.values() for m in values],'complete':not pending,'pending':pending}
    f=SimpleNamespace(__file__=__file__,build=build,transport_payload=lambda x:x,
        response_schema=lambda p:obj(request_sha256=S,value=S),materialize=materialize,assemble_matches=assemble)
    monkeypatch.setattr(v,'facts',lambda:f)
    monkeypatch.setattr(v.planning,'verify_plan',lambda p:read_json(p))
    plan=write_json(tmp_path/'plan.json',{'version':'TEST'})
    out=tmp_path/'run';v.prepare(plan,tmp_path,out)
    return out


def good(request,**options):
    return {'request_sha256':request['request_sha256'],'value':'source bound'}


def test_explicit_batch_continues_exhausted_import_without_reset(prepared, monkeypatch):
    from research_pipeline.data_live_batch import Batch
    from research_pipeline.adequacy import file_ref
    root = prepared.parent
    history = write_json(root/'old_budget.json', {'elapsed_seconds': 1500.407, 'calls': 4, 'prior_calls': 4})
    source = write_json(root/'source_view.json', {})
    built = read_json(prepared/'build.json')
    built.update(prior_model_seconds=1500.407, prior_model_calls=8,
                 historical_import={'refs': {'budget': file_ref(history)}})
    built['bindings']['source_view'] = file_ref(source)
    write_json(prepared/'build.json', built)
    # Pure fixture bypasses the historical import parser, not either runtime budget.
    monkeypatch.setattr(v, '_load', lambda out: built)
    (prepared/'model_budget.json').unlink()
    auth = write_json(root/'auth.json', {'new_calls_model': 'gpt-6-sol',
        'new_batch_provider_seconds_limit': 1500, 'new_batch_wall_seconds_limit': 1800,
        'prior_history_is_not_reset': True, 'inputs': {'DR': built['bindings']['plan'],
        'source_view': file_ref(source), 'historical_coverage_budget': file_ref(history)}})
    Batch.create(auth, root/'batch')
    blocked = v.run_prepared(prepared, generator=lambda *a, **k: pytest.fail('default exhausted'))
    assert blocked['stop_reason'] == 'BUDGET_EXHAUSTED'
    with Batch.open(root/'batch') as batch:
        result = v.run_prepared(prepared, batch=batch, generator=good)
        assert result['model_budget']['elapsed_seconds'] >= 1500.407
        assert result['model_budget']['prior_calls'] == 8
        assert result['model_budget']['calls'] == 1
        assert result['stop_reason'] == 'CALL_LIMIT'
        assert batch.summary()['new_calls'] == 1
    with pytest.raises(ValueError, match='original explicit batch'):
        v.run_prepared(prepared, generator=good)
    assert read_json(history)['elapsed_seconds'] == 1500.407


def test_default_one_call_and_reuse(prepared):
    calls=[]
    def generator(request,**options):calls.append(request);return good(request,**options)
    first=v.run_prepared(prepared,generator=generator)
    assert not first['complete'] and len(calls)==1 and first['pending_parts']==['P2']
    final=v.run_prepared(prepared,generator=generator)
    assert final['complete'] and len(calls)==2
    assert v.verify_result(prepared/'coverage.json')==final
    v.run_prepared(prepared,generator=generator)
    assert len(calls)==2


def test_failure_is_accounted_and_explicit_retry_required(prepared):
    def bad(request,**options):return {'request_sha256':request['request_sha256'],'value':'BAD'}
    with pytest.raises(ValueError,match='scoped evidence'):v.run_prepared(prepared,generator=bad)
    before=read_json(prepared/'model_budget.json')
    assert before['calls']==1
    checkpoint=v.run_prepared(prepared,generator=lambda *a,**k:pytest.fail('blind retry'))
    assert checkpoint['model_budget']==before
    done=v.run_prepared(prepared,retry_failed=True,generator=good)
    assert done['model_budget']['calls']==2 and done['pending_parts']==['P2']


def test_boundary_pause_during_call_preserves_result(prepared):
    def pause(request,**options):v.request_pause(prepared);return good(request,**options)
    result=v.run_prepared(prepared,max_new_calls=2,generator=pause)
    assert len(result['matches'])==1 and result['pending_parts']==['P2']


def test_stale_checkpoint_recovers_without_call(prepared):
    v.run_prepared(prepared,generator=good)
    write_json(prepared/'checkpoint.json',{'complete':True,'matches':[]})
    result=v.rebuild_checkpoint(prepared)
    assert not result['complete'] and len(result['matches'])==1
    with pytest.raises(ValueError,match='Incomplete'):v.verify_result(prepared/'checkpoint.json')


def test_raw_tampering_rejected_no_fallback(prepared):
    v.run_prepared(prepared,generator=good)
    receipt=read_json(prepared/'accepted/P1.json')
    path=Path(receipt['refs']['raw']['path']);raw=read_json(path);raw['value']='changed';write_json(path,raw)
    with pytest.raises(ValueError):v.run_prepared(prepared,generator=lambda *a,**k:pytest.fail('fallback call'))


def test_crash_after_raw_before_receipt_recovers_zero_calls(prepared,monkeypatch):
    v.run_prepared(prepared,generator=good)
    (prepared/'accepted/P1.json').unlink()
    path=next((prepared/'attempts').glob('*.json'));a=read_json(path)
    a['status']='RUNNING';a['owner_pid']=987654321;write_json(path,a)
    monkeypatch.setattr(v,'_alive',lambda pid:False)
    result=v.run_prepared(prepared,max_new_calls=0,generator=lambda *a,**k:pytest.fail('provider'))
    assert len(result['matches'])==1
    assert read_json(path)['recovery']=='REPLAYED_RETAINED_RAW_ZERO_PROVIDER'


def test_unknown_crash_elapsed_consumes_reservation(prepared,monkeypatch):
    built=read_json(prepared/'build.json')
    write_json(prepared/'attempts/crashed.json',{'id':'crashed','part_id':'P1','build_sha256':digest(built),
        'status':'RUNNING','owner_pid':987654321,'provider_started':True,'timeout_seconds':1490,'checks':1})
    monkeypatch.setattr(v,'_alive',lambda pid:False)
    result=v.run_prepared(prepared,retry_failed=True,generator=lambda *a,**k:pytest.fail('budget reset'))
    assert result['model_budget']['elapsed_seconds']==1490 and not result['complete']


def test_verify_rejects_modified_result_without_rewriting_it(prepared):
    v.run_prepared(prepared,max_new_calls=2,generator=good)
    path=prepared/'coverage.json';value=read_json(path);value['matches'][0]['value']='changed';write_json(path,value)
    original=path.read_bytes()
    with pytest.raises(ValueError):v.verify_result(path)
    assert path.read_bytes()==original


def test_read_only_verify_and_status_do_not_write(prepared,monkeypatch):
    v.run_prepared(prepared,max_new_calls=2,generator=good)
    monkeypatch.setattr(v,'write_json',lambda *a,**kw:pytest.fail('read-only API wrote a file'))
    assert v.verify_result(prepared/'coverage.json')['complete']
    assert v.rebuild_checkpoint(prepared,write=False)['complete']


def test_attempt_removal_cannot_reset_budget(prepared):
    v.run_prepared(prepared,generator=good)
    path=next((prepared/'attempts').glob('*.json'));path.unlink()
    with pytest.raises((ValueError,FileNotFoundError)):
        v.run_prepared(prepared,generator=lambda *a,**k:pytest.fail('reset budget'))


def test_status_explains_call_limit_and_pause(prepared):
    assert v.run_prepared(prepared,generator=good)['stop_reason']=='CALL_LIMIT'
    v.request_pause(prepared)
    assert v.rebuild_checkpoint(prepared,write=False)['stop_reason']=='PAUSED'


def test_tampered_schema_refuses_before_model(prepared):
    path=prepared/'requests/P1.json';r=read_json(path);r['payload']['instructions']='changed';write_json(path,r)
    with pytest.raises(ValueError):v.run_prepared(prepared,generator=lambda *a,**k:pytest.fail('tampered'))


def test_target_search_inherits_exact_final_ledger(prepared,monkeypatch,tmp_path):
    v.run_prepared(prepared,max_new_calls=2,generator=good)
    parent=read_json(prepared/'model_budget.json')
    f=v.facts()
    def search(build,matches,targets):
        result=copy.deepcopy(build);result['payloads']=[{**result['payloads'][0],'part_id':'LOOKUP1'}]
        result['search_targets']=targets
        return result
    f.build_search=search
    f.lookup_targets=lambda built,matches:{'P1':['NOTE']}
    target=tmp_path/'search'
    built=v.prepare_search(prepared/'coverage.json',target)
    assert built['prior_model_seconds']==parent['elapsed_seconds']
    assert built['prior_model_calls']==parent['calls']+parent['prior_calls']
    assert built['bindings']['parent_budget']==v.file_ref(prepared/'model_budget.json')
    assert v.rebuild_checkpoint(target,write=False)['model_budget']['elapsed_seconds']==parent['elapsed_seconds']


def test_no_lookup_match_does_not_fabricate_missing(prepared,monkeypatch,tmp_path):
    v.run_prepared(prepared,max_new_calls=2,generator=good)
    v.facts().lookup_targets=lambda built,matches:{}
    target=tmp_path/'emptysearch'
    result=v.prepare_search(prepared/'coverage.json',target)
    assert result['status']=='NO_PERMITTED_LOOKUP_TARGETS' and result['model_calls']==0
    assert not target.exists()


def test_late_provider_response_is_archived_but_not_accepted(prepared,monkeypatch):
    ticks=iter([0.0,1501.0])
    monkeypatch.setattr(v.time,'monotonic',lambda:next(ticks))
    with pytest.raises(ValueError,match='beyond the reserved timeout'):
        v.run_prepared(prepared,generator=good)
    assert list((prepared/'calls').glob('*/data_agents/audit/DC-review/*/response.json'))
    assert not (prepared/'accepted/P1.json').exists()
    assert read_json(prepared/'model_budget.json')['elapsed_seconds']==1501
    assert read_json(prepared/'checkpoint.json')['stop_reason']=='BUDGET_EXHAUSTED'


def test_bool_is_not_a_call_limit(prepared):
    with pytest.raises(ValueError,match='call limit'):v.run_prepared(prepared,max_new_calls=True,generator=good)
