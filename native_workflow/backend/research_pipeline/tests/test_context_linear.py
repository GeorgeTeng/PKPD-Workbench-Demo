import copy
import pytest
from ctxcomp import providers, model_view
from ctxcomp.io import canonical, digest
from research_pipeline import context_linear as linear, context_builder as cb, data_direct_runtime as rt
from research_pipeline import context_model_view as cmv
from research_pipeline.common import PipelineError, read_json, write_json


def request(stage='HUMAN_REVIEW_SUMMARY_ONLY', **extra):
    payload = {'stage':stage,'instructions':'Summarize accepted opinions only.',
               'assessment':{'decision':'CONDITIONAL_PASS'},'action_decisions':{}}
    payload.update(extra)
    return rt.make_request(payload, {'type':'object'})


def coverage(ids):
    return rt.make_request({'stage':'DIRECT_DR_COVERAGE','instructions':'Check these requirements only.',
        'objective':'Animal PK','requirements':[{'id':i} for i in ids],
        'rules':[],'profiles':[],'source_units':{}}, {'type':'object'})


def test_preview_is_exact_transport_prompt_without_call(tmp_path, monkeypatch):
    monkeypatch.setattr(providers, '_codex_generate_raw', lambda *a, **k: pytest.fail('No live calls'))
    req = request()
    out = tmp_path/'preview'
    linear.export_preview(req,out)
    assert read_json(out/'request.json') == req
    assert (out/'model_prompt.txt').read_text(encoding='utf-8') == providers.PROMPT+canonical(cmv.view(req))
    assert read_json(out/'execution_policy.json')['model_calls'] == 0


def test_actual_provider_hook_uses_builder_and_retains_raw(tmp_path, monkeypatch):
    calls=[]
    def transport(req, **kwargs):
        calls.append(copy.deepcopy(req))
        return {'request_sha256':req['request_sha256'],'raw':'not scientific approval'}
    monkeypatch.setattr(providers, '_codex_generate_raw', transport)
    req=request()
    with linear.LinearSession(tmp_path/'session').activate():
        raw=providers.codex_generate(req, model='gpt-6-sol')
    assert calls == [req]
    folder=tmp_path/'session/001_data_human_summary'
    assert read_json(folder/'response.json') == raw
    assert read_json(folder/'context_manifest.json')['route']=='data.human_summary'
    assert read_json(tmp_path/'session/session.json')['calls'][0]['status']=='RETURNED_PENDING_STAGE_VALIDATION'


def test_duplicate_even_changed_payload_is_not_another_call(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(providers,'_codex_generate_raw',lambda r,**kw: calls.append(r) or {})
    with pytest.raises(PipelineError,match='already dispatched'):
        with linear.LinearSession(tmp_path).activate():
            providers.codex_generate(request())
            providers.codex_generate(request(assessment={'decision':'PASS'}))
    assert len(calls)==1
    assert read_json(tmp_path/'session.json')['status']=='FAILED'


def test_transport_failure_is_preserved_no_resume(tmp_path,monkeypatch):
    calls=[]
    def broken(*a,**k):
        calls.append(1)
        raise RuntimeError('transport disconnected')
    monkeypatch.setattr(providers,'_codex_generate_raw',broken)
    with pytest.raises(RuntimeError,match='disconnected'):
        with linear.LinearSession(tmp_path).activate():
            providers.codex_generate(request())
    with pytest.raises(PipelineError,match='no automatic resume'):
        with linear.LinearSession(tmp_path).activate():
            providers.codex_generate(request())
    assert calls==[1]


def test_source_change_during_call_stops_session(tmp_path,monkeypatch):
    source=write_json(tmp_path/'source.json',{'value':1})
    def changed(*a,**k):
        write_json(source,{'value':2})
        return {'answer':'retained'}
    monkeypatch.setattr(providers,'_codex_generate_raw',changed)
    with pytest.raises(PipelineError,match='Changed input'):
        with linear.LinearSession(tmp_path/'session',{'source':cb.file_ref(source)}).activate():
            providers.codex_generate(request())
    assert read_json(tmp_path/'session/001_data_human_summary/response.json')['answer']=='retained'


@pytest.mark.parametrize('change_before_transport', [False, True])
def test_projection_dependency_change_rejects_dispatch_or_response(tmp_path, monkeypatch, change_before_transport):
    dependency = write_json(tmp_path/'projection_dependency.json', {'version':1})
    project = cmv.project
    calls = []
    def bound_projection(req):
        visible, audit = project(req)
        audit['bindings']['test_dependency'] = cb.file_ref(dependency)
        if change_before_transport:
            write_json(dependency, {'version':2})
        return visible, audit
    def transport(req, **kwargs):
        calls.append(req)
        write_json(dependency, {'version':2})
        return {'answer':'retained, not accepted'}
    monkeypatch.setattr(cmv, 'project', bound_projection)
    monkeypatch.setattr(providers, '_codex_generate_raw', transport)
    with pytest.raises(PipelineError, match='Changed input'):
        with linear.LinearSession(tmp_path/'session').activate():
            providers.codex_generate(request())
    assert len(calls) == (0 if change_before_transport else 1)
    assert read_json(tmp_path/'session/session.json')['status'] == 'FAILED'
    if calls:
        assert read_json(tmp_path/'session/001_data_human_summary/response.json')['answer'] == 'retained, not accepted'


def test_coverage_allows_distinct_tasks_but_not_rechecking_overlap(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(providers,'_codex_generate_raw',lambda r,**kw:calls.append(r) or {})
    with pytest.raises(PipelineError,match='already dispatched'):
        with linear.LinearSession(tmp_path).activate():
            providers.codex_generate(coverage(['R1']))
            providers.codex_generate(coverage(['R2']))
            providers.codex_generate(coverage(['R1','R3']))
    assert len(calls)==2


def test_provider_unchanged_outside_session(monkeypatch):
    raw={'unmodified':True}
    monkeypatch.setattr(providers,'_codex_generate_raw',lambda *a,**k:raw)
    assert providers.codex_generate({'old':'unrelated entrypoint'}) is raw


def test_linear_compression_stops_on_review_revise_no_patch(tmp_path,monkeypatch):
    state={'accepted':{}}
    monkeypatch.setattr(linear.engine,'load_run',lambda p:({'compression_profile':{'id':'LEAN_1.0'}},state))
    write_json(tmp_path/'inputs.json',{})
    monkeypatch.setattr(linear.engine,'prepare',lambda p,s:{'stage':s})
    calls=[]
    monkeypatch.setattr(providers,'codex_generate',lambda r,**k:calls.append(r['stage']) or {})
    def accept(p,s,r,provider):
        if s=='context':
            state['accepted'][s]={}
            return {'status':'ACCEPTED'}
        return {'status':'REVISE'}
    monkeypatch.setattr(linear.engine,'accept',accept)
    monkeypatch.setattr(linear.engine,'verify_context',lambda *a:pytest.fail('Must not verify a rejection'))
    with pytest.raises(PipelineError,match='REVISE'):
        linear.run_compression(tmp_path,tmp_path/'session')
    assert calls==['context','context_review']


def test_review_correction_fields_are_rejected_before_transport(tmp_path,monkeypatch):
    monkeypatch.setattr(providers,'_codex_generate_raw',lambda *a,**k:pytest.fail('Must not dispatch'))
    with pytest.raises(ValueError,match='correction/repair'):
        with linear.LinearSession(tmp_path).activate():
            providers.codex_generate(request(original_draft={'old':'answer'}))
