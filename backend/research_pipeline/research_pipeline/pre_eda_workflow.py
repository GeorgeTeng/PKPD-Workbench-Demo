"""Bound fresh compression-to-DirectDataReview technical preparation adapter.

Runs existing source test stages, lossless input projection, v6 requirement planning,
scoped assessment and the existing direct preparation pipeline. It never enters EDA.
"""
import copy
import json
from pathlib import Path

from .adequacy import file_ref
from .common import read_json, write_json, utcnow


def _project_source(main_path, source_run, out):
    from . import data_agents as agents, method_profiles_next as methods
    from .data_direct_runtime import verify_refs
    from .first_part_handoff import verify_final_main
    main_path, source_run, out = Path(main_path), Path(source_run), Path(out)
    main = read_json(main_path)
    verified = verify_final_main(main_path)
    refs = {k: file_ref(source_run / (k + '.json')) for k in ('inventory', 'definition', 'requirements', 'labels')}
    refs['main'] = verified['main_ref']
    inventory, definition, permissions, labels = [read_json(refs[k]['path']) for k in ('inventory', 'definition', 'requirements', 'labels')]
    if any(value['main'] != refs['main'] for value in (inventory, definition, permissions)):
        raise ValueError('Fresh source stages do not bind to the exact compressed main.')
    if permissions['inventory'] != refs['inventory']:
        raise ValueError('Fresh access permissions bind to a different inventory.')
    for stage in ('inventory', 'define', 'access', 'label'):
        receipt = read_json(source_run / 'receipts' / (stage + '.json'))
        for artifact in receipt['artifacts']: verify_refs({'stage_artifact': artifact})
        if receipt['status'] != 'COMPLETED_TEST_STAGE': raise ValueError('Incomplete fresh source stage: ' + stage)
    allowed = {a['item_id'] for a in permissions['access'] if a['disposition'] == 'REVIEW_DATA'}
    by_id = {p['item_id']: p for p in labels['labels']}
    units, profiles = {}, []
    for item in inventory['items']:
        if item['id'] not in allowed: continue
        if item['id'] not in by_id: raise ValueError('Permitted source has no completed label: ' + item['id'])
        original_units = dict(agents.content_units(item))
        original_units[item['id']] = json.dumps(item['descriptor'], ensure_ascii=False)
        units.update(original_units)
        profile = {k: copy.deepcopy(v) for k, v in by_id[item['id']].items() if k not in ('requirement_ids', 'reason')}
        def compact(value):
            if isinstance(value, dict):
                for key, child in list(value.items()):
                    if key == 'evidence':
                        agents.evidence_check(child, original_units)
                        value['evidence_source_ids'] = list(dict.fromkeys(e['source'] for e in child))
                        del value[key]
                    else: compact(child)
            elif isinstance(value, list):
                for child in value: compact(child)
        compact(profile)
        profiles.append(profile)
    projection = out / 'source_projection'; projection.mkdir(parents=True, exist_ok=False)
    inventory_ref = file_ref(source_run / 'inventory.json')
    permission_path = write_json(projection / 'permissions.json', {'main': refs['main'], 'access': permissions['access']})
    write_json(projection / 'inventory.json', inventory)
    source_view = write_json(projection / 'source_view.json', {
        'version': 'FRESH_SOURCE_VIEW_1.0', 'main_ref': refs['main'], 'profiles': profiles,
        'source_units': units, 'permissions': permissions['access'], 'pending_item_ids': [],
        'extraction_findings': labels['findings'], 'bindings': refs, 'scientific_approval': False,
        'derivation': 'Exact source units and checked fresh labels; no semantic rewriting.'})
    permission_ref = file_ref(permission_path)
    manifest = write_json(projection / 'manifest.json', {'version': 'SOURCE_FIRST_1.0',
        'bindings': {'main': refs['main'], 'source_view': file_ref(source_view), 'inventory': inventory_ref,
            'permissions': permission_ref, 'projection_code': file_ref(Path(__file__)),
            'original_data_checker': file_ref(agents.__file__)},
        'derivation': 'Fresh checked extraction; no historical source responses reused.', 'scientific_approval': False})
    wrapped_method_profiles = methods.planning_context()
    method_profiles = write_json(projection / 'local_method_profiles.json',
        _flatten_method_profiles(wrapped_method_profiles, methods.LIBRARY_PATH, methods.__file__))
    baseline = write_json(projection / 'input_bindings.json', {'main': refs['main'], 'source_view': file_ref(source_view)})
    return {'source_run': source_run, 'projection': projection, 'source_view': source_view,
            'manifest': manifest, 'baseline': baseline, 'method_profiles': method_profiles}


def _json_safe(value):
    if isinstance(value, Path): return str(value)
    if isinstance(value, dict): return {str(k): _json_safe(v) for k,v in value.items()}
    if isinstance(value, (tuple,list)): return [_json_safe(v) for v in value]
    if value is None or isinstance(value,(str,int,float,bool)): return value
    return repr(value)


def _flatten_method_profiles(wrapped, source_path, adapter_path=None):
    """Expose the frozen library at the legacy Necessity consumer's top level."""
    from .adequacy import file_ref
    library = wrapped['library']
    projected = {**copy.deepcopy(library),
        'projection_provenance': {'source': file_ref(source_path),
            'adapter': file_ref(adapter_path or Path(__file__)),
            'transformation': 'Expose the existing library object at top level; preserve profile/source/condition contents exactly.'},
        'authority': wrapped['authority'], 'scientific_release': wrapped['scientific_release']}
    if projected['profiles'] != library['profiles'] or projected['sources'] != library['sources']:
        raise ValueError('Method profile projection changed the frozen library contents.')
    return projected


def run(main_path, output, *, state, outputs, model=None, auto_approve_human_gates=False, status_path=None):
    from . import data_test_workflow as source_test, data_requirement_plan_v6 as dr, data_assessment_workflow as assessment
    from .data_direct_review import DirectDataReview
    from .workflow_canvas import Decision
    from . import direct_preparation
    main_path, output = Path(main_path).resolve(), Path(output).resolve()
    if not auto_approve_human_gates:
        raise ValueError('This automated flow requires explicit auto_approve_human_gates=true for this run.')
    from ctxcomp.providers import provider_model
    from .data_direct_runtime import MODEL as ASSESSMENT_MODEL
    model = provider_model(model)
    if model not in {'gpt-6-sol','gpt-6-luna'}:
        raise ValueError('The existing source test stages support configured gpt-6-sol or gpt-6-luna only; configured model was not changed.')
    planning_model = dr.MODEL
    model_profile = {'source_test': model, 'requirement_plan_v6': planning_model,
                     'coverage_necessity_summary': ASSESSMENT_MODEL, 'direct_preparation': model,
                     'selection': 'configured provider model where accepted; existing assessment runtime retains its fixed model contract'}
    if output.exists() and any(output.iterdir()):
        raise ValueError('Pre-EDA output already exists; existing outputs are preserved.')
    output.mkdir(parents=True, exist_ok=True)
    status_path = Path(status_path or output / 'pre_eda_status.json')
    def phase(stage, call):
        write_json(status_path, {'status': 'RUNNING', 'stage': stage, 'at': utcnow(),
            'model_profile': model_profile, 'auto_approve_human_gates': True,
            'user_authorized_automation': True, 'scientific_release': False, 'downstream_executed': False})
        try:
            result = call()
            write_json(status_path, {'status': 'RUNNING', 'stage': stage, 'at': utcnow(),
                'result': _json_safe(result) if isinstance(result, dict) else None, 'model_profile': model_profile,
                'auto_approve_human_gates': True, 'user_authorized_automation': True,
                'scientific_release': False, 'downstream_executed': False})
            return result
        except BaseException as exc:
            write_json(status_path, {'status': 'FAILED_RETAINED', 'stage': stage, 'at': utcnow(),
                'error': str(exc), 'error_type': type(exc).__name__,
                'auto_approve_human_gates': True, 'user_authorized_automation': True,
                'scientific_release': False, 'downstream_executed': False})
            raise
    try:
        source = output / 'fresh_source'
        for stage in ('inventory', 'define', 'access', 'label'):
            phase('source_' + stage, lambda stage=stage: source_test.run_stage(main_path, source, stage,
                model=model, rules_mode='published'))
        projected = phase('source_projection', lambda: _project_source(main_path, source, output))
        phase('source_checkpoint', lambda: dr.verify_source_checkpoint(projected['projection']))
        plan_path = output / 'requirements' / 'plan.json'
        assessment_path = output / 'assessment'
        from . import context_library
        with context_library.request_scope(output / 'context_support'):
            phase('requirement_plan_v6', lambda: dr.run(projected['projection'], plan_path,
                input_bindings=projected['baseline'], model=planning_model))
            phase('coverage_necessity_summary', lambda: assessment.run(plan_path, projected['source_view'], main_path,
                projected['method_profiles'], assessment_path, contract='original', review_state=Path(state)))
        gate = read_json(assessment_path / 'human_gate.json')
        controller = DirectDataReview(state, outputs)
        decision = Decision(decision='APPROVE', reviewer='USER_AUTHORIZED_AUTOMATION',
            rationale='User explicitly enabled auto_approve_human_gates for this run; scientific checks preserved.',
            output_signature=gate['output_signature'], confirmed=True)
        approved = phase('user_authorized_direct_review', lambda: controller.decide(gate['id'], decision))
        approval_ref = file_ref(controller.path(gate['id']))
        result = phase('direct_preparation_and_qc', lambda: direct_preparation.run(approval_ref, output / 'cleaning',
            model=model, max_review_attempts=1, review_timeout=None))
        write_json(status_path, {'status': 'COMPLETED_TO_CLEANING', 'stage': 'complete', 'at': utcnow(),
            'review_id': gate['id'], 'review': approved, 'cleaning_result': result,
            'model_profile': model_profile, 'auto_approve_human_gates': True, 'user_authorized_automation': True,
            'scientific_release': result.get('scientific_release', False), 'downstream_executed': False,
            'technical_processing_complete': result.get('technical_processing_complete'),
            'handoff_review_complete': result.get('handoff_review_complete'), 'fit_ready': result.get('fit_ready')})
        return result
    except BaseException:
        raise


def run_from_rules_pack(rules_pack_ref, output, *, state, outputs, model=None, auto_approve_human_gates=False):
    """Run the existing formal First Part prepare/review/publish before fresh Data."""
    from . import first_part_cli
    from .project_rule_agent import verify_published
    output=Path(output).resolve(); state_path=output/'pre_eda_status.json'
    if not auto_approve_human_gates:
        raise ValueError('This automated flow requires explicit auto_approve_human_gates=true for this run.')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Pre-EDA output already exists; existing outputs are preserved.')
    output.mkdir(parents=True,exist_ok=True)
    firstpart=output/'first_part'
    from .first_part_handoff import DEFAULT_MODEL as FIRST_PART_REVIEW_MODEL
    write_json(state_path,{'status':'RUNNING','stage':'first_part_review','at':utcnow(),
        'authorization_type':'USER_AUTHORIZED_AUTOMATION','user_authorized_automation':True,
        'auto_approve_human_gates':True,'data_started':False,'scientific_release':False,
        'first_part_review_model':FIRST_PART_REVIEW_MODEL,'rules_pack':rules_pack_ref})
    try:
        pack=verify_published(rules_pack_ref)
        pack_path=Path(rules_pack_ref['path']).resolve()
        if not pack_path.is_relative_to(Path(outputs).resolve()):
            raise ValueError('Published Rules pack must be inside configured project outputs.')
        first_result=first_part_cli.run(pack_path,firstpart)
        if first_result.get('status')!='FIRST_PART_REVIEWED' or not first_result.get('handoff_main_ref'):
            raise ValueError('Formal First Part did not publish a verified PASS handoff; fresh Data was not started.')
        main_ref=first_result['handoff_main_ref']
        main=Path(main_ref['path']).resolve()
        if not main.is_relative_to(output):
            raise ValueError('First Part published main is outside this isolated pre-EDA run.')
    except BaseException as exc:
        write_json(state_path,{'status':'FIRST_PART_REVIEW_FAILED_RETAINED','stage':'first_part_review',
            'at':utcnow(),'error':str(exc),'error_type':type(exc).__name__,
            'first_part_status':locals().get('first_result'),'data_started':False,
            'scientific_release':False,'downstream_executed':False,
            'user_authorized_automation':True,'auto_approve_human_gates':True,
            'first_part_review_model':FIRST_PART_REVIEW_MODEL,'rules_pack':rules_pack_ref})
        raise
    return run(main,output/'data_chain',state=state,outputs=outputs,model=model,
        auto_approve_human_gates=True,status_path=state_path)
