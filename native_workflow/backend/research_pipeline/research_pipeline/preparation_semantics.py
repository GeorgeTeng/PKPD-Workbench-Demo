"""Small source-bounded metadata rules; no numeric changes or scientific release."""
import copy
import re
from decimal import Decimal, InvalidOperation


def row_value_statuses(raw_values, column_map, source_notes, base_statuses):
    """Respect the explicitly stated CENS=1/Y convention without guessing a limit.

    column_map maps stored field keys to original headers. Call with independently
    reconstructed snapshot values/statuses in QC, not the output being checked.
    """
    result = dict(base_statuses)
    headers = list(column_map.values())
    if headers.count('Y') != 1 or headers.count('CENS') != 1:
        return result
    statements = [s.strip().casefold() for s in re.split(r'[.;\n]', source_notes or '')]
    if 'cens=1 flags censored y' not in statements:
        return result
    y = next(k for k, h in column_map.items() if h == 'Y')
    flag = next(k for k, h in column_map.items() if h == 'CENS')
    cens = raw_values.get(flag)
    if isinstance(cens, bool) or cens not in (1, '1', '1.0'):
        return result
    if result.get(y) == 'QUANTIFIED':
        result[y] = 'CENSORED'
    elif result.get(y) in {'EMPTY_SLOT', 'MISSING_OR_NOT_APPLICABLE'}:
        result[y] = 'MISSING_CENSORED_OBSERVATION'
    return result


def _literal_quantity(quote, value, unit):
    # Match the already reviewed literal, never parse an arbitrary dose from text.
    literal = re.escape(str(value).strip() + ' ' + unit).replace(r'\ ', r'\s+')
    return re.search(r'(?<![\w.])' + literal + r'(?![\w/])', quote) is not None


def dose_metadata(label, stated_values):
    """Copy local, evidence-backed dose quantities; never assign doses to rows.

    `stated_values` is the hydrated reviewed list (item_id plus exact evidence).
    A unique literal route/dose statement supports table-level metadata only.
    Multiple/conflicting or other-agent quantities remain explicit candidates.
    """
    item_id = label.get('item_id', label.get('source_item_id'))
    route = label.get('route', 'NOT_FOUND')
    candidates = []
    for entry in stated_values:
        if not item_id or entry.get('item_id') != item_id:
            continue
        value, unit = entry.get('value'), entry.get('unit')
        if unit not in {'mg/kg', 'mg/kg/day', 'mg', 'ug/kg', 'µg/kg'} or value in (None, '', 'NOT_FOUND'):
            continue
        evidence = [copy.deepcopy(e) for e in entry.get('evidence', [])
                    if e.get('source', '').startswith(item_id + ':') and e.get('quote')]
        if not any(_literal_quantity(e['quote'], value, unit) for e in evidence):
            continue
        candidate = {k: copy.deepcopy(entry.get(k, 'NOT_FOUND'))
                     for k in ('quantity', 'value', 'unit', 'subject', 'qualifiers')}
        candidate['evidence'] = evidence
        if candidate not in candidates:
            candidates.append(candidate)
    if not candidates:
        return 'NOT_FOUND'
    quantities = {(str(c['value']), c['unit']) for c in candidates}
    supported = False
    if len(quantities) == 1 and route in {'IV', 'IP', 'SC', 'IT', 'PO', 'IM'}:
        value, unit = next(iter(quantities))
        try:
            scalar = Decimal(value)
            positive_scalar = scalar.is_finite() and scalar > 0
        except InvalidOperation:
            positive_scalar = False
        phrase = value + ' ' + unit
        # Restricted adjacency of the source-stated route and quantity. A mass
        # unit alone cannot establish target-drug applicability or a regimen.
        supported = positive_scalar and any(
            re.search(r'(?<!\w)' + re.escape(text) + r'(?![\w/])', e['quote'])
            for c in candidates for e in c['evidence']
            for text in (route + ' ' + phrase, phrase + ' ' + route))
        drug = label.get('drug', 'NOT_FOUND').casefold()
        species = label.get('species', 'NOT_FOUND').casefold()
        subjects = [str(c['subject']).casefold() for c in candidates]
        if any(s not in {'not_found', drug, species} for s in subjects):
            supported = False
    if not supported:
        return {'status': 'SOURCE_REPORTED_APPLICABILITY_UNRESOLVED',
                'candidates': candidates, 'per_record_assignment': False}
    evidence = []
    qualifiers = []
    for candidate in candidates:
        for span in candidate['evidence']:
            if span not in evidence: evidence.append(span)
        for qualifier in candidate['qualifiers'] if isinstance(candidate['qualifiers'], list) else []:
            if qualifier not in qualifiers: qualifiers.append(qualifier)
    return {'status': 'SOURCE_STATED', 'value': value, 'unit': unit, 'route': route,
            'dose_basis': label.get('dose_basis', 'NOT_FOUND'),
            'dosing_regimen': label.get('dosing_regimen', 'NOT_FOUND'),
            'qualifiers': qualifiers, 'evidence': evidence,
            'applicability': 'SOURCE_TABLE_ONLY', 'per_record_assignment': False}
