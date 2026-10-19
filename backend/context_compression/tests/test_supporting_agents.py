"""File-scoped transport and citation gates; synthetic, not LLM accuracy tests."""
import copy
import pytest
from ctxcomp.io import digest, canonical, read_json
from ctxcomp.supporting import SCHEMAS, validate
from ctxcomp.supporting_agents import execute, plan_calls, synthesis_request


def request():
    questions = [dict(id='MI001', field='binding', question='What is the exposure basis?',
        importance='MATERIAL', importance_reason='Defines exposure', needed_at='pk',
        downstream_impact='Select correct exposure', requested_information='Free or total?',
        file_ids=['F1', 'F2', 'F3'], search_terms=['binding'])]
    passages = [dict(id=f'{f}_{i}', file_id=f, name=f+'.txt', locator=f'row {i}',
                     text=('binding '+str(i)+' ') * 12, file_sha256=f) for f in ['F1','F2'] for i in range(6)]
    payload = dict(stage='attachment_evidence', schema=SCHEMAS['attachment_evidence'],
        proposal_sources=[dict(id='P1', text='Predict exposure.')], questions=questions,
        passages=passages, searches=[dict(question_id='MI001', terms=['binding'], method='Literal search',
        passage_ids=[p['id'] for p in passages], files=[
            dict(file_id=f, status='MATCHED_PASSAGES', locations=[], records_scanned=6) for f in ['F1','F2']
        ]+[dict(file_id='F3', status='PROTECTED_NOT_READ', locations=[])])],
        instructions='Preserve evidence.', processing_rules={'rules':[{'id':'CC005','instruction':'Keep units.'}]})
    return dict(request_sha256=digest(payload), payload=payload)


def responder(calls):
    def generate(req, label):
        calls.append(req)
        p=req['payload']
        return dict(request_sha256=req['request_sha256'], answers=[dict(question_id=q['id'],
            status='FOUND', statement='Binding evidence was found.', reason='Exact local evidence.',
            citations=[dict(passage_id=p['passages'][0]['id'], quote=p['passages'][0]['text'])]) for q in p['questions']])
    return generate


def test_every_passage_is_assigned_only_to_its_file_with_rules():
    req=request(); calls=plan_calls(req, max_chars=3200)
    seen=set()
    assert len(calls)>2
    for c in calls:
        p=c['request']['payload']
        assert len(canonical(c['request']))<=3200
        assert {x['file_id'] for x in p['passages']}=={c['file_id']}
        assert p['questions'][0]['file_ids']==[c['file_id']]
        assert p['processing_rules']==req['payload']['processing_rules']
        assert p['proposal_sources']==req['payload']['proposal_sources']
        seen.update(x['id'] for x in p['passages'])
    assert seen=={x['id'] for x in req['payload']['passages']}
    assert all(c['file_id']!='F3' for c in calls)


def test_synthesis_gets_findings_and_exact_citations_not_all_raw_rows(tmp_path):
    req=request(); calls=[]
    result=execute(req,tmp_path,responder(calls),max_chars=6500)
    assert result['request_sha256']==req['request_sha256']
    assert len(result['answers'])==1
    summary=calls[-1]['payload']
    assert summary['evidence_task']['mode']=='QUESTION_SYNTHESIS'
    assert any(f['answer']['status']=='DEFERRED' for f in summary['file_findings'])
    quoted={c['passage_id'] for f in summary['file_findings'] for c in f['answer']['citations']}
    assert {p['id'] for p in summary['passages']}==quoted
    assert len(summary['passages'])<len(req['payload']['passages'])
    assert read_json(tmp_path/'coverage.json')['status']=='COMPLETE'


def test_no_gaps_skips_model_calls(tmp_path):
    req=request(); req['payload'].update(questions=[],passages=[],searches=[])
    calls=[]
    assert execute(req,tmp_path,responder(calls))['answers']==[]
    assert calls==[]


def test_failure_stops_without_publishing_partial_results(tmp_path):
    def fail(req,label): raise RuntimeError('Synthetic unavailable provider')
    with pytest.raises(RuntimeError,match='Synthetic'):
        execute(request(),tmp_path,fail)
    assert not (tmp_path/'response.json').exists()


def test_worker_cannot_cite_another_file(tmp_path):
    def wrong(req,label):
        return {'request_sha256':req['request_sha256'],'answers':[dict(question_id='MI001',status='FOUND',
            statement='wrong',reason='wrong',citations=[dict(passage_id='F2_0',quote='binding')])]}
    with pytest.raises(ValueError,match='searched evidence'):
        execute(request(),tmp_path,wrong)


def test_conflict_cannot_disappear_at_synthesis(tmp_path):
    good=responder([])
    def conflict(req,label):
        r=good(req,label)
        if req['payload']['evidence_task']['mode']=='FILE_SEARCH': r['answers'][0]['status']='CONFLICT'
        return r
    with pytest.raises(ValueError,match='conflict'):
        execute(request(),tmp_path,conflict)


def test_oversized_indivisible_record_stops_instead_of_truncating():
    req=request(); req['payload']['passages'][0]['text']='x'*20000
    with pytest.raises(ValueError,match='cannot fit'):
        plan_calls(req,max_chars=4200)


def test_live_runner_uses_file_agents_before_later_extraction(tmp_path):
    from test_runtime_rules import evidence_run
    from ctxcomp.providers import run_model
    from ctxcomp.engine import load_run
    run, _, _ = evidence_run(tmp_path)
    calls=[]
    good=responder(calls)
    def generator(req,model=None):
        if req['payload']['stage']!='attachment_evidence':
            raise RuntimeError('Synthetic stop after attachment handoff')
        return good(req,'fixture')
    with pytest.raises(RuntimeError,match='Synthetic stop'):
        run_model(run,generator=generator)
    assert len(calls)==1 and calls[0]['payload']['evidence_task']['mode']=='FILE_SEARCH'
    _, state=load_run(run)
    assert 'attachment_evidence' in state['accepted']
    assert list((run/'audit/attachment_agents').glob('*/coverage.json'))


def proposal_answer(req, quote='Predict exposure.'):
    return {'request_sha256':req['request_sha256'], 'answers':[{
        'question_id':'MI001','status':'SEARCH_INCOMPLETE','statement':'The objective is known; binding is unresolved.',
        'reason':'Proposal background is not evidence that binding data exist.',
        'citations':[{'passage_id':'P1','quote':quote}]}]}


def test_exact_primary_proposal_citation_is_allowed_in_file_worker():
    req=plan_calls(request())[0]['request']
    validate(req,proposal_answer(req))


def test_altered_proposal_quote_is_rejected_with_identifiers():
    req=plan_calls(request())[0]['request']
    with pytest.raises(ValueError) as error:
        validate(req,proposal_answer(req,'Observed human exposure.'))
    assert error.value.code=='MODEL_CITATION_INVALID'
    assert error.value.validation_details=={
        'question_id':'MI001','citation_id':'P1','source_type':'PROPOSAL','reason':'QUOTE_NOT_IN_SOURCE'}


def test_mixed_citations_survive_synthesis_without_relabeling_proposal_as_attachment(tmp_path):
    calls=[]
    def generate(req,label):
        calls.append(req)
        result=proposal_answer(req)
        passage=req['payload']['passages'][0]
        result['answers'][0]['citations'].append({'passage_id':passage['id'],'quote':passage['text']})
        return result
    result=execute(request(),tmp_path,generate)
    synth=calls[-1]['payload']
    assert synth['evidence_task']['mode']=='QUESTION_SYNTHESIS'
    assert synth['proposal_sources']==request()['payload']['proposal_sources']
    assert 'P1' not in {p['id'] for p in synth['passages']}
    assert 'P1' not in synth['searches'][0]['passage_ids']
    assert any(c['passage_id']=='P1' for c in result['answers'][0]['citations'])


def test_proposal_only_citations_can_be_reconciled(tmp_path):
    result=execute(request(),tmp_path,lambda req,label:proposal_answer(req))
    assert result['answers'][0]['citations']==[{'passage_id':'P1','quote':'Predict exposure.'}]
    validate(request(),result)


def test_invalid_citation_is_saved_as_actionable_validation_record(tmp_path):
    def wrong(req,label): return proposal_answer(req,'Not in the supplied source')
    with pytest.raises(ValueError) as error:
        execute(request(),tmp_path,wrong)
    record=read_json(tmp_path/'file_0001/validation_error.json')
    assert record['validation_details']['citation_id']=='P1'
    assert record['validation_details']['question_id']=='MI001'
    assert record['request_sha256']==error.value.failed_request_sha256
    assert (tmp_path/'file_0001/response.json').exists()
    assert not (tmp_path/'response.json').exists()


@pytest.mark.parametrize('citation_id,kind',[('FABRICATED','UNKNOWN'),('F1_1','ATTACHMENT')])
def test_unknown_or_other_question_citations_remain_blocked(citation_id,kind):
    req=request()
    req['payload']['searches'][0]['passage_ids']=['F1_0']
    req['request_sha256']=digest(req['payload'])
    result=proposal_answer(req,'binding')
    result['answers'][0]['citations'][0]['passage_id']=citation_id
    with pytest.raises(ValueError) as error:
        validate(req,result)
    assert error.value.validation_details['source_type']==kind
    assert error.value.validation_details['reason']=='OUT_OF_SCOPE'


def test_duplicate_source_ids_stop_before_model_calls(tmp_path):
    req=request(); req['payload']['passages'][0]['id']='P1'; calls=[]
    with pytest.raises(ValueError,match='Ambiguous evidence source ID'):
        execute(req,tmp_path,responder(calls))
    assert calls==[]


def test_audit_keeps_proposal_and_attachment_source_types():
    from ctxcomp.supporting import audit_reports
    req=request(); result=proposal_answer(req)
    result['answers'][0]['citations'].append({'passage_id':'F1_0','quote':'binding'})
    report=audit_reports({'missing_information_warnings':[],'sources':[]},req,result)['supporting_evidence.json']
    assert {s['id']:s['source_type'] for s in report['citation_sources']}=={'P1':'PROPOSAL','F1_0':'ATTACHMENT'}


def test_live_runner_preserves_failed_worker_identifiers(tmp_path, monkeypatch):
    from test_runtime_rules import evidence_run
    from ctxcomp.providers import run_model
    from rule_versions import before_1_29, freeze
    freeze(monkeypatch, before_1_29())  # From 1.29.0 the citation is removed instead (test_unconfirmed_evidence).
    run, _, _=evidence_run(tmp_path)
    def wrong(req,model=None):
        if req['payload']['stage']=='attachment_citation_repair':
            return {'request_sha256':req['request_sha256'],'decisions':[{
                'issue_id':x['issue_id'],'decision':'UNRESOLVED','source_id':x['citation']['passage_id'],'quote':x['citation']['quote'],
                'reason':'Synthetic reviewer cannot establish the intended quotation.'} for x in req['payload']['issues']]}
        result=responder([])(req,'fixture')
        result['answers'][0]['citations'][0]['quote']='Deliberately incorrect quotation.'
        return result
    with pytest.raises(ValueError): run_model(run,generator=wrong)
    stopped=read_json(run/'stopped.json')
    assert stopped['error_code']=='MODEL_CITATION_REPAIR_FAILED'
    assert stopped['validation_details']['issues'][0]['question_id']=='MI001'
    assert 'attachment_evidence--file_0001' in stopped['model_call']
    assert 'citation_repair' in stopped['model_call']
    validation=read_json(run/stopped['validation_record'])
    assert validation['request_sha256']==stopped['failed_request_sha256']
    assert not (run/'main.json').exists()


def test_parallel_file_agents_overlap_and_give_the_sequential_result(tmp_path):
    import threading
    req=request(); both_running=threading.Barrier(2,timeout=10)
    def generate(r,label):
        if r['payload']['evidence_task']['mode']=='FILE_SEARCH': both_running.wait()  # Fails if run one at a time.
        return responder([])(r,label)
    parallel=execute(req,tmp_path/'parallel',generate,workers=4)
    assert parallel==execute(req,tmp_path/'sequential',responder([]))
    for name in ['plan.json','file_0001/request.json','file_0002/request.json','question_0001/request.json','response.json']:
        assert read_json(tmp_path/'parallel'/name)==read_json(tmp_path/'sequential'/name)
    assert read_json(tmp_path/'parallel/coverage.json')['max_concurrent_calls']==4


def test_parallel_failure_starts_no_new_call_and_lets_running_calls_finish(tmp_path):
    import threading
    req=request(); started=[]; failed=threading.Event()
    assert len(plan_calls(req,max_chars=3200))>2
    def generate(r,label):
        started.append(label)
        if label=='file_0002': failed.set(); raise RuntimeError('Synthetic provider failure')
        assert failed.wait(10)  # Still running when its sibling fails, and not stopped by it.
        return responder([])(r,label)
    with pytest.raises(RuntimeError,match='Synthetic provider failure'):
        execute(req,tmp_path,generate,max_chars=3200,workers=2)
    assert sorted(started)==['file_0001','file_0002']
    finished=read_json(tmp_path/'file_0001/response.json')
    assert finished['request_sha256']==read_json(tmp_path/'file_0001/request.json')['request_sha256']
    assert not (tmp_path/'response.json').exists()


def test_retry_reuses_valid_calls_of_the_same_executor_only(tmp_path):
    req=request(); run=tmp_path/'run'; cache=run/'evidence_cache'
    def failing(r,label):
        if label=='file_0002': raise RuntimeError('Synthetic provider failure')
        return responder([])(r,label)
    with pytest.raises(RuntimeError):
        execute(req,run/'audit/attachment_agents/first',failing,max_chars=6500,cache_dir=cache,executor_id='test-provider-v1')
    calls=[]
    def labelled(r,label):
        calls.append(label); return responder([])(r,label)
    result=execute(req,run/'audit/attachment_agents/second',labelled,max_chars=6500,cache_dir=cache,executor_id='test-provider-v1')
    assert 'file_0001' not in calls and 'file_0002' in calls
    assert result==execute(req,tmp_path/'fresh',responder([]),max_chars=6500)
    second=run/'audit/attachment_agents/second'
    assert read_json(second/'file_0001/reused.json')['from']=='audit/attachment_agents/first/file_0001/response.json'
    assert 'file_0001' in read_json(second/'coverage.json')['reused_calls']
    # Another executor, or no executor identity, never reuses a response.
    other=[]
    execute(req,run/'audit/attachment_agents/third',lambda r,label:(other.append(label),responder([])(r,label))[1],
            max_chars=6500,cache_dir=cache,executor_id='another-provider')
    assert 'file_0001' in other
    anonymous=[]
    execute(req,run/'audit/attachment_agents/fourth',lambda r,label:(anonymous.append(label),responder([])(r,label))[1],
            max_chars=6500,cache_dir=cache)
    assert 'file_0001' in anonymous


def test_a_later_run_reuses_valid_calls_from_the_shared_memory(tmp_path):
    req=request(); shared=tmp_path/'memory'/'attachment_evidence_calls'
    first=execute(req,tmp_path/'first/audit',responder([]),max_chars=6500,cache_dir=tmp_path/'first/evidence_cache',
                  executor_id='test-provider-v1',shared_cache=shared)
    calls=[]
    second=execute(req,tmp_path/'second/audit',responder(calls),max_chars=6500,cache_dir=tmp_path/'second/evidence_cache',
                   executor_id='test-provider-v1',shared_cache=shared)
    assert calls==[] and second==first
    assert read_json(tmp_path/'second/audit/file_0001/reused.json')['shared'] is True
    # A fresh attempt still calls the model, and another executor never reuses.
    fresh=[]
    execute(req,tmp_path/'third/audit',responder(fresh),max_chars=6500,executor_id='test-provider-v1',
            shared_cache=shared,shared_lookup=False)
    other=[]
    execute(req,tmp_path/'fourth/audit',responder(other),max_chars=6500,executor_id='another-provider',shared_cache=shared)
    assert fresh and len(fresh)==len(other)


def test_changed_reusable_response_stops_the_retry(tmp_path):
    from ctxcomp.io import write_json
    req=request(); run=tmp_path/'run'; cache=run/'evidence_cache'
    execute(req,run/'audit/attachment_agents/first',responder([]),max_chars=6500,cache_dir=cache,executor_id='test-provider-v1')
    path=run/'audit/attachment_agents/first/file_0001/response.json'
    response=read_json(path); response['answers'][0]['reason']='Altered audit'; write_json(path,response)
    calls=[]
    with pytest.raises(ValueError,match='changed'):
        execute(req,run/'audit/attachment_agents/second',responder(calls),max_chars=6500,cache_dir=cache,executor_id='test-provider-v1')


def test_live_runner_runs_evidence_calls_with_a_shared_cancel_signal(tmp_path,monkeypatch):
    from test_runtime_rules import evidence_run
    from ctxcomp import providers
    run, _, _=evidence_run(tmp_path); signals=[]
    def codex(req,model=None,timeout=None,diagnostics_dir=None,cancel_event=None,cli_schema=None):
        if req['payload']['stage']!='attachment_evidence': raise RuntimeError('Synthetic stop after attachment handoff')
        signals.append(cancel_event)
        return responder([])(req,'fixture')
    monkeypatch.setattr(providers,'codex_generate',codex)
    monkeypatch.setenv('CTXCOMP_EVIDENCE_WORKERS','2')
    with pytest.raises(RuntimeError,match='Synthetic stop'): providers.run_model(run,generator=codex)
    assert len(signals)==1 and not signals[0].is_set()
    assert read_json(next((run/'audit/attachment_agents').glob('*/coverage.json')))['max_concurrent_calls']==2


@pytest.mark.parametrize('value,expected',[(None,6),('1',1),(' 6 ',6),('0',None),('two',None),('1.5',None)])
def test_evidence_worker_count_setting(monkeypatch,value,expected):
    from ctxcomp.supporting_agents import evidence_workers
    if value is None: monkeypatch.delenv('CTXCOMP_EVIDENCE_WORKERS',raising=False)
    else: monkeypatch.setenv('CTXCOMP_EVIDENCE_WORKERS',value)
    if expected is None:
        with pytest.raises(ValueError,match='whole number'): evidence_workers()
    else:
        assert evidence_workers()==expected


def two_question_request():
    """MI001 searches F1 and F2; MI002 searches F2 only (two batches of F2 at max_chars=4000)."""
    req = request(); p = copy.deepcopy(req['payload'])
    p['questions'][0]['file_ids'] = ['F1', 'F2']
    p['questions'].append({**p['questions'][0], 'id': 'MI002', 'file_ids': ['F2']})
    p['searches'][0]['files'] = [f for f in p['searches'][0]['files'] if f['file_id'] != 'F3']
    p['searches'].append({**p['searches'][0], 'question_id': 'MI002',
        'passage_ids': [x['id'] for x in p['passages'] if x['file_id'] == 'F2'],
        'files': [f for f in p['searches'][0]['files'] if f['file_id'] == 'F2']})
    return dict(request_sha256=digest(p), payload=p)


def test_a_question_synthesis_starts_once_its_own_files_have_returned(tmp_path):
    """Compression rules 1.25.0: MI002 needs only F2, so its synthesis runs while the slow F1 call is still going."""
    import threading
    req = two_question_request(); slow = threading.Event(); order = []
    plan = plan_calls(req, max_chars=4000)
    f1 = [c['id'] for c in plan if c['file_id'] == 'F1']
    def generate(r, label):
        order.append(label)
        if label in f1:
            assert slow.wait(10)  # Released only when MI002's synthesis has started.
        elif r['payload']['evidence_task']['mode'] == 'QUESTION_SYNTHESIS' and r['payload']['questions'][0]['id'] == 'MI002':
            slow.set()
        return responder([])(r, label)
    result = execute(req, tmp_path/'early', generate, max_chars=6500, batch=4000, workers=8)
    assert slow.is_set() and [a['question_id'] for a in result['answers']] == ['MI001', 'MI002']
    # The same calls and answers as one call at a time.
    assert result == execute(req, tmp_path/'serial', responder([]), max_chars=6500, batch=4000, workers=1)


def test_batch_size_comes_from_the_runs_rules():
    from ctxcomp.supporting_agents import batch_chars, MAX_REQUEST_CHARS
    rules = lambda hr: {'processing_rules': {'rules': [{'id': 'CC002', 'host_requirement': hr}]}}
    assert batch_chars(rules({})) == MAX_REQUEST_CHARS
    assert batch_chars(rules({'evidence_batch_chars': 250000})) == 250000
    assert batch_chars(rules({'evidence_batch_chars': 10**9})) == MAX_REQUEST_CHARS
    req = request()
    small = plan_calls(req, max_chars=3200); large = plan_calls(req, max_chars=6500)
    assert len(small) > len(large)


def test_a_call_that_is_done_before_its_callback_is_added_does_not_deadlock(tmp_path, monkeypatch):
    """A reused response can finish before add_done_callback; the callback then runs in the submitting thread."""
    import threading
    from concurrent.futures import Future
    from ctxcomp import supporting_agents
    class Immediate:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def submit(self, fn, *args):
            future = Future(); future.set_result(fn(*args)); return future
    monkeypatch.setattr(supporting_agents, 'ThreadPoolExecutor', Immediate)
    req = two_question_request(); result = {}
    worker = threading.Thread(target=lambda: result.update(answer=execute(
        req, tmp_path/'immediate', responder([]), max_chars=6500, batch=4000, workers=8)), daemon=True)
    worker.start(); worker.join(20)
    assert not worker.is_alive(), 'evidence calls deadlocked'
    assert [a['question_id'] for a in result['answer']['answers']] == ['MI001', 'MI002']
