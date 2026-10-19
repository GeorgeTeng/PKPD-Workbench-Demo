"""Compression-only integration; synthetic files and no live model calls."""
import io
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
from research_pipeline.attachments import store_upload
from research_pipeline.common import read_json, sha256
from research_pipeline.workbench import create_workbench
from research_pipeline.workflow_runtime import make_plan, context_requires_project_rules


def test_new_workbench_job_explicitly_selects_lean_compression(tmp_path, monkeypatch):
    import research_pipeline.workbench as module
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *a, **k: SimpleNamespace(poll=lambda: 0))
    state = tmp_path / 'state'
    client = TestClient(create_workbench(tmp_path / 'outputs', state))
    upload = store_upload(state, io.BytesIO(b'Preserve the original study conditions.'), 'proposal.txt')
    response = client.post('/ui-api/jobs', json={'upload_ids': [upload['upload_id']], 'proposal_entry': 'proposal.txt', 'stop_after': 'context'})
    assert response.status_code == 202, response.text
    spec = read_json(state / 'workbench_jobs' / response.json()['id'] / 'request.json')
    assert spec['compression_profile'] == 'LEAN_1.0'


def test_lean_context_target_stops_before_project_rules(tmp_path):
    source = tmp_path / 'proposal.txt'
    source.write_text('Preserve source conditions.', encoding='utf-8')
    spec = {'id': 'lean_plan', 'mode': 'fresh', 'out': str(tmp_path / 'run'),
            'job_dir': str(tmp_path / 'job'), 'compression_profile': 'LEAN_1.0',
            'uploads': [{'path': str(source), 'name': source.name, 'sha256': sha256(source)}],
            'proposal_entry': source.name, 'reference_only': []}
    plan = make_plan(spec)
    assert plan['targets']['context'] == 'compress'
    assert plan['targets']['project_rules'] == 'project_rules_publish'
    assert not context_requires_project_rules(spec)
    intake = read_json(plan['steps']['intake']['contract'])
    assert intake['options']['compression_profile'] == 'LEAN_1.0'
    from research_pipeline.workflow_runtime import execute_contract
    from ctxcomp.engine import load_run, active_stages
    execute_contract(plan['steps']['intake']['contract'])
    bundle, _ = load_run(Path(spec['out']) / 'context_work')
    assert active_stages(bundle) == ('context', 'context_review')
    assert bundle['compression_profile']['wall_budget_seconds'] is None


def test_unprofiled_plan_keeps_historical_context_target(tmp_path):
    source = tmp_path / 'proposal.txt'
    source.write_text('Preserve historical contracts.', encoding='utf-8')
    spec = {'id': 'historical_plan', 'mode': 'fresh', 'out': str(tmp_path / 'run'),
            'job_dir': str(tmp_path / 'job'),
            'uploads': [{'path': str(source), 'name': source.name, 'sha256': sha256(source)}]}
    assert make_plan(spec)['targets']['context'] == 'project_rules_publish'


def test_lean_stage_controls_do_not_offer_unsupported_resampling(tmp_path):
    from ctxcomp.engine import init_run
    from research_pipeline.common import write_json, utcnow
    source = tmp_path / 'proposal.txt'
    source.write_text('Freeze predictions before validation.', encoding='utf-8')
    app = create_workbench(tmp_path / 'outputs', tmp_path / 'state')
    canvas = app.state.canvas
    sid = canvas.create()['session_id']
    run = canvas.outputs / 'lean_stop'
    init_run(run / 'context_work', proposal=source, compression_profile='LEAN_1.0')
    folder = canvas.state / 'workbench_jobs/lean_stop'
    write_json(folder / 'request.json', {'out': str(run)})
    write_json(folder / 'status.json', {'id': 'lean_stop', 'status': 'REVISION_REQUIRED', 'created_at': utcnow()})
    session = canvas.load(sid)
    session['job_id'] = 'lean_stop'
    write_json(canvas.path(sid), session)
    client = TestClient(app)
    url = '/ui-api/workflow/sessions/' + sid + '/context-stages'
    result = client.get(url)
    assert result.status_code == 200, result.text
    assert [x['stage'] for x in result.json()['stages']] == ['context', 'context_review']
    assert not result.json()['can_rerun']
    assert client.post(url + '/context_review/rerun', json={'confirmed': True}).status_code == 409
