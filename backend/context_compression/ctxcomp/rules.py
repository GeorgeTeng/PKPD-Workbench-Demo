"""Trusted processing rules are snapshotted, scoped and sent inline to each agent."""
import copy
from .io import read_json, digest
from .governance import load_governance, attach_governance
from .paths import RULES


def frozen_rule(source, rule_id):
    """A rule of the run's frozen processing_rules, from a run bundle or a request payload; {} when absent."""
    return next((r for r in source.get('processing_rules', {}).get('rules', []) if r['id'] == rule_id), None) or {}


def host_requirement(source, rule_id):
    """A frozen rule's host_requirement; {} when the run's rules have none."""
    return frozen_rule(source, rule_id).get('host_requirement', {})

RESOURCE = RULES / 'compression'


def _check_general_dependencies(rules, governance):
    available = {r['id'] for r in (governance or {}).get('rules', [])}
    required = {rid for rule in rules for rid in rule.get('general_rules', [])}
    if required - available:
        raise ValueError('Missing shared governance for compression extensions: '
                         + ', '.join(sorted(required - available)))


def _check_terminology_appendix(details, profile):
    """Check references, not scientific completeness or semantic applicability."""
    appendix = details['terminology_appendix']
    mapping = appendix['categories']
    if set(mapping) != set(details['preserve']):
        raise ValueError('CC005 terminology mapping must cover all preservation categories')
    ids = [group['id'] for group in profile['groups']]
    if len(ids) != len(set(ids)):
        raise ValueError('CC005 terminology appendix has duplicate group IDs')
    for category, references in mapping.items():
        if len(references) != len(set(references)) or set(references) - set(ids):
            raise ValueError('CC005 terminology mapping has invalid references: ' + category)
    if appendix['profile'] != 'pk_binding_knowledge':
        raise ValueError('CC005 terminology appendix must use the supplied PK profile')


def load_rules():
    pack = read_json(RESOURCE / 'compression_rules.json')
    pack['governance'] = load_governance()
    pack['agent_contracts'] = read_json(RESOURCE / 'compression_agents.json')
    for name in ('scientific_extraction', 'pk_binding_knowledge'):
        pack[name] = read_json(RESOURCE / (name + '.json'))
    expected = {f'CC{i:03}' for i in range(1, 20) if i not in {10, 13, 14, 18}}
    ordered = [r['id'] for r in pack['rules']]
    groups = [rid for group in pack['logical_order']['groups'] for rid in group['rules']]
    if set(ordered) != expected or len(ordered) != len(expected) or ordered != groups:
        raise ValueError('Compression rules must cover each active ID once in the declared logical order')
    for rule in pack['rules']:
        if 'details_file' in rule:
            name = rule.pop('details_file')
            if name != 'cc005_details.json':
                raise ValueError('Unexpected compression rule details resource')
            rule['details'] = read_json(RESOURCE / name)
        for field in ('agents', 'instruction', 'actions', 'evidence', 'on_failure'):
            if not rule.get(field): raise ValueError(f"Incomplete {rule['id']}: {field}")
    if len(next(r for r in pack['rules'] if r['id'] == 'CC005')['details']['preserve']) != 13:
        raise ValueError('CC005 must contain all 13 approved preservation categories')
    _check_terminology_appendix(
        next(r for r in pack['rules'] if r['id'] == 'CC005')['details'],
        pack['pk_binding_knowledge'])
    _check_general_dependencies(pack['rules'], pack['governance'])
    return pack


def intake_agent_contract():
    """A host-executed upload contract, independent of compression-model prompts."""
    pack = read_json(RULES / 'intake' / 'intake_rules.json')
    return {'schema_version': '1.0', 'stage': 'intake',
            'executor': 'DETERMINISTIC_FILE_READER',
            'task': 'Check and register uploads before releasing inputs to compression.',
            'inputs': ['Uploaded file references and hashes', 'Proposal selection', 'Reference-access restrictions'],
            'outputs': ['agent_contract.json', 'manifest.json', 'readability_report.json'],
            'governance': load_governance(), 'processing_rules': pack}


def attach_rules(payload, pack):
    if payload['stage'] not in pack['scope']['internal_roles']:
        raise ValueError('CC rules apply only to context compression and its internal reviews')
    selected = copy.deepcopy([r for r in pack['rules'] if 'all' in r['agents'] or payload['stage'] in r['agents']])
    _check_general_dependencies(selected, pack.get('governance'))
    payload['processing_rules'] = {'version': pack['version'], 'authority': pack['authority'],
                                   'scope': copy.deepcopy(pack['scope']), 'rules': selected}
    for name in ('scientific_extraction', 'pk_binding_knowledge'):
        profile = pack.get(name)
        if profile and payload['stage'] in profile['scope']:
            payload['processing_rules'][name] = copy.deepcopy(profile)
    payload['processing_rules_sha256'] = digest(payload['processing_rules'])
    contracts = pack.get('agent_contracts')
    if contracts:
        payload['agent_contract'] = copy.deepcopy({
            **contracts['shared_contract'], **contracts['agents'][payload['stage']]})
        if payload['stage'] == 'context_review':
            payload['review_agent_contracts'] = copy.deepcopy(contracts)
    payload['instructions'] = (
        'The inline processing_rules are mandatory workflow instructions for this agent, not source facts. '
        'Read every assigned rule including all CC005 details. Apply relevant actions and report violations '
        'through this stage response schema. Do not require unstated experimental details to exist. '
        'Never copy CC rules into the project rules in main.json.\n' + payload['instructions'])
    if pack.get('governance'):
        attach_governance(payload, pack['governance'])


def require_rules(bundle):
    if not bundle.get('processing_rules'):
        raise ValueError('This run predates the complete CC rules. Initialize a new run from the original files; '
                         'historical results and approvals must not inherit the new rules silently.')
