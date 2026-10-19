"""CTXCOMP_MODEL_PROVIDER switches every model call between the Codex CLI, the Claude Code CLI and an
OpenAI-compatible server (for example a local Qwen). Synthetic stand-ins for the CLI and the server; no live models."""
import json
import os
import stat
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import pytest
from ctxcomp.io import read_json
from ctxcomp.providers import (codex_generate, executor_identity, model_provider, response_json, ModelProviderError,
                               CLAUDE_ISOLATION, CLAUDE_SCHEMA_ISOLATION)

# Transport-only fixtures are not valid scientific requests. Managed stages are
# exercised through the mandatory builder in test_context_linear_integration.
REQUEST = {'request_sha256': 'synthetic', 'payload': {'schema': {'type': 'object'}, 'stage': 'transport_fixture'}}


def fake_claude(tmp_path, monkeypatch, result, exit_code=0, help_text='Usage: claude [options]', models=()):
    """A claude executable that records its arguments and stdin, then streams Claude Code's event shapes."""
    folder = tmp_path / 'bin'; folder.mkdir()
    script = folder / 'claude'
    script.write_text(f'''#!{sys.executable}
import json, os, sys
if sys.argv[1:] == ['--help']:
    print({help_text!r}); sys.exit(0)
open({str(tmp_path / 'output_tokens.txt')!r}, 'w').write(os.environ.get('CLAUDE_CODE_MAX_OUTPUT_TOKENS', 'unset'))
open({str(tmp_path / 'argv.json')!r}, 'w').write(json.dumps(sys.argv[1:]))
open({str(tmp_path / 'stdin.txt')!r}, 'w', encoding='utf-8').write(sys.stdin.read())
answers = [{{"type": "assistant", "message": {{"model": m, "content": []}}}} for m in {list(models)!r}]
for event in [{{"type": "system", "subtype": "init"}}, {{"type": "assistant", "message": {{"content": []}}}}, *answers, {result!r}]:
    print(json.dumps(event), flush=True)
sys.exit({exit_code})
''', encoding='utf-8')
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv('PATH', str(folder) + os.pathsep + os.environ['PATH'])
    monkeypatch.setenv('CTXCOMP_MODEL_PROVIDER', 'claude')


@pytest.mark.skipif(os.name == 'nt', reason='The stand-in CLI is a POSIX script')
def test_claude_code_answers_through_the_same_call(tmp_path, monkeypatch):
    fake_claude(tmp_path, monkeypatch, {'type': 'result', 'subtype': 'success', 'is_error': False,
        'result': '```json\n{"request_sha256": "synthetic", "requirements": []}\n```', 'total_cost_usd': 0.01})
    monkeypatch.setenv('CTXCOMP_CLAUDE_MODEL', 'sonnet')
    calls = tmp_path / 'call'
    assert codex_generate(REQUEST, diagnostics_dir=calls) == {'request_sha256': 'synthetic', 'requirements': []}
    argv = json.loads((tmp_path / 'argv.json').read_text())
    assert argv[0] == '-p' and argv[argv.index('--model') + 1] == 'sonnet'
    assert all(flag in argv for flag in CLAUDE_ISOLATION if flag) and argv[argv.index('--tools') + 1] == ''
    assert '"request_sha256":"synthetic"' in (tmp_path / 'stdin.txt').read_text(encoding='utf-8')
    call = read_json(calls / 'call.json')
    assert call['status'] == 'RETURNED' and call['provider'] == 'claude' and call['requested_model'] == 'sonnet'
    progress = read_json(calls / 'progress.json')
    assert progress['model_turn_completed_at'] and progress['first_response_at']
    # A long answer that thinks first gets the model's full output limit, not the CLI's lower default.
    assert (tmp_path / 'output_tokens.txt').read_text() == '128000'
    monkeypatch.setenv('CTXCOMP_CLAUDE_MAX_OUTPUT_TOKENS', '64000')
    codex_generate(REQUEST, diagnostics_dir=tmp_path / 'again')
    assert (tmp_path / 'output_tokens.txt').read_text() == '64000'


@pytest.mark.skipif(os.name == 'nt', reason='The stand-in CLI is a POSIX script')
@pytest.mark.parametrize('text,code', [
    ("You've hit your session limit · resets 3:45pm", 'MODEL_RATE_LIMITED'),
    ('Not logged in · Please run /login', 'MODEL_RESPONSE_UNAVAILABLE')])
def test_claude_code_errors_are_typed(tmp_path, monkeypatch, text, code):
    fake_claude(tmp_path, monkeypatch, {'type': 'result', 'subtype': 'error_during_execution', 'is_error': True, 'result': text}, 1)
    with pytest.raises(ModelProviderError) as caught:
        codex_generate(REQUEST, diagnostics_dir=tmp_path / 'call')
    assert caught.value.code == code


@pytest.mark.skipif(os.name == 'nt', reason='The stand-in CLI is a POSIX script')
def test_a_reply_that_is_not_json_is_rejected(tmp_path, monkeypatch):
    fake_claude(tmp_path, monkeypatch, {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'I cannot do that.'})
    with pytest.raises(ModelProviderError, match='not one JSON object') as caught:
        codex_generate(REQUEST, diagnostics_dir=tmp_path / 'call')
    assert caught.value.code == 'MODEL_RESPONSE_UNAVAILABLE'


class Server:
    """An OpenAI-compatible chat server that streams a Qwen-style reply with a reasoning block."""
    def __init__(self, chunks, status=200):
        received = self.received = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                received.append((self.path, dict(self.headers), json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(status); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
                if status != 200: self.wfile.write(b'{"error": "model not loaded"}'); return
                for chunk in chunks:
                    self.wfile.write(b'data: ' + json.dumps({'choices': [{'delta': {'content': chunk}}]}).encode() + b'\n\n')
                self.wfile.write(b'data: [DONE]\n\n')
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f'http://127.0.0.1:{self.httpd.server_port}/v1'


@pytest.fixture
def openai_env(monkeypatch):
    monkeypatch.setenv('CTXCOMP_MODEL_PROVIDER', 'openai'); monkeypatch.setenv('CTXCOMP_OPENAI_MODEL', 'qwen3:32b')
    monkeypatch.setenv('CTXCOMP_OPENAI_API_KEY', 'local-key')


def test_local_openai_compatible_server_answers(tmp_path, monkeypatch, openai_env):
    server = Server(['<think>check the schema</think>', '{"request_sha256": ', '"synthetic", "ok": true}'])
    monkeypatch.setenv('CTXCOMP_OPENAI_BASE_URL', server.url)
    try:
        assert codex_generate(REQUEST, diagnostics_dir=tmp_path) == {'request_sha256': 'synthetic', 'ok': True}
    finally: server.httpd.shutdown()
    path, headers, body = server.received[0]
    assert path == '/v1/chat/completions' and body['model'] == 'qwen3:32b' and body['stream'] is True
    assert '"request_sha256":"synthetic"' in body['messages'][-1]['content'] and 'response_format' not in body
    assert body['stream_options'] == {'include_usage': True}
    assert headers['Authorization'] == 'Bearer local-key'
    assert 'local-key' not in (tmp_path / 'events.jsonl').read_text(encoding='utf-8')
    call = read_json(tmp_path / 'call.json')
    assert call['provider'] == 'openai' and call['requested_model'] == 'qwen3:32b' and call['status'] == 'RETURNED'
    assert read_json(tmp_path / 'progress.json')['model_turn_completed_at']


def test_an_unloaded_local_model_is_reported(tmp_path, monkeypatch, openai_env):
    server = Server([], status=404)
    monkeypatch.setenv('CTXCOMP_OPENAI_BASE_URL', server.url)
    try:
        with pytest.raises(ModelProviderError, match='server is running and the model is loaded') as caught:
            codex_generate(REQUEST, diagnostics_dir=tmp_path)
    finally: server.httpd.shutdown()
    assert caught.value.code == 'MODEL_RESPONSE_UNAVAILABLE'
    assert 'model not loaded' in (tmp_path / 'events.jsonl').read_text(encoding='utf-8')


def test_openai_provider_needs_a_model_name(monkeypatch):
    monkeypatch.setenv('CTXCOMP_MODEL_PROVIDER', 'openai'); monkeypatch.delenv('CTXCOMP_OPENAI_MODEL', raising=False)
    with pytest.raises(ModelProviderError, match='CTXCOMP_OPENAI_MODEL') as caught:
        codex_generate(REQUEST)
    assert caught.value.code == 'MODEL_CLI_UNAVAILABLE'


def test_reused_calls_belong_to_one_provider(monkeypatch):
    monkeypatch.delenv('CTXCOMP_MODEL_PROVIDER', raising=False)
    monkeypatch.delenv('CTXCOMP_CODEX_MODEL', raising=False)
    assert model_provider() == 'codex'
    assert executor_identity() == {'provider': 'codex_cli', 'requested_model': 'gpt-6-luna'}
    monkeypatch.setenv('CTXCOMP_MODEL_PROVIDER', 'claude'); monkeypatch.delenv('CTXCOMP_CLAUDE_MODEL', raising=False)
    assert executor_identity() == {'provider': 'claude_code_cli', 'requested_model': 'claude-opus-5'}
    monkeypatch.setenv('CTXCOMP_CLAUDE_MODEL', 'opus')
    assert executor_identity() == {'provider': 'claude_code_cli', 'requested_model': 'opus'}
    monkeypatch.setenv('CTXCOMP_MODEL_PROVIDER', 'openai'); monkeypatch.setenv('CTXCOMP_OPENAI_MODEL', 'qwen3:32b')
    monkeypatch.setenv('CTXCOMP_OPENAI_BASE_URL', 'http://127.0.0.1:1234/v1/')
    assert executor_identity() == {'provider': 'openai_compatible', 'requested_model': 'qwen3:32b',
                                   'base_url': 'http://127.0.0.1:1234/v1'}
    monkeypatch.setenv('CTXCOMP_MODEL_PROVIDER', 'gemini')
    with pytest.raises(ValueError, match='codex, claude or openai'):
        model_provider()


@pytest.mark.parametrize('configured,explicit,expected', [
    ('', None, 'gpt-6-luna'), (' gpt-6-sol ', None, 'gpt-6-sol'),
    ('gpt-6-sol', 'test-explicit-model', 'test-explicit-model'),
    ('test-env-model', None, 'test-env-model')])
def test_codex_command_audit_and_cache_use_the_same_model(tmp_path, monkeypatch, configured, explicit, expected):
    import subprocess
    from ctxcomp.io import write_json
    monkeypatch.setenv('CTXCOMP_MODEL_PROVIDER', 'codex')
    monkeypatch.setenv('CTXCOMP_CODEX_MODEL', configured)
    monkeypatch.setattr('ctxcomp.providers.shutil.which', lambda _: 'synthetic-codex')
    def run(command, prompt, cwd, *args, **kwargs):
        assert command[command.index('--model') + 1] == expected
        write_json(Path(command[command.index('--output-last-message') + 1]), {'status': 'CONNECTED'})
        return subprocess.CompletedProcess(command, 0, '', '')
    monkeypatch.setattr('ctxcomp.providers.monitored_run', run)
    assert codex_generate(REQUEST, model=explicit, diagnostics_dir=tmp_path) == {'status': 'CONNECTED'}
    identity = executor_identity(explicit)
    assert identity['requested_model'] == expected
    assert identity['requested_model'] == read_json(tmp_path / 'call.json')['requested_model']


@pytest.mark.parametrize('text,expected', [
    ('{"a": 1}', {'a': 1}), ('```json\n{"a": 1}\n```', {'a': 1}), ('<think>{"b": 2}</think>\n{"a": 1}', {'a': 1}),
    ('Here it is: {"a": 1}', {'a': 1})])
def test_reply_json_is_extracted(text, expected):
    assert response_json(text) == expected


@pytest.mark.parametrize('text', ['no json', '{"a": 1} and more', '[1, 2]'])
def test_reply_without_one_object_is_refused(text):
    with pytest.raises(ValueError):
        response_json(text)


def test_a_prompt_longer_than_the_local_context_is_refused(tmp_path, monkeypatch, openai_env):
    server = Server(['{}'])
    monkeypatch.setenv('CTXCOMP_OPENAI_BASE_URL', server.url); monkeypatch.setenv('CTXCOMP_OPENAI_CONTEXT_TOKENS', '10')
    try:
        with pytest.raises(ModelProviderError) as caught:
            codex_generate(REQUEST, diagnostics_dir=tmp_path)
    finally: server.httpd.shutdown()
    assert caught.value.code == 'MODEL_INPUT_TOO_LARGE' and not server.received


@pytest.mark.skipif(os.name == 'nt', reason='The stand-in CLI is a POSIX script')
def test_the_call_record_names_the_models_that_actually_answered(tmp_path, monkeypatch):
    # Claude Code can retry a refused message with a fallback model; the record must not imply the requested one answered.
    fake_claude(tmp_path, monkeypatch, {'type': 'result', 'subtype': 'success', 'is_error': False,
        'result': '{"request_sha256": "synthetic", "requirements": []}'},
        models=['claude-opus-5', 'claude-opus-5', 'claude-sonnet-5'])
    monkeypatch.setenv('CTXCOMP_CLAUDE_MODEL', 'claude-fable-5-1')
    codex_generate(REQUEST, diagnostics_dir=tmp_path / 'call')
    call = read_json(tmp_path / 'call' / 'call.json')
    assert call['requested_model'] == 'claude-fable-5-1'
    assert call['served_models'] == ['claude-opus-5', 'claude-sonnet-5']


@pytest.mark.skipif(os.name == 'nt', reason='The stand-in CLI is a POSIX script')
@pytest.mark.parametrize('supported', [True, False])
def test_claude_code_receives_the_response_schema_when_it_can_enforce_it(tmp_path, monkeypatch, supported):
    fake_claude(tmp_path, monkeypatch, {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': '',
        'structured_output': {'request_sha256': 'synthetic', 'requirements': []}},
        help_text=('  --allowedTools <tools...>\n  --disallowedTools <tools...>\n  --json-schema <schema>  JSON Schema for '
                   'structured output\n  --strict-mcp-config' if supported else '  --allowedTools <tools...>\n  --json-schema <schema>'))
    assert codex_generate(REQUEST, diagnostics_dir=tmp_path / 'call') == {'request_sha256': 'synthetic', 'requirements': []}
    argv = json.loads((tmp_path / 'argv.json').read_text())
    if supported:
        assert json.loads(argv[argv.index('--json-schema') + 1]) == REQUEST['payload']['schema']
        # Only the StructuredOutput tool that carries the answer is allowed; MCP tools stay blocked.
        assert argv[argv.index('--allowedTools') + 1] == 'StructuredOutput'
        assert argv[argv.index('--disallowedTools') + 1] == 'mcp__*' and '--strict-mcp-config' in argv
        assert all(flag in argv for flag in CLAUDE_SCHEMA_ISOLATION if flag) and argv[argv.index('--tools') + 1] == ''
    else:
        assert '--json-schema' not in argv and '--allowedTools' not in argv
        assert argv[argv.index('--disallowedTools') + 1] == '*'
