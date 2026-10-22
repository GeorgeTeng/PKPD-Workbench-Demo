"""Common host contract for minimum sufficient model context on every route."""
import copy
from pathlib import Path

from .common import read_json, sha256

HERE = Path(__file__).parent / 'resources/context_builder'
POLICY = HERE / 'minimal_context.v1.json'
ROUTES = HERE / 'routes.v2.json'


def load_policy():
    before = sha256(POLICY)
    route_before = sha256(ROUTES)
    policy = read_json(POLICY)
    routes = read_json(ROUTES)['routes']
    if (policy.get('version') != 'MINIMAL_TASK_CONTEXT_1.0'
            or policy.get('scope') != 'ALL_CONTEXTBUILDER_ROUTES'
            or policy.get('implicit_full_payload_fallback') is not False
            or set(policy.get('routes', {})) != set(routes)):
        raise ValueError('Every ContextBuilder route requires an explicit minimal-context profile')
    for name, entry in policy['routes'].items():
        profile = policy.get('profiles', {}).get(entry.get('profile'))
        if not isinstance(profile, dict) or not all(profile.get(k) for k in ('purpose', 'model_needs', 'evidence_boundary')):
            raise ValueError('Incomplete minimal-context profile for ' + name)
        retrieval = entry.get('method_retrieval', {})
        if retrieval.get('mode') not in {'NONE', 'EXPLICIT_UNANSWERED_QUESTIONS'}:
            raise ValueError('Every workflow step requires an explicit retrieval boundary')
        for key in ('rule_paths', 'reference_fields'):
            paths = entry.get(key)
            if (not isinstance(paths, list) or any(not isinstance(path, list) or not path
                    or any(not isinstance(part, str) or not part for part in path) for path in paths)):
                raise ValueError('Invalid declared context paths for ' + name)
        if retrieval['mode'] == 'EXPLICIT_UNANSWERED_QUESTIONS':
            if not all(retrieval.get(key) for key in ('target', 'project_path', 'consumer_route', 'allowed_stages')):
                raise ValueError('Incomplete retrieval task contract for ' + name)
    if sha256(POLICY) != before or sha256(ROUTES) != route_before:
        raise ValueError('Minimal-context policy changed during resolution')
    return policy, {'path': str(POLICY.resolve()), 'sha256': before}


def route_contract(route):
    policy, binding = load_policy()
    entry = policy['routes'].get(route)
    if entry is None:
        raise ValueError('No minimal-context contract for route: ' + route)
    return {'version': policy['version'], 'governance_rule': policy['governance_rule'],
            'route': route, 'profile': entry['profile'],
            **copy.deepcopy(policy['profiles'][entry['profile']]),
            'identifiers': policy['identifiers'], 'required_audit': policy['required_audit'],
            'policy_ref': binding,
            'status': 'TASK_CONTRACT_NOT_SCIENTIFIC_OR_RESPONSE_QUALITY_APPROVAL'}
