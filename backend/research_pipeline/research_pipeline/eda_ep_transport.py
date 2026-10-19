"""Strict wire shape for EP; the original host schema remains authoritative.

The provider accepts a JSON Schema subset. This explicit TEST adapter closes
finite operation maps and leaves unsupported lexical/uniqueness checks to the
unchanged host validator. It never repairs or edits a response.
"""
import copy


VERSION = 'EP_STRICT_WIRE_1.2'
HOST_ONLY = {'$schema', 'uniqueItems', 'minLength', 'maxLength', 'minProperties', 'maxProperties'}


def schema(host_schema, registry, *, scope=None):
    def fixed_map(values):
        return {'type': 'object', 'properties': {
            key: {'type': 'string', 'enum': [value]} for key, value in values.items()},
            'required': list(values), 'additionalProperties': False}

    def visit(node, path=()):
        if not isinstance(node, dict):
            raise ValueError('EP wire schema node must be an object')
        if isinstance(node.get('additionalProperties'), dict):
            name = path[-1] if path else ''
            if name not in {'column_roles', 'units'}:
                raise ValueError('Undeclared dynamic EP wire map: ' + '/'.join(path))
            variants = []
            for operation in registry['operations'].values():
                candidate = fixed_map(operation[name])
                if candidate not in variants:
                    variants.append(candidate)
            if not variants:
                raise ValueError('EP wire operation signatures required')
            return {'anyOf': variants}
        result = {}
        for key, value in node.items():
            if key in HOST_ONLY:
                continue
            if key == 'const':
                result['enum'] = [copy.deepcopy(value)]
            elif key in {'anyOf', 'oneOf'}:
                result['anyOf'] = [visit(branch, path) for branch in value]
            elif key in {'properties', '$defs'}:
                result[key] = {name: visit(child, (*path, name)) for name, child in value.items()}
            elif key == 'items':
                result[key] = visit(value, (*path, 'items'))
            else:
                result[key] = copy.deepcopy(value)
        if result.get('type') == 'object':
            if result.get('additionalProperties') is not False:
                raise ValueError('EP wire object is not closed: ' + '/'.join(path))
            result['required'] = list(result.get('properties', {}))
        return result

    result = visit(host_schema)
    # Global cell/rule/reference lists repeat the per-analysis citations. Emit
    # only admitted dataset identities here; full version bindings stay host-side.
    references = result['properties'].get('input_refs')
    if references is not None:
        references['properties'] = {'dataset_ids': references['properties']['dataset_ids']}
        references['required'] = ['dataset_ids']
    if 'analyses' in result['properties']:
        analysis = result['properties']['analyses']['items']['properties']
        result['properties']['version'] = {'type': 'string', 'enum': ['EP_PLAN_TEST_1.1']}
        analysis['experimental_unit'] = {'type': 'string', 'enum': list(dict.fromkeys(
            value['experimental_unit'] for value in registry['operations'].values()))}
        analysis['display_spec']['properties']['uncertainty_definition'] = {
            'type': 'string', 'enum': list(dict.fromkeys(
                value['display']['uncertainty_definition'] for value in registry['operations'].values()))}
        if scope is not None:
            # Semantic IDs are finite choices from the exact model-visible
            # evidence. Full headings and unrelated IDs are not aliases.
            for field, key in [('dataset_ids', 'dataset_ids'), ('source_refs', 'source_ids'),
                               ('requirement_ids', 'rule_ids'), ('reference_sections', 'reference_sections')]:
                analysis[field]['items'] = {'type': 'string', 'enum': sorted(scope[key])}
            result['properties']['input_refs']['properties']['dataset_ids']['items'] = {
                'type': 'string', 'enum': sorted(scope['dataset_ids'])}
    return result
