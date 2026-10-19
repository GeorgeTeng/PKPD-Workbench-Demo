"""EDA request assembly only; no model calls, R execution or release authority.

The stage adapter admits Data and materializes authorized evidence before using
this module. Paths alone are not evidence contents or proof of Data approval.
This adapter never searches files referenced inside supplied artifacts.
"""
import argparse
import copy
import re
from ctxcomp import governance

from . import context_builder as cb, context_routes
from .common import BACKEND, RULES, read_json

PACK = RULES / 'eda/eda_rules.json'
PROMPTS = BACKEND / 'prompts/stage_contracts/v1'
MODEL_OUTPUT = {'EP-plan': 'eda_plan', 'EI-findings': 'eda_findings', 'ER-review': 'eda_review'}
TRANSPORT_SCOPE = {
    'mode': 'JSON_ONLY',
    'rendered_images_supplied': False,
    'boundary': 'Only supplied JSON/text is visible. File paths are locators, not inspected contents. '
                'Rendered images are not transmitted by this transport. Disclose unreviewed images '
                'and any missing result/plot rows; do not claim visual verification.',
}


def _contract(call_id):
    if call_id not in context_routes.EDA:
        cb.fail('Unsupported EDA model call: ' + str(call_id))
    refs = {'eda_rules': cb.file_ref(PACK),
            'eda_prompt_manifest': cb.file_ref(PROMPTS / 'manifest.json'),
            'eda_context_adapter': cb.file_ref(__file__)}
    pack = read_json(PACK)
    manifest = read_json(PROMPTS / 'manifest.json')['stages']['eda']
    prompt_path = PROMPTS / manifest['file']
    refs['eda_prompt'] = cb.file_ref(prompt_path)
    prompt = prompt_path.read_text(encoding='utf-8')
    call = next(c for c in pack['calls'] if c['id'] == call_id)
    operation = context_routes.EDA[call_id]
    if call['prompt_operation'] != operation or operation not in manifest['operations']:
        cb.fail('EDA prompt operation differs from route')
    agent = next(a for a in pack['agents'] if a['id'] == call['agent'])
    if agent.get('call') != call_id or agent['execution'] not in {'MODEL', 'MODEL_REVIEW_HOST_HANDOFF'}:
        cb.fail('EDA call is not a model operation')
    def section(tag):
        matches = re.findall(r'^\[' + re.escape(tag) + r'\]\s*\n(.*?)^\[END\]', prompt, re.M | re.S)
        if len(matches) != 1:
            cb.fail('Missing or ambiguous EDA prompt section: ' + tag)
        return matches[0].strip()
    instructions = section('STAGE') + '\n\n' + section('OPERATION:' + operation)
    reference = pack['source']['scientific_reference']
    reference_path = PACK.parent / reference['file']
    refs['eda_scientific_reference'] = cb.file_ref(reference_path)
    if refs['eda_scientific_reference']['sha256'] != reference['sha256']:
        cb.fail('EDA scientific reference changed from its bound snapshot')
    scientific_reference = {
        'source_id': 'EDA_SCIENTIFIC_REFERENCE', 'locator': reference['file'],
        'role': 'Method and display guidance; not observed project data.',
        'text': reference_path.read_text(encoding='utf-8'),
    }
    cb.check_refs(refs)
    return pack, call, agent, instructions, scientific_reference, refs


def _fixed_sections(pack, call, instructions, reference):
    payload = {
        'stage': call['id'], 'agent': call['agent'], 'operation': call['operation'],
        'instructions': instructions, 'eda_scope': pack['scope'],
        'processing_rules': [r for r in pack['rules'] if call['id'] in r['calls']],
        'scientific_reference': reference,
        'output_contract': pack['artifact_contracts'][MODEL_OUTPUT[call['id']]],
        'transport_scope': TRANSPORT_SCOPE,
    }
    # Match the existing provider convention before hashing and comparison.
    # attach_governance is idempotent, so reconstruction adds no second prefix.
    governance.attach_governance(payload)
    return payload


def _input_names(agent):
    return set(agent['inputs']) - {'human_confirmation', 'scientific_reference'}


def validate_payload(payload, operation, schema):
    """Recheck bindings and authoritative clauses at every builder boundary."""
    pack, call, agent, instructions, reference, refs = _contract(payload.get('stage'))
    if call['prompt_operation'] != operation:
        cb.fail('EDA operation does not match route')
    recorded = payload.get('eda_context_bindings')
    if not isinstance(recorded, dict) or any(recorded.get(k) != v for k, v in refs.items()):
        cb.fail('Missing or changed EDA context bindings; rebuild the request')
    cb.check_refs(recorded)
    for name, expected in _fixed_sections(pack, call, instructions, reference).items():
        if payload.get(name) != expected:
            cb.fail('EDA authoritative context mismatch: ' + name)
    for name in _input_names(agent):
        if not isinstance(payload.get(name), dict) or not payload[name]:
            cb.fail('Missing EDA input object: ' + name)
    if call['id'] == 'EP-plan' and not isinstance(payload['task_context'].get('implemented_r_operations'), list):
        cb.fail('EDA Planner requires the explicit implemented_r_operations registry (empty is valid)')
    required = pack['artifact_contracts'][MODEL_OUTPUT[call['id']]]['required_fields']
    if schema.get('type') != 'object' or not set(required).issubset(schema.get('required', [])):
        cb.fail('EDA output schema must require the existing artifact contract fields')
    return recorded


def prepare(call_id, inputs, schema, *, input_bindings=None):
    """Prepare one immutable request. Admission/semantic validation stays upstream.

    Inputs must contain exactly this agent's supplied evidence objects. The bound
    scientific reference and operation prompt are loaded once by the host; no
    retrieval/model selection is performed. The returned bundle is not approval
    or authorization to execute the still-disabled EDA runtime.
    """
    pack, call, agent, instructions, reference, refs = _contract(call_id)
    if not isinstance(inputs, dict) or set(inputs) != _input_names(agent):
        cb.fail('EDA inputs must be exactly: ' + ', '.join(sorted(_input_names(agent))))
    for key, value in (input_bindings or {}).items():
        if key in refs and refs[key] != value:
            cb.fail('Conflicting EDA binding: ' + key)
        refs[key] = value
    payload = {**_fixed_sections(pack, call, instructions, reference),
               **copy.deepcopy(inputs), 'eda_context_bindings': refs}
    return cb.build_context('eda', call['prompt_operation'], payload, schema)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--call', required=True, choices=tuple(context_routes.EDA))
    parser.add_argument('--inputs', required=True, help='JSON containing admitted, materialized input objects')
    parser.add_argument('--schema', required=True, help='Stage response JSON schema, not inferred by the builder')
    parser.add_argument('--out', required=True, help='New directory for the exact context preview')
    args = parser.parse_args()
    refs = {'eda_supplied_inputs': cb.file_ref(args.inputs), 'eda_response_schema': cb.file_ref(args.schema)}
    bundle = prepare(args.call, read_json(args.inputs), read_json(args.schema), input_bindings=refs)
    from .context_linear import export_preview
    export_preview(bundle['request'], args.out)
    print('EDA context preview saved. Model calls: 0. EDA runtime remains disabled.')


if __name__ == '__main__':
    main()
