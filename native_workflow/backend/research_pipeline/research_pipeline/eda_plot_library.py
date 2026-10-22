"""Local EP planning guidance; never a renderer registry or rule override."""
import re
from pathlib import Path
from .common import read_json

CATALOG = Path(__file__).parent/'resources/eda/plot_methods.v1.json'


def load():
    library = read_json(CATALOG)
    if (library.get('version') != 'EP_PLOT_METHOD_LIBRARY_1.0' or
            library.get('status') != 'PLANNING_GUIDANCE_NOT_EXECUTION_AUTHORITY' or library.get('language') != 'en'):
        raise ValueError('Unsupported EP plot planning library')
    seen = set()
    for method in library['methods']:
        ident = method['id']
        if not re.fullmatch(r'EPG[0-9]{3}', ident) or ident in seen:
            raise ValueError('Invalid or duplicate EP plot method ID')
        seen.add(ident)
        for key in ['name','family','question','required_inputs','applicability','limitations','ec_preparation']:
            if not isinstance(method.get(key),str) or not method[key].strip():
                raise ValueError('Missing EP plot method field: '+key)
        execution = method['execution']
        if (execution.get('planning_status') != 'CANDIDATE_GUIDANCE' or
                not isinstance(execution.get('candidate_operation_ids'),list) or
                not isinstance(library.get('execution_authorization'),str) or not library['execution_authorization'].strip()):
            raise ValueError('A plot card cannot assert execution authorization')
        if not set(method['source_ids']) <= set(library['sources']):
            raise ValueError('Unknown plot reference')
    if not seen or not library['selection_instructions'] or not library['shared_options']:
        raise ValueError('Incomplete EP plot library')
    for option in library['shared_options']:
        if not set(option['source_ids']) <= set(library['sources']):
            raise ValueError('Unknown shared-option reference')
    return library
