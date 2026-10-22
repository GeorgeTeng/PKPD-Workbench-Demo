"""One independent handoff call with explicit full or selected-record scope."""
import copy
import json


def ledger_schema(schema, due_ids):
    """Expose existing ledger invariants before generation, without choosing outcomes."""
    from . import unresolved_ledger
    result=copy.deepcopy(schema)
    if 'ledger_outcomes' not in result.get('properties',{}):return result
    outcomes=result['properties']['ledger_outcomes'];variants=[]
    for state in ('RESOLVED','LIMITATION_ACCEPTED','ESCALATED','CARRIED'):
        item=copy.deepcopy(outcomes['items']);p=item['properties']
        p['item_id']={'type':'string','enum':due_ids} if due_ids else {'type':'string'}
        p['outcome']={'type':'string','enum':[state]}
        p['limitation']=({'type':'string','minLength':1,'pattern':r'^\s*\S+(?:\s+\S+)+\s*$'}
                         if state=='LIMITATION_ACCEPTED' else {'type':'string','enum':['NONE']})
        p['carried_to']={'type':'string','enum':[x for x in unresolved_ledger.PHASES
            if unresolved_ledger.later(x,'BEFORE_EDA')] if state=='CARRIED' else ['NOT_APPLICABLE']}
        if state=='RESOLVED':p['evidence']['minItems']=1
        variants.append(item)
    outcomes.update(items={'anyOf':variants},minItems=len(due_ids),maxItems=len(due_ids))
    return result


def compact(payload):
    value=copy.deepcopy(payload)
    # Upstream facts were already reviewed. Retain all operative rule content,
    # requirements and conditions; their derivation stays in bound references.
    value['project_rules']=[{k:v for k,v in r.items() if k in {
        'id','kind','text','conditions','exceptions','scope','requirement','stages','context_path'}}
        for r in payload.get('project_rules',[])]
    value['requirements']=[{k:v for k,v in r.items() if k!='evidence'}
                           for r in payload.get('requirements',[])]
    value['coverage']={'reference':(payload.get('upstream_data') or {}).get('coverage'),
                       'scope':'Already reviewed upstream; not reassessed here.'}
    # A routed finding is already present verbatim in the ledger record.
    ledger_records=[i.get('record') for i in payload.get('unresolved_ledger',[])]
    value['findings']=[f for f in payload.get('findings',[]) if f not in ledger_records]
    selected=[];scope=[]
    for dataset in payload['actual_data']:
        records=dataset['records'];quarantine=dataset['quarantine']
        # Check first/last source rows plus every explicitly marked exception.
        # Selection is disclosed; no claim of exhaustive model record review.
        chosen=[r for index,r in enumerate(records) if index in {0,len(records)-1}
                or r.get('duplicate_value_pattern') or r.get('qc_reasons')
                or any(s in {'CENSORED','BLQ','MISSING_CENSORED_OBSERVATION','FORMULA_REQUIRES_REVIEW',
                             'SOURCE_CELL_ERROR'} for s in r.get('value_status',{}).values())
                or any(isinstance(x,str) and ('UNRESOLVED' in x or 'REVIEW' in x)
                       for x in r.get('source_raw_values',{}).values())]
        # Raw cells already carry the preserved values; send derived fields once.
        def row_view(row):
            return {k:v for k,v in row.items() if k not in row.get('source_raw_values',{})
                    and k not in {'source_sha256','source_file_id','source_sheet'}}
        source_bindings=[{k:r[k] for k in ('source_file_id','source_sha256','source_sheet') if k in r}
                         for r in chosen+quarantine]
        source_bindings=list({json.dumps(x,sort_keys=True):x for x in source_bindings}.values())
        selected.append({'id':dataset['id'],'source_bindings':source_bindings,
                         'records':[row_view(r) for r in chosen],
                         'quarantine':[row_view(r) for r in quarantine]})
        if dataset.get('observation_view'):
            view=dataset['observation_view'];chosen_ids={r['record_id'] for r in chosen+quarantine}
            observations=[o for o in view['observations'] if o['record_id'] in chosen_ids]
            selected[-1]['observation_view']={**view,'observations':observations,
                'exposure_events':[e for e in view.get('exposure_events',[]) if e['record_id'] in chosen_ids],
                'supplied_observations':len(observations),
                'unchecked_observations_by_model':len(view['observations'])-len(observations),
                'scope':'Selected source rows; host QC checks all measurement cells and summary rows.'}
        scope.append({'dataset_id':dataset['id'],'total_retained':len(records),'supplied_retained':len(chosen),
            'total_quarantined':len(quarantine),'supplied_quarantined':len(quarantine),
            'unchecked_by_model':len(records)-len(chosen)})
    value['actual_data']=selected
    value['model_record_scope']=scope
    value['operation']='REVIEW_HANDOFF_WITH_HOST_FULL_QC_AND_SELECTED_RECORDS'
    value['datasets']=[{**{k:v for k,v in x.items() if k!='metadata'},'metadata':{
        k:([{a:b for a,b in c.items() if a!='evidence'} for c in v] if k=='columns' else v)
        for k,v in x['metadata'].items() if k!='source_evidence'}} for x in payload['datasets']]
    artifact=value['artifact_manifest_and_bindings']
    artifact['datasets']=[{'id':x['id']} for x in payload['artifact_manifest_and_bindings']['datasets']]
    artifact['binding_scope']='Execution reference binds the complete manifest and each data/metadata file.'
    if 'upstream_assessment' in value:
        value['upstream_assessment']={'scope':'Already reviewed upstream; see bound upstream_data. Not reassessed.'}
    if 'data_dictionary' in value:
        value['data_dictionary']={'scope':'Bound by execution; source column maps and normalized fields are supplied per dataset.'}
    if 'partition_manifest' in value:
        for entry in value['partition_manifest'].get('entries',[]):
            entry.pop('context_paths',None)
    value['metadata_reviews']=[{'dataset_id':x['dataset_id'],'review':{'decision':x['review']['decision']}}
                               for x in payload['metadata_reviews']]
    value['qc_results'].pop('input_bindings',None)
    # Original pending findings remain in program QC evidence/history, but
    # repeated identical execution references need only one authoritative link.
    if 'planning_check_resolutions' in value['qc_results']:
        value['qc_results']['planning_check_resolutions']=[{
            'affected_id':x['finding']['affected_id'],'code':x['finding']['code'],
            'decision':x['decision'],'executor':x['executor']}
            for x in value['qc_results']['planning_check_resolutions']]
    selected_ids={r['record_id'] for d in selected for key in ('records','quarantine') for r in d[key]}
    changes=payload['transformation_logs']['changes']
    supplied_changes=[];seen=set()
    for c in changes:
        if c['record_id'] not in selected_ids: continue
        key=(c['record_id'].split('_R')[0],c.get('field'),c.get('factor'),c.get('action'))
        if c.get('factor')==1 and key in seen: continue
        seen.add(key)
        supplied_changes.append({k:v for k,v in c.items()
            if k not in {'source_sha256','source_file_id','source_sheet','execution_version'}})
    value['transformation_logs']={**payload['transformation_logs'],
        'changes':supplied_changes,'total_changes':len(changes),'supplied_changes':len(supplied_changes),
        'scope':'Selected-record changes; factor-1 mappings have one example per dataset/field. Host QC checks the complete log.'}
    # Stated values and full log/dictionary are retained in the authoritative
    # execution/manifest. Table notes, dose evidence and upstream conditions stay.
    value['stated_values']=[x for x in payload['stated_values']
        if x.get('quantity','').lower().find('dose')>=0 or x.get('unit') in {'mg/kg','mg/kg/day'}]
    value['stated_values_scope']={'total':len(payload['stated_values']),
        'supplied':len(value['stated_values']),'scope':'Dose statements; other stated values remain bound upstream and are not independently reread.'}
    value['instructions'] += (
        ' This is ONE independent package review. Host QC compared all source/output rows. '
        'You receive all table metadata/notes, operative project rules and requirements, open findings, '
        'all quarantined/marked exception rows and first/last retained rows per table. '
        'model_record_scope states exactly what you did not read; do not claim full model record review. '
        'Focus on censoring, dose applicability, definitions, unsupported mappings and next-action restrictions. '
        'Do not repeat host arithmetic, Coverage or Necessity. Original files and full logs remain bound by the manifest.')
    value['instructions'] += ' Due items include overdue earlier-phase items. Routed findings appear once, in unresolved_ledger.record; their absence from findings does not close them.'
    return value


def review(run,payload,schema,verify_bindings,validate_package=None,**options):
    from . import data_agents as d
    from .preparation_views import POLICY, OPERATION_POLICY, OPERATIONS, validate_operation_review
    value=payload
    schema=ledger_schema(schema,payload.get('due_item_ids',[]))
    operation_scoped = payload.get('operation_policy') == OPERATION_POLICY
    if operation_scoped:
        item = schema['properties']['findings']['items']
        item['properties']['affected_operations'] = {'type':'array', 'items':{'type':'string','enum':list(OPERATIONS)}}
        item['required'].append('affected_operations')
    aggregate=payload.get('preparation_policy')==POLICY
    if aggregate:
        # The model judges each scope once. The host derives the redundant
        # package summary; no independent check/finding is altered or discarded.
        schema['properties'].pop('decision')
        schema['required'].remove('decision')
    def with_summary(response):
        result=copy.deepcopy(response)
        if aggregate:
            result['decision']='PASS' if (all(c['decision']=='PASS' for c in result['checks'])
                and all(f['severity']=='FOLLOW_UP' for f in result['findings'])) else 'REVISE'
        return result
    if len(json.dumps(payload,ensure_ascii=False))>300_000:
        value=compact(payload)
    def check(response):
        summarized=with_summary(response)
        d.check_review(summarized,value['expected_check_ids'])
        if operation_scoped:
            validate_operation_review(summarized, [x for x in value['expected_check_ids']
                if x not in {'COMPLETENESS','GLOBAL_HANDOFF_CONSTRAINTS','HANDOFF_SCOPE'}])
        if validate_package: validate_package(summarized)
        return True
    verify_bindings()
    result=d.invoke(run,'DH-handoff',value,schema,check=check,**options)
    verify_bindings()
    # Add host scope after caching the unmodified model response.
    result=with_summary(result)
    if operation_scoped: result['operation_policy'] = OPERATION_POLICY
    if aggregate:result['decision_origin']='HOST_AGGREGATION_OF_INDEPENDENT_CHECKS'
    result['model_record_scope']=value.get('model_record_scope',[
        {'dataset_id':x['dataset_id'],'total_retained':x['retained_records'],
         'supplied_retained':x['retained_records'],'total_quarantined':x['quarantined_records'],
         'supplied_quarantined':x['quarantined_records'],'unchecked_by_model':0}
        for x in payload['supplied_record_scope']])
    result['host_qc_scope']='All permitted source rows; not a scientific adequacy assessment.'
    return result
