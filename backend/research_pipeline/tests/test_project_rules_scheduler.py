"""Scheduler contracts only; fake agent responses never count as scientific review."""
import sys
import types
from pathlib import Path

import pytest

from research_pipeline.common import read_json, write_json
from research_pipeline.graph_execution import run_controlled
from research_pipeline.workflow_runtime import make_plan, execute_contract, ref


@pytest.fixture
def rules_job(tmp_path, monkeypatch):
    base = write_json(tmp_path / 'compression/main.json', {'objective': 'Study the supplied project.'})
    source = write_json(tmp_path / 'source.json', {'text': 'Human observations are validation only.'})
    prepared = {'base_main_ref': ref(base), 'source_refs': [ref(source)]}
    input_path = write_json(tmp_path / 'job/input.json', prepared)
    spec = {'id': 'rules_fixture', 'created_at': '2026-10-06T00:00:00Z', 'mode': 'project_rules',
            'stop_after': 'project_rules', 'project_rules_input': ref(input_path),
            'job_dir': str(tmp_path / 'job'), 'out': str(tmp_path / 'run'), 'model': 'fixture-model'}
    calls = []
    core = types.ModuleType('research_pipeline.project_rule_agent')
    core.validate_input = lambda reference: read_json(reference['path'])

    def extract(input_ref, output_dir, model=None):
        calls.append(('extract', input_ref, model))
        return write_json(Path(output_dir) / 'candidate.json', {'candidate': 'fixture'})

    def review(input_ref, candidate_ref, output_dir, model=None):
        assert read_json(candidate_ref['path']) == {'candidate': 'fixture'}
        calls.append(('review', input_ref, model))
        return write_json(Path(output_dir) / 'review.json', {'decision': 'PASS', 'fixture_only': True})

    def publish(input_ref, candidate_ref, review_ref, output_dir):
        assert read_json(review_ref['path'])['decision'] == 'PASS'
        calls.append(('publish', input_ref, None))
        folder = Path(output_dir)
        for name in ('main.json', 'project_rules.json', 'rule_audit.json'):
            write_json(folder / name, {'fixture_only': True})
        return write_json(folder / 'report.json', {'status': 'PROJECT_RULES_PUBLISHED'})

    core.extract, core.review, core.publish = extract, review, publish
    monkeypatch.setitem(sys.modules, 'research_pipeline.project_rule_agent', core)
    return spec, calls, core


def test_opt_in_plan_executes_three_ordered_blocks_and_receipts(rules_job):
    spec, calls, _ = rules_job
    plan = make_plan(spec)
    assert plan['targets'] == {'project_rules': 'project_rules_publish'}
    assert list(plan['steps']) == ['project_rules_extract', 'project_rules_review', 'project_rules_publish']
    assert plan['steps']['project_rules_review']['depends'] == ['project_rules_extract']
    assert plan['steps']['project_rules_publish']['depends'] == ['project_rules_review']
    assert len(plan['source_refs']) == 3
    assert any(Path(r['path']).name == 'extraction_policy.1.2.json' for r in plan['code_refs'])
    for stage in plan['steps'].values():
        execute_contract(stage['contract'])
    assert [c[0] for c in calls] == ['extract', 'review', 'publish']
    assert [c[2] for c in calls[:2]] == ['fixture-model', 'fixture-model']
    outputs = read_json(Path(spec['job_dir']) / 'receipts/project_rules_publish.json')['outputs']
    assert {Path(o['path']).name for o in outputs} == {'report.json', 'main.json', 'project_rules.json', 'rule_audit.json'}


def test_changed_source_invalidates_saved_plan(rules_job):
    spec, _, _ = rules_job
    plan = make_plan(spec)
    Path(plan['source_refs'][-1]['path']).write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='Changed or missing'):
        make_plan(spec)


@pytest.mark.parametrize('report_status, disposition, final_status', [
    ('PROJECT_RULES_PUBLISHED', 'PROJECT_RULES_READY', 'PROJECT_RULES_PUBLISHED'),
    ('RULES_REVISION_REQUIRED', 'CONTEXT_REVISION_REQUIRED', 'REVISION_REQUIRED'),
])
def test_graph_uses_publication_diagnostics_without_extra_human_gate(rules_job, report_status, disposition, final_status):
    spec, _, _ = rules_job
    request = write_json(Path(spec['job_dir']) / 'request.json', spec)
    write_json(Path(spec['out']) / 'project_rules/published/report.json', {'status': report_status})
    status = run_controlled(request, prefect_runner=lambda *a, **k: {'status': report_status})
    assert status['status'] == final_status
    assert status['control']['disposition'] == disposition
    assert status['control']['diagnostics']['scientific_accepted'] is False


def test_graph_rejects_missing_publication_report(rules_job):
    spec, _, _ = rules_job
    request = write_json(Path(spec['job_dir']) / 'request.json', spec)
    status = run_controlled(request, prefect_runner=lambda *a, **k: {'status': 'PROJECT_RULES_PUBLISHED'})
    assert status['status'] == 'STOPPED_ON_ERROR'
    assert 'missing' in status['error']


def test_revision_with_published_handoff_is_rejected(rules_job):
    spec, _, core = rules_job

    def bad_publish(input_ref, candidate_ref, review_ref, output_dir):
        write_json(Path(output_dir) / 'main.json', {'must_not_release': True})
        write_json(Path(output_dir) / 'report.json', {'status': 'RULES_REVISION_REQUIRED'})

    core.publish = bad_publish
    plan = make_plan(spec)
    execute_contract(plan['steps']['project_rules_extract']['contract'])
    execute_contract(plan['steps']['project_rules_review']['contract'])
    with pytest.raises(ValueError, match='cannot expose a published handoff'):
        execute_contract(plan['steps']['project_rules_publish']['contract'])
    assert not (Path(spec['job_dir']) / 'receipts/project_rules_publish.json').exists()
    assert read_json(Path(spec['out']) / 'project_rules/stopped.json')['stage'] == 'project_rules_publish'


@pytest.mark.parametrize('selection', ['stop_after', 'target'])
def test_fresh_target_builds_prepare_after_compress_and_resolves_late_input(rules_job, monkeypatch, selection):
    spec, calls, core = rules_job
    from research_pipeline import workflow_runtime
    original_execute = workflow_runtime.execute_builtin
    root = Path(spec['out'])
    source = write_json(Path(spec['job_dir']) / 'proposal.json', {'proposal': 'fixture'})
    fresh = {**spec, 'mode': 'fresh', 'uploads': [{'path': str(source), 'name': source.name}],
             'stop_after': 'project_rules' if selection == 'stop_after' else 'context'}
    fresh.pop('project_rules_input')

    def fake_compression(c):
        if c['kind'] == 'intake':
            write_json(c['outputs'][0], {'fixture_only': True})
            Path(c['outputs'][1]).mkdir(parents=True)
        elif c['kind'] == 'compress':
            write_json(c['outputs'][0], {'objective': 'fixture'})
            write_json(root / 'context_work/handoff/main.json', {'objective': 'fixture'})
        else:
            original_execute(c)

    def prepare(compression_run, output, project_materials=None):
        assert Path(compression_run) == root / 'context_work'
        assert (Path(compression_run) / 'handoff/main.json').is_file()
        calls.append(('prepare', str(compression_run), None))
        write_json(output, {'base_main_ref': ref(root / 'context_work/handoff/main.json'),
                            'source_refs': [ref(source)]})
        return ref(output)

    core.prepare = prepare
    monkeypatch.setattr(workflow_runtime, 'execute_builtin', fake_compression)
    plan = make_plan(fresh, target='project_rules' if selection == 'target' else None)
    assert plan['targets']['context'] == 'project_rules_publish'
    assert plan['targets']['project_rules'] == 'project_rules_publish'
    assert plan['steps']['project_rules_prepare']['depends'] == ['compress']
    assert plan['steps']['project_rules_extract']['depends'] == ['project_rules_prepare']
    assert not (root / 'project_rules/input.json').exists()
    for stage in plan['steps'].values():
        execute_contract(stage['contract'])
    assert [call[0] for call in calls] == ['prepare', 'extract', 'review', 'publish']
    assert calls[1][1] == ref(root / 'project_rules/input.json')


def test_existing_fresh_plan_is_not_expanded_by_new_target(rules_job):
    spec, _, _ = rules_job
    source = write_json(Path(spec['job_dir']) / 'proposal.json', {'proposal': 'fixture'})
    fresh = {**spec, 'mode': 'fresh', 'stop_after': 'context',
             'uploads': [{'path': str(source), 'name': source.name}]}
    plan = make_plan(fresh)
    assert plan['targets']['context'] == 'project_rules_publish'
    assert plan['targets']['compression'] == 'compress'
    assert make_plan(fresh, target='project_rules') == plan


def test_intake_first_plan_already_includes_project_rule_chain(rules_job):
    spec,_,_=rules_job
    source=write_json(Path(spec['job_dir'])/'proposal.json',{'proposal':'fixture'})
    materials=[{'file_id':'F0002','role':'PROTOCOL','designation_reason':'Explicit user designation'}]
    fresh={**spec,'mode':'fresh','stop_after':'intake','uploads':[{'path':str(source),'name':source.name}], 'project_materials':materials}
    plan=make_plan(fresh)
    assert plan['targets']['context']=='project_rules_publish'
    contract=read_json(plan['steps']['project_rules_prepare']['contract'])
    assert contract['options']['project_materials']==materials
    assert make_plan(fresh,target='context')==plan


@pytest.mark.parametrize('published', [True, False])
def test_context_target_waits_for_rule_publication_diagnostics(rules_job,published):
    spec,_,_=rules_job
    source=write_json(Path(spec['job_dir'])/'proposal.json',{'proposal':'fixture'})
    fresh={**spec,'mode':'fresh','stop_after':'context','uploads':[{'path':str(source),'name':source.name}]}
    make_plan(fresh)
    request=write_json(Path(spec['job_dir'])/'request.json',fresh)
    report_status='PROJECT_RULES_PUBLISHED' if published else 'RULES_REVISION_REQUIRED'
    write_json(Path(spec['out'])/'project_rules/published/report.json',{'status':report_status})
    state=run_controlled(request,prefect_runner=lambda *a,**k:{'status':'WAITING_FOR_HUMAN_REVIEW' if published else 'REVISION_REQUIRED'})
    assert state['control']['disposition']==('HUMAN_SCIENTIFIC_REVIEW' if published else 'CONTEXT_REVISION_REQUIRED')


def test_adequacy_plan_binds_opt_in_published_pack_and_its_sources(rules_job):
    spec, _, core = rules_job
    original = core.validate_input(spec['project_rules_input'])
    main_path = write_json(Path(spec['job_dir']) / 'base_main.json', {'data': {'files': []}})
    pack = {key: ref(write_json(Path(spec['job_dir']) / (key + '.json'), {'fixture_only': True}))
            for key in ['main_ref', 'audit_ref', 'candidate_ref', 'review_ref']}
    pack.update(base_main_ref=ref(main_path), input_ref=spec['project_rules_input'])
    pack_ref = ref(write_json(Path(spec['job_dir']) / 'pack.json', pack))
    core.verify_published = lambda reference: pack
    approval = write_json(Path(spec['job_dir']) / 'approval.json', {
        'project_rules_ref': pack_ref, 'context': {'artifacts': [{'name': 'main.json', **ref(main_path)}]}})
    reviewed = {**spec, 'mode': 'reviewed_context', 'approved_context': ref(approval)}
    plan = make_plan(reviewed)
    paths = {r['path'] for r in plan['source_refs']}
    assert {pack_ref['path'], *(item['path'] for item in pack.values()),
            *(item['path'] for item in original['source_refs'])} <= paths
    Path(pack['audit_ref']['path']).write_text('{}', encoding='utf-8')
    with pytest.raises(ValueError, match='Changed or missing'):
        make_plan(reviewed)
