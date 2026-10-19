"""Bounded, deterministic cleaning views over immutable source-shaped records.

One measurement cell produces one observation; source column labels never become
animal identifiers. Alternative times and matrix dimensions remain separate.
"""
import copy
import re
from collections import Counter

from .preparation_workflow import numeric, unit_mapping

POLICY = 'DATASET_ACTION_V1'
OPERATION_POLICY = 'OPERATION_SCOPED_V1'
OPERATIONS = {
    'DESCRIPTIVE_EDA': 'Display each source series separately with reported units, flags and time alternatives; no inferred joins or quantitative substitutions.',
    'NORMALIZED_TIME_CONCENTRATION_VIEW': 'Use a unique supported time axis and compatible concentration units; never select alternatives or convert tissue mass to volume implicitly.',
    'TIME_AXIS_SELECTION': 'Choose or reconcile one time axis for dependent calculations.',
    'LONGITUDINAL_JOIN': 'Link measurements as repeated observations of the same animal.',
    'CROSS_TABLE_LINKAGE': 'Link records across source tables or experiments.',
    'CROSS_MATRIX_CONVERSION': 'Convert or pool different biological matrices.',
    'CENSORED_VALUE_CALCULATION': 'Perform limit- or direction-dependent calculations on censored observations.',
    'UNCERTAINTY_WEIGHTING': 'Use dispersion or replicate counts for statistical weighting.',
    'DOSE_RESPONSE_LINKAGE': 'Assign exposure or response records to a dose/regimen.',
    'MIC_WEIGHTED_PTA': 'Use MIC frequencies as weights in PTA.',
    'NCA': 'Compute curve-specific noncompartmental endpoints.',
    'PK_MODELING': 'Construct or fit a PK model.'}
DISPLAY_CONDITIONS = [
    'Keep source series, matrices, units and alternative times separate.',
    'Show censoring/missingness and source conflicts; do not substitute censored values.',
    'No inferred animal IDs, longitudinal joins, dose assignment, pooling, weighting or fitting.']


def finding_scopes(finding, ledger=()):
    target = finding['affected_id']
    entry = next((i for i in ledger if i['id'] == target), None)
    if entry: target = entry.get('record', {}).get('affected_id', entry.get('field', target))
    return set(re.split(r'[,;\s]+', target)) - {''}


def validate_operation_review(response, dataset_ids):
    """Reject unexplained or contradictory decisions before caching a response."""
    from .common import PipelineError
    findings = response['findings']
    for f in findings:
        ops = f.get('affected_operations')
        if not isinstance(ops, list) or any(op not in OPERATIONS for op in ops) or len(ops) != len(set(ops)):
            raise PipelineError('DATA_AGENT_CONTRACT_INVALID', 'Invalid operation scope: ' + f['code'])
        if f['severity'] != 'FOLLOW_UP' and not ops:
            raise PipelineError('DATA_AGENT_CONTRACT_INVALID', 'Restriction needs affected_operations: ' + f['code'])
        if not finding_scopes(f) or not finding_scopes(f) <= set(dataset_ids) | {'DATA'}:
            raise PipelineError('DATA_AGENT_CONTRACT_INVALID', 'Use dataset IDs or DATA for operation-scoped findings.')
    for check in response['checks']:
        if check['id'] not in dataset_ids: continue
        local = [f for f in findings if check['id'] in finding_scopes(f) or 'DATA' in finding_scopes(f)]
        if check['decision'] != 'PASS' and not any(f['affected_operations'] for f in local):
            raise PipelineError('DATA_AGENT_CONTRACT_INVALID', 'Unexplained dataset restriction: ' + check['id'])
        if check['decision'] == 'PASS' and any(f['severity'] != 'FOLLOW_UP' and
                'DESCRIPTIVE_EDA' in f['affected_operations'] for f in local):
            raise PipelineError('DATA_AGENT_CONTRACT_INVALID', 'PASS conflicts with a descriptive EDA restriction: ' + check['id'])


NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
MEASUREMENTS = {'CONCENTRATION', 'BINDING'}
MISSING = {'EMPTY_SLOT', 'NOT_SAMPLED', 'MISSING_CANNULA_BLOCKAGE', 'MISSING_OR_NOT_APPLICABLE', 'MISSING'}


def conversion(column, target):
    """Use an explicit unit or an already source-bound reviewed column unit.

    Contradictory or dimensionally incompatible header/metadata units never fall
    through to the other source. The caller binds the complete reviewed label.
    """
    header = column['header']
    explicit = unit_mapping(header, target)
    unit = column.get('unit')
    reviewed = unit_mapping(unit, target) if unit not in (None, '', 'NOT_FOUND') else None
    expression = re.search(r'(?:\(([^()]*)\)|\[([^\[\]]*)\])$', header)
    if unit not in (None, '', 'NOT_FOUND') and reviewed is None:
        return None
    if expression and explicit is None:
        return None
    if explicit is not None and reviewed is not None and explicit != reviewed:
        return None
    if explicit is not None:
        return explicit
    return reviewed if column.get('evidence') else None


def mapping_factor(mapping, label, column):
    if mapping.get('preparation_policy') != POLICY:
        return unit_mapping(column['source_header'], column['target'])
    matched = [c for c in label['columns'] if c['header'] == column['source_header']]
    return conversion(matched[0], column['target']) if len(matched) == 1 and scalar_eligible(matched[0],column['target']) else None


def typed_value(raw, column, status):
    """Split only explicit scalar/summary/censor syntax. Never impute a value."""
    text = str(raw).strip()
    if status in {'FORMULA_REQUIRES_REVIEW', 'SOURCE_CELL_ERROR'}:
        return {'kind': 'INVALID', 'reason': status}
    censor = re.fullmatch(r'([<>]=?)\s*('+NUMBER+r')', text)
    if censor:
        if numeric(censor[2]) is None or float(censor[2])<0:
            return {'kind':'INVALID','reason':'INVALID_CENSOR_LIMIT'}
        return {'kind': 'CENSORED', 'direction': 'LEFT' if censor[1].startswith('<') else 'RIGHT',
                'operator': censor[1], 'limit': float(censor[2]), 'source_status': status}
    if status == 'BLQ' or text.upper() in {'<LLOQ', 'BLQ'}:
        return {'kind': 'CENSORED', 'direction': 'LEFT', 'limit': None, 'source_status': status}
    if status in {'CENSORED', 'MISSING_CENSORED_OBSERVATION'}:
        # A generic flag establishes censoring, not its direction or limit.
        return {'kind': 'CENSORED', 'direction': 'UNRESOLVED', 'limit': None, 'source_status': status}
    if status in MISSING or raw is None or text in {'', '.'}:
        return {'kind': 'MISSING', 'source_status': status}
    if text.casefold() in {'mean', 'average', 'median', 'total'}:
        return {'kind': 'SUMMARY_LABEL', 'label': text}
    if column.get('meaning')=='BINDING' and text.casefold() in {'bound','unbound','free','total'}:
        return {'kind':'CATEGORY','label':text}
    value = numeric(raw)
    if value is not None:
        if column.get('meaning') in MEASUREMENTS and value < 0:
            return {'kind': 'INVALID', 'reason': 'NEGATIVE_MEASUREMENT'}
        return {'kind': 'SCALAR', 'value': value}
    pair = re.fullmatch(r'('+NUMBER+r')\s*(?:±|\+/-)\s*('+NUMBER+r')', text)
    if pair:
        center, spread = float(pair[1]), float(pair[2])
        if numeric(center) is None or numeric(spread) is None or center < 0 or spread < 0:
            return {'kind': 'INVALID', 'reason': 'INVALID_SUMMARY'}
        definition = ' '.join(column.get('qualifiers', [])).casefold()
        # Do not infer SD from ± itself, table-wide mentions or unrelated columns.
        sd = bool(re.search(r'(?:mean|summary)\s*(?:±|\+/-)\s*sd\b', definition))
        return {'kind': 'SUMMARY', 'value': center, 'spread': spread, 'spread_type': 'SD' if sd else 'UNRESOLVED'}
    return {'kind': 'UNRESOLVED', 'reason': status or 'NONNUMERIC_SOURCE_VALUE'}


def scalar_result(raw, column, status, target, factor):
    parsed = typed_value(raw, column, status)
    if parsed['kind'] == 'SCALAR':
        return parsed['value'] * factor, None
    if parsed['kind'] in {'CENSORED','MISSING','SUMMARY','SUMMARY_LABEL'}:
        return None, None  # Preserved and typed in a separate observation view.
    return None, parsed.get('reason', 'UNRESOLVED_SOURCE_VALUE')


def time_kind(column):
    text = (column['header'] + ' ' + ' '.join(column.get('qualifiers', []))).casefold()
    if 'interval' in text or 'duration' in text: return 'INTERVAL'
    if 'pixel' in column['header'].casefold(): return 'DIGITIZED'
    if 'nominal' in text: return 'NOMINAL'
    if 'actual' in text: return 'ACTUAL'
    return 'SOURCE_REPORTED_UNSPECIFIED'


def scalar_eligible(column, target):
    if target=='time_h':return time_kind(column)!='INTERVAL'
    return not any('nominal exposure' in q.casefold() for q in column.get('qualifiers',[]))


def event_layout(metadata):
    """Existing event-table convention, only when its source states the roles."""
    fields=set(metadata['source_table']['column_map'].values())
    notes=metadata['source_table'].get('notes','').casefold()
    return ({'ID','AMT','AMT_CMT','TIME','Y','CENS'}<=fields
        and 'amt_cmt=2 rows carry nominal exposure amt (mg/l)' in notes
        and 'observation rows use amt_cmt=1' in notes
        and 'cens=1 flags censored y' in notes)


def build_view(metadata, records):
    fields = metadata['source_table']['column_map']
    columns = {c['header']: c for c in metadata['columns']}
    event_table=event_layout(metadata)
    measurement_fields = [k for k,h in fields.items() if
        (h=='Y' if event_table else columns.get(h,{}).get('meaning') in MEASUREMENTS)]
    time_fields = [k for k,h in fields.items() if columns.get(h,{}).get('meaning') == 'TIME']
    summary_fields=[k for k,h in fields.items() if columns.get(h,{}).get('meaning')=='GROUP_OR_TREATMENT'
                    and conversion(columns[h],'concentration_mg_L') is not None]
    observations, summaries, events = [], [], []
    for record in sorted(records, key=lambda r: r['source_row']):
        typed = {k: typed_value(record['source_raw_values'][k], columns[fields[k]], record['value_status'][k])
                 for k in measurement_fields + time_fields + summary_fields}
        if event_table:
            key_by_header={h:k for k,h in fields.items()}
            flag=numeric(record['source_raw_values'][key_by_header['AMT_CMT']])
            if flag!=1:
                exposure_key=key_by_header['AMT'];id_key=key_by_header['ID']
                events.append({'record_id':record['record_id'],'source_row':record['source_row'],
                    **{a:record[a] for a in ('source_file_id','source_sha256','source_sheet')},
                    'source_cell':record['source_cells'][exposure_key],
                    'source':metadata['source_item_id']+'::'+record['source_cells'][exposure_key]+'::'+record['record_id'],
                    'kind':'NOMINAL_EXPOSURE_EVENT' if flag==2 else 'UNRESOLVED_EVENT',
                    'source_group':record['source_raw_values'][id_key],
                    'raw':record['source_raw_values'][exposure_key],
                    'qualifiers':copy.deepcopy(columns['AMT'].get('qualifiers',[])),
                    'typed_value':typed_value(record['source_raw_values'][exposure_key],columns['AMT'],record['value_status'][exposure_key]),
                    'unit':columns['AMT']['unit'], 'response_imputed':False})
                continue
        if any(t['kind'] == 'SUMMARY_LABEL' for t in typed.values()):
            summaries.append({'record_id':record['record_id'], 'source_row':record['source_row'],
                'labels':{record['source_cells'][k]:t['label'] for k,t in typed.items() if t['kind']=='SUMMARY_LABEL'},
                'reason':'Source summary row retained separately from measurement observations.'})
            continue
        times=[]
        for k in time_fields:
            col=columns[fields[k]];factor=conversion(col,'time_h');parsed=typed[k]
            times.append({'source_header':fields[k], 'source_cell':record['source_cells'][k],
                'raw':record['source_raw_values'][k], 'kind':time_kind(col), 'unit':col.get('unit'),
                'time_h':parsed['value']*factor if parsed['kind']=='SCALAR' and factor is not None else None})
        # More than one source time coordinate remains a choice for a named action.
        canonical = times[0]['time_h'] if len(times)==1 and times[0]['kind']!='INTERVAL' else None
        for k in measurement_fields:
            col=columns[fields[k]];parsed=typed[k]
            factor=conversion(col,'concentration_mg_L') if col['meaning']=='CONCENTRATION' else None
            normalized=None
            if factor is not None and parsed['kind'] in {'SCALAR','SUMMARY'}:
                normalized={'value':parsed['value']*factor,'unit':'mg/L','factor':factor}
                if parsed['kind']=='SUMMARY':
                    normalized.update(spread=parsed['spread']*factor,spread_type=parsed['spread_type'])
            elif factor is not None and parsed['kind']=='CENSORED':
                normalized={'limit':parsed['limit']*factor if parsed['limit'] is not None else None,
                            'unit':'mg/L','factor':factor}
            observations.append({'observation_id':record['record_id']+'_'+k,
                'source':metadata['source_item_id']+'::'+record['source_sheet']+'!'+record['source_cells'][k]+'::'+record['record_id'],
                'record_id':record['record_id'], 'source_item_id':metadata['source_item_id'],
                **{a:record[a] for a in ('source_file_id','source_sha256','source_sheet','source_row')},
                'source_cell':record['source_cells'][k], 'source_field':k, 'source_header':fields[k],
                'raw':record['source_raw_values'][k], 'meaning':col['meaning'], 'unit':col.get('unit'),
                'qualifiers':copy.deepcopy(col.get('qualifiers',[])), 'typed_value':parsed,
                'normalized':normalized,'times':copy.deepcopy(times),'canonical_time_h':canonical,
                'source_series_label':fields[k], 'animal_id':None, 'longitudinal_join_allowed':False,
                'record_category':metadata.get('record_category','NOT_FOUND'),
                'source_qc_reasons':copy.deepcopy(record.get('qc_reasons',[]))})
            if event_table:
                id_key=next(k for k,h in fields.items() if h=='ID')
                observations[-1]['source_group']=record['source_raw_values'][id_key]
                observations[-1]['event_link_policy']='SOURCE_TABLE_AND_ID_ONLY; no inferred replicate identity or cross-table join.'
    restrictions=[]
    if len(time_fields)>1:restrictions.append('TIME_AXIS_SELECTION_REQUIRED')
    if any(o['normalized'] is None and o['meaning']=='CONCENTRATION' and o['typed_value']['kind'] in {'SCALAR','SUMMARY'} for o in observations):
        restrictions.append('VOLUME_CONCENTRATION_NORMALIZATION_NOT_APPLICABLE_TO_ALL_SERIES')
    if any(o['typed_value']['kind']=='CENSORED' and o['typed_value']['limit'] is None for o in observations):
        restrictions.append('CENSORED_LIMIT_UNRESOLVED')
    if any(o['typed_value']['kind']=='CENSORED' and o['typed_value']['direction']=='UNRESOLVED' for o in observations):
        restrictions.append('CENSORING_DIRECTION_UNRESOLVED')
    if any(o['typed_value']['kind']=='SUMMARY' and o['typed_value']['spread_type']=='UNRESOLVED' for o in observations):
        restrictions.append('SUMMARY_UNCERTAINTY_TYPE_UNRESOLVED')
    if any(e['kind']=='UNRESOLVED_EVENT' for e in events):restrictions.append('EVENT_ROLE_UNRESOLVED')
    return {'schema_version':POLICY, 'source_item_id':metadata['source_item_id'],
        'observations':observations, 'summary_rows':summaries,'exposure_events':events,
        'operation_restrictions':restrictions,
        'counts':{'source_records':len(records),'observation_cells':len(observations),
                  'summary_rows':len(summaries),'exposure_events':len(events),
                  'by_kind':dict(Counter(o['typed_value']['kind'] for o in observations))},
        'restrictions':['No inferred animal IDs or cross-time joins.',
                        'Multiple time coordinates require an explicit downstream action choice.',
                        'Different source series, matrices and units must not be pooled.',
                        'Censored limits may be unknown; no imputation performed.']}


def verify_view(view, metadata, records):
    """Reconstruct against QC-checked raw cells; reject added, lost or changed cells."""
    errors=[]
    expected=build_view(metadata,records)
    if view != expected: errors.append('Observation view differs from source-bound operators or cell accounting.')
    ids=[o['observation_id'] for o in view.get('observations',[])]
    if len(ids)!=len(set(ids)): errors.append('Duplicate observation identity.')
    return errors


def action_readiness(datasets, qc, metadata_reviews, response, findings, ledger=()):
    """Scope known dataset findings locally; unscoped integrity issues stay global."""
    qc_by={r['dataset_id']:r for r in qc['datasets']}
    meta_by={r['dataset_id']:r['review'] for r in metadata_reviews}
    checks={c['id']:c for c in response['checks']}
    known={x for d in datasets for x in (d['id'],d['metadata']['source_item_id'])}
    scoped = response.get('operation_policy') == OPERATION_POLICY
    def blocks(finding, operation):
        if finding['severity'] == 'FOLLOW_UP': return False
        if scoped and 'affected_operations' in finding:
            return operation in finding['affected_operations']
        # Legacy/current-phase issues without a typed scope fail closed. Their
        # original records stay unchanged; later-phase issues are carried.
        return finding['required_by'] in {'BEFORE_QC','BEFORE_EDA'}
    due=[f for f in findings if blocks(f, 'DESCRIPTIVE_EDA')]
    ledger_by={i['id']:i for i in ledger}
    def scopes(finding):
        target=finding['affected_id']
        if target in ledger_by:
            entry=ledger_by[target]
            target=entry.get('record',{}).get('affected_id',entry.get('field',target))
        tokens=set(re.split(r'[,;\s]+',target))
        # Unknown IDs in a compound scope cannot be silently dropped.
        return tokens if tokens and tokens<=known else set()
    global_reasons=[f['code']+': '+f['reason'] for f in due if not scopes(f)]
    if qc.get('errors'): global_reasons.append('Package integrity check failed.')
    scope_check='GLOBAL_HANDOFF_CONSTRAINTS' if 'GLOBAL_HANDOFF_CONSTRAINTS' in checks else 'HANDOFF_SCOPE'
    for key in ('COMPLETENESS',scope_check):
        if checks.get(key,{}).get('decision')!='PASS':global_reasons.append(key+' independent check did not pass.')
    # An unexplained overall rejection cannot silently be ignored.
    if response['decision']!='PASS' and not findings and all(c['decision']=='PASS' for c in checks.values()):
        global_reasons.append('Independent handoff rejected without a local scope.')
    result=[]
    for d in datasets:
        identifier=d['id'];source=d['metadata']['source_item_id']
        local=[f['code']+': '+f['reason'] for f in due if scopes(f)&{identifier,source}]
        integrity=[]
        if qc_by.get(identifier,{}).get('decision')!='PASS':integrity.append('Dataset program QC did not pass.')
        if meta_by.get(identifier,{}).get('decision')!='PASS':integrity.append('Dataset metadata validation did not pass.')
        reasons=global_reasons+integrity+local
        if checks.get(identifier,{}).get('decision')!='PASS':
            supported = scoped and any(scopes(f)&{identifier,source} and f.get('affected_operations') for f in findings)
            if not supported: reasons.append('Dataset independent handoff check lacks an explicit operation scope.')
        view_restrictions=d.get('observation_restrictions',[])
        typed_reasons=list(reasons)
        if d.get('role')!='PK_OBSERVATIONS':typed_reasons.append('Not a PK observation dataset.')
        if not d.get('observation_summary',{}).get('observation_cells'):typed_reasons.append('No typed observation cells.')
        if not scoped: typed_reasons.extend(view_restrictions)
        if scoped:
            typed_reasons += [f['code']+': '+f['reason'] for f in findings
                if blocks(f, 'NORMALIZED_TIME_CONCENTRATION_VIEW') and
                (not scopes(f) or scopes(f)&{identifier,source})]
            typed_reasons += [x for x in view_restrictions if x in {
                'TIME_AXIS_SELECTION_REQUIRED', 'VOLUME_CONCENTRATION_NORMALIZATION_NOT_APPLICABLE_TO_ALL_SERIES',
                'EVENT_ROLE_UNRESOLVED'}]
        if not d.get('metadata',{}).get('normalized_fields',{}).get('time_h'):
            typed_reasons.append('No unique source-supported scalar time mapping.')
        result.append({'dataset_id':identifier,'source_item_id':source,'actions':{
            'SOURCE_INSPECTION':{'status':'RESTRICTED' if integrity or qc.get('errors') else 'READY',
                                 'reasons':integrity+(['Package integrity check failed.'] if qc.get('errors') else [])},
            'DESCRIPTIVE_EDA':{'status':'RESTRICTED' if reasons else 'READY','reasons':reasons,
                'conditions':DISPLAY_CONDITIONS if scoped else []},
            'NORMALIZED_TIME_CONCENTRATION_VIEW':{'status':'RESTRICTED' if typed_reasons else 'READY',
                'reasons':typed_reasons, 'conditions':['Keep source series and units separate; no inferred longitudinal joins.']},
            'NCA':{'status':'RESTRICTED','reasons':['Requires curve-specific sampling, time-axis, censoring and endpoint assessment.']},
            'PK_MODELING':{'status':'RESTRICTED','reasons':['Requires independent scientific adequacy and model-specific inputs.']}}})
        if scoped:
            restricted = {}
            host_ops = {
                'TIME_AXIS_SELECTION_REQUIRED':'TIME_AXIS_SELECTION',
                'VOLUME_CONCENTRATION_NORMALIZATION_NOT_APPLICABLE_TO_ALL_SERIES':'CROSS_MATRIX_CONVERSION',
                'CENSORED_LIMIT_UNRESOLVED':'CENSORED_VALUE_CALCULATION',
                'CENSORING_DIRECTION_UNRESOLVED':'CENSORED_VALUE_CALCULATION',
                'SUMMARY_UNCERTAINTY_TYPE_UNRESOLVED':'UNCERTAINTY_WEIGHTING',
                'EVENT_ROLE_UNRESOLVED':'DOSE_RESPONSE_LINKAGE'}
            for restriction in view_restrictions:
                if restriction in host_ops: restricted.setdefault(host_ops[restriction], []).append(restriction)
            for f in findings:
                if scopes(f) and not scopes(f)&{identifier,source}: continue
                for operation in f.get('affected_operations', []):
                    if f['severity'] != 'FOLLOW_UP': restricted.setdefault(operation, []).append(f['code']+': '+f['reason'])
            result[-1]['operation_restrictions'] = [
                {'operation':op, 'reasons':list(dict.fromkeys(why))} for op,why in sorted(restricted.items())]
            result[-1]['operation_policy'] = OPERATION_POLICY
            result[-1]['authorized_action'] = 'DESCRIPTIVE_EDA' if not reasons else None
            result[-1]['other_operations_authorized'] = False
    return result
