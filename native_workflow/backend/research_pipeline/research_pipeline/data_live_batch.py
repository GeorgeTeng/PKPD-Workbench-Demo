"""Explicit, single-authorization budget shared by a live Coverage/Necessity batch.

This is an execution adapter, not a reset of either stage's cumulative ledger.
Unknown interrupted calls retain their full reservation. No automatic renewal.
"""
import math
import os
import time
from pathlib import Path
from uuid import uuid4

from .adequacy import check_ref, file_ref
from .common import read_json, write_json, utcnow

MODEL = 'gpt-6-sol'
PROVIDER_LIMIT = 1500.0
WALL_LIMIT = 1800.0
RESERVE = 20.0


def fail(message):
    raise ValueError('DATA_LIVE_BATCH: ' + message)


class Batch:
    @classmethod
    def create(cls, authorization, directory):
        authorization = Path(authorization).resolve()
        directory = Path(directory).resolve()
        scope = read_json(authorization)
        if (scope.get('new_calls_model') != MODEL or
                scope.get('new_batch_provider_seconds_limit') != PROVIDER_LIMIT or
                scope.get('new_batch_wall_seconds_limit') != WALL_LIMIT or
                scope.get('prior_history_is_not_reset') is not True):
            fail('Authorization must explicitly preserve history and grant this bounded batch')
        if directory.parent != authorization.parent:
            fail('Budget directory must be beside its authorization')
        for ref in scope['inputs'].values():
            check_ref(ref)
        if directory.exists() and any(directory.iterdir()):
            fail('New batch requires an empty directory')
        # A second directory cannot silently redeem the same authorization again.
        claim = authorization.with_suffix(authorization.suffix + '.batch_claim.json')
        with claim.open('x', encoding='utf-8') as stream:
            import json
            json.dump({'batch_directory': str(directory), 'authorization': file_ref(authorization)}, stream)
        history = read_json(scope['inputs']['historical_coverage_budget']['path'])
        from .data_coverage_v5 import inherited_budget
        historical_seconds, historical_calls = inherited_budget(history)
        manifest = {'version': 'DATA_LIVE_BATCH_1.0', 'id': uuid4().hex,
            'authorization': file_ref(authorization), 'claim': file_ref(claim),
            'adapter_code': file_ref(__file__), 'created_at': utcnow(),
            'provider_limit_seconds': PROVIDER_LIMIT, 'wall_limit_seconds': WALL_LIMIT,
            'requested_model': MODEL, 'historical_elapsed_seconds': historical_seconds,
            'historical_calls': historical_calls}
        write_json(directory/'manifest.json', manifest)
        write_json(directory/'state.json', {'started_epoch': None, 'stages': {}})
        return manifest

    @classmethod
    def open(cls, directory, *, recover_stale_lock=False):
        return cls(directory, recover_stale_lock=recover_stale_lock)

    def __init__(self, directory, *, recover_stale_lock=False):
        self.directory = Path(directory).resolve()
        self.manifest = read_json(self.directory/'manifest.json')
        self.ref = file_ref(self.directory/'manifest.json')
        self.lock = self.directory/'batch.lock'
        self.active = False
        self.recover_stale_lock = recover_stale_lock
        self._verify()

    def _verify(self):
        check_ref(self.ref)
        for key in ('authorization', 'claim', 'adapter_code'):
            check_ref(self.manifest[key])
        scope = read_json(self.manifest['authorization']['path'])
        for ref in scope['inputs'].values():
            check_ref(ref)
        if Path(read_json(self.manifest['claim']['path'])['batch_directory']) != self.directory:
            fail('Authorization belongs to another batch')
        if self.manifest['adapter_code'] != file_ref(__file__):
            fail('Batch adapter changed after authorization')
        return scope

    def __enter__(self):
        from .data_coverage_v5 import _alive
        if self.lock.exists() and self.recover_stale_lock:
            if _alive(read_json(self.lock).get('pid')):
                fail('Batch is still running')
            self.lock.replace(self.directory/('stale_lock_' + uuid4().hex + '.json'))
        with self.lock.open('x', encoding='utf-8') as stream:
            import json
            json.dump({'pid': os.getpid(), 'at': utcnow()}, stream)
        self.active = True
        self._verify()
        return self

    def __exit__(self, *args):
        self.active = False
        self.lock.unlink(missing_ok=True)

    def summary(self):
        self._verify()
        state = read_json(self.directory/'state.json')
        records = [read_json(p) for p in (self.directory/'calls').glob('*.json')]
        elapsed = 0.0
        for record in records:
            if record['batch'] != self.ref:
                fail('Call belongs to another batch')
            seconds = record.get('elapsed_seconds', record['timeout_seconds'])
            if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
                fail('Invalid call accounting')
            elapsed += seconds
        wall = 0.0 if state['started_epoch'] is None else time.time() - state['started_epoch']
        if wall < 0:
            fail('Wall clock moved before batch start')
        result = {'batch': self.ref, 'new_provider_seconds': elapsed, 'new_calls': len(records),
            'historical_elapsed_seconds': self.manifest['historical_elapsed_seconds'],
            'historical_calls': self.manifest['historical_calls'], 'wall_seconds': wall,
            'remaining_seconds': max(0.0, min(PROVIDER_LIMIT-elapsed, WALL_LIMIT-wall))}
        prior = self.directory/'summary.json'
        if prior.exists():
            old = read_json(prior)
            if old['new_provider_seconds'] > elapsed + 0.000001 or old['new_calls'] > len(records):
                fail('Batch accounting cannot decrease')
        return result

    def bind_stage(self, out, stage):
        if not self.active:
            fail('Use the batch context manager before execution')
        scope = self._verify()
        out = Path(out).resolve()
        root = Path(self.manifest['authorization']['path']).parent
        if root not in out.parents or self.directory == out or self.directory in out.parents:
            fail('Stage output must be a new directory inside the authorized test batch')
        built = read_json(out/'build.json')
        bindings = built.get('bindings') or read_json(out/'bindings.json')
        if bindings.get('plan') != scope['inputs']['DR']:
            fail('Stage plan differs from authorized DR')
        if stage == 'coverage':
            if bindings.get('source_view') != scope['inputs']['source_view']:
                fail('Stage source differs from authorized extraction')
            historical = built.get('historical_import', {}).get('refs', {}).get('budget')
            if historical != scope['inputs']['historical_coverage_budget']:
                parent = bindings.get('parent_coverage')
                if not parent:
                    fail('Coverage must preserve the authorized historical import')
                check_ref(parent)
                marker = Path(parent['path']).parent/'batch_binding.json'
                if not marker.exists() or read_json(marker)['batch'] != self.ref:
                    fail('Targeted Coverage requires its parent from this same batch')
        elif stage == 'necessity':
            coverage = Path(bindings['coverage']['path'])
            check_ref(bindings['coverage'])
            marker = coverage.parent/'batch_binding.json'
            if not marker.exists() or read_json(marker)['batch'] != self.ref:
                fail('Necessity requires Coverage from this same batch')
        else:
            fail('Only Coverage and Necessity are authorized')
        state = read_json(self.directory/'state.json')
        entry = {'stage': stage, 'build': file_ref(out/'build.json'), 'batch': self.ref}
        if (out/'bindings.json').exists():
            entry['bindings'] = file_ref(out/'bindings.json')
        existing = state['stages'].get(str(out))
        if existing and existing != entry:
            fail('Prepared stage changed inside a running batch')
        marker = out/'batch_binding.json'
        if marker.exists() and read_json(marker) != entry:
            fail('Stage already belongs to another batch')
        state['stages'][str(out)] = entry
        write_json(self.directory/'state.json', state)
        write_json(marker, entry)

    def admission(self, ledger, checks):
        from .data_coverage_v5 import admission
        result = admission(ledger, checks, remaining_seconds=self.summary()['remaining_seconds'])
        return {**result, 'batch': self.ref, 'historical_ledger_elapsed_seconds': ledger['elapsed_seconds']}

    def generator(self, out, generator=None):
        from . import data_agents as d
        out = Path(out).resolve()
        executor = d.executor_id(MODEL, generator)
        def bounded(request, *, model, timeout, **options):
            if not self.active or model != MODEL:
                fail('Batch requires an active lock and exact gpt-6-sol')
            if d.executor_id(MODEL, generator) != executor:
                fail('Underlying executor identity changed after wrapper creation')
            state = read_json(self.directory/'state.json')
            entry = state['stages'].get(str(out))
            if not entry:
                fail('Stage was not bound to this batch')
            for key in ('build', 'bindings'):
                if key in entry:
                    check_ref(entry[key])
            remaining = self.summary()['remaining_seconds']
            timeout = min(timeout, remaining - RESERVE)
            if timeout <= 0:
                fail('Shared provider/wall budget exhausted')
            if state['started_epoch'] is None:
                state['started_epoch'] = time.time()
                write_json(self.directory/'state.json', state)
            record = {'batch': self.ref, 'stage': entry, 'request_sha256': request['request_sha256'],
                'requested_model': model, 'timeout_seconds': timeout, 'status': 'RUNNING', 'at': utcnow()}
            path = self.directory/'calls'/(uuid4().hex+'.json')
            write_json(path, record)
            started = time.monotonic()
            try:
                response = (generator or d.codex_generate)(request, model=model, timeout=timeout, **options)
                record['status'] = 'RETURNED'
                return response
            except BaseException as exc:
                record['status'] = 'INTERRUPTED' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'FAILED'
                record['error'] = str(exc)
                raise
            finally:
                record['elapsed_seconds'] = time.monotonic()-started
                record['ended_at'] = utcnow()
                write_json(path, record)
                write_json(self.directory/'summary.json', self.summary())
        # Cache routing identity only; this does not attest the served model.
        bounded.executor_id = ('live-batch:' + self.ref['sha256'] + ':' + executor) if executor else None
        return bounded


def require_stage_batch(out, batch):
    marker = Path(out)/'batch_binding.json'
    if marker.exists() and (batch is None or read_json(marker)['batch'] != batch.ref):
        fail('Bound stage requires its original explicit batch; budget cannot be bypassed')
    if batch is not None and not isinstance(batch, Batch):
        fail('Invalid live batch adapter')
