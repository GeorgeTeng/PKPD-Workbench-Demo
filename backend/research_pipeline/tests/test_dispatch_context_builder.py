"""Offline handoff integration; no EDA runner, approvals or model calls."""
import copy
import pytest
from research_pipeline import clinical_dispatch as dispatch, context_builder as cb
from research_pipeline.animal_pk import build_plan
from research_pipeline.common import PipelineError, read_json, write_json
from research_pipeline.adequacy import file_ref
from test_project_rule_agent import bundle


@pytest.fixture
def routed_inputs(tmp_path, monkeypatch):
    main = {'objective': 'Synthetic animal PK and index analysis',
            'study': {'drug': 'Synthetic', 'methods': 'Animal PK; fAUC/MIC.'},
            'rules': [
                {'id': 'PK', 'text': 'Check animal PK identifiability.', 'stages': ['animal_pk']},
                {'id': 'PD', 'text': 'Match exposure and PD endpoints.', 'stages': ['index']}]}
    assessment = {'tasks': [
        {'id': 'pk', 'destination': 'pk', 'question': 'Fit animal PK.', 'endpoint': 'plasma'},
        {'id': 'pd', 'destination': 'index', 'question': 'Compare exposure-response indices.',
         'endpoint': 'log10 CFU', 'endpoint_window': '24 hours'},
        {'id': 'unknown', 'question': 'Unclassified research question.'}],
        'requirements': [{'id': 'RQ-PD', 'task_id': 'pd', 'status': 'DEFERRED',
                          'needed_material': 'Matched MIC', 'reason': 'Confirm matching.'}]}
    datasets = []
    for identifier, role in [('PK', 'PK_OBSERVATIONS'), ('PD', 'PD_OBSERVATIONS'),
                             ('DOSE', 'DOSING'), ('OTHER', 'UNKNOWN')]:
        folder = tmp_path / identifier
        metadata = {'role': role, 'permission': 'DEVELOPMENT_CANDIDATE', 'species': 'mouse',
                    'matrix': 'plasma', 'record_level': 'INDIVIDUAL', 'exposure_basis': 'total',
                    'route': 'IV', 'source_table': {'title': 'Synthetic ' + identifier}}
        data = file_ref(write_json(folder/'data.json', {'records': [
            {'id': 'a', 'time': 0, 'concentration': 1}]}))
        csv = folder/'data.csv'
        csv.write_text('id,time,concentration\na,0,1\n', encoding='utf-8')
        datasets.append({'id': identifier, 'role': role, 'metadata': metadata,
            'data': data, 'csv': file_ref(csv),
            'metadata_file': file_ref(write_json(folder/'metadata.json',
                {'dataset_id': identifier, 'data_file': data, 'metadata': metadata})),
            'quarantine': file_ref(write_json(folder/'quarantine.json', {'records': []}))})
    eda = {'datasets': [{'dataset_id': d['id'], 'findings': [
        {'dataset_id': d['id'], 'reason': 'Descriptive evidence for ' + d['id']}]} for d in datasets]}
    def artifact(name, value):
        return {'name': name, **file_ref(write_json(tmp_path/name, value))}
    snapshot = {'nodes': {
        'adequacy': {'output_signature': 'synthetic-assessment',
                     'artifacts': [artifact('effective_main.json', main),
                                   artifact('assessment.json', assessment)]},
        'eda': {'output_signature': 'synthetic-eda',
                'artifacts': [artifact('eda_report.json', eda)]}}}
    ref = file_ref(write_json(tmp_path/'snapshot.json', snapshot))
    source = (snapshot, main, assessment, eda, datasets)
    # Replace only disabled intake with synthetic fixtures, not production gates.
    monkeypatch.setattr(dispatch, 'inputs', lambda *a, **k: copy.deepcopy(source))
    from ctxcomp import providers
    monkeypatch.setattr(providers, 'codex_generate',
                        lambda *a, **k: pytest.fail('Routing must not call a model'))
    return ref, datasets


def test_router_uses_builder_for_isolated_compatible_handoffs(routed_inputs, tmp_path, monkeypatch):
    ref, datasets = routed_inputs
    called = []
    original = cb.build_branch_handoff
    def tracked(branch, **kwargs):
        called.append((branch, [t['id'] for t in kwargs['assignment']['tasks']]))
        return original(branch, **kwargs)
    monkeypatch.setattr(cb, 'build_branch_handoff', tracked)
    out = tmp_path/'dispatch'
    dispatch.build(ref, out, exposure_source='REQUIRES_PK_PREDICTIONS')
    assert called[:2] == [('pk', ['pk']), ('index', ['pd'])]
    pk, index = [read_json(out/(b+'_context.json')) for b in ('pk', 'index')]
    assert [d['dataset_id'] for d in pk['data_files']] == ['PK', 'DOSE']
    assert [d['dataset_id'] for d in index['data_files']] == ['PD', 'DOSE']
    assert {f['dataset_id'] for f in pk['findings']} == {'PK', 'DOSE'}
    assert {f['dataset_id'] for f in index['findings']} == {'PD', 'DOSE'}
    assert [r['id'] for r in pk['rules']] == ['PK']
    assert [r['id'] for r in index['rules']] == ['PD']
    assert not pk['task_requirements']
    assert index['task_requirements'][0]['status'] == 'DEFERRED'
    assert index['candidate_indices'] == ['fAUC/MIC']
    assert index['index_exposure_source'] == 'REQUIRES_PK_PREDICTIONS'
    assert 'pd_endpoint' not in pk['clinical_questions']
    assert any(e.get('path') == '/tasks/1/endpoint'
               for e in index['question_evidence_catalog'].values())
    routing = read_json(out/'routing_plan.json')
    assert [t['id'] for t in routing['unassigned_tasks']] == ['unknown']
    assert [d['dataset_id'] for d in routing['unassigned_datasets']] == ['OTHER']
    assert routing['dependencies'][0]['from'] == 'pk:reviewed_exposure_predictions'
    assert not read_json(out/'clinical_context.json')['tasks']
    for branch in ('pk', 'index', 'clinical'):
        context = read_json(out/(branch+'_context.json'))
        cb.verify_branch_handoff(context)
        manifest = read_json(context['context_manifest_ref']['path'])
        assert manifest['model_calls'] == 0 and not manifest['execution_authorized']
        assert not context['model_release'] and not any(context['data_access'].values())
    assert build_plan(file_ref(out/'pk_context.json'))['species']
    for dataset in datasets:
        assert file_ref(dataset['data']['path']) == dataset['data']


@pytest.mark.parametrize('change', ['context', 'data', 'metadata', 'eda', 'manifest'])
def test_modified_context_or_bound_source_is_rejected(routed_inputs, tmp_path, change):
    ref, datasets = routed_inputs
    out = tmp_path/'dispatch'
    dispatch.build(ref, out)
    context = read_json(out/'pk_context.json')
    if change == 'context':
        context['findings'].append({'reason': 'Invented result'})
    else:
        paths = {'data': datasets[0]['data']['path'],
                 'metadata': datasets[0]['metadata_file']['path'],
                 'eda': tmp_path/'eda_report.json',
                 'manifest': context['context_manifest_ref']['path']}
        write_json(paths[change], {'changed': True})
    with pytest.raises(PipelineError, match='hash mismatch|Changed input'):
        cb.verify_branch_handoff(context)


def test_changed_file_during_projection_cannot_bind_old_context(routed_inputs, tmp_path, monkeypatch):
    from research_pipeline import dispatch_context
    ref, datasets = routed_inputs
    original = dispatch_context.prepare_branch
    def changed(*args, **kwargs):
        context = original(*args, **kwargs)
        write_json(datasets[0]['data']['path'], {'changed': True})
        return context
    monkeypatch.setattr(dispatch_context, 'prepare_branch', changed)
    with pytest.raises(PipelineError, match='Changed input'):
        dispatch.build(ref, tmp_path/'dispatch')
    assert not (tmp_path/'dispatch/pk_context.json').exists()


def test_question_edits_and_matched_exposure_are_preserved(routed_inputs, tmp_path):
    ref, _ = routed_inputs
    dispatch.build(ref, tmp_path/'draft')
    values = read_json(tmp_path/'draft/clinical_questions.json')['values']
    values['decision_question'] = 'Explicit reviewed question'
    out = tmp_path/'edited'
    dispatch.build(ref, out, values, 'AVAILABLE_MATCHED_DATA')
    for branch in ('pk', 'index'):
        context = read_json(out/(branch+'_context.json'))
        assert context['clinical_questions']['decision_question'] == values['decision_question']
        assert 'decision_question' in context['human_edited_question_fields']
    assert read_json(out/'index_context.json')['index_exposure_source'] == 'AVAILABLE_MATCHED_DATA'


def test_restricted_inputs_never_reach_builder(routed_inputs, tmp_path, monkeypatch):
    ref, datasets = routed_inputs
    snapshot, main, assessment, eda, _ = dispatch.inputs(ref)
    datasets[0]['metadata']['permission'] = 'WITHHELD_VALIDATION'
    monkeypatch.setattr(dispatch, 'inputs', lambda *a, **k: (snapshot, main, assessment, eda, datasets))
    monkeypatch.setattr(cb, 'build_branch_handoff',
                        lambda *a, **k: pytest.fail('Restricted data reached assembly'))
    with pytest.raises(PipelineError, match='held-out'):
        dispatch.build(ref, tmp_path/'dispatch')


@pytest.mark.parametrize('compact', [False, True])
def test_scientific_records_are_projected_with_dependencies(routed_inputs, tmp_path, monkeypatch, compact):
    from test_scientific_handoff import science
    ref, _ = routed_inputs
    snapshot, main, assessment, eda, datasets = dispatch.inputs(ref)
    main['scientific_context'] = science()
    if compact:
        from ctxcomp.scientific import compact_projection
        main['scientific_context'] = compact_projection(main['scientific_context'])
    assessment['tasks'][0]['context_evidence'] = [
        {'path': '/scientific_context/items/0', 'quote': 'Human CL'}]
    assessment['tasks'][1]['context_evidence'] = [
        {'path': '/scientific_context/potential_questions/0', 'quote': 'fu constant'}]
    for artifact, value in zip(snapshot['nodes']['adequacy']['artifacts'], [main, assessment]):
        artifact.update(file_ref(write_json(artifact['path'], value)))
    ref = file_ref(write_json(tmp_path/'typed_snapshot.json', snapshot))
    monkeypatch.setattr(dispatch, 'inputs',
                        lambda *a, **k: (snapshot, main, assessment, eda, datasets))
    out = tmp_path/'typed'
    dispatch.build(ref, out)
    pk, index = [read_json(out/(b+'_context.json')) for b in ('pk', 'index')]
    assert {x['id'] for x in pk['scientific_context']['items']} == {'E1', 'M1'}
    assert not pk['scientific_context']['potential_questions']
    assert not index['scientific_context']['items']
    assert index['scientific_context']['potential_questions'][0]['status'] == 'PENDING_CONFIRMATION'


def test_canvas_checks_handoff_before_returning_scoped_context(routed_inputs, tmp_path):
    from types import SimpleNamespace
    from threading import RLock
    from fastapi import HTTPException
    from research_pipeline.workflow_canvas import CanvasStore
    ref, datasets = routed_inputs
    out = tmp_path/'dispatch'
    dispatch.build(ref, out)
    node = {'artifacts': read_json(out/'artifact_manifest.json')['files'],
            'output_signature': 'synthetic-dispatch', 'review': {'decision': 'APPROVE'}}
    store = SimpleNamespace(lock=RLock(), load=lambda _: {'nodes': {'dispatch': node}},
        approved=lambda _: True, dependency_ready=lambda *a: True,
        artifacts_valid=lambda _: True, tributaries=None)
    result = CanvasStore.assigned_context(store, 'synthetic', 'pk')
    assert result['context']['module'] == 'pk' and not result['model_release']
    write_json(datasets[0]['metadata_file']['path'], {'changed': True})
    with pytest.raises(HTTPException) as exc:
        CanvasStore.assigned_context(store, 'synthetic', 'pk')
    assert exc.value.status_code == 409
    assert 'rebuild dispatch' in exc.value.detail


def test_later_branch_cannot_publish_an_earlier_stale_handoff(routed_inputs, tmp_path, monkeypatch):
    ref, datasets = routed_inputs
    original = cb.build_branch_handoff
    def changed(branch, **kwargs):
        bundle = original(branch, **kwargs)
        if branch == 'clinical':
            write_json(datasets[0]['data']['path'], {'changed': True})
        return bundle
    monkeypatch.setattr(cb, 'build_branch_handoff', changed)
    with pytest.raises(PipelineError, match='Changed input'):
        dispatch.build(ref, tmp_path/'dispatch')
    assert not (tmp_path/'dispatch/routing_plan.json').exists()


def replace_source(tmp_path, monkeypatch, source):
    """Update synthetic artifacts as well as their in-memory intake view."""
    snapshot, main, assessment, eda, datasets = source
    values = {'effective_main.json': main, 'assessment.json': assessment, 'eda_report.json': eda}
    for node in snapshot['nodes'].values():
        for artifact in node['artifacts']:
            if artifact['name'] in values:
                artifact.update(file_ref(write_json(artifact['path'], values[artifact['name']])))
    ref = file_ref(write_json(tmp_path/'updated_snapshot.json', snapshot))
    monkeypatch.setattr(dispatch, 'inputs', lambda *a, **k: copy.deepcopy(source))
    return ref


def test_regenerating_draft_keeps_every_manifest_reference_valid(routed_inputs, tmp_path):
    from research_pipeline.adequacy import check_ref
    ref, _ = routed_inputs
    out = tmp_path/'repeat'
    for _ in range(2):
        dispatch.build(ref, out)
        artifacts = read_json(out/'artifact_manifest.json')['files']
        assert 'artifact_manifest.json' not in [a['name'] for a in artifacts]
        assert len({a['name'] for a in artifacts}) == len(artifacts)
        for artifact in artifacts:
            check_ref(artifact)


@pytest.mark.parametrize('active', ['pk', 'index', None])
def test_single_or_empty_branch_does_not_borrow_other_tasks(routed_inputs, tmp_path, monkeypatch, active):
    ref, _ = routed_inputs
    source = dispatch.inputs(ref)
    source[2]['tasks'] = [t for t in source[2]['tasks'] if t.get('destination') == active and active]
    ref = replace_source(tmp_path, monkeypatch, source)
    out = tmp_path/'single'
    dispatch.build(ref, out)
    for branch in ('pk', 'index', 'clinical'):
        context = read_json(out/(branch+'_context.json'))
        cb.verify_branch_handoff(context)
        if branch != active:
            assert not context['tasks'] and not context['data_files']
            assert not context['expected_outputs']
            assert context['missing_materials'][0]['code'] == 'NO_REVIEWED_BRANCH_TASK'
    plan = read_json(out/'routing_plan.json')
    expected = [] if active is None else [active+':task_input_preparation']
    assert plan['parallel_groups'] == [expected]


def test_published_rules_flow_through_builder_and_remain_bound(routed_inputs, bundle, tmp_path, monkeypatch):
    from test_project_rule_agent import run
    published = run(bundle)  # Deterministic fixture generators; no live models.
    ref, _ = routed_inputs
    snapshot, _, assessment, eda, datasets = dispatch.inputs(ref)
    main = read_json(published['main_ref']['path'])
    provenance = {'project_rules_ref': published['project_rules_ref']}
    snapshot['nodes']['adequacy']['artifacts'].append({
        'name': 'context_provenance.json',
        **file_ref(write_json(tmp_path/'context_provenance.json', provenance))})
    ref = replace_source(tmp_path, monkeypatch, (snapshot, main, assessment, eda, datasets))
    out = tmp_path/'published_dispatch'
    dispatch.build(ref, out)
    pk = read_json(out/'pk_context.json')
    assert pk['rules'] and all(r['project_rules_ref'] == published['project_rules_ref'] for r in pk['rules'])
    assert pk['rule_projection']['method'] == 'EXPLICIT_REVIEWED_SCOPE_NO_REWRITE'
    cb.verify_branch_handoff(pk)
    write_json(published['project_rules_ref']['path'], {'changed': True})
    with pytest.raises(PipelineError, match='Changed input'):
        cb.verify_branch_handoff(pk)


@pytest.mark.parametrize('mode', ['valid', 'stale', 'unknown', 'unconfirmed'])
def test_execution_requires_exact_confirmation(routed_inputs, tmp_path, mode):
    ref, _ = routed_inputs
    dispatch.build(ref, tmp_path/'confirmation_draft')
    values = read_json(tmp_path/'confirmation_draft/clinical_questions.json')['values']
    snapshot = dispatch.inputs(ref)[0]
    spec = {'confirmed': True, 'reviewer': 'Synthetic test reviewer',
            'values': values, 'index_exposure_source': 'REQUIRES_PK_PREDICTIONS',
            'upstream_signatures': {k:n['output_signature'] for k,n in snapshot['nodes'].items()}}
    if mode == 'stale':
        spec['upstream_signatures']['eda'] = 'other-version'
    elif mode == 'unknown':
        spec['index_exposure_source'] = 'UNKNOWN'
    elif mode == 'unconfirmed':
        spec['confirmed'] = False
    spec_ref = file_ref(write_json(tmp_path/'confirmed.json', spec))
    out = tmp_path/'execute'
    if mode == 'valid':
        result = dispatch.execute(ref, spec_ref, out)
        assert result['status'] == 'WAITING_FOR_HUMAN_REVIEW'
        assert not result['fit_ready']
        assert read_json(out/'pk_context.json')['status'] == 'PENDING_DISPATCH_REVIEW'
    else:
        with pytest.raises(PipelineError) as exc:
            dispatch.execute(ref, spec_ref, out)
        expected = {'stale': 'DISPATCH_CONFIRMATION_STALE', 'unknown': 'DISPATCH_DEPENDENCY_UNCONFIRMED',
                    'unconfirmed': 'DISPATCH_QUESTIONS_UNCONFIRMED'}
        assert exc.value.code == expected[mode]
        assert not out.exists()


def test_advisory_evidence_is_branch_scoped_and_version_bound(routed_inputs, tmp_path, monkeypatch):
    ref, _ = routed_inputs
    dispatch.build(ref, tmp_path/'no_advice')
    defaults = read_json(tmp_path/'no_advice/clinical_questions.json')['values']
    advice = {'authority': 'ADVISORY_ONLY', 'scope': 'IN_SCOPE',
              'suggestions': [{'card_id': 'PK-METHOD', 'relevant_step': 'pk'},
                             {'card_id': 'PD-METHOD', 'relevant_step': 'index'}],
              'cards': [{'id': 'PK-METHOD', 'source_ids': ['S-PK']},
                        {'id': 'PD-METHOD', 'source_ids': ['S-PD']}],
              'sources': [{'id': 'S-PK'}, {'id': 'S-PD'}]}
    advice_ref = file_ref(write_json(tmp_path/'advice.json', advice))
    monkeypatch.setattr(dispatch, 'reference_advice',
                        lambda *a: {**copy.deepcopy(advice), 'provenance': advice_ref})
    out = tmp_path/'with_advice'
    dispatch.build(ref, out)
    assert read_json(out/'clinical_questions.json')['values'] == defaults
    pk, index = [read_json(out/(b+'_context.json')) for b in ('pk', 'index')]
    assert [s['id'] for s in pk['external_reference_advice']['sources']] == ['S-PK']
    assert [s['id'] for s in index['external_reference_advice']['sources']] == ['S-PD']
    assert not pk['external_reference_advice']['rule_activation']
    cb.verify_branch_handoff(pk)
    write_json(advice_ref['path'], {'changed': True})
    with pytest.raises(PipelineError, match='Changed input'):
        cb.verify_branch_handoff(pk)


@pytest.mark.parametrize('branch,task_ids', [('other', ['pk']), ('pk', ['pd']), ('pk', ['pk', 'pk'])])
def test_builder_rejects_unknown_or_misallocated_tasks(routed_inputs, tmp_path, branch, task_ids):
    ref, _ = routed_inputs
    _, _, assessment, _, _ = dispatch.inputs(ref)
    source = {'assessment': assessment, 'task_branches': {'pk': 'pk', 'pd': 'index'}}
    tasks = {t['id']: t for t in assessment['tasks']}
    assignment = {'tasks': [tasks[i] for i in task_ids], 'datasets': []}
    with pytest.raises(PipelineError, match='Unsupported handoff|routing allocation'):
        cb.build_branch_handoff(branch, source=source, assignment=assignment,
                                output=tmp_path/'invalid', input_bindings={})
    assert not (tmp_path/'invalid').exists()
