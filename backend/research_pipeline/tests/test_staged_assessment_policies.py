"""Policy/example consistency only: no scientific data, fits or stage execution."""
import copy
import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError

from research_pipeline.common import PipelineError
from research_pipeline.staged_assessment_policy import DEFAULT_MANIFEST, load_bundle


@pytest.fixture(scope='module')
def bundle():
    return load_bundle()


def validate_case(bundle, kind, value):
    schema = bundle['schema']
    Draft202012Validator({'$defs': schema['$defs'], '$ref': '#/$defs/' + kind}).validate(value)


def example(bundle, kind, **matching):
    for row in bundle['references']['examples']:
        if row['case_schema'] == kind and all(row['case'].get(k) == v for k, v in matching.items()):
            return copy.deepcopy(row['case'])
    raise AssertionError('Requested hypothetical case is absent')


def test_loader_binds_unactivated_policies_sources_and_real_rule_ids(bundle):
    assert bundle['manifest']['runtime_integration'] == 'NOT_CONNECTED'
    assert bundle['manifest']['supersedes'] == []
    assert {bundle[k]['status'] for k in ('coverage_policy', 'necessity_policy', 'references')} == {'AUTHORED_NOT_ACTIVATED'}
    assert len(bundle['coverage_policy']['rules']) == 7
    assert len(bundle['necessity_policy']['rules']) == 6
    assert {a['family'] for a in bundle['references']['action_templates']} == {'NCA', 'MODEL_BASED', 'PD_INDEX', 'PD_TARGET', 'PTA'}
    assert all(e['hypothetical'] for e in bundle['references']['examples'])
    assert bundle['references']['authority'] == 'REFERENCE_KNOWLEDGE_NOT_SOURCE_DATA'


def test_every_published_example_satisfies_its_declared_contract(bundle):
    for ex in bundle['references']['examples']:
        validate_case(bundle, ex['case_schema'], ex['case'])


@pytest.mark.parametrize('search', ['ASSIGNED_ONLY', 'TARGETED_INCOMPLETE'])
def test_unfinished_permitted_source_search_cannot_be_called_missing(bundle, search):
    case = example(bundle, 'coverage_case', status='MISSING')
    case['search_state'] = search
    with pytest.raises(ValidationError):
        validate_case(bundle, 'coverage_case', case)
    case['status'] = 'UNRESOLVED'
    validate_case(bundle, 'coverage_case', case)


def test_counterevidence_cannot_be_erased_by_supported_values(bundle):
    case = example(bundle, 'coverage_case', conflict=True)
    case['status'] = 'SUPPORTED'
    with pytest.raises(ValidationError):
        validate_case(bundle, 'coverage_case', case)


def test_planned_output_is_deferred_not_missing_source_data(bundle):
    case = example(bundle, 'coverage_case', status='MISSING')
    case.update(planned_output=True)
    with pytest.raises(ValidationError):
        validate_case(bundle, 'coverage_case', case)
    case['status'] = 'DEFERRED'
    validate_case(bundle, 'coverage_case', case)


def test_future_target_does_not_block_unrelated_current_action(bundle):
    case = example(bundle, 'action_case', depends_on_this_action=False)
    case['blocked'] = True
    with pytest.raises(ValidationError):
        validate_case(bundle, 'action_case', case)


def test_same_output_remains_needed_when_dependent_action_is_due(bundle):
    case = example(bundle, 'action_case', depends_on_this_action=True)
    case['blocked'] = False
    with pytest.raises(ValidationError):
        validate_case(bundle, 'action_case', case)


def test_required_input_cannot_be_cancelled_just_because_it_is_missing(bundle):
    case = example(bundle, 'action_case', depends_on_this_action=True)
    case.update(coverage_status='MISSING', applicability='NOT_APPLICABLE', blocked=False)
    with pytest.raises(ValidationError):
        validate_case(bundle, 'action_case', case)
    case['applicability_basis'] = 'ORIGINAL_RULE_EXCEPTION'
    validate_case(bundle, 'action_case', case)  # Explicit exception semantics are a separate evidence review.


def test_clear_original_exception_is_not_automatically_sent_to_human(bundle):
    case = example(bundle, 'exception_case', decision='EXCEPTION_APPLIES')
    case['decision'] = 'HUMAN_REVIEW'
    with pytest.raises(ValidationError):
        validate_case(bundle, 'exception_case', case)


@pytest.mark.parametrize('field', ['human_required', 'conflict'])
def test_original_human_gate_or_conflict_prevents_automatic_exception_decision(bundle, field):
    case = example(bundle, 'exception_case', decision='EXCEPTION_APPLIES')
    case[field] = True
    with pytest.raises(ValidationError):
        validate_case(bundle, 'exception_case', case)
    case['decision'] = 'HUMAN_REVIEW'
    validate_case(bundle, 'exception_case', case)


def test_no_original_clause_means_no_invented_exception(bundle):
    case = example(bundle, 'exception_case', decision='EXCEPTION_APPLIES')
    case['clause_present'] = False
    with pytest.raises(ValidationError):
        validate_case(bundle, 'exception_case', case)


@pytest.mark.parametrize('field', ['scope_equal', 'source_link_supported', 'fact_definition_equal', 'source_versions_equal'])
def test_shared_fact_reuse_requires_all_scope_definition_and_provenance_checks(bundle, field):
    case = example(bundle, 'shared_fact_case', reuse=True)
    case[field] = False
    with pytest.raises(ValidationError):
        validate_case(bundle, 'shared_fact_case', case)


@pytest.mark.parametrize('field,value', [('needed_for_current_action', False), ('applicability_resolved', False),
    ('permitted_search_complete', False), ('existing_material_can_supply', True),
    ('definition_pending', True), ('planned_output_pending', True)])
def test_new_data_advice_requires_actual_necessity_and_exhausted_permitted_alternatives(bundle, field, value):
    case = example(bundle, 'new_data_case', suggest_new_data=True)
    case[field] = value
    with pytest.raises(ValidationError):
        validate_case(bundle, 'new_data_case', case)


def test_new_data_advice_never_authorizes_an_experiment(bundle):
    case = example(bundle, 'new_data_case', suggest_new_data=True)
    case['experiment_authorized'] = True
    with pytest.raises(ValidationError):
        validate_case(bundle, 'new_data_case', case)


def test_alternative_route_policy_does_not_require_both_routes(bundle):
    contract = bundle['necessity_policy']['decision_contract']
    assert contract['animal_pk_preference'] == ['MODEL_BASED', 'NCA']
    assert contract['group_satisfaction'] == 'ANY_APPLICABLE_ROUTE'
    assert contract['rewrite_coverage'] is False
    assert contract['missing_implies_not_applicable'] is False
    assert contract['new_data_suggestion_authorizes_experiment'] is False


def test_action_templates_reference_existing_mp_profiles_and_keep_project_isolation(bundle):
    source = next(s for s in bundle['references']['sources'] if s['id'] == 'MP')
    import re
    for action in bundle['references']['action_templates']:
        for item in [action] + action['inputs']:
            assert set(re.findall(r'MP\d{3}', item['locator'])) <= set(source['ids'])
        assert {'regimen', 'window', 'record_level', 'concentration_basis'} <= set(action['scope_fields'])
    assert set(bundle['references']['project_scope']['protected_roles']) == {'HUMAN_PK_HOLDOUT', 'HORSE_HOLDOUT', 'BENCHMARK_RESULTS'}
    pta = next(a for a in bundle['references']['action_templates'] if a['action_id'] == 'SIMULATE_PER_MIC_PTA')
    assert '逐MIC PTA不要求MIC频数分布' in pta['not_required']
    target = next(a for a in bundle['references']['action_templates'] if a['action_id'] == 'ESTIMATE_PD_TARGET')
    assert any('不要求先选winning index' in s for s in target['not_required'])


def copied_manifest(tmp_path):
    manifest = json.loads(DEFAULT_MANIFEST.read_text(encoding='utf-8'))
    for row in manifest['files']:
        (tmp_path / row['path']).write_bytes((DEFAULT_MANIFEST.parent / row['path']).read_bytes())
    path = tmp_path / DEFAULT_MANIFEST.name
    path.write_text(json.dumps(manifest), encoding='utf-8')
    return path, manifest


def test_loader_rejects_changed_policy_bytes_before_loading(tmp_path):
    path, manifest = copied_manifest(tmp_path)
    policy = tmp_path / manifest['files'][0]['path']
    policy.write_bytes(policy.read_bytes() + b' ')
    with pytest.raises(PipelineError, match='hash changed'):
        load_bundle(path)


def test_loader_rejects_reference_promoted_to_source_data_even_with_updated_file_hash(tmp_path):
    path, manifest = copied_manifest(tmp_path)
    row = next(r for r in manifest['files'] if r['role'] == 'references')
    ref_path = tmp_path / row['path']
    value = json.loads(ref_path.read_text(encoding='utf-8'))
    value['authority'] = 'SOURCE_DATA'
    ref_path.write_text(json.dumps(value), encoding='utf-8')
    row['file_sha256'] = hashlib.sha256(ref_path.read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(PipelineError):
        load_bundle(path)
