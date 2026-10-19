"""Shared exact-excerpt contract and exhaustive binding diagnostics. No repair."""
import copy
import json
from .paths import RULES
from .matching import contains, loose
from .rules import host_requirement

CONTRACT = json.loads((RULES/'compression/scientific_extraction.json').read_text(encoding='utf-8'))['binding_contract']


# Where a value may be found in its cited evidence, most specific first. Every place is exact source text; the
# location says how far the value sits from the quote so that reviewers can check the pairing. TABLE_CONTEXT (the
# cited row's table title and header rows) counts from compression rules 1.29.0 only.
LOCATIONS = ('QUOTE', 'SAME_LINE', 'SAME_ROW_CELL', 'SHEET_NAME', 'COLUMN_HEADER', 'TABLE_CONTEXT', 'SAME_SOURCE_UNIT')
STRICT = {'loose': False, 'table_headers': {}}


def options(source):
    """The binding checks of a run bundle or request payload. From compression rules 1.29.0 a value also matches
    after normalization (CC002 quote_matching NORMALIZED) and in the title and header rows of a cited spreadsheet
    row's table (CC002 binding_locations TABLE_CONTEXT); earlier runs match exactly in the places above."""
    table = host_requirement(source, 'CC002').get('binding_locations') == 'TABLE_CONTEXT'
    return {'loose': loose(source), 'table_headers': {s['id']: s['table_header_ids'] for s in source.get('sources', [])
                                                      if table and s.get('table_header_ids')}}


def spreadsheet_row(unit):
    """A spreadsheet row unit as {'sheet', 'cells'}, or None for running text."""
    try: row = json.loads(unit['text'])
    except (TypeError, ValueError): return None
    return row if isinstance(row, dict) and isinstance(row.get('cells'), list) else None


def sheet_key(unit):
    """The file and sheet of a spreadsheet row unit (F0004_S03R000192 -> F0004_S03)."""
    source = unit['source_id']; cut = source.rfind('R')
    return source[:cut] if cut > 0 else source


def cell_values(unit):
    """A unit's spreadsheet cell values, or its text."""
    row = spreadsheet_row(unit)
    return [str(c.get('value', '')) for c in row['cells'] if isinstance(c, dict)] if row else [unit['text']]


def value_location(value, evidence, lookup, units, options=STRICT):
    """The first place in the cited, verified evidence that contains value, or None."""
    places = {name: [] for name in LOCATIONS}
    for e in evidence:
        places['QUOTE'].append(e['quote'])
        unit = lookup[e['unit_id']]; text = unit['text']; row = spreadsheet_row(unit)
        headers = options['table_headers'].get(unit['source_id'], [])
        places['TABLE_CONTEXT'] += [v for u in units if u['source_id'] in headers for v in cell_values(u)]
        if row is None:
            at = text.find(e['quote']); start = text.rfind('\n', 0, at) + 1; end = text.find('\n', at + len(e['quote']))
            places['SAME_LINE'].append(text[start:None if end < 0 else end]); places['SAME_SOURCE_UNIT'].append(text)
            continue
        cells = [c for c in row['cells'] if isinstance(c, dict)]
        places['SAME_ROW_CELL'] += [str(c.get('value', '')) for c in cells]
        places['SHEET_NAME'].append(str(row.get('sheet', '')))
        cited = [c for c in cells if str(c.get('value', '')) and (str(c.get('value', '')) in e['quote'] or e['quote'] in str(c.get('value', '')))]
        columns = {c.get('column') for c in cited}; first_row = min((c.get('row', 0) for c in cited), default=0)
        for other in units:
            if other is unit or sheet_key(other) != sheet_key(unit): continue
            above = spreadsheet_row(other)
            if above and above.get('sheet') == row.get('sheet'):
                places['COLUMN_HEADER'] += [str(c.get('value', '')) for c in above['cells'] if isinstance(c, dict)
                    and c.get('column') in columns and isinstance(c.get('row'), int) and c['row'] < first_row]
    return next((name for name in LOCATIONS if any(contains(text, value, options['loose']) for text in places[name])), None)


def binding_diagnostics(requirements, units, options=STRICT):
    """Input shape is checked by the response schema; source text is untrusted."""
    lookup = {u['id']:u for u in units}
    issues = []; total = 0; located = []
    for ri, record in enumerate(requirements['items']):
        components = {c['id']:c for c in record['components']}
        for bi, binding in enumerate(record['science']['bindings']):
            total += 1; selected = binding['component_ids']; evidence = []
            for cid in dict.fromkeys(selected):
                for span in components.get(cid, {}).get('evidence', []):
                    unit = lookup.get(span['unit_id'])
                    verified = bool(unit and unit['source_id']==span['source_id']
                        and span['quote'].strip() and span['quote'] in unit['text'])
                    evidence.append({'component_id':cid, **span, 'source_verified':verified})
            reason = None
            if not selected or len(selected)!=len(set(selected)) or not set(selected)<=components.keys():
                reason = 'INVALID_COMPONENT_SELECTION'
            elif not binding['value'].strip(): reason = 'EMPTY_VALUE'
            elif not evidence or any(not e['source_verified'] for e in evidence): reason = 'CITED_EVIDENCE_INVALID'
            else:
                where = value_location(binding['value'], evidence, lookup, units, options)
                if where is None: reason = 'VALUE_NOT_IN_CITED_SOURCE'
                elif where != 'QUOTE':
                    located.append({'item_id':record['id'], 'field':binding['field'], 'binding_index':bi,
                        'value':binding['value'], 'location':where})
            if reason:
                correction = ('Select non-duplicate component IDs belonging to this item; retain the correct study and conditions.'
                    if reason=='INVALID_COMPONENT_SELECTION' else
                    'Correct the source ID, unit ID or quotation using the supplied source unit. Do not manufacture source text.'
                    if reason=='CITED_EVIDENCE_INVALID' else
                    'Copy one continuous exact excerpt of the cited source into value: from a quote, the rest of its line or source unit, '
                    'its spreadsheet row, sheet name or column header' + (", or its table's title and header rows"
                    if options['table_headers'] else '') + '. Put faithful compressed meaning in statement; split distinct '
                    'values into separate bindings and preserve linked conditions.')
                issues.append({'item_id':record['id'], 'field':binding['field'], 'binding_index':bi,
                    'path':f'/requirements/items/{ri}/science/bindings/{bi}/'+('component_ids' if reason=='INVALID_COMPONENT_SELECTION' else 'value'),
                    'proposed_value':binding['value'], 'component_ids':selected, 'evidence':evidence,
                    'reason':reason, 'what_to_change':correction})
    return {'schema_version':'1.0', 'contract_version':CONTRACT['version'], 'total_bindings':total,
        'issue_count':len(issues), 'affected_item_count':len({i['item_id'] for i in issues}), 'issues':issues,
        'outside_quote':located,
        'check_scope':'Exact source location and wording only. Counts are not counts of proven scientific errors. '
            'outside_quote lists values found next to, not inside, their quote; reviews check that pairing.',
        'automatic_repair':False, 'scientific_approval':False}


def without(requirements, issues):
    """The inventory without the flagged bindings and method references (issues name binding_index or ref_index)."""
    probe = copy.deepcopy(requirements)
    bindings = {(i['item_id'], i['binding_index']) for i in issues if 'binding_index' in i}
    refs = {(i['item_id'], i['ref_index']) for i in issues if 'ref_index' in i}
    for record in probe['items']:
        science = record['science']
        science['bindings'] = [b for k, b in enumerate(science['bindings']) if (record['id'], k) not in bindings]
        science['method_refs'] = [m for k, m in enumerate(science['method_refs']) if (record['id'], k) not in refs]
    return probe


class BindingValidationError(ValueError):
    code = 'MODEL_BINDING_INVALID'

    def __init__(self, details):
        self.validation_details = details
        first = details['issues'][0]
        super().__init__(f"{details['issue_count']} binding validation issue(s) across {details['affected_item_count']} item(s). "
            f"First: {first['item_id']} / {first['field']} at {first['path']}: {first['reason']}. "
            'Preserve original units/wording in value; use statement for compressed meaning.')
