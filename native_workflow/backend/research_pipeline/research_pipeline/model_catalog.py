"""Source-bound candidate catalog; implementation support is not model validation."""

import csv
import math
from pathlib import Path
import re

from .common import PipelineError, sha256


COLUMNS = ('model_id', 'layer', 'model_name', 'required_data', 'eligible_use',
           'hard_rejection_rule', 'selection_priority')
IMPLEMENTED = {
    'PK_SYS_1C_LIN': ('systemic_pk', 'pk_longitudinal', 'IV; individual or supported one-compartment population mode'),
    'PK_SYS_2C_LIN': ('systemic_pk', 'pk_longitudinal', 'IV; individual mode only'),
    'INPUT_IV_BOLUS': ('input', 'pk_longitudinal', 'Explicit zero administration duration'),
    'INPUT_IV_INF': ('input', 'pk_longitudinal', 'Explicit positive administration duration'),
    'PD_EMAX': ('pd', 'pkpd_index', 'Endpoint Emax; Hill fixed to 1'),
    'PD_SIGMOID': ('pd', 'pkpd_index', 'Endpoint Emax; estimated Hill'),
}


def load_catalog(path):
    path = Path(path).resolve()
    before = sha256(path)
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(COLUMNS):
            raise PipelineError('CATALOG_COLUMNS', f'Expected columns {COLUMNS}')
        models, seen = [], set()
        for row in reader:
            line = reader.line_num
            if None in row or any(not isinstance(row.get(k), str) or not row[k].strip() for k in COLUMNS):
                raise PipelineError('CATALOG_ROW', f'Missing or extra fields at CSV line {line}')
            identifier = row['model_id']
            if not re.fullmatch(r'[A-Z][A-Z0-9_]*', identifier):
                raise PipelineError('CATALOG_ID', f'Invalid model ID at line {line}')
            if identifier in seen:
                raise PipelineError('CATALOG_DUPLICATE_ID', identifier)
            seen.add(identifier)
            if not re.fullmatch(r'[1-9][0-9]*', row['selection_priority']):
                raise PipelineError('CATALOG_PRIORITY', f'Invalid selection priority: {identifier}')
            support = IMPLEMENTED.get(identifier)
            if support and row['layer'] != support[0]:
                raise PipelineError('CATALOG_LAYER_MISMATCH', identifier)
            models.append({**row, 'selection_priority': int(row['selection_priority']),
                           'source_line': line,
                           'implementation': 'AVAILABLE_WITH_SCOPE_LIMITS' if support else 'NOT_IMPLEMENTED',
                           'module': support[1] if support else None,
                           'implementation_scope': support[2] if support else None,
                           'scientific_acceptance': 'NOT_ESTABLISHED'})
    if not models:
        raise PipelineError('CATALOG_EMPTY', 'No candidate models')
    if sha256(path) != before:
        raise PipelineError('CATALOG_CHANGED', 'Catalog changed while reading')
    return {'schema_version': '1.0', 'source': {'path': str(path), 'sha256': before},
            'models': models, 'scientific_review': 'NOT_GRANTED_BY_CATALOG',
            'rule_handling': 'Required data and rejection text are preserved for review, not executed as instructions.'}


def search_catalog(catalog, query='', layer=None):
    tokens = query.casefold().split()
    matches = []
    for row in catalog['models']:
        body = ' '.join(str(row[k]) for k in COLUMNS).casefold()
        if (layer is None or row['layer'] == layer) and all(token in body for token in tokens):
            matches.append(row)
    return sorted(matches, key=lambda row: (row['selection_priority'], row['model_id']))


def require_catalog_models(catalog, identifiers, module, options, metadata, worker):
    if not isinstance(identifiers, list) or not identifiers or any(not isinstance(x, str) for x in identifiers) or len(identifiers) != len(set(identifiers)):
        raise PipelineError('CATALOG_SELECTION_REQUIRED', 'Supply distinct model_catalog_ids')
    by_id = {row['model_id']: row for row in catalog['models']}
    rows = []
    for identifier in identifiers:
        if identifier not in by_id:
            raise PipelineError('CATALOG_MODEL_NOT_FOUND', identifier)
        row = by_id[identifier]
        if row['implementation'] == 'NOT_IMPLEMENTED':
            raise PipelineError('CATALOG_MODEL_NOT_IMPLEMENTED', identifier)
        if row['module'] != module:
            raise PipelineError('CATALOG_MODULE_MISMATCH', identifier)
        rows.append(row)
    primary = [r for r in rows if r['layer'] in ('systemic_pk', 'pd')]
    if len(primary) != 1:
        raise PipelineError('CATALOG_PRIMARY_MODEL', 'Select exactly one structural PK or endpoint model per step')
    if module == 'pk_longitudinal':
        expected = 'PK_SYS_1C_LIN' if options.get('compartments', 1) == 1 else 'PK_SYS_2C_LIN'
        mode = options.get('mode', 'individual')
        if primary[0]['model_id'] != expected or metadata.get('route') != 'IV':
            raise PipelineError('CATALOG_MODEL_CONFIG_MISMATCH', 'PK compartment count or IV route differs from selected model')
        if expected == 'PK_SYS_2C_LIN' and mode != 'individual':
            raise PipelineError('CATALOG_MODEL_CONFIG_MISMATCH', 'Two-compartment population fitting is not implemented')
        inputs = [r['model_id'] for r in rows if r['layer'] == 'input']
        if len(inputs) != 1:
            raise PipelineError('CATALOG_INPUT_REQUIRED', 'Select one IV input model explicitly')
        schedules = worker.get('doses') if mode == 'individual' else worker.get('records')
        if not schedules:
            raise PipelineError('CATALOG_INPUT_TIMING_MISSING', 'Explicit dose administration duration is required')
        durations = [r.get('duration_h') for r in schedules]
        if any(not isinstance(d, (int, float)) or isinstance(d, bool) or not math.isfinite(d) or d < 0 for d in durations):
            raise PipelineError('CATALOG_INPUT_TIMING_MISSING', 'Missing or invalid duration_h')
        is_bolus = inputs[0] == 'INPUT_IV_BOLUS'
        if (is_bolus and any(d != 0 for d in durations)) or (not is_bolus and any(d <= 0 for d in durations)):
            raise PipelineError('CATALOG_INPUT_MISMATCH', 'Selected input model does not match administration duration')
        if (mode == 'population_bolus' and not is_bolus) or (mode == 'population_infusion_per_kg' and is_bolus):
            raise PipelineError('CATALOG_INPUT_MISMATCH', 'Population mode does not match selected input')
    else:
        expected = 'PD_SIGMOID' if options.get('estimate_hill', False) else 'PD_EMAX'
        if primary[0]['model_id'] != expected or options.get('mode', 'compare_indices') not in ('endpoint_emax', 'compare_indices'):
            raise PipelineError('CATALOG_MODEL_CONFIG_MISMATCH', 'Endpoint mode or Hill setting differs from selected model')
    return {'status': 'IMPLEMENTATION_CONFIG_MATCHED', 'source': catalog['source'],
            'selected_models': rows, 'scientific_acceptance': 'PENDING_HUMAN_REVIEW',
            'rejection_rules_evaluated': False,
            'limit': 'Checks implementation/configuration only. Empirical identifiability, validation and textual rejection rules still need scientific review.'}
