import copy

import pytest
from jsonschema import Draft202012Validator, ValidationError

from research_pipeline import eda_ep_execution as bridge, eda_ep_transport as wire
from research_pipeline.common import read_json


def test_strict_wire_preserves_host_and_expands_finite_maps():
    host = bridge.execution_schema()
    before = copy.deepcopy(host)
    registry = read_json(bridge.REGISTRY)
    strict = wire.schema(host, registry)
    assert host == before
    Draft202012Validator.check_schema(strict)

    def check(node):
        assert not (set(node) & (wire.HOST_ONLY | {'const', 'oneOf'}))
        if node.get('type') == 'object':
            assert node['additionalProperties'] is False
            assert node['required'] == list(node.get('properties', {}))
        for key in ['properties', '$defs']:
            for child in node.get(key, {}).values():
                check(child)
        for child in node.get('anyOf', []):
            check(child)
        if 'items' in node:
            check(node['items'])
    check(strict)
    analysis = strict['properties']['analyses']['items']['properties']
    roles = analysis['formula_definition']['anyOf'][1]['properties']['parameters']['properties']['column_roles']
    assert len(roles['anyOf']) == 3
    assert roles['anyOf'][1]['properties']['reported_n']['enum'] == ['F']
    assert strict['properties']['input_refs']['required'] == ['dataset_ids']
    assert list(strict['properties']['input_refs']['properties']) == ['dataset_ids']
    assert analysis['experimental_unit']['enum'] == [op['experimental_unit'] for op in registry['operations'].values()]
    assert analysis['display_spec']['properties']['uncertainty_definition']['enum'] == [
        op['display']['uncertainty_definition'] for op in registry['operations'].values()]


def test_host_still_rejects_duplicates_accepted_by_wire_shape():
    host = {'type': 'object', 'properties': {'rows': {'type': 'array',
            'items': {'type': 'integer'}, 'uniqueItems': True, 'minItems': 1}},
            'required': ['rows'], 'additionalProperties': False}
    strict = wire.schema(host, read_json(bridge.REGISTRY))
    value = {'rows': [1, 1]}
    Draft202012Validator(strict).validate(value)
    with pytest.raises(ValidationError):
        Draft202012Validator(host).validate(value)


def test_unknown_dynamic_map_is_rejected_instead_of_silently_weakened():
    host = {'type': 'object', 'properties': {'unknown': {
        'type': 'object', 'additionalProperties': {'type': 'string'}}},
        'required': ['unknown'], 'additionalProperties': False}
    with pytest.raises(ValueError, match='Undeclared dynamic'):
        wire.schema(host, read_json(bridge.REGISTRY))


def test_wire_uses_exact_visible_semantic_ids_instead_of_prose_aliases():
    scope = {'dataset_ids': {'table'}, 'source_ids': {'table:A1'},
             'rule_ids': {'R034'}, 'reference_sections': {'01', 'B01'}}
    strict = wire.schema(bridge.execution_schema(), read_json(bridge.REGISTRY), scope=scope)
    props = strict['properties']['analyses']['items']['properties']
    section = props['reference_sections']
    Draft202012Validator(section).validate(['01'])
    with pytest.raises(ValidationError):
        Draft202012Validator(section).validate(['01 | CONCENTRATION-TIME OBSERVATIONS'])
    assert props['source_refs']['items']['enum'] == ['table:A1']
    assert strict['properties']['version']['enum'] == ['EP_PLAN_TEST_1.1']
