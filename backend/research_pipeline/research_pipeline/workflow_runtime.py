"""Minimal block contracts and hashed receipts for the file execution layer."""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from .common import BACKEND, PROJECT, RULES, read_json, write_json, sha256, utcnow
from .engine import rscript_path
from ctxcomp.governance import load_governance


def ref(path):
    return {'path': str(Path(path).resolve()), 'sha256': sha256(path)}


def verify_refs(items):
    for item in items:
        if not Path(item['path']).is_file() or sha256(item['path']) != item['sha256']:
            raise ValueError('Changed or missing file; create a new run: ' + item['path'])


def cpu_budget():
    import psutil
    physical = psutil.cpu_count(logical=False) or 1
    available = max(1, physical - 1)
    workers = min(4, available)
    return {'physical_cores': physical, 'total_slots': available, 'rat_workers': workers,
            'blas_threads_per_process': 1}


def context_requires_project_rules(spec):
    plan_path = Path(spec['job_dir']) / 'plan.json'
    if plan_path.is_file():
        return read_json(plan_path).get('targets', {}).get('context') == 'project_rules_publish'
    main = Path(spec['out']) / 'B1/main.json'
    return main.is_file() and read_json(main).get('rule_publication') == 'PROJECT_RULES_AGENT'


def make_plan(spec, target=None):
    folder, run = Path(spec['job_dir']), Path(spec['out'])
    path = folder / 'plan.json'
    if path.exists():
        plan = read_json(path)
        verify_refs(plan['source_refs'] + plan['code_refs'] + plan['contract_refs'])
        for receipt in (folder / 'receipts').glob('*.json'):
            verify_refs(read_json(receipt)['outputs'])
        return plan
    steps = {}; scripts = BACKEND / 'research_pipeline/scripts'; budget = cpu_budget()
    governance = load_governance()
    def py(script, *args):
        return [sys.executable, '-I', '-X', 'utf8', str(scripts / script), *map(str, args)]
    def add(name, deps, inputs, outputs, commands=None, kind='commands', slots=1, clean=None, **options):
        if kind.startswith('data_v2_') and spec.get('demo_lightweight_data'):
            options['demo_lightweight_data'] = True
        contract = {'schema_version': '1.0', 'stage': name, 'kind': kind, 'governance': governance,
            'inputs': [str(p) for p in inputs], 'outputs': [str(p) for p in outputs],
            'commands': commands or [], 'options': options, 'cpu_slots': slots,
            'dependency_receipts': [str(folder / 'receipts' / (d + '.json')) for d in deps],
            'receipt': str(folder / 'receipts' / (name + '.json')), 'run_root': str(run),
            'attempts_dir': str(folder / 'attempts' / name), 'cancel_file': str(folder / 'cancel.flag'),
            'partial_paths': [str(p) for p in (clean if clean is not None else outputs)]}
        if kind == 'intake':
            from ctxcomp.rules import intake_agent_contract
            contract['agent_contract'] = intake_agent_contract()
        request = write_json(folder / 'contracts' / (name + '.json'), contract)
        steps[name] = {'contract': str(request), 'depends': deps, 'slots': slots,
                       'external_inputs': [str(p) for p in inputs if Path(p).is_file() and not Path(p).is_relative_to(run)],
                       'input_files': contract['inputs'], 'output_files': contract['outputs']}
    def reference_steps(main_path, dependency=None):
        from .pk_reference_pilot import snapshot_library
        library = snapshot_library(folder/'pk_reference_library.json', spec.get('reference_library'))
        source_refs.append(library)
        add('pk_reference_prepare', [dependency] if dependency else [], [main_path, library['path']],
            [run/'pk_references/input.json'], kind='pk_reference_prepare', library=library)
        add('pk_reference_review', ['pk_reference_prepare'], [run/'pk_references/input.json'],
            [run/'pk_references/review'], kind='pk_reference_review', model=spec.get('model'))
        return run/'pk_references/review/reference_context.json'
    def project_rule_steps(input_path, dependency=None, input_ref=None, source_paths=None):
        root = run / 'project_rules'
        options = {'input_ref': input_ref} if input_ref else {'input_path': str(input_path)}
        if spec.get('demo_key_rules'):
            add('project_rules_publish', [dependency] if dependency else [], source_paths or [input_path],
                [root/'published'], kind='demo_key_rules', model=spec.get('model'), **options)
            return
        add('project_rules_extract', [dependency] if dependency else [], source_paths or [input_path],
            [root / 'extraction'], kind='project_rules_extract', model=spec.get('model'), **options)
        add('project_rules_review', ['project_rules_extract'],
            [input_path, root / 'extraction/candidate.json'], [root / 'review'],
            kind='project_rules_review', model=spec.get('model'), **options)
        add('project_rules_publish', ['project_rules_review'],
            [input_path, root / 'extraction/candidate.json', root / 'review/review.json'],
            [root / 'published'], kind='project_rules_publish', **options)
    if spec.get('mode') == 'project_rules':
        from .project_rule_agent import validate_input
        rules_input = spec['project_rules_input']; prepared = validate_input(rules_input)
        source_refs = [rules_input, prepared['base_main_ref'], *prepared['source_refs']]
        verify_refs(source_refs)
        project_rule_steps(rules_input['path'], input_ref=rules_input, source_paths=[r['path'] for r in source_refs])
        targets = {'project_rules': 'project_rules_publish'}
    elif spec.get('mode') == 'pk_reference_pilot':
        verify_refs([spec['main_ref']]); source_refs=[spec['main_ref']]
        advice=reference_steps(spec['main_ref']['path'])
        targets={'pk_reference_pilot':'pk_reference_review'}
        if spec.get('revise_main'):
            add('main_reference_revision',['pk_reference_review'],[spec['main_ref']['path'],advice],
                [run/'pk_references/revision'],kind='main_reference_revision',model=spec.get('model'))
            add('main_reference_revision_review',['main_reference_revision'],[run/'pk_references/revision/revision.json'],
                [run/'pk_references/revised'],kind='main_reference_revision_review',model=spec.get('model'))
            targets['pk_reference_pilot']='main_reference_revision_review'
    elif spec.get('mode') == 'animal_pk_individual':
        from .animal_pk_individual import validate_request
        master_ref=spec['individual_request'];master=validate_request(master_ref)
        source_refs=[master_ref,master['approval_ref'],*master['source_refs']]
        names=[];folders=[]
        for request_ref in master['candidates']:
            candidate=validate_request(request_ref);source_refs.append(request_ref)
            candidate={**candidate,'qualification':{**candidate['qualification'],'pause_file':str(folder/'pause.flag')}}
            request_ref=ref(write_json(folder/'individual_requests'/(candidate['id']+'.json'),candidate))
            source_refs.append(request_ref)
            name=candidate['id'];names.append(name);destination=run/'animal_pk/candidates'/name;folders.append(str(destination))
            add(name,[],[r['path'] for r in [request_ref,*candidate['source_refs']]], [destination],
                kind='animal_pk_individual_candidate',request_ref=request_ref,slots=max(1,(budget['total_slots']+2)//3))
        add('animal_pk_individual',names,[Path(p)/'report.json' for p in folders],
            [run/'animal_pk/report.json',run/'animal_pk/comparison.json',run/'animal_pk/comparison.csv',run/'animal_pk/README.md',run/'animal_pk/artifact_manifest.json'],
            kind='animal_pk_individual_report',master_ref=master_ref,folders=folders)
        targets={'animal_pk_individual':'animal_pk_individual'}
    elif spec.get('mode') == 'animal_pk_summary':
        from .animal_pk_summary import validate_summary_request
        master_ref=spec['summary_request']; master=validate_summary_request(master_ref)
        source_refs=[master_ref,master['approval_ref'],master['preflight_ref'],*master['source_refs']]
        names=[];folders=[]
        for group_ref in master['groups']:
            group=validate_summary_request(group_ref);source_refs.append(group_ref)
            for nc in [1,2]:
                name=group['analysis_id']+'_'+str(nc)+'C';names.append(name)
                request_ref=ref(write_json(folder/'summary_requests'/(name+'.json'),{**group,'compartments':nc,'pause_file':str(folder/'pause.flag')}))
                source_refs.append(request_ref);destination=run/'animal_pk/candidates'/name;folders.append(str(destination))
                add(name,[],[r['path'] for r in [request_ref,*group['source_refs']]], [destination],
                    kind='animal_pk_summary_candidate',request_ref=request_ref,slots=max(1,(budget['total_slots']+2)//3))
        add('animal_pk_summary',names,[Path(p)/'report.json' for p in folders],
            [run/'animal_pk/report.json',run/'animal_pk/comparison.json',run/'animal_pk/comparison.csv',run/'animal_pk/README.md',run/'animal_pk/artifact_manifest.json'],
            kind='animal_pk_summary_report',master_ref=master_ref,folders=folders)
        targets={'animal_pk_summary':'animal_pk_summary'}
    elif spec.get('mode') == 'animal_pk_execution':
        from .animal_pk_control import validate_plan
        from .adequacy import check_ref
        check_ref(spec['pk_plan']); architecture = read_json(spec['pk_plan']['path']); validate_plan(architecture)
        requests = spec.get('agent_requests') or [spec['agent_request']]
        source_refs = [spec['pk_plan'], *architecture['source_refs'], *requests]
        agent_steps = []; folders = []
        for request_ref in requests:
            check_ref(request_ref); request = read_json(request_ref['path'])
            if request['plan_signature'] != architecture['plan_signature']:
                raise ValueError('Agent request belongs to a different PK plan')
            source_refs.extend(request['source_refs'])
            name = 'pk_execute_' + request['agent']['id']; agent_steps.append(name)
            destination = run/'animal_pk' if len(requests)==1 else run/'animal_pk/agents'/request['agent']['id']
            folders.append(str(destination))
            slots = 1
            if request.get('qualification_ref'):
                envelope=read_json(request['qualification_ref']['path'])
                for q in envelope['configurations']:
                    source_refs.extend(q['input_refs']+[q['approval_ref']])
                    slots=max(slots,q['fit_config'].get('cores',1))
            if slots>budget['total_slots']: raise ValueError('Requested PK worker cores exceed the local CPU budget; reduce cores in the fitting contract.')
            add(name, [], [r['path'] for r in [request_ref,*request['source_refs']]], [destination],
                kind='animal_pk_execution', request_ref=request_ref, slots=slots)
        if len(requests)>1:
            add('animal_pk_batch',agent_steps,[Path(f)/'report.json' for f in folders],
                [run/'animal_pk/report.json',run/'animal_pk/artifact_manifest.json'],kind='animal_pk_batch',folders=folders)
            targets={'animal_pk_execution':'animal_pk_batch'}
        else: targets={'animal_pk_execution':agent_steps[0]}
    elif spec.get('mode') == 'animal_pk_architecture':
        from .animal_pk import build_plan
        architecture = build_plan(spec['pk_context'], spec.get('pk_options'))
        architecture_path = write_json(folder/'animal_pk_plan.json', architecture)
        source_refs = [*architecture['source_refs'], ref(architecture_path)]
        agent_steps = {a['id']:'pk_'+a['id'] for a in architecture['agents']}
        for agent in architecture['agents']:
            name=agent_steps[agent['id']]
            deps=[agent_steps[d] for d in agent['depends_on'] if d in agent_steps]
            add(name, deps, [architecture_path], [run/'animal_pk/agents'/agent['id']],
                kind='animal_pk_agent_contract', agent=agent)
        add('animal_pk_architecture', list(agent_steps.values()), [architecture_path],
            [run/'animal_pk/architecture.json',run/'animal_pk/report.json',run/'animal_pk/comparison.csv',run/'animal_pk/artifact_manifest.json'],
            kind='animal_pk_architecture', plan=str(architecture_path))
        targets={'animal_pk_architecture':'animal_pk_architecture'}
    elif spec.get('mode') in {'fresh_pre_eda','fresh_pre_eda_from_rules'}:
        from .adequacy import check_ref
        if spec['mode']=='fresh_pre_eda_from_rules':
            from .project_rule_agent import verify_published
            check_ref(spec['rules_pack_ref']); verify_published(spec['rules_pack_ref'])
            source_refs=[spec['rules_pack_ref']]
        else:
            check_ref(spec['main_ref'])
            main_path = Path(spec['main_ref']['path'])
            from .first_part_handoff import verify_final_main
            if verify_final_main(main_path)['main_ref'] != spec['main_ref']:
                raise ValueError('Fresh pre-EDA run must bind the exact reviewed compression main.')
            source_refs=[spec['main_ref']]
        declared_outputs=[run/'pre_eda_status.json', run/'first_part', run/'data_chain'] if spec['mode']=='fresh_pre_eda_from_rules' else [run/'pre_eda_status.json',run/'cleaning']
        add('fresh_pre_eda', [], [r['path'] for r in source_refs], declared_outputs,
            kind='fresh_pre_eda_from_rules' if spec['mode']=='fresh_pre_eda_from_rules' else 'fresh_pre_eda',
            main_ref=spec.get('main_ref'), rules_pack_ref=spec.get('rules_pack_ref'), model=spec.get('model'),
            auto_approve_human_gates=spec.get('auto_approve_human_gates') is True,
            user_authorized_automation=spec.get('user_authorized_automation') is True,
            state_dir=spec['state_dir'], outputs_dir=spec['outputs_dir'])
        targets = {'data_preparation': 'fresh_pre_eda'}
    elif spec.get('mode') == 'direct_preparation':
        from .adequacy import check_ref
        check_ref(spec['approval_ref'])
        from .direct_preparation import reviewed
        approval, refs, plan_value, inventory, source, coverage, necessity = reviewed(spec['approval_ref'])
        source_refs = [spec['approval_ref'], *[{'path': a['path'], 'sha256': a['sha256']} for a in approval['artifacts']],
                       *approval['inputs'].values()]
        verify_refs(source_refs)
        add('direct_preparation', [], [r['path'] for r in source_refs],
            [run/'cleaning_status.json', run/'data_preparation'], kind='direct_preparation',
            approval_ref=spec['approval_ref'], model=spec.get('model'), authorization=spec['launch_authorization'])
        targets = {'data_preparation': 'direct_preparation'}
    elif spec.get('mode') == 'supplemental':
        from .common import PipelineError
        raise PipelineError('EDA_DISABLED', 'EDA is disabled. Its backend has been removed and will not be called.')
    elif spec.get('mode') == 'reviewed_eda':
        from .clinical_dispatch import inputs
        from .adequacy import check_ref
        snapshot, _, _, _, datasets = inputs(spec['reviewed_eda'], require_eda=True)
        check_ref(spec['clinical_spec'])
        source_refs = [spec['reviewed_eda'], spec['clinical_spec']]
        source_refs += [r for n in snapshot['nodes'].values() for r in n['artifacts']]
        source_refs += [d[k] for d in datasets for k in ['data','csv','metadata_file','quarantine']]
        add('clinical_dispatch', [], [r['path'] for r in source_refs], [run/'dispatch'],
            kind='clinical_dispatch', snapshot=spec['reviewed_eda'], clinical_spec=spec['clinical_spec'])
        targets = {'clinical_dispatch':'clinical_dispatch'}
    elif spec.get('mode') == 'reviewed_preparation':
        from .common import PipelineError
        raise PipelineError('EDA_DISABLED', 'EDA is disabled. Its backend has been removed and will not be called.')
    elif spec.get('mode') == 'reviewed_data':
        from .preparation_workflow import approved_inputs
        approval, qc, report = approved_inputs(spec['approved_data'])
        source_refs = [spec['approved_data'], *approval['adequacy']['artifacts'], qc['upstream_main'], *qc['files']]
        if approval.get('preparation_plan'): source_refs.append(approval['preparation_plan'])
        add('reviewed_data', [], [r['path'] for r in source_refs], [run / 'preparation_inputs/qc_context.json'],
            kind='reviewed_data', approval=spec['approved_data'])
        if spec.get('data_agents_version') == '2.0':
            if qc.get('schema_version') != '2.0':
                raise ValueError('Rebuilt Data module requires new requirements and labels. Rerun Define requirements & label data from the approved context; old data outputs remain historical.')
            source_refs += [qc[k] for k in ['inventory','requirements','labels']]
            add('data_preparation_agent',['reviewed_data'],[run/'preparation_inputs/qc_context.json'],
                [run/'data_agents/preparation_plan.json'],kind='data_v2_plan',model=spec.get('model'))
            add('data_transform',['data_preparation_agent'],[run/'preparation_inputs/qc_context.json',run/'data_agents/preparation_plan.json'],
                [run/'data_preparation/preparation_execution.json',run/'data_preparation/normalization_manifest.json',run/'source_preparation/output.json'],kind='data_v2_transform')
            add('data_metadata_validation',['data_transform'],[run/'data_preparation/preparation_execution.json'],
                [run/'data_agents/metadata_review.json'],kind='data_v2_metadata')
            add('data_handoff_agent',['data_metadata_validation'],[run/'data_preparation/preparation_execution.json',run/'data_agents/metadata_review.json'],
                [run/'data_preparation'],kind='data_v2_publish',model=spec.get('model'),
                clean=[run/'data_preparation/data_report.json', run/'data_preparation/main.json',
                       run/'data_preparation/handoffs', run/'data_preparation/handoff_review.json'])
            targets={'data_preparation':'data_handoff_agent'}
        else:
            add('partition_sources', ['reviewed_data'], [run / 'preparation_inputs/qc_context.json'],
                [run / 'source_preparation'], kind='partition_sources')
            add('clean_and_assess', ['partition_sources'], [run / 'preparation_inputs/qc_context.json', run / 'source_preparation/output.json'],
                [run / 'data_preparation'], kind='clean_and_assess')
            targets = {'data_preparation': 'clean_and_assess'}
    elif spec.get('mode') == 'reviewed_context':
        from .adequacy import check_ref
        check_ref(spec['approved_context'])
        approval = read_json(spec['approved_context']['path'])
        source_refs = [spec['approved_context'], *approval['context']['artifacts']]
        if approval.get('project_rules_ref'):
            from .project_rule_agent import verify_published, validate_input
            pack_ref = approval['project_rules_ref']; pack = verify_published(pack_ref)
            source_refs += [pack_ref, *[pack[key] for key in
                ['main_ref', 'audit_ref', 'input_ref', 'candidate_ref', 'review_ref', 'base_main_ref']],
                *validate_input(pack['input_ref'])['source_refs']]
            verify_refs(source_refs)
        if approval.get('scope_amendment'):
            check_ref(approval['scope_amendment']); source_refs.append(approval['scope_amendment'])
        main = next(a for a in approval['context']['artifacts'] if a['name'] == 'main.json')
        source_refs += [ref(f['path']) for f in read_json(main['path'])['data']['files']]
        add('reviewed_context', [], [r['path'] for r in source_refs], [run / 'B1/main.json', run / 'B1/context_provenance.json'],
            kind='reviewed_context', approval=spec['approved_context'])
        if spec.get('data_agents_version') == '2.0':
            plan=[Path(spec['table_range_plan'])] if spec.get('table_range_plan') else []
            if spec.get('demo_lightweight_data') and spec.get('demo_retained_data'):
                source_refs += list(spec['demo_retained_data'].values())
                add('data_label_agents', ['reviewed_context'], [run/'B1/main.json', *[r['path'] for r in spec['demo_retained_data'].values()]],
                    [run/'adequacy/inventory.json', run/'adequacy/requirements.json', run/'adequacy/data_labels.json', run/'adequacy/retained_inputs.json'],
                    kind='data_v2_restore', references=spec['demo_retained_data'])
            else:
                add('data_inventory',['reviewed_context'],[run/'B1/main.json',*plan],[run/'adequacy/inventory.json'],kind='data_v2_inventory',model=spec.get('model'))
                # DR runs alongside the inventory; its access call joins both before labelling.
                add('data_requirements_agent',['reviewed_context'],[run/'B1/main.json'],
                    [run/'adequacy/requirement_definition.json'],kind='data_v2_define',model=spec.get('model'))
                add('data_access_agent',['data_inventory','data_requirements_agent'],[run/'B1/main.json',run/'adequacy/inventory.json',run/'adequacy/requirement_definition.json'],
                    [run/'adequacy/requirements.json'],kind='data_v2_access',model=spec.get('model'))
                add('data_label_agents',['data_access_agent'],[run/'B1/main.json',run/'adequacy/inventory.json',run/'adequacy/requirements.json'],
                    [run/'adequacy/data_labels.json'],kind='data_v2_label',model=spec.get('model'))
            add('data_adequacy_agent',['data_label_agents'],[run/'B1/main.json',run/'adequacy/inventory.json',run/'adequacy/requirements.json',run/'adequacy/data_labels.json'],
                [run/'adequacy/adequacy.json',run/'adequacy/qc_context.json',run/'adequacy/assessment.json',run/'adequacy/review.json',run/'adequacy/requirement_matrix.json',run/'adequacy/condition_checklist.json',run/'adequacy/unresolved_ledger.json',run/'adequacy/evidence_gaps.csv',run/'adequacy/report.md',run/'adequacy/checkpoint.json',run/'adequacy/checkpoint.md'],kind='data_v2_assess',model=spec.get('review_model') or spec.get('model'))  # DC008: optional separate review model.
            targets={'adequacy':'data_adequacy_agent'}
        else:
            add('adequacy_inventory', ['reviewed_context'], [run / 'B1/main.json'],
            [run / 'adequacy/inventory.json'], kind='adequacy_inventory')
            advisory=reference_steps(run/'B1/main.json','reviewed_context') if spec.get('pk_reference_pilot') else None
            advisory_inputs=[advisory] if advisory else []
            add('adequacy_assessment', ['adequacy_inventory'] + (['pk_reference_review'] if advisory else []), [run / 'B1/main.json', run / 'adequacy/inventory.json', *advisory_inputs],
            [run / 'adequacy/assessment.json'], kind='adequacy_assessment', model=spec.get('model'), reference_context=str(advisory) if advisory else None)
            add('adequacy_review', ['adequacy_assessment'], [run / 'B1/main.json', run / 'adequacy/inventory.json', run / 'adequacy/assessment.json', *advisory_inputs],
            [run / 'adequacy/adequacy.json', run / 'adequacy/qc_context.json', run / 'adequacy/evidence_gaps.csv', run / 'adequacy/report.md'],
            kind='adequacy_review', model=spec.get('model'), reference_context=str(advisory) if advisory else None)
            add('sources', ['adequacy_review'], [run / 'adequacy/qc_context.json'],
            [run / 'source_preparation'], kind='sources', qc_gate=str(folder / 'qc_release.json'))
            add('data_review', ['sources'], [run / 'B1/main.json', run / 'source_preparation/output.json'],
            [run / 'data_preparation'], kind='data_review')
            targets = {'adequacy': 'adequacy_review', 'data_preparation': 'data_review'}
    elif spec.get('mode', 'fresh') == 'fresh':
        verify_refs([{'path': f['path'], 'sha256': f['sha256']} for f in spec['uploads'] if f.get('sha256')])
        work = run / 'context_work'; source_refs = [ref(f['path']) for f in spec['uploads']]
        add('intake', [], [f['path'] for f in spec['uploads']], [work / 'inputs.json', work / 'intake'], kind='intake',
            clean=[work, run / 'uploaded_sources'], work=str(work), uploads=spec['uploads'],
            proposal_entry=spec.get('proposal_entry'), reference_only=spec.get('reference_only', []), revision=spec.get('context_revision'),
            **({'compression_profile': spec['compression_profile']} if spec.get('compression_profile') else {}))
        add('compress', ['intake'], [work / 'inputs.json'], [run / 'B1/main.json'], kind='compress',
            clean=[], work=str(work), model=spec.get('model'))
        # Build the complete dependency chain even when the first target is intake.
        # Saved plans remain immutable when a user later resumes context.
        rules_input_path = run / 'project_rules/input.json'
        add('project_rules_prepare', ['compress'], [run / 'B1/main.json'], [rules_input_path],
            kind='project_rules_prepare', compression_run=str(work), project_materials=spec.get('project_materials', []))
        project_rule_steps(rules_input_path, dependency='project_rules_prepare')
        targets = {'intake': 'intake', 'compression': 'compress',
                   'context': ('compress' if spec.get('compression_profile') == 'LEAN_1.0'
                               and not spec.get('context_include_project_rules') else 'project_rules_publish'),
                   'project_rules': 'project_rules_publish'}
    else:
        base = Path(spec['baseline'])
        source_refs = [ref(spec['package']), ref(base / 'B1/main.json')]
        source_refs += [ref(f['path']) for f in read_json(base / 'B1/main.json')['data']['files']]
        add('sources', [], [spec['package'], base / 'B1/main.json'], [run / 'B1/main.json', run / 'attachments', run / 'source_preparation'],
            [py('prepare_package_rerun.py', '--package', spec['package'], '--previous-main', base / 'B1/main.json', '--out', run)], clean=[run])
        add('data', ['sources'], [run / 'B1/main.json', run / 'source_preparation/output.json'], [run / 'data_preparation'],
            [py('run_pmb_data_review.py', '--out', run / 'data_preparation', '--source-preparation', run / 'source_preparation',
                '--upstream-main', run / 'B1/main.json', '--request-id', spec['id'])])
        previous = write_json(folder / 'previous_inventory.json', {'datasets': [
            {'file': d['json']} for d in read_json(base / 'data_preparation/normalization_manifest.json')['datasets']]})
        add('model_inputs', ['data'], [run / 'data_preparation/normalization_manifest.json', base / 'rat_population/input.json'], [run / 'model_inputs'],
            [py('prepare_package_model_inputs.py', '--run', run, '--previous-run', base)])
        add('route', ['model_inputs'], [run / 'B1/main.json', run / 'data_preparation/main.json'], [run / 'handoffs'], kind='route')
        for branch, data, script in [('rat_population', 'rat', 'review_population_candidates.R'),
                                      ('rat_individual', 'rat', 'review_rat_pk_candidates.R'),
                                      ('mouse_plasma', 'mouse', 'review_mouse_composite.R')]:
            add(branch, ['route'], [run / 'handoffs' / (branch + '.json')], [run / branch],
                [py('run_review_process.py', '--input', run / 'handoffs' / (branch + '.json'),
                    '--r-script', PROJECT / 'pkpd_r/scripts' / script, '--out', run / branch)],
                slots=budget['rat_workers'] if branch == 'rat_population' else 1)
        add('index', ['route'], [run / 'handoffs/index.json', previous],
            [run / 'index/index_output.json', run / 'index/dataset_screening.json', run / 'index/execution.json', run / 'index/candidate_specifications.json'],
            [py('rescreen_pmb_indices.py', '--prepared-manifest', run / 'handoffs/index.json', '--previous-inventory', previous, '--out', run / 'index', '--expanded')], clean=[run / 'index'])
        add('index_audit', ['index'], [run / 'index/index_output.json'], [run / 'index/supplemental_input_audit.json'],
            [py('audit_package_index_inputs.py', '--run', run)])
        add('verify_r', ['rat_population'], [run / 'rat_population/results/output.json'], [run / 'verification/verification.json'],
            [[rscript_path(), '--vanilla', str(PROJECT / 'pkpd_r/scripts/verify_population_review.R'), str(run / 'rat_population'), str(run / 'verification')]])
        tests = ['test_supplemental_preparation.py', 'test_index_screening.py', 'test_population_candidates.py', 'test_source_preparation.py']
        # The R verifier owns initial creation of verification/. Tests follow it.
        add('tests', ['verify_r'], [run / 'verification/verification.json'], [run / 'verification/tests.junit.xml'],
            [[sys.executable, '-I', '-X', 'utf8', '-m', 'pytest', *[str(BACKEND / 'research_pipeline/tests' / t) for t in tests], '-q', '-x',
              '--basetemp', str(folder / 'pytest_run'), '--junitxml', str(run / 'verification/tests.junit.xml')]])
        add('assemble', ['rat_individual', 'mouse_plasma', 'index_audit', 'verify_r', 'tests'],
            [run / 'rat_population/results/output.json', run / 'index/index_output.json'],
            [run / 'main.json', run / 'verification/package_provenance.json'],
            [py('assemble_species_review.py', '--run', run, '--prepared', run / 'data_preparation/normalized', '--catalog', run / 'attachments/F0003.csv',
                '--junit', run / 'verification/tests.junit.xml'), py('verify_package_rerun.py', '--run', run, '--previous-run', base)])
        targets = {'data_preparation': 'data', 'exploratory_results': 'assemble'}
    code = [p for p in (BACKEND / 'research_pipeline/research_pipeline').glob('*.py')
            if p.name not in {'workbench.py', 'api.py', 'model_connection.py'}]
    for step in steps.values():
        for command in read_json(step['contract'])['commands']:
            code.extend(Path(arg) for arg in command if str(arg).endswith('.py') and Path(arg).is_file())
    code += list((PROJECT / 'pkpd_r').rglob('*.R')) + list((BACKEND / 'context_compression/ctxcomp').glob('*.py'))
    code += list((BACKEND / 'research_pipeline/workflow').rglob('*.smk')) + [BACKEND / 'research_pipeline/workflow/Snakefile']
    code += list((BACKEND / 'context_compression/ctxcomp/resources').glob('*.*')) + list((BACKEND / 'context_compression/schemas').glob('*.json'))
    code += list((BACKEND / 'research_pipeline/research_pipeline/schemas').glob('*.json'))
    code += list((BACKEND / 'research_pipeline/research_pipeline/resources/pk_references').glob('*.json'))
    code += [path for layer in ('general', 'intake', 'compression', 'project_rules', 'eda') for path in sorted((RULES / layer).glob('*.json'))]
    from .data_agents import AGENT_FILES
    code += [*AGENT_FILES.values(), RULES / 'data/pkpd_method_profiles.json']
    code = list(dict.fromkeys(code))
    plan = {'schema_version': '1.0', 'steps': steps, 'targets': targets, 'cpu': budget,
        'receipts': str(folder / 'receipts'), 'source_refs': source_refs, 'code_refs': [ref(p) for p in code],
        'contract_refs': [ref(s['contract']) for s in steps.values()],
        'scheduler': 'Prefect', 'file_executor': 'Snakemake', 'automatic_retries': 0,
        'science_scope': 'Exploratory review only; this plan cannot sign data gates or establish human prediction.'}
    write_json(path, plan); return plan


def stop_process(proc):
    if proc.poll() is not None: return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True,
                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    else:
        import psutil
        parent = psutil.Process(proc.pid)
        for child in parent.children(recursive=True): child.terminate()
        parent.terminate()


def execute_contract(path):
    c = read_json(path); cancel = Path(c['cancel_file'])
    if cancel.exists(): raise RuntimeError('Another block failed; run stopped')
    for dep in c['dependency_receipts']: verify_refs(read_json(dep)['outputs'])
    attempt = Path(c['attempts_dir']) / uuid4().hex; attempt.mkdir(parents=True)
    record = {'stage': c['stage'], 'status': 'RUNNING', 'started_at': utcnow(), 'contract': ref(path), 'pid': os.getpid(), 'processes': []}
    write_json(attempt / 'execution.json', record)
    try:
        # Preserve incomplete outputs on explicit resume, within this job only.
        root = Path(c['run_root']).resolve()
        for i, value in enumerate(c['partial_paths']):
            p = Path(value).resolve()
            if not p.is_relative_to(root): raise ValueError('Partial output outside this run')
            if p.exists():
                archive = attempt / 'previous_partial' / str(i); archive.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(p), str(archive))
        execute_builtin(c)
        env = os.environ.copy()
        env.update(OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
                   VECLIB_MAXIMUM_THREADS='1', PKPD_WORKERS=str(c['cpu_slots']), LC_ALL='C')
        for i, command in enumerate(c['commands']):
            if cancel.exists(): raise RuntimeError('Another block failed; run stopped')
            with (attempt / f'{i}.log').open('w', encoding='utf-8') as log:
                proc = subprocess.Popen(command, cwd=PROJECT, stdout=log, stderr=log, env=env,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                record['processes'].append({'pid': proc.pid, 'command': command, 'cpu_slots': c['cpu_slots']})
                write_json(attempt / 'execution.json', record)
                while proc.poll() is None:
                    if cancel.exists():
                        stop_process(proc); raise RuntimeError('Another block failed; active process stopped')
                    time.sleep(.2)
                if proc.returncode:
                    raise RuntimeError(f'{c["stage"]}: exit {proc.returncode}\n' + (attempt / f'{i}.log').read_text(encoding='utf-8', errors='replace')[-8000:])
        outputs = []
        for name in c['outputs']:
            p = Path(name)
            if not p.exists(): raise RuntimeError('Expected output missing: ' + name)
            outputs.extend(ref(x) for x in (sorted(p.rglob('*')) if p.is_dir() else [p]) if x.is_file())
        record.update(status='SUCCEEDED', finished_at=utcnow(), outputs=outputs)
        write_json(c['receipt'], record)
    except BaseException as exc:
        from .context_feedback import ContextRevisionRequired
        if c['kind'] == 'intake':
            work = Path(c['options']['work'])
            write_json(work / 'stopped.json', {'at': utcnow(), 'status': 'ERROR', 'stage': 'intake',
                'error_code': 'UPLOAD_READ_FAILED' if (work / 'intake/read_error.json').is_file() else 'UPLOAD_INTAKE_FAILED',
                'reason': str(exc)})
        if c['kind'] in {'reviewed_data','partition_sources','clean_and_assess'} or c['kind'].startswith('data_v2_'):
            write_json(Path(c['run_root']) / 'data_preparation/stopped.json', {
                'at': utcnow(), 'status': 'ERROR', 'stage': c['stage'],
                'error_code': getattr(exc, 'code', 'PREPARATION_EXECUTION_FAILED'), 'reason': str(exc)})
        if c['kind'].startswith('data_v2_'):
            write_json(Path(c['run_root'])/'data_agents/stopped.json',{'at':utcnow(),'status':'ERROR','stage':c['stage'],
                'error_code':getattr(exc,'code','DATA_AGENT_ERROR'),'reason':str(exc),
                'next_action':'Inspect this agent request/response and the cited source. Correct the source definition, mapping or output contract, then explicitly retry this Data stage. Compression is not repeated.'})
        if c['kind'] in {'reviewed_preparation','eda_describe','eda_report'}:
            write_json(Path(c['run_root']) / 'eda/stopped.json', {'at':utcnow(),'status':'ERROR','stage':c['stage'],
                'error_code':getattr(exc,'code','EDA_EXECUTION_FAILED'),'reason':str(exc)})
        if c['kind'] == 'clinical_dispatch':
            write_json(Path(c['run_root'])/'dispatch/stopped.json', {'at':utcnow(),'status':'ERROR','stage':c['stage'],
                'error_code':getattr(exc,'code','DISPATCH_EXECUTION_FAILED'),'reason':str(exc)})
        if c['kind'] in {'project_rules_prepare', 'project_rules_extract', 'project_rules_review', 'project_rules_publish'}:
            write_json(Path(c['run_root']) / 'project_rules/stopped.json', {
                'at': utcnow(), 'status': 'ERROR', 'stage': c['stage'],
                'error_code': getattr(exc, 'code', 'PROJECT_RULES_EXECUTION_FAILED'), 'reason': str(exc),
                'next_action': 'Inspect the saved input, candidate and review diagnostics; correct the identified contract or evidence issue and start a new project-rules job. The original compression handoff is unchanged.'})
        record.update(status='REVISION_REQUIRED' if isinstance(exc, ContextRevisionRequired) else 'STOPPED_ON_ERROR',
                      finished_at=utcnow(), error=str(exc)); cancel.touch(exist_ok=True)
        raise
    finally: write_json(attempt / 'execution.json', record)


def execute_builtin(c):
    options, kind = c['options'], c['kind']
    if kind == 'commands': return
    if kind == 'demo_key_rules':
        from .demo_key_rules import extract, verify
        input_ref = options.get('input_ref') or ref(options['input_path'])
        verify(extract(input_ref, Path(c['outputs'][0]).parent, model=options.get('model')))
        return
    if kind == 'project_rules_prepare':
        from .project_rule_agent import prepare, validate_input
        prepare(options['compression_run'], c['outputs'][0], options.get('project_materials', []))
        validate_input(ref(c['outputs'][0]))
    elif kind in {'project_rules_extract', 'project_rules_review', 'project_rules_publish'}:
        from .project_rule_agent import extract, review, publish
        input_ref = options.get('input_ref') or ref(options['input_path'])
        if kind == 'project_rules_extract':
            extract(input_ref, c['outputs'][0], model=options.get('model'))
            required = ['candidate.json']
        elif kind == 'project_rules_review':
            from .project_rule_agent import validate_input
            from . import project_rule_pipeline as ledger
            if ledger.enabled(validate_input(input_ref)):
                ledger.review_with_repair(input_ref,ref(c['inputs'][1]),c['outputs'][0],model=options.get('model'))
            else:
                review(input_ref, ref(c['inputs'][1]), c['outputs'][0], model=options.get('model'))
            required = ['review.json']
        else:
            candidate_ref,review_ref=ref(c['inputs'][1]),ref(c['inputs'][2])
            selection_path=Path(c['inputs'][2]).parent/'selection.json'
            if selection_path.exists():
                selection=read_json(selection_path)
                if selection['initial_candidate_ref']!=candidate_ref:
                    raise ValueError('Rule review selection belongs to a different initial candidate.')
                if read_json(selection['review_ref']['path'])!=read_json(c['inputs'][2]):
                    raise ValueError('Rule review selection differs from the exposed review.')
                if selection['candidate_ref']!=candidate_ref:
                    selected_candidate=read_json(selection['candidate_ref']['path'])
                    if (selected_candidate.get('lineage') or {}).get('candidate_ref')!=candidate_ref:
                        raise ValueError('Selected rule candidate is not a local repair of this extraction.')
                candidate_ref,review_ref=selection['candidate_ref'],selection['review_ref']
            publish(input_ref, candidate_ref, review_ref, c['outputs'][0])
            report = read_json(Path(c['outputs'][0]) / 'report.json')
            if report.get('status') not in {'PROJECT_RULES_PUBLISHED', 'RULES_REVISION_REQUIRED'}:
                raise ValueError('Unknown project-rules publication status')
            required = ['report.json']
            if report['status'] == 'PROJECT_RULES_PUBLISHED':
                required += ['main.json', 'project_rules.json', 'rule_audit.json']
            elif any((Path(c['outputs'][0]) / name).exists() for name in ['main.json', 'project_rules.json']):
                raise ValueError('A project-rules revision cannot expose a published handoff')
        for name in required:
            if not (Path(c['outputs'][0]) / name).is_file():
                raise ValueError('Expected project-rules output missing: ' + name)
    elif kind == 'pk_reference_prepare':
        from .pk_reference_pilot import prepare
        prepare(ref(c['inputs'][0]), options['library'], c['outputs'][0])
    elif kind == 'pk_reference_review':
        from .pk_reference_pilot import execute
        execute(c['inputs'][0], c['outputs'][0], model=options.get('model'))
    elif kind in {'main_reference_revision','main_reference_revision_review'}:
        from .main_reference_revision import propose, review
        try:
            if kind=='main_reference_revision':
                propose(ref(c['inputs'][0]),ref(c['inputs'][1]),c['outputs'][0],model=options.get('model'))
            else:
                review(ref(c['inputs'][0]),c['outputs'][0],model=options.get('model'))
        except Exception as exc:
            write_json(Path(c['outputs'][0])/'stopped.json',{'at':utcnow(),'status':'ERROR','stage':kind,
                'error_code':getattr(exc,'code','MAIN_REVISION_INVALID'),'reason':str(exc),
                'next_action':'Inspect the revision response and independent review. Correct the identified changes and run a new revision. The accepted main.json is unchanged.'})
            raise
    elif kind == 'animal_pk_individual_candidate':
        from .animal_pk_individual import execute_candidate
        execute_candidate(options['request_ref'],c['outputs'][0])
    elif kind == 'animal_pk_individual_report':
        from .animal_pk_individual import assemble
        assemble(options['master_ref'],options['folders'],Path(c['outputs'][0]).parent)
    elif kind == 'animal_pk_summary_candidate':
        from .animal_pk_summary import execute_candidate
        execute_candidate(options['request_ref'],c['outputs'][0])
    elif kind == 'animal_pk_summary_report':
        from .animal_pk_summary import assemble
        assemble(options['master_ref'],options['folders'],Path(c['run_root'])/'animal_pk')
    elif kind == 'animal_pk_execution':
        from .animal_pk_control import execute_agent
        execute_agent(options['request_ref'], c['outputs'][0])
    elif kind == 'animal_pk_batch':
        from .animal_pk_control import assemble_batch
        assemble_batch(options['folders'],Path(c['run_root'])/'animal_pk')
    elif kind == 'animal_pk_agent_contract':
        from .animal_pk import materialize_agent
        materialize_agent(options['agent'], c['outputs'][0])
    elif kind == 'animal_pk_architecture':
        from .animal_pk import assemble_architecture
        assemble_architecture(options['plan'], c['run_root'])
    elif kind == 'supplemental_prepare':
        from .tributary_processing import prepare_tributary
        prepare_tributary(options['request'], c['outputs'][0])
    elif kind == 'supplemental_eda':
        from .common import PipelineError
        raise PipelineError('EDA_DISABLED', 'EDA is disabled. Its backend has been removed and will not be called.')
    elif kind == 'intake':
        from ctxcomp.engine import init_run
        from ctxcomp.intake import inputs_from
        from ctxcomp.rules import intake_agent_contract
        if c.get('agent_contract', intake_agent_contract()) != intake_agent_contract():
            raise ValueError('Intake agent rules changed; create a new run with the current contract.')
        work = Path(options['work']); supplied = work.parent / 'uploaded_sources'; supplied.mkdir(parents=True)
        files = options['uploads']
        if len(files) == 1 and Path(files[0]['path']).suffix.lower() == '.zip':
            source = list(inputs_from(package=files[0]['path']))
        else:
            if any(Path(f['path']).suffix.lower() == '.zip' for f in files): raise ValueError('One ZIP or individual files, not both')
            source = [(f['name'], Path(f['path']).read_bytes(), {}) for f in files]
        paths, names = [], set()
        for name, content, origin in source:
            basename = Path(name).name
            if basename.casefold() in names: raise ValueError('Duplicate attachment filename: ' + basename)
            names.add(basename.casefold()); target = supplied / basename
            target.write_bytes(content); paths.append(str(target))
        init_run(work, attachments=paths, proposal_entry=options.get('proposal_entry') or None,
                 reference_only=options.get('reference_only', []), opaque_references=True, revision=options.get('revision'),
                 **({'compression_profile': options['compression_profile']} if options.get('compression_profile') else {}))
    elif kind == 'compress':
        from ctxcomp.providers import run_model
        from ctxcomp.engine import verify_context, load_run
        work = Path(options['work']); fresh = ()
        control = work / 'stage_control.json'
        if control.is_file():  # A person's one-off request to redo a stage; kept as history once read.
            fresh = tuple(read_json(control).get('fresh', ()))
            control.rename(work / f'stage_control.{uuid4().hex}.used.json')
        # Answers shared between runs (CTXCOMP_STAGE_CACHE, set by the workbench); unset, nothing is shared.
        shared = os.environ.get('CTXCOMP_STAGE_CACHE', '').strip()
        shared = None if shared.lower() in {'', 'off', '0', 'none'} else shared
        _, compression_state = load_run(work)
        if os.getenv('CTXCOMP_DISABLE_RESPONSE_REUSE') == '1' and compression_state['accepted']:
            raise ValueError('Response reuse is disabled: create a fresh run instead of reusing Context')
        if not fresh and 'context_review' in compression_state['accepted']:
            # A complete retained handoff needs verification, not another dispatch
            # into a prior failed model session. The original ledger is immutable.
            retained = verify_context(work)
            write_json(work/'audit/verified_context_reuse.json', {
                'at': utcnow(), 'handoff': ref(retained['handoff_file']),
                'new_model_calls': False, 'scientific_release': False})
            result = {'status': 'CONTEXT_READY'}
        else:
            result = run_model(work, model=options.get('model') or None, shared_cache=shared, fresh=fresh)
        if result['status'] in {'REVISE', 'NEEDS_REVIEW'}:
            from .context_feedback import context_feedback, ContextRevisionRequired
            feedback = context_feedback(work.parent)
            if not feedback: raise ValueError('Context stopped for review, but its review evidence is missing')
            raise ContextRevisionRequired(feedback['summary'])
        if result['status'] != 'CONTEXT_READY': raise ValueError('Context execution did not finish: ' + str(result))
        verify_context(work); write_json(c['outputs'][0], read_json(work / 'handoff/main.json'))
    elif kind == 'clinical_dispatch':
        from .clinical_dispatch import execute
        execute(options['snapshot'], options['clinical_spec'], c['outputs'][0])
    elif kind == 'reviewed_preparation':
        from .common import PipelineError
        raise PipelineError('EDA_DISABLED', 'EDA is disabled. Its backend has been removed and will not be called.')
    elif kind in {'eda_describe', 'eda_report'}:
        from .common import PipelineError
        raise PipelineError('EDA_DISABLED', 'EDA is disabled. Its backend has been removed and will not be called.')
    elif kind == 'reviewed_data':
        from .preparation_workflow import import_inputs
        import_inputs(options['approval'], c['outputs'][0])
    elif kind == 'direct_preparation':
        from .direct_preparation import run
        run(options['approval_ref'], c['run_root'], model=options.get('model'), review=True)
    elif kind == 'fresh_pre_eda':
        from .pre_eda_workflow import run
        if options.get('auto_approve_human_gates') is not True or options.get('user_authorized_automation') is not True:
            raise ValueError('Fresh pre-EDA automation requires explicit per-run user authorization.')
        run(options['main_ref']['path'], c['run_root'], state=options['state_dir'],
            outputs=options['outputs_dir'], model=options.get('model'), auto_approve_human_gates=True)
    elif kind == 'fresh_pre_eda_from_rules':
        from .pre_eda_workflow import run_from_rules_pack
        if options.get('auto_approve_human_gates') is not True or options.get('user_authorized_automation') is not True:
            raise ValueError('Fresh pre-EDA automation requires explicit per-run user authorization.')
        run_from_rules_pack(options['rules_pack_ref'], c['run_root'], state=options['state_dir'],
            outputs=options['outputs_dir'], model=options.get('model'), auto_approve_human_gates=True)
    elif kind == 'partition_sources':
        from .preparation_workflow import split_sources
        split_sources(c['inputs'][0], c['outputs'][0])
    elif kind == 'clean_and_assess':
        from .preparation_workflow import prepare
        prepare(*c['inputs'], c['outputs'][0])
    elif kind.startswith('data_v2_'):
        from . import data_agents as da
        from . import demo_data
        args=c['inputs'];run=Path(c['run_root']);model=options.get('model')
        scoped = demo_data if options.get('demo_lightweight_data') else da
        if kind=='data_v2_restore':
            if not options.get('demo_lightweight_data'): raise ValueError('Retained-data import requires the explicit demo profile.')
            demo_data.restore(args[0], options['references'], run/'adequacy')
        elif kind=='data_v2_inventory': da.inventory(args[0],c['outputs'][0],run=run,range_plan=args[1] if len(args)>1 else None,model=model)
        elif kind=='data_v2_define': da.define(run,args[0],c['outputs'][0],model=model)
        elif kind=='data_v2_access': da.assign_access(run,*args,c['outputs'][0],model=model)
        elif kind=='data_v2_label': da.label(run,*args,c['outputs'][0],model=model)
        elif kind=='data_v2_assess': scoped.assess(run,*args,run/'adequacy',model=model)
        elif kind=='data_v2_plan': scoped.plan_preparation(run,args[0],c['outputs'][0],model=model)
        elif kind=='data_v2_transform': da.execute_preparation(*args,run/'data_preparation')
        elif kind=='data_v2_metadata': da.metadata_review(run,args[0],c['outputs'][0])
        elif kind=='data_v2_publish': scoped.publish_data(run,*args,run/'data_preparation',model=model)
        else: raise ValueError('Unknown Data agent: '+kind)
    elif kind == 'reviewed_context':
        from .adequacy import import_reviewed_context
        import_reviewed_context(options['approval'], c['outputs'][0])
    elif kind == 'adequacy_inventory':
        from .adequacy import inspect_inputs
        inspect_inputs(c['inputs'][0], c['outputs'][0])
    elif kind in {'adequacy_assessment', 'adequacy_review'}:
        from .adequacy import call_stage, finalize
        args = c['inputs']
        response = call_stage(c['run_root'], kind, args[0], args[1],
            args[2] if kind == 'adequacy_review' else None, model=options.get('model'), reference_context_path=options.get('reference_context'))
        if kind == 'adequacy_assessment': write_json(c['outputs'][0], response)
        else: finalize(c['run_root'], *args[:3], response, reference_context_path=options.get('reference_context'))
    elif kind == 'sources':
        from .adequacy import verify_qc_gate
        verify_qc_gate(options.get('qc_gate'), Path(c['run_root']) / 'adequacy/adequacy.json')
        from .source_preparation import prepare_sources
        result = prepare_sources(c['inputs'][0], c['outputs'][0])
        if result['status'] == 'FAILED': raise ValueError(str(result['errors']))
    elif kind == 'data_review':
        source = read_json(c['inputs'][1])
        write_json(Path(c['outputs'][0]) / 'main.json', {'schema_version': '1.0', 'module': 'data_preparation',
            'status': 'WAITING_FOR_MAPPING_REVIEW', 'upstream_main': ref(c['inputs'][0]), 'source_tables': ref(c['inputs'][1]),
            'candidate_tables': source['tables'], 'cleaning_complete': False, 'fit_ready': False,
            'sample_size_status': 'NOT_CALCULABLE', 'released_datasets': [],
            'required_review': ['Confirm table boundaries, units, dosing, individual identifiers and total/free definitions', 'Provide a data-preparation plan; complete scientific QC and human review'],
            'next_api': '/pipeline/v1/modules/data_preparation/run', 'review_api': '/pipeline/v1/data-reviews',
            'parallel_after_release': ['pk_longitudinal', 'pkpd_index']})
    elif kind == 'route':
        from .context_router import route_context
        route_context(Path(c['run_root']))
    else: raise ValueError('Unknown stage kind: ' + kind)


if __name__ == '__main__': execute_contract(sys.argv[1])
