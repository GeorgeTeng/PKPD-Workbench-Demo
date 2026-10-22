"""Disabled EDA must never start a worker, including through old saved runs."""
import pytest
from research_pipeline.common import PipelineError, write_json
from research_pipeline.workflow_runtime import make_plan, execute_builtin
from test_workflow_canvas import canvas, node, url
from test_tributaries import setup, base


@pytest.mark.parametrize('execution', ['NOT_STARTED', 'FAILED', 'COMPLETED'])
def test_eda_cannot_start_or_retry_even_with_ready_dependencies(canvas, monkeypatch, execution):
    client, store, sid, calls, _ = canvas
    monkeypatch.setattr(store, 'dependency_for_step', lambda *args: True)
    session = store.load(sid)
    session['nodes']['eda']['execution'] = execution
    write_json(store.path(sid), session)
    response = client.get(url(sid)).json()
    definition = next(n for n in response['nodes'] if n['id'] == 'eda')
    assert definition['target'] is None
    assert definition['execution_adapter'] == 'DISABLED'
    assert not definition['state']['can_run']
    assert not definition['state']['can_retry_eda']
    assert 'disabled' in definition['state']['reason'].lower()
    assert client.post(url(sid, '/nodes/eda/start')).status_code == 409
    assert calls == []


def test_paused_eda_cannot_resume_a_worker(canvas):
    client, store, sid, calls, _ = canvas
    session = store.load(sid)
    session['control_status'] = 'PAUSED'
    session['nodes']['eda']['execution'] = 'PAUSED'
    write_json(store.path(sid), session)
    response = client.post(url(sid, '/continue'))
    assert response.status_code == 409
    assert 'disabled' in response.text.lower()
    assert calls == []


def test_supplemental_processing_does_not_launch_retired_eda(setup):
    client, store, sid, request = setup
    calls = []
    store.tributaries.launch = lambda *args: calls.append(args) or {'id': 'must_not_start'}
    branch = client.post(base(sid) + '/supplements', json=request).json()
    assert branch['can_start'] is False
    response = client.post(base(sid) + '/supplements/' + branch['id'] + '/start')
    assert response.status_code == 409
    assert 'disabled' in response.text.lower()
    assert calls == []


@pytest.mark.parametrize('mode', ['reviewed_preparation', 'supplemental'])
def test_old_workflow_modes_are_rejected_before_planning(tmp_path, mode):
    with pytest.raises(PipelineError) as exc:
        make_plan({'mode': mode, 'job_dir': str(tmp_path/'job'), 'out': str(tmp_path/'out')})
    assert exc.value.code == 'EDA_DISABLED'


def test_old_supplemental_eda_contract_is_not_executed():
    with pytest.raises(PipelineError) as exc:
        execute_builtin({'kind': 'supplemental_eda', 'options': {}, 'inputs': [], 'outputs': []})
    assert exc.value.code == 'EDA_DISABLED'
