"""Contract and fault-injection tests. Authored verdicts do not benchmark an LLM."""
import copy
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from ctxcomp.engine import (STAGES, RESOURCE, init_run, load_run, prepare, accept,
                            verify_context)
from ctxcomp.io import read_json, write_json, leaves
from ctxcomp.providers import run_model
from ctxcomp.retention import (source_units, requirements_check, requirements_review_check,
                               context_coverage_check)
from attachment_fixture import accept_empty_search
from rule_versions import rules_1_30

EXAMPLES = Path(__file__).parents[1] / 'examples'
spec = importlib.util.spec_from_file_location('retention_demo', EXAMPLES / 'replay_demo.py')
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


@pytest.fixture(scope='module')
def reference_run(tmp_path_factory):
    run = tmp_path_factory.mktemp('retention') / 'complete'
    demo.replay(run)
    return run


def replay_until(run, reference_run, last):
    init_run(run, EXAMPLES / 'current_research/proposal.md', context_review_mode='legacy')
    for stage in STAGES[:STAGES.index(last) + 1]:
        response = read_json(reference_run / 'saved_responses' / (stage + '.json'))
        response['request_sha256'] = prepare(run, stage)['request_sha256']
        accept(run, stage, response)


def test_source_units_cover_original_text_without_loss():
    source = {'id': 'S', 'text': '# title\n\n' + 'ABC\n' * 2500 + '\n中文条件\n\nfinal'}
    units = source_units([source])
    assert ''.join(u['text'] for u in units) == source['text']
    assert all(source['text'][u['start_char']:u['end_char']] == u['text'] for u in units)
    assert all(a['end_char'] == b['start_char'] for a, b in zip(units, units[1:]))


def test_context_cannot_skip_inventory_or_its_review(tmp_path, reference_run):
    run = tmp_path / 'run'
    init_run(run, EXAMPLES / 'current_research/proposal.md', context_review_mode='legacy')
    with pytest.raises(ValueError, match='attachment_plan and attachment_evidence'):
        prepare(run, 'context')
    accept_empty_search(run)
    with pytest.raises(ValueError, match='requirements must be accepted'):
        prepare(run, 'context')
    response = read_json(reference_run / 'saved_responses/requirements.json')
    response['request_sha256'] = prepare(run, 'requirements')['request_sha256']
    accept(run, 'requirements', response)
    with pytest.raises(ValueError, match='requirements_review must be accepted'):
        prepare(run, 'context')


def test_inventory_review_has_no_candidate_and_context_review_has_evidence(tmp_path, reference_run):
    run = tmp_path / 'run'
    replay_until(run, reference_run, 'requirements')
    req = prepare(run, 'requirements_review')['payload']
    assert 'context' not in req and 'requirements' in req and 'source_units' in req
    response = read_json(reference_run / 'saved_responses/requirements_review.json')
    response['request_sha256'] = prepare(run, 'requirements_review')['request_sha256']
    accept(run, 'requirements_review', response)
    response = read_json(reference_run / 'saved_responses/context.json')
    response['request_sha256'] = prepare(run, 'context')['request_sha256']
    accept(run, 'context', response)
    req = prepare(run, 'context_review')['payload']
    assert req['evidence'] == response['evidence']
    assert req['evidence_audit'][0]['location']['source_id'] == 'S1'
    assert 'requirements_review_sha256' in req


@pytest.mark.parametrize('collection', ['items', 'source_units'])
def test_incomplete_inventory_review_blocks_generation(tmp_path, reference_run, collection):
    run = tmp_path / 'run'
    replay_until(run, reference_run, 'requirements')
    response = read_json(reference_run / 'saved_responses/requirements_review.json')
    response['request_sha256'] = prepare(run, 'requirements_review')['request_sha256']
    response['review'][collection].pop()
    with pytest.raises(ValueError, match='exactly once'):
        accept(run, 'requirements_review', response)
    assert read_json(run / 'stopped.json')['stage'] == 'requirements_review'
    assert not (run / 'compressed_context.json').exists()
    assert list((run / 'submissions').glob('requirements_review.*.json'))


def test_inventory_missing_source_obligation_stops_before_context(tmp_path, reference_run, monkeypatch):
    from rule_versions import before_1_29, freeze
    freeze(monkeypatch, before_1_29())  # From 1.29.0 the host first revises once (test_same_run_revision).
    run = tmp_path / 'run'
    init_run(run, EXAMPLES / 'current_research/proposal.md', context_review_mode='legacy')
    calls = []
    def model(request, model=None):
        stage = request['payload']['stage']
        calls.append(stage)
        response = read_json(reference_run / 'saved_responses' / (stage + '.json'))
        response['request_sha256'] = request['request_sha256']
        if stage == 'requirements_review':
            response['review']['decision'] = 'REVISE'
            response['review']['source_units'][0]['verdict'] = 'MISSING'
        return response
    assert run_model(run, generator=model)['status'] == 'REVISE'
    # An empty attachment plan completes deterministically, without a model call.
    state = load_run(run)[1]
    assert read_json(run / state['accepted']['attachment_plan']['file'])['questions'] == []
    assert calls == ['attachment_plan', 'requirements', 'requirements_review']
    assert 'attachment_evidence' in load_run(run)[1]['accepted']
    assert 'context' not in load_run(run)[1]['accepted']


def test_model_failure_is_not_retried(tmp_path):
    run = tmp_path / 'run'
    init_run(run, EXAMPLES / 'current_research/proposal.md', context_review_mode='legacy')
    calls = []
    def failure(request, model=None):
        calls.append(request['payload']['stage'])
        raise ValueError('backend failed')
    with pytest.raises(ValueError, match='backend failed'):
        run_model(run, generator=failure)
    assert calls == ['attachment_plan']
    assert read_json(run / 'stopped.json')['status'] == 'ERROR'
    with pytest.raises(ValueError, match='automatic retries are disabled'):
        run_model(run, attempts=2, generator=failure)


@pytest.mark.usefixtures('rules_1_30')
def test_default_model_run_ends_at_b1(tmp_path, reference_run):
    run = tmp_path / 'run'
    init_run(run, EXAMPLES / 'current_research/proposal.md', context_review_mode='legacy')
    calls = []
    def model(request, model=None):
        stage = request['payload']['stage']
        calls.append(stage)
        response = read_json(reference_run / 'saved_responses' / (stage + '.json'))
        response['request_sha256'] = request['request_sha256']
        return response
    assert run_model(run, generator=model)['status'] == 'CONTEXT_READY'
    assert calls == [s for s in STAGES[:STAGES.index('context_review') + 1] if s != 'attachment_evidence']
    assert 'attachment_evidence' in load_run(run)[1]['accepted']
    assert verify_context(run)['status'] == 'VALID'
    assert not (run / 'project_plan.candidate.json').exists()
    result = subprocess.run([sys.executable, '-I', '-m', 'ctxcomp', 'verify-context', '--run', str(run)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize('artifact', ['critical_requirements.json', 'coverage_report.json'])
def test_modified_sidecar_invalidates_verification(tmp_path, reference_run, artifact):
    run = tmp_path / 'run'
    shutil.copytree(reference_run, run)
    value = read_json(run / artifact)
    value['tampered'] = True
    write_json(run / artifact, value)
    with pytest.raises(ValueError, match='changed'):
        verify_context(run)


def test_modified_accepted_inventory_invalidates_old_review(tmp_path, reference_run):
    run = tmp_path / 'run'
    shutil.copytree(reference_run, run)
    state = read_json(run / 'state.json')
    path = run / state['accepted']['requirements']['file']
    value = read_json(path)
    value['requirements']['items'][0]['statement'] = 'changed'
    write_json(path, value)
    with pytest.raises(ValueError, match='Accepted requirements changed'):
        verify_context(run)


@pytest.mark.parametrize('change', ['coverage', 'components', 'decomposition', 'atoms', 'wrong_target'])
def test_incomplete_bidirectional_review_rejected(tmp_path, reference_run, change):
    run = tmp_path / 'run'
    replay_until(run, reference_run, 'context')
    response = read_json(reference_run / 'saved_responses/context_review.json')
    response['request_sha256'] = prepare(run, 'context_review')['request_sha256']
    review = response['review']
    if change == 'coverage':
        review['coverage'].pop()
    elif change == 'components':
        review['coverage'][0]['components'][0]['component_id'] = 'UNKNOWN'
    elif change == 'decomposition':
        review['decomposition'].pop()
    elif change == 'atoms':
        review['atomic_claims'].pop()
    else:
        review['coverage'][0]['components'][0]['targets'][0]['quote'] = 'Invented context phrase'
    with pytest.raises(ValueError):
        accept(run, 'context_review', response)
    assert not (run / 'compressed_context.json').exists()


def pmb_fixture(tmp_path, mutation):
    """Source obligations + manually specified review labels for known mutations."""
    gate = 'Each module requires unit tests and a simulated recovery test before it becomes eligible.'
    trigger = 'If BLQ values exceed 10 percent of a stratum or cluster in a terminal or pulmonary phase'
    action = 'censored likelihood is the primary approach.'
    limitation = 'Deleting BLQ observations is a sensitivity analysis only.'
    blq = trigger + ', ' + action + ' ' + limitation
    source = 'Study PMB.\n\n' + gate + '\n\n' + blq
    path = tmp_path / 'pmb.md'
    path.write_text(source, encoding='utf-8')
    run = tmp_path / 'run'
    init_run(run, path, context_review_mode='legacy')
    accept_empty_search(run)
    units = load_run(run)[0]['source_units']
    requirements = demo.fixture_requirements({'/checks/0': gate, '/checks/1': blq}, units)
    requirements['items'][0]['components'] = [
        {'id': 'C1', 'role': 'PRECONDITION', 'text': 'unit tests and a simulated recovery test',
         'evidence': demo.spans_for_quote('unit tests and a simulated recovery test', units)},
        {'id': 'C2', 'role': 'LIMITATION', 'text': 'before it becomes eligible',
         'evidence': demo.spans_for_quote('before it becomes eligible', units)}]
    requirements['items'][1]['components'] = [
        {'id': f'C{i}', 'role': role, 'text': text, 'evidence': demo.spans_for_quote(text, units)}
        for i, (role, text) in enumerate([('TRIGGER', trigger), ('ACTION', action), ('LIMITATION', limitation)], 1)]
    accept(run, 'requirements', {'request_sha256': prepare(run, 'requirements')['request_sha256'],
                                 'requirements': requirements})
    accept(run, 'requirements_review', {'request_sha256': prepare(run, 'requirements_review')['request_sha256'],
                                       'review': demo.fixture_requirements_review(requirements, units)})
    context = {'version': '3.0', 'objective': 'Study PMB.',
               'study': {k: 'NOT_FOUND' for k in ['drug', 'regimen', 'population', 'system', 'measurements', 'methods']},
               'data': {'available': [], 'required': []}, 'rules': [], 'checks': [gate, blq], 'uncertainties': []}
    context['study']['drug'] = 'PMB'
    bad_component = None
    if mutation == 'recovery':
        context['checks'][0] = gate.replace(' and a simulated recovery test', '')
        bad_component = (0, 0)
    elif mutation == 'or_to_and':
        context['checks'][1] = blq.replace('or cluster', 'and cluster')
        bad_component = (1, 0)
    elif mutation == 'greater_equal':
        context['checks'][1] = blq.replace('exceed 10 percent', 'are at least 10 percent')
        bad_component = (1, 0)
    elif mutation == 'sensitivity_only':
        context['checks'][1] = blq.replace(limitation, 'Deleting BLQ observations is allowed.')
        bad_component = (1, 2)
    evidence = []
    for pointer, value in leaves(context):
        if pointer == '/version':
            continue
        quote = gate if pointer == '/checks/0' else blq if pointer == '/checks/1' else value
        status = 'NOT_FOUND' if value == 'NOT_FOUND' else 'EXPLICIT'
        evidence.append({'path': pointer, 'status': status, 'source_id': '' if status == 'NOT_FOUND' else 'S1',
                         'quote': '' if status == 'NOT_FOUND' else quote, 'reason': 'Authored fault-injection test.'})
    accept(run, 'context', {'request_sha256': prepare(run, 'context')['request_sha256'], 'context': context, 'evidence': evidence})
    atoms, decomposition = demo.fixture_atoms(context, evidence, units)
    review = {'decision': 'PASS', 'reviewer': 'Authored mutation labels', 'review_type': 'ASSISTANT_INTERNAL_REVIEW',
              'claims': [{'path': p, 'verdict': 'PRESERVED', 'reason': 'Fixture.'} for p, v in leaves(context) if p != '/version'],
              'retention': [{'source_id': 'S1', 'quote': gate, 'verdict': 'PRESERVED', 'critical': True, 'reason': 'Fixture.'}],
              'critical_errors': [], 'limitations': ['Authored judgments test gates, not LLM detection.'],
              'atomic_claims': atoms, 'decomposition': decomposition,
              'scientific_checks': [{'id': r['id'], 'faithfulness': 'PRESERVED', 'completeness': 'PRESERVED',
                                     'reason': 'Authored metadata fixture; core-context mutation tested separately.'}
                                    for r in requirements['items']],
              'coverage': demo.fixture_coverage(requirements, ['/checks/0', '/checks/1'], context)}
    if bad_component:
        row, component = bad_component
        review['decision'] = 'REVISE'
        review['coverage'][row]['verdict'] = 'ALTERED'
        review['coverage'][row]['components'][component]['verdict'] = 'ALTERED'
        review['coverage'][row]['components'][component]['reason'] = 'Known source condition changed in this test.'
    return run, review


@pytest.mark.parametrize('mutation', ['recovery', 'or_to_and', 'greater_equal', 'sensitivity_only'])
def test_known_semantic_mutation_blocks_publication(tmp_path, mutation):
    run, review = pmb_fixture(tmp_path, mutation)
    response = {'request_sha256': prepare(run, 'context_review')['request_sha256'], 'review': review}
    assert accept(run, 'context_review', response)['status'] == 'REVISE'
    report = read_json(run / 'coverage_report.json')
    assert report['critical_recall'] == 0.5
    assert report['independent_accuracy'] is None
    assert not (run / 'compressed_context.json').exists()
    # Contradictory PASS must also fail, even if all old field-level judgments say preserved.
    review['decision'] = 'PASS'
    requirements = read_json(run / 'critical_requirements.json')
    original = next((run / 'accepted').glob('context.*.json'))
    value = read_json(original)
    with pytest.raises(ValueError, match='PASS contradicts'):
        context_coverage_check(review, requirements, value['context'], value['evidence'], load_run(run)[0]['source_units'])


def test_unchanged_pmb_rules_can_pass_contract_checks(tmp_path):
    run, review = pmb_fixture(tmp_path, None)
    response = {'request_sha256': prepare(run, 'context_review')['request_sha256'], 'review': review}
    assert accept(run, 'context_review', response)['status'] == 'ACCEPTED'
    assert verify_context(run)['critical_recall'] == 1


def test_unknown_judgment_keeps_recall_null(tmp_path):
    run, review = pmb_fixture(tmp_path, None)
    review['decision'] = 'NEEDS_REVIEW'
    review['coverage'][0]['verdict'] = 'UNRESOLVED'
    review['coverage'][0]['components'][0]['verdict'] = 'UNRESOLVED'
    response = {'request_sha256': prepare(run, 'context_review')['request_sha256'], 'review': review}
    assert accept(run, 'context_review', response)['status'] == 'NEEDS_REVIEW'
    assert read_json(run / 'coverage_report.json')['critical_recall'] is None


def test_stale_review_cannot_be_reused_on_another_candidate(tmp_path, reference_run):
    run = tmp_path / 'run'
    replay_until(run, reference_run, 'requirements_review')
    response = read_json(reference_run / 'saved_responses/context.json')
    response['context']['checks'][0] = 'Include PBPK.'
    response['request_sha256'] = prepare(run, 'context')['request_sha256']
    accept(run, 'context', response)
    stale = read_json(reference_run / 'saved_responses/context_review.json')
    with pytest.raises(ValueError, match='Stale response'):
        accept(run, 'context_review', stale)
    assert not (run / 'compressed_context.json').exists()


def test_critical_rule_cannot_be_demoted_against_selection(tmp_path):
    run, _ = pmb_fixture(tmp_path, None)
    requirements = read_json(run / 'critical_requirements.json')
    requirements['items'][0]['critical'] = False
    with pytest.raises(ValueError, match='Critical classification'):
        requirements_check(requirements, load_run(run)[0]['source_units'])


def test_cli_revise_returns_nonzero_and_no_context(tmp_path, reference_run):
    run = tmp_path / 'run'
    replay_until(run, reference_run, 'requirements')
    response = read_json(reference_run / 'saved_responses/requirements_review.json')
    response['request_sha256'] = prepare(run, 'requirements_review')['request_sha256']
    response['review']['decision'] = 'REVISE'
    response['review']['source_units'][0]['verdict'] = 'MISSING'
    path = tmp_path / 'review.json'
    write_json(path, response)
    result = subprocess.run([sys.executable, '-I', '-m', 'ctxcomp', 'accept', '--run', str(run),
                             '--stage', 'requirements_review', '--response', str(path)],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert 'REVISE' in result.stdout
    assert not (run / 'compressed_context.json').exists()


def test_rule_cannot_be_preserved_as_only_a_proposal(tmp_path):
    run, review = pmb_fixture(tmp_path, None)
    original = read_json(next((run / 'accepted').glob('context.*.json')))
    evidence = original['evidence']
    next(e for e in evidence if e['path'] == '/checks/0')['status'] = 'PROPOSED'
    with pytest.raises(ValueError, match='PROPOSED or NOT_FOUND'):
        context_coverage_check(review, read_json(run / 'critical_requirements.json'),
                               original['context'], evidence, load_run(run)[0]['source_units'])


def test_false_decomposition_pass_cannot_hide_unresolved_atomic_claim(tmp_path):
    run, review = pmb_fixture(tmp_path, None)
    review['atomic_claims'][0]['verdict'] = 'UNRESOLVED'
    response = {'request_sha256': prepare(run, 'context_review')['request_sha256'], 'review': review}
    with pytest.raises(ValueError, match='PASS contradicts'):
        accept(run, 'context_review', response)
    assert not (run / 'compressed_context.json').exists()


def test_unknown_unit_or_fabricated_quote_rejected(tmp_path):
    run, _ = pmb_fixture(tmp_path, None)
    requirements = read_json(run / 'critical_requirements.json')
    requirements['items'][0]['components'][0]['evidence'][0]['unit_id'] = 'INVENTED'
    with pytest.raises(ValueError, match='declared source unit'):
        requirements_check(requirements, load_run(run)[0]['source_units'])


def test_legacy_run_cannot_silently_skip_new_gates(tmp_path):
    from ctxcomp.io import digest
    run = tmp_path / 'legacy'
    init_run(run, EXAMPLES / 'current_research/proposal.md', context_review_mode='legacy')
    bundle, state = load_run(run)
    bundle.pop('workflow_version')
    state['inputs_sha256'] = digest(bundle)
    write_json(run / 'inputs.json', bundle)
    write_json(run / 'state.json', state)
    with pytest.raises(ValueError, match='Legacy run'):
        prepare(run, 'context')
