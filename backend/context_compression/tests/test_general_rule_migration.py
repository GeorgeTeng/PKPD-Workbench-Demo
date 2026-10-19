"""Shared-rule delivery and retained compression boundaries; no live model claims."""
import copy
import json
from pathlib import Path

import pytest

from ctxcomp.governance import attach_governance, load_governance
from ctxcomp.io import digest, read_json
from ctxcomp.rules import attach_rules, load_rules


def test_promoted_principles_are_delivered_as_text_to_fresh_requests():
    first = {'stage': 'animal_pk', 'instructions': 'Review the assigned model.'}
    second = {'stage': 'data_qc', 'instructions': 'Check assigned data.'}
    for payload in (first, second):
        attach_governance(payload)
        rules = payload['governance']['rules']
        assert [r['id'] for r in rules] == [f'G{i:03}' for i in range(1, 9)]
        assert all(r['instruction'] and r['actions'] for r in rules)
        assert 'G002' in payload['instructions'] and 'G008' in payload['instructions']
        assert 'processing_rules' not in payload
        assert payload['governance_sha256'] == digest(payload['governance'])
    first['governance']['rules'][1]['instruction'] = 'Changed after delivery'
    assert second['governance'] == load_governance()


def test_compression_extensions_cannot_lose_their_shared_dependencies():
    pack = load_rules()
    pack['governance']['rules'] = pack['governance']['rules'][:1]
    with pytest.raises(ValueError, match='Missing shared governance'):
        attach_rules({'stage': 'context', 'instructions': 'Build context.'}, pack)


def test_compression_keeps_specialist_detail_and_project_rule_extraction():
    p = {'stage': 'context', 'instructions': 'Build context.'}
    attach_rules(p, load_rules())
    rules = {r['id']: r for r in p['processing_rules']['rules']}
    assert len(rules['CC005']['details']['preserve']) == 13
    assert rules['CC005']['general_rules'] == ['G004']
    assert 'Project Rules Agent' in rules['CC007']['instruction']
    assert 'context.rules empty' in ' '.join(rules['CC007']['actions'])
    assert 'PROPOSED' in ' '.join(rules['CC009']['actions'])
    assert 'Do not browse' in ' '.join(rules['CC003']['actions'])
    assert set(rules['CC019']['handoff_requirement']['required_fields']) == {
        'id', 'field', 'status', 'needed_at', 'impact'}


def test_frozen_v1_governance_keeps_original_request_identity():
    old = {'version': '1.0.0', 'scope': 'ALL_WORKFLOW_STEPS',
           'rules': [copy.deepcopy(load_governance()['rules'][0])]}
    prefix = ('Apply governance rule G001 first, then the rules for this step. '
              'Preserve inherited rule IDs and their source-artifact versions; do not renumber a filtered subset. '
              'Governance is processing policy, not a scientific project rule.\n')
    expected = {'instructions': prefix + 'Frozen task.', 'governance': old,
                'governance_sha256': digest(old)}
    p = {'instructions': 'Frozen task.'}
    attach_governance(p, old)
    assert p == expected and digest(p) == digest(expected)
    attach_governance(p, old)
    assert p == expected
    with pytest.raises(ValueError, match='Conflicting'):
        attach_governance(p)


def test_every_compression_extension_resolves_in_delivered_governance():
    pack = load_rules()
    for stage in pack['scope']['internal_roles']:
        p = {'stage': stage, 'instructions': 'Perform this task.'}
        attach_rules(p, pack)
        shared_ids = {r['id'] for r in p['governance']['rules']}
        for rule in p['processing_rules']['rules']:
            assert set(rule.get('general_rules', [])) <= shared_ids
        assert p['processing_rules_sha256'] == digest(p['processing_rules'])


def test_g008_requires_closure_at_needed_at_and_frozen_g007_requests_stay_unchanged():
    g008 = load_governance()['rules'][-1]
    text = g008['instruction'] + ' '.join(g008['actions'])
    assert g008['id'] == 'G008' and 'needed_at' in text
    for outcome in ('RESOLVED', 'LIMITATION_ACCEPTED', 'ESCALATED', 'CARRIED'):
        assert outcome in text
    # Host enforcement is claimed only for the handoffs that have it.
    assert all(x in g008['implementation'] for x in ('CC019', 'DC007', 'DH004', 'model instruction'))
    assert 'G008' in next(r for r in load_rules()['rules'] if r['id'] == 'CC019')['general_rules']
    old = read_json(Path(__file__).resolve().parents[2]
                    / 'research_pipeline/docs/review_drafts/history/workflow_governance.1.4.0.json')
    assert [r['id'] for r in old['rules']] == [f'G{i:03}' for i in range(1, 8)]
    p = {'instructions': 'Frozen task.'}
    attach_governance(p, old)
    assert p['instructions'] == old['instruction_prefix'] + 'Frozen task.'
    assert p['governance_sha256'] == digest(old) and 'G008' not in json.dumps(p)
