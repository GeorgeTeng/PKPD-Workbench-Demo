"""Lossless host adapter from an approved direct Data review to DP inputs.

No Coverage/Necessity rerun, synthetic PASS, or new scientific associations.
Derived views are reconstructed at every entry to detect post-approval edits.
"""
import copy
from pathlib import Path

from .adequacy import check_ref, file_ref
from .common import PipelineError, read_json, write_json, utcnow
from .preparation_checks import freeze_refs, verify_frozen

VERSION = 'DIRECT_DP_INPUT_1.0'


def reject(message):
    raise PipelineError('DP_HUMAN_APPROVAL_STALE', message)


def reviewed(approval_ref):
    from .data_direct_review import DirectDataReview, effective_assessment
    check_ref(approval_ref)
    approval = read_json(approval_ref['path'])
    review = approval.get('review') or {}
    if (approval.get('scope') != 'DATA_ASSESSMENT_REVIEW'
            or approval.get('gate', {}).get('status') != 'APPROVED'
            or review.get('decision') != 'APPROVE' or review.get('confirmed') is not True
            or not isinstance(review.get('reviewer'), str) or not review['reviewer'].strip()
            or not isinstance(review.get('at'), str) or not review['at'].strip()):
        raise PipelineError('DP_HUMAN_APPROVAL_REQUIRED',
                            'DP requires confirmed human approval with reviewer and timestamp.')
    if (approval.get('superseded_by') or not DirectDataReview.unchanged(approval)
            or review.get('output_signature') != approval.get('output_signature')):
        reject('The approved direct Data checkpoint changed or was superseded.')
    refs = {a['name']: {'path': a['path'], 'sha256': a['sha256']} for a in approval['artifacts']}
    inputs = approval['inputs']
    for name, key in [('plan.json', 'plan'), ('main.json', 'main')]:
        if refs.get(name) != inputs.get(key):
            reject('Reviewed artifacts do not match reviewed inputs: ' + key)
    plan = read_json(inputs['plan']['path'])
    if plan['bindings']['source_view'] != inputs['source_view'] or plan['bindings']['main'] != inputs['main']:
        reject('Reviewed plan belongs to different source inputs.')
    coverage = read_json(refs['coverage.json']['path'])
    _, assessment_ref = effective_assessment(approval)
    necessity = read_json(assessment_ref['path'])
    if not coverage.get('complete') or not necessity.get('complete'):
        reject('Partial assessment checkpoints cannot enter DP.')
    for value in (coverage, necessity):
        if value.get('execution', {}).get('test_generator'):
            reject('Synthetic assessment cannot authorize real DP.')
    if any(coverage['bindings'].get(k) != inputs[k] for k in ('main', 'plan', 'source_view')):
        reject('Coverage belongs to different reviewed inputs.')
    if necessity['bindings'].get('coverage') != refs['coverage.json']:
        reject('Necessity belongs to a different Coverage result.')
    for key, name in [('main','main'),('local_method_profiles','local_method_profiles')]:
        if necessity['bindings'].get(key) != inputs[name]:
            reject('Necessity belongs to different reviewed inputs: '+key)
    inventory_ref = plan['bindings']['inventory']
    check_ref(inventory_ref)
    inventory = read_json(inventory_ref['path'])
    source = read_json(inputs['source_view']['path'])
    if inventory['main'] != inputs['main'] or source['main_ref'] != inputs['main']:
        reject('Source inventory belongs to a different main context.')
    freeze_refs(inventory)
    return approval, refs, plan, inventory, source, coverage, necessity


def views(approval_ref):
    """Pure reconstruction; source labels remain source labels, never new inference."""
    approval, refs, plan, inventory, source, coverage, necessity = reviewed(approval_ref)
    from .data_direct_review import effective_assessment
    _, assessment_ref = effective_assessment(approval)
    permissions = copy.deepcopy(source['permissions'])
    allowed = {p['item_id'] for p in permissions if p['disposition'] == 'REVIEW_DATA'}
    profiles = {p['item_id']: p for p in source['profiles']}
    tables = [i['id'] for i in inventory['items'] if i['kind'] == 'TABLE' and i['id'] in allowed]
    if any(identifier not in profiles for identifier in tables):
        reject('A permitted table is missing its reviewed source profile.')
    # Only preserve associations explicitly present in Coverage; never reuse legacy matching.
    associations = {identifier: set() for identifier in profiles}
    def collect(value, requirement):
        if isinstance(value, dict):
            if value.get('item_id') in associations:
                associations[value['item_id']].add(requirement)
            for child in value.values(): collect(child, requirement)
        elif isinstance(value, list):
            for child in value: collect(child, requirement)
    for identifier, check in coverage['checks'].items(): collect(check, identifier)
    def evidence(value):
        result = copy.deepcopy(value)
        ids = result.pop('evidence_source_ids', [])
        if ids:
            if any(s not in source['source_units'] for s in ids): reject('Source evidence ID is missing.')
            result['evidence'] = [{'source': s, 'quote': source['source_units'][s]} for s in ids]
        return result
    labels, stated = [], []
    for identifier, profile in profiles.items():
        if identifier not in allowed: continue
        label = evidence(profile)
        label['requirement_ids'] = sorted(associations[identifier])
        label['columns'] = [evidence(c) for c in profile.get('columns', [])]
        for value in profile.get('stated_values', []):
            stated.append({'item_id': identifier, **evidence(value)})
        labels.append(label)
    requirements = copy.deepcopy(plan['requirements'])
    for requirement in requirements:
        # A technical packaging task, not a guessed PK/index task assignment.
        requirement['task_id'] = 'APPROVED_SOURCE_PREPARATION'
    req = {'schema_version': VERSION, 'requirements': requirements, 'access': permissions,
           'tasks': [{'id': 'APPROVED_SOURCE_PREPARATION', 'destination': 'eda',
                      'objective': 'Preserve reviewed source records and definitions for technical preparation only.'}],
           'upstream_plan': approval['inputs']['plan'], 'association_policy': 'EXPLICIT_COVERAGE_SOURCE_SCOPES_ONLY'}
    labeled = {'schema_version': VERSION, 'labels': labels, 'stated_values': stated,
               'coverage': copy.deepcopy(coverage['checks']), 'source_view': approval['inputs']['source_view']}
    file_sources = {item['file_id']: item['source'] for item in inventory['items']}
    files = [{**f, **file_sources[f['id']]} for f in inventory['files']]
    base = {'schema_version': VERSION, 'approval': approval_ref, 'assessment': assessment_ref,
            'upstream_main': approval['inputs']['main'], 'inventory': plan['bindings']['inventory'],
            'files': files, 'execution_scope': 'TECHNICAL_PREPARATION_ONLY',
            'scientific_release': False, 'upstream_data': {
                'coverage': refs['coverage.json'], 'necessity': assessment_ref,
                'source_view': approval['inputs']['source_view'], 'plan': approval['inputs']['plan'],
                'approval_signature': approval['output_signature']}}
    return approval, base, req, labeled


def import_inputs(approval_ref, output):
    approval, base, req, labeled = views(approval_ref)
    bindings = freeze_refs(approval_ref, approval, base)
    folder = Path(output).parent
    base['requirements'] = file_ref(write_json(folder/'direct_requirements.json', req))
    base['labels'] = file_ref(write_json(folder/'direct_labels.json', labeled))
    verify_frozen(bindings)
    write_json(output, base)
    return base


def require_approval(context):
    approval, expected, req, labeled = views(context['approval'])
    if any(context.get(k) != v for k, v in expected.items()):
        reject('DP context differs from its approved direct Data checkpoint.')
    for key, value in [('requirements', req), ('labels', labeled)]:
        check_ref(context[key])
        if read_json(context[key]['path']) != value:
            reject('Derived DP input differs from reviewed evidence: ' + key)
    return approval


def host_plan(context_path, output, previous_plan=None):
    """Reuse checked mappings or select only unambiguous reviewed scalar fields."""
    from . import data_agents as d
    from .preparation_views import POLICY, conversion, mapping_factor, scalar_eligible
    context,main,inventory,labeled=d.prepared_input(context_path)
    req=read_json(context['requirements']['path'])
    allowed={x['item_id'] for x in req['access'] if x['disposition']=='REVIEW_DATA'}
    items=[x for x in inventory['items'] if x['kind']=='TABLE' and x['id'] in allowed]
    prior=None
    if previous_plan:
        prior=read_json(previous_plan);check_ref(prior['context'])
        old=d.prepared_input(prior['context']['path'])[0]
        if old['approval']!=context['approval'] or old['inventory']!=context['inventory']:
            reject('Prior mappings belong to another approved source version.')
        d.exact([t['item_id'] for t in prior['tables']],[x['id'] for x in items],'Prior preparation scope')
    tables=[];findings=[];pending=[]
    for f in (prior or {}).get('findings',[]):
        if d.execution_pending(f): pending.append(copy.deepcopy(f))
        else: findings.append(copy.deepcopy(f))
    for item in items:
        label=next(x for x in labeled['labels'] if x['item_id']==item['id'])
        if prior:
            table=copy.deepcopy(next(t for t in prior['tables'] if t['item_id']==item['id']))
        else:
            columns=[]
            for target,meaning in [('time_h','TIME'),('concentration_mg_L','CONCENTRATION')]:
                candidates=[c['header'] for c in label.get('columns',[]) if c.get('meaning')==meaning
                    and item['descriptor']['headers'].count(c['header'])==1
                    and conversion(c,target) is not None and scalar_eligible(c,target)]
                if len(candidates)==1: columns.append({'source_header':candidates[0],'target':target})
                # Multiple measurements become a cell-bound long view. Multiple
                # times remain typed alternatives, never an implicit scalar choice.
            table={'item_id':item['id'],'action':'PREPARE','columns':columns,
                'preparation_policy':POLICY,
                'reason':'Preserve source rows and derive cell-bound observations with typed time alternatives and reviewed column units.',
                'evidence':copy.deepcopy(label.get('evidence',[]))}
        for c in table['columns']:
            if item['descriptor']['headers'].count(c['source_header'])!=1 or mapping_factor(table,label,c) is None:
                reject('Prior scalar mapping is not supported by the current source and adapter.')
        tables.append(table)
    bindings=freeze_refs(context,main,inventory,req,file_ref(d.AGENT_FILES['DP']))
    code_refs=[file_ref(Path(__file__).with_name(name)) for name in
        ('direct_preparation.py','data_agents.py','preparation_views.py','preparation_checks.py','preparation_semantics.py','handoff_review.py')]
    bindings=freeze_refs(bindings,code_refs)
    value={'schema_version':d.VERSION,'executor':'HOST_PROGRAM','context':file_ref(context_path),
        'human_approval':context['approval'],'input_bindings':bindings,'tables':tables,'findings':findings,
        'preparation_policy':POLICY if not prior else prior.get('preparation_policy'),
        'code_refs':code_refs,
        'prior_plan':file_ref(previous_plan) if previous_plan else None,'prior_execution_checks':pending}
    verify_frozen(bindings)
    write_json(output,value)
    return value


def self_check(execution_path):
    """Read persisted outputs against unchanged approved inputs; never repair sources."""
    from . import data_agents as d,preparation_checks as checks
    execution=read_json(execution_path)
    context,_,inventory,labels=d.prepared_input(execution['context']['path'])
    checks.freeze_refs(execution)
    manifest=read_json(execution['manifest']['path'])
    checks.freeze_refs(manifest)
    stored=read_json(execution['program_qc']['path'])
    if stored.get('execution_version')!=checks.EXECUTION_VERSION:
        raise PipelineError('DERIVED_VERSION_STALE','Derived output needs the current execution adapter.')
    qc=checks.verify_preparation(manifest,read_json(execution['plan']['path']),inventory,
        read_json(execution['cleaning_log']['path'])['changes'],read_json(execution['data_dictionary']['path']),labels)
    if qc['decision']!='PASS':
        raise PipelineError('DERIVED_QC_FAILED',str(qc['errors']+[r for r in qc['datasets'] if r['errors']]))
    return qc


def run(approval_ref, output, *, model, reuse_model=None, generator=None, previous_plan=None,
        review_timeout=None, max_review_attempts=1, review=True):
    """Approved Data -> DP -> host QC/metadata -> independent DH; no EDA/fitting.

    Host planning uses reviewed source meanings or source-bound previous mappings.
    Reruns self-check outputs, rebuild damaged derivatives once, and reuse valid DH.
    """
    from . import data_agents as d
    folder = Path(output).resolve()
    context = folder/'inputs/context.json'
    plan = folder/'preparation_plan.json'
    prepared = folder/'data_preparation'
    execution = prepared/'preparation_execution.json'
    metadata = folder/'metadata_review.json'
    stage = 'DP_IMPORT'
    started = utcnow()
    def status(state, **values):
        write_json(folder/'cleaning_status.json', {'started_at':started,'at':utcnow(),
            'stage':stage,'status':state,'requested_model':model,'reuse_model':reuse_model,
            'approval':approval_ref,'scientific_release':False,'downstream_executed':False,**values})
    try:
        status('RUNNING')
        if context.exists():
            previous = read_json(context)
            if previous.get('approval') != approval_ref:
                reject('This output directory belongs to a different reviewed checkpoint; use a new directory.')
            require_approval(previous)
        else:
            import_inputs(approval_ref, context)
        if max_review_attempts not in (1,2) or (review_timeout is not None and review_timeout<=0):
            raise ValueError('Use one or two review attempts and a positive timeout or None for no deadline.')
        options = {'model':model, 'generator':generator,'timeout':review_timeout}
        stage = 'DP_PLAN'; status('RUNNING')
        host_plan(context,plan,previous_plan=previous_plan)
        stage = 'HOST_EXECUTION_QC'; status('RUNNING')
        repairs=[];reused=False
        if execution.exists():
            try:
                old=read_json(execution)
                if old['plan']!=file_ref(plan): raise PipelineError('DERIVED_PLAN_STALE','Preparation plan changed.')
                self_check(execution);reused=True
            except (ValueError,KeyError,OSError) as exc:
                # Input approval was rechecked above. Rebuild derived files once
                # from those immutable sources, never edit source values to pass.
                require_approval(read_json(context))
                repairs.append({'code':getattr(exc,'code',type(exc).__name__),'reason':str(exc),
                    'action':'REBUILD_DERIVED_FROM_APPROVED_SOURCE'})
        if not reused: d.execute_preparation(context, plan, prepared)
        self_check(execution)
        write_json(folder/'self_check.json',{'executor':'HOST_PROGRAM','decision':'PASS',
            'execution':file_ref(execution),'reused_execution':reused,'repairs':repairs,
            'source_modified':False,'maximum_rebuilds':1})
        stage = 'HOST_METADATA_VALIDATION'; status('RUNNING')
        d.metadata_review(folder, execution, metadata)
        from .reading_package import export_package
        export_package(execution, prepared/'reading_package.zip')
        if not review:
            status('HOST_COMPLETE_REVIEW_PENDING',execution=file_ref(execution))
            return {'status':'HOST_COMPLETE_REVIEW_PENDING','technical_processing_complete':True,
                    'handoff_review_complete':False,'summary':{'datasets':len(read_json(prepared/'normalization_manifest.json')['datasets'])}}
        stage = 'DH_HANDOFF'; status('RUNNING')
        for attempt in range(max_review_attempts):
            try:
                d.publish_data(folder, execution, metadata, prepared,**options)
                break
            except Exception as exc:
                retryable=getattr(exc,'code','') in {'MODEL_TIMEOUT','MODEL_RESPONSE_UNAVAILABLE',
                    'DATA_AGENT_STALE_RESPONSE','DATA_AGENT_CONTRACT_INVALID','SCHEMA_VALIDATION_FAILED'}
                if not retryable or attempt+1==max_review_attempts: raise
                require_approval(read_json(context))
                status('RETRYING_REVIEW',attempt=attempt+2,code=getattr(exc,'code',None))
        result = read_json(prepared/'data_report.json')
        export_package(execution, prepared/'reading_package.zip')
        stage = 'COMPLETE'; status('COMPLETE', report=file_ref(prepared/'data_report.json'),
            technical_processing_complete=result['technical_processing_complete'],
            handoff_status=result['status'])
        return result
    except Exception as exc:
        status('FAILED_RETAINED', code=getattr(exc,'code',type(exc).__name__), reason=str(exc))
        raise


def main():
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--review', required=True, help='Existing authoritative approved DirectDataReview review.json')
    parser.add_argument('--output', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--reuse-model', help=argparse.SUPPRESS)  # Legacy CLI compatibility; host planning makes no DP call.
    parser.add_argument('--previous-plan',help='Reuse existing source-bound mappings and findings without DP model calls')
    parser.add_argument('--host-only',action='store_true',help='Prepare and self-check; leave independent review pending')
    args = parser.parse_args()
    result = run(file_ref(args.review), args.output, model=args.model, reuse_model=args.reuse_model,
                 previous_plan=args.previous_plan,review=not args.host_only)
    print(json.dumps({k:result[k] for k in ('status','technical_processing_complete','handoff_review_complete','summary')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
