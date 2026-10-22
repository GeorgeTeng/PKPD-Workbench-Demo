"""Small runtime for direct DR coverage and shortage advice.

Only actual input artifacts and executing code are bound. Historical producer
code, unrelated stage policies and old execution ledgers are not prerequisites.
"""
import copy
import json
import os
import time
from pathlib import Path
from uuid import uuid4

from ctxcomp import governance, providers
from ctxcomp.io import digest
from ctxcomp.schemas import validate_schema
from .common import PipelineError, read_json, write_json, sha256, utcnow

MODEL = 'gpt-6-sol'
REQUEST_TIMEOUT_SECONDS = 1500
MAX_REQUEST_CHARS = 700_000


def fail(message):
    raise PipelineError('DIRECT_DATA_INVALID', message)


def file_ref(path):
    return {'path': str(Path(path).resolve()), 'sha256': sha256(path)}


def verify_refs(bindings):
    for name, ref in bindings.items():
        if file_ref(ref['path']) != ref:
            fail('Active input changed: ' + name)


def make_request(payload, schema):
    request = governance.governed_request({**copy.deepcopy(payload), 'schema': schema})
    if len(json.dumps(request, ensure_ascii=False)) > MAX_REQUEST_CHARS:
        fail('Request exceeds transport capacity; split whole DR requirements without truncating evidence')
    return request


def runtime_bindings():
    return {'direct_runtime': file_ref(__file__), 'governance': file_ref(governance.RESOURCE)}


def diagnostics(folder):
    folder = Path(folder)
    call = read_json(folder/'call.json') if (folder/'call.json').exists() else {}
    served = call.get('served_models') or ([call['served_model']] if call.get('served_model') else [])
    usage = {}
    if (folder/'events.jsonl').exists():
        for line in (folder/'events.jsonl').read_text(encoding='utf-8').splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get('type') == 'turn.completed':
                usage = event.get('usage') or {}
    return {'requested_model': MODEL, 'served_models': served,
            'served_model': served[0] if len(set(served)) == 1 else None,
            'usage': usage}


def invoke(out, request, bindings, validate, *, generator=None):
    """Execute once or reuse the exact accepted response. Never auto-retry."""
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    verify_refs(bindings)
    if request['request_sha256'] != digest(request['payload']):
        fail('Prepared request hash differs from payload')
    envelope = {'request_sha256': request['request_sha256'], 'bindings': bindings, 'requested_model': MODEL}
    manifest = out/'manifest.json'
    if manifest.exists() and read_json(manifest) != envelope:
        fail('Output directory belongs to different inputs; use a new directory')
    lock = out/'runtime.lock'
    with lock.open('x', encoding='utf-8') as stream:
        json.dump({'pid': os.getpid(), 'at': utcnow()}, stream)
    try:
        write_json(manifest, envelope)
        write_json(out/'request.json', request)
        accepted = out/'accepted.json'
        if accepted.exists():
            receipt = read_json(accepted)
            if receipt.get('test_generator', False) != (generator is not None):
                fail('Synthetic test and real provider receipts cannot be interchanged')
            if receipt['request_sha256'] != request['request_sha256']:
                fail('Accepted response belongs to another request')
            verify_refs({'raw': receipt['raw']})
            raw = read_json(receipt['raw']['path'])
            validate_schema(raw, request['payload']['schema'])
            if raw.get('request_sha256') != request['request_sha256']:
                fail('Accepted raw belongs to another request')
            validate(raw)
            verify_refs(bindings)
            return raw
        if (out/'PAUSE').exists():
            fail('Paused before model dispatch')
        previous = list((out/'attempts').glob('*/status.json'))
        if previous:
            fail('Previous attempt retained; diagnose it and use an explicit correction or a new attempt directory')
        if generator is None and (providers.model_provider() != 'codex' or providers.provider_model(MODEL) != MODEL):
            fail('This run requires the authorized Codex gpt-6-sol provider')
        folder = out/'attempts'/uuid4().hex
        status = {'status': 'RUNNING', 'started_at': utcnow(), 'requested_model': MODEL,
                  'request_sha256': request['request_sha256'], 'timeout_seconds': REQUEST_TIMEOUT_SECONDS,
                  'test_generator': generator is not None}
        write_json(folder/'status.json', status)
        started = time.monotonic()
        try:
            raw = (generator or providers.codex_generate)(request, model=MODEL,
                timeout=REQUEST_TIMEOUT_SECONDS, diagnostics_dir=folder/'model_call')
            write_json(folder/'response.json', raw)
            status.update(diagnostics(folder/'model_call'))
            if any(model != MODEL for model in status['served_models']):
                fail('Provider reported a different served model')
            verify_refs(bindings)
            validate_schema(raw, request['payload']['schema'])
            if raw.get('request_sha256') != request['request_sha256']:
                fail('Model response belongs to another request')
            validate(raw)
            verify_refs(bindings)
            status['status'] = 'ACCEPTED'
            write_json(accepted, {'request_sha256': request['request_sha256'],
                'raw': file_ref(folder/'response.json'), 'attempt': str(folder),
                'requested_model': MODEL, 'served_models': status['served_models'],
                'test_generator': generator is not None})
            return raw
        except BaseException as exc:
            status.update(status='INTERRUPTED' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'FAILED', error=str(exc))
            raise
        finally:
            status.update(ended_at=utcnow(), elapsed_seconds=time.monotonic()-started)
            write_json(folder/'status.json', status)
    finally:
        lock.unlink(missing_ok=True)
