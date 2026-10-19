from pathlib import Path
import pytest
from research_pipeline.common import read_json, write_json, utcnow
from research_pipeline.execution_feedback import execution_feedback, model_progress
from test_context_revisions import stopped, endpoint


def make_timeout(work):
    call=work/'audit/model_calls/synthetic/requirements'
    write_json(work/'requests/requirements.json',{'request_sha256':'synthetic'})
    write_json(call/'call.json',{'status':'TIMEOUT','at':utcnow(),'timeout_seconds':600,'request_sha256':'synthetic'})
    (call/'stderr.log').write_text('failed to refresh available models: timeout waiting for child process to exit',encoding='utf-8')
    write_json(work/'stopped.json',{'status':'ERROR','stage':'requirements','at':utcnow(),
        'reason':'Model request exceeded 600 seconds; no candidate accepted'})


def test_timeout_has_clear_next_steps_and_is_not_a_proposal_rejection(stopped):
    client,canvas,sid,work,_=stopped; make_timeout(work)
    response=client.get(endpoint(sid)).json()
    context=next(n['state'] for n in response['nodes'] if n['id']=='context')
    f=context['failure']
    assert f['code']=='MODEL_TIMEOUT' and f['stage']=='requirements'
    assert '600 seconds' in f['summary']
    assert f['proposal_change_required'] is False and f['missing_materials']==[]
    assert any('diagnostic clue' in s for s in f['known_facts'])
    assert context['can_retry_context'] and not context['can_revise_context'] and not context['can_review']
    assert 'Snakemake traceback' not in context['error']


def test_timeout_retry_creates_new_attempt_without_changing_proposal(stopped):
    client,canvas,sid,work,calls=stopped; make_timeout(work)
    view=client.get(endpoint(sid)).json(); f=next(n['state']['failure'] for n in view['nodes'] if n['id']=='context')
    response=client.post(endpoint(sid,'/context-retries'),json={'failure_signature':f['signature'],'confirmed':True})
    assert response.status_code==202,response.text
    assert calls[0]['context_revision']['mode']=='RETRY_EXECUTION'
    assert calls[0]['context_revision']['prior_review']=={}
    assert calls[0]['context_revision']['scientific_approval'] is False
    assert all(not n['state']['approved'] for n in response.json()['nodes'])
    assert '600 seconds' in read_json(work/'stopped.json')['reason']


def test_timeout_retry_rejects_stale_report(stopped):
    client,_,sid,work,calls=stopped; make_timeout(work)
    assert client.post(endpoint(sid,'/context-retries'),json={'failure_signature':'stale','confirmed':True}).status_code==409
    assert not calls


def test_unknown_failure_does_not_invent_a_network_or_data_problem(tmp_path):
    f=execution_feedback(tmp_path,'Snakemake stopped:\nTraceback\nunknown')
    assert f['code']=='EXECUTION_FAILED' and f['proposal_change_required'] is None
    assert not f['retry_supported'] and f['missing_materials']==[]


@pytest.mark.parametrize('historical', [False, True])
def test_log_replace_failure_is_actionable_and_retryable(stopped, historical):
    client, _, sid, work, calls = stopped
    folder = work/'audit/model_calls/ioattempt/attachment_evidence--question_0008'
    call_path = folder/'call.json'
    write_json(call_path, {'status':'STARTED','at':utcnow(),'request_sha256':'io-request'})
    destination = folder/'progress.json'
    details = {'operation':'atomic_replace','path':str(destination.resolve()),'winerror':5,
        'attempts':8,'retry_wait_seconds':1.58,'occupying_process':'NOT_IDENTIFIED'}
    reason = f"[WinError 5] Access denied: {str(folder/'.writing-temp')!r} -> {str(destination)!r}"
    write_json(work/'stopped.json', {'status':'ERROR','stage':'attachment_evidence','at':utcnow(),
        'reason':reason,'model_call':str(call_path.relative_to(work)), 'failed_request_sha256':'io-request',
        'error_code':'CONTEXT_EXECUTION_ERROR' if historical else 'LOCAL_FILE_REPLACE_BLOCKED',
        'validation_details':None if historical else details})
    original = (work/'stopped.json').read_bytes()
    state = next(n['state'] for n in client.get(endpoint(sid)).json()['nodes'] if n['id']=='context')
    f = state['failure']
    assert f['code'] == 'LOCAL_FILE_REPLACE_BLOCKED'
    assert f['title'] == 'A local log file could not be updated'
    assert f['proposal_change_required'] is False and not f['scientific_release']
    assert f['validation_details']['occupying_process'] == 'NOT_IDENTIFIED'
    assert f['validation_details']['attempts'] == (1 if historical else 8)
    assert state['can_retry_context'] and not state['can_review']
    assert not f['missing_materials']
    assert (work/'stopped.json').read_bytes() == original
    response = client.post(endpoint(sid,'/context-retries'), json={'failure_signature':f['signature'],'confirmed':True})
    assert response.status_code == 202, response.text
    assert calls[0]['context_revision']['scientific_approval'] is False


def test_unrelated_access_denied_is_not_diagnosed_as_progress_replacement(tmp_path):
    work = tmp_path/'context_work'
    write_json(work/'stopped.json', {'status':'ERROR','stage':'attachment_evidence','at':utcnow(),
        'reason':"[WinError 5] Access denied: 'outside/.writing-temp' -> 'outside/progress.json'",
        'error_code':'CONTEXT_EXECUTION_ERROR', 'model_call':'../../outside/call.json'})
    assert execution_feedback(tmp_path, 'error')['code'] == 'CONTEXT_EXECUTION_ERROR'


def test_terminal_io_record_overrides_stale_running_progress(tmp_path):
    folder = tmp_path/'context_work/audit/model_calls/invocation/requirements'
    stamp = utcnow()
    stale = {'status':'RUNNING','started_at':stamp,'last_checked_at':stamp,'process_alive':True}
    write_json(folder/'progress.json', stale)
    write_json(folder/'progress.error.json', {**stale,'status':'ERROR','process_alive':False})
    progress = model_progress(tmp_path)
    assert progress['status'] == 'ERROR' and not progress['process_alive']
    assert len(progress['parallel_calls']) == 1
    # This also works if the first ordinary progress file was never published.
    (folder/'progress.json').unlink()
    assert model_progress(tmp_path)['status'] == 'ERROR'


def binding_failure(work):
    from ctxcomp.io import digest
    p = {'schema':{'type':'object'}, 'source_units':[{'id':'U1','source_id':'S1','text':'CL is 4 L/h.'}]}
    request = {'request_sha256':digest(p),'payload':p}
    response = {'request_sha256':request['request_sha256'],'requirements':{'items':[
        {'id':'I1','components':[{'id':'C1','evidence':[{'source_id':'S1','unit_id':'U1','quote':'CL is 4 L/h.'}]}],
         'science':{'bindings':[{'field':'value','value':'4.0 L/hour','component_ids':['C1']}]}}]}}
    write_json(work/'requests/requirements.json',request)
    write_json(work/'responses/requirements.exactattempt.json',response)
    call = work/'audit/model_calls/exactattempt/requirements/call.json'
    write_json(call, {'request_sha256':request['request_sha256'],'at':utcnow(),'status':'RETURNED'})
    write_json(work/'stopped.json',{'stage':'requirements','status':'ERROR','at':utcnow(),
        'model_call':str(call.relative_to(work)),
        'reason':'Binding value must occur in its cited source components; preserve original units/wording'})
    return response


def test_binding_failure_is_actionable_and_retryable_without_rewriting_proposal(stopped):
    client,canvas,sid,work,_ = stopped
    binding_failure(work)
    original = (work/'stopped.json').read_bytes()
    state = next(n['state'] for n in client.get(endpoint(sid)).json()['nodes'] if n['id']=='context')
    report = state['failure']
    assert report['code']=='MODEL_BINDING_INVALID'
    assert report['validation_details']['issue_count']==1
    assert report['validation_details']['issues'][0]['proposed_value']=='4.0 L/hour'
    assert report['proposal_change_required'] is False and not report['scientific_release']
    assert state['can_retry_context'] and not state['can_review']
    assert (work/'stopped.json').read_bytes()==original


def test_binding_replay_does_not_use_stale_response(tmp_path):
    work = tmp_path/'context_work'; response = binding_failure(work)
    response['request_sha256']='different'
    write_json(work/'responses/requirements.exactattempt.json',response)
    assert execution_feedback(tmp_path,'error')['code']=='EXECUTION_FAILED'


def test_failed_automatic_repair_explains_stop_and_allows_explicit_retry(stopped):
    client,canvas,sid,work,_ = stopped
    write_json(work/'stopped.json',{'stage':'binding_repair','status':'ERROR','at':utcnow(),
        'error_code':'MODEL_BINDING_REPAIR_FAILED','reason':'I001 / units: Cannot preserve the original association.',
        'validation_details':{'issue_count':1,'affected_item_count':1,'issues':[]}})
    state=next(n['state'] for n in client.get(endpoint(sid)).json()['nodes'] if n['id']=='context')
    assert state['can_retry_context'] and not state['can_review']
    assert 'one permitted correction' in state['failure']['summary']
    assert state['failure']['known_facts'][0].startswith('I001 / units')
    assert not state['failure']['scientific_release']


def test_historical_input_size_failure_is_explained_from_retained_log(stopped):
    client, canvas, sid, work, _ = stopped
    call = work/'audit/model_calls/synthetic/attachment_evidence'
    write_json(work/'requests/attachment_evidence.json', {'request_sha256':'oversized'})
    write_json(call/'call.json', {'status':'RETURNED','exit_code':1,'at':utcnow(),'request_sha256':'oversized'})
    (call/'stderr.log').write_text('Input exceeds the maximum length of 1048576 characters. '
        '{"input_error_code":"input_too_large","max_chars":1048576,"actual_chars":2968678}',encoding='utf-8')
    write_json(work/'stopped.json', {'status':'ERROR','stage':'attachment_evidence','at':utcnow(),
        'error_code':'MODEL_RESPONSE_UNAVAILABLE','reason':'No valid response file. Check CLI login.'})
    state=next(n['state'] for n in client.get(endpoint(sid)).json()['nodes'] if n['id']=='context')
    f=state['failure']
    assert f['code']=='MODEL_INPUT_TOO_LARGE'
    assert 'Submitted characters: 2,968,678' in f['known_facts']
    assert f['proposal_change_required'] is False and state['can_retry_context']
    assert any(r['path'].endswith('stderr.log') for r in f['evidence_refs'])
    session=canvas.load(sid); session['context_revision_child']='flow_child'
    write_json(canvas.path(sid),session)
    state=next(n['state'] for n in client.get(endpoint(sid)).json()['nodes'] if n['id']=='context')
    assert not state['can_retry_context'] and 'latest retry' in state['reason']


def test_old_timeout_does_not_override_later_failure(stopped):
    _,_,_,work,_=stopped; make_timeout(work)
    f=execution_feedback(work.parent,'Missing runtime executable','2099-01-01T00:00:00+00:00')
    assert f['code']=='EXECUTION_FAILED'


def make_legacy_citation_failure(work, quote='Predict exposure.'):
    from ctxcomp.io import digest
    from ctxcomp.supporting import SCHEMAS
    p={'stage':'attachment_evidence','schema':SCHEMAS['attachment_evidence'],
       'proposal_sources':[{'id':'P1','text':'Predict exposure.'}], 'passages':[],
       'questions':[{'id':'MI001'}], 'searches':[{'question_id':'MI001','passage_ids':[]}]}
    req={'request_sha256':digest(p),'payload':p}
    response={'request_sha256':req['request_sha256'],'answers':[{'question_id':'MI001',
        'status':'SEARCH_INCOMPLETE','statement':'Binding is unresolved.','reason':'Objective is not observed data.',
        'citations':[{'passage_id':'P1','quote':quote}]}]}
    root=work/'audit/attachment_agents/synthetic/file_0001'
    write_json(root/'request.json',req); write_json(root/'response.json',response)
    write_json(work/'stopped.json',{'status':'ERROR','stage':'attachment_evidence','at':utcnow(),
        'error_code':'CONTEXT_EXECUTION_ERROR', 'reason':"Citation is not in this question's searched evidence",
        'model_call':'audit/model_calls/synthetic/attachment_evidence/call.json'})
    return root


def test_legacy_valid_proposal_citation_explains_bug_and_enables_retry(stopped):
    client,_,sid,work,calls=stopped; root=make_legacy_citation_failure(work)
    original=(root/'response.json').read_bytes()
    state=next(n['state'] for n in client.get(endpoint(sid)).json()['nodes'] if n['id']=='context')
    f=state['failure']
    assert f['code']=='MODEL_CITATION_CONTRACT_MISMATCH'
    assert state['can_retry_context'] and not state['can_review']
    assert f['validation_details']['rejected_citation_count']==1
    assert f['proposal_change_required'] is False and f['scientific_release'] is False
    assert (root/'response.json').read_bytes()==original
    retry=client.post(endpoint(sid,'/context-retries'),json={'failure_signature':f['signature'],'confirmed':True})
    assert retry.status_code==202,retry.text
    assert calls[0]['context_revision']['scientific_approval'] is False


def test_legacy_invalid_quote_is_not_reported_as_fixed(stopped):
    _,_,_,work,_=stopped; make_legacy_citation_failure(work,'Observed human data.')
    f=execution_feedback(work.parent,'old validation error')
    assert f['code']=='MODEL_CITATION_INVALID'
    assert f['validation_details']['reason']=='QUOTE_NOT_IN_SOURCE'
    assert 'MI001' in f['summary'] and 'P1' in f['summary']
    assert not f['scientific_release']


@pytest.mark.parametrize('change',['hash','invocation'])
def test_legacy_replay_requires_exact_request_and_invocation(stopped,change):
    _,_,_,work,_=stopped; root=make_legacy_citation_failure(work)
    if change=='hash':
        response=read_json(root/'response.json'); response['request_sha256']='different'
        write_json(root/'response.json',response)
    else:
        record=read_json(work/'stopped.json'); record['model_call']='audit/model_calls/different/attachment_evidence/call.json'
        write_json(work/'stopped.json',record)
    f=execution_feedback(work.parent,'old validation error')
    assert f['code']=='CONTEXT_EXECUTION_ERROR' and not f['retry_supported']


def test_new_citation_failure_reports_exact_question_and_source(stopped):
    client,_,sid,work,_=stopped
    record=work/'audit/attachment_agents/current/file_0001/validation_error.json'
    write_json(record,{'at':utcnow(),'request_sha256':'failed-worker','status':'REJECTED'})
    write_json(record.with_name('request.json'),{'request_sha256':'failed-worker'})
    write_json(record.with_name('response.json'),{'request_sha256':'failed-worker'})
    write_json(work/'stopped.json',{'status':'ERROR','stage':'attachment_evidence','at':utcnow(),
        'error_code':'MODEL_CITATION_INVALID','reason':'Wrong citation',
        'failed_request_sha256':'failed-worker','validation_record':str(record.relative_to(work)),
        'validation_details':{'question_id':'MI003','citation_id':'F2_E3','source_type':'ATTACHMENT','reason':'OUT_OF_SCOPE'}})
    state=next(n['state'] for n in client.get(endpoint(sid)).json()['nodes'] if n['id']=='context')
    assert state['can_retry_context'] and not state['can_review']
    assert 'MI003' in state['failure']['summary'] and 'F2_E3' in state['failure']['summary']
    assert state['failure']['proposal_change_required'] is False
    assert {Path(r['path']).name for r in state['failure']['evidence_refs']} >= {'validation_error.json','request.json','response.json'}


def test_unresolved_citation_review_explains_support_not_permission(stopped):
    client,_,sid,work,_=stopped
    write_json(work/'stopped.json',{'status':'ERROR','stage':'attachment_evidence','at':utcnow(),
        'error_code':'MODEL_CITATION_REPAIR_FAILED','reason':'MI005 / F5: Study identity cannot be confirmed.',
        'validation_details':{'attempts':1,'issue_count':1,'issues':[{'question_id':'MI005',
            'citation_id':'F5','support_status':'NOT_ESTABLISHED','outcome':'UNRESOLVED'}]}})
    state=next(n['state'] for n in client.get(endpoint(sid)).json()['nodes'] if n['id']=='context')
    report=state['failure']
    assert state['can_retry_context'] and not state['can_review']
    assert report['summary']=='MI005 / F5: Study identity cannot be confirmed.'
    assert all('not permitted' not in fact for fact in report['known_facts'])
    assert report['validation_details']['issues'][0]['support_status']=='NOT_ESTABLISHED'
    assert 'does not prove the claim false' in report['uncertainty']
    assert report['scientific_release'] is False


def test_stale_monitor_does_not_claim_process_is_alive(tmp_path):
    p=tmp_path/'context_work/audit/model_calls/test/requirements/progress.json'
    write_json(p,{'started_at':'2020-01-01T00:00:00+00:00','last_checked_at':'2020-01-01T00:00:00+00:00','process_alive':True})
    result=model_progress(tmp_path)
    assert not result['monitor_current'] and not result['process_alive']


@pytest.mark.parametrize('stage',['context_faithfulness','context_completeness','context_conflicts'])
def test_invalid_parallel_review_has_clear_diagnosis_and_retry_interface(stopped,stage):
    client,canvas,sid,work,calls=stopped
    write_json(work/'stopped.json',{'status':'ERROR','stage':stage,'at':utcnow(),
        'error_code':'MODEL_REVIEW_INVALID','reason':'Atomic claim A1 at /rules/1 quotes text absent from the candidate context.'})
    view=client.get(endpoint(sid)).json()
    state=next(n['state'] for n in view['nodes'] if n['id']=='context'); f=state['failure']
    assert f['code']=='MODEL_REVIEW_INVALID' and f['proposal_change_required'] is False
    assert state['can_retry_context'] and not state['can_review'] and f['missing_materials']==[]
    assert any('evidence[].quote' in text for text in f['suggested_actions'])
    response=client.post(endpoint(sid,'/context-retries'),json={'failure_signature':f['signature'],'confirmed':True})
    assert response.status_code==202,response.text
    assert calls[0]['context_revision']['mode']=='RETRY_EXECUTION'


def test_browser_execution_retry_and_heartbeat(stopped):
    import os, socket, subprocess, threading
    import uvicorn
    from research_pipeline.common import BACKEND, PROJECT
    client,canvas,sid,work,calls=stopped; make_timeout(work)
    original_launch=canvas.context_revisions.launch
    def launch(*args):
        job=original_launch(*args); spec=calls[-1]; timestamp=utcnow()
        write_json(Path(spec['out'])/'context_work/audit/model_calls/test/requirements/progress.json',{
            'status':'RUNNING','started_at':timestamp,'last_checked_at':timestamp,'process_alive':True,
            'elapsed_seconds':300,'model_event_count':1,'last_model_event_at':timestamp,'timeout_seconds':None,
            'last_heartbeat':{'sequence':1,'at':timestamp,'elapsed_seconds':300,'message':'Synthetic liveness message only.'}})
        return job
    canvas.context_revisions.launch=launch
    sock=socket.socket(); sock.bind(('127.0.0.1',0)); sock.listen(); port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(client.app,log_level='error'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},daemon=True); thread.start()
    try:
        env={**os.environ,'CANVAS_URL':f'http://127.0.0.1:{port}','CONTEXT_SESSION':sid,
            'CONTEXT_CHECK_OUT':str(PROJECT/'outputs/Workbench_v22_Check')}
        node='C:/Users/georg/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe'
        result=subprocess.run([node,str(BACKEND/'research_pipeline/scripts/check_context_revision.mjs'),'--execution-retry'],
            capture_output=True,text=True,encoding='utf-8',env=env,timeout=60)
        assert result.returncode==0,result.stdout+result.stderr
        assert len(calls)==1
    finally:
        server.should_exit=True; thread.join(timeout=10); sock.close()


def test_unresolved_source_coverage_stops_before_any_model_call_with_actionable_feedback(tmp_path):
    import zipfile
    from docx import Document
    from ctxcomp.coverage import SourceIncompleteError
    from ctxcomp.engine import init_run
    from ctxcomp.providers import run_model
    proposal = tmp_path / 'proposal.txt'; proposal.write_text('Objective: estimate rat clearance.', encoding='utf-8')
    study = tmp_path / 'study.docx'; document = Document(); document.add_paragraph('Study notes.'); document.save(study)
    with zipfile.ZipFile(study, 'a') as archive:
        archive.writestr('word/comments.xml', '<w:comments xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                         '<w:comment w:id="0"><w:p><w:r><w:t>Use the corrected dose.</w:t></w:r></w:p></w:comment></w:comments>')
    run = tmp_path / 'flow'; init_run(run / 'context_work', attachments=[proposal, study], proposal_entry=proposal.name)
    def never(*args, **kwargs): raise AssertionError('No model call while IN001 gaps are unresolved')
    with pytest.raises(SourceIncompleteError):
        run_model(run / 'context_work', generator=never)
    assert read_json(run / 'context_work/stopped.json')['error_code'] == 'SOURCE_INCOMPLETE'
    f = execution_feedback(run, 'IN001 SOURCE_INCOMPLETE')
    assert f['code'] == 'SOURCE_INCOMPLETE' and 'IN001' in f['title']
    assert f['known_facts'] == ['study.docx: Word comments (1) at 1 comment in word/comments.xml']
    assert any('irrelevant' in a for a in f['suggested_actions']) and not f['retry_supported']


def test_split_faithfulness_part_has_a_readable_label():
    from research_pipeline.execution_feedback import stage_label
    assert stage_label('context_faithfulness--part_2') == 'Context faithfulness review · part 2'
    assert stage_label('context_completeness') == 'Context completeness review'
    assert stage_label(None) == 'Executor'


@pytest.mark.parametrize('code,stage,mode,parallel', [
    ('MODEL_RATE_LIMITED', 'attachment_evidence', 'parallel_v2', True),
    ('MODEL_RATE_LIMITED', 'requirements', 'parallel_v3', False),
    ('MODEL_SILENT', 'context_faithfulness--part_2', 'parallel_v2', True),
    ('MODEL_SILENT', 'context_conflicts', 'parallel_v2', False),  # Runs alone after the other reviews.
    ('MODEL_SILENT', 'context_conflicts', 'parallel_v3', True)])
def test_rate_limit_and_silence_are_retryable_and_name_their_settings(tmp_path, code, stage, mode, parallel):
    work = tmp_path/'context_work'
    write_json(work/'inputs.json', {'context_review_mode': mode})
    reason = ('Codex returned exit code 1; the model service reported a rate or usage limit.' if code == 'MODEL_RATE_LIMITED'
              else 'The model process sent no output for 900 seconds and was stopped (CTXCOMP_MODEL_SILENCE_SECONDS).')
    write_json(work/'stopped.json', {'status':'ERROR','stage':stage,'at':utcnow(),'error_code':code,'reason':reason})
    f = execution_feedback(tmp_path, 'Snakemake stopped:\nTraceback')
    assert f['code'] == code and f['retry_supported'] and f['proposal_change_required'] is False
    assert f['missing_materials'] == [] and f['scientific_release'] is False
    assert any(a.startswith(('Retry context', 'Wait for the limit to reset, then Retry context')) for a in f['suggested_actions'])
    setting = 'CTXCOMP_REVIEW_WORKERS' if code == 'MODEL_RATE_LIMITED' else 'CTXCOMP_MODEL_SILENCE_SECONDS'
    assert any(setting in a for a in f['suggested_actions'])
    assert any('kept for the retry' in x for x in f['known_facts']) is parallel
    if code == 'MODEL_SILENT': assert '900 seconds' in f['summary']


def test_silent_review_part_offers_retry_in_the_workbench(stopped):
    client,canvas,sid,work,calls=stopped
    write_json(work/'stopped.json',{'status':'ERROR','stage':'context_faithfulness--part_1','at':utcnow(),'error_code':'MODEL_SILENT',
        'reason':'The model process sent no output for 900 seconds and was stopped (CTXCOMP_MODEL_SILENCE_SECONDS). No candidate was accepted.'})
    state=next(n['state'] for n in client.get(endpoint(sid)).json()['nodes'] if n['id']=='context')
    assert state['failure']['code']=='MODEL_SILENT' and state['failure']['stage_label']=='Context faithfulness review · part 1'
    assert state['can_retry_context'] and not state['can_review']
