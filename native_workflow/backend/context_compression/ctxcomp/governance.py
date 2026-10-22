"""Model/API-independent conventions shared by every workflow step."""
import copy
from contextlib import contextmanager
from contextvars import ContextVar
from .io import read_json, digest
from .paths import RULES

RESOURCE = RULES / 'general' / 'workflow_governance.json'
_request_transform = ContextVar('workflow_request_transform', default=None)


@contextmanager
def request_transform(transform):
    """Explicit run-local preparation before adapter validators capture identity."""
    token = _request_transform.set(transform)
    try:
        yield
    finally:
        _request_transform.reset(token)


def load_governance():
    value = read_json(RESOURCE)
    ids = [rule['id'] for rule in value['rules']]
    if value['scope'] != 'ALL_WORKFLOW_STEPS' or ids != [f'G{i:03}' for i in range(1, 9)]:
        raise ValueError('Current workflow governance must contain G001-G008 in order')
    if not value.get('instruction_prefix') or any(
            not rule.get('instruction') or not rule.get('actions') for rule in value['rules']):
        raise ValueError('Shared governance must contain complete inline instructions')
    return value


def attach_governance(payload, governance=None):
    """Attach before hashing/saving a request, never inside a provider adapter."""
    value = copy.deepcopy(governance if governance is not None else load_governance())
    if 'governance' in payload and payload['governance'] != value:
        raise ValueError('Conflicting workflow-governance versions in one request')
    payload['governance'] = value
    payload['governance_sha256'] = digest(value)
    # Frozen v1 requests must retain their exact original prefix and hash.
    prefix = value.get('instruction_prefix', (
        'Apply governance rule G001 first, then the rules for this step. '
        'Preserve inherited rule IDs and their source-artifact versions; do not renumber a filtered subset. '
        'Governance is processing policy, not a scientific project rule.\n'))
    if not payload.get('instructions', '').startswith(prefix):
        payload['instructions'] = prefix + payload.get('instructions', '')


def governed_request(payload):
    attach_governance(payload)
    request = {'request_sha256': digest(payload), 'payload': payload}
    transform = _request_transform.get()
    if transform is not None:
        # Suppress recursive preparation while assembling this one request.
        with request_transform(None):
            request = transform(request)
        if digest(request['payload']) != request['request_sha256']:
            raise ValueError('Prepared request identity mismatch')
    return request
