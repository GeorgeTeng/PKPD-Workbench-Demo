"""Question-driven EDA over an admitted Data handoff and immutable completed EC.

One EP call, one bounded post-EC decision, deterministic R, one EI summary and disjoint ER batches.
The legacy adapter remains replayable; this adapter uses the richer typed registry.
"""
from __future__ import annotations
import copy, html, json, math, subprocess, time
from pathlib import Path
from collections import Counter
from jsonschema import Draft202012Validator
from ctxcomp import providers
from ctxcomp.io import digest
from . import context_builder as cb, eda_context, eda_ep_full as legacy
from .common import PROJECT, read_json, write_json
from .context_linear import LinearSession
from .eda_workflow import strict_schema,compact_grid,expand_grid
from .engine import rscript_path
from . import eda_display_catalog_v5 as display_catalog
from . import eda_display_catalog as base_display_catalog
from . import eda_pk_scales, eda_axis_scales, eda_plot_policy, eda_quality_checks_v3 as quality
from . import eda_dataset_routes as dataset_routes

HERE=Path(legacy.__file__).resolve().parent
CAPABILITIES=HERE/'resources/eda/question_capabilities.v1.json'
HANDLER=Path(__file__).parent/'resources/eda/question_displays.v2.R'
QUESTIONS=[
 ('Q_PK_SHAPE','What observed animal concentration-time patterns and sampling windows must modeling explain?'),
 ('Q_PK_VARIABILITY','What variability is actually observed, and what is unavailable at the supplied record level?'),
 ('Q_PD_EFFECT','What terminal PD effect range, controls and strain differences must modeling explain?'),
 ('Q_INDEX','What within-panel exposure/index-response information is available, and what comparisons remain unsupported?'),
 ('Q_TIMEKILL','What killing, suppression and regrowth patterns are observed over time?'),
 ('Q_CONTEXT','Which contextual observations materially qualify these modeling questions?')]

def require(ok,message):
    if not ok:raise ValueError('Question EDA: '+message)

def obj(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
TEXT={'type':'string','minLength':1}
TEXTS={'type':'array','items':TEXT}
def enum(values):return {'type':'string','enum':list(values)}

def disposition_schema(datasets):
    columns=sorted({c['id'] for t in datasets.values() for c in t['columns']
                    if c.get('meaning') in {'CONCENTRATION','RESPONSE','MIC','BINDING','DOSE'}}) if isinstance(datasets,dict) else []
    unshown={'type':'array','items':enum(columns) if columns else TEXT,
             'description':'Exact column IDs only from dataset_display_inventory.display_fields minus selected source_fields. No labels, time columns, non-display fields, prose, unavailable observations or ID-plus-explanation strings. Put explanation in reason.'}
    return {'type':'array','minItems':len(datasets),'maxItems':len(datasets),'items':obj({
        'dataset_id':enum(datasets),'status':enum(['DISPLAYED','CONTEXT_ONLY','NEEDS_CAPABILITY']),
        'reason':TEXT,
        'handoff':obj({'destinations':{'type':'array','items':enum(['PK','PD']),'minItems':1,'maxItems':2,'uniqueItems':True},
            'role':enum(['OBSERVATIONS','CONTEXT','SUPPLEMENTARY']), 'purpose':TEXT, 'pending_checks':TEXTS})})}

def plan_schema(candidates,datasets):
    view=obj({'view_id':enum(candidates),'purpose':TEXT,'scale_rationale':TEXT,'complementary_value':TEXT})
    question=obj({'analysis_id':enum(q[0] for q in QUESTIONS),'question':TEXT,'objective_link':TEXT,
        'understanding_needed':TEXT,'next_modeling_action':TEXT,'dataset_ids':{'type':'array','items':enum(datasets)},
        'views':{'type':'array','items':view},'record_level_and_grouping':TEXT,'uncertainty_and_status':TEXT,
        'status':enum(['PLANNED','PARTIAL','DEFERRED','NOT_APPLICABLE']),'reason':TEXT,'remaining_unknowns':TEXTS,
        'modeling_preparation':obj({'usable_now':TEXT,'preferred_action':TEXT,'why':TEXT,
            'conditional_alternatives':TEXTS,'essential_clarifications':TEXTS})})
    return obj({'version':enum(['QUESTION_DRIVEN_2']),'input_refs':obj({'dataset_ids':{'type':'array','items':enum(datasets)}}),
        'objective':TEXT,'analyses':{'type':'array','items':question,'minItems':len(QUESTIONS),'maxItems':len(QUESTIONS)},
        'not_planned':TEXTS,'open_items':TEXTS,'dataset_dispositions':disposition_schema(datasets)})

def final_schema(candidates,datasets):
    return obj({'version':enum(['QUESTION_FINAL_2']),'summary':TEXT,
        'task_decisions':plan_schema(candidates,datasets)['properties']['analyses'],'open_items':TEXTS,'dataset_dispositions':disposition_schema(datasets)})

def findings_schema(datasets=None,candidates=None):
    artifacts=TEXTS if datasets is None else {'type':'array','items':enum(list(datasets)+list(candidates or [])+['EC_REUSED','SOURCE_TABLES'])}
    records=TEXTS if datasets is None else {'type':'array','items':enum(sorted({r['record_id'] for t in datasets.values() for r in t['records']}))}
    finding=obj({'finding_id':TEXT,'analysis_ids':{'type':'array','items':enum(q[0] for q in QUESTIONS)},
        'artifact_refs':artifacts,'record_scope':records,'observation':TEXT,'interpretation_if_useful':{'type':'string'},
        'alternative_if_interpretation':{'type':'string'},'downstream_implication':TEXT,
        'visual_support':obj({'status':enum(['OBSERVED','NOT_ASSESSED','NON_GRAPHICAL']),
            'figure_ids':{'type':'array','items':enum(list(candidates or []))} if candidates else TEXTS,
            'features':TEXT,'limitations':TEXTS}),
        'anomaly_assessment':obj({'status':enum(['CANDIDATES','NONE_IDENTIFIED_IN_REVIEWED_SCOPE','NOT_ASSESSED']),
            'record_ids':copy.deepcopy(records),'observation':TEXT,'possible_explanations':TEXTS,
            'recommended_action':TEXT,'affected_analysis':TEXT,'data_changed':{'const':False}})})
    finding['properties']['visual_support']['properties']['element_claims']={'type':'array','items':obj({
        'figure_id':enum(candidates) if candidates else TEXT,
        'elements':{'type':'array','minItems':1,'items':enum(quality.ELEMENTS)}})}
    finding['properties']['visual_support']['required'].append('element_claims')
    finding['properties']['analysis_ids']['minItems']=1
    finding['properties']['artifact_refs']['minItems']=1
    anomaly=finding['properties']['anomaly_assessment']
    candidate=copy.deepcopy(anomaly)
    candidate['properties']['status']=enum(['CANDIDATES'])
    candidate['properties']['record_ids']['minItems']=1
    candidate['properties']['possible_explanations']['minItems']=1
    other_anomaly=copy.deepcopy(anomaly)
    other_anomaly['properties']['status']=enum(['NONE_IDENTIFIED_IN_REVIEWED_SCOPE','NOT_ASSESSED'])
    finding['properties']['anomaly_assessment']={'anyOf':[candidate,other_anomaly]}
    # Enumerate conditional cases in the strict wire schema as well as host checks.
    variants=[]
    for observed in [True,False]:
        for interpreted in [True,False]:
            variant=copy.deepcopy(finding);p=variant['properties']
            visual=p['visual_support']['properties']
            if observed:
                p['record_scope']['minItems']=1
                visual['status']=enum(['OBSERVED']);visual['figure_ids']['minItems']=1
            else:visual['status']=enum(['NOT_ASSESSED','NON_GRAPHICAL'])
            if interpreted:
                nonblank={'type':'string','minLength':1,'pattern':r'\S'}
                p['interpretation_if_useful']=copy.deepcopy(nonblank)
                p['alternative_if_interpretation']=copy.deepcopy(nonblank)
            else:p['interpretation_if_useful']=enum([''])
            variants.append(variant)
    return obj({'version':enum(['QUESTION_FINDINGS_3']),'input_refs':TEXTS,
        'findings':{'type':'array','items':{'anyOf':variants}},'limitations':TEXTS,'open_items':TEXTS,
        'figure_checks':{'type':'array','items':obj({'figure_id':enum(candidates) if candidates else TEXT,
            'inspection':enum(['INSPECTED','NOT_ASSESSED']),'note':TEXT})}})


def review_schema():
    issue=obj({'issue_id':TEXT,'affected_artifact':TEXT,'evidence':TEXT,'consequence':TEXT,
        'correction_owner':enum(['EP','EC','EV','EI','DATA','HUMAN']),'smallest_correction':TEXT})
    return obj({'version':enum(['QUESTION_REVIEW_1']),'reviewed_refs':TEXTS,
        'decision':enum(['PASS','REVISE','NEEDS_REVIEW']),'review_scope':TEXT,
        'issues':{'type':'array','items':issue},'unreviewed_items':TEXTS,
        'quality_checks':obj({k:enum(['PASS','REVISE','NOT_ASSESSED']) for k in ['source_semantics','readability','figure_text_stage_consistency']})})

def candidate_datasets(spec):
    return sorted({s['dataset_id'] for p in spec['panels'] for s in p.get('series',[p])})

def intake(inputs_path,completed_run,catalog_path):
    inputs,catalog,sources,source_refs=legacy.load_inputs(inputs_path)
    from .eda_dh_adapter import bind_tree
    for f in inputs['data_handoff']['files']:
        bind_tree(legacy.verified(f['metadata_file']),source_refs)
    views=read_json(catalog_path)
    from .eda_dh_adapter import VERSION as SNAPSHOT_VERSION, project_tables
    if views.get('version')==SNAPSHOT_VERSION:
        require(completed_run is None,'DH snapshot must not impersonate a completed EC')
        cb.check_refs({'snapshot':views['input_ref']})
        result=read_json(views['input_ref']['path'])
        require(result.get('version')==SNAPSHOT_VERSION and result.get('computed_statistics') is False,'invalid descriptive snapshot')
        cb.check_refs(result['bindings'])
        expected=project_tables(catalog,sources,{f['id']:f for f in inputs['data_handoff']['files']})
        require(result['tasks']==expected,'snapshot differs from admitted Data semantics or records')
        tables={t['dataset_id']:t for t in result['tasks']}
        completed_bindings={'completed_ec_result':views['input_ref'],'source_snapshot':views['input_ref'],**result['bindings']}
    else:
        run=Path(completed_run)
        receipt=read_json(run/'EC.receipt.json');cb.check_refs(receipt['outputs'])
        calculation=read_json(run/'EC/calculation_bundle.json')
        cb.check_refs({'result':calculation['result'],'request':calculation['request']})
        result=read_json(calculation['result']['path'])
        require(result.get('computed_statistics') is False,'this reuse adapter requires source-preserving EC')
        tables={}
        for task in result['tasks']:
            did=task['dataset_id']
            require(did in sources and task['records']==sources[did]['records'],'EC differs from admitted Data: '+did)
            if did in tables:require(tables[did]['records']==task['records'],'duplicate task differs')
            tables[did]=copy.deepcopy(task)
        require(set(tables)==set(sources),'completed EC does not cover current admitted scope')
        cb.check_refs({'catalog_source':views['input_ref']})
        old=read_json(views['input_ref']['path'])
        require(all(t['records']==tables[t['dataset_id']]['records'] for t in old['tasks']),'candidate source changed')
        # Add Data role/column metadata on projection, without changing source records.
        projected={t['dataset_id']:t for t in project_tables(catalog,sources,{f['id']:f for f in inputs['data_handoff']['files']})}
        for did,t in tables.items():
            t['metadata']=projected[did]['metadata']
            for col in t['columns']:
                matched=next(c for c in projected[did]['columns'] if c['id']==col['id'])
                col.update({k:matched[k] for k in ('role','time_role','time_origin') if k in matched})
        completed_bindings={'completed_ec_receipt':cb.file_ref(run/'EC.receipt.json'),'completed_ec_result':calculation['result']}
    caps=read_json(CAPABILITIES);kinds={x['kind'] for x in caps['templates']}
    candidates={v['id']:v for v in views['plots']}
    require(len(candidates)==len(views['plots']),'duplicate candidate ID')
    for v in candidates.values():
        require(v['kind'] in kinds,'unknown R template')
        require(set(candidate_datasets(v))<=set(tables),'unknown candidate dataset')
        require(v['y_scale'] in {'linear','log10'},'unknown scale')
        for panel in v['panels']:
            for s in panel.get('series',[panel]):
                columns={c['id'] for c in tables[s['dataset_id']]['columns']}
                for k in ('x','y','group','facet','error','n','baseline','unit_column','group_column'):
                    if s.get(k):require(s[k] in columns,'unknown candidate column '+k)
                if 'value_columns' in s:require(set(s['value_columns'])<=columns,'unknown response columns')
    match_report=[]
    candidates=eda_plot_policy.finalize(eda_pk_scales.defaults(eda_plot_policy.normalize(display_catalog.augment(candidates,tables,match_report=match_report),tables),tables))
    views['match_report']=match_report
    candidates=quality.prepare(candidates,tables)
    candidates=eda_axis_scales.prepare(candidates,tables)
    eda_plot_policy.validate(list(candidates.values()),tables)
    bindings={'input':cb.file_ref(inputs_path),**completed_bindings,'catalog':cb.file_ref(catalog_path),
        'dh_adapter_code':cb.file_ref(Path(__file__).with_name('eda_dh_adapter.py')),
        'rules':cb.file_ref(eda_context.PACK),
        'review_context_code':cb.file_ref(Path(__file__).with_name('eda_review_context.py')),
        'review_batches_code':cb.file_ref(Path(__file__).with_name('eda_review_batches.py')),
        'plan_accounting_code':cb.file_ref(Path(__file__).with_name('eda_plan_accounting.py')),
        'field_accounting_code':cb.file_ref(Path(__file__).with_name('eda_coverage_accounting.py')),
        'quality_code':cb.file_ref(quality.__file__),'table_block_contract':cb.file_ref(quality.CONFIG),'capabilities':cb.file_ref(CAPABILITIES),'renderer':cb.file_ref(HANDLER),'adapter':cb.file_ref(__file__),
        'source_recipes':cb.file_ref(display_catalog.RECIPES),'source_renderer':cb.file_ref(display_catalog.SOURCE_HANDLER),
        'plot_style':cb.file_ref(PROJECT/'pkpd_r/eda/plot_style.R'),
        'study_annotations_code':cb.file_ref(HERE/'eda_study_annotations.py'),
        'study_annotations_binding':cb.file_ref(HERE/'resources/eda/study_annotations.v1.json'),
        'pk_scale_policy':cb.file_ref(eda_pk_scales.__file__),
        'axis_scale_policy':cb.file_ref(eda_axis_scales.__file__),
        'verified_axis_scales':cb.file_ref(eda_axis_scales.CONFIG),
        'plot_policy_code':cb.file_ref(eda_plot_policy.__file__),'plot_policy_config':cb.file_ref(eda_plot_policy.CONFIG),
        'display_catalog_code':cb.file_ref(display_catalog.__file__),
        'base_display_catalog_code':cb.file_ref(base_display_catalog.__file__),
        'source_projection_code':cb.file_ref(Path(base_display_catalog.__file__).with_name('eda_source_views.py'))}
    return inputs,tables,candidates,views,caps,bindings,source_refs

def question_context(inputs,tables,candidates,caps,match_report=None):
    tc=copy.deepcopy(inputs['task_context'])
    tc.pop('plot_method_library',None);tc.pop('analysis_method_library',None)
    tc['implemented_r_operations']=caps['templates']
    tc['execution_registry_note']='The current question_displays R registry is implemented and source-bound to the supplied candidate views. Select those views for execution where scientifically applicable. The original context-only preview and its empty test registry are historical; they do not describe this run. Scientific Data permissions and unresolved limits remain unchanged.'
    tc['question_driven_contract']={
      'version':'QUESTION_DRIVEN_2','objective':'What must we understand before modeling?',
      'priority_questions':[{'id':i,'question':q} for i,q in QUESTIONS],
      'instruction':'Return each priority question once. Select immutable candidate views only when they add information; justify scale explicitly. Every selected view is a request to render it now under the implemented registry. A view may support multiple questions. PARTIAL can select usable views and retain unanswered aspects. DEFERRED has no executable views; name the unavailable representation in remaining_unknowns. Do not declare a question answered from renderer success.',
      'candidate_views':[{**display_catalog.brief(v),'dataset_ids':candidate_datasets(v),'axis_scales':v['axis_scales']} for v in candidates.values()],
      'axis_scale_contract':eda_axis_scales.POLICY,
      'dataset_display_inventory':display_catalog.inventory(tables,candidates),
      'recipe_match_report':copy.deepcopy(match_report or []),
      'pk_scale_policy':eda_pk_scales.POLICY,
      'pk_scale_requirements':eda_pk_scales.requirements(candidates,tables),
      'presentation_policy':eda_plot_policy.POLICY_TEXT,
      'dataset_handoff_contract':dataset_routes.INSTRUCTION,
      'three_quality_checks':quality.INSTRUCTION,
      'coverage_contract':'Return dataset_dispositions for every admitted dataset exactly once in EP and EP-finalize. DISPLAYED requires a selected view; CONTEXT_ONLY requires a scoped reason; NEEDS_CAPABILITY must identify a genuinely unavailable representation. The host computes unshown_columns exactly from each dataset display_fields minus selected source_fields. Do not generate field-difference lists. The host does not rewrite your scientific reasons or roles. On unchanged EC, mandatory primary PK views already validated in EP cannot be silently dropped: the host retains those exact parent selections and discloses each retention to EI/ER. A DISPLAYED dataset with a missing view link retains its unique validated parent view on unchanged EC. Source dataset references are derived from selected views. Unshown fields remain explicit for EI/ER; a rendered figure does not prove complete data coverage.',
      'completed_ec_reuse':'Source records are already materialized and verified, from the declared completed EC or DH source snapshot. No new calculations requested; reuse exact records.',
      'evidence_use':'Use all relevant admitted data in reasoning. A candidate display catalog is not the entire evidence scope. Tables without a supported figure remain visible with notes. Do not claim a missing candidate is missing data.',
      'review_output':'EI: give one concise evidence-based answer per priority question and its next-modeling implication; use only individually enumerated view IDs or dataset IDs as artifact_refs (no ID ranges). For visual_support.status OBSERVED, both figure_ids and record_scope must be nonempty, including dataset-level or contextual findings. Select exact record_id values supporting the stated feature in the cited plotted rows; never invent IDs, ranges or automatically expand a dataset into all rows. A metadata-only limitation may use NON_GRAPHICAL with record_scope [] and must not claim a visual observation. NOT_ASSESSED must state the unassessed scope. Put factual metadata, source limitations and descriptive qualifications in observation or downstream_implication. Leave interpretation_if_useful empty unless proposing an explanatory hypothesis; every nonempty interpretation requires a nonempty alternative_if_interpretation giving a plausible competing explanation. CANDIDATES anomaly assessment requires exact record_ids and possible_explanations; otherwise use a scoped NONE_IDENTIFIED_IN_REVIEWED_SCOPE or NOT_ASSESSED status. Distinguish rendered views from retained tables. ER: review question coverage, scientific semantics and record/image anchors. Inspect images marked image_supplied_to_model; mark any genuinely uninspected scope explicitly.',
      'imperfect_data':'Each question needs a concise modeling_preparation recommendation: supported usable scope, best defensible next action and rationale, conditional alternatives and essential clarifications. EI reassesses that recommendation from actual outputs; ER checks that it preserves useful evidence without inventing readiness or executing unapproved transformations. A limitation on one analysis must not automatically block all analyses. No blanket exclusion or automatic request for new data.',
      'limit':'No automatic repetitions, fitting, source edits or human approval.'}
    handoff=copy.deepcopy(inputs['data_handoff'])
    # Reuse the complete Data context, replacing repeated markdown with exact existing records once.
    handoff.pop('reading_views',None)
    if 'preview_scope' in handoff:
        handoff['preview_scope']={'mode':'SOURCE_BOUND_QUESTION_EDA','materialized':f'All {len(tables)} admitted source tables, column definitions, notes and source records from verified completed EC. Exact candidate-view mappings and current implemented R registry are supplied.',
            'release_boundary':handoff['preview_scope']['release_boundary']}
    # The host already verifies every bound file in legacy.load_inputs. These are
    # transport locations, not observations; the full originals remain in input_ref.
    handoff['files']=[{k:copy.deepcopy(v) for k,v in f.items()
        if not (isinstance(v,dict) and set(v)=={'path','sha256'})} for f in handoff['files']]
    handoff['host_file_bindings']='Original Data file locations and SHA-256 bindings are retained and verified by the host in the bound input artifact; Working rows and cells are supplied below; confirmed redundant pixel-time fields are omitted with a working_view note. Original source records remain bound for verification.'
    working=eda_plot_policy.working_tables(tables)
    handoff['admitted_evidence']=[{k:copy.deepcopy(t[k]) for k in ('dataset_id','title','experimental_unit','columns','notes','records','metadata','working_view') if k in t} for t in working.values()]
    return {'task_context':tc,'data_handoff':handoff}

def validate_questions(analyses,candidates,tables,dispositions=None):
    require([a['analysis_id'] for a in analyses]==[q[0] for q in QUESTIONS],'priority questions missing, duplicated or reordered')
    for a in analyses:
        require(set(a['dataset_ids'])<=set(tables),'unknown question dataset')
        ids=[v['view_id'] for v in a['views']]
        require(len(ids)==len(set(ids)),'duplicate view within question')
        if a['status']=='NOT_APPLICABLE':require(not ids,'not-applicable question has plots')
        if a['status']=='DEFERRED':require(not ids,'deferred question cannot request executable views')
        if a['status']=='PLANNED':require(bool(ids),'planned question without evidence view')
        if a['status'] in {'PARTIAL','DEFERRED'}:require(bool(a['remaining_unknowns']),'partial question needs unknowns')
        for v in a['views']:
            require(v['view_id'] in candidates,'unknown view')
            require(set(candidate_datasets(candidates[v['view_id']]))<=set(a['dataset_ids']),'view datasets absent from question scope')
            require(len(v['scale_rationale'].strip())>=12,'scale rationale absent')
    selected=sorted({v['view_id'] for a in analyses for v in a['views']})
    optional={d['dataset_id'] for d in (dispositions or []) if d.get('handoff',{}).get('role')=='SUPPLEMENTARY' and d.get('handoff',{}).get('purpose','').strip()}
    eda_pk_scales.validate(selected,candidates,tables,optional_datasets=optional)
    eda_axis_scales.validate(selected,candidates,tables)
    return selected

def verify_render(out,specs,tables):
    eda_plot_policy.validate(specs,tables)
    manifest=read_json(out/'manifest.json');by_id={s['id']:s for s in specs}
    require({a['id'] for a in manifest['artifacts']}==set(by_id),'missing/extra rendered views')
    count=0
    for a in manifest['artifacts']:
        rows=read_json(out/a['data']);audit=read_json(out/a['audit']);spec=by_id[a['id']]
        require(a['panels']==1,'non-standalone rendered figure')
        if spec['kind']=='source_projection':
            count+=display_catalog.verify_projection(out,a,spec,tables)
            continue
        eda_axis_scales.verify_render(audit,spec)
        for z in rows:
            r=next(r for r in tables[z['dataset_id']]['records'] if r['record_id']==z['record_id'])
            require(z['y_cell']==r['source_cells'][z['y_column']],'altered source cell')
            if z['y'] is not None:
                require(r['value_status'][z['y_column']]=='QUANTIFIED','plotted nonquantified value')
                require(math.isclose(z['y'],r['source_raw_values'][z['y_column']],rel_tol=2e-15,abs_tol=0),'altered response')
                if spec['y_scale']=='log10':require(z['y']>0,'nonpositive log response')
                count+=1
            if spec['kind'] not in {'categorical_raw','frequency_bars'}:
                require(math.isclose(z['x'],r['source_raw_values'][z['x_column']],rel_tol=2e-15,abs_tol=0),'altered time/index')
            if z['error'] is not None:
                require(r['value_status'][z['error_column']]=='QUANTIFIED' and z['error']==r['source_raw_values'][z['error_column']],'altered uncertainty')
        for seg in audit['segments']:
            line=sorted([z for z in rows if z['dataset_id']==seg['dataset_id'] and z['group']==seg['group'] and z['panel']==seg['panel']],key=lambda z:z['x'])
            i=next(i for i,z in enumerate(line) if z['record_id']==seg['from_record'])
            require(i+1<len(line) and line[i+1]['record_id']==seg['to_record'] and line[i]['y'] is not None and line[i+1]['y'] is not None,'segment crosses unsupported row')
        require((out/a['png']).read_bytes().startswith(b'\x89PNG\r\n\x1a\n'),'invalid PNG')
    return {'status':'PASS','figures':len(manifest['artifacts']),'displayed_value_instances':count,'source_coordinates_checked':True,
        'new_statistics':False,'Data_reextracted':False,'visual_review':'PENDING','scientific_release':False}

def pack(value):
    if isinstance(value,list):return compact_grid([pack(v) for v in value])
    if isinstance(value,dict):return {k:copy.deepcopy(v) if k in {'project_rules','implemented_r_operations'} else pack(v) for k,v in value.items()}
    return value

def unpack(value):
    if isinstance(value,dict) and value.get('encoding')=='EDA_COLUMNAR_1':
        return [unpack(v) for v in expand_grid(value)]
    if isinstance(value,dict):return {k:unpack(v) for k,v in value.items()}
    if isinstance(value,list):return [unpack(v) for v in value]
    return value

def prepare_bundle(call_id,inputs,schema,bindings):
    from . import eda_review_context as review_context
    inputs=review_context.summary_inputs(inputs) if call_id=='EI-findings' else review_context.prepare_inputs(call_id,inputs)
    schema=review_context.summary_schema(schema) if call_id=='EI-findings' else (review_context.compact_schema(schema) if call_id=='ER-review' else schema)
    bindings=copy.deepcopy(bindings)
    if call_id=='EI-findings':bindings.pop('eda_image_manifest',None)
    calculation=inputs.get('calculation_bundle',{})
    refs=calculation.get('input_refs')
    if refs:
        cb.check_refs(refs)
        require(all(bindings.get(k)==v for k,v in refs.items()),'EC input bindings differ from current host bindings')
        calculation.pop('input_refs')
        calculation['input_refs_location']='Exact input file bindings are verified and retained in this request host manifest and the saved EC_reuse artifact; they are locators, not omitted data.'
    if call_id=='ER-review':
        from . import eda_explicit_rows
        explicit=eda_explicit_rows.encode(inputs)
        bindings['eda_explicit_rows']=cb.file_ref(eda_explicit_rows.__file__)
        return eda_context.prepare(call_id,explicit,schema,input_bindings=bindings)
    transport=copy.deepcopy(inputs)
    shared_rows={f['figure_id']:f['plotted_rows'] for f in transport.get('figure_bundle',{}).get('figures',[]) if isinstance(f.get('plotted_rows'),list)}
    rank=sorted(shared_rows,key=lambda key:(-len(shared_rows[key]),key))
    for figure in transport.get('figure_bundle',{}).get('figures',[]):
        rows=figure.get('plotted_rows')
        if not isinstance(rows,list):continue
        for prior in rank[:rank.index(figure['figure_id'])]:
            source=shared_rows[prior]
            if source==rows:
                figure['plotted_rows']={'same_plotted_rows_as':prior};break
            if rows and all(row in source for row in rows):
                figure['plotted_rows']={'same_plotted_rows_as':prior,'row_indices':[source.index(row) for row in rows]};break
    segments={f['figure_id']:f['audit']['segments'] for f in transport.get('figure_bundle',{}).get('figures',[]) if isinstance(f.get('audit',{}).get('segments'),list)}
    segment_rank=sorted(segments,key=lambda key:(-len(segments[key]),key))
    for figure in transport.get('figure_bundle',{}).get('figures',[]):
        if figure['figure_id'] not in segments:continue
        items=segments[figure['figure_id']]
        for prior in segment_rank[:segment_rank.index(figure['figure_id'])]:
            source=segments[prior]
            if items and all(item in source for item in items):
                figure['audit']['segments']={'same_segments_as':prior,'segment_indices':[source.index(item) for item in items]};break
    restored=copy.deepcopy(transport)
    for figure in restored.get('figure_bundle',{}).get('figures',[]):
        rows=figure.get('plotted_rows')
        if isinstance(rows,dict) and 'same_plotted_rows_as' in rows:
            source=shared_rows[rows['same_plotted_rows_as']]
            figure['plotted_rows']=[source[i] for i in rows['row_indices']] if 'row_indices' in rows else source
        items=figure.get('audit',{}).get('segments')
        if isinstance(items,dict) and 'same_segments_as' in items:
            figure['audit']['segments']=[segments[items['same_segments_as']][i] for i in items['segment_indices']]
    require(restored==inputs,'shared plotted rows lost evidence')
    packed=pack(transport)
    packed['task_context']['implemented_r_operations']=copy.deepcopy(inputs['task_context']['implemented_r_operations'])
    require(unpack(packed)==transport,'context encoding lost evidence')
    # Exact repeated text is stored once; rules and executable signatures remain readable.
    counts=Counter()
    def count(v):
        if isinstance(v,str) and len(v)>=100:counts[v]+=1
        elif isinstance(v,list):
            for x in v:count(x)
        elif isinstance(v,dict):
            for k,x in v.items():
                if k not in {'project_rules','implemented_r_operations'}:count(x)
    count(packed)
    texts={s:'TEXT_'+str(i+1) for i,s in enumerate(sorted(s for s,n in counts.items() if n>1 and (n-1)*len(s)>n*50+50))}
    def factor(v):
        if isinstance(v,str) and v in texts:return {'evidence_text_ref':texts[v]}
        if isinstance(v,list):return [factor(x) for x in v]
        if isinstance(v,dict):return {k:copy.deepcopy(x) if k in {'project_rules','implemented_r_operations'} else factor(x) for k,x in v.items()}
        return v
    shared={key:s for s,key in texts.items()}
    def restore(v):
        if isinstance(v,dict) and set(v)=={'evidence_text_ref'}:return shared[v['evidence_text_ref']]
        if isinstance(v,list):return [restore(x) for x in v]
        if isinstance(v,dict):return {k:restore(x) for k,x in v.items()}
        return v
    factored=factor(packed)
    require(restore(factored)==packed,'shared text encoding lost evidence')
    packed=factored
    packed['task_context']['shared_evidence_text']=shared
    packed['task_context']['input_encoding']=(
      'same_plotted_rows_as reuses the exact plotted_rows of the named figure (possibly later in the list); optional row_indices selects its zero-based rows in order. All row fields and source bindings are identical; scale and caption remain figure-specific. '
      'same_segments_as analogously reuses the named figure audit.segments selected by zero-based segment_indices. Resolve references recursively. '
      'First expand every evidence_text_ref using task_context.shared_evidence_text, an exact text dictionary. '
      'EDA_COLUMNAR_1 is exact JSON encoding. Pair fields with each row; remove absent_fields; '
      'inherit defaults only for absent keys, never replace explicit null/empty values. '
      'Decode nested_columns first into the corresponding row cells. Copy copy_from_source_raw_values '
      'keys from source_raw_values. Recursively decode nested grids. All original values, source IDs, '
      'statuses, conditions and limits are preserved. The host verified an exact round trip.')
    from . import eda_shared_values
    packed=eda_shared_values.encode(packed)
    packed['task_context']['input_encoding'] = (
        'First replace every object containing only $v with the exact value at task_context.shared_values[$v]. '
        'The dictionary entries are literal (not recursive $v references). Then apply the text and columnar decoding below. '
        + packed['task_context']['input_encoding'])
    if inputs['task_context'].get('review_batch'):
        packed['task_context']['review_batch']=copy.deepcopy(inputs['task_context']['review_batch'])
    bindings={**bindings,'eda_review_context':cb.file_ref(review_context.__file__),'eda_shared_values':cb.file_ref(eda_shared_values.__file__)}
    return eda_context.prepare(call_id,packed,schema,input_bindings=bindings)

def call(stage,call_id,inputs,schema,root,bindings):
    if call_id=='ER-review':
        from .eda_review_batches import execute
        return execute(inputs,schema,root,bindings,call_once)
    return call_once(stage,call_id,inputs,schema,root,bindings)

def call_once(stage,call_id,inputs,schema,root,bindings):
    folder=root/stage
    if folder.exists():require(not any(folder.iterdir()),'stage already has artifacts; refusing to repeat '+stage)
    else:folder.mkdir()
    inputs=copy.deepcopy(inputs);bindings=copy.deepcopy(bindings)
    if call_id=='EI-findings':
        from . import eda_review_context as review_context
        inputs=review_context.summary_inputs(inputs);schema=review_context.summary_schema(schema)
        bindings.pop('eda_image_manifest',None)
    if call_id in {'ER-review'} and not bindings.get('eda_image_manifest'):
        pictures=[{'figure_id':f['figure_id'],'file':f['image_ref']}
                  for f in inputs.get('figure_bundle',{}).get('figures',[]) if f.get('image_ref')]
        if pictures:
            write_json(folder/'images.json',{'version':'EDA_IMAGE_INPUTS_1','images':pictures})
            bindings['eda_image_manifest']=cb.file_ref(folder/'images.json')
    if bindings.get('eda_image_manifest'):
        image_ids={i['figure_id'] for i in read_json(bindings['eda_image_manifest']['path'])['images']}
        for figure in inputs.get('figure_bundle',{}).get('figures',[]):
            figure['image_supplied_to_model']=figure['figure_id'] in image_ids
    if call_id!='EI-findings':
        inputs['task_context']['question_driven_contract']['current_stage_evidence']=quality.stage_evidence(stage,inputs)
    bundle=prepare_bundle(call_id,inputs,schema,bindings)
    cb.save_bundle(folder/'prepared',bundle)
    started=time.perf_counter()
    raw=providers.codex_generate(bundle['request'],model=read_json(root/'status.json')['model'],timeout=None,cli_schema=strict_schema(bundle['request']['payload']['schema']))
    write_json(folder/'output.json',raw)
    cb.verify_bundle(bundle);Draft202012Validator(schema).validate(raw)
    write_json(folder/'timing.json',{'seconds':time.perf_counter()-started})
    if call_id=='EI-findings':
        resolved=review_context.complete_summary(raw,[f['figure_id'] for f in inputs['figure_bundle']['figures']])
        write_json(folder/'resolved_output.json',resolved)
        write_json(folder/'host_accounting.json',{'figure_checks':'EI did not inspect images; all marked NOT_ASSESSED by host.','routing':'Copied from existing plan; not chosen by EI.','raw_output_modified':False})
        return resolved
    return raw

def validate_findings(result,questions,candidates,tables):
    covered=set();allowed=set(candidates)|set(tables)|{'EC_REUSED','SOURCE_TABLES'}
    for f in result['findings']:
        require(bool(f['analysis_ids']),'finding lacks a question')
        require(set(f['analysis_ids'])<=set(questions),'unknown finding question')
        require(bool(f['artifact_refs']) and set(f['artifact_refs'])<=allowed,'unknown finding artifact')
        scope={r['record_id'] for t in tables.values() for r in t['records']}
        require(set(f['record_scope'])<=scope,'unknown source record')
        if f['interpretation_if_useful']:require(bool(f['alternative_if_interpretation']),'interpretation lacks alternative')
        if result.get('version') in {'QUESTION_FINDINGS_2','QUESTION_FINDINGS_3'}:
            visual=f['visual_support']; advice=f.get('model_advice'); anomaly=f['anomaly_assessment']
            require(set(visual['figure_ids'])<=set(candidates),'unknown inspected figure')
            if visual['status']=='OBSERVED':
                require(bool(visual['figure_ids']) and bool(f['record_scope']),'observed visual feature needs image and record anchors')
            require(set(anomaly['record_ids'])<=scope,'unknown anomaly record')
            require(anomaly['data_changed'] is False,'EI cannot change data')
            if anomaly['status']=='CANDIDATES':
                require(bool(anomaly['record_ids']) and bool(anomaly['possible_explanations']),'anomaly needs records and competing explanations')
            if result.get('version')=='QUESTION_FINDINGS_3':
                require(advice is None,'model advice belongs to downstream PK/PD')
            elif advice:
                if advice['status']=='CANDIDATES':
                    require(bool(advice['candidates']),'candidate advice is empty')
                    require(any(c['priority']=='FIRST_COMPARISON' for c in advice['candidates']),'candidate advice lacks first comparison')
                else:require(not advice['candidates'],'unsupported candidate advice')
        covered.update(f['analysis_ids'])
    require(covered==set(questions),'EI did not address every priority question')

def report(root,plan,final,findings,review,manifest):
    e=html.escape
    body=['<!doctype html><html lang="en"><meta charset="utf-8"><title>What must we understand before modeling?</title><style>body{font:16px/1.55 system-ui;color:#183448;max-width:1200px;margin:32px auto;padding:0 24px}section{border:1px solid #ccd8e1;border-radius:10px;padding:20px;margin:22px 0}img{max-width:100%}a{color:#176c99}pre{white-space:pre-wrap}li{margin:8px}</style><h1>What must we understand before modeling?</h1>',
      '<p>Question-driven EDA using the existing admitted Data and completed source-preserving EC. No extraction, fitting, automatic retry or scientific approval.</p>',
      '<p><strong>Independent review: '+e(review['decision'])+'</strong>. Human review applies to these exact new figures and findings.</p>']
    artifacts={a['id']:a for a in manifest['artifacts']}
    seen=set()
    for q in final['task_decisions']:
        body+=['<section id="'+q['analysis_id']+'"><h2>'+e(q['question'])+'</h2><p><b>Need to understand:</b> '+e(q['understanding_needed'])+'</p>']
        for f in findings['findings']:
            if q['analysis_id'] in f['analysis_ids']:
                body+=['<p><b>Observed:</b> '+e(f['observation'])+'</p><p><b>Next modeling implication:</b> '+e(f['downstream_implication'])+'</p>']
                if f['interpretation_if_useful']:body+=['<p>Candidate interpretation: '+e(f['interpretation_if_useful'])+' Alternative: '+e(f['alternative_if_interpretation'])+'</p>']
        if q['remaining_unknowns']:body+=['<p><b>Still unknown:</b> '+e(' '.join(q['remaining_unknowns']))+'</p>']
        prep=q['modeling_preparation']
        body+=['<p><b>Usable now:</b> '+e(prep['usable_now'])+'</p><p><b>Best next preparation:</b> '+e(prep['preferred_action'])+'<br>'+e(prep['why'])+'</p>']
        if prep['conditional_alternatives']:body+=['<p><b>Conditional alternatives:</b> '+e(' '.join(prep['conditional_alternatives']))+'</p>']
        if prep['essential_clarifications']:body+=['<p><b>Clarify before the affected action:</b> '+e(' '.join(prep['essential_clarifications']))+'</p>']
        for v in q['views']:
            a=artifacts[v['view_id']]
            body+=['<p><b>'+e(v['purpose'])+'</b><br>Scale: '+e(v['scale_rationale'])+'<br>Additional information: '+e(v['complementary_value'])+'</p>']
            if a['id'] not in seen:
                body+=['<p><a href="EV/'+a['pdf']+'">Vector PDF</a> · <a href="EV/'+a['data']+'">Exact plotted rows</a></p><img loading="lazy" src="EV/'+a['png']+'" alt="'+e(a['id'])+'">']
                seen.add(a['id'])
            else:body+=['<p>Reuses '+e(a['id'])+' shown above.</p>']
        body+=['</section>']
    body+=['<section><h2>Review issues</h2>']
    for i in review['issues']:body+=['<p><b>'+e(i['affected_artifact'])+'</b>: '+e(i['evidence'])+' '+e(i['consequence'])+'<br>Next action ('+e(i['correction_owner'])+'): '+e(i['smallest_correction'])+'</p>']
    body+=['<p>Unreviewed: '+e(' '.join(review['unreviewed_items']))+'</p></section>',
      '<p><a href="EP/output.json">EP plan</a> · <a href="EP_FINALIZE/output.json">Post-EC decisions</a> · <a href="EI/output.json">Findings</a> · <a href="ER/output.json">Review</a> · <a href="source_tables.json">All retained source tables and notes</a> · <a href="verification.json">Technical checks</a></p></html>']
    (root/'report.html').write_text(''.join(body),encoding='utf-8')

def run_questions(inputs_path,completed_run,catalog_path,out,*,model=None,until='EV',inheritance_scope=None):
    require(until in {'EV','ER'},'question workflow stop must be EV or ER')
    root=Path(out);root.mkdir(parents=True,exist_ok=False)
    from . import eda_inheritance
    inputs_path=eda_inheritance.prepare(inputs_path,root/'admitted_inputs',inheritance_scope)
    inputs,tables,candidates,catalog,caps,bindings,source_refs=intake(inputs_path,completed_run,catalog_path)
    write_json(root/'presentation_policy_audit.json',eda_plot_policy.audit(candidates,tables))
    state={'status':'RUNNING','model':providers.provider_model(model),'provider':providers.model_provider(),'mode':'QUESTION_DRIVEN_2','scientific_release':False,'fit_ready':False,'human_approval':False,
        'Data_reextracted':False,'EC_reexecuted':False,'automatic_retries':0,'bindings':bindings}
    write_json(root/'status.json',state);write_json(root/'source_tables.json',list(tables.values()))
    write_json(root/'recipe_match_report.json',catalog.get('match_report',[]))
    base=question_context(inputs,tables,candidates,caps,catalog.get('match_report'))
    started=time.perf_counter()
    try:
        with LinearSession(root/'model_calls',bindings).activate():
            plan=call('EP','EP-plan',base,plan_schema(candidates,tables),root,bindings)
            selected=validate_questions(plan['analyses'],candidates,tables,plan.get('dataset_dispositions'))
            dataset_routes.build(list(tables.values()),plan.get('dataset_dispositions'))
            from . import eda_coverage_accounting as accounting
            plan['dataset_dispositions'],field_audit=accounting.resolve(plan['dataset_dispositions'],selected,candidates,tables,match_report=catalog.get('match_report'))
            write_json(root/'EP/field_accounting.json',field_audit)
            write_json(root/'EP/resolved_output.json',plan)
            write_json(root/'EP/coverage.json',display_catalog.coverage(plan.get('dataset_dispositions'),selected,candidates,tables,match_report=catalog.get('match_report')))
            ec={'version':'QUESTION_EC_REUSE_1','plan_ref':cb.file_ref(root/'EP/resolved_output.json'),
                'input_refs':bindings,'results_ref':bindings['completed_ec_result'],
                'provenance_ref':bindings.get('completed_ec_receipt',bindings.get('source_snapshot')),
                'source_mode':'DH_SOURCE_SNAPSHOT' if 'source_snapshot' in bindings else 'COMPLETED_EC_REUSE',
                'checks':['Exact admitted Data source records and metadata verified; no statistics computed.'],
                'not_calculable':['No new statistics requested; source-native rendering only.'],'reexecuted':False}
            write_json(root/'EC_reuse.json',ec)
            finalinputs={**copy.deepcopy(base),'eda_plan':plan,'calculation_bundle':copy.deepcopy(ec)}
            finalinputs['calculation_bundle']['source_evidence']=base['data_handoff']['admitted_evidence']
            finalinputs['data_handoff'].pop('admitted_evidence',None)
            final=call('EP_FINALIZE','EP-finalize',finalinputs,final_schema(candidates,tables),root,bindings)
            from . import eda_plan_accounting
            final,plan_audit=eda_plan_accounting.resolve(plan,final,candidates,tables,ec_reexecuted=ec['reexecuted'])
            write_json(root/'EP_FINALIZE/plan_accounting.json',plan_audit)
            selected=validate_questions(final['task_decisions'],candidates,tables,final.get('dataset_dispositions'))
            final['dataset_dispositions'],field_audit=accounting.resolve(final['dataset_dispositions'],selected,candidates,tables,match_report=catalog.get('match_report'))
            write_json(root/'EP_FINALIZE/field_accounting.json',field_audit)
            write_json(root/'EP_FINALIZE/resolved_output.json',final)
            coverage=display_catalog.coverage(final.get('dataset_dispositions'),selected,candidates,tables,match_report=catalog.get('match_report'))
            write_json(root/'dataset_routing.json',dataset_routes.build(list(tables.values()),final.get('dataset_dispositions')))
            write_json(root/'EP_FINALIZE/coverage.json',coverage)
            specs=[copy.deepcopy(candidates[i]) for i in selected]
            ev=root/'EV';ev.mkdir()
            renderplan={'version':'QUESTION_DISPLAYS_1','input_ref':bindings['completed_ec_result'],
                'rules_ref':cb.file_ref(eda_context.PACK),'plots':specs,'references':catalog['references']}
            write_json(ev/'plot_plan.json',renderplan)
            rstart=time.perf_counter()
            display_catalog.render(ev,specs,tables,bindings,rscript_path(),HANDLER,catalog['references'])
            quality_audit=quality.inspect_render(ev,specs,tables)
            write_json(root/'quality_checks.json',quality_audit)
            checks=verify_render(ev,specs,tables);checks['R_seconds']=time.perf_counter()-rstart
            write_json(root/'verification.json',checks)
            manifest=read_json(ev/'manifest.json')
            figures={'version':'QUESTION_FIGURES_1','plan_ref':cb.file_ref(root/'EP_FINALIZE/resolved_output.json'),
                'calculation_ref':cb.file_ref(root/'EC_reuse.json'),'technical_checks':checks,'omissions':[],
                'figures':[{'figure_id':a['id'],'analysis_ids':[q['analysis_id'] for q in final['task_decisions'] if any(v['view_id']==a['id'] for v in q['views'])],
                    'plotted_rows':read_json(ev/a['data']),'audit':read_json(ev/a['audit']),
                    'caption':candidates[a['id']]['caption'],'scale':candidates[a['id']]['y_scale'],
                    'render_recipe':display_catalog.brief(candidates[a['id']]),
                    'context_rows':candidates[a['id']].get('source_recipe',{}).get('context_rows',[]),
                    'render_facts':a['render_facts'],'semantic_audit':quality_audit['figures'][a['id']]['semantic_audit'],
                    'image_ref':cb.file_ref(ev/a['png']),'image_supplied_to_model':False} for a in manifest['artifacts']],
                'tables':{'all_sources_retained':True,'host_file':cb.file_ref(root/'source_tables.json')}}
            figures['dataset_display_coverage']=coverage
            write_json(root/'figure_bundle.json',figures)
            if until=='EV':
                cb.check_refs(bindings);cb.check_refs(source_refs)
                state.update(status='STOPPED_AFTER_EV',elapsed_seconds=time.perf_counter()-started,
                    figures=len(specs),EI_run=False,ER_run=False)
                write_json(root/'status.json',state)
                links=''.join('<h2>'+html.escape(a['id'])+'</h2><img style="max-width:100%" src="EV/'+a['png']+'">' for a in manifest['artifacts'])
                (root/'report.html').write_text('<html lang="en"><meta charset="utf-8"><h1>Question-driven EDA: stopped after EV</h1><p>Source-bound displays; no EI/ER or scientific release.</p><a href="EP_FINALIZE/coverage.json">Dataset coverage</a>'+links+'</html>',encoding='utf8')
                write_json(root/'outputs.json',{str(p.relative_to(root)):cb.file_ref(p) for p in root.rglob('*') if p.is_file() and p.name!='outputs.json'})
                return state
            subsequent={**copy.deepcopy(base),'eda_plan':quality.current_plan(plan,final),
                'calculation_bundle':ec,'figure_bundle':figures}
            subsequent['eda_plan']['host_plan_accounting']=plan_audit
            subsequent['task_context']['question_driven_contract'].pop('candidate_views')
            findings=call('EI','EI-findings',subsequent,findings_schema(tables,selected),root,bindings)
            validate_findings(findings,[q[0] for q in QUESTIONS],selected,tables)
            quality_audit['narrative_consistency']=quality.validate_consistency(findings,quality_audit)
            write_json(root/'quality_checks.json',quality_audit)
            review=call('ER','ER-review',{**subsequent,'eda_findings':findings},review_schema(),root,bindings)
            quality.validate_review(review)
            quality_audit['independent_review']=review['quality_checks']
            write_json(root/'quality_checks.json',quality_audit)
            require(review['decision']!='PASS' or not review['issues'],'PASS cannot contain unresolved issues')
            cb.check_refs(bindings);cb.check_refs(source_refs)
        state.update(status='WAITING_FOR_HUMAN_REVIEW' if review['decision']=='PASS' else 'REVIEW_REQUIRED',
            independent_review=review['decision'],elapsed_seconds=time.perf_counter()-started,figures=len(specs))
        report(root,plan,final,findings,review,manifest)
        if findings.get('version')=='QUESTION_FINDINGS_3':
            from .eda_review_handoff import build as build_human_gate
            build_human_gate(root,subsequent,findings,review,
                {**bindings,**{'source:'+k:v for k,v in source_refs.items()},
                 'EI_output':cb.file_ref(root/'EI/resolved_output.json'),'ER_output':cb.file_ref(root/'ER/output.json')})
        write_json(root/'status.json',state)
        write_json(root/'outputs.json',{str(p.relative_to(root)):cb.file_ref(p) for p in root.rglob('*') if p.is_file() and p.name!='outputs.json'})
        return state
    except BaseException as exc:
        state.update(status='FAILED',error=str(exc),elapsed_seconds=time.perf_counter()-started)
        write_json(root/'status.json',state)
        raise
    finally:
        from .eda_run_summary import export
        export(root)
