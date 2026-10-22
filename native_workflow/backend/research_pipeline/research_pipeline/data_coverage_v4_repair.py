"""Audited repair of a returned coverage part; immutable parent and no automatic provider call."""
import copy
import importlib.util
import re
from pathlib import Path
from collections import Counter
from . import data_coverage_v4 as v

INSTRUCTIONS='''This is a bounded repair of named checks, not a new assessment of the entire project.
The prior model statements are NON-EVIDENCE and can be wrong. Evaluate each concrete diagnostic against
this unit's adjacent original title/notes and the exact criterion description. Use its actual scope,
not a preceding table's facts. Only requested check keys can change; other checks remain prior model
decisions, not human scientific approval. PARTIAL, CONFLICT and UNRESOLVED remain legitimate outcomes.
Do not seek PASS. Reconsider the scientific reason together with its sources, not just the selector.
All conjuncts are needed for SUPPORTED; route alone is not formulation, and CFU is not drug concentration.
Normative rules alone cannot establish observed facts. A global multi-species/input-class requirement
does not require each local table to contain every species or input class. Apply the relevant local class.
'''


def _old_module(snapshot):
    spec=importlib.util.spec_from_file_location('research_pipeline._frozen_coverage_repair_parent',snapshot)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def diagnose(payload,raw,old):
    """Determine repair targets; no status/evidence is repaired or invented here."""
    sources=payload['source_rows'];scopes={s['id']:s for s in payload['scopes']};result={}
    for unit in payload['units']:
        uid=unit['unit_id'];answer=raw['rows'][uid];specs={x['id']:x for x in unit['criteria']}
        grouped={cid:[c for c in answer['checks'] if c['criterion_id']==cid] for cid in specs}
        findings={};allowed=set(scopes[unit['scope_id']]['item_ids'])|set(payload['support_item_ids'])
        def flag(cid,reason):findings.setdefault(cid,[]).append(reason)
        for cid,spec in specs.items():
            if len(grouped[cid])!=1:
                flag(cid,'Missing or duplicated criterion; return exactly this named criterion.');continue
            check=grouped[cid][0]
            single=copy.deepcopy(payload);u=copy.deepcopy(unit);u['criteria']=[spec];single['units']=[u]
            a=copy.deepcopy(answer);a['checks']=[check]
            if check['s']!='DEFERRED':a['deferred_outputs']=[]
            # Search metadata is diagnosed separately, so it cannot mask all criterion errors.
            a['search_item_ids']=[]
            try:old.materialize({'request_sha256':raw['request_sha256'],'rows':{uid:a}},single)
            except Exception as exc:flag(cid,'Host predicate rejected this check: '+str(exc))
            if cid=='FULL_REQUIREMENT' and unit['requirement']['id'] in {'RQ001','RQ003'}:
                flag(cid,'Assess the local input class/species; absent other project classes/species does not alone make this local input partial.')
            indices=check['e']+check['x']
            if check['s']=='SUPPORTED' and indices and all(sources[i][2] is None for i in indices):
                flag(cid,'Authority is not an observation: confirm whether this criterion is normative or needs local facts; do not assert observed compliance from a Rule alone.')
            if check['s']=='SUPPORTED' and 'route' in spec['description'].lower() and 'formulation' in spec['description'].lower():
                flag(cid,'SUPPORTED must establish both route and formulation; route alone gives at most partial evidence.')
            if 'concentration' in spec['description'].lower() and 'cfu' in check['r'].lower():
                flag(cid,'Bacterial CFU endpoint is not drug concentration; reassess quantity compatibility.')
        table=re.search(r':T(\d+)$',unit['scope_id'])
        wrong=[]
        if table:
            for check in answer['checks']:
                named=re.match(r'T(\d+)\b',check['r'])
                if named and named.group(1)!=table.group(1):wrong.append(check['criterion_id'])
        if wrong:
            for cid in specs:flag(cid,'This unit contains another table\'s narrative ('+', '.join(wrong)+'); reassess this unit against its own explicit scope and notes.')
        badsearch=bool(set(answer['search_item_ids'])-set(payload['permitted_item_ids']) or
                       set(answer['search_item_ids']) & set(payload['visible_item_ids']))
        result[uid]={'targets':findings,'repair_search':badsearch,'wrong_scope_narrative':wrong}
    return result


def _compose(current,parent,raw,old,parent_part):
    prior=next(p for p in parent['payloads'] if p['part_id']==parent_part)
    fresh=next(p for p in current['payloads'] if p['part_id']==parent_part)
    comparable=[{k:value for k,value in u.items() if k!='local_scope_identity'} for u in fresh['units']]
    if prior['source_rows']!=fresh['source_rows'] or prior['units']!=comparable:
        v.fail('Repair cannot change original source rows or criteria')
    diagnosis=diagnose(prior,raw,old);units=[]
    for original in fresh['units']:
        unit=copy.deepcopy(original);uid=unit['unit_id'];answer=raw['rows'][uid];targets=diagnosis[uid]['targets']
        unit['response_criterion_ids']=[s['id'] for s in unit['criteria'] if s['id'] in targets]
        unit['fixed_checks']={c['criterion_id']:{k:copy.deepcopy(value) for k,value in c.items() if k!='criterion_id'}|{'ce':[],'cx':[]}
            for c in answer['checks'] if c['criterion_id'] not in targets}
        unit['repair_findings']=targets
        unit['prior_target_checks']=[copy.deepcopy(c) for c in answer['checks'] if c['criterion_id'] in targets]
        metadata={k:copy.deepcopy(value) for k,value in answer.items() if k!='checks'}
        unit['response_metadata_fields']=['source_links','deferred_outputs'] if targets else []
        if diagnosis[uid]['repair_search']:unit['response_metadata_fields']+=['search_item_ids','search_reason']
        if any(c['s']=='DEFERRED' for c in unit['fixed_checks'].values()):
            unit['preserved_deferred_outputs']=copy.deepcopy(answer['deferred_outputs'])
        unit['preserved_source_links']=copy.deepcopy(answer['source_links'])
        unit['fixed_metadata']={k:value for k,value in metadata.items() if k not in unit['response_metadata_fields']}
        units.append(unit)
    # Keep a source scope together whenever it fits; at most two scopes and 150 target checks per call.
    groups=[];group=[];scope_ids=set();count=0
    for unit in units:
        n=len(unit['response_criterion_ids']);sid=unit['scope_id']
        if group and (count+n>150 or len(scope_ids|{sid})>2):
            groups.append(group);group=[];scope_ids=set();count=0
        group.append(unit);scope_ids.add(sid);count+=n
    if group:groups.append(group)
    parts=[]
    for i,group in enumerate(groups,1):
        p=copy.deepcopy(fresh);p['part_id']=parent_part+'_REPAIR'+str(i).zfill(2);p['units']=group
        visible=set(p['support_item_ids'])|{item for scope in p['scopes'] if scope['id'] in {u['scope_id'] for u in group} for item in scope['item_ids']}
        omitted=set(p['visible_item_ids'])-visible
        p['source_rows']=[r for r in p['source_rows'] if r[2] is None or r[2] in visible]
        p['visible_item_ids']=sorted(visible)
        p['permitted_item_overviews'] += [{'item_id':item,'original_descriptor':current['catalog'][item]['content']} for item in sorted(omitted)]
        p['source_projection']={'policy':'ALL_LOCAL_AND_SUPPORT_BODY_RETAINED; OTHER_PRIMARY_BODY_NOT_READ_IN_THIS_REPAIR',
                                'omitted_primary_item_ids':sorted(omitted),'original_selector_indices_preserved':True}
        p['instructions']+='\n'+INSTRUCTIONS
        p['repair_scope']={'parent_part':parent_part,'preserved_checks':'UNMODIFIED_PRIOR_MODEL_DECISIONS_NOT_HUMAN_APPROVAL',
                           'allowed_changes':'ONLY_KEYED_TARGET_CHECKS_AND_IDENTIFIED_INVALID_SEARCH_METADATA'}
        parts.append(p)
    current['payloads']=[p for original in current['payloads'] for p in (parts if original['part_id']==parent_part else [original])]
    current['repair_diagnosis']=diagnosis
    return current


def replay_build(saved,current):
    refs=saved['bindings'];v.planning.check_refs(refs)
    parent=v.read_json(refs['repair_parent_build']['path']);snapshot=refs['repair_parent_code']
    for key,ref in parent['bindings'].items():
        if key=='code':
            if ref['sha256']!=snapshot['sha256']:v.fail('Historical contract snapshot hash mismatch')
        else:v.check_ref(ref)
    raw=v.read_json(refs['repair_parent_response']['path']);request=v.read_json(refs['repair_parent_request']['path'])
    old=_old_module(snapshot['path']);part=saved['repair_parent_part']
    payload=next(p for p in parent['payloads'] if p['part_id']==part)
    if request!=old.governed_request(payload) or raw['request_sha256']!=request['request_sha256']:
        v.fail('Parent response/request binding mismatch')
    if current['planning_sha256']!=parent['planning_sha256'] or current['catalog']!=parent['catalog']:
        v.fail('Repair source or planning identity changed')
    current=_compose(current,parent,raw,old,part)
    current['bindings'].update({k:refs[k] for k in refs if k.startswith('repair_')})
    current['repair_parent_part']=part
    budget=v.read_json(refs['repair_parent_budget']['path'])
    if budget['build_sha256']!=v.digest(parent):v.fail('Parent model budget not bound to source build')
    current['prior_model_seconds']=budget['elapsed_seconds'];current['prior_model_calls']=budget['calls']
    if saved.get('imported_parts'):
        current['imported_parts']=copy.deepcopy(saved['imported_parts'])
    if saved.get('model_correction'):
        current=_model_correction(current,saved['model_correction'])
    if current.get('imported_parts'):
        budgets=[]
        for spec in current['imported_parts']:
            payload=next(p for p in current['payloads'] if p['part_id']==spec['part_id'])
            _import_derivation(spec,payload)
            imported_budget=v.read_json(spec['budget']['path']);budgets.append(imported_budget)
        current['prior_model_seconds']=max([current['prior_model_seconds']]+[x['elapsed_seconds'] for x in budgets])
        current['prior_model_calls']=max([current['prior_model_calls']]+[x['calls']+x.get('prior_calls',0) for x in budgets])
    return current


def prepare_repair(failed_out,out,snapshot,parent_part='COV01'):
    failed_out=Path(failed_out).resolve();out=Path(out).resolve()
    if out.exists() and any(out.iterdir()):v.fail('Repair requires a new output directory')
    parent=v.read_json(failed_out/'build.json')
    audits=list((failed_out/parent_part/'data_agents/audit/DC-review').glob('*/response.json'))
    if len(audits)!=1:v.fail('Select an unambiguous original failed response')
    response=audits[0];plan_ref=parent['bindings']['plan']
    plan=v.planning.verify_plan(plan_ref['path'])
    current=v.build(plan,Path(parent['bindings']['source_view']['path']).parent);current['bindings']['plan']=plan_ref
    saved={'bindings':dict(current['bindings'],repair_parent_build=v.file_ref(failed_out/'build.json'),
        repair_parent_response=v.file_ref(response),repair_parent_request=v.file_ref(response.parent/'request.json'),
        repair_parent_budget=v.file_ref(failed_out/'model_budget.json'),repair_parent_code=v.file_ref(snapshot),
        repair_code=v.file_ref(__file__)),'repair_parent_part':parent_part}
    built=replay_build(saved,current);sizes=[]
    for payload in built['payloads']:
        request=v.governed_request(payload);size=v._chars(request)
        if size>v.d.REQUEST_BUDGET:v.fail(f"Repair part {payload['part_id']} exceeds 700000: {size}")
        v.write_json(out/'requests'/(payload['part_id']+'.json'),request)
        sizes.append({'part_id':payload['part_id'],'request_chars':size,'units':len(payload['units']),
            'requested_checks':sum(len(u.get('response_criterion_ids',u['criteria'])) for u in payload['units']),
            'preserved_checks':sum(len(u.get('fixed_checks',{})) for u in payload['units'])})
    v.write_json(out/'build.json',built)
    v.write_json(out/'preflight.json',{'parts':sizes,'model_calls':0,'prior_model_seconds':built['prior_model_seconds'],
        'remaining_model_seconds':v.MODEL_BUDGET_SECONDS-built['prior_model_seconds']})
    return built


def classify_references(raw,payload):
    """Lossless same-polarity union, classified solely by actual frozen source ownership."""
    normalized=copy.deepcopy(raw);indexed={r[4]:r for r in payload['source_rows']}
    scopes={s['id']:s for s in payload['scopes']};mapping=[]
    for unit in payload['units']:
        uid=unit['unit_id'];allowed=set(scopes[unit['scope_id']]['item_ids'])|set(payload['support_item_ids'])
        for cid,check in normalized['rows'][uid]['checks'].items():
            for ordinary,cross in [('e','ce'),('x','cx')]:
                before={ordinary:list(check[ordinary]),cross:list(check[cross])}
                merged=list(dict.fromkeys(check[ordinary]+check[cross]))
                if not set(merged)<=indexed.keys():v.fail('Normalization cannot introduce an unseen source')
                check[ordinary]=[i for i in merged if indexed[i][2] is None or indexed[i][2] in allowed]
                check[cross]=[i for i in merged if indexed[i][2] is not None and indexed[i][2] not in allowed]
                after={ordinary:check[ordinary],cross:check[cross]}
                if before!=after:mapping.append({'unit_id':uid,'criterion_id':cid,'before':before,'after':after,
                    'sources':[{'index':i,'source_id':indexed[i][0],'item_id':indexed[i][2],'quote_sha256':v.digest(indexed[i][3])} for i in merged]})
    v.materialize(normalized,payload)  # Foreign sources still require the original strict relation/body gates.
    return normalized,mapping


def _import_derivation(spec,payload):
    v.planning.check_refs(spec)
    parent=v.read_json(spec['parent_build']['path']);old=_old_module(spec['code_snapshot']['path'])
    for key,ref in parent['bindings'].items():
        if key in {'code','repair_code'}:
            snapshot=spec['code_snapshot' if key=='code' else 'repair_snapshot']
            if snapshot['sha256']!=ref['sha256']:v.fail('Imported response historical code binding mismatch')
        else:v.check_ref(ref)
    oldpayload=next(p for p in parent['payloads'] if p['part_id']==spec['part_id'])
    if {k:x for k,x in oldpayload.items() if k!='transport_version'}!={k:x for k,x in payload.items() if k!='transport_version'}:
        v.fail('Imported response scientific payload changed')
    request=v.read_json(spec['request']['path']);raw=v.read_json(spec['response']['path'])
    if request!=old.governed_request(oldpayload) or raw['request_sha256']!=request['request_sha256']:
        v.fail('Imported response does not belong to its actual sent request')
    v.d.validate_schema(raw,old.response_schema(oldpayload))
    budget=v.read_json(spec['budget']['path'])
    if budget['build_sha256']!=v.digest(parent):v.fail('Imported model time does not belong to parent build')
    derived,mapping=classify_references(raw,payload)
    materialized=v.materialize(derived,payload)
    qualifications=[{'unit_id':m['unit_id'],'criterion_id':c['id'],'host_qualification':c['host_qualification']}
        for m in materialized for c in m['criteria'] if 'host_qualification' in c]
    proof={'version':'SOURCE_OWNERSHIP_NORMALIZATION_1.0','parent':spec,'current_payload_sha256':v.digest(payload),
        'raw_sha256':v.digest(raw),'derived_sha256':v.digest(derived),'mapping':mapping,
        'normalizer_ref':v.file_ref(__file__),'materializer_ref':v.file_ref(v.__file__),
        'materialized_sha256':v.digest(materialized),'host_qualifications':qualifications,
        'provider_calls':0,'model_provenance':'ORIGINAL_MODEL_RESPONSE_WITH_HOST_REFERENCE_FIELD_CLASSIFICATION',
        'raw_response_unchanged_fields':['statuses','reasons','needed_material','source_quotes','polarity','scientific_content'],
        'materialization_status_changes_are_explicit':True,
        'scientific_approval':False}
    return derived,proof


def load_imported_response(out,built,payload):
    selected=[x for x in built.get('imported_parts',[]) if x['part_id']==payload['part_id']]
    if not selected:return None
    if len(selected)!=1:v.fail('Duplicate response import')
    derived,proof=_import_derivation(selected[0],payload)
    path=Path(out)/'imports'/(payload['part_id']+'.json')
    if v.read_json(path)!=proof:v.fail('Saved response normalization proof does not replay')
    return derived,v.file_ref(path)


def prepare_continuation(previous_out,out,parent_snapshot,code_snapshot,repair_snapshot,part_id='COV01_REPAIR01'):
    previous_out=Path(previous_out).resolve();out=Path(out).resolve()
    previous=v.read_json(previous_out/'build.json')
    built=prepare_repair(Path(previous['bindings']['repair_parent_build']['path']).parent,out,parent_snapshot)
    candidates=list((previous_out/part_id/'data_agents/audit/DC-review').glob('*/response.json'))
    if len(candidates)!=1:v.fail('Import requires one exact returned response')
    response=candidates[0]
    spec={'part_id':part_id,'parent_build':v.file_ref(previous_out/'build.json'),
        'request':v.file_ref(response.parent/'request.json'),'response':v.file_ref(response),
        'budget':v.file_ref(previous_out/'model_budget.json'),'code_snapshot':v.file_ref(code_snapshot),
        'repair_snapshot':v.file_ref(repair_snapshot)}
    built['imported_parts']=[spec]
    payload=next(p for p in built['payloads'] if p['part_id']==part_id)
    _,proof=_import_derivation(spec,payload)
    budget=v.read_json(spec['budget']['path'])
    built['prior_model_seconds']=budget['elapsed_seconds'];built['prior_model_calls']=budget['calls']+budget.get('prior_calls',0)
    v.write_json(out/'build.json',built);v.write_json(out/'imports'/(part_id+'.json'),proof)
    v.write_json(out/'model_budget.json',{'build_sha256':v.digest(built),'elapsed_seconds':built['prior_model_seconds'],
        'calls':0,'prior_calls':built['prior_model_calls']})
    pre=v.read_json(out/'preflight.json');pre.update(prior_model_seconds=built['prior_model_seconds'],
        remaining_model_seconds=v.MODEL_BUDGET_SECONDS-built['prior_model_seconds'],imported_part=part_id,import_provider_calls=0)
    v.write_json(out/'preflight.json',pre)
    return built


def prepare_qualified_continuation(previous_out,out,code_snapshot,repair_snapshot,part_id='COV01_REPAIR02'):
    """Import an actual saved response under explicit fail-closed materialization; zero providers."""
    previous_out=Path(previous_out).resolve();out=Path(out).resolve()
    if out.exists() and any(out.iterdir()):v.fail('Continuation requires a new output directory')
    previous=v.read_json(previous_out/'build.json');refs=previous['bindings']
    plan=v.planning.verify_plan(refs['plan']['path'])
    current=v.build(plan,Path(refs['source_view']['path']).parent);current['bindings']['plan']=refs['plan']
    saved=copy.deepcopy(previous)
    saved['bindings']['code']=v.file_ref(v.__file__);saved['bindings']['repair_code']=v.file_ref(__file__)
    candidates=list((previous_out/part_id/'data_agents/audit/DC-review').glob('*/response.json'))
    if len(candidates)!=1:v.fail('Import requires one exact returned response')
    response=candidates[0]
    spec={'part_id':part_id,'parent_build':v.file_ref(previous_out/'build.json'),
        'request':v.file_ref(response.parent/'request.json'),'response':v.file_ref(response),
        'budget':v.file_ref(previous_out/'model_budget.json'),'code_snapshot':v.file_ref(code_snapshot),
        'repair_snapshot':v.file_ref(repair_snapshot)}
    if any(x['part_id']==part_id for x in saved.get('imported_parts',[])):v.fail('Part already imported')
    saved.setdefault('imported_parts',[]).append(spec)
    built=replay_build(saved,current);sizes=[]
    for payload in built['payloads']:
        request=v.governed_request(payload);size=v._chars(request)
        if size>v.d.REQUEST_BUDGET:v.fail('Continuation request exceeds unchanged transport budget')
        v.write_json(out/'requests'/(payload['part_id']+'.json'),request)
        sizes.append({'part_id':payload['part_id'],'request_chars':size})
        chosen=next((s for s in built['imported_parts'] if s['part_id']==payload['part_id']),None)
        if chosen:
            _,proof=_import_derivation(chosen,payload);v.write_json(out/'imports'/(payload['part_id']+'.json'),proof)
    v.write_json(out/'build.json',built)
    v.write_json(out/'model_budget.json',{'build_sha256':v.digest(built),'elapsed_seconds':built['prior_model_seconds'],
        'calls':0,'prior_calls':built['prior_model_calls']})
    v.write_json(out/'preflight.json',{'parts':sizes,'model_calls':0,'model_routing':built['model_routing'],
        'prior_model_seconds':built['prior_model_seconds'],'remaining_model_seconds':v.MODEL_BUDGET_SECONDS-built['prior_model_seconds']})
    return built


def _correction_payload(payload,raw,findings):
    """Reassess the complete affected units; retain immutable prior decisions as non-evidence."""
    result=copy.deepcopy(payload)
    for unit in result['units']:
        uid=unit['unit_id']; prior=copy.deepcopy(unit.get('fixed_checks',{}))
        prior.update(copy.deepcopy(raw['rows'][uid]['checks']))
        if set(prior)!={c['id'] for c in unit['criteria']}:v.fail('Correction parent is not a complete criterion record')
        for key in ('fixed_checks','fixed_metadata','preserved_deferred_outputs','preserved_source_links','response_metadata_fields'):
            unit.pop(key,None)
        unit['response_criterion_ids']=[c['id'] for c in unit['criteria']]
        unit['prior_target_checks']=prior
        unit['repair_findings']=[{k:f[k] for k in ('criterion_id','finding')}
            for f in findings.get('semantic_spotcheck_flags',[]) if f['unit_id']==uid]
    result['instructions']+='''\nReassess ALL checks in these affected units, including earlier fixed checks. Each adjacent criterion description
is authoritative for this exact requirement; FIELD_001 under RQ001 is not FIELD_001 under RQ002.
The prior response and diagnostic findings are NON-EVIDENCE, not instructions to reach a favorable status.
Keep T3 and T4 distinct. Cite their actual original notes for route, formulation, quantities and organism;
generic MAIN objectives, another study's MAIN statement, and METHOD knowledge cannot establish these local facts.
A note-held MIC such as an explicitly reported numerical fact must remain in the corresponding field facts
and reason with its actual organism and scope. Do not say it is absent merely because it is outside a table.
The unchanged FULL_REQUIREMENT body-evidence gate still applies: if its measurement-body qualification
is not established, use UNRESOLVED with an accurate reason rather than decorative unrelated CFU body evidence.
Do not recategorize a source note as body, invent observations, or change scientific requirements.
'''
    result['repair_scope']={'allowed_changes':'ALL_CRITERIA_AND_METADATA_OF_THIS_AFFECTED_PART_ONLY',
        'prior_answers':'NON_EVIDENCE; NOT_SCIENTIFIC_APPROVAL','original_sources_and_criteria':'UNCHANGED'}
    return result


def _model_correction(current,spec):
    v.planning.check_refs(spec)
    parent=v.read_json(spec['parent_build']['path'])
    for key,ref in parent['bindings'].items():
        if key in {'code','repair_code'}:
            snapshot=spec['code_snapshot' if key=='code' else 'repair_snapshot']
            if snapshot['sha256']!=ref['sha256']:v.fail('Correction historical code binding mismatch')
        else:v.check_ref(ref)
    if parent['planning_sha256']!=current['planning_sha256'] or parent['catalog']!=current['catalog']:
        v.fail('Correction source or plan identity changed')
    part=spec['part_id']; prior=next(p for p in parent['payloads'] if p['part_id']==part)
    fresh=next(p for p in current['payloads'] if p['part_id']==part)
    if prior!=fresh:v.fail('Correction base payload changed before explicit corrective projection')
    old=_old_module(spec['code_snapshot']['path'])
    request=v.read_json(spec['request']['path']);raw=v.read_json(spec['response']['path'])
    if old.governed_request(prior)!=request or raw['request_sha256']!=request['request_sha256']:
        v.fail('Correction raw is not bound to the actual sent request')
    v.d.validate_schema(raw,old.response_schema(prior))
    findings=v.read_json(spec['findings']['path'])
    budget=v.read_json(spec['budget']['path'])
    if budget['build_sha256']!=v.digest(parent):v.fail('Correction budget is not bound to its parent build')
    current['payloads']=[_correction_payload(p,raw,findings) if p['part_id']==part else p for p in current['payloads']]
    current['model_correction']=copy.deepcopy(spec)
    current['prior_model_seconds']=max(current.get('prior_model_seconds',0),budget['elapsed_seconds'])
    current['prior_model_calls']=max(current.get('prior_model_calls',0),budget['calls']+budget.get('prior_calls',0))
    current['model_routing']={'new_calls_model':v.MODEL,'imported_parts':[{'part_id':s['part_id'],
        'original_model':_old_module(s['code_snapshot']['path']).MODEL,'raw_response_ref':s['response']}
        for s in current.get('imported_parts',[])]}
    return current


def prepare_model_correction(previous_out,out,code_snapshot,repair_snapshot,findings_path,part_id='COV01_REPAIR02'):
    previous_out=Path(previous_out).resolve();out=Path(out).resolve()
    if out.exists() and any(out.iterdir()):v.fail('Correction requires a new output directory')
    previous=v.read_json(previous_out/'build.json');refs=previous['bindings']
    plan=v.planning.verify_plan(refs['plan']['path'])
    current=v.build(plan,Path(refs['source_view']['path']).parent);current['bindings']['plan']=refs['plan']
    saved=copy.deepcopy(previous)
    saved['bindings']['code']=v.file_ref(v.__file__);saved['bindings']['repair_code']=v.file_ref(__file__)
    responses=list((previous_out/part_id/'data_agents/audit/DC-review').glob('*/response.json'))
    if len(responses)!=1:v.fail('Correction needs one unambiguous returned response')
    response=responses[0]
    saved['model_correction']={'part_id':part_id,'parent_build':v.file_ref(previous_out/'build.json'),
        'request':v.file_ref(response.parent/'request.json'),'response':v.file_ref(response),
        'budget':v.file_ref(previous_out/'model_budget.json'),'code_snapshot':v.file_ref(code_snapshot),
        'repair_snapshot':v.file_ref(repair_snapshot),'findings':v.file_ref(findings_path)}
    built=replay_build(saved,current);sizes=[]
    for payload in built['payloads']:
        request=v.governed_request(payload);size=v._chars(request)
        if size>v.d.REQUEST_BUDGET:v.fail(f"Correction part {payload['part_id']} exceeds 700000: {size}")
        v.write_json(out/'requests'/(payload['part_id']+'.json'),request)
        sizes.append({'part_id':payload['part_id'],'request_chars':size,'units':len(payload['units']),
            'requested_checks':sum(len(u.get('response_criterion_ids',u['criteria'])) for u in payload['units']),
            'preserved_checks':sum(len(u.get('fixed_checks',{})) for u in payload['units'])})
        spec=next((s for s in built.get('imported_parts',[]) if s['part_id']==payload['part_id']),None)
        if spec:
            _,proof=_import_derivation(spec,payload);v.write_json(out/'imports'/(payload['part_id']+'.json'),proof)
    v.write_json(out/'build.json',built)
    v.write_json(out/'model_budget.json',{'build_sha256':v.digest(built),'elapsed_seconds':built['prior_model_seconds'],
        'calls':0,'prior_calls':built['prior_model_calls']})
    v.write_json(out/'preflight.json',{'parts':sizes,'model_calls':0,'model_routing':built['model_routing'],
        'prior_model_seconds':built['prior_model_seconds'],'remaining_model_seconds':v.MODEL_BUDGET_SECONDS-built['prior_model_seconds']})
    return built
