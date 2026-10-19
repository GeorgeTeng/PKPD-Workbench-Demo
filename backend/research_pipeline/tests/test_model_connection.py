"""The connection check follows CTXCOMP_MODEL_PROVIDER. A synthetic local server; no live models."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from research_pipeline.model_connection import connection_status


def test_codex_status_names_the_configured_model(monkeypatch):
    import subprocess
    monkeypatch.setenv('CTXCOMP_MODEL_PROVIDER', 'codex')
    monkeypatch.setenv('CTXCOMP_CODEX_MODEL', 'gpt-6-sol')
    monkeypatch.setattr('research_pipeline.model_connection.shutil.which', lambda _: 'synthetic-codex')
    monkeypatch.setattr('research_pipeline.model_connection.subprocess.run',
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, 'Logged in using ChatGPT', ''))
    status = connection_status()
    assert status['logged_in'] and status['provider'] == 'codex_cli'
    assert status['model'] == 'gpt-6-sol'


def serve(models):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            body = json.dumps({'data': [{'id': m} for m in models]}).encode()
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers(); self.wfile.write(body)
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def test_local_server_status_names_the_configured_model(monkeypatch):
    httpd = serve(['qwen3:32b', 'qwen3:8b'])
    monkeypatch.setenv('CTXCOMP_MODEL_PROVIDER', 'openai'); monkeypatch.setenv('CTXCOMP_OPENAI_MODEL', 'qwen3:32b')
    monkeypatch.setenv('CTXCOMP_OPENAI_BASE_URL', f'http://127.0.0.1:{httpd.server_port}/v1')
    try:
        status = connection_status()
        assert status['installed'] and status['logged_in'] and status['provider'] == 'openai_compatible'
        monkeypatch.setenv('CTXCOMP_OPENAI_MODEL', 'qwen3:72b')
        assert connection_status()['logged_in'] is False  # Served, but not the configured model.
    finally: httpd.shutdown()


def test_unreachable_server_and_missing_claude_are_reported(monkeypatch):
    monkeypatch.setenv('CTXCOMP_MODEL_PROVIDER', 'openai'); monkeypatch.setenv('CTXCOMP_OPENAI_MODEL', 'qwen3:32b')
    monkeypatch.setenv('CTXCOMP_OPENAI_BASE_URL', 'http://127.0.0.1:9/v1')
    status = connection_status()
    assert status['installed'] is False and 'error' in status
    monkeypatch.setenv('CTXCOMP_MODEL_PROVIDER', 'claude')
    monkeypatch.setattr('research_pipeline.model_connection.shutil.which', lambda _: None)
    assert connection_status() == {'installed': False, 'logged_in': False, 'method': 'UNAVAILABLE', 'provider': 'claude_code_cli'}
