"""Compact scoped facts, not scientific adequacy. No provider or mutable legacy state."""
import copy
import json
import re
from pathlib import Path

from ctxcomp.io import digest
from ctxcomp.schemas import S, arr, enum, obj
from . import data_coverage_v4 as legacy
from . import data_agents as d, data_requirement_check as c
from .adequacy import file_ref
from .common import read_json

VERSION = 'COVERAGE_FACTS_5.0'
TRANSPORT_VERSION = 'SCOPED_FACTS_1.0'
FULL_DERIVATION = 'CONSTITUENT_FACTS_1.0'
MAX_CHECKS = 100
MAX_INPUT_CHARS = 240000
MAX_OUTPUT_ESTIMATE_CHARS = 60000
STATES = ('SUPPORTED', 'PARTIAL', 'CONFLICT', 'UNRESOLVED', 'DEFERRED')
INSTRUCTIONS = '''Check each keyed fact against its exact description and scope. A shared fact may
satisfy identical FIELD definitions only; conditions and scope alignment are separate decisions.
source_rows=[source_id,kind,item_id,exact original content,explicit sparse selector]. Cite printed
selectors only. Headers and descriptors are context, not observed measurements. Rules specify
obligations, never prove an observation. For every positive fact explain why the cited source
supports ALL its conjuncts, including quantity, units, organism, record level and window.
MIC reported in a source note may support the MIC-value field. CFU body values cannot establish
MIC measurement support, drug concentration or a matched PK observation. Do not infer links,
individual identities or variability from group means or other panels. Preserve counterevidence.
s=status,e=support selectors,x=counter selectors,r=concise scientific relevance explanation,
n=needed material (NONE only for SUPPORTED),k=evidence role. Use UNRESOLVED where relevance,
scope or completeness cannot be established; no implicit applicability waiver or global MISSING.
Use lookup_query to identify the concrete unresolved topic for later permitted-source retrieval;
the unseen catalog is not evidence. DEFERRED needs an approved producer/output/first dependency.
Do not produce FULL_REQUIREMENT, method eligibility, numerical analysis, fit or scientific release.
Original required_by is preserved; free-exposure and matched-MIC may be needed at PD index work
before later translation/PTA. Future model/target outputs are not absent original observations.'''


def fail(message):
    d.fail('COVERAGE_V5_FACTS_INVALID', message)


def _chars(value):
    return len(json.dumps(value, ensure_ascii=False))


def _uniq(values, label):
    if len(values) != len(set(values)):
        fail('Duplicate ' + label)
    return set(values)


def _recheck_set(values):
    result = set()
    for value in values:
        if isinstance(value, dict):
            ids = value.get('criterion_ids', [value.get('criterion_id')])
            for cid in ids:
                result.add((value['unit_id'], cid))
        else:
            result.add(tuple(value))
    return result


def _context(plan, base):
    pp = read_json(plan['provenance']['payload_ref']['path'])
    main = read_json(plan['bindings']['main']['path'])
    catalog = copy.deepcopy(base['catalog'])
    # Exact whole operative rule, including structural conditions/exceptions, once per request.
    rules = {}
    for index, rule in enumerate(pp['project_rules']):
        pointer = rule.get('provenance', {}).get('main_pointer', '/rules/' + str(index))
        key = 'main:' + pointer
        original = main['rules'][int(pointer.rsplit('/', 1)[1])]
        rules[key] = {field: copy.deepcopy(original[field]) for field in
                      ('id', 'kind', 'text', 'conditions', 'exceptions', 'scope', 'requirement', 'usage') if field in original}
        for field, value in rules[key].items():
            catalog[key + '/' + field] = {'kind': 'RULE', 'item_id': None,
                'content': value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)}
    return catalog, rules, pp


def _authority_keys(needs, catalog, rules):
    keys = {'main:/objective'} & catalog.keys()
    for need in needs:
        for key in need.get('project_source_ids', []):
            match = re.match(r'^(main:/rules/\d+)(?:/|$)', key)
            if match and match[1] in rules:
                keys.update(k for k in catalog if k.startswith(match[1] + '/'))
                key = match[1]
            if key in catalog:
                keys.add(key)
        for mid in need.get('method_profile_ids', []):
            keys.update(k for k in catalog if k.startswith('method:') and mid in k)
    return keys


def _exclusion(unit, need, scope, catalog, rules):
    """Only the explicit Kp-only PD obligation with an unambiguous original panel label.

    PK scopes and generic provenance needs are NEVER filtered by pathogen mentions.
    Any structured rule condition/exception prevents automatic routing exclusion.
    """
    if not set(unit['method_uses']) <= {'PD_INDEX', 'PD_TARGET'}:
        return None
    if 'K. pneumoniae' not in need['description']:
        return None
    local = [(key, value) for key, value in catalog.items()
             if value['item_id'] in scope['item_ids'] and value['kind'] == 'SOURCE_NOTE']
    text = '\n'.join(v['content'] for _, v in local)
    if re.search(r'(K\.\s*pneumoniae|Klebsiella)', text, re.I):
        return None
    # Narrow original figure-label proof, not a descriptor inference or mere pathogen mention.
    labels = [(key, value) for key, value in local if re.match(
        r'^Figure\s+\S+\s+[—–-]\s+(?:P\. aeruginosa|A\. baumannii|E\. coli)\s+\S+',
        value['content'])]
    if not labels:
        return None
    authorities = []
    covered_uses = set()
    rule_keys = {m[1] for key in need.get('project_source_ids', []) if (m := re.match(r'^(main:/rules/\d+)(?:/|$)', key))}
    for key in rule_keys:
        rule = rules.get(key)
        if not rule or rule.get('exceptions'):
            continue
        conditions = rule.get('conditions', [])
        if any(x != 'Eligible K. pneumoniae data are available for the comparison.' for x in conditions):
            continue
        usage = rule.get('usage', {})
        if usage.get('except_when') or any(x not in conditions for x in usage.get('applies_when', [])):
            continue
        if rule.get('scope', {}).get('matrix', 'NOT_SPECIFIED') not in {'NOT_SPECIFIED', ''}:
            continue
        text = rule['text'].lower()
        if 'k. pneumoniae' not in text:
            continue
        if 'compare' in text and rule.get('scope', {}).get('population') == 'K. pneumoniae':
            covered_uses.add('PD_INDEX'); authorities.append(key + '/text' if key + '/text' in catalog else key)
        if ('targets' in text and ('other pathogens' in text or 'supported k. pneumoniae' in text)):
            covered_uses.add('PD_TARGET'); authorities.append(key + '/text' if key + '/text' in catalog else key)
    if not set(unit['method_uses']) <= covered_uses:
        return None
    return {'unit_id': unit['unit_id'], 'scope_id': unit['scope_id'],
            'requirement_id': need['id'], 'method_uses': unit['method_uses'],
            'state': 'SCOPED_EXCLUSION', 'reason': 'Explicit K. pneumoniae-only PD scope; original panel label identifies another organism.',
            'evidence': [{'source': k, 'quote': v['content']} for k, v in labels],
            'rule_evidence': [{'source': k, 'quote': catalog[k]['content']} for k in sorted(authorities)],
            'derivation': 'EXPLICIT_RULE_AND_ORIGINAL_PANEL_LABEL_1.0',
            'scientific_approval': False}


def _make_payload(units, base, needs, rules, ordinal, extras=None):
    catalog = base['catalog']
    scope_ids = {u['scope_id'] for u in units}
    scopes = [s for s in base['scopes'] if s['id'] in scope_ids]
    local_items = {i for s in scopes for i in s['item_ids']}
    local_items.update(extras or [])
    selected_needs = [needs[k] for k in dict.fromkeys(u['requirement']['id'] for u in units)]
    keys = _authority_keys(selected_needs, catalog, rules)
    keys.update(k for k, v in catalog.items() if v['item_id'] in local_items)
    # Only exact previously admitted rows are carried; this does not read the rest of an old item.
    keys.update(k for u in units for k in u.get('retained_source_ids', []))
    if not keys <= catalog.keys():
        fail('A retained source is absent from the unchanged permitted catalog')
    retained_links = {u['unit_id']: copy.deepcopy(u.get('retained_source_links', [])) for u in units}
    retained_items = {s['id']: sorted({link['item_id'] for u in units if u['scope_id'] == s['id']
                                     for link in retained_links[u['unit_id']]}) for s in scopes}
    rows = [[key, catalog[key]['kind'], catalog[key]['item_id'], catalog[key]['content'], index]
            for index, key in enumerate(catalog) if key in keys and catalog[key]['content'].strip()]
    facts, shared = {}, {}
    for unit in units:
        for spec in unit['criteria']:
            cid = spec['id']
            if cid == 'FULL_REQUIREMENT' or cid in unit.get('fixed_criteria', {}):
                continue
            # Only exact same FIELD semantics within the immutable source scope share a decision.
            shared_field = cid.startswith('FIELD_') and spec['description'] == 'Study and regimen membership'
            key = (unit['scope_id'], spec['description']) if shared_field else (unit['unit_id'], cid)
            fid = shared.get(key)
            if fid is None:
                fid = 'F' + str(len(facts) + 1).zfill(4)
                shared[key] = fid
                facts[fid] = {'scope_id': unit['scope_id'], 'description': spec['description'], 'targets': []}
            facts[fid]['targets'].append({'unit_id': unit['unit_id'], 'criterion_id': cid})
            prior = unit.get('prior_criteria', {}).get(cid, {})
            if prior.get('counterevidence'):
                facts[fid].setdefault('retained_counterevidence', []).append({
                    'unit_id': unit['unit_id'], 'criterion_id': cid,
                    'evidence': copy.deepcopy(prior['counterevidence'])})
        if unit.get('qualification_spec'):
            fid = 'F' + str(len(facts) + 1).zfill(4)
            facts[fid] = {'scope_id': unit['scope_id'], 'description': unit['qualification_spec'],
                          'targets': [{'unit_id': unit['unit_id'], 'criterion_id': 'HOST_MEASUREMENT_QUALIFICATION'}]}
            prior = unit.get('original_full_judgment', {}).get('host_derivation', {}).get('measurement_qualification', {})
            if prior.get('counterevidence'):
                facts[fid]['retained_counterevidence'] = [{'unit_id': unit['unit_id'],
                    'criterion_id': 'HOST_MEASUREMENT_QUALIFICATION', 'evidence': copy.deepcopy(prior['counterevidence'])}]
    return {'version': VERSION, 'transport_version': TRANSPORT_VERSION,
            'part_id': 'FACT' + str(ordinal).zfill(3), 'round': 'ASSIGNED_ONLY',
            'instructions': INSTRUCTIONS, 'units': copy.deepcopy(units), 'facts': facts,
            'scopes': scopes, 'source_rows': rows,
            'visible_item_ids': sorted(local_items | {catalog[k]['item_id'] for k in keys if catalog[k]['item_id'] is not None}),
            'extra_item_ids': sorted(extras or []), 'authorized_extra_items': retained_items,
            'retained_source_links': retained_links,
            'counterevidence_targets': {u['unit_id']: copy.deepcopy(u.get('fixed_criteria', {}))
                                       for u in units if extras and u.get('fixed_criteria')},
            'incomplete_item_ids': base.get('incomplete_item_ids', []),
            'requirements': {n['id']: {k: copy.deepcopy(n[k]) for k in
                             ('description', 'required_by', 'origin', 'project_source_ids', 'method_profile_ids')}
                             for n in selected_needs},
            'scientific_approval': False}


def transport_payload(payload):
    result = copy.deepcopy(payload)
    result['units'] = [{k: copy.deepcopy(u[k]) for k in ('unit_id', 'scope_id', 'method_uses', 'requirement')}
                       for u in payload['units']]
    return result


def response_schema(payload):
    definitions, fields = {}, {}
    scopes = {s['id']: s for s in payload['scopes']}
    for index, (fid, fact) in enumerate(payload['facts'].items()):
        scope = fact['scope_id']
        key = 'scope_' + str(list(scopes).index(scope))
        if key not in definitions:
            allowed = [r[4] for r in payload['source_rows'] if r[2] is None or r[2] in scopes[scope]['item_ids']]
            # Extra sources require explicit local authorization supplied by targeted build.
            allowed += [r[4] for r in payload['source_rows'] if r[2] in payload.get('authorized_extra_items', {}).get(scope, [])]
            allowed += [r[4] for r in payload['source_rows'] if r[2] in payload.get('extra_item_ids', [])]
            selector = arr({'type': 'integer', 'enum': sorted(set(allowed))}) if allowed else arr({'type': 'integer'}, 0)
            if not allowed:
                selector['maxItems'] = 0
            definitions[key] = obj(s=enum(*STATES), e=selector, x=selector, r=S, n=S,
                k=enum('BODY_OBSERVATION', 'NOTE_REPORTED_FACT', 'DESIGN_METADATA', 'RULE_CONDITION', 'DEFERRED_OUTPUT', 'UNRESOLVED'))
        fields[fid] = {'$ref': '#/$defs/' + key}
    authority = [r[4] for r in payload['source_rows'] if r[1] in {'MAIN', 'RULE'}]
    auth = arr({'type': 'integer', 'enum': authority}) if authority else arr({'type': 'integer'})
    if not authority:
        auth['maxItems'] = 0
    metadata = {}
    for u in payload['units']:
        meta_fields = dict(lookup_query={'type': 'string'}, deferred_outputs=arr(obj(
            producer_task=S, output=S, first_dependency=S, source_indices=auth)))
        if payload.get('extra_item_ids'):
            notes = [r[4] for r in payload['source_rows'] if r[1] == 'SOURCE_NOTE'
                     and r[2] in scopes[u['scope_id']]['item_ids'] + payload['extra_item_ids']]
            meta_fields['source_links'] = arr(obj(item_id=enum(*payload['extra_item_ids']),
                relation=enum('CONTEXT_DEPENDENCY', 'EXPLICIT_RECORD_LINK'), scope_basis=S, reason=S,
                evidence_indices=arr({'type': 'integer', 'enum': notes}, 2)))
        fixed = payload.get('counterevidence_targets', {}).get(u['unit_id'], {})
        if fixed:
            selectors = [r[4] for r in payload['source_rows'] if r[2] in payload['extra_item_ids']]
            meta_fields['new_counterevidence'] = arr(obj(criterion_id=enum(*fixed),
                source_indices=arr({'type': 'integer', 'enum': selectors}, 1), reason=S, needed_material=S))
        metadata[u['unit_id']] = obj(**meta_fields)
    result = obj(request_sha256=S, facts=obj(**fields), unit_metadata=obj(**metadata))
    result['$defs'] = definitions
    return result


def _partition(units, base, needs, rules, max_checks):
    result, group = [], []
    def fits(p):
        return (len(p['facts']) <= max_checks and len(p['facts']) * 600 <= MAX_OUTPUT_ESTIMATE_CHARS
                and _chars(transport_payload(p)) + _chars(response_schema(p)) <= MAX_INPUT_CHARS)
    scoped = {}
    for unit in units:
        scoped.setdefault(unit['scope_id'], []).append(unit)
    groups = []
    for local in scoped.values():
        # Keep consumers of the one shared factual field together; other complete
        # requirements can fill a packet without repeating that field in another call.
        shared = [u for u in local if any(s['id'].startswith('FIELD_') and
                  s['description'] == 'Study and regimen membership' and
                  s['id'] not in u.get('fixed_criteria', {}) for s in u['criteria'])]
        if shared:
            groups.append(shared)
        groups.extend([u] for u in local if u not in shared)
    for scoped_units in groups:
        trial = _make_payload(group + scoped_units, base, needs, rules, len(result) + 1)
        if group and not fits(trial):
            result.append(_make_payload(group, base, needs, rules, len(result) + 1))
            group = []
            trial = _make_payload(scoped_units, base, needs, rules, len(result) + 1)
        if not fits(trial):
            fail('One complete shared-fact group exceeds fact/input/output budget; explicit smaller criterion partition required; no truncation')
        group.extend(scoped_units)
    if group:
        result.append(_make_payload(group, base, needs, rules, len(result) + 1))
    return result


def build(plan, source_run, *, max_checks=MAX_CHECKS, accepted_matches=(), semantic_rechecks=()):
    if not isinstance(max_checks, int) or not 1 <= max_checks <= MAX_CHECKS:
        fail('max_checks must be between 1 and 100')
    base = legacy.build(plan, source_run)
    catalog, rules, pp = _context(plan, base)
    units = [copy.deepcopy(u) for p in base['payloads'] for u in p['units']]
    needs = {n['id']: n for n in plan['requirements']}
    accepted = {m['unit_id']: copy.deepcopy(m) for m in accepted_matches}
    if len(accepted) != len(accepted_matches):
        fail('Duplicate accepted unit')
    rechecks = _recheck_set(semantic_rechecks)
    universe = {(u['unit_id'], s['id']) for u in units for s in u['criteria']}
    if not rechecks <= universe or not accepted.keys() <= {u['unit_id'] for u in units}:
        fail('Unknown semantic recheck or accepted unit')
    base.update(version=VERSION, catalog=catalog, units=units, requirements=needs,
                rule_context=rules, accepted_matches=list(accepted.values()), semantic_rechecks=sorted(rechecks),
                lookup_catalog=copy.deepcopy(pp['data_overviews']), scoped_exclusions=[])
    base['incomplete_item_ids'] = sorted({i for p in base['payloads'] for i in p['incomplete_item_ids']})
    active = []
    scopes = {s['id']: s for s in base['scopes']}
    for unit in units:
        old = accepted.get(unit['unit_id'])
        if old:
            if old['scope_id'] != unit['scope_id'] or old['requirement_id'] != unit['requirement']['id']:
                fail('Accepted fact identity changed')
            specs = {s['id']: s for s in unit['criteria']}
            if set(specs) != _uniq([c['id'] for c in old['criteria']], 'accepted criteria'):
                fail('Accepted unit is incomplete')
            unit['fixed_criteria'] = {x['id']: copy.deepcopy(x) for x in old['criteria']
                                      if (unit['unit_id'], x['id']) not in rechecks and x['id'] != 'FULL_REQUIREMENT'}
            unit['original_full_judgment'] = next(x for x in old['criteria'] if x['id'] == 'FULL_REQUIREMENT')
            if not any(uid == unit['unit_id'] for uid, _ in rechecks):
                continue
            if (unit['unit_id'], 'FULL_REQUIREMENT') in rechecks:
                mic = any(_is_mic_field(s['description']) for s in unit['criteria'])
                unit['qualification_spec'] = ('MIC measurement-body qualification, distinct from a reported MIC note and CFU response body.'
                    if mic else 'Original measurement-body qualification for: ' + needs[unit['requirement']['id']]['description'])
        exclusion = _exclusion(unit, needs[unit['requirement']['id']], scopes[unit['scope_id']], catalog, rules)
        if exclusion and not old:
            base['scoped_exclusions'].append(exclusion)
            continue
        active.append(unit)
    base['payloads'] = _partition(active, base, needs, rules, max_checks)
    base['bindings']['facts_code'] = file_ref(__file__)
    base['max_checks'] = max_checks
    base['facts_preflight'] = [{'part_id': p['part_id'], 'decision_checks': len(p['facts']),
                              'canonical_criteria': sum(len(u['criteria']) for u in p['units']),
                              'input_schema_chars': _chars(transport_payload(p)) + _chars(response_schema(p)),
                              'output_estimate_chars': len(p['facts']) * 600} for p in base['payloads']]
    return base


def _is_mic_field(description):
    return bool(re.search(r'(?:MIC value|matched strain MIC|strain.matched MIC|MIC measurement.body)', description, re.I))


def _mic_body_support(support, rows, scope):
    for row in support:
        if row[1] != 'SOURCE_CONTENT' or row[2] not in scope['item_ids']:
            continue
        if re.search(r'\bMIC\b.*\d', row[3], re.I):
            return True
        column = re.search(r':([A-Z]+)\d+$', row[0])
        if not column:
            continue
        for header in rows.values():
            hcol = re.search(r':([A-Z]+)\d+$', header[0])
            if (header[2] == row[2] and header[1] == 'SOURCE_HEADER' and hcol
                    and hcol[1] == column[1] and re.search(r'\bMIC\b', header[3], re.I)
                    and not re.search(r'CFU', header[3], re.I)):
                return True
    return False


def _qualify(fact, check, rows, scope):
    """Deterministic rejection of well-defined false evidence types; not semantic validation."""
    value = copy.deepcopy(check)
    support = [rows[i] for i in check['e']]
    if check['s'] not in {'SUPPORTED', 'PARTIAL'}:
        return value
    reason = None
    if check['k'] == 'BODY_OBSERVATION' and not any(r[1] == 'SOURCE_CONTENT' for r in support):
        reason = 'Body-observation claim lacks original body evidence.'
    if check['k'] == 'NOTE_REPORTED_FACT' and not any(r[1] == 'SOURCE_NOTE' for r in support):
        reason = 'Note-reported claim lacks an original source note.'
    if _is_mic_field(fact['description']):
        explicit = any(re.search(r'\bMIC\b', r[3], re.I) and r[1] in {'SOURCE_NOTE', 'SOURCE_CONTENT'} for r in support)
        mic_body = _mic_body_support(support, rows, scope)
        if not explicit and not mic_body:
            reason = 'MIC field evidence is not an explicit original MIC statement or a MIC-labelled measurement body; CFU values do not establish MIC.'
        if (check['k'] == 'BODY_OBSERVATION' or 'measurement-body' in fact['description']) and not mic_body:
            reason = 'Original MIC measurement-body qualification is unresolved; CFU body and a separate MIC note do not establish MIC body support.'
    if re.search(r'concentration.time|drug concentration', fact['description'], re.I):
        headers = '\n'.join(r[3] for r in rows.values() if r[2] in scope['item_ids'] and r[1] == 'SOURCE_HEADER')
        if re.search(r'CFU', headers, re.I) and not re.search(r'concentration|(?:mg|ng|ug|μg)/[mMlL]', headers, re.I):
            reason = 'CFU response body does not establish a drug concentration-time observation.'
    if reason:
        value.update(s='UNRESOLVED', r=check['r'] + ' Host qualification: ' + reason,
                     n='Qualify the original evidence type and field relevance; preserve reported facts, do not infer absent MIC or new experiments.')
        value['host_qualification'] = {'version': 'EVIDENCE_TYPE_1.0', 'reason': reason,
                                     'original_model_check': copy.deepcopy(check)}
    return value


def materialize(raw, payload, catalog=None):
    d.validate_schema(raw, response_schema(payload))
    rows = {r[4]: r for r in payload['source_rows']}
    if len(rows) != len(payload['source_rows']) or any(len(r) != 5 or not isinstance(r[4], int) for r in payload['source_rows']):
        fail('Invalid or duplicate explicit source selector')
    scopes = {s['id']: s for s in payload['scopes']}
    units = {u['unit_id']: u for u in payload['units']}
    results = {uid: {'unit_id': uid, 'scope_id': u['scope_id'], 'requirement_id': u['requirement']['id'],
                     'method_uses': u['method_uses'], 'criteria': [], 'deferred_outputs': [],
                     'search_scope': {'round': payload['round'],
                         'visible_item_ids': sorted(set(scopes[u['scope_id']]['item_ids']) | set(payload.get('extra_item_ids', [])) |
                             set(payload.get('authorized_extra_items', {}).get(u['scope_id'], []))),
                         'requested_item_ids': list(payload.get('extra_item_ids', []))},
                     'lookup_query': raw['unit_metadata'][uid]['lookup_query']} for uid, u in units.items()}
    def spans(indices):
        _uniq(indices, 'evidence selectors')
        if any(i not in rows or not rows[i][3].strip() for i in indices):
            fail('Invalid source selector')
        return [{'source': rows[i][0], 'quote': rows[i][3]} for i in indices]
    links = {}
    for uid, unit in units.items():
        links[uid] = {}
        for link in payload.get('retained_source_links', {}).get(uid, []):
            owners = set()
            for proof in link['evidence']:
                row = next((r for r in rows.values() if r[0] == proof['source']), None)
                if not row or row[1] != 'SOURCE_NOTE' or not proof['quote'].strip() or proof['quote'] not in row[3]:
                    fail('Retained source linkage no longer matches its original note proof')
                owners.add(row[2])
            if (link['item_id'] not in owners or not owners.intersection(scopes[unit['scope_id']]['item_ids'])
                    or link['relation'] not in {'CONTEXT_DEPENDENCY', 'EXPLICIT_RECORD_LINK'}
                    or link['item_id'] in links[uid]):
                fail('Invalid retained original source linkage')
            links[uid][link['item_id']] = copy.deepcopy(link)
        for link in raw['unit_metadata'][uid].get('source_links', []):
            item = link['item_id']; proof = spans(link['evidence_indices'])
            owners = {rows[i][2] for i in link['evidence_indices']}
            if item in links[uid] or item not in owners or not owners.intersection(scopes[unit['scope_id']]['item_ids']):
                fail('Source linkage requires distinct original local and target notes')
            if not link['scope_basis'].strip() or not link['reason'].strip():
                fail('Source linkage needs its exact scientific scope basis')
            if link['relation'] == 'EXPLICIT_RECORD_LINK' and not any(re.search(
                    r'same (?:animals|records|subjects|samples)|explicitly (?:paired|linked)|corresponding (?:animal|record|sample)', p['quote'], re.I) for p in proof):
                fail('A study reference alone does not establish explicit record linkage')
            links[uid][item] = {k: v for k, v in link.items() if k != 'evidence_indices'} | {'evidence': proof,
                'authority': 'MODEL_ASSERTED_RELATION_WITH_ORIGINAL_NOTE_AND_SCOPE_CHECKS; NOT_SCIENTIFIC_RELEASE'}
    for fid, fact in payload['facts'].items():
        original = raw['facts'][fid]
        for target in fact['targets']:
            for index in original['e'] + original['x']:
                row = rows[index]
                if row[2] is not None and row[2] not in scopes[fact['scope_id']]['item_ids']:
                    link = links[target['unit_id']].get(row[2])
                    if not link or (link['relation'] == 'CONTEXT_DEPENDENCY' and row[1] not in {'SOURCE_NOTE', 'SOURCE_HEADER', 'DESCRIPTOR'}):
                        fail('Targeted source evidence requires a scope-supported source link; context does not transfer observations')
        qualification_scope = copy.deepcopy(scopes[fact['scope_id']])
        linked = [{item for item, link in links[t['unit_id']].items() if link['relation'] == 'EXPLICIT_RECORD_LINK'}
                  for t in fact['targets']]
        if linked:
            qualification_scope['item_ids'] += sorted(set.intersection(*linked))
        check = _qualify(fact, original, rows, qualification_scope)
        support, counter = spans(check['e']), spans(check['x'])
        for retained in fact.get('retained_counterevidence', []):
            for span in retained['evidence']:
                if not any(e['source'] == span['source'] and span['quote'] in e['quote'] for e in counter):
                    fail('Targeted review cannot discard original counterevidence')
                if span not in counter:
                    counter.append(copy.deepcopy(span))
        if check['s'] in {'SUPPORTED', 'PARTIAL', 'CONFLICT'} and not support + counter:
            fail('Positive fact lacks evidence')
        if counter and check['s'] == 'SUPPORTED':
            fail('Counterevidence cannot be hidden behind SUPPORTED')
        if not check['r'].strip() or (check['s'] != 'SUPPORTED' and check['n'].strip().upper() in {'', 'NONE', 'N/A', 'NOT_FOUND'}):
            fail('Every gap needs relevance and a concrete action')
        for target in fact['targets']:
            criterion = {'id': target['criterion_id'], 'description': fact['description'],
                         'status': check['s'], 'reason': check['r'], 'needed_material': check['n'],
                         'evidence': support + [s for s in counter if s not in support], 'counterevidence': counter,
                         'evidence_role': check['k'], 'search_state': 'ASSIGNED_SCOPE_REVIEWED',
                         'searched_item_ids': sorted(set(scopes[fact['scope_id']]['item_ids']) | set(payload.get('extra_item_ids', [])) |
                             set(payload.get('authorized_extra_items', {}).get(fact['scope_id'], []))),
                         'unread_item_ids': sorted(set(payload.get('incomplete_item_ids', [])) &
                                                   (set(scopes[fact['scope_id']]['item_ids']) | set(payload.get('extra_item_ids', [])))),
                         'incomplete_item_ids': sorted(set(payload.get('incomplete_item_ids', [])) & set(scopes[fact['scope_id']]['item_ids'])),
                         'fact_provenance': {'version': TRANSPORT_VERSION, 'part_id': payload['part_id'], 'fact_id': fid}}
            if 'host_qualification' in check:
                criterion['host_qualification'] = check['host_qualification']
            if target['criterion_id'] == 'HOST_MEASUREMENT_QUALIFICATION':
                results[target['unit_id']]['measurement_qualification'] = criterion
            else:
                results[target['unit_id']]['criteria'].append(criterion)
    for uid, result in results.items():
        result['source_links'] = list(links[uid].values())
        result['new_counterevidence'] = []
        changes = raw['unit_metadata'][uid].get('new_counterevidence', [])
        _uniq([x['criterion_id'] for x in changes], 'new counterevidence targets')
        for change in changes:
            cid = change['criterion_id']
            previous = payload.get('counterevidence_targets', {}).get(uid, {}).get(cid)
            if not previous or previous['status'] != 'SUPPORTED':
                fail('New counterevidence may only challenge an earlier supported fact')
            for index in change['source_indices']:
                row = rows[index]
                if row[2] not in payload['extra_item_ids']:
                    fail('New counterevidence must come from this targeted reading')
                if row[2] not in scopes[units[uid]['scope_id']]['item_ids']:
                    link = links[uid].get(row[2])
                    if not link or (link['relation'] == 'CONTEXT_DEPENDENCY' and row[1] not in {'SOURCE_NOTE', 'SOURCE_HEADER', 'DESCRIPTOR'}):
                        fail('New counterevidence requires a scope-supported source link')
            if not change['reason'].strip() or change['needed_material'].strip().upper() in {'', 'NONE', 'N/A', 'NOT_FOUND'}:
                fail('New counterevidence needs a reason and an explicit review action')
            result['new_counterevidence'].append({'criterion_id': cid, 'previous_status': 'SUPPORTED',
                'counterevidence': spans(change['source_indices']), 'reason': change['reason'],
                'needed_material': change['needed_material'],
                'derivation': 'PRESERVED_POSITIVE_EVIDENCE_PLUS_EXPLICIT_NEW_COUNTEREVIDENCE'})
        for output in raw['unit_metadata'][uid]['deferred_outputs']:
            if not output['source_indices'] or any(not output[k].strip() or output[k].upper() in {'NONE', 'N/A', 'NOT_FOUND'} for k in ('producer_task', 'output', 'first_dependency')):
                fail('Deferred producer/output/dependency needs exact authority')
            result['deferred_outputs'].append({k: v for k, v in output.items() if k != 'source_indices'} | {'evidence': spans(output['source_indices'])})
    return list(results.values())


def _derive_full(unit, criteria, catalog, qualification=None):
    statuses = {x['status'] for x in criteria}
    if qualification is not None:
        statuses.add(qualification['status'])
    evidence = []
    for item in criteria:
        for span in item['evidence']:
            if span not in evidence:
                evidence.append(span)
    # A relevant field body is required; arbitrary CFU body cannot qualify a MIC need.
    field_body = any(x['id'].startswith('FIELD_') and x['status'] in {'SUPPORTED', 'PARTIAL'}
                     and x.get('evidence_role') == 'BODY_OBSERVATION'
                     and any(catalog.get(e['source'], {}).get('kind') == 'SOURCE_CONTENT' for e in x['evidence'])
                     for x in criteria)
    mic_fields = [x for x in criteria if _is_mic_field(x['description'])]
    if mic_fields:
        field_body = field_body and any(x.get('evidence_role') == 'BODY_OBSERVATION' and x['status'] == 'SUPPORTED' for x in mic_fields)
    if qualification is not None:
        field_body = qualification['status'] == 'SUPPORTED' and qualification.get('evidence_role') == 'BODY_OBSERVATION'
        for span in qualification['evidence']:
            if span not in evidence:
                evidence.append(span)
    if criteria and field_body:
        aggregate = c.aggregate(criteria)
        status = 'SUPPORTED' if aggregate == 'AVAILABLE_CANDIDATE' else aggregate
    elif 'CONFLICT' in statuses:
        status = 'CONFLICT'
    elif criteria and statuses == {'SUPPORTED'} and field_body:
        status = 'SUPPORTED'
    elif 'DEFERRED' in statuses and statuses <= {'SUPPORTED', 'DEFERRED'}:
        status = 'DEFERRED'
    else:
        status = 'UNRESOLVED'
    derivation = {'version': FULL_DERIVATION, 'constituent_ids': [x['id'] for x in criteria],
                  'measurement_body_qualified': field_body,
                  'pure_aggregate': bool(criteria) and (field_body or status in {'CONFLICT', 'DEFERRED'}),
                  'scientific_approval': False}
    if 'original_full_judgment' in unit:
        derivation['original_judgment'] = copy.deepcopy(unit['original_full_judgment'])
    if qualification is not None:
        derivation['measurement_qualification'] = copy.deepcopy(qualification)
        derivation['pure_aggregate'] = False
        derivation['semantic_recheck_status'] = 'OPEN' if qualification['status'] != 'SUPPORTED' else 'QUALIFICATION_REVIEWED_NOT_SCIENTIFIC_RELEASE'
    return {'id': 'FULL_REQUIREMENT', 'description': next(s['description'] for s in unit['criteria'] if s['id'] == 'FULL_REQUIREMENT'),
            'status': status, 'evidence': evidence, 'counterevidence': [e for x in criteria + ([qualification] if qualification else []) for e in x.get('counterevidence', [])],
            'reason': 'Host conservative conjunction of distinct field, condition and scope facts; no independent model summary or scientific approval.',
            'needed_material': 'NONE' if status == 'SUPPORTED' else 'Resolve constituent gaps or qualify the relevant original measurement body; retained reported facts are not absent observations.',
            'host_derivation': derivation, 'search_state': 'ASSIGNED_SCOPE_REVIEWED',
            'searched_item_ids': sorted({i for x in criteria for i in x.get('searched_item_ids', [])}),
            'unread_item_ids': sorted({i for x in criteria for i in x.get('unread_item_ids', [])})}


def assemble_matches(build, part_matches):
    incoming = {}
    for entry in (part_matches.values() if isinstance(part_matches, dict) else part_matches):
        for match in (entry if isinstance(entry, list) else [entry]):
            uid = match['unit_id']
            if uid in incoming:
                fail('Duplicate materialized unit; complete units are partitioned once')
            incoming[uid] = match
    if not incoming.keys() <= {u['unit_id'] for u in build['units']}:
        fail('Unknown materialized unit')
    accepted = {m['unit_id']: m for m in build.get('accepted_matches', [])}
    rechecks = {uid for uid, _ in build.get('semantic_rechecks', [])}
    excluded = {x['unit_id'] for x in build.get('scoped_exclusions', [])}
    matches, pending = [], []
    scopes = {s['id']: s for s in build['scopes']}
    for unit in build['units']:
        uid = unit['unit_id']
        if uid in accepted and uid not in rechecks:
            matches.append(copy.deepcopy(accepted[uid]))
            continue
        if uid in excluded:
            continue
        entry = incoming.get(uid)
        fixed = copy.deepcopy(unit.get('fixed_criteria', {}))
        if entry:
            if entry['scope_id'] != unit['scope_id'] or entry['requirement_id'] != unit['requirement']['id']:
                fail('Materialized unit identity changed')
            for criterion in entry['criteria']:
                if criterion['id'] in fixed:
                    fail('A new decision overwrote a retained fact')
                fixed[criterion['id']] = copy.deepcopy(criterion)
            for change in entry.get('new_counterevidence', []):
                cid = change['criterion_id']
                if cid not in unit.get('fixed_criteria', {}) or fixed[cid]['status'] != 'SUPPORTED':
                    fail('New counterevidence cannot overwrite a new or unsupported fact')
                previous = copy.deepcopy(fixed[cid])
                fixed[cid].update(status='CONFLICT', prior_judgment=previous,
                    reason=previous['reason'] + ' New source counterevidence: ' + change['reason'],
                    needed_material=change['needed_material'])
                for key in ('evidence', 'counterevidence'):
                    for span in change['counterevidence']:
                        if span not in fixed[cid].setdefault(key, []):
                            fixed[cid][key].append(copy.deepcopy(span))
                fixed[cid]['searched_item_ids'] = sorted(set(previous.get('searched_item_ids', [])) |
                    set(entry.get('search_scope', {}).get('visible_item_ids', [])))
        ids = [s['id'] for s in unit['criteria'] if s['id'] != 'FULL_REQUIREMENT']
        if not set(fixed) <= set(ids):
            fail('Unrelated materialized criterion')
        missing_qualification = unit.get('qualification_spec') and not (entry or {}).get('measurement_qualification')
        if set(fixed) != set(ids) or missing_qualification:
            pending.extend({'unit_id': uid, 'scope_id': unit['scope_id'], 'requirement_id': unit['requirement']['id'], 'criterion_id': cid}
                           for cid in ids if cid not in fixed)
            if missing_qualification:
                pending.append({'unit_id': uid, 'scope_id': unit['scope_id'], 'requirement_id': unit['requirement']['id'], 'criterion_id': 'FULL_REQUIREMENT', 'reason': 'Open original measurement qualification requires its targeted fact review.'})
            continue
        constituents = [fixed[cid] for cid in ids]
        criteria = [_derive_full(unit, constituents, build['catalog'], (entry or {}).get('measurement_qualification'))] + constituents
        agg = c.aggregate(criteria)
        status = 'UNRESOLVED' if agg in {'PARTIAL', 'CONFLICT'} else agg
        deferred = copy.deepcopy((entry or {}).get('deferred_outputs', []))
        dependencies = [o['first_dependency'] for o in deferred if o.get('first_dependency')]
        if any(x['status'] == 'DEFERRED' for x in unit.get('fixed_criteria', {}).values()):
            # A qualification-only reply cannot erase the producer of an unchanged fact.
            for output in accepted.get(uid, {}).get('deferred_outputs', []):
                if output not in deferred:
                    deferred.append(copy.deepcopy(output))
            for dependency in accepted.get(uid, {}).get('deferred_dependencies', []):
                if dependency not in dependencies:
                    dependencies.append(copy.deepcopy(dependency))
        allowed = sorted({e['source'] for x in criteria for e in x['evidence']} | {e['source'] for out in deferred for e in out['evidence']})
        reason = 'Host aggregate of scoped constituent facts; not method eligibility or scientific release.'
        needed = '; '.join(dict.fromkeys(x['needed_material'] for x in criteria if x['status'] != 'SUPPORTED')) or 'NONE'
        match = {'requirement_id': unit['requirement']['id'], 'status': status, 'criteria': criteria,
                 'source_ids': sorted({e['source'] for x in criteria for e in x['evidence']}),
                 'reason': reason, 'needed_material': needed, 'deferred_outputs': deferred}
        validation = {'criteria': unit['criteria'], 'allowed_source_ids': allowed,
                      'assigned_item_ids': scopes[unit['scope_id']]['item_ids'], 'unresolved_review_items': [],
                      'search_scope': copy.deepcopy((entry or {}).get('search_scope', {
                          'round': 'ASSIGNED_ONLY', 'visible_item_ids': scopes[unit['scope_id']]['item_ids'], 'requested_item_ids': []}))}
        checked = c.validate_match(unit['requirement'], match, validation, build['catalog'])
        checked.update(unit_id=uid, scope_id=unit['scope_id'], scope=scopes[unit['scope_id']]['scientific_scope'],
                       method_uses=unit['method_uses'], search_item_ids=[], search_reason=(entry or {}).get('lookup_query', ''),
                       lookup_query=(entry or {}).get('lookup_query', ''), allowed_source_ids=allowed,
                       deferred_dependencies=dependencies,
                       source_links=(entry or {}).get('source_links', []),
                       new_counterevidence=copy.deepcopy(accepted.get(uid, {}).get('new_counterevidence', [])) +
                           copy.deepcopy((entry or {}).get('new_counterevidence', [])))
        matches.append(checked)
    return {'matches': matches, 'complete': not pending, 'pending': pending,
            'scoped_exclusions': copy.deepcopy(build.get('scoped_exclusions', []))}


def lookup_targets(build, matches, *, max_per_unit=2, max_total=8):
    """Bounded lexical routing over permitted overviews, never evidence or a source link.

    A no-hit result leaves the query open. Scores select reading candidates only. Exact
    original rows still must establish relevance after reading; no inference of absence.
    """
    if not 1 <= max_per_unit <= 3 or not 1 <= max_total <= 16:
        fail('Lookup routing bounds exceeded')
    permitted = {v['item_id'] for v in build['catalog'].values() if v['item_id'] is not None}
    ignored = {'the', 'and', 'for', 'source', 'sources', 'data', 'original', 'with', 'this', 'that',
               'scope', 'inspect', 'find', 'needed', 'reported', 'not', 'from', 'units', 'records'}
    result, count = {}, 0
    scopes = {s['id']: s for s in build['scopes']}
    for match in matches:
        query = match.get('lookup_query', match.get('search_reason', '')).strip()
        if not query or query.upper() in {'NONE', 'N/A', 'NOT_FOUND'}:
            continue
        terms = {t.lower() for t in re.findall(r'[A-Za-z][A-Za-z0-9_-]{2,}', query)} - ignored
        seen = set(scopes[match['scope_id']]['item_ids'])
        seen.update(i for c in match['criteria'] for i in c.get('searched_item_ids', []))
        ranked = []
        for overview in build.get('lookup_catalog', []):
            item = overview['item_id']
            if item not in permitted or item in seen:
                continue
            # Notes are original note references already in the permitted catalog, not new bodies.
            text = json.dumps(overview, ensure_ascii=False).lower()
            text += '\n' + '\n'.join(build['catalog'][key]['content'].lower() for key in overview.get('notes', [])
                                      if key in build['catalog'] and build['catalog'][key]['kind'] == 'SOURCE_NOTE')
            score = sum(bool(re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', text)) for term in terms)
            if score:
                ranked.append((-score, item))
        chosen = [item for _, item in sorted(ranked)[:min(max_per_unit, max_total - count)]]
        if chosen:
            result[match['unit_id']] = chosen
            count += len(chosen)
        if count >= max_total:
            break
    return result


def build_search(build, parent_matches, unit_ids):
    """Explicit permitted lookup only. Does not equate one lookup with global absence.

    unit_ids is {unit_id: [item_id,...]}; caller must separately establish scope linkage
    before extra observations become ordinary supporting evidence.
    """
    if not isinstance(unit_ids, dict) or not unit_ids:
        fail('Targeted lookup needs explicit unit -> permitted item IDs; no automatic search')
    parents = {m['unit_id']: m for m in parent_matches}
    permitted = {v['item_id'] for v in build['catalog'].values() if v['item_id'] is not None}
    result = copy.deepcopy(build)
    result['payloads'] = []
    result['accepted_matches'] = copy.deepcopy(parent_matches)
    result['semantic_rechecks'] = []
    for uid, items in unit_ids.items():
        if uid not in parents or not items or not _uniq(items, 'lookup items') <= permitted:
            fail('Lookup is not an explicit permitted unresolved unit/source request')
        unit = copy.deepcopy(next(u for u in build['units'] if u['unit_id'] == uid))
        unit['fixed_criteria'] = {c['id']: copy.deepcopy(c) for c in parents[uid]['criteria'] if c['id'] != 'FULL_REQUIREMENT' and c['status'] == 'SUPPORTED'}
        unit['prior_criteria'] = {c['id']: copy.deepcopy(c) for c in parents[uid]['criteria']}
        unit['retained_source_links'] = copy.deepcopy(parents[uid].get('source_links', []))
        unit['retained_source_ids'] = sorted({e['source'] for c in parents[uid]['criteria']
            for key in ('evidence', 'counterevidence') for e in c.get(key, [])} |
            {e['source'] for link in unit['retained_source_links'] for e in link['evidence']})
        unit['original_full_judgment'] = copy.deepcopy(unit['prior_criteria']['FULL_REQUIREMENT'])
        full = unit['original_full_judgment']
        if full['status'] != 'SUPPORTED' and not full.get('host_derivation', {}).get('pure_aggregate', False):
            mic = any(_is_mic_field(c['description']) for c in unit['criteria'])
            unit['qualification_spec'] = ('MIC measurement-body qualification, distinct from a reported MIC note and CFU response body.'
                if mic else 'Original measurement-body qualification for: ' + unit['requirement']['description'])
        for index, stored in enumerate(result['units']):
            if stored['unit_id'] == uid:
                result['units'][index] = unit
        result['semantic_rechecks'].extend((uid, s['id']) for s in unit['criteria'] if s['id'] not in unit['fixed_criteria'])
        p = _make_payload([unit], result, result['requirements'], result['rule_context'], len(result['payloads']) + 1, extras=items)
        p['round'] = 'TARGETED_REVIEW'
        p['instructions'] += '\nNew source bodies are visible but not automatically evidence for a different scope; retain UNRESOLVED until original linkage is established. No global MISSING. Retained counterevidence is immutable: include its original source selectors in x; this review cannot silently dismiss it.'
        p['instructions'] += '\nDo not rejudge counterevidence_targets. If this reading explicitly contradicts an earlier supported fact, report only that criterion in new_counterevidence with newly read, scope-linked evidence; the host retains its prior judgment and marks the conflict for review.'
        checks = len(p['facts']) + sum(len(x) for x in p['counterevidence_targets'].values())
        if (checks > MAX_CHECKS or _chars(transport_payload(p)) + _chars(response_schema(p)) > MAX_INPUT_CHARS
                or checks * 600 > MAX_OUTPUT_ESTIMATE_CHARS):
            fail('Targeted unit exceeds its fact and potential counterevidence review budget; explicit smaller criterion partition required')
        result['payloads'].append(p)
    return result
