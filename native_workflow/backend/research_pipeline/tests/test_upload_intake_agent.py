"""Exercise the first upload agent and its downstream gate with real file parsing."""
import io
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from ctxcomp.io import digest
from ctxcomp.rules import load_rules, intake_agent_contract
from ctxcomp.intake import verify_intake
from research_pipeline.common import read_json, write_json
from research_pipeline.attachments import store_upload
from research_pipeline.execution_feedback import execution_feedback
from research_pipeline.workflow_runtime import make_plan, execute_contract
from research_pipeline.workbench import create_workbench
from test_orchestration import fresh_spec


def test_cc013_runs_in_first_intake_contract_without_a_model_call(tmp_path, monkeypatch):
    def forbidden_model(*args, **kwargs):
        pytest.fail('The upload check must execute file reads before any LLM call')
    monkeypatch.setattr('ctxcomp.providers.codex_generate', forbidden_model)
    spec = fresh_spec(tmp_path)
    plan = make_plan(spec)
    c = read_json(plan['steps']['intake']['contract'])
    agent = c['agent_contract']
    assert agent['stage'] == 'intake'
    assert agent['executor'] == 'DETERMINISTIC_FILE_READER'
    assert [r['id'] for r in agent['processing_rules']['rules']] == [f'IN{i:03}' for i in range(1, 9)]
    assert agent['governance']['rules'][0]['id'] == 'G001'
    assert 'CC013' not in [r['id'] for r in load_rules()['rules']]
    execute_contract(plan['steps']['intake']['contract'])
    root = Path(spec['out']) / 'context_work'
    assert read_json(root / 'intake/agent_contract.json') == agent
    report = read_json(root / 'intake/readability_report.json')
    assert report['status'] == 'PASS' and not report['scientific_release']
    assert read_json(Path(spec['job_dir']) / 'receipts/intake.json')['status'] == 'SUCCEEDED'
    assert report['agent_contract_sha256'] == digest(agent)
    assert all(f['read_status'] == 'READ_COMPLETE' for f in report['files'])
    assert all(not f['fit_ready'] and f['qc_status'] == 'NOT_RUN' for f in report['files'])
    assert read_json(root / 'state.json')['accepted'] == {}
    assert plan['steps']['compress']['depends'] == ['intake']


@pytest.mark.parametrize('archive', [False, True])
def test_bad_upload_stops_first_agent_and_blocks_compression(tmp_path, monkeypatch, archive):
    from pathlib import Path
    import zipfile
    def forbidden_model(*args, **kwargs):
        pytest.fail('No model call is allowed after a failed upload check')
    monkeypatch.setattr('ctxcomp.providers.codex_generate', forbidden_model)
    spec = fresh_spec(tmp_path)
    Path(spec['uploads'][1]['path']).write_bytes(b'\xff\xfeinvalid UTF-8')
    if archive:
        package = tmp_path / 'package.zip'
        with zipfile.ZipFile(package, 'w') as z:
            for f in spec['uploads']:
                z.write(f['path'], f['name'])
        spec['uploads'] = [{'path': str(package), 'name': package.name}]
    plan = make_plan(spec)
    with pytest.raises(ValueError, match='CC013.*new_data.csv'):
        execute_contract(plan['steps']['intake']['contract'])
    assert not (Path(spec['job_dir']) / 'receipts/intake.json').exists()
    with pytest.raises(RuntimeError, match='Another block failed'):
        execute_contract(plan['steps']['compress']['contract'])
    feedback = execution_feedback(spec['out'], 'Snakemake stopped: Traceback', stage='intake')
    assert feedback['code'] == 'UPLOAD_READ_FAILED'
    assert 'new_data.csv' in feedback['summary']
    assert feedback['stage_label'] == 'Check uploaded files'
    assert feedback['proposal_change_required'] is False
    assert 'upload' in ' '.join(feedback['suggested_actions']).lower()
    assert feedback['evidence_refs'] and feedback['scientific_release'] is False


def test_transport_success_is_not_a_readability_pass(tmp_path):
    upload = store_upload(tmp_path, io.BytesIO(b'{invalid json'), 'candidate.json')
    assert upload['readability_status'] == 'PENDING_INTAKE'
    assert upload['fit_ready'] is False


@pytest.mark.parametrize('name', ['agent_contract.json', 'readability_report.json'])
def test_changed_intake_audit_cannot_release_compression(tmp_path, name):
    spec = fresh_spec(tmp_path)
    plan = make_plan(spec)
    execute_contract(plan['steps']['intake']['contract'])
    root = Path(spec['out']) / 'context_work/intake'
    write_json(root / name, {'tampered': True})
    with pytest.raises(ValueError, match='Intake audit changed'):
        verify_intake(root / 'manifest.json')
    with pytest.raises(ValueError, match='Changed or missing file'):
        execute_contract(plan['steps']['compress']['contract'])


def test_standalone_upload_contract_matches_the_actual_first_agent():
    from research_pipeline.common import BACKEND, PROJECT
    contract = intake_agent_contract()
    assert read_json(BACKEND / 'research_pipeline/docs/interfaces/file_intake.runtime.json') == contract


def test_first_step_exposes_downloadable_contract_and_readability_report(tmp_path):
    from pathlib import Path
    app = create_workbench(tmp_path / 'outputs', tmp_path / 'state')
    client = TestClient(app)
    created = client.post('/ui-api/workflow/sessions').json()
    sid = created['session_id']
    store = app.state.canvas
    spec = fresh_spec(tmp_path)
    spec['out'] = str(tmp_path / 'outputs/run')
    spec['job_dir'] = str(store.state / 'workbench_jobs/check_upload')
    write_json(Path(spec['job_dir']) / 'request.json', spec)
    plan = make_plan(spec)
    execute_contract(plan['steps']['intake']['contract'])
    s = store.load(sid)
    s['job_id'] = 'check_upload'
    store.collect_outputs(s, 'intake')
    write_json(store.path(sid), s)
    for name in ['agent_contract.json', 'readability_report.json']:
        response = client.get(f'/ui-api/workflow/sessions/{sid}/nodes/intake/artifacts/{name}')
        assert response.status_code == 200, response.text
    view = client.get(f'/ui-api/workflow/sessions/{sid}').json()
    assert next(n['state'] for n in view['nodes'] if n['id'] == 'context')['can_run']
