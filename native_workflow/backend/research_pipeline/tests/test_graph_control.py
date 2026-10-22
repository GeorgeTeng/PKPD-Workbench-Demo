"""Real checkpoint/restart and owned-process tests; synthetic inputs only."""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
import psutil
import pytest
from research_pipeline.common import read_json, write_json
from research_pipeline.graph_control import ReviewController
from research_pipeline.graph_execution import run_controlled
from research_pipeline.job_control import PauseRequested, run_interruptible


def test_persistent_interrupt_survives_controller_restart_and_exports(tmp_path):
    receipt = ReviewController(tmp_path).begin('test_session', 'eda', 'hash', [{'name': 'synthetic.svg'}])
    assert receipt['status'] == 'INTERRUPTED'
    controller = ReviewController(tmp_path)
    with pytest.raises(ValueError, match='signature'):
        controller.resume(receipt, {'output_signature': 'wrong', 'decision': 'APPROVE', 'reviewer': 'test', 'confirmed': True})
    accepted = controller.resume(receipt, {'output_signature': 'hash', 'decision': 'APPROVE', 'reviewer': 'test', 'confirmed': True})
    assert accepted['status'] == 'APPROVED'
    history = controller.export_history(accepted)
    assert history[0]['values']['disposition'] == 'APPROVED'
    assert any(s['interrupts'] for s in history)
    json.dumps(history)


@pytest.mark.parametrize('runtime,expected', [
    ({'status': 'WAITING_FOR_HUMAN_REVIEW'}, 'HUMAN_SCIENTIFIC_REVIEW'),
    ({'status': 'PAUSED'}, 'PAUSED'),
    ({'status': 'STOPPED_ON_ERROR', 'error': 'synthetic failure'}, 'ENGINEERING_FAILURE')])
def test_execution_controller_records_minimal_scope_and_never_accepts_science(tmp_path, runtime, expected):
    spec = {'id': 'test', 'job_dir': str(tmp_path), 'out': str(tmp_path / 'run'),
            'uploads': [{'name': 'synthetic.csv', 'sha256': 'datahash'}]}
    request = write_json(tmp_path / 'request.json', spec)
    write_json(tmp_path / 'run/data_preparation/main.json', {'fit_ready': False, 'cleaning_complete': False})
    called = []
    def runner(path, **kw): called.append((path, kw)); return runtime
    result = run_controlled(request, 'data_preparation', prefect_runner=runner)
    assert called[0][1]['target'] == 'data_preparation'
    assert result['control']['disposition'] == expected
    assert not result['control']['diagnostics']['scientific_accepted']
    assert result['control']['diagnostics']['reported_findings'][0]['reported_fields']['fit_ready'] is False
    assert list(tmp_path.glob('control_traces/*.json')) and (tmp_path / 'langgraph.sqlite').is_file()


def test_invalid_diagnostics_stops_instead_of_passing(tmp_path):
    request = write_json(tmp_path / 'request.json', {'id': 'test', 'job_dir': str(tmp_path), 'out': str(tmp_path)})
    (tmp_path / 'main.json').write_text('broken JSON', encoding='utf-8')
    result = run_controlled(request, 'intake', prefect_runner=lambda *a, **kw: {'status': 'WAITING_FOR_HUMAN_REVIEW'})
    assert result['status'] == 'STOPPED_ON_ERROR'
    assert 'Invalid structured diagnostics' in result['error']


def test_pause_stops_owned_process_tree_and_preserves_completed_receipt(tmp_path):
    record, pause, child_record = tmp_path / 'process.json', tmp_path / 'pause.flag', tmp_path / 'child.pid'
    receipt = write_json(tmp_path / 'completed.json', {'status': 'SUCCEEDED', 'synthetic': True})
    script = tmp_path / 'synthetic_wait.py'
    script.write_text("import sys,subprocess,time\nfrom pathlib import Path\np=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])\nPath(sys.argv[1]).write_text(str(p.pid))\ntime.sleep(30)\n", encoding='utf-8')
    errors = []
    def work():
        try:
            with (tmp_path / 'log.txt').open('w') as output:
                run_interruptible([sys.executable, str(script), str(child_record)], pause_file=pause,
                                  stdout=output, cwd=tmp_path, process_record=record)
        except BaseException as exc: errors.append(exc)
    thread = threading.Thread(target=work); thread.start()
    deadline = time.monotonic() + 10
    try:
        while not child_record.exists() and time.monotonic() < deadline: time.sleep(.05)
        assert child_record.exists()
        pause.touch(); thread.join(10)
        assert not thread.is_alive()
        assert len(errors) == 1 and isinstance(errors[0], PauseRequested)
        assert not psutil.pid_exists(read_json(record)['pid'])
        assert not psutil.pid_exists(int(child_record.read_text()))
        assert read_json(receipt)['status'] == 'SUCCEEDED'
    finally:
        pause.touch(); thread.join(10)
