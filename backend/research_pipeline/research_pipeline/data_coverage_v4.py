"""Scope-local coverage facts for DR v4; no adequacy, necessity or release decision."""
import copy
import json
import time
from pathlib import Path
from ctxcomp.io import digest
from ctxcomp.schemas import S, arr, enum, obj
from . import data_agents as d, data_requirement_check as c
from . import data_requirement_plan_v4 as planning, data_coverage_review as original
from . import staged_assessment_policy as policy
from .adequacy import check_ref, file_ref
from .common import read_json, write_json

VERSION = 'COVERAGE_FACTS_4.0'
TRANSPORT_VERSION = 'SCOPED_KEYED_SELECTORS_1.3'
MODEL = 'gpt-6-sol'
MODEL_BUDGET_SECONDS = 1500
STATES = ('SUPPORTED', 'PARTIAL', 'CONFLICT', 'UNRESOLVED', 'DEFERRED')
PENDING_GLOBAL_GATES = ['DC006_METHOD_ASSUMPTION_AND_CONDITION_REVIEW', 'DC007_GLOBAL_CONFLICT_AND_GAP_RECONCILIATION',
    'DC008_FULL_ADEQUACY_AND_HUMAN_CHECKPOINT', 'G008_UNRESOLVED_ITEM_CLOSURE',
    'UNASSIGNED_METHOD_LIBRARY_CONDITIONS', 'METHOD_ELIGIBILITY_AND_SCIENTIFIC_RELEASE']
INSTRUCTIONS = '''Independently check source facts for every supplied unit and every ordered criterion.
Each unit is one immutable source scope and one shared requirement. Its method_uses reuse facts, not
permission to merge different studies, species, regimens, matrices, strains or independent panels.
The source_rows columns are [source_id, kind, item_id, exact original content, citation_index]. Cite ONLY
the explicit citation_index printed on that row. Never count rows, infer offsets, cite ranges, or use
table numbers as citation indices. Whitespace-only rows cannot be evidence. Host materializes exact evidence;
do not copy quotes. Metadata and headers are not body evidence.
Other primary scopes are not evidence for this unit unless source_links explicitly states the relation,
all applicable scope dimensions, and cites original textual notes for BOTH records. Common species,
study name, similar values, response ranking or nearest points do not establish record linkage.
CONTEXT_DEPENDENCY only permits contextual notes/headers; observation transfer requires an explicit
source-supported EXPLICIT_RECORD_LINK. Unsupported panel pairing must remain UNRESOLVED.
Use the source scope's own observations and properly attributed supporting records. Multi-experiment
documents cannot transfer another experiment's regimen, uncertainty or animal identity into this scope.
Checks are an object keyed by the exact criterion ID. Match each description, never approximate position.
SUPPORTED requires all conjuncts: route alone does not establish formulation; CFU/lung is a bacterial
endpoint, not drug concentration. A normative Rule cannot by itself prove an observed local fact.
Global lists of species or input classes describe the project: evaluate the relevant local class, not
whether each mouse PK table also contains rat/rabbit PK, PD, MIC and benchmarks. Keep other scopes distinct.
Ordinary e/x use only the unit's authorized selectors. Foreign-primary evidence must use ce/cx AND
a source_links entry supported by both local and target original notes; neither alone authorizes transfer.
s=status, e=support evidence citation_index values, x=counterevidence
indices, r=short scientific reason, n=concrete needed material/action (NONE only when SUPPORTED).
Preserve BLQ, missingness, incompatible quantities, source conflicts, limitations and original record level.
FULL_REQUIREMENT requires original body evidence for SUPPORTED/PARTIAL. Planned model/target outputs
are not missing raw observations: DEFERRED requires documented producer/output/first dependency and
MAIN/RULE evidence. It is not permission to execute or accept a current missing prerequisite.
Do not decide whether a method can run, waive a project rule, select a model, compute endpoints or fit.
No method-level PASS. Conditions are assessed as facts; applicability/necessity decisions are downstream.
For an unanswered point, inspect the remaining permitted_item_overviews and return relevant additional
search_item_ids with a concrete search_reason. This is a request, not a claim those bodies were read.
Initial assigned-source review cannot return MISSING. Use UNRESOLVED until targeted relevant permitted
sources have actually been inspected. In a TARGETED_COMPLETE round MISSING means only not found in the
recorded scope; new requested sources mean search remains incomplete and MISSING is prohibited.
Different method needs may have the same evidence. Do not repeat entire quotations or provenance JSON.
RQ009/RQ011 shared phase labels do not defer earlier free-exposure/MIC dependencies: retain actual
use-specific timing in reasons; never rewrite the DR phase. All scientific gates remain false.
'''


def fail(message): d.fail('COVERAGE_V4_INVALID', message)
def _unique(values, label):
    if len(values) != len(set(values)): fail('Duplicate '+label)
    return set(values)
def _chars(value): return len(json.dumps(value, ensure_ascii=False))


def response_schema(payload):
    count = max((r[4] for r in payload['source_rows']),default=-1)+1
    index = {'type':'integer', 'minimum':0, 'maximum':max(0,count-1)}
    states = STATES + (('MISSING',) if payload['round'] == 'TARGETED_COMPLETE' else ())
    fields = {}; definitions={}; scopes={s['id']:s for s in payload['scopes']}
    def choices(values):
        if values:return arr({'type':'integer','enum':values})
        result=arr({'type':'integer'});result['maxItems']=0;return result
    authority=[r[4] for r in payload['source_rows'] if r[1] in {'MAIN','RULE'} and r[3].strip()]
    shared=[r[4] for r in payload['source_rows'] if r[3].strip() and (r[2] is None or r[2] in payload['support_item_ids'])]
    primaries=[r[4] for r in payload['source_rows'] if r[3].strip() and r[2] is not None and r[2] not in payload['support_item_ids']]
    definitions['shared_selector']={'type':'integer','enum':shared} if shared else {'type':'integer','maximum':-1,'minimum':0}
    primary_items={item:'primary_item_'+str(i) for i,item in enumerate(dict.fromkeys(
        r[2] for r in payload['source_rows'] if r[2] is not None and r[2] not in payload['support_item_ids']))}
    for item,key in primary_items.items():
        indices=[r[4] for r in payload['source_rows'] if r[2]==item and r[3].strip()]
        definitions[key]={'type':'integer','enum':indices} if indices else {'type':'integer','minimum':0,'maximum':-1}
    definitions['authority_indices']=choices(authority)
    unread=sorted(set(payload['permitted_item_ids'])-set(payload['visible_item_ids']))
    search=arr(enum(*unread)) if unread else arr(S)
    if not unread:search['maxItems']=0
    definitions['search_item_ids']=search
    definitions['deferred_outputs']=arr(obj(producer_task=S,output=S,first_dependency=S,source_indices={'$ref':'#/$defs/authority_indices'}))
    definitions['source_links']=arr(obj(item_id=S,relation=enum('CONTEXT_DEPENDENCY','EXPLICIT_RECORD_LINK'),
        scope_basis=S,reason=S,evidence_indices=arr(index,2)))
    for unit in payload['units']:
        ids=unit.get('response_criterion_ids',[x['id'] for x in unit['criteria']])
        scope=unit['scope_id']; key='scope_'+str(list(scopes).index(scope))
        if key not in definitions:
            local=[r[4] for r in payload['source_rows'] if r[3].strip() and r[2] in scopes[scope]['item_ids']]
            selector={'anyOf':[{'$ref':'#/$defs/shared_selector'}]+([{'type':'integer','enum':local}] if local else [])}
            definitions[key+'_ordinary']=arr(selector)
            foreign_items=[{'$ref':'#/$defs/'+itemkey} for item,itemkey in primary_items.items() if item not in scopes[scope]['item_ids']]
            definitions[key+'_foreign']=arr({'anyOf':foreign_items}) if foreign_items else choices([])
            ordinary={'$ref':'#/$defs/'+key+'_ordinary'};foreign={'$ref':'#/$defs/'+key+'_foreign'}
            definitions[key]=obj(s=enum(*states),e=ordinary,x=ordinary,ce=foreign,cx=foreign,r=S,n=S)
        checks=obj(**{cid:{'$ref':'#/$defs/'+key} for cid in ids})
        fields[unit['unit_id']] = obj(checks=checks, search_item_ids={'$ref':'#/$defs/search_item_ids'}, search_reason=S,
            deferred_outputs={'$ref':'#/$defs/deferred_outputs'},source_links={'$ref':'#/$defs/source_links'})
        if 'response_metadata_fields' in unit:
            props=fields[unit['unit_id']]['properties']
            fields[unit['unit_id']]=obj(**{k:value for k,value in props.items() if k=='checks' or k in unit['response_metadata_fields']})
        if payload['round']=='TARGETED_COMPLETE':
            fields[unit['unit_id']]['properties']['new_counterevidence']=arr(obj(
                criterion_id=enum(*[x['id'] for x in unit['criteria']]),
                source_indices=arr(index,1),reason=S,needed_material=S))
            fields[unit['unit_id']]['required'].append('new_counterevidence')
    schema=obj(request_sha256=S, rows=obj(**fields));schema['$defs']=definitions
    return schema


def governed_request(payload):
    return _capture(payload)


def _transport_payload(payload):
    value=copy.deepcopy(payload)
    if 'repair_scope' in value:
        for unit in value['units']:
            unit['unchanged_prior_check_count']=len(unit.pop('fixed_checks',{}))
    return value


def _capture(payload):
    class Capture(Exception): pass
    private = planning.sf.private_module()
    def capture(p):
        err=Capture(); err.request=d.governed_request(_transport_payload(p)); raise err
    private.governed_request=capture
    try: private.invoke(Path('.'),'DC-review',payload,response_schema(payload),model=MODEL)
    except Capture as result: return result.request
    fail('Request capture reached provider')


def _need(n):
    return {k:copy.deepcopy(n[k]) for k in ('id','description','input_fields','conditions','origin','required_by','method_profile_ids')} | {
        'fields':n['input_fields'], 'task_id':'SOURCE_SCOPE', 'kind':'DATA'}


def _unit_need(n):
    return {k:copy.deepcopy(_need(n)[k]) for k in ('id','task_id','kind','origin','required_by','method_profile_ids')}


def _scope(item, profile):
    return {'id':item, 'item_ids':[item], 'scientific_scope':
        {k:copy.deepcopy(profile.get(k,'NOT_FOUND')) for k in
         ('species','matrix','route','dosing_regimen','record_level','analyte','endpoint_window','observation_source')},
        'identity_policy':'DISTINCT_SOURCE_RECORD; NO CROSS_TABLE_PAIRING_OR_SCOPE_EQUIVALENCE_ASSUMED'}


def build(plan, source_run):
    if plan.get('version') != planning.VERSION: fail('Expected verified DR v4 plan')
    view, inv, catalog, items, incomplete = original._catalog(source_run)
    for name in ('source_view','inventory'):
        if file_ref(Path(source_run)/(name+'.json')) != plan['bindings'][name]: fail('Source checkpoint differs from plan')
    bundle=policy.load_bundle()
    main=read_json(view['main_ref']['path'])
    pp=read_json(plan['provenance']['payload_ref']['path'])
    context=read_json(plan['provenance']['source_catalog_ref']['path'])
    for key,value in context.items(): catalog[key]={'content':value,'kind':'METHOD' if key.startswith('method:') else 'MAIN','item_id':None}
    profiles={p['item_id']:p for p in view['profiles']}
    primaries=[i for i in items if profiles[i].get('role') in {'PK_OBSERVATIONS','PD_OBSERVATIONS','IN_VITRO_TIME_KILL'}]
    supports=[i for i in items if i not in primaries]
    scopes=[]; units=[]; routed=[]
    for item in primaries:
        profile=profiles[item]; scope=_scope(item,profile)
        uses=['MODEL_BASED','NCA'] if profile.get('role')=='PK_OBSERVATIONS' else ['PD_INDEX','PD_TARGET']
        scope['method_uses']=uses; scopes.append(scope)
        for need in plan['requirements']:
            shared=[u for u in need['method_uses'] if u in uses]
            if not shared:
                routed.append({'scope_id':item,'requirement_id':need['id'],'state':'ROUTING_NOT_ASSESSED',
                    'reason':'This source role is routed to other method uses; not a waiver or coverage verdict.'}); continue
            units.append({'unit_id':f'U{len(units)+1:04d}','scope_id':item,'method_uses':shared,
                'requirement':_unit_need(need),'criteria':c.criterion_plan(_need(need))})
    # PTA has no observed human/horse population. This scope checks prospective nonhuman inputs only.
    pta_items=[i for i in supports if profiles[i].get('role') in {'MIC','BINDING'}]
    scopes.append({'id':'NONHUMAN_PTA_DEFINITION','item_ids':pta_items,'method_uses':['PTA'],
        'scientific_scope':{'species':'NONHUMAN_SCENARIO_TO_BE_DEFINED','matrix':'AS_STATED_PER_SOURCE'},
        'identity_policy':'NO POPULATION, VARIABILITY OR CROSS_SPECIES DISTRIBUTION IS INVENTED'})
    for need in plan['requirements']:
        if 'PTA' in need['method_uses']:
            units.append({'unit_id':f'U{len(units)+1:04d}','scope_id':scopes[-1]['id'],'method_uses':['PTA'],
                'requirement':_unit_need(need),'criteria':c.criterion_plan(_need(need))})
    # Partition source scopes, never a scope's criteria. Source data appears once per package.
    chunks=[]; group=[]; total=0
    for scope in scopes:
        selected=[u for u in units if u['scope_id']==scope['id']]
        count=sum(len(u['criteria']) for u in selected)
        if group and total+count>600: chunks.append(group); group=[]; total=0
        group.append(scope); total+=count
    if group:chunks.append(group)
    payloads=[]
    for ix, chunk in enumerate(chunks,1):
        ids={s['id'] for s in chunk}; selected=[u for u in units if u['scope_id'] in ids]
        visible=set(supports)|{i for s in chunk for i in s['item_ids']}
        rows=[[key,value['kind'],value['item_id'],value['content']] for key,value in catalog.items()
              if value['item_id'] in visible or value['item_id'] is None]
        rows=[r+[i] for i,r in enumerate(rows)]
        selected=copy.deepcopy(selected)
        for unit in selected:
            local=[r for r in rows if r[2]==unit['scope_id'] and r[1]=='SOURCE_NOTE']
            unit['local_scope_identity']={'scope_id':unit['scope_id'],'original_notes':
                [{'citation_index':r[4],'source_id':r[0],'text':r[3]} for r in local[:2]],
                'complete_original_note_indices':[r[4] for r in local]}
        payload={'version':VERSION,'transport_version':TRANSPORT_VERSION,'part_id':f'COV{ix:02d}','round':'ASSIGNED_ONLY','instructions':INSTRUCTIONS,
            'policy':bundle['coverage_policy'],'policy_implementation':{'runtime':VERSION,'original_authoring_status_unchanged':True},
            'units':selected,'scopes':chunk,'source_rows':rows,'visible_item_ids':sorted(visible),
            'permitted_item_ids':list(items),'support_item_ids':supports,
            'permitted_item_overviews':[x for x in pp['data_overviews'] if x['item_id'] not in visible],
            'project_context':{k:v for k,v in pp['project_context'].items() if k not in ('objective','scientific_context')},
            'project_rules':pp['project_rules'],'method_knowledge':{k:v for k,v in pp['method_knowledge'].items() if k!='profiles'},
            'incomplete_item_ids':incomplete,'scientific_approval':False}
        # Remove duplicate authoritative method/project text from the transport source rows only.
        # Context rows remain to provide stable source selectors; their full text is the evidence.
        payloads.append(payload)
    bindings={k:plan['bindings'][k] for k in ('main','source_view','inventory','permissions')}
    bindings.update(code=file_ref(__file__),original_catalog_code=file_ref(original.__file__),criterion_code=file_ref(c.__file__),
        policy_manifest=file_ref(policy.DEFAULT_MANIFEST),policy_loader=file_ref(policy.__file__),invocation_code=file_ref(d.__file__))
    return {'version':VERSION,'planning_sha256':digest(plan),'bindings':bindings,'scopes':scopes,
        'routing_not_assessed':routed,'catalog':catalog,'payloads':payloads,'upstream_missing_information':main.get('missing_information',{})}


def _qualify_note_full(need,criteria,allowed_sources,catalog):
    """Fail closed on measurement qualification, without changing the reported source facts."""
    for criterion in criteria:
        if need['kind']!='DATA' or criterion['id']!='FULL_REQUIREMENT' or criterion['status'] not in {'SUPPORTED','PARTIAL'}:
            continue
        for span in criterion['evidence']:
            key=span['source']
            if key not in allowed_sources or key not in catalog or not span['quote'].strip() or span['quote'] not in catalog[key]['content']:
                c.fail('Invalid or unassigned evidence for '+need['id']+': '+key)
        kinds={catalog[e['source']]['kind'] for e in criterion['evidence']}
        if 'SOURCE_NOTE' not in kinds or 'SOURCE_CONTENT' in kinds:continue
        if criterion['status']=='PARTIAL' and criterion['needed_material'].strip().upper() in {'NONE','NOT_FOUND','N/A'}:
            c.fail('An unresolved criterion needs a concrete correction or next action: '+criterion['id'])
        original=copy.deepcopy(criterion)
        qualification='HOST DC005: original measurement-body qualification remains UNRESOLVED; note-reported facts are retained.'
        criterion['status']='UNRESOLVED'
        criterion['reason']=original['reason']+' '+qualification
        action='Qualify the required measurement-body support; reported note facts are not absent and no new-data requirement is inferred.'
        criterion['needed_material']=(original['needed_material']+' ' if original['needed_material'].strip().upper()!='NONE' else '')+action
        criterion['host_qualification']={'version':'NOTE_REPORTED_FACT_MEASUREMENT_QUALIFICATION_1.0','policy':'DC005',
            'original_model_criterion':original,'derived_status':'UNRESOLVED',
            'reason':qualification,'source_kinds_unchanged':True,'not_a_model_judgment':True}


def materialize(raw,payload):
    d.validate_schema(raw,response_schema(payload))
    if any(len(r)!=5 or not isinstance(r[4],int) or r[4]<0 for r in payload['source_rows']):fail('Invalid explicit source citation index')
    indexed={r[4]:r for r in payload['source_rows']}
    if len(indexed)!=len(payload['source_rows']):fail('Duplicate explicit source citation index')
    catalog={r[0]:{'kind':r[1],'item_id':r[2],'content':r[3]} for r in payload['source_rows']}
    if len(catalog)!=len(payload['source_rows']):fail('Duplicate source row')
    permitted=set(payload['permitted_item_ids'])
    scope_map={s['id']:s for s in payload['scopes']}; rows=[]
    def spans(indices):
        _unique(indices,'source indices')
        if not set(indices)<=indexed.keys():fail('Source selector is not present in this frozen request')
        return [{'source':indexed[i][0],'quote':indexed[i][3]} for i in indices]
    for unit in payload['units']:
        answer={**copy.deepcopy(unit.get('fixed_metadata',{})),**raw['rows'][unit['unit_id']]}
        for field,preserved in [('deferred_outputs','preserved_deferred_outputs'),('source_links','preserved_source_links')]:
            if any(value not in answer[field] for value in unit.get(preserved,[])):
                fail('Repair removed a preserved dependency or source relation')
        search=_unique(answer['search_item_ids'],'search targets')
        if not search<=permitted or search & set(payload['visible_item_ids']):fail('Search target is unpermitted or already visible')
        if search and not answer['search_reason'].strip():fail('Search needs a reason')
        allowed_items=set(scope_map[unit['scope_id']]['item_ids']) | set(payload['support_item_ids'])
        allowed_sources=[key for key,value in catalog.items() if value['item_id'] is None or value['item_id'] in allowed_items]
        source_links=[]
        _unique([x['item_id'] for x in answer['source_links']],'linked source items')
        for link in answer['source_links']:
            item=link['item_id']
            if item not in permitted or item not in payload['visible_item_ids'] or item in allowed_items:
                fail('A cross-primary link must identify a distinct visible permitted record')
            evidence=spans(link['evidence_indices'])
            owners={catalog[e['source']]['item_id'] for e in evidence}
            if not owners & set(scope_map[unit['scope_id']]['item_ids']) or item not in owners:
                fail('A source link needs original local and target notes')
            if any(catalog[e['source']]['kind']!='SOURCE_NOTE' for e in evidence):
                fail('A cross-primary link requires original textual notes, not body values, descriptors or headers')
            if not link['reason'].strip() or not link['scope_basis'].strip():fail('A source link needs explicit scientific scope and relation')
            allowed_sources += [key for key,value in catalog.items() if value['item_id']==item and
                (link['relation']=='EXPLICIT_RECORD_LINK' or value['kind'] in {'SOURCE_NOTE','SOURCE_HEADER','DESCRIPTOR'})]
            source_links.append({k:v for k,v in link.items() if k!='evidence_indices'}|{'evidence':evidence,
                'authority':'MODEL_ASSERTED_SOURCE_RELATION; EXACT_LOCAL_AND_TARGET_NOTES_VALIDATED'})
        ids=list(answer['checks'])
        expected=unit.get('response_criterion_ids',[x['id'] for x in unit['criteria']])
        if _unique(ids,'criterion IDs')!=set(expected):fail('Missing or unrelated criterion ID')
        restored=copy.deepcopy(unit.get('fixed_checks',{}));restored.update(answer['checks'])
        if set(restored)!={x['id'] for x in unit['criteria']}:fail('Incomplete frozen check restoration')
        checks=[restored[x['id']] for x in unit['criteria']]
        new_counter=[]
        _unique([x['criterion_id'] for x in answer.get('new_counterevidence',[])],'new counterevidence targets')
        for change in answer.get('new_counterevidence',[]):
            cid=change['criterion_id'];pos=next(i for i,x in enumerate(unit['criteria']) if x['id']==cid)
            if cid not in unit.get('fixed_checks',{}) or checks[pos]['s']!='SUPPORTED':
                fail('New counterevidence targets only an earlier supported criterion')
            evidence=spans(change['source_indices'])
            if any(catalog[e['source']]['item_id'] not in payload.get('newly_read_item_ids',[]) or
                   e['source'] not in allowed_sources for e in evidence):fail('Counterevidence must be newly read and scope-authorized')
            checks[pos].update(s='CONFLICT',x=list(dict.fromkeys(checks[pos]['x']+change['source_indices'])),
                r=checks[pos]['r']+' New source counterevidence: '+change['reason'],n=change['needed_material'])
            new_counter.append({'criterion_id':unit['criteria'][pos]['id'],'previous_status':'SUPPORTED',
                'counterevidence':evidence,'reason':change['reason'],'derivation':'PRESERVED_POSITIVE_EVIDENCE_PLUS_EXPLICIT_NEW_COUNTEREVIDENCE'})
        criteria=[]; details=[]
        for spec, check in zip(unit['criteria'],checks):
            if check['s']=='MISSING' and (payload['round']!='TARGETED_COMPLETE' or search):fail('Incomplete search cannot establish MISSING')
            cross=check.get('ce',[])+check.get('cx',[])
            if any(i not in indexed or indexed[i][2] in allowed_items or indexed[i][2] is None for i in cross):
                fail('Cross-primary selectors must name a distinct explicitly linked record')
            evidence=spans(check['e']+check.get('ce',[])); counter=spans(check['x']+check.get('cx',[]))
            if counter and check['s']=='SUPPORTED':fail('Counterevidence cannot silently retain full support')
            merged=evidence+[x for x in counter if x not in evidence]
            criteria.append({'id':spec['id'],'status':check['s'],'evidence':merged,'reason':check['r'],'needed_material':check['n']})
            details.append({'id':spec['id'],'description':spec['description'],'counterevidence':counter,
                'search_state':'TARGETED_COMPLETE' if payload['round']=='TARGETED_COMPLETE' and not search else 'ASSIGNED_SCOPE_REVIEWED',
                'searched_item_ids':payload['visible_item_ids'],'unread_item_ids':sorted(search)})
        deferred=[{'producer_task':x['producer_task'],'output':x['output'],'evidence':spans(x['source_indices'])} for x in answer['deferred_outputs']]
        _qualify_note_full(unit['requirement'],criteria,allowed_sources,catalog)
        agg=c.aggregate(criteria); status='UNRESOLVED' if agg in {'PARTIAL','CONFLICT'} else agg
        reason='Host aggregate of individually selected criterion facts; no method eligibility decision.'
        needed='; '.join(dict.fromkeys(x['needed_material'] for x in criteria if x['status']!='SUPPORTED')) or 'NONE'
        match={'requirement_id':unit['requirement']['id'],'status':status,
            'source_ids':sorted({e['source'] for x in criteria for e in x['evidence']}),'reason':reason,
            'needed_material':needed,'criteria':criteria,'deferred_outputs':deferred}
        plan={'criteria':unit['criteria'],'allowed_source_ids':allowed_sources,'assigned_item_ids':scope_map[unit['scope_id']]['item_ids'],
            'unresolved_review_items':list(set(payload['incomplete_item_ids']) & set(payload['visible_item_ids'])),
            'search_scope':{'round':payload['round'],'visible_item_ids':payload['visible_item_ids'],'requested_item_ids':sorted(search)}}
        checked=c.validate_match(unit['requirement'],match,plan,catalog)
        for criterion, detail in zip(checked['criteria'],details):criterion.update({k:v for k,v in detail.items() if k!='id'})
        checked.update(unit_id=unit['unit_id'],scope_id=unit['scope_id'],method_uses=unit['method_uses'],
            scope=scope_map[unit['scope_id']]['scientific_scope'],search_item_ids=sorted(search),search_reason=answer['search_reason'],
            allowed_source_ids=allowed_sources,deferred_dependencies=[x['first_dependency'] for x in answer['deferred_outputs']],
            source_links=source_links,new_counterevidence=new_counter)
        rows.append(checked)
    return rows


def prepare(plan_path,source_run,out):
    out=Path(out).resolve()
    if out.exists() and any(out.iterdir()):fail('Use a new output directory')
    plan=planning.verify_plan(plan_path); built=build(plan,source_run)
    built['bindings']['plan']=file_ref(plan_path)
    sizes=[]
    for payload in built['payloads']:
        request=governed_request(payload); size=_chars(request)
        if size>d.REQUEST_BUDGET:fail(f"Part {payload['part_id']} exceeds 700000 characters: {size}; no truncation")
        sizes.append({'part_id':payload['part_id'],'request_chars':size,'units':len(payload['units']),
            'criteria':sum(len(u['criteria']) for u in payload['units']),'sources':len(payload['source_rows'])})
        write_json(out/'requests'/(payload['part_id']+'.json'),request)
    write_json(out/'build.json',built);write_json(out/'preflight.json',{'parts':sizes,'model_calls':0,'version':VERSION})
    return built


def run(plan_path,source_run,out,generator=None):
    out=Path(out);built=prepare(plan_path,source_run,out)
    return _execute(built,out,generator)


def run_prepared(out, part_ids=None, generator=None):
    """Run selected prepared parts; subsequent calls reuse invoke's checked exact-request cache."""
    out=Path(out).resolve(); built=read_json(out/'build.json')
    planning.check_refs(built['bindings'])
    if 'parent_coverage' in built['bindings']:fail('Use run_search for a targeted follow-up')
    plan=planning.verify_plan(built['bindings']['plan']['path'])
    replay=build(plan,Path(built['bindings']['source_view']['path']).parent)
    replay['bindings']['plan']=built['bindings']['plan']
    if 'repair_parent_build' in built['bindings']:
        from . import data_coverage_v4_repair as repair
        replay=repair.replay_build(built,replay)
    if replay!=built:fail('Prepared coverage no longer replays')
    for p in built['payloads']:
        if read_json(out/'requests'/(p['part_id']+'.json'))!=governed_request(p):fail('Prepared request changed')
    selected=set(part_ids) if part_ids is not None else None
    if selected is not None and (not selected or not selected<={p['part_id'] for p in built['payloads']}):
        fail('Select known prepared parts')
    return _execute(built,out,generator,part_ids=selected)


def _execute(built,out,generator=None,parent=None,part_ids=None):
    matches=[];responses=[];start=time.monotonic()
    ledger_path=out/'model_budget.json'
    ledger=read_json(ledger_path) if ledger_path.exists() else {'build_sha256':digest(built),
        'elapsed_seconds':built.get('prior_model_seconds',0.0),'calls':0,'prior_calls':built.get('prior_model_calls',0)}
    if ledger['build_sha256']!=digest(built):fail('Model budget belongs to another build')
    def bounded(request,**options):
        remaining=MODEL_BUDGET_SECONDS-ledger['elapsed_seconds']
        if remaining<=0:fail('Explicit 25-minute stage budget exhausted; no automatic retry')
        planning.sf.emit(out,'MODEL_START',stage=VERSION,part_id=request['payload']['part_id'],
                         request_chars=_chars(request),model=MODEL)
        call_start=time.monotonic()
        try:return (generator or d.codex_generate)(request,timeout=remaining,**options)
        finally:
            elapsed=time.monotonic()-call_start
            ledger['elapsed_seconds']+=elapsed;ledger['calls']+=1;write_json(ledger_path,ledger)
            planning.sf.emit(out,'MODEL_END',stage=VERSION,part_id=request['payload']['part_id'],elapsed_seconds=elapsed)
    identity=d.executor_id(MODEL,generator)
    bounded.executor_id=('COVERAGE_V4:'+identity) if identity else None
    caller=planning.sf.private_module()
    caller.governed_request=lambda payload:d.governed_request(_transport_payload(payload))
    planning.sf.emit(out,'STAGE_START',stage=VERSION,parts=len(built['payloads']),model=MODEL)
    try:
        for payload in built['payloads']:
            if part_ids is not None and payload['part_id'] not in part_ids:continue
            planning.check_refs(built['bindings'])
            prior_calls=ledger['calls']
            imported=None
            if any(x['part_id']==payload['part_id'] for x in built.get('imported_parts',[])):
                from . import data_coverage_v4_repair as repair
                imported=repair.load_imported_response(out,built,payload)
            if imported is not None:
                raw,receipt=imported
                responses.append({'part_id':payload['part_id'],'raw':raw,'import_ref':receipt})
                matches.extend(materialize(raw,payload))
                planning.sf.emit(out,'PART_END',stage=VERSION,part_id=payload['part_id'],provider_calls=0,
                    provenance='AUDITED_SAVED_MODEL_RESPONSE_NORMALIZATION',import_ref=receipt)
                continue
            executor=d.executor_id(MODEL,bounded)
            if executor:
                sha=governed_request(payload)['request_sha256']
                kept=out/payload['part_id']/'data_agents/kept'/(digest({'request_sha256':sha,'executor':executor})+'.json')
                if kept.exists():
                    cached=read_json(kept)
                    if cached.get('request_sha256')!=sha:fail('Checked cache request binding changed; no automatic retry')
                    materialize(cached,payload)  # A corrupted cache stops, never triggers invoke's fallback call.
            raw=caller.invoke(out/payload['part_id'],'DC-review',payload,response_schema(payload),model=MODEL,generator=bounded,
                         check=lambda raw: bool(materialize(raw,payload)))
            responses.append({'part_id':payload['part_id'],'raw':raw});matches.extend(materialize(raw,payload))
            planning.sf.emit(out,'PART_END',stage=VERSION,part_id=payload['part_id'],elapsed_seconds=time.monotonic()-start,
                             provider_calls=ledger['calls']-prior_calls)
        if len(responses)!=len(built['payloads']):
            checkpoint={'status':'PARTIAL_COVERAGE_CHECKPOINT','completed_in_invocation':[r['part_id'] for r in responses],
                        'pending_parts':[p['part_id'] for p in built['payloads'] if p['part_id'] not in part_ids],
                        'model_budget':ledger,'scientific_approval':False}
            write_json(out/'checkpoint.json',checkpoint)
            planning.sf.emit(out,'STAGE_END',stage=VERSION,status=checkpoint['status'],elapsed_seconds=time.monotonic()-start)
            return checkpoint
        write_json(out/'responses.json',responses)
        if parent is not None:
            replaced={r['unit_id']:r for r in matches}
            matches=[replaced.get(r['unit_id'],r) for r in parent['matches']]
        result={'version':VERSION,'planning_sha256':built['planning_sha256'],'bindings':built['bindings'],
            'scopes':built['scopes'],'matches':matches,'routing_not_assessed':built['routing_not_assessed'],
            'pending_searches':[{'unit_id':m['unit_id'],'item_ids':m['search_item_ids'],'reason':m['search_reason']} for m in matches if m['search_item_ids']],
            'upstream_missing_information':built['upstream_missing_information'],'scientific_approval':False,'can_enter_qc':False,'fit_ready':False,
            'assessment_scope':'LOCAL_SOURCE_FACTS_ONLY; NOT_FULL_DC_ADEQUACY_OR_RELEASE',
            'pending_global_gates':PENDING_GLOBAL_GATES,
            'missingness_assessment':'INCOMPLETE_WHERE_SEARCH_STATE_IS_NOT_TARGETED_COMPLETE; NO_GLOBAL_MISSING_CLAIM',
            'provenance':{'build_ref':file_ref(out/'build.json'),'responses_ref':file_ref(out/'responses.json'),'model':MODEL,
                          'model_routing':built.get('model_routing',{'new_calls_model':MODEL})}}
        if 'parent_coverage' in built['bindings']:result['provenance']['parent_coverage_ref']=built['bindings']['parent_coverage']
        write_json(out/'coverage.json',result);verify_result(out/'coverage.json')
        planning.sf.emit(out,'STAGE_END',stage=VERSION,elapsed_seconds=time.monotonic()-start)
        return result
    except Exception as exc:
        planning.sf.emit(out,'STAGE_ERROR',stage=VERSION,reason=str(exc),elapsed_seconds=time.monotonic()-start);raise


def verify_result(path):
    result=read_json(path)
    if result.get('version')!=VERSION:fail('Unknown coverage version')
    planning.check_refs(result['bindings']);planning.check_refs(result['provenance'])
    plan=planning.verify_plan(result['bindings']['plan']['path'])
    if digest(plan)!=result['planning_sha256']:fail('Wrong plan digest')
    built=read_json(result['provenance']['build_ref']['path']);raws=read_json(result['provenance']['responses_ref']['path'])
    parent=None
    if 'parent_coverage_ref' in result['provenance']:
        parent=verify_result(result['provenance']['parent_coverage_ref']['path'])
        replay=_search_build(result['provenance']['parent_coverage_ref']['path'],built['selected_unit_ids'])
    else:
        replay=build(plan,Path(result['bindings']['source_view']['path']).parent);replay['bindings']['plan']=result['bindings']['plan']
        if 'repair_parent_build' in result['bindings']:
            from . import data_coverage_v4_repair as repair
            replay=repair.replay_build(built,replay)
    if replay!=built:fail('Coverage build does not replay')
    expected=[]
    if [r['part_id'] for r in raws]!=[p['part_id'] for p in built['payloads']]:fail('Incomplete parts')
    for raw,payload in zip(raws,built['payloads']):
        if 'import_ref' in raw:
            from . import data_coverage_v4_repair as repair
            check_ref(raw['import_ref'])
            imported=repair.load_imported_response(Path(result['provenance']['build_ref']['path']).parent,built,payload)
            if imported is None or raw['raw']!=imported[0] or raw['import_ref']!=imported[1]:fail('Saved-response import does not replay')
        elif raw['raw']['request_sha256']!=governed_request(payload)['request_sha256']:fail('Stale part response')
        expected.extend(materialize(raw['raw'],payload))
    if parent is not None:
        replaced={r['unit_id']:r for r in expected};expected=[replaced.get(r['unit_id'],r) for r in parent['matches']]
    if expected!=result['matches']:fail('Coverage facts differ from raw derivation')
    pending=[{'unit_id':m['unit_id'],'item_ids':m['search_item_ids'],'reason':m['search_reason']} for m in expected if m['search_item_ids']]
    if pending!=result['pending_searches']:fail('Search obligations changed')
    if result.get('pending_global_gates')!=PENDING_GLOBAL_GATES:fail('Global pending gates changed')
    if result.get('assessment_scope')!='LOCAL_SOURCE_FACTS_ONLY; NOT_FULL_DC_ADEQUACY_OR_RELEASE':fail('Assessment scope changed')
    for key in ('scopes','routing_not_assessed','upstream_missing_information'):
        if result[key]!=built[key]:fail('Altered '+key)
    if any(result[k] is not False for k in ('scientific_approval','can_enter_qc','fit_ready')):fail('No scientific release')
    return result


def result_sources(path):
    result=verify_result(path);built=read_json(result['provenance']['build_ref']['path'])
    return built['catalog']


def _search_build(coverage_path,unit_ids=None):
    parent=verify_result(coverage_path)
    if 'parent_coverage_ref' in parent['provenance']:fail('No automatic multi-round search chain')
    original_build=read_json(parent['provenance']['build_ref']['path'])
    ledger_path=Path(parent['provenance']['build_ref']['path']).parent/'model_budget.json'
    ledger=read_json(ledger_path)
    if ledger['build_sha256']!=digest(original_build):fail('Targeted-search parent budget is not bound to the parent build')
    originals={r['part_id']:r['raw'] for r in read_json(parent['provenance']['responses_ref']['path'])}
    pending={r['unit_id']:r for r in parent['matches'] if r['search_item_ids']}
    selected=list(unit_ids) if unit_ids is not None else list(pending)
    if not selected or not _unique(selected,'targeted units')<=pending.keys():fail('Select actual pending searches only')
    built=copy.deepcopy(original_build);built['payloads']=[];built['selected_unit_ids']=selected
    built['bindings']['parent_coverage']=file_ref(coverage_path)
    built['bindings']['parent_model_budget']=file_ref(ledger_path)
    built['prior_model_seconds']=ledger['elapsed_seconds']
    built['prior_model_calls']=ledger.get('prior_calls',0)+ledger['calls']
    for payload in original_build['payloads']:
        targets=[u for u in payload['units'] if u['unit_id'] in selected]
        if not targets:continue
        # Preserve the original source indices; append only the explicitly requested permitted sources.
        extra={i for u in targets for i in pending[u['unit_id']]['search_item_ids']}
        p=copy.deepcopy(payload);p['part_id']+='-SEARCH';p['round']='TARGETED_COMPLETE';p['units']=copy.deepcopy(targets)
        present={r[0] for r in p['source_rows']}
        appended=[[k,v['kind'],v['item_id'],v['content']] for k,v in built['catalog'].items() if v['item_id'] in extra and k not in present]
        next_index=max(r[4] for r in p['source_rows'])+1
        p['source_rows'] += [r+[next_index+i] for i,r in enumerate(appended)]
        p['visible_item_ids']=sorted(set(p['visible_item_ids'])|extra)
        p['newly_read_item_ids']=sorted(extra)
        p['permitted_item_overviews']=[x for x in p['permitted_item_overviews'] if x['item_id'] not in extra]
        for u in p['units']:
            old=originals[payload['part_id']]['rows'][u['unit_id']]
            prior_checks=copy.deepcopy(u.get('fixed_checks',{}));prior_checks.update(old['checks'])
            statuses={c['id']:c['status'] for c in pending[u['unit_id']]['criteria']}
            u['response_criterion_ids']=[spec['id'] for spec in u['criteria'] if statuses[spec['id']]!='SUPPORTED']
            u['fixed_checks']={spec['id']:prior_checks[spec['id']] for spec in u['criteria'] if statuses[spec['id']]=='SUPPORTED'}
            u['targeted_search_reason']=pending[u['unit_id']]['search_reason']
        p['instructions']+='\nFor targeted units return checks only for response_criterion_ids. Earlier supported fixed_checks are preserved; if newly read evidence contradicts one, use new_counterevidence with its exact criterion_id. Host preserves old positive evidence and records CONFLICT rather than silently overwriting it. source_links may explicitly establish an original-source relation in this same review; undeclared other-primary evidence remains prohibited.'
        built['payloads'].append(p)
    return built


def prepare_search(coverage_path,out,unit_ids=None):
    out=Path(out)
    if out.exists() and any(out.iterdir()):fail('Use a new targeted-search directory')
    built=_search_build(coverage_path,unit_ids);sizes=[]
    for payload in built['payloads']:
        request=governed_request(payload);size=_chars(request)
        if size>d.REQUEST_BUDGET:fail('Targeted search exceeds unchanged 700000 budget; no truncation')
        sizes.append({'part_id':payload['part_id'],'request_chars':size})
        write_json(out/'requests'/(payload['part_id']+'.json'),request)
    write_json(out/'build.json',built);write_json(out/'preflight.json',{'parts':sizes,'model_calls':0})
    return built


def run_search(coverage_path,out,unit_ids=None,generator=None):
    built=prepare_search(coverage_path,out,unit_ids)
    return _execute(built,Path(out),generator,verify_result(coverage_path))
