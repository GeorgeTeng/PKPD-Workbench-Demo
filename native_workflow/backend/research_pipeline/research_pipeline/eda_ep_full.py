"""Full admitted Data EP intake, deterministic acceptance and source-display bridge.

No extraction, generated code, fitting, automatic model retries or human approval.
The existing three-table TEST bridge remains separate and replayable.
"""
from __future__ import annotations

import copy
import math
import re
import subprocess
from pathlib import Path

from jsonschema import Draft202012Validator
from ctxcomp.io import digest
from . import context_builder as cb, eda_context, eda_ep
from .common import PROJECT, read_json, write_json
from .engine import rscript_path

VERSION = 'EP_FULL_SOURCE_1.0'
HANDLER = PROJECT / 'pkpd_r/eda/full_source_display.R'
OPERATIONS = ['SOURCE_TABLE', 'SOURCE_XY_POINTS']


def require(ok, message):
    if not ok:
        raise ValueError('EP full Data: ' + message)


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def verified(ref):
    require(cb.file_ref(ref['path']) == ref, 'changed bound source: ' + ref['path'])
    return read_json(ref['path'])


def load_inputs(path):
    """Read only existing prepared Data; do not parse the source workbook again."""
    inputs = read_json(path)
    h = inputs['data_handoff']
    require(h['status'] == 'READY_FOR_EDA' and h['allowed_action'] == 'DESCRIPTIVE_EDA',
            'requires an admitted descriptive EDA handoff')
    require(not h['scientific_release'] and not h['fit_ready'], 'unexpected release scope')
    refs = {'ep:existing_inputs': cb.file_ref(path), 'ep:full_adapter': cb.file_ref(__file__),
            'ep:source_handler': cb.file_ref(HANDLER)}
    # Verify all inherited file bindings, including existing upstream decisions.
    def walk(value):
        if isinstance(value, dict):
            if isinstance(value.get('path'), str) and isinstance(value.get('sha256'), str):
                ref = cb.file_ref(value['path'])
                require(ref['sha256'] == value['sha256'], 'changed inherited source')
                refs['source:' + str(len(refs))] = ref
            for child in value.values(): walk(child)
        elif isinstance(value, list):
            for child in value: walk(child)
    walk(h)
    views = {v['dataset_id']: v for v in h['reading_views']}
    readiness = {x['dataset_id']:x for x in h['dataset_action_readiness']}
    catalog, sources = [], {}
    require(len(views) == len(h['files']), 'duplicate/missing reading views')
    for f in h['files']:
        did = f['id']
        require(did in views and did in readiness, 'missing dataset context')
        records = verified(f['data'])['records']
        meta = verified(f['metadata_file'])['metadata']
        require(all(row['record_id'] in views[did]['reading_view_markdown'] for row in records),
                'reading view lacks source record')
        require(len({row['record_id'] for row in records}) == len(records), 'duplicate record IDs')
        columns = []
        col_meta = {c['column']:c for c in meta.get('columns', [])}
        keys = list(dict.fromkeys(k for row in records for k in row['source_cells']))
        for key in keys:
            cell = next(row['source_cells'][key] for row in records if key in row['source_cells'])
            letter = re.match(r'[A-Z]+', cell).group()
            c = col_meta.get(letter, {})
            columns.append({'id':key, 'header':c.get('header', key), 'unit':c.get('unit','NOT_FOUND'),
                'meaning':c.get('meaning','NOT_FOUND'), 'numeric_quantified_rows':sum(
                    row.get('value_status',{}).get(key)=='QUANTIFIED' and
                    number(row.get('source_raw_values',{}).get(key)) for row in records)})
        notes = meta.get('source_table',{}).get('notes','')
        study_ids = sorted(set(re.findall(r'(?m)^\s*(S\d{2}[A-Z]?)\s*\|',notes)))
        item = {'dataset_id':did,'title':views[did]['title'],'group':views[did]['group'],
            'source_item_id':meta['source_item_id'],'study_source_ids':study_ids,
            'role':f['role'],'experimental_unit':meta.get('record_level','NOT_FOUND'),
            'columns':columns,'descriptive_readiness':readiness[did]['actions']['DESCRIPTIVE_EDA'],
            'operation_restrictions':readiness[did].get('operation_restrictions',[])}
        catalog.append(item)
        sources[did] = {'records':records,'metadata':meta,'reading_view':views[did]}
    require(len(catalog) == len(views), 'missing/duplicate file IDs')
    return inputs, catalog, sources, refs


def schema(catalog):
    result = eda_ep.response_schema()
    result['title'] = VERSION
    text = {'type':'string','minLength':1}
    ids = {'type':'string','enum':[x['dataset_id'] for x in catalog]}
    def obj(props):
        return {'type':'object','properties':props,'required':list(props),'additionalProperties':False}
    a = result['properties']['analyses']['items']
    a['properties']['execution'] = obj({
        'operation_id':{'type':'string','enum':['NONE']+OPERATIONS},
        'series':{'type':'array','items':obj({'dataset_id':ids,
            'x':{'type':'string'},'y':{'type':'string'},'group_by':{'type':'string'},
            'x_scale':{'enum':['linear','log10']},'y_scale':{'enum':['linear','log10']}})},
        'limitation':text})
    a['required'].append('execution')
    a['properties']['status'] = {'enum':['PLANNED','DEFERRED','NOT_CALCULABLE']}
    a['properties']['source_refs']['description'] = 'Return []; host derives exact source-item and study IDs from selected dataset IDs.'
    result['properties']['dataset_disposition'] = {'type':'array','items':obj({
        'dataset_id':ids,'use':{'enum':['PLANNED','SUPPORTING','OMITTED']},
        'analysis_ids':{'type':'array','items':text},'reason':text})}
    result['required'].append('dataset_disposition')
    return result


def prepare(existing_inputs):
    inputs, catalog, sources, refs = load_inputs(existing_inputs)
    inputs = copy.deepcopy(inputs)
    inputs['data_handoff'].pop('preview_scope', None)
    inputs['task_context'].pop('execution_registry_note', None)
    inputs['task_context']['dataset_catalog'] = catalog
    inputs['task_context']['implemented_r_operations'] = [
        {'id':'SOURCE_TABLE','status':'IMPLEMENTED','scope':'One unchanged existing source table per series; all rows and original value/status/notes retained. No calculation, joining or aggregation.',
         'parameters':'dataset_id; x/y/group_by must be empty; scales linear.'},
        {'id':'SOURCE_XY_POINTS','status':'IMPLEMENTED','scope':'Separate source-native point panel per series; no lines, inferred identities, error bars, fitting, joins, transformations or aggregation. X/Y must be explicit existing numeric source columns. Nonquantified or nonpositive-log rows stay in the companion source table with exclusion reasons.',
         'parameters':'dataset_id,x,y,group_by (existing source column or empty),x_scale,y_scale. Units copied by host from column metadata; never generated.'}]
    inputs['task_context']['ep_plan_contract'] = {
        'version':VERSION,'mode':'REAL_DATA_EP_PLANNING_ONLY',
        'dataset_disposition':'Account for every admitted table exactly once as PLANNED, SUPPORTING or OMITTED. Give a short scientific reason; a table need not have its own figure. PLANNED links must exactly match analyses using that dataset. SUPPORTING links refer to analyses using its context without plotting it.',
        'limited_data_display':'For limited objective-relevant evidence, propose a scoped display in analyses and link it from dataset_disposition. A deferred figure still counts as a planned use of evidence. Use existing fields for supported observations/axes, status handling, caption limits and executable/deferred status. If the renderer lacks required categorical axes, status marks or layout, keep the needed figure DEFERRED and add a permitted source-table fallback; never drop the data solely because a later matching/modeling action is restricted.',
        'priority':'Use objective and existing requirements to cover relevant animal PK and PD evidence, including supplied in-vitro time-kill evidence where applicable. Consider controls, baseline/endpoint definitions, observed effect range and reported source summaries. Explain other-pathogen background versus target-pathogen evidence.',
        'execution':'Keep scientific need separate from handler availability. SOURCE_TABLE and SOURCE_XY_POINTS are available only within the supplied signatures. Choose NONE with DEFERRED or NOT_CALCULABLE for other proposed displays; do not erase a needed question or force an unsuitable registered display. execution.series identifies the exact native columns. No generated code.',
        'mapping_check':'Before returning, compare every dataset_disposition with analyses.dataset_ids and execution.series. A PLANNED dataset must occur in an analysis and its exact series; derive all disposition analysis_ids from the actual analysis selections. Do not attach Rabbit series to a Mouse-only question. A source-context table explicitly selected for table execution is PLANNED execution, even when its scientific role is supporting context. Describe that role in reason; do not add a nonselecting analysis link to the execution mapping.',
        'scoped_points':'SOURCE_XY_POINTS renders a SEPARATE panel for EACH series and retains the entire source table plus excluded-row reasons. Lack of composite layout, connecting lines or uncertainty bars does not by itself prevent scoped observed-value points. If two explicit numeric time columns conflict, consider separate clearly labeled source-column views; do not select a preferred analysis axis or resolve the conflict. Assess each dataset independently; one unsupported wide table must not defer all usable long-form series. Propose numeric source-native PK, index-response and uncensored time-kill displays when their actual columns support the question. Keep categorical endpoints or unsuitable wide/status/identity structures as explicit table fallbacks with dataset-specific limitations. Do not convert source labels into invented numbers or treat these descriptive points as model readiness.',
        'references':'Use exact dataset and requirement IDs. Return empty source_refs and input_refs.source_ids; the host reconstructs these deterministic links from dataset_catalog. Do not invent study IDs. Reference sections must occur verbatim in the supplied reference.',
        'output':'Use a small number of coherent scientific questions rather than one analysis per table. For each analysis give a concise purpose, exact selections and limitations. For a table set x/y/group_by empty and scales linear. For points each series is one source dataset and explicit column pair; group_by labels groups only, never creates an animal ID. Do not declare output already computed.'}
    # No source selection or Rules changes; only the stage contract and capability context change.
    # All inherited hashes are verified above and again on acceptance. Their
    # exact values are already bound inside existing_inputs; avoid duplicating
    # hundreds of file pointers in the model request. Execution retains them.
    context_refs={k:v for k,v in refs.items() if k.startswith('ep:')}
    return eda_context.prepare('EP-plan',inputs,schema(catalog),input_bindings=context_refs)


def validate(plan, inputs, catalog, sources):
    errors = [str(e.message) for e in Draft202012Validator(schema(catalog)).iter_errors(plan)]
    if errors: return errors
    by_id = {d['dataset_id']:d for d in catalog}
    analyses = {a['analysis_id']:a for a in plan['analyses']}
    if len(analyses)!=len(plan['analyses']): errors.append('duplicate analysis IDs')
    dispositions = {d['dataset_id']:d for d in plan['dataset_disposition']}
    if len(dispositions)!=len(plan['dataset_disposition']) or set(dispositions)!=set(by_id):
        errors.append('every dataset needs exactly one disposition')
    if set(plan['input_refs'].get('dataset_ids',[])) != set(by_id): errors.append('input dataset IDs do not cover admitted scope')
    if plan['input_refs'].get('source_ids'): errors.append('source_ids must be host-derived')
    reqs = {r['id'] for r in inputs['data_handoff']['task_requirements']}
    for a in plan['analyses']:
        aid = a['analysis_id']; selected = a['dataset_ids']; ex = a['execution']
        if len(selected)!=len(set(selected)) or not set(selected)<=set(by_id): errors.append(aid+': invalid dataset selection'); continue
        if not set(a['requirement_ids'])<=reqs: errors.append(aid+': unknown requirement')
        if a['source_refs']: errors.append(aid+': source_refs must be host-derived')
        if ex['operation_id']=='NONE':
            if ex['series'] or a['status']=='PLANNED': errors.append(aid+': unimplemented operation cannot execute')
            continue
        if a['status']!='PLANNED': errors.append(aid+': implemented task needs PLANNED status')
        if {s['dataset_id'] for s in ex['series']} != set(selected): errors.append(aid+': execution series do not cover selected datasets')
        seen = set()
        for s in ex['series']:
            if s['dataset_id'] not in by_id: errors.append(aid+': unknown series'); continue
            key = tuple(s[k] for k in ['dataset_id','x','y','group_by','x_scale','y_scale'])
            if key in seen: errors.append(aid+': duplicate series')
            seen.add(key)
            cat = by_id[s['dataset_id']]
            if cat['descriptive_readiness']['status']!='READY': errors.append(aid+': dataset not ready for descriptive display')
            cols = {c['id']:c for c in cat['columns']}
            if ex['operation_id']=='SOURCE_TABLE':
                if any(s[k] for k in ['x','y','group_by']) or s['x_scale']!='linear' or s['y_scale']!='linear': errors.append(aid+': table cannot transform/select axes')
            else:
                if not s['x'] or not s['y'] or any(s[k] not in cols for k in ['x','y']) or (s['group_by'] and s['group_by'] not in cols):
                    errors.append(aid+': unknown/empty source column'); continue
                if any(cols[s[k]]['numeric_quantified_rows']==0 for k in ['x','y']): errors.append(aid+': axes have no quantified native numbers')
                if not point_rows(sources[s['dataset_id']]['records'],s)['points']: errors.append(aid+': no supported points; propose table instead')
    for did,d in dispositions.items():
        actual = {a['analysis_id'] for a in plan['analyses'] if did in a['dataset_ids']}
        links = set(d['analysis_ids'])
        if len(links)!=len(d['analysis_ids']) or not links<=set(analyses): errors.append(did+': invalid disposition links')
        if actual:
            if d['use']!='PLANNED' or links!=actual: errors.append(did+': selected dataset disposition mismatch')
        elif d['use']=='PLANNED': errors.append(did+': planned without analysis')
        elif d['use']=='SUPPORTING' and not links: errors.append(did+': supporting context needs an analysis')
        elif d['use']=='OMITTED' and links: errors.append(did+': omitted dataset cannot link an analysis')
    return errors


def point_rows(records, series):
    points, excluded = [], []
    for row in records:
        raw = row['source_raw_values']; statuses = row['value_status']
        why = []
        for role in ['x','y']:
            k = series[role]; value = raw.get(k)
            if statuses.get(k) != 'QUANTIFIED' or not number(value): why.append(role+': not a quantified numeric observation')
            elif series[role+'_scale']=='log10' and value<=0: why.append(role+': nonpositive on log axis')
        if why:
            excluded.append({'record_id':row['record_id'],'reasons':why}); continue
        points.append({'record_id':row['record_id'],'x':raw[series['x']],'y':raw[series['y']],
            'group':str(raw.get(series['group_by'],'')) if series['group_by'] else '',
            'source_cells':{k:row['source_cells'][series[k]] for k in ['x','y']}})
    return {'points':points,'excluded':excluded}


def accept(plan_path, bundle, out):
    """Persist validation and freeze an explicit EP->EC request; never execute it."""
    cb.verify_bundle(bundle)
    payload = bundle['request']['payload']
    source_ref = payload['eda_context_bindings']['ep:existing_inputs']
    inputs,catalog,sources,refs = load_inputs(source_ref['path'])
    plan_ref = cb.file_ref(plan_path); plan = read_json(plan_path)
    errors = validate(plan,inputs,catalog,sources)
    reference = payload['scientific_reference']['text']
    for section in plan.get('input_refs',{}).get('reference_sections',[]) + [s for a in plan.get('analyses',[]) for s in a.get('reference_sections',[])]:
        if section not in reference: errors.append('unknown reference section: '+section)
    out=Path(out); out.mkdir(parents=True,exist_ok=False)
    write_json(out/'validation.json',{'status':'REVISE' if errors else 'CONTRACT_VALID',
        'errors':errors,'scientific_review':'REQUIRED','automatic_retries':0})
    if errors: return {'status':'REVISE','errors':errors}
    by_id={x['dataset_id']:x for x in catalog}
    resolved=copy.deepcopy(plan)
    tasks=[]
    for a in resolved['analyses']:
        a['source_refs']=sorted({v for d in a['dataset_ids'] for v in [by_id[d]['source_item_id']]+by_id[d]['study_source_ids']})
        for s in a['execution']['series']:
            source=sources[s['dataset_id']]; cat=by_id[s['dataset_id']]
            tasks.append({'task_id':'TASK%04d'%(len(tasks)+1),'analysis_id':a['analysis_id'],
                'operation_id':a['execution']['operation_id'],'selection':s,
                'dataset_id':s['dataset_id'],'title':cat['title'],'columns':cat['columns'],
                'experimental_unit':cat['experimental_unit'],'records':source['records'],
                'notes':source['reading_view']['reading_view_markdown'].split('**Notes / limits**',1)[-1],
                'context':{'source_refs':a['source_refs'],'reason':a['reason'],
                    'caption_limits':a['display_spec']['caption_limits'],
                    'annotations':a['display_spec']['annotations'],
                    'operation_limitations':a['execution']['limitation']},
                'plot':point_rows(source['records'],s) if a['execution']['operation_id']=='SOURCE_XY_POINTS' else {'points':[],'excluded':[]}})
    resolved['input_refs']['source_ids']=sorted({s for a in resolved['analyses'] for s in a['source_refs']})
    write_json(out/'resolved_plan.json',resolved)
    cb.verify_bundle(bundle); cb.check_refs(refs)
    require(cb.file_ref(plan_path)==plan_ref,'model response changed during acceptance')
    frozen={'version':VERSION,'request_sha256':bundle['request']['request_sha256'],
        'bindings':{**refs,**payload['eda_context_bindings'],'plan':plan_ref},
        'tasks':tasks,'scientific_release':False,'fit_ready':False,'execution_requested':False}
    frozen['content_sha256']=digest(frozen)
    write_json(out/'ec_request.json',frozen)
    return {'status':'CONTRACT_VALID','tasks':len(tasks),'scientific_release':False,
        'handoff':str(out/'ec_request.json'),'execution_started':False}


def verify_request(frozen):
    copy_=copy.deepcopy(frozen); hash_=copy_.pop('content_sha256')
    require(digest(copy_)==hash_,'changed frozen execution request')
    require(frozen['version']==VERSION and not frozen['scientific_release'],'invalid execution scope')
    cb.check_refs(frozen['bindings'])
    for t in frozen['tasks']:
        require(t['operation_id'] in OPERATIONS,'unimplemented execution operation')
        if t['operation_id']=='SOURCE_XY_POINTS':
            require(t['plot']==point_rows(t['records'],t['selection']),'changed point selection/statuses')


def execute_ec(frozen, out):
    """Explicit downstream entry: R preserves source records; no new statistics."""
    verify_request(frozen)
    out=Path(out); out.mkdir(parents=True,exist_ok=False)
    request=write_json(out/'request.json',frozen)
    command=[rscript_path(),'--vanilla',str(HANDLER),'ec',str(request),str(out/'result.json')]
    completed=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=120)
    (out/'r_stderr.txt').write_text(completed.stderr,encoding='utf-8')
    require(completed.returncode==0,'R EC failed: '+completed.stderr)
    actual=read_json(out/'result.json')
    verify_request(frozen)
    require(actual['tasks']==frozen['tasks'],'R changed source records or display contract')
    require(actual['computed_statistics'] is False,'unexpected computation')
    result={'version':VERSION,'request':cb.file_ref(request),'result':cb.file_ref(out/'result.json'),
        'figures_rendered':False,'scientific_release':False}
    write_json(out/'calculation_bundle.json',result)
    return result


def execute_ev(calculation, out, *, display_review=None):
    """Explicit downstream entry: source tables and isolated source-native points."""
    frozen=verified(calculation['request']); verify_request(frozen)
    actual=verified(calculation['result'])
    require(actual['tasks']==frozen['tasks'],'EC rows differ from frozen source contract')
    review_refs = {}
    tasks = frozen['tasks']
    if display_review is not None:
        from .eda_post_ec import final_tasks
        tasks, review_refs = final_tasks(display_review, frozen, actual)
    out=Path(out); out.mkdir(parents=True,exist_ok=False)
    render_input = write_json(out/'render_input.json', {**actual, 'tasks': tasks})
    render_ref = cb.file_ref(render_input)
    completed=subprocess.run([rscript_path(),'--vanilla',str(HANDLER),'ev',str(render_input),str(out)],
        capture_output=True,text=True,encoding='utf-8',timeout=120)
    (out/'r_stderr.txt').write_text(completed.stderr,encoding='utf-8')
    require(completed.returncode==0,'R EV failed: '+completed.stderr)
    verify_request(frozen); cb.check_refs({'ec_result':calculation['result']})
    cb.check_refs({'render_input': render_ref, **review_refs})
    if display_review is not None:
        repeated, repeated_refs = final_tasks(display_review, frozen, actual)
        require(repeated == tasks and repeated_refs == review_refs, 'display review changed during rendering')
    manifest=read_json(out/'manifest.json')
    require([x['task_id'] for x in manifest['artifacts']]==[t['task_id'] for t in tasks],
            'missing or reordered rendered artifacts')
    for item in manifest['artifacts']:
        task=next(t for t in tasks if t['task_id']==item['task_id'])
        require(read_json(out/item['plotted_rows'])==task['plot'],'rendered point provenance differs')
        require((out/item['table']).is_file(),'missing source table')
        if task['operation_id']=='SOURCE_XY_POINTS': require((out/item['image']).read_bytes()[:8]==b'\x89PNG\r\n\x1a\n','invalid image')
    manifest['scientific_release']=False; manifest['visual_review']='PENDING'
    manifest['display_review_bindings'] = review_refs
    manifest['render_input'] = render_ref
    write_json(out/'visualization_bundle.json',manifest)
    return manifest
