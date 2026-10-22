"""Merged rule ownership, appendix integrity and current exported review artifacts."""
import copy
from pathlib import Path
import subprocess
import sys

import pytest

from ctxcomp.io import digest, read_json
from ctxcomp.rules import _check_terminology_appendix, attach_rules, load_rules


def resources():
    pack = load_rules()
    rules = {r['id']: r for r in pack['rules']}
    return pack, rules, rules['CC005']['details']


def test_cc005_unifies_the_checklist_and_single_terminology_appendix():
    pack, rules, details = resources()
    assert len(details['preserve']) == 13
    assert set(details['terminology_appendix']['categories']) == set(details['preserve'])
    assert details['terminology_appendix']['categories']['logic_scope_and_exceptions'] == []
    for stage in pack['pk_binding_knowledge']['scope']:
        payload = {'stage': stage, 'instructions': 'Read supplied evidence.'}
        attach_rules(payload, pack)
        cc005 = next(r for r in payload['processing_rules']['rules'] if r['id'] == 'CC005')
        assert cc005['details'] == details
        assert 'groups' not in cc005['details']['terminology_appendix']
        assert payload['processing_rules']['pk_binding_knowledge'] == pack['pk_binding_knowledge']
    # Attachment planning does not need the PK glossary; preservation still applies.
    payload = {'stage': 'attachment_plan', 'instructions': 'Plan evidence retrieval.'}
    attach_rules(payload, pack)
    assert 'pk_binding_knowledge' not in payload['processing_rules']
    assert not any(r['id'] == 'CC009' for r in payload['processing_rules']['rules'])
    assert any(r['id'] == 'CC005' for r in payload['processing_rules']['rules'])


@pytest.mark.parametrize('fault', ['missing_category', 'unknown_group', 'duplicate_reference', 'duplicate_group'])
def test_invalid_appendix_references_cannot_silently_enter_new_runs(fault):
    pack, _, details = resources()
    details = copy.deepcopy(details)
    profile = copy.deepcopy(pack['pk_binding_knowledge'])
    mapping = details['terminology_appendix']['categories']
    if fault == 'missing_category':
        mapping.pop('information_status')
    elif fault == 'unknown_group':
        mapping['information_status'].append('NONEXISTENT')
    elif fault == 'duplicate_reference':
        mapping['information_status'] *= 2
    else:
        profile['groups'].append(copy.deepcopy(profile['groups'][0]))
    with pytest.raises(ValueError, match='CC005 terminology'):
        _check_terminology_appendix(details, profile)


def test_abc_extends_existing_rules_and_retains_separate_authority():
    pack, rules, _ = resources()
    assert len(rules) == 15
    assert pack['consolidation']['A']['owner'] == 'CC009'
    assert pack['consolidation']['C']['owner'] == 'CC005'
    assert 'FACT/UNKNOWN is retention bookkeeping' in ' '.join(rules['CC009']['actions'])
    assert pack['scientific_extraction']['rule_owners']['classification'] == 'CC009'
    assert pack['project_rule_owner'] == 'PROJECT_RULES_AGENT'
    for stage in pack['scientific_extraction']['scope']:
        payload = {'stage': stage, 'instructions': 'Review.'}
        attach_rules(payload, pack)
        ids = {r['id'] for r in payload['processing_rules']['rules']}
        if stage == 'binding_repair':
            # This agent repairs exact bindings; it must preserve existing labels
            # and obligations rather than extract or reclassify them.
            assert {'CC005', 'CC011', 'CC015'} <= ids
            assert not {'CC007', 'CC009'} & ids
        else:
            assert {'CC005', 'CC007', 'CC009', 'CC011'} <= ids


def test_critical_error_criterion_is_approved_but_live_qualification_is_not_claimed():
    pack, rules, _ = resources()
    plan = rules['CC012']['qualification_requirement']['acceptance_plan']
    threshold = plan['metric_definitions_and_acceptance_thresholds']
    assert threshold['critical_unblocked_errors'] == 0
    assert 'not zero real-world error' in threshold['scope']
    assert plan['benchmark_status'] == 'DEFERRED_INSUFFICIENT_LABELLED_DOCUMENTS'
    assert pack['scientific_extraction']['qualification']['rule_reference'] == 'CC012.qualification_requirement'
    assert 'critical_error_acceptance' not in pack['scientific_extraction']['qualification']


def test_generated_reviews_and_hashes_match_the_runtime_pack():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, '-I', '-X', 'utf8',
        str(root/'research_pipeline/scripts/export_compression_rules_review.py'), '--check'],
        capture_output=True, text=True, encoding='utf-8')
    assert result.returncode == 0, result.stdout + result.stderr
    review = read_json(root/'research_pipeline/docs/interfaces/context_compression.review.json')
    pack = load_rules()
    assert review['source_snapshot']['compression_runtime_sha256'] == digest(pack)
    assert review['rules'] == {r['id']: r['instruction'] for r in pack['rules']}
    assert review['shared_rules'] == {r['id']: r['instruction'] for r in pack['governance']['rules']}
    assert review['version']['shared_governance'] == pack['governance']['version']
    interfaces = root / 'research_pipeline/docs/interfaces'
    governance = read_json(interfaces / 'workflow_governance.json')
    intake = read_json(interfaces / 'file_intake.runtime.json')
    general = read_json(interfaces / 'general_rules.review.json')
    layers = read_json(interfaces / 'rule_layers.review.json')
    assert governance == pack['governance'] == intake['governance']
    assert review['source_snapshot']['intake_runtime_sha256'] == digest(intake)
    assert general['version'] == layers['current_state']['governance_version'] == governance['version']
    assert layers['current_state']['compression_rules_version'] == pack['version']
    assert {r['id']: r['actions'] for r in governance['rules']} == {
        rid: r['actions'] for rid, r in general['rules'].items()}
