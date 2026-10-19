"""Stage orchestration and preservation checks; no scientific/provider execution."""
import copy

import pytest

from research_pipeline import data_staged_workflow as workflow
from research_pipeline.adequacy import file_ref
from research_pipeline.common import PipelineError, read_json, write_json


@pytest.fixture
def checkpoint(tmp_path):
    missing = {'items': [{'id': 'MI01', 'status': 'SEARCH_INCOMPLETE',
                         'field': 'Regimen definition', 'needed_at': 'BEFORE_MODELING'}]}
    main = write_json(tmp_path / 'main.json', {'missing_information': missing})
    source = tmp_path / 'source'
    write_json(source / 'manifest.json', {'bindings': {'main': file_ref(main)}})
    write_json(source / 'source_view.json', {
        'legacy_findings': [{'code': 'HISTORICAL', 'reason': 'Original unresolved finding'}]})
    return source, main, missing


def test_build_planning_stops_and_preserves_upstream_records(checkpoint, tmp_path, monkeypatch):
    from research_pipeline import data_requirement_plan_v4 as planning
    source, main, missing = checkpoint
    original = main.read_bytes()
    calls = []
    monkeypatch.setattr(planning, 'prepare', lambda *_: calls.append('prepare') or {})
    monkeypatch.setattr(planning, 'run', lambda *_a, **_k: pytest.fail('No provider in build-only'))
    result = workflow.run_stage('planning', tmp_path / 'out', source_run=source, build_only=True)
    assert calls == ['prepare']
    assert result['status'] == 'BUILT_NO_MODEL_CALL'
    assert result['next_stage_started'] is False
    assert main.read_bytes() == original
    carried = read_json(result['inherited_unresolved_ref']['path'])
    assert carried['missing_information'] == missing
    assert carried['extraction_findings'][0]['reason'] == 'Original unresolved finding'
    assert all(result[k] is False for k in ('scientific_approval', 'can_enter_qc', 'fit_ready'))


@pytest.mark.parametrize('stage', ['coverage', 'disposition', 'necessity'])
def test_v4_routes_to_compatible_stage_without_legacy_execution(stage, checkpoint, tmp_path, monkeypatch):
    import research_pipeline
    from types import SimpleNamespace
    from research_pipeline import data_coverage_review as review
    from research_pipeline import data_gap_disposition as disposition
    source, main, missing = checkpoint
    plan = write_json(tmp_path / 'plan4.json', {'version': 'REQUIREMENT_PLAN_4.0', 'bindings': {
        'main': file_ref(main), 'source_view': file_ref(source / 'source_view.json')}})
    coverage = write_json(tmp_path / 'coverage.json', {})
    monkeypatch.setattr(review, 'run', lambda *_a, **_k: pytest.fail('Legacy coverage must not start'))
    monkeypatch.setattr(disposition, 'resolve', lambda *_a, **_k: pytest.fail('Legacy disposition must not start'))
    calls = []
    def run(p, predecessor, out, **kwargs):
        assert p == plan
        assert predecessor == (source if stage == 'coverage' else coverage)
        calls.append(stage)
        result = {'scientific_approval': False, 'can_enter_qc': False, 'fit_ready': False}
        write_json(out / ('coverage.json' if stage == 'coverage' else 'necessity.json'), result)
        return result
    def prepare(p, predecessor, out):
        assert p == plan and predecessor == coverage
        return {}
    def continued(out, **kwargs):
        assert kwargs['max_new_calls'] == 1
        return run(plan, coverage, out, **kwargs)
    module = 'data_coverage_v5' if stage == 'coverage' else 'data_necessity_v4'
    monkeypatch.setattr(research_pipeline, module, SimpleNamespace(
        run=run, prepare=prepare, run_prepared=continued, verify_result=read_json), raising=False)
    result = workflow.run_stage(stage, tmp_path / 'new', source_run=source, plan=plan,
                                coverage=coverage if stage != 'coverage' else None)
    assert calls == [stage]
    assert result['next_stage_started'] is False
    assert read_json(result['inherited_unresolved_ref']['path'])['missing_information'] == missing


def test_coverage_requires_verified_plan_before_execution(checkpoint, tmp_path, monkeypatch):
    from research_pipeline import data_requirement_planning as planning
    from research_pipeline import data_coverage_review as review
    source, _, _ = checkpoint
    plan = write_json(tmp_path / 'plan.json', {'not': 'a published plan'})
    def reject(_):
        raise PipelineError('BAD_PLAN', 'Unverified planning artifact')
    monkeypatch.setattr(planning, 'verify_plan', reject)
    monkeypatch.setattr(review, 'run', lambda *_a, **_k: pytest.fail('Provider must not start'))
    with pytest.raises(PipelineError, match='Unverified'):
        workflow.run_stage('coverage', tmp_path / 'out', source_run=source, plan=plan)


def test_disposition_replays_inputs_and_uses_only_original_evidence(tmp_path, checkpoint, monkeypatch):
    from research_pipeline import data_requirement_planning as planning
    from research_pipeline import data_coverage_review as review
    from research_pipeline import data_gap_disposition as disposition
    source, main, missing = checkpoint
    plan_value = {'bindings': {'main': file_ref(main), 'source_view': file_ref(source / 'source_view.json')}}
    plan = write_json(tmp_path / 'plan.json', plan_value)
    coverage = write_json(tmp_path / 'coverage.json', {'matches': []})
    order = []
    monkeypatch.setattr(planning, 'verify_plan', lambda _: order.append('plan') or copy.deepcopy(plan_value))
    monkeypatch.setattr(review, 'verify_result', lambda _: order.append('coverage') or {'matches': []})
    monkeypatch.setattr(review, 'result_sources', lambda _: {'original:1': 'Original condition'})
    def resolve(p, c, applicability_decisions, evidence_sources):
        order.append('resolve')
        assert evidence_sources == {'original:1': 'Original condition'}
        assert applicability_decisions == ()
        return {'scientific_approval': False, 'can_enter_qc': False, 'fit_ready': False}
    monkeypatch.setattr(disposition, 'resolve', resolve)
    result = workflow.run_stage('disposition', tmp_path / 'out', plan=plan, coverage=coverage)
    assert order == ['plan', 'coverage', 'resolve']
    assert result['output']['path'].endswith('disposition.json')
    assert read_json(result['inherited_unresolved_ref']['path'])['missing_information'] == missing


@pytest.mark.parametrize('options', [
    {'stage': 'planning'}, {'stage': 'coverage', 'source_run': 'x'},
    {'stage': 'disposition', 'plan': 'x'}, {'stage': 'unknown'},
    {'stage': 'coverage', 'resume': True, 'pause': True},
])
def test_missing_predecessor_or_invalid_stage_rejected(tmp_path, options):
    with pytest.raises(PipelineError):
        workflow.run_stage(out=tmp_path / 'out', **options)


def test_existing_attempt_never_overwritten(checkpoint, tmp_path):
    out = tmp_path / 'out'
    saved = write_json(out / 'failed_response.json', {'preserve': True})
    with pytest.raises(PipelineError, match='new empty'):
        workflow.run_stage('planning', out, source_run=checkpoint[0])
    assert read_json(saved) == {'preserve': True}


def test_output_cannot_contain_or_overlap_sources(checkpoint):
    with pytest.raises(PipelineError, match='separate'):
        workflow.run_stage('planning', checkpoint[0] / 'new', source_run=checkpoint[0])


def test_main_cli_reaches_new_stages(tmp_path, monkeypatch, capsys):
    from research_pipeline import cli
    calls = []
    monkeypatch.setattr(workflow, 'execute_args', lambda a: calls.append(a.stage) or {'status': 'TEST_ONLY'})
    assert cli.main(['data-stages', 'planning', '--source-run', 'source', '--out', str(tmp_path / 'out'),
                     '--build-only']) == 0
    assert calls == ['planning']
    assert 'TEST_ONLY' in capsys.readouterr().out


def test_partial_coverage_is_not_reported_complete_and_import_is_forwarded(checkpoint, tmp_path, monkeypatch):
    from research_pipeline import data_coverage_v5 as review
    source, main, _ = checkpoint
    plan = write_json(tmp_path / 'plan4.json', {'version': 'REQUIREMENT_PLAN_4.0'})
    imported = tmp_path / 'old'
    imported.mkdir()
    calls = []
    def run(p, s, out, **kw):
        calls.append(kw)
        return {'status': 'PARTIAL_COVERAGE_CHECKPOINT', 'complete': False,
                'stop_reason': 'CALL_LIMIT'}
    monkeypatch.setattr(review, 'run', run)
    manifest = workflow.run_stage('coverage', tmp_path / 'out', source_run=source,
                                 plan=plan, import_from=imported)
    assert calls[0]['max_new_calls'] == 1 and calls[0]['import_from'] == imported
    assert manifest['status'] == 'PARTIAL_COVERAGE_CHECKPOINT'
    assert manifest['stop_reason'] == 'CALL_LIMIT' and 'output' not in manifest


def test_new_necessity_v6_can_prepare_without_provider(checkpoint, tmp_path, monkeypatch):
    from research_pipeline import data_necessity_v6 as necessity
    source, main, _ = checkpoint
    plan = write_json(tmp_path / 'plan4.json', {'version': 'REQUIREMENT_PLAN_4.0'})
    coverage = write_json(tmp_path / 'coverage.json', {'version': 'COVERAGE_FACTS_5.0'})
    calls = []
    monkeypatch.setattr(necessity, 'prepare', lambda *a, **kw: calls.append('prepare') or {})
    monkeypatch.setattr(necessity, 'run_prepared', lambda *a, **kw: pytest.fail('Provider forbidden'))
    manifest = workflow.run_stage('necessity', tmp_path / 'out', source_run=source,
                                  plan=plan, coverage=coverage, build_only=True)
    assert calls == ['prepare'] and manifest['status'] == 'BUILT_NO_MODEL_CALL'


@pytest.mark.parametrize('version,module', [('DATA_NECESSITY_4.0', 'data_necessity_v4'),
    ('DATA_NECESSITY_5.0', 'data_necessity_v5'), ('DATA_NECESSITY_IMPACT_6.0', 'data_necessity_v6')])
def test_saved_necessity_uses_prepared_version_not_new_default(tmp_path, version, module):
    coverage = write_json(tmp_path/'coverage.json', {'version': 'COVERAGE_FACTS_5.0'})
    out = tmp_path/'saved'
    write_json(out/'build.json', {'version': version})
    assert workflow._necessity_module(coverage, out).__name__.endswith(module)
    assert workflow._necessity_module(coverage).__name__.endswith('data_necessity_v6')


def test_unknown_saved_necessity_cannot_fall_through_to_new_engine(tmp_path):
    coverage = write_json(tmp_path/'coverage.json', {'version': 'COVERAGE_FACTS_5.0'})
    write_json(tmp_path/'saved/build.json', {'version': 'UNKNOWN'})
    with pytest.raises(PipelineError, match='Unknown saved'):
        workflow._necessity_module(coverage, tmp_path/'saved')


def test_resume_pause_and_readonly_status_use_saved_stage_only(tmp_path, monkeypatch):
    from research_pipeline import data_coverage_v5 as review
    out = tmp_path / 'out'
    write_json(out / 'build.json', {'version': review.VERSION})
    saved = write_json(out / 'workflow.json', {'stage': 'coverage', 'inputs': {},
                      'status': 'BUILT_NO_MODEL_CALL', 'next_stage_started': False})
    calls = []
    def run(out, **kw):
        assert not (out / 'PAUSE').exists()
        calls.append(kw)
        return {'status': 'PARTIAL_COVERAGE_CHECKPOINT', 'complete': False}
    monkeypatch.setattr(review, 'run_prepared', run)
    monkeypatch.setattr(review, 'rebuild_checkpoint', lambda out, **kw:
        {'status': 'PARTIAL_COVERAGE_CHECKPOINT', 'complete': False} if kw == {'write': False}
        else pytest.fail('Status must be read only'))
    assert workflow.run_stage('coverage', out, pause=True)['status'] == 'PAUSE_REQUESTED'
    assert (out / 'PAUSE').exists()
    before = saved.read_bytes()
    workflow.run_stage('coverage', out, status=True)
    assert saved.read_bytes() == before and not calls
    workflow.run_stage('coverage', out, resume=True)
    assert len(calls) == 1 and calls[0]['max_new_calls'] == 1
    with pytest.raises(PipelineError, match='saved inputs'):
        workflow.run_stage('coverage', out, resume=True, plan='another.json')
    with pytest.raises(PipelineError, match='differs'):
        workflow.run_stage('necessity', out, status=True)


def test_new_cli_controls_are_exclusive_and_bounded():
    import argparse
    parser = argparse.ArgumentParser()
    workflow.add_arguments(parser)
    args = parser.parse_args(['coverage', '--out', 'saved', '--resume'])
    assert args.max_new_calls == 1 and args.resume
    with pytest.raises(SystemExit):
        parser.parse_args(['coverage', '--out', 'saved', '--resume', '--pause'])


def test_completed_resume_does_not_inherit_paused_stop_reason(tmp_path, monkeypatch):
    from types import SimpleNamespace
    out = tmp_path/'stage'
    write_json(out/'workflow.json', {'stage': 'disposition', 'inputs': {},
                                   'status': 'CHECKPOINTED', 'stop_reason': 'PAUSED'})
    write_json(out/'necessity.json', {'complete': True})
    engine = SimpleNamespace(run_prepared=lambda *a, **k: {'complete': True},
                             verify_result=lambda *a, **k: {'complete': True})
    # Saved input is needed only for engine selection in this fixture.
    workflow_path = out/'workflow.json'
    saved = read_json(workflow_path)
    coverage = write_json(tmp_path/'coverage.json', {})
    saved['inputs']['coverage'] = file_ref(coverage)
    write_json(workflow_path, saved)
    monkeypatch.setattr(workflow, '_necessity_module', lambda *a, **k: engine)
    result = workflow.run_stage('necessity', out, resume=True)
    assert result['status'] == 'STAGE_COMPLETE'
    assert 'stop_reason' not in result
    assert read_json(workflow_path) == result


def test_first_failed_call_still_leaves_an_explicit_resume_handle(checkpoint, tmp_path, monkeypatch):
    from research_pipeline import data_coverage_v5 as review
    source, _, missing = checkpoint
    plan = write_json(tmp_path / 'plan4.json', {'version': 'REQUIREMENT_PLAN_4.0'})
    out = tmp_path / 'out'
    def failed(p, s, folder, **kwargs):
        write_json(folder / 'build.json', {'version': review.VERSION})
        write_json(folder / 'raw.json', {'preserve': 'failed response'})
        raise RuntimeError('Injected provider failure')
    monkeypatch.setattr(review, 'run', failed)
    with pytest.raises(RuntimeError, match='Injected'):
        workflow.run_stage('coverage', out, source_run=source, plan=plan)
    saved = read_json(out / 'workflow.json')
    assert saved['status'] == 'FAILED_RETAINED'
    assert saved['inputs']['plan'] == file_ref(plan)
    assert read_json(out / 'raw.json') == {'preserve': 'failed response'}
    assert read_json(saved['inherited_unresolved_ref']['path'])['missing_information'] == missing
