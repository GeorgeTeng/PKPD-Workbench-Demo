"""Synthetic revision attempts only: no live model calls or research approvals."""
import io
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from ctxcomp.engine import init_run, load_run, make_request, prepare, accept
from research_pipeline.common import read_json, write_json, sha256, utcnow
from research_pipeline.context_feedback import context_feedback
from research_pipeline.workbench import create_workbench
from research_pipeline.attachments import store_upload
from research_pipeline.workflow_runtime import make_plan, execute_contract
from research_pipeline.graph_execution import run_controlled


@pytest.fixture
def stopped(tmp_path):
    app = create_workbench(tmp_path / 'runs', tmp_path / 'state')
    canvas = app.state.canvas
    client = TestClient(app)
    sid = canvas.create()['session_id']
    run = canvas.outputs / 'synthetic_stop'
    proposal = tmp_path / 'proposal.txt'; proposal.write_text('Freeze targets and MIC input. Keep unresolved permissions explicit.', encoding='utf-8')
    data = tmp_path / 'data.csv'; data.write_text('time,concentration\n1,2\n', encoding='utf-8')
    benchmark = tmp_path / 'benchmark_reference.json'; benchmark.write_text('opaque held-out benchmark', encoding='utf-8')
    init_run(run / 'context_work', attachments=[proposal, data, benchmark], proposal_entry=proposal.name, opaque_references=True)
    work = run / 'context_work'
    write_json(work / 'critical_requirements.json', {'items': [{'id': 'R001', 'components': []}]})
    review = {'decision': 'REVISE', 'items': [{'requirement_id': 'R001', 'verdict': 'MISSING', 'reason': 'MIC input freeze omitted.'}],
        'critical_errors': ['The inventory omits the MIC input freeze.'], 'source_units': []}
    write_json(work / 'submissions/review.json', {'review': review})
    started = utcnow()
    write_json(work / 'stopped.json', {'status': 'REVISE', 'stage': 'requirements_review', 'at': utcnow(), 'response': 'submissions/review.json'})
    folder = canvas.state / 'workbench_jobs' / 'synthetic_stop'
    spec = {'id': 'synthetic_stop', 'created_at': started, 'job_dir': str(folder), 'out': str(run), 'mode': 'fresh'}
    write_json(folder / 'request.json', spec)
    write_json(folder / 'status.json', {'id': 'synthetic_stop', 'created_at': started, 'started_at': started,
        'finished_at': utcnow(), 'status': 'STOPPED_ON_ERROR', 'error': 'Snakemake traceback details'})
    s = canvas.load(sid); s['job_id'] = 'synthetic_stop'
    canvas.collect_outputs(s, 'intake')
    s['nodes']['context'].update(execution='FAILED', error='Snakemake traceback details')
    write_json(canvas.path(sid), s)
    calls = []
    def launch(uploads, proposal_entry, reference_only, model, revision):
        jid = 'synthetic_revision'; job = canvas.state / 'workbench_jobs' / jid
        next_spec = {'id': jid, 'created_at': utcnow(), 'job_dir': str(job), 'out': str(canvas.outputs / jid),
            'mode': 'fresh', 'stop_after': 'context', 'proposal_entry': proposal_entry, 'reference_only': reference_only,
            'context_revision': revision,
            'uploads': [{'name': u['name'], 'path': str(canvas.state / 'uploads' / u['upload_id'] / read_json(canvas.state / 'uploads' / u['upload_id'] / 'metadata.json')['stored_name']),
                         'sha256': u['sha256']} for u in uploads]}
        write_json(job / 'request.json', next_spec)
        write_json(job / 'status.json', {'id': jid, 'created_at': utcnow(), 'status': 'RUNNING'})
        calls.append(next_spec)
        return {'id': jid}
    canvas.context_revisions.launch = launch
    return client, canvas, sid, work, calls


def endpoint(sid, suffix=''):
    return '/ui-api/workflow/sessions/' + sid + suffix


def request_for(client, sid, **extra):
    feedback = client.get(endpoint(sid, '/context-feedback')).json()
    return {'feedback_signature': feedback['signature'], 'mode': 'REPAIR_EXTRACTION',
        'submitted_by': 'Synthetic tester', 'confirmed': True, **extra}


def test_semantic_stop_is_readable_and_not_approvable(stopped):
    client, _, sid, _, _ = stopped
    view = client.get(endpoint(sid)).json()
    node = next(n['state'] for n in view['nodes'] if n['id'] == 'context')
    assert node['execution'] == 'REVISION_REQUIRED'
    assert node['can_revise_context'] and not node['can_review']
    assert 'Snakemake' not in node['error']
    assert node['technical_error'] == 'Snakemake traceback details'
    issue = node['context_feedback']['issues'][0]
    assert issue['category'] == 'EXTRACTION_OMISSION' and issue['requirement_ids'] == ['R001']
    assert client.post(endpoint(sid, '/nodes/context/review'), json={'decision':'APPROVE','reviewer':'test',
        'confirmed':True,'output_signature':'anything'}).status_code == 409


def test_retry_copies_sources_preserves_history_and_passes_feedback_to_model(stopped):
    client, canvas, sid, work, calls = stopped
    original = {str(p): sha256(p) for p in work.rglob('*') if p.is_file()}
    response = client.post(endpoint(sid, '/context-revisions'), json=request_for(client, sid, guidance='Restore the MIC freeze.'))
    assert response.status_code == 202, response.text
    child = response.json(); assert child['session_id'] != sid
    assert all(not n['state']['approved'] for n in child['nodes'])
    spec = calls[0]; plan = make_plan(spec)
    execute_contract(plan['steps']['intake']['contract'])
    new_work = Path(spec['out']) / 'context_work'
    bundle, _ = load_run(new_work)
    assert bundle['budget'] == {'content_words': None, 'compact_characters': None}
    assert bundle['revision']['guidance'] == 'Restore the MIC freeze.'
    # Explicit authored search responses exercise the new prelude without a live model.
    for stage, field in [('attachment_plan','questions'),('attachment_evidence','answers')]:
        request=prepare(new_work,stage)
        accept(new_work,stage,{'request_sha256':request['request_sha256'],field:[]})
    payload = make_request(new_work, 'requirements')['payload']
    assert payload['revision']['prior_review']['decision'] == 'REVISE'
    assert len(payload['sources']) == 1
    assert 'opaque held-out benchmark' not in str(payload)
    assert not (Path(spec['out']) / 'B1/main.json').exists()
    updated = client.get(endpoint(child['session_id'])).json()
    assert next(n['state'] for n in updated['nodes'] if n['id'] == 'intake')['approved']
    assert original == {str(p): sha256(p) for p in work.rglob('*') if p.is_file()}
    assert client.post(endpoint(sid, '/context-revisions'), json=request_for(client, sid)).status_code == 409


def test_replacement_proposal_is_explicit_and_other_files_are_unchanged(stopped):
    client, canvas, sid, work, calls = stopped
    upload = store_upload(canvas.state, io.BytesIO(b'Revised scientific proposal: freeze targets and MIC input.'), 'updated.txt')
    request = request_for(client, sid, mode='REPLACE_PROPOSAL', proposal_upload_id=upload['upload_id'])
    response = client.post(endpoint(sid, '/context-revisions'), json=request)
    assert response.status_code == 202, response.text
    spec = calls[0]; plan = make_plan(spec); execute_contract(plan['steps']['intake']['contract'])
    bundle, _ = load_run(Path(spec['out']) / 'context_work')
    assert 'Revised scientific proposal' in str(bundle['sources'])
    old = read_json(work / 'intake/manifest.json')['files']
    new = read_json(Path(spec['out']) / 'context_work/intake/manifest.json')['files']
    assert {i['original_name']:i['sha256'] for i in old if i['original_name'] != 'proposal.txt'} == {
        i['original_name']:i['sha256'] for i in new if i['original_name'] != 'proposal.txt'}


@pytest.mark.parametrize('overrides,code', [({'feedback_signature':'stale'},409), ({'mode':'REPLACE_PROPOSAL'},422),
    ({'submitted_by':' '},422), ({'confirmed':False},422)])
def test_invalid_revision_is_not_launched(stopped, overrides, code):
    client, _, sid, _, calls = stopped
    assert client.post(endpoint(sid, '/context-revisions'), json=request_for(client,sid,**overrides)).status_code == code
    assert calls == []


def test_original_source_tampering_stops_revision(stopped):
    client, _, sid, work, calls = stopped
    request = request_for(client, sid)
    manifest = read_json(work / 'intake/manifest.json')
    (work / 'intake' / manifest['files'][0]['raw_path']).write_text('changed', encoding='utf-8')
    assert client.post(endpoint(sid, '/context-revisions'), json=request).status_code in {409,422}
    assert not calls


def test_stale_semantic_stop_does_not_hide_later_engineering_failure(stopped):
    client, _, sid, work, _ = stopped
    assert context_feedback(work.parent, '2099-01-01T00:00:00+00:00') is None
    write_json(work / 'stopped.json', {'status':'ERROR', 'reason':'Provider disconnected'})
    assert context_feedback(work.parent) is None
    assert client.get(endpoint(sid, '/context-feedback')).status_code == 409
    view = client.get(endpoint(sid)).json()
    context = next(n['state'] for n in view['nodes'] if n['id'] == 'context')
    assert context['execution'] == 'FAILED' and not context['can_revise_context']


def test_langgraph_keeps_revision_separate_from_engineering_failure(stopped):
    _, canvas, _, work, _ = stopped
    folder = canvas.state / 'workbench_jobs/synthetic_stop'
    feedback = context_feedback(work.parent)
    result = run_controlled(folder / 'request.json', target='context', prefect_runner=lambda *a,**k: {
        'status':'REVISION_REQUIRED','context_feedback':feedback})
    assert result['control']['disposition'] == 'CONTEXT_REVISION_REQUIRED'
    assert result['status'] == 'REVISION_REQUIRED'
    assert result['control']['diagnostics']['scientific_accepted'] is False
    assert result['control']['diagnostics']['reported_findings'][0]['decision'] == 'REVISE'


def test_semantic_stop_writes_revision_attempt_without_success_receipt(stopped, monkeypatch):
    from research_pipeline.context_feedback import ContextRevisionRequired
    client, canvas, sid, _, calls = stopped
    client.post(endpoint(sid, '/context-revisions'), json=request_for(client, sid))
    spec = calls[0]; plan = make_plan(spec)
    execute_contract(plan['steps']['intake']['contract'])
    def reject(work, **kwargs):
        write_json(work / 'submissions/review.json', {'review': {'decision':'REVISE', 'critical_errors':['Required content is missing.']}})
        write_json(work / 'stopped.json', {'status':'REVISE','stage':'requirements_review','at':utcnow(),'response':'submissions/review.json'})
        return {'status':'REVISE'}
    monkeypatch.setattr('ctxcomp.providers.run_model', reject)
    with pytest.raises(ContextRevisionRequired): execute_contract(plan['steps']['compress']['contract'])
    job = Path(spec['job_dir'])
    assert not (job / 'receipts/compress.json').exists()
    assert not (Path(spec['out']) / 'B1/main.json').exists()
    record = read_json(next((job / 'attempts/compress').glob('*/execution.json')))
    assert record['status'] == 'REVISION_REQUIRED'


def test_prefect_classifies_review_and_keeps_technical_error(stopped, monkeypatch):
    from types import SimpleNamespace
    import research_pipeline.orchestration as module
    _, canvas, _, work, _ = stopped
    monkeypatch.setattr(module, 'flow_run', SimpleNamespace(id='synthetic-flow'))
    def stop(*args):
        current = read_json(work / 'stopped.json'); current['at'] = utcnow(); write_json(work / 'stopped.json', current)
        raise RuntimeError('synthetic Snakemake exit 1')
    monkeypatch.setattr(module, 'run_dag', stop)
    status = module.research_flow.fn(canvas.state / 'workbench_jobs/synthetic_stop/request.json', target='context')
    assert status['status'] == 'REVISION_REQUIRED'
    assert status['technical_error'] == 'synthetic Snakemake exit 1'
    assert not status['scientific_release']


def test_browser_revision_form(stopped, tmp_path):
    """Real HTTP + Edge, isolated synthetic launcher; no model invocation."""
    import os
    import socket
    import subprocess
    import threading
    import uvicorn
    from research_pipeline.common import BACKEND, PROJECT
    client, _, sid, _, calls = stopped
    node = Path('C:/Users/georg/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')
    if not node.is_file(): pytest.skip('Bundled browser test runtime unavailable')
    sock = socket.socket(); sock.bind(('127.0.0.1', 0)); sock.listen()
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(client.app, log_level='error'))
    thread = threading.Thread(target=server.run, kwargs={'sockets':[sock]}, daemon=True); thread.start()
    try:
        env = {**os.environ, 'CANVAS_URL': f'http://127.0.0.1:{port}', 'CONTEXT_SESSION': sid,
               'CONTEXT_CHECK_OUT': str(PROJECT / 'outputs/Context_Revision_Check')}
        result = subprocess.run([str(node), str(BACKEND / 'research_pipeline/scripts/check_context_revision.mjs')],
            capture_output=True, text=True, encoding='utf-8', env=env, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        assert len(calls) == 1
        assert calls[0]['context_revision']['guidance'] == 'Synthetic extraction repair only.'
    finally:
        server.should_exit = True; thread.join(timeout=10); sock.close()
