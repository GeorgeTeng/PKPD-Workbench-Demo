"""Use official CLI authentication; never read or return account credentials.
The provider is the one every model call uses (CTXCOMP_MODEL_PROVIDER: codex, claude or openai)."""
import json
import os
import shutil
import subprocess
import urllib.request
from urllib.parse import urlparse
from uuid import uuid4
from .common import utcnow, write_json


def connection_status():
    from ctxcomp.providers import model_provider, provider_model
    provider = model_provider()
    if provider == 'claude': return claude_status(provider_model())
    if provider == 'openai': return openai_status(provider_model())
    executable = shutil.which('codex')
    if not executable: return {'installed': False, 'logged_in': False, 'method': 'UNAVAILABLE'}
    result = subprocess.run([executable, 'login', 'status'], capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    output = (result.stdout + result.stderr).lower()
    method = 'ChatGPT' if 'chatgpt' in output else 'API_KEY' if 'api key' in output else 'UNKNOWN'
    return {'installed': True, 'logged_in': result.returncode == 0, 'method': method,
            'provider': 'codex_cli', 'model': provider_model(), 'checked_at': utcnow()}


def claude_status(model):
    """Claude Code has no separate login check; a test call shows whether generation works."""
    executable = shutil.which('claude')
    if not executable: return {'installed': False, 'logged_in': False, 'method': 'UNAVAILABLE', 'provider': 'claude_code_cli'}
    result = subprocess.run([executable, '--version'], capture_output=True, text=True, encoding='utf-8', errors='replace',
        timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return {'installed': result.returncode == 0, 'logged_in': None, 'method': 'NOT_CHECKED', 'provider': 'claude_code_cli',
            'version': result.stdout.strip()[:100], 'model': model or 'CLI_DEFAULT', 'checked_at': utcnow()}


def openai_status(model):
    """Whether the OpenAI-compatible server answers and lists the configured model."""
    base = (os.getenv('CTXCOMP_OPENAI_BASE_URL') or 'http://127.0.0.1:11434/v1').rstrip('/')
    value = {'provider': 'openai_compatible', 'base_url': base, 'model': model, 'method': 'SERVER', 'checked_at': utcnow()}
    local = urlparse(base).hostname in {'localhost', '127.0.0.1', '::1'}
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({})) if local else urllib.request.build_opener()
    request = urllib.request.Request(base + '/models')
    key = os.getenv('CTXCOMP_OPENAI_API_KEY', '').strip()
    if key: request.add_header('Authorization', 'Bearer ' + key)
    try:
        with opener.open(request, timeout=10) as response: served = [m.get('id') for m in json.load(response).get('data', [])]
    except (OSError, ValueError, AttributeError) as exc:
        return {**value, 'installed': False, 'logged_in': False, 'error': f'{type(exc).__name__}: {exc}'[:300]}
    return {**value, 'installed': True, 'logged_in': bool(model) and model in served, 'served_models': served[:50]}


def test_connection(state):
    from ctxcomp.providers import codex_generate, model_provider, provider_model
    from ctxcomp.io import digest
    folder = state / 'model_checks' / uuid4().hex
    request = {'task': 'Return status CONNECTED to confirm this local model connection.',
        'payload': {'schema': {'type': 'object', 'properties': {'status': {'type': 'string', 'enum': ['CONNECTED']}},
                               'required': ['status'], 'additionalProperties': False}}}
    request['request_sha256'] = digest(request)
    response = codex_generate(request, diagnostics_dir=folder)
    if response != {'status': 'CONNECTED'}: raise ValueError('Model connection response did not match schema')
    provider = {'codex': 'codex_cli', 'claude': 'claude_code_cli', 'openai': 'openai_compatible'}[model_provider()]
    result = {'status': 'CONNECTED', 'provider': provider, 'model': provider_model(), 'checked_at': utcnow(),
              'research_data_sent': False, 'audit_directory': str(folder)}
    write_json(folder / 'result.json', result); return result
