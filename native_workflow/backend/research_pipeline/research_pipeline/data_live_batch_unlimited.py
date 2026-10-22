"""Explicit one-batch removal of aggregate time limits; original records stay intact.

The 1500-second timeout is now per provider request, never a cumulative allowance.
This separate adapter leaves already-bound Coverage and bounded batch code intact.
"""
from pathlib import Path

from . import data_live_batch as bounded
from .adequacy import check_ref, file_ref
from .common import read_json, write_json, utcnow

REQUEST_TIMEOUT_SECONDS = 1500.0
POLICY_FILE = 'unlimited_time_authorization.json'


def validate_policy(ref):
    check_ref(ref)
    policy = read_json(ref['path'])
    for key in ('authorization', 'original_batch', 'adapter_code'):
        check_ref(policy[key])
    if policy['adapter_code'] != file_ref(__file__):
        bounded.fail('Unlimited time adapter changed')
    authorization = read_json(policy['authorization']['path'])
    if (authorization.get('aggregate_provider_seconds_limit', 1) is not None or
            authorization.get('aggregate_wall_seconds_limit', 1) is not None or
            authorization.get('preserve_elapsed_time_and_call_history') is not True or
            authorization.get('reuse_all_accepted_results') is not True or
            authorization.get('requested_model') != bounded.MODEL):
        bounded.fail('Explicit unlimited batch authorization is incomplete')
    if policy.get('request_timeout_seconds') != REQUEST_TIMEOUT_SECONDS:
        bounded.fail('Per-request transport timeout changed')
    original = Path(policy['original_batch']['path'])
    if Path(ref['path']).resolve() != original.parent/POLICY_FILE:
        bounded.fail('Unlimited authorization must belong to its original batch')
    if Path(policy['authorization']['path']).parent != original.parent.parent:
        bounded.fail('Unlimited authorization belongs to another test run')
    # Validates the original authorization, code hash, inputs, and single claim.
    bounded.Batch(original.parent)
    return policy


class UnlimitedBatch(bounded.Batch):
    @classmethod
    def enable(cls, directory, authorization):
        directory = Path(directory).resolve()
        if (directory/'batch.lock').exists():
            bounded.fail('Enable unlimited time only after the active batch releases its lock')
        original = bounded.Batch(directory)
        policy = {'version': 'EXPLICIT_UNLIMITED_AGGREGATE_TIME_1.0',
            'authorization': file_ref(authorization), 'original_batch': original.ref,
            'adapter_code': file_ref(__file__), 'enabled_at': utcnow(),
            'aggregate_provider_seconds_limit': None, 'aggregate_wall_seconds_limit': None,
            'request_timeout_seconds': REQUEST_TIMEOUT_SECONDS}
        path = directory/POLICY_FILE
        # Append-only transition; original manifest, claims, calls, and accepted parts stay untouched.
        import json
        with path.open('x', encoding='utf-8') as stream:
            json.dump(policy, stream, ensure_ascii=False, indent=2)
        validate_policy(file_ref(path))
        return file_ref(path)

    def __init__(self, directory, **kwargs):
        self.policy_ref = file_ref(Path(directory)/POLICY_FILE)
        super().__init__(directory, **kwargs)

    def _verify(self):
        scope = super()._verify()
        policy = validate_policy(self.policy_ref)
        if policy['original_batch'] != self.ref:
            bounded.fail('Unlimited authorization refers to another original batch')
        return scope

    def summary(self):
        result = super().summary()
        return {**result, 'time_policy': self.policy_ref,
            'aggregate_provider_seconds_limit': None, 'aggregate_wall_seconds_limit': None,
            'request_timeout_seconds': REQUEST_TIMEOUT_SECONDS,
            'remaining_seconds': REQUEST_TIMEOUT_SECONDS + bounded.RESERVE,
            'remaining_seconds_basis': 'PER_REQUEST_WINDOW_NOT_AGGREGATE_REMAINING'}

    def admission(self, ledger, checks):
        result = super().admission(ledger, checks)
        return {**result, 'allowed': True, 'time_policy': self.policy_ref,
                'admission_basis': 'EXPLICIT_NO_AGGREGATE_TIME_LIMIT'}


def necessity_policy(out):
    bindings = read_json(Path(out)/'bindings.json')
    ref = bindings.get('execution_time_policy')
    if ref:
        validate_policy(ref)
    return ref


def necessity_timeout(out, spent):
    return REQUEST_TIMEOUT_SECONDS if necessity_policy(out) else bounded.PROVIDER_LIMIT-spent


def aggregate_time_limit(out):
    return None if necessity_policy(out) else bounded.PROVIDER_LIMIT


def adapt_necessity_engine(engine):
    """Narrow, checked adaptation of private legacy functions; no global limit mutation.

Only cumulative timeout arithmetic and its matching replay/metadata checks vary.
Every other ledger, request, evidence, cache and call/character check stays original.
"""
    import inspect
    from . import data_necessity_v4 as legacy
    # Fail closed if the frozen implementation changes underneath these expressions.
    expected = 'd1c79e634da21243c54ceb0834ba55bf58507d6d0145611c13184f06a0b7d272'
    if file_ref(legacy.__file__)['sha256'] != expected:
        bounded.fail('Frozen necessity source changed; time adaptation needs review')
    engine._authorized_request_timeout = necessity_timeout
    engine._authorized_aggregate_time_limit = aggregate_time_limit
    changes = [('_validate_ledger', 'MODEL_BUDGET_SECONDS-elapsed_total',
                '_authorized_request_timeout(out, elapsed_total)'),
               ('run_prepared', "MODEL_BUDGET_SECONDS-ledger['provider_elapsed_seconds']",
                "_authorized_request_timeout(out, ledger['provider_elapsed_seconds'])"),
               ('verify_prepared', "'max_provider_seconds':MODEL_BUDGET_SECONDS",
                "'max_provider_seconds':_authorized_aggregate_time_limit(out)")]
    for name, before, after in changes:
        source = inspect.getsource(getattr(engine, name))
        if source.count(before) != 1:
            bounded.fail('Unexpected necessity timeout implementation')
        exec(compile(source.replace(before, after), __file__ + ':' + name, 'exec'), engine.__dict__)
    return engine
