"""Workbench retries and extraction repairs continue the same run when its code and inputs are unchanged.
Authored responses and a stubbed launcher only; no live model calls or research approvals."""
import importlib.util
import io
import os
import subprocess
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from ctxcomp.engine import load_run, make_request, prepare, accept
from research_pipeline.attachments import store_upload, uploaded_path
from research_pipeline.common import BACKEND, read_json, write_json, utcnow
from research_pipeline.workbench import create_workbench, worker_record
from research_pipeline.workflow_runtime import make_plan, execute_contract

spec = importlib.util.spec_from_file_location('demo', BACKEND / 'context_compression/examples/replay_demo.py')
demo = importlib.util.module_from_spec(spec); spec.loader.exec_module(demo)
QUOTE = 'Freeze targets and MIC input.'


def endpoint(sid, suffix=''):
    return '/ui-api/workflow/sessions/' + sid + suffix


@pytest.fixture
def job(tmp_path):
    """A real plan and intake receipt; compression accepted the attachment steps before stopping."""
    app = create_workbench(tmp_path / 'runs', tmp_path / 'state'); canvas = app.state.canvas
    sid = canvas.create()['session_id']
    uploads = [store_upload(canvas.state, io.BytesIO(content), name) for name, content in [
        ('proposal.txt', (QUOTE + ' Keep unresolved permissions explicit.').encode()),
        ('data.csv', b'time,concentration\n1,2\n')]]
    jid = 'same_run_job'; folder = canvas.state / 'workbench_jobs' / jid
    job_spec = {'id': jid, 'created_at': utcnow(), 'mode': 'fresh', 'proposal_entry': 'proposal.txt', 'reference_only': [],
        'model': None, 'project_materials': [], 'stop_after': 'context', 'out': str(canvas.outputs / jid), 'job_dir': str(folder),
        'uploads': [{'path': str(uploaded_path(canvas.state, u['upload_id'])), 'name': name, 'sha256': u['sha256']}
                    for u, name in zip(uploads, ['proposal.txt', 'data.csv'])]}
    write_json(folder / 'request.json', job_spec)
    plan = make_plan(job_spec); execute_contract(plan['steps']['intake']['contract'])
    work = Path(job_spec['out']) / 'context_work'
    for stage, field in [('attachment_plan', 'questions'), ('attachment_evidence', 'answers')]:
        accept(work, stage, {'request_sha256': prepare(work, stage)['request_sha256'], field: []})
    s = canvas.load(sid); s['job_id'] = jid; canvas.collect_outputs(s, 'intake')
    s['nodes']['context'].update(execution='FAILED', error='Snakemake traceback details')
    write_json(canvas.path(sid), s)
    resumed, launched = [], []
    canvas.resume = lambda identifier, target: resumed.append((identifier, target))
    def launch(*args):
        launched.append(args)
        child = canvas.state / 'workbench_jobs/new_run_job'
        write_json(child / 'request.json', {'id': 'new_run_job', 'job_dir': str(child), 'out': str(canvas.outputs / 'new_run_job')})
        write_json(child / 'status.json', {'id': 'new_run_job', 'created_at': utcnow(), 'status': 'RUNNING'})
        return {'id': 'new_run_job'}
    canvas.context_revisions.launch = launch
    return TestClient(app), canvas, sid, work, folder, resumed, launched


def stop_job(folder, status, started):
    write_json(folder / 'status.json', {'id': folder.name, 'created_at': started, 'started_at': started,
        'finished_at': utcnow(), 'status': status, 'target': 'context', 'error': 'Snakemake traceback details'})


def timeout(work, folder):
    started = utcnow()
    call = work / 'audit/model_calls/first/requirements'
    request = prepare(work, 'requirements')
    write_json(call / 'call.json', {'status': 'TIMEOUT', 'at': utcnow(), 'timeout_seconds': 600, 'request_sha256': request['request_sha256']})
    write_json(work / 'stopped.json', {'status': 'ERROR', 'stage': 'requirements', 'at': utcnow(),
        'reason': 'Model request exceeded 600 seconds; no candidate accepted', 'failed_request_sha256': request['request_sha256']})
    stop_job(folder, 'STOPPED_ON_ERROR', started)


def revise(work, folder):
    started = utcnow()
    payload = prepare(work, 'requirements')['payload']
    proposal = [u for u in payload['source_units'] if u['source_id'] in payload['compression_scope']['source_ids']]
    requirements = demo.fixture_requirements({'/objective': QUOTE}, payload['source_units'], proposal[0]['source_id'])
    accept(work, 'requirements', {'request_sha256': prepare(work, 'requirements')['request_sha256'], 'requirements': requirements})
    review = demo.fixture_requirements_review(requirements, proposal)
    review.update(decision='REVISE', critical_errors=['R001 omits the unresolved permissions.'])
    review['items'][0]['verdict'] = 'MISSING'
    request = prepare(work, 'requirements_review')
    assert accept(work, 'requirements_review', {'request_sha256': request['request_sha256'], 'review': review})['status'] == 'REVISE'
    stop_job(folder, 'REVISION_REQUIRED', started)


def context_state(client, sid):
    return next(n['state'] for n in client.get(endpoint(sid)).json()['nodes'] if n['id'] == 'context')


def test_execution_retry_continues_the_same_run(job):
    client, canvas, sid, work, folder, resumed, launched = job
    timeout(work, folder)
    state = context_state(client, sid); assert state['can_retry_context']
    response = client.post(endpoint(sid, '/context-retries'), json={'failure_signature': state['failure']['signature'], 'confirmed': True})
    assert response.status_code == 202, response.text
    view = response.json()
    assert view['session_id'] == sid and not view['context_revision_child']
    assert resumed == [('same_run_job', 'context')] and not launched
    context = next(n['state'] for n in view['nodes'] if n['id'] == 'context')
    assert context['execution'] == 'RUNNING' and not context.get('failure') and not context['approved']
    assert {'attachment_plan', 'attachment_evidence'} <= set(load_run(work)[1]['accepted'])
    attempt = read_json(next((folder / 'context_attempts').glob('*.json')))
    assert attempt['mode'] == 'RETRY_EXECUTION' and attempt['previous']['failure']['code'] == 'MODEL_TIMEOUT'
    assert attempt['scientific_approval'] is False
    assert canvas.load(sid)['events'][-1]['action'] == 'CONTINUED_IN_SAME_RUN'


def test_extraction_repair_redoes_the_reviewed_stage_with_guidance(job):
    client, canvas, sid, work, folder, resumed, launched = job
    revise(work, folder)
    feedback = client.get(endpoint(sid, '/context-feedback')).json()
    response = client.post(endpoint(sid, '/context-revisions'), json={'feedback_signature': feedback['signature'],
        'mode': 'REPAIR_EXTRACTION', 'guidance': 'Keep the unresolved permissions.', 'submitted_by': 'Synthetic tester', 'confirmed': True})
    assert response.status_code == 202, response.text
    assert response.json()['session_id'] == sid and resumed == [('same_run_job', 'context')] and not launched
    accepted = load_run(work)[1]['accepted']
    assert 'requirements' not in accepted and {'attachment_plan', 'attachment_evidence'} <= set(accepted)
    payload = make_request(work, 'requirements')['payload']
    assert payload['previous_feedback']['decision'] == 'REVISE'
    assert payload['revision_guidance']['guidance'] == 'Keep the unresolved permissions.'
    assert read_json(next((folder / 'context_attempts').glob('*.json')))['stage'] == 'requirements'


def test_changed_code_falls_back_to_a_new_run(job):
    client, canvas, sid, work, folder, resumed, launched = job
    timeout(work, folder)
    plan = read_json(folder / 'plan.json'); plan['code_refs'][0]['sha256'] = '0' * 64; write_json(folder / 'plan.json', plan)
    state = context_state(client, sid)
    response = client.post(endpoint(sid, '/context-retries'), json={'failure_signature': state['failure']['signature'], 'confirmed': True})
    assert response.status_code == 202, response.text
    assert response.json()['session_id'] != sid and not resumed
    revision = launched[0][-1]
    assert revision['mode'] == 'RETRY_EXECUTION' and 'Changed or missing file' in revision['same_run_unavailable']


def test_vanished_worker_is_reported_and_its_run_can_continue(job):
    client, canvas, sid, work, folder, resumed, launched = job
    ended = subprocess.Popen([sys.executable, '-c', 'pass']); record = worker_record(ended); ended.wait()
    write_json(folder / 'worker.json', record)
    started = utcnow()
    write_json(folder / 'status.json', {'id': folder.name, 'created_at': started, 'started_at': started, 'status': 'RUNNING', 'target': 'context'})
    s = canvas.load(sid); s['nodes']['context'].update(execution='RUNNING', error=None); write_json(canvas.path(sid), s)
    state = context_state(client, sid)
    assert state['execution'] == 'FAILED' and state['failure']['code'] == 'WORKER_EXITED'
    assert state['failure']['proposal_change_required'] is False and state['can_retry_context']
    response = client.post(endpoint(sid, '/context-retries'), json={'failure_signature': state['failure']['signature'], 'confirmed': True})
    assert response.status_code == 202, response.text
    assert resumed == [('same_run_job', 'context')] and not launched


class FakeWorker:
    def __init__(self, *args, **kwargs): self.pid = os.getpid()
    def poll(self): return 0


@pytest.mark.parametrize('alive', [False, True])
def test_resume_unlocks_only_after_the_previous_worker_is_gone(tmp_path, monkeypatch, alive):
    app = create_workbench(tmp_path / 'runs', tmp_path / 'state'); client = TestClient(app)
    folder = app.state.canvas.state / 'workbench_jobs/plain_job'
    proposal = tmp_path / 'proposal.txt'; proposal.write_text(QUOTE, encoding='utf-8')
    from research_pipeline.common import sha256
    job_spec = {'id': 'plain_job', 'created_at': utcnow(), 'mode': 'fresh', 'stop_after': 'context', 'out': str(tmp_path / 'runs/plain_job'),
        'job_dir': str(folder), 'uploads': [{'path': str(proposal), 'name': 'proposal.txt', 'sha256': sha256(proposal)}]}
    write_json(folder / 'request.json', job_spec); make_plan(job_spec)
    if alive:
        record = worker_record(FakeWorker())
    else:
        ended = subprocess.Popen([sys.executable, '-c', 'pass']); record = worker_record(ended); ended.wait()
    write_json(folder / 'worker.json', record)
    write_json(folder / 'status.json', {'id': 'plain_job', 'created_at': utcnow(), 'status': 'RUNNING', 'target': 'context',
        'failure': {'code': 'OLD'}, 'control': {'disposition': 'OLD'}})
    monkeypatch.setattr('research_pipeline.workbench.subprocess.Popen', FakeWorker)
    response = client.post('/ui-api/jobs/plain_job/resume', json={'target': 'context'})
    if alive:
        assert response.status_code == 409 and not (folder / 'needs_unlock.flag').exists()
        return
    assert response.status_code == 202, response.text
    assert (folder / 'needs_unlock.flag').exists()
    status = read_json(folder / 'status.json')
    assert status['status'] == 'QUEUED' and 'failure' not in status and 'control' not in status
    assert read_json(folder / 'worker.json')['pid'] == os.getpid()


def test_a_review_that_cannot_be_reopened_falls_back_to_a_new_run(job, monkeypatch):
    client, canvas, sid, work, folder, resumed, launched = job
    revise(work, folder)
    def refuse(*args, **kwargs): raise ValueError('Review feedback no longer matches the stopped review')
    monkeypatch.setattr('ctxcomp.engine.reopen_for_revision', refuse)
    feedback = client.get(endpoint(sid, '/context-feedback')).json()
    response = client.post(endpoint(sid, '/context-revisions'), json={'feedback_signature': feedback['signature'],
        'mode': 'REPAIR_EXTRACTION', 'guidance': '', 'submitted_by': 'Synthetic tester', 'confirmed': True})
    assert response.status_code == 202, response.text
    assert response.json()['session_id'] != sid and not resumed
    assert launched[0][-1]['same_run_unavailable'] == 'Review feedback no longer matches the stopped review'
    assert not (folder / 'context_attempts').exists()


def test_a_stopped_run_lists_its_stages_and_reruns_one_with_a_fresh_call(job):
    client, canvas, sid, work, folder, resumed, launched = job
    revise(work, folder)
    listed = client.get(endpoint(sid, '/context-stages')).json()
    status = {r['stage']: r['status'] for r in listed['stages']}
    assert listed['can_rerun'] and status['attachment_plan'] == 'ACCEPTED' and status['requirements_review'] == 'STOPPED'
    response = client.post(endpoint(sid, '/context-stages/attachment_evidence/rerun'),
                           json={'submitted_by': 'Synthetic tester', 'confirmed': True})
    assert response.status_code == 202, response.text
    assert resumed == [('same_run_job', 'context')] and not launched
    accepted = load_run(work)[1]['accepted']
    assert 'attachment_plan' in accepted and 'attachment_evidence' not in accepted
    assert read_json(work / 'stage_control.json')['fresh'] == ['attachment_evidence']
    attempt = read_json(next((folder / 'context_attempts').glob('*.json')))
    assert attempt['mode'] == 'RERUN_STAGE' and attempt['stage'] == 'attachment_evidence'
    assert attempt['removed_acceptances'] == ['attachment_evidence'] and attempt['scientific_approval'] is False
    # While context runs, nothing else can be rerun.
    write_json(folder / 'status.json', {**read_json(folder / 'status.json'), 'status': 'RUNNING'})
    assert client.get(endpoint(sid, '/context-stages')).json()['can_rerun'] is False
    assert client.post(endpoint(sid, '/context-stages/requirements/rerun'),
                       json={'confirmed': True}).status_code == 409
    assert client.post(endpoint(sid, '/context-stages/unknown/rerun'), json={'confirmed': True}).status_code == 404
    # The context step ends at its review; the later pipeline stages are not listed or rerun here.
    assert [r['stage'] for r in listed['stages']][-1] == 'context_review'
    assert client.post(endpoint(sid, '/context-stages/pipeline/rerun'), json={'confirmed': True}).status_code == 404
    # The workbench page loads the step list and its buttons.
    assert '/assets/context-stages.js' in client.get('/').text
    js = client.get('/assets/context-stages.js').text
    assert '/context-stages' in js and 'data-rerun-stage' in js and '/rerun' in js


def test_the_compress_step_redoes_a_requested_stage_and_shares_answers(job, monkeypatch, tmp_path):
    from research_pipeline import workflow_runtime
    import ctxcomp.providers as providers
    client, canvas, sid, work, folder, resumed, launched = job
    seen = {}
    def fake_run_model(run, model=None, shared_cache=None, fresh=()):
        seen.update(run=run, shared_cache=shared_cache, fresh=fresh)
        raise RuntimeError('stop after recording the call')
    monkeypatch.setattr(providers, 'run_model', fake_run_model)
    write_json(work / 'stage_control.json', {'fresh': ['requirements']})
    monkeypatch.setenv('CTXCOMP_STAGE_CACHE', str(tmp_path / 'memory'))
    contract = {'kind': 'compress', 'options': {'work': str(work)}, 'outputs': [str(tmp_path / 'main.json')]}
    with pytest.raises(RuntimeError, match='stop after'):
        workflow_runtime.execute_builtin(contract)
    assert seen['fresh'] == ('requirements',) and seen['shared_cache'] == str(tmp_path / 'memory')
    assert not (work / 'stage_control.json').exists() and list(work.glob('stage_control.*.used.json'))
    monkeypatch.setenv('CTXCOMP_STAGE_CACHE', 'off')
    with pytest.raises(RuntimeError):
        workflow_runtime.execute_builtin(contract)
    assert seen['fresh'] == () and seen['shared_cache'] is None
