import json
import subprocess
import sys
from pathlib import Path
import pytest
from ctxcomp.providers import monitored_run, codex_generate, ModelProviderError
from ctxcomp.io import read_json, write_json
import threading
import time
from concurrent.futures import ThreadPoolExecutor


def test_input_size_rejection_is_not_reported_as_login_failure(monkeypatch,tmp_path):
    monkeypatch.setattr('ctxcomp.providers.shutil.which',lambda _: 'codex.exe')
    monkeypatch.setattr('ctxcomp.providers.monitored_run',lambda *a,**k:
        subprocess.CompletedProcess(a[0],1,'','Input exceeds the maximum length of 1048576 characters. input_too_large'))
    with pytest.raises(ModelProviderError) as caught:
        codex_generate({'request_sha256':'synthetic','payload':{'schema':{'type':'object'}}},diagnostics_dir=tmp_path)
    assert caught.value.code=='MODEL_INPUT_TOO_LARGE'
    assert 'login' not in str(caught.value).lower()


def wait_for(path, predicate, timeout=8):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        try:
            value=read_json(path)
            if predicate(value): return value
        except (OSError,ValueError): pass
        time.sleep(.02)
    raise AssertionError('Expected live telemetry was not observed')


def test_events_are_saved_live_and_output_completion_is_separate_from_exit(tmp_path):
    program='''import json,sys,time
sys.stdin.read()
print(json.dumps({'type':'turn.started'}),flush=True)
time.sleep(.7)
print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':'synthetic'}}),flush=True)
time.sleep(.7)
print(json.dumps({'type':'turn.completed','usage':{'output_tokens':3}}),flush=True)
time.sleep(.7)
'''
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(monitored_run,[sys.executable,'-u','-c',program],'',tmp_path,tmp_path)
        first=wait_for(tmp_path/'progress.json',lambda x:x['last_event_type']=='turn.started')
        assert first['first_event_at'] and first['first_response_at'] is None
        assert 'turn.started' in (tmp_path/'events.jsonl').read_text(encoding='utf-8')
        output=wait_for(tmp_path/'progress.json',lambda x:x['phase']=='MODEL_OUTPUT_RECEIVED_WAITING_TURN_END')
        assert output['first_response_at']==output['model_output_completed_at']
        assert output['cli_process_exited_at'] is None and not future.done()
        turn=wait_for(tmp_path/'progress.json',lambda x:x['phase']=='MODEL_TURN_COMPLETE_WAITING_CLI_EXIT')
        assert turn['model_turn_completed_at'] and turn['process_alive'] and not future.done()
        assert future.result().returncode==0
    final=read_json(tmp_path/'progress.json')
    assert final['cli_process_exited_at'] >= final['model_turn_completed_at']
    timeline=[json.loads(x) for x in (tmp_path/'event_timeline.jsonl').read_text(encoding='utf-8').splitlines()]
    assert [x['type'] for x in timeline]==['turn.started','item.completed','turn.completed']
    assert timeline[0]['elapsed_seconds']<timeline[1]['elapsed_seconds']<timeline[2]['elapsed_seconds']


def test_live_logs_redact_secrets_and_handle_unknown_events(tmp_path):
    program='''import json,sys,time
print(json.dumps({'type':'error','message':'reconnect Bearer fake_secret'}),flush=True)
print('api_key=sk-testsecret',file=sys.stderr,flush=True)
print('not-json',flush=True)
print('[]',flush=True)
print(json.dumps({'type':'custom.event'}),flush=True)
time.sleep(.6)
'''
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(monitored_run,[sys.executable,'-u','-c',program],'',tmp_path,tmp_path)
        value=wait_for(tmp_path/'progress.json',lambda x:x['model_event_count']==4)
        for name in ['events.jsonl','stderr.log','event_timeline.jsonl','progress.json']:
            text=(tmp_path/name).read_text(encoding='utf-8')
            assert 'fake_secret' not in text and 'sk-testsecret' not in text
        assert value['event_types']['UNPARSED_STDOUT']==2
        assert 'reconnect' in value['last_transport_or_model_error']['message']
        future.result()


def test_peer_failure_cancellation_stops_process_and_records_exit(tmp_path):
    cancel=threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(monitored_run,[sys.executable,'-u','-c','import time; time.sleep(30)'],'',tmp_path,tmp_path,None,300,cancel)
        wait_for(tmp_path/'progress.json',lambda x:x['process_alive'])
        cancel.set()
        with pytest.raises(ModelProviderError,match='Model call cancelled'): future.result(timeout=8)
    value=read_json(tmp_path/'progress.json')
    assert value['status']=='CANCELLED' and value['cli_process_exited_at'] and not value['process_alive']


def test_live_monitor_reports_local_liveness_without_remote_progress_claim(tmp_path):
    command=[sys.executable,'-u','-c', 'import sys,time; sys.stdin.read(); print("{\\"type\\":\\"turn.started\\"}",flush=True); time.sleep(0.55)']
    result=monitored_run(command,'synthetic',tmp_path,tmp_path,heartbeat_seconds=.1)
    assert result.returncode==0
    progress=read_json(tmp_path/'progress.json')
    assert progress['status']=='RETURNED' and not progress['process_alive']
    assert progress['timeout_seconds'] is None and progress['model_event_count']==1
    assert progress['remote_progress_verified'] is False
    history=[json.loads(s) for s in (tmp_path/'heartbeats.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(history)>=2 and all(h['process_alive'] for h in history)
    assert all('unverified' in h['message'] for h in history)


def test_explicit_short_test_deadline_stops_child_and_keeps_diagnostics(tmp_path):
    with pytest.raises(subprocess.TimeoutExpired):
        monitored_run([sys.executable,'-u','-c','import time; time.sleep(10)'],'',tmp_path,tmp_path,timeout=.1,heartbeat_seconds=.05)
    progress=read_json(tmp_path/'progress.json')
    assert progress['status']=='TIMEOUT' and not progress['process_alive']


def test_default_deadline_removed_and_heartbeat_interval_is_five_minutes():
    import inspect
    assert inspect.signature(codex_generate).parameters['timeout'].default is None
    assert inspect.signature(monitored_run).parameters['heartbeat_seconds'].default == 300


def test_missing_cli_is_typed_and_does_not_generate_a_candidate(monkeypatch):
    monkeypatch.setattr('ctxcomp.providers.shutil.which',lambda _:None)
    with pytest.raises(ModelProviderError) as error: codex_generate({})
    assert error.value.code=='MODEL_CLI_UNAVAILABLE'


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows tree-termination fallback')
def test_taskkill_failure_uses_owned_handle_and_reports_tree_limit(tmp_path, monkeypatch):
    monkeypatch.setattr('ctxcomp.providers.subprocess.run',
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, b'', b'Access denied'))
    cancel = threading.Event(); cancel.set()
    started = time.monotonic()
    with pytest.raises(ModelProviderError, match='Model call cancelled'):
        monitored_run([sys.executable,'-c','import time; time.sleep(15)'], '', tmp_path,
                      tmp_path, cancel_event=cancel)
    assert time.monotonic()-started < 8
    result = read_json(tmp_path/'progress.json')
    assert not result['process_alive']
    assert result['termination']['method'] == 'OWNED_PROCESS_HANDLE'
    assert result['termination']['descendants_status'] == 'NOT_VERIFIED'


def test_transient_progress_conflicts_keep_the_same_child_running(tmp_path, monkeypatch):
    from ctxcomp import io
    original = io.os.replace
    failures = []
    def conflict(source, target):
        if Path(target).name == 'progress.json' and len(failures) < 2:
            failures.append(str(target))
            exc = PermissionError(13, 'Synthetic sharing conflict'); exc.winerror = 32
            raise exc
        return original(source, target)
    monkeypatch.setattr(io.os, 'replace', conflict)
    result = monitored_run([sys.executable, '-u', '-c',
        'import sys,time; sys.stdin.read(); print("completed",flush=True); time.sleep(.1)'], '', tmp_path, tmp_path)
    assert result.returncode == 0 and result.stdout.strip() == 'completed'
    progress = read_json(tmp_path/'progress.json')
    assert progress['status'] == 'RETURNED' and progress['termination'] is None
    assert len(failures) == 2 and not (tmp_path/'progress.error.json').exists()


def test_persistent_progress_conflict_is_recorded_and_the_call_completes(tmp_path, monkeypatch):
    from ctxcomp import io
    original = io.os.replace
    def blocked(source, target):
        if Path(target).name == 'progress.json':
            exc = PermissionError(13, 'Synthetic access denied'); exc.winerror = 5
            raise exc
        return original(source, target)
    monkeypatch.setattr(io.os, 'replace', blocked)
    monkeypatch.setattr(io, 'REPLACE_RETRY_DELAYS', (.01,))
    result = monitored_run([sys.executable, '-u', '-c',
        'import sys; sys.stdin.read(); print("completed",flush=True)'], '', tmp_path, tmp_path)
    assert result.returncode == 0 and result.stdout.strip() == 'completed'
    record = read_json(tmp_path/'progress_write_failures.json')
    assert record['count'] >= 2 and record['code'] == 'LOCAL_FILE_REPLACE_BLOCKED' and record['call_continued']
    assert Path(record['path']).name == 'progress.json'
    assert not (tmp_path/'progress.json').exists() and not (tmp_path/'progress.error.json').exists()
    assert 'completed' in (tmp_path/'events.jsonl').read_text(encoding='utf-8')


def test_unwritable_event_log_does_not_stop_the_call(tmp_path, monkeypatch):
    from ctxcomp import providers
    real_open = Path.open
    def guarded(self, mode='r', *args, **kwargs):
        if self.name == 'event_timeline.jsonl' and 'a' in mode: raise PermissionError(13, 'Synthetic lock')
        return real_open(self, mode, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', guarded)
    command = [sys.executable, '-u', '-c', 'import sys; sys.stdin.read(); print("{\\"type\\":\\"turn.started\\"}",flush=True)']
    assert providers.monitored_run(command, '', tmp_path, tmp_path).returncode == 0
    assert read_json(tmp_path/'progress.json')['diagnostic_write_failures'] == 1
    assert read_json(tmp_path/'progress_write_failures.json')['code'] == 'LOCAL_IO_ERROR'


def test_opt_in_silence_limit_stops_a_quiet_call(tmp_path):
    started = time.monotonic()
    with pytest.raises(ModelProviderError) as error:
        monitored_run([sys.executable, '-u', '-c', 'import time; time.sleep(30)'], '', tmp_path, tmp_path, silence_seconds=.5)
    assert error.value.code == 'MODEL_SILENT' and time.monotonic() - started < 10
    progress = read_json(tmp_path/'progress.json')
    assert progress['status'] == 'SILENT' and progress['silence_limit_seconds'] == .5 and not progress['process_alive']


def test_output_keeps_a_call_alive_under_the_silence_limit(tmp_path):
    program = 'import sys,time\nsys.stdin.read()\nfor _ in range(4):\n    print("{}",flush=True); time.sleep(.3)'
    assert monitored_run([sys.executable, '-u', '-c', program], '', tmp_path, tmp_path, silence_seconds=1).returncode == 0


@pytest.mark.parametrize('value,expected', [(None, None), ('', None), ('900', 900), ('59', 'error'), ('ten', 'error')])
def test_silence_limit_setting(monkeypatch, value, expected):
    from ctxcomp.providers import model_silence_seconds
    if value is None: monkeypatch.delenv('CTXCOMP_MODEL_SILENCE_SECONDS', raising=False)
    else: monkeypatch.setenv('CTXCOMP_MODEL_SILENCE_SECONDS', value)
    if expected == 'error':
        with pytest.raises(ValueError, match='at least 60'): model_silence_seconds()
    else:
        assert model_silence_seconds() == expected


@pytest.mark.parametrize('stdout,stderr,code', [
    ('{"type":"error","message":"exceeded retry limit, last status: 429 Too Many Requests"}\n', '', 'MODEL_RATE_LIMITED'),
    ('', "You've hit your usage limit. Try again later.", 'MODEL_RATE_LIMITED'),
    ('{"type":"item.completed","item":{"type":"agent_message","text":"Absorption is the rate limiting step"}}\n', 'stream disconnected',
     'MODEL_RESPONSE_UNAVAILABLE')])
def test_rate_limits_are_reported_apart_from_login_problems(monkeypatch, tmp_path, stdout, stderr, code):
    monkeypatch.setattr('ctxcomp.providers.shutil.which', lambda _: 'codex.exe')
    monkeypatch.setattr('ctxcomp.providers.monitored_run', lambda *a, **k: subprocess.CompletedProcess(a[0], 1, stdout, stderr))
    with pytest.raises(ModelProviderError) as caught:
        codex_generate({'request_sha256': 'synthetic', 'payload': {'schema': {'type': 'object'}}}, diagnostics_dir=tmp_path)
    assert caught.value.code == code
    assert ('rate or usage limit' in str(caught.value)) == (code == 'MODEL_RATE_LIMITED')


def test_provider_records_local_io_error_without_discarding_streamed_logs(tmp_path, monkeypatch):
    from ctxcomp.io import AtomicReplaceError
    monkeypatch.setattr('ctxcomp.providers.shutil.which', lambda _: 'codex.exe')
    error = PermissionError(13, 'Denied'); error.winerror = 5
    failure = AtomicReplaceError(tmp_path/'progress.json', error, 8, 1.58)
    def fail(*args, **kwargs):
        (tmp_path/'events.jsonl').write_text('{"type":"turn.started"}\n', encoding='utf-8')
        raise failure
    monkeypatch.setattr('ctxcomp.providers.monitored_run', fail)
    with pytest.raises(AtomicReplaceError) as raised:
        codex_generate({'request_sha256':'synthetic','payload':{'schema':{'type':'object'}}}, diagnostics_dir=tmp_path)
    assert raised.value is failure
    assert read_json(tmp_path/'call.json')['status'] == 'LOCAL_FILE_REPLACE_BLOCKED'
    assert 'turn.started' in (tmp_path/'events.jsonl').read_text(encoding='utf-8')


def test_a_blocked_final_log_copy_keeps_the_response_and_is_counted(tmp_path, monkeypatch):
    from ctxcomp import providers
    from ctxcomp.io import AtomicReplaceError
    monkeypatch.setattr('ctxcomp.providers.shutil.which', lambda _: 'codex.exe')
    returned = []
    def run(command, prompt, cwd, *args, **kwargs):
        write_json(Path(cwd)/'response.json', {'request_sha256': 'synthetic', 'answer': 1})
        write_json(tmp_path/'progress_write_failures.json', {'count': 2})  # Two live copies had already failed.
        returned.append(True)
        return subprocess.CompletedProcess(command, 0, '{"type":"turn.completed"}\n', '')
    monkeypatch.setattr('ctxcomp.providers.monitored_run', run)
    real = providers.atomic_text
    def blocked(path, text):
        if returned and Path(path).name == 'events.jsonl':
            error = PermissionError(13, 'Denied'); error.winerror = 5
            raise AtomicReplaceError(path, error, 8, 1.58)
        return real(path, text)
    monkeypatch.setattr('ctxcomp.providers.atomic_text', blocked)
    response = codex_generate({'request_sha256': 'synthetic', 'payload': {'schema': {'type': 'object'}}}, diagnostics_dir=tmp_path)
    assert response == {'request_sha256': 'synthetic', 'answer': 1}
    record = read_json(tmp_path/'progress_write_failures.json')
    assert record['count'] == 3 and record['path'].endswith('events.jsonl') and record['code'] == 'LOCAL_FILE_REPLACE_BLOCKED'
    assert record['call_continued'] is True
