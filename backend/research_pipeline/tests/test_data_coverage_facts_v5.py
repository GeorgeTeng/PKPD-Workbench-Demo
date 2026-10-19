"""Offline contract/negative tests. No real evidence or scientific approval is inferred."""
import copy
import pytest
from research_pipeline import data_coverage_facts_v5 as f


@pytest.fixture
def case():
    need = {'id': 'RQ001', 'task_id': 'SOURCE_SCOPE', 'kind': 'DATA', 'origin': 'METHOD_CANDIDATE',
            'required_by': 'BEFORE_INDEX_ANALYSIS', 'method_profile_ids': [], 'project_source_ids': [],
            'description': 'Provide MIC observations'}
    unit = {'unit_id': 'U0001', 'scope_id': 'A', 'method_uses': ['PD_INDEX'], 'requirement': need,
            'criteria': [{'id': 'FULL_REQUIREMENT', 'description': 'Provide MIC observations'},
                         {'id': 'FIELD_001', 'description': 'MIC value or bins and units'},
                         {'id': 'SCOPE_ALIGNMENT', 'description': 'Evidence belongs to requested context.'},
                         {'id': 'CONDITION_001', 'description': 'Use the original experimental unit.'}]}
    catalog = {'main:/objective': {'kind': 'MAIN', 'item_id': None, 'content': 'Compare indices.'},
               'A:h': {'kind': 'SOURCE_HEADER', 'item_id': 'A', 'content': 'log10 CFU/lung'},
               'A:v': {'kind': 'SOURCE_CONTENT', 'item_id': 'A', 'content': '4.2'},
               'A:n': {'kind': 'SOURCE_NOTE', 'item_id': 'A', 'content': 'PMB MIC 0.5 mg/L for strain K1.'},
               'B:n': {'kind': 'SOURCE_NOTE', 'item_id': 'B', 'content': 'PMB MIC 8 mg/L for strain B2.'}}
    scope = {'id': 'A', 'item_ids': ['A'], 'scientific_scope': {'species': 'Mouse'}, 'method_uses': ['PD_INDEX']}
    built = {'catalog': catalog, 'scopes': [scope], 'units': [unit], 'requirements': {'RQ001': need},
             'rule_context': {}, 'accepted_matches': [], 'semantic_rechecks': [], 'scoped_exclusions': []}
    payload = f._make_payload([unit], built, built['requirements'], {}, 1)
    return built, payload


def answer(payload):
    note = next(r[4] for r in payload['source_rows'] if r[0] == 'A:n')
    return {'request_sha256': 'fixture', 'facts': {fid: {'s': 'SUPPORTED', 'e': [note], 'x': [],
             'r': 'Original source statement addresses this field.', 'n': 'NONE', 'k': 'NOTE_REPORTED_FACT'}
             for fid in payload['facts']},
            'unit_metadata': {u['unit_id']: {'lookup_query': '', 'deferred_outputs': [],
                **({'new_counterevidence': []} if payload.get('counterevidence_targets', {}).get(u['unit_id']) else {})}
                for u in payload['units']}}


def assemble(case, raw):
    built, payload = case
    return f.assemble_matches(built, {payload['part_id']: f.materialize(raw, payload, built['catalog'])})


def test_note_mic_stays_supported_full_body_remains_unresolved(case):
    result = assemble(case, answer(case[1]))
    assert result['complete']
    criteria = result['matches'][0]['criteria']
    assert criteria[1]['status'] == 'SUPPORTED'
    assert criteria[0]['status'] == 'UNRESOLVED'
    assert criteria[0]['host_derivation']['pure_aggregate'] is False
    assert 'absent' in criteria[0]['needed_material']


def test_cfu_body_cannot_support_mic(case):
    raw = answer(case[1]); body = next(r[4] for r in case[1]['source_rows'] if r[0] == 'A:v')
    raw['facts']['F0001'].update(e=[body], k='BODY_OBSERVATION')
    item = assemble(case, raw)['matches'][0]['criteria'][1]
    assert item['status'] == 'UNRESOLVED'
    assert item['host_qualification']['original_model_check']['s'] == 'SUPPORTED'
    assert item['evidence'][0]['quote'] == '4.2'


def test_cfu_body_plus_mic_note_does_not_qualify_mic_body(case):
    raw = answer(case[1]); body = next(r[4] for r in case[1]['source_rows'] if r[0] == 'A:v')
    raw['facts']['F0001']['e'].append(body); raw['facts']['F0001']['k'] = 'BODY_OBSERVATION'
    assert assemble(case, raw)['matches'][0]['criteria'][1]['status'] == 'UNRESOLVED'


def test_original_mic_body_can_qualify_when_children_supported(case):
    built, payload = case
    payload['source_rows'][2][3] = 'MIC 4.2 mg/L'
    built['catalog']['A:v']['content'] = 'MIC 4.2 mg/L'
    raw = answer(payload); raw['facts']['F0001'].update(e=[2], k='BODY_OBSERVATION')
    full = assemble(case, raw)['matches'][0]['criteria'][0]
    assert full['status'] == 'SUPPORTED' and full['host_derivation']['pure_aggregate']


@pytest.mark.parametrize('mutation', ['cross_scope', 'unknown_selector', 'missing_fact', 'extra_fact', 'missing_initial', 'counter_hidden', 'empty_reason'])
def test_strict_rejections(case, mutation):
    payload = case[1]; raw = answer(payload)
    if mutation == 'cross_scope':
        payload['source_rows'].append(['B:n', 'SOURCE_NOTE', 'B', 'MIC 8 mg/L', 99]); raw['facts']['F0001']['e'] = [99]
    elif mutation == 'unknown_selector': raw['facts']['F0001']['e'] = [998]
    elif mutation == 'missing_fact': raw['facts'].pop('F0001')
    elif mutation == 'extra_fact': raw['facts']['F9999'] = copy.deepcopy(raw['facts']['F0001'])
    elif mutation == 'missing_initial': raw['facts']['F0001']['s'] = 'MISSING'
    elif mutation == 'counter_hidden': raw['facts']['F0001']['x'] = raw['facts']['F0001']['e']
    else: raw['facts']['F0001']['r'] = ''
    with pytest.raises(Exception): f.materialize(raw, payload)


def test_same_scope_field_shared_but_scope_and_conditions_distinct(case):
    built, _ = case
    a = built['units'][0]; a['criteria'][1]['description'] = 'Study and regimen membership'
    b = copy.deepcopy(a); b['unit_id'] = 'U0002'; b['requirement']['id'] = 'RQ002'
    built['requirements']['RQ002'] = b['requirement']
    payload = f._make_payload([a, b], built, built['requirements'], {}, 1)
    assert len(payload['facts']) == 5
    assert len(payload['facts']['F0001']['targets']) == 2
    assert sum('context' in x['description'] for x in payload['facts'].values()) == 2
    assert all(x['criterion_id'] != 'FULL_REQUIREMENT' for fact in payload['facts'].values() for x in fact['targets'])


def test_identical_words_other_scopes_not_shared(case):
    built, _ = case; a = built['units'][0]; a['criteria'][1]['description'] = 'Study and regimen membership'
    b = copy.deepcopy(a); b.update(unit_id='U0002', scope_id='B')
    built['scopes'].append({'id': 'B', 'item_ids': ['B'], 'scientific_scope': {}, 'method_uses': ['PD_INDEX']})
    payload = f._make_payload([a, b], built, built['requirements'], {}, 1)
    assert len(payload['facts']) == 6


def test_missing_part_is_pending_not_fake_missing(case):
    result = f.assemble_matches(case[0], {})
    assert not result['complete'] and len(result['pending']) == 3 and not result['matches']


def test_duplicate_part_or_unknown_unit_rejected(case):
    facts = f.materialize(answer(case[1]), case[1])
    with pytest.raises(Exception, match='Duplicate'): f.assemble_matches(case[0], {'A': facts, 'B': facts})
    facts[0]['unit_id'] = 'NOPE'
    with pytest.raises(Exception, match='Unknown'): f.assemble_matches(case[0], {'A': facts})


def test_empty_constituents_cannot_autopass(case):
    full = f._derive_full(case[0]['units'][0], [], case[0]['catalog'])
    assert full['status'] == 'UNRESOLVED' and not full['host_derivation']['pure_aggregate']


def test_imported_full_unchanged_until_explicit_recheck(case):
    built, payload = case
    match = assemble(case, answer(payload))['matches'][0]
    match['criteria'][0]['reason'] = 'Exact historical judgment.'
    built['accepted_matches'] = [copy.deepcopy(match)]
    assert f.assemble_matches(built, {})['matches'] == [match]
    unit = built['units'][0]; unit['original_full_judgment'] = copy.deepcopy(match['criteria'][0])
    full = f._derive_full(unit, match['criteria'][1:], built['catalog'])
    assert full['host_derivation']['original_judgment'] == match['criteria'][0]


def test_context_keeps_objective_and_complete_exception_clauses(case):
    built, _ = case
    rule = {'text': 'Use data.', 'conditions': ['Original condition'], 'exceptions': ['Original explicit exception'],
            'scope': {'matrix': 'plasma'}, 'requirement': {'action': 'Original action'}, 'usage': {'except_when': ['Exception timing']}}
    built['catalog']['main:/rules/2'] = {'item_id': None, 'kind': 'RULE', 'content': f.json.dumps(rule)}
    built['requirements']['RQ001']['project_source_ids'] = ['main:/rules/2/text']
    payload = f._make_payload(built['units'], built, built['requirements'], {'main:/rules/2': rule}, 1)
    keys = {r[0] for r in payload['source_rows']}
    assert {'main:/objective', 'main:/rules/2'} <= keys
    text = next(r[3] for r in payload['source_rows'] if r[0] == 'main:/rules/2')
    assert f.json.loads(text) == rule
    assert 'lookup_catalog' not in f.transport_payload(payload)
    assert 'fixed_criteria' not in str(f.transport_payload(payload)['units'])


def test_scoped_exclusion_needs_original_label_and_applicable_rule(case):
    built, _ = case; unit = built['units'][0]; need = built['requirements']['RQ001']
    need['description'] = 'For K. pneumoniae index comparison'; need['project_source_ids'] = ['main:/rules/2/text']
    built['catalog']['A:n']['content'] = 'Figure 3a — P. aeruginosa FADDI-PA038'
    rule = {'text': 'For eligible K. pneumoniae data, compare indices.', 'scope': {'population': 'K. pneumoniae', 'matrix': 'NOT_SPECIFIED'}, 'conditions': [], 'exceptions': []}
    built['catalog']['main:/rules/2'] = {'content': f.json.dumps(rule), 'kind': 'RULE', 'item_id': None}
    args = [unit, need, built['scopes'][0], built['catalog'], {'main:/rules/2': rule}]
    assert f._exclusion(*args)['state'] == 'SCOPED_EXCLUSION'
    rule['exceptions'] = ['May be used in a specified exceptional setting']
    assert f._exclusion(*args) is None
    rule['exceptions'] = []; rule['scope']['matrix'] = 'in-vitro time-kill'
    assert f._exclusion(*args) is None
    rule['scope']['matrix'] = 'NOT_SPECIFIED'; unit['method_uses'] = ['MODEL_BASED', 'NCA']
    assert f._exclusion(*args) is None


def test_partition_count_and_output_caps_preserve_every_target(case):
    built, _ = case
    units = []
    for i in range(5):
        unit = copy.deepcopy(built['units'][0]); unit['unit_id'] = str(i); unit['scope_id'] = str(i); units.append(unit)
        built['scopes'].append({'id': str(i), 'item_ids': ['A'], 'scientific_scope': {}, 'method_uses': ['PD_INDEX']})
    parts = f._partition(units, built, built['requirements'], {}, 6)
    assert len(parts) == 3 and all(len(p['facts']) <= 6 for p in parts)
    targets = [(t['unit_id'], t['criterion_id']) for p in parts for fact in p['facts'].values() for t in fact['targets']]
    assert len(targets) == len(set(targets)) == 15


def test_target_lookup_does_not_authorize_cross_scope_or_missing(case):
    built, payload = case; matches = assemble(case, answer(payload))['matches']
    updated = f.build_search(built, matches, {'U0001': ['B']})
    p = updated['payloads'][0]
    assert 'MISSING' not in str(f.response_schema(p))
    assert p['round'] == 'TARGETED_REVIEW' and any(r[2] == 'B' for r in p['source_rows'])
    with pytest.raises(Exception, match='permitted'): f.build_search(built, matches, {'U0001': ['HUMAN_HOLDOUT']})
    with pytest.raises(Exception, match='explicit'): f.build_search(built, matches, ['U0001'])


def test_mixed_cfu_mic_columns_do_not_cross_qualify_body(case):
    payload = case[1]
    payload['source_rows'][1] = ['A:A1', 'SOURCE_HEADER', 'A', 'CFU/lung', 1]
    payload['source_rows'][2] = ['A:A2', 'SOURCE_CONTENT', 'A', '4.2', 2]
    payload['source_rows'].append(['A:B1', 'SOURCE_HEADER', 'A', 'MIC mg/L', 7])
    raw = answer(payload); raw['facts']['F0001'].update(e=[2], k='BODY_OBSERVATION')
    assert f.materialize(raw, payload)[0]['criteria'][0]['status'] == 'UNRESOLVED'


def test_lookup_only_routes_permitted_unread_overviews(case):
    built, payload = case; matches = assemble(case, answer(payload))['matches']
    matches[0]['lookup_query'] = 'MIC measurement method'
    built['lookup_catalog'] = [{'item_id': 'B', 'role': 'MIC', 'notes': ['B:n']},
                              {'item_id': 'HUMAN_HOLDOUT', 'role': 'MIC'}]
    targets = f.lookup_targets(built, matches)
    assert targets == {'U0001': ['B']}
    assert matches[0]['criteria'][1]['status'] == 'SUPPORTED'
    matches[0]['lookup_query'] = 'unfindabletopic'
    assert f.lookup_targets(built, matches) == {}


def test_open_full_recheck_has_its_own_qualification_fact_and_keeps_old_fields(case):
    built, payload = case; old = assemble(case, answer(payload))['matches'][0]
    unit = built['units'][0]
    unit['fixed_criteria'] = {c['id']: copy.deepcopy(c) for c in old['criteria'][1:]}
    unit['original_full_judgment'] = copy.deepcopy(old['criteria'][0])
    unit['qualification_spec'] = 'MIC measurement-body qualification, distinct from a reported MIC note and CFU response body.'
    built['accepted_matches'] = [old]; built['semantic_rechecks'] = [('U0001', 'FULL_REQUIREMENT')]
    payload = f._make_payload([unit], built, built['requirements'], {}, 1)
    assert len(payload['facts']) == 1
    assert not f.assemble_matches(built, {})['complete']
    result = f.assemble_matches(built, {'FACT001': f.materialize(answer(payload), payload)})['matches'][0]
    assert result['criteria'][1:] == old['criteria'][1:]
    full = result['criteria'][0]
    assert full['host_derivation']['original_judgment'] == old['criteria'][0]
    assert full['host_derivation']['semantic_recheck_status'] == 'OPEN'
    assert full['status'] == 'UNRESOLVED' and not full['host_derivation']['pure_aggregate']


def test_partial_child_with_valid_body_matches_necessity_aggregate_contract(case):
    from test_data_necessity_v5 import inputs
    from test_data_necessity_v4 import rules
    from research_pipeline import data_necessity_v5 as n
    built, payload = case
    payload['source_rows'][2][3] = 'MIC 4.2 mg/L'; built['catalog']['A:v']['content'] = 'MIC 4.2 mg/L'
    raw = answer(payload); raw['facts']['F0001'].update(e=[2], k='BODY_OBSERVATION')
    raw['facts']['F0002'].update(s='PARTIAL', n='Clarify endpoint window.')
    match = assemble(case, raw)['matches'][0]
    assert match['criteria'][0]['status'] == 'PARTIAL' and match['criteria'][0]['host_derivation']['pure_aggregate']
    plan, coverage, catalog = inputs()
    coverage['matches'][0]['criteria'] = match['criteria']
    coverage['matches'][0].setdefault('allowed_source_ids', []).extend(built['catalog'])
    catalog.update(built['catalog'])
    output = n.build_payload(plan, coverage, catalog, project_rules=rules())
    assert all(g['criterion_id'] != 'FULL_REQUIREMENT' for g in output['gaps'])


def test_targeted_context_note_requires_both_original_link_notes(case):
    built, _ = case
    built['catalog']['B:n']['content'] = 'Supporting study note: PMB MIC 0.5 mg/L for strain K1.'
    payload = f._make_payload(built['units'], built, built['requirements'], {}, 1, extras=['B'])
    raw = answer(payload)
    raw['unit_metadata']['U0001']['source_links'] = []
    raw['facts']['F0001']['e'] = [4]
    with pytest.raises(Exception, match='source link'): f.materialize(raw, payload)
    raw['unit_metadata']['U0001']['source_links'] = [{'item_id': 'B', 'relation': 'CONTEXT_DEPENDENCY',
        'scope_basis': 'Supporting note for strain K1 only, no body observation transfer.',
        'reason': 'Both original notes identify the same strain-specific MIC context.', 'evidence_indices': [3, 4]}]
    assert f.materialize(raw, payload)[0]['criteria'][0]['status'] == 'SUPPORTED'
    raw['unit_metadata']['U0001']['source_links'][0]['evidence_indices'] = [4, 4]
    with pytest.raises(Exception): f.materialize(raw, payload)


def test_search_accounting_is_local_not_other_scopes_in_same_packet(case):
    built, payload = case
    payload['visible_item_ids'].append('OTHER_SCOPE')
    payload['incomplete_item_ids'] = ['A', 'OTHER_SCOPE']
    criterion = f.materialize(answer(payload), payload)[0]['criteria'][0]
    assert criterion['searched_item_ids'] == ['A']
    assert criterion['incomplete_item_ids'] == ['A'] and criterion['unread_item_ids'] == ['A']


def test_explicit_original_record_link_can_supply_targeted_mic_body_context_cannot(case):
    built, _ = case
    built['catalog']['B:n']['content'] = 'MIC measurements for corresponding samples of strain K1 from panel A.'
    built['catalog']['B:B1'] = {'kind': 'SOURCE_HEADER', 'item_id': 'B', 'content': 'MIC mg/L'}
    built['catalog']['B:B2'] = {'kind': 'SOURCE_CONTENT', 'item_id': 'B', 'content': '0.5'}
    payload = f._make_payload(built['units'], built, built['requirements'], {}, 1, extras=['B'])
    raw = answer(payload); raw['facts']['F0001'].update(e=[6], k='BODY_OBSERVATION')
    link = {'item_id': 'B', 'relation': 'EXPLICIT_RECORD_LINK', 'scope_basis': 'Same strain K1, corresponding samples explicitly reported in the original note.',
            'reason': 'Original note explicitly links the measurement samples to panel A.', 'evidence_indices': [3, 4]}
    raw['unit_metadata']['U0001']['source_links'] = [link]
    assert f.materialize(raw, payload)[0]['criteria'][0]['status'] == 'SUPPORTED'
    link['relation'] = 'CONTEXT_DEPENDENCY'
    with pytest.raises(Exception, match='does not transfer'): f.materialize(raw, payload)
    link['relation'] = 'EXPLICIT_RECORD_LINK'; payload['source_rows'][4][3] = 'Same paper, another experiment.'
    with pytest.raises(Exception, match='study reference alone'): f.materialize(raw, payload)


def test_targeted_search_reviews_distinct_body_qualification_when_fields_are_supported(case):
    built, payload = case
    old = assemble(case, answer(payload))['matches']
    updated = f.build_search(built, old, {'U0001': ['B']})
    packet = updated['payloads'][0]
    assert len(packet['facts']) == 1
    assert next(iter(packet['facts'].values()))['targets'] == [
        {'unit_id': 'U0001', 'criterion_id': 'HOST_MEASUREMENT_QUALIFICATION'}]
    assert not f.assemble_matches(updated, {})['complete']


def test_targeted_search_cannot_silently_drop_original_counterevidence(case):
    built, payload = case
    raw = answer(payload)
    raw['facts']['F0001'].update(s='CONFLICT', x=[3], n='Resolve the original conflicting MIC statement.')
    old = assemble(case, raw)['matches']
    updated = f.build_search(built, old, {'U0001': ['B']})
    packet = updated['payloads'][0]
    response = answer(packet)
    response['unit_metadata']['U0001']['source_links'] = []
    with pytest.raises(Exception, match='counterevidence'):
        f.materialize(response, packet)
    field_id = next(fid for fid, fact in packet['facts'].items()
                    if fact['targets'][0]['criterion_id'] == 'FIELD_001')
    assert packet['facts'][field_id]['retained_counterevidence'][0]['evidence'] == old[0]['criteria'][1]['counterevidence']
    response['facts'][field_id].update(s='CONFLICT', x=[3], n='Resolve the retained conflict.')
    result = f.assemble_matches(updated, {packet['part_id']: f.materialize(response, packet)})['matches'][0]
    assert result['criteria'][1]['counterevidence'] == old[0]['criteria'][1]['counterevidence']
    assert result['criteria'][0]['status'] == 'CONFLICT'


def test_targeted_search_keeps_actual_search_scope_in_assembled_record(case):
    built, payload = case
    old = assemble(case, answer(payload))['matches']
    updated = f.build_search(built, old, {'U0001': ['B']})
    packet = updated['payloads'][0]
    response = answer(packet)
    response['unit_metadata']['U0001']['source_links'] = []
    matches = f.materialize(response, packet)
    result = f.assemble_matches(updated, {packet['part_id']: matches})['matches'][0]
    assert result['search_scope']['round'] == 'TARGETED_REVIEW'
    assert result['search_scope']['visible_item_ids'] == ['A', 'B']
    assert result['search_scope']['requested_item_ids'] == ['B']
    assert result['criteria'][1:] == old[0]['criteria'][1:]


def test_qualification_only_recheck_retains_deferred_producer_dependency(case):
    built, payload = case
    raw = answer(payload)
    raw['facts']['F0002'].update(s='DEFERRED', n='Wait for the approved qualified target.', k='DEFERRED_OUTPUT')
    raw['unit_metadata']['U0001']['deferred_outputs'] = [{'producer_task': 'PD_TARGET',
        'output': 'Qualified target', 'first_dependency': 'SIMULATE_PER_MIC_PTA', 'source_indices': [0]}]
    old = assemble(case, raw)['matches'][0]
    # Historical v4 stored the dependency separately from its output object.
    old['deferred_outputs'][0].pop('first_dependency')
    unit = built['units'][0]
    unit['fixed_criteria'] = {c['id']: copy.deepcopy(c) for c in old['criteria'][1:]}
    unit['original_full_judgment'] = copy.deepcopy(old['criteria'][0])
    unit['qualification_spec'] = 'MIC measurement-body qualification'
    built['accepted_matches'] = [old]
    built['semantic_rechecks'] = [('U0001', 'FULL_REQUIREMENT')]
    packet = f._make_payload([unit], built, built['requirements'], {}, 1)
    result = f.assemble_matches(built, {'FACT001': f.materialize(answer(packet), packet)})['matches'][0]
    assert result['deferred_outputs'] == old['deferred_outputs']
    assert result['deferred_dependencies'] == ['SIMULATE_PER_MIC_PTA']
    assert result['criteria'][1:] == old['criteria'][1:]


@pytest.mark.parametrize('linked', [True, False])
def test_targeted_new_counterevidence_preserves_supported_fact_and_rejects_unlinked_scope(case, linked):
    built, payload = case
    old = assemble(case, answer(payload))['matches']
    updated = f.build_search(built, old, {'U0001': ['B']})
    packet = updated['payloads'][0]
    response = answer(packet)
    response['unit_metadata']['U0001'].update(source_links=[], new_counterevidence=[{
        'criterion_id': 'FIELD_001', 'source_indices': [4],
        'reason': 'The newly read linked note reports a conflicting MIC value.',
        'needed_material': 'Resolve the reported MIC conflict in the original notes.'}])
    if linked:
        response['unit_metadata']['U0001']['source_links'] = [{'item_id': 'B', 'relation': 'CONTEXT_DEPENDENCY',
            'scope_basis': 'Original notes establish the context dependency for this reported value.',
            'reason': 'Only note context is used, no measurement body transfer.', 'evidence_indices': [3, 4]}]
        result = f.assemble_matches(updated, {packet['part_id']: f.materialize(response, packet)})['matches'][0]
        changed = result['criteria'][1]
        assert changed['status'] == 'CONFLICT'
        assert all(e in changed['evidence'] for e in old[0]['criteria'][1]['evidence'])
        assert changed['prior_judgment'] == old[0]['criteria'][1]
        assert changed['counterevidence'][0]['source'] == 'B:n'
        assert result['new_counterevidence'][0]['criterion_id'] == 'FIELD_001'
    else:
        with pytest.raises(Exception, match='source link'):
            f.materialize(response, packet)


def test_targeted_counterevidence_candidates_count_towards_packet_limit(case):
    from research_pipeline import data_coverage_v5 as runtime
    built, payload = case
    old = assemble(case, answer(payload))['matches']
    packet = f.build_search(built, old, {'U0001': ['B']})['payloads'][0]
    assert runtime._checks(packet) == 4  # One qualification plus three possible challenges.
    for index in range(4, 102):
        criterion = copy.deepcopy(old[0]['criteria'][1])
        criterion['id'] = 'FIELD_' + str(index).zfill(3)
        old[0]['criteria'].append(criterion)
    with pytest.raises(Exception, match='review budget'):
        f.build_search(built, old, {'U0001': ['B']})


def test_second_targeted_reading_retains_previously_admitted_counter_source_and_link(case):
    built, payload = case
    built['catalog']['C:n'] = {'kind': 'SOURCE_NOTE', 'item_id': 'C', 'content': 'Additional assay protocol.'}
    built['catalog']['B:unused'] = {'kind': 'SOURCE_CONTENT', 'item_id': 'B', 'content': 'Uncited body value.'}
    old = assemble(case, answer(payload))['matches']
    first = f.build_search(built, old, {'U0001': ['B']})
    packet = first['payloads'][0]
    response = answer(packet)
    response['unit_metadata']['U0001'].update(source_links=[{
        'item_id': 'B', 'relation': 'CONTEXT_DEPENDENCY', 'scope_basis': 'An established note context dependency.',
        'reason': 'Original local and target notes were reviewed together.', 'evidence_indices': [3, 4]}],
        new_counterevidence=[{'criterion_id': 'FIELD_001', 'source_indices': [4],
            'reason': 'Conflicting reported MIC in the newly read note.', 'needed_material': 'Resolve original MIC conflict.'}])
    parent = f.assemble_matches(first, {packet['part_id']: f.materialize(response, packet)})['matches']
    second = f.build_search(first, parent, {'U0001': ['C']})
    packet = second['payloads'][0]
    counter_index = next((r[4] for r in packet['source_rows'] if r[0] == 'B:n'), None)
    assert counter_index is not None, 'Previously admitted counterevidence must remain visible in the next reading'
    assert not any(r[0] == 'B:unused' for r in packet['source_rows'])
    response = answer(packet)
    response['unit_metadata']['U0001']['source_links'] = []  # No repeat approval of the immutable B link.
    fid = next(fid for fid, fact in packet['facts'].items() if fact['targets'][0]['criterion_id'] == 'FIELD_001')
    response['facts'][fid].update(s='CONFLICT', x=[counter_index], n='Resolve the retained MIC conflict.')
    result = f.assemble_matches(second, {packet['part_id']: f.materialize(response, packet)})['matches'][0]
    assert result['source_links'] == parent[0]['source_links']
    assert result['criteria'][1]['counterevidence'] == parent[0]['criteria'][1]['counterevidence']
    assert result['new_counterevidence'] == parent[0]['new_counterevidence']
    assert result['search_scope']['requested_item_ids'] == ['C']
    packet['retained_source_links']['U0001'][0]['evidence'][0]['quote'] = 'Invented linkage proof'
    with pytest.raises(Exception, match='original note proof'):
        f.materialize(response, packet)


def test_qualification_counterevidence_survives_summary_and_next_search(case):
    built, payload = case
    old = assemble(case, answer(payload))['matches']
    updated = f.build_search(built, old, {'U0001': ['B']})
    packet = updated['payloads'][0]
    response = answer(packet)
    response['unit_metadata']['U0001']['source_links'] = []
    response['facts']['F0001'].update(s='CONFLICT', x=[3], n='Resolve the measurement qualification conflict.')
    reviewed = f.assemble_matches(updated, {packet['part_id']: f.materialize(response, packet)})['matches']
    full = reviewed[0]['criteria'][0]
    assert full['status'] == 'CONFLICT'
    assert full['counterevidence'] == full['host_derivation']['measurement_qualification']['counterevidence']
    subsequent = f.build_search(updated, reviewed, {'U0001': ['B']})['payloads'][0]
    retry = answer(subsequent)
    retry['unit_metadata']['U0001']['source_links'] = []
    with pytest.raises(Exception, match='counterevidence'):
        f.materialize(retry, subsequent)
