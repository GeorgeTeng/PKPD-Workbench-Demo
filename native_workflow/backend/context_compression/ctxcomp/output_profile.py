"""Frozen field-ownership profile; old bundles without one retain their contracts."""
import copy
from pathlib import Path

from .io import read_json

DEFAULT = 'DATA_DEFERRED_1.0'


def load_profile(identifier=DEFAULT):
    if identifier is None:
        return None
    profile = read_json(Path(__file__).parent / 'resources/context_output_profile.json')
    if profile['id'] != identifier:
        raise ValueError('Unknown context output profile: ' + str(identifier))
    return profile


def attach(payload, source):
    profile = source.get('context_output_profile')
    if not profile:
        return
    if profile.get('id') != DEFAULT or profile.get('version') != '1.0':
        raise ValueError('Unsupported frozen context output profile')
    payload['context_output_profile'] = copy.deepcopy(profile)
    payload['instructions'] += '\n' + profile['instructions']
    if payload['stage'] == 'context':
        payload['schema'] = copy.deepcopy(payload['schema'])
        fields = payload['schema']['properties']['context']['properties']['data']['properties']
        for name in profile['empty_context_arrays']:
            fields[name] = {**fields[name], 'maxItems': 0}
    if 'context' in payload:
        for name in profile['empty_context_arrays']:
            if payload['context']['data'][name] != []:
                raise ValueError('Frozen context output profile requires data.' + name + ' to be empty')
