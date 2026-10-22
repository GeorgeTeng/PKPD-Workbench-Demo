"""Post-source DR: unchanged source notes and checked profiles inform candidate requirements."""
import copy
import json
import re
from pathlib import Path
from ctxcomp.io import leaves
from ctxcomp.schemas import obj,arr,S,enum
from . import data_agents as d,method_profiles as mp,data_source_first_workflow as sf
from .data_test_workflow import embedded_projection
from .adequacy import file_ref
from .common import read_json,write_json

RULE_FIELDS=('id','kind','text','conditions','exceptions','scope','requirement','usage','stages','context_path')
METHOD_FEASIBILITY=obj(task_id=S,status=enum('CONDITIONAL_CANDIDATE','UNRESOLVED','UNAVAILABLE'),
    approaches=arr(obj(description=S,method_profile_ids=arr(S),applicability_conditions=arr(S),
        available_inputs=arr(S),missing_inputs=arr(S),evidence=arr(d.EVIDENCE,1))),
    proposed_requirement_followups=arr(S),reason=S,evidence=arr(d.EVIDENCE,1))
INSTRUCTIONS=('Organize Data Requirements AFTER reading the actual permitted source profiles and complete original source_units, including all notes. '
 'Retain every explicit project objective even when its data are missing. The reused Sol labels were conditioned on historical requirements; '
 'their old associations, reasons and finding target IDs are historical, not restrictions on the present organization. Do not reuse an old Q ID: '
 'new task IDs start SFT and new requirement IDs start SFQ. Preserve all scientific limitations and conflicts in legacy_findings. '
 'Profiles omit the duplicate stated_values extraction array only in this request: every underlying original note/line remains in source_units. '
 'Read those original notes, including regimen, units/basis, missingness, BLQ, identity and timing; record counts do not prove adequacy. '
 'Descriptor source_notes/linked_notes fields are omitted only where each exact line is already present as a source unit of that same item; cite those unchanged individual source units. '
 'Separate PROJECT_EXPLICIT from conditional METHOD_CANDIDATE. A candidate must cite a supplied method:MP profile, exact project objective/rule '
 'evidence showing applicability, explicit applicability conditions, and relevant actual source evidence when data or notes prompted it. '
 'A generic PK objective does not explicitly request terminal NCA parameters. Omit unsupported methodological obligations with a finding; '
 'do not promote a conditional candidate into an adopted project requirement. Keep source facts separate from future calculated outputs. '
 'Each needed field, relationship, window or condition must be independently checkable. No fits, selection, adequacy decision or permission change. '
 'For every permitted item, data_links assigns potentially related NEW requirement IDs, or gives an evidence-based reason for no assignment; '
 'an association is not a claim that a requirement is met. Do not omit relevant unmatched or conflicting material. '
 'For every objective_source_id, objective_coverage records applicable new requirement IDs or a source-grounded reason that no new requirement is needed. '
 'Project rule semantic fields are copied exactly; upstream annotation/provenance records stay in the verified main and are not scientific instructions. '
 'Cite rules via exact main:/rules/<index>/<field> leaf paths from the supplied rule context_path, with a quote from that field; '
 'cite other main leaves through context_sources, methods as method:MPxxx, and actual data/notes through source_units. '
 'Never cite a model label, record count or finding as original source evidence. '+d.WARNING_INSTRUCTIONS)


def response_schema(item_ids,objective_ids,rule_ids):
    schema=copy.deepcopy(d.DEFINITION)
    task=schema['properties']['tasks']['items'];need=schema['properties']['requirements']['items']
    task['properties']['id']={'type':'string','pattern':'^SFT[0-9]+$'}
    need['properties']['id']={'type':'string','pattern':'^SFQ[0-9]+$'}
    need['properties']['task_id']={'type':'string','pattern':'^SFT[0-9]+$'}
    need['properties']['rule_ids']=arr(enum(*rule_ids)) if rule_ids else {'type':'array','items':S,'maxItems':0}
    schema['properties']['data_links']=arr(obj(item_id=enum(*item_ids),requirement_ids=arr(S),reason=S,evidence=arr(d.EVIDENCE,1)))
    schema['properties']['objective_coverage']=arr(obj(source=enum(*objective_ids),requirement_ids=arr(S),reason=S,evidence=arr(d.EVIDENCE,1)))
    schema['required']+=['data_links','objective_coverage']
    return schema


def build_payload(main,view,knowledge):
    rules=embedded_projection(main,d.DATA_STAGES)
    full_sources=d.source_map(main,rules)
    context={k:v for k,v in full_sources.items() if k.startswith('main:') and not k.startswith('main:/rules/')}
    # The semantic rule objects supply these exact leaves once, not a second duplicate source map.
    semantic=[{k:copy.deepcopy(r[k]) for k in RULE_FIELDS if k in r} for r in rules]
    profiles=[]
    for original in view['profiles']:
        p={k:copy.deepcopy(v) for k,v in original.items() if k not in ('stated_values','evidence_source_ids')}
        p['checked_stated_value_count']=len(original['stated_values'])
        profiles.append(p)
    objectives=['main:/objective']
    objectives += ['main:/scientific_context/items/'+str(i)+'/statement' for i,x in enumerate(main['scientific_context']['items']) if 'statement' in x]
    if len(objectives)==1:
        objectives += ['main:/scientific_context/items/'+str(i)+'/'+k for i,x in enumerate(main['scientific_context']['items'])
                       for k in ('claim','text','content') if k in x]
    objectives += ['main:/missing_information/items/'+str(i)+'/field' for i in range(len(main.get('missing_information',{}).get('items',[])))]
    if not all(x in context for x in objectives):sf.fail('Objective coverage must name actual exact context leaves')
    units=copy.deepcopy(view['source_units'])
    for profile in view['profiles']:
        item_id=profile['item_id'];descriptor=json.loads(units[item_id])
        same_item_values={v for k,v in units.items() if k.startswith(item_id+':')}
        for key in ('source_notes','linked_notes'):
            if key in descriptor and all(line in same_item_values for line in descriptor[key].split('\n')):
                del descriptor[key]
        units[item_id]=json.dumps(descriptor,ensure_ascii=False)
    payload={'operation':'ORGANIZE_REQUIREMENTS_AFTER_SOURCE_REVIEW','objective':main['objective'],
        'context_sources':context,'project_rules':semantic,'method_knowledge':knowledge,
        'data_profiles':profiles,'source_units':units,'legacy_findings':view['legacy_findings'],
        'objective_source_ids':objectives,'instructions':INSTRUCTIONS}
    schema=response_schema([p['item_id'] for p in profiles],objectives,[r['id'] for r in rules])
    sources={**full_sources,**view['source_units'],**mp.evidence_sources(knowledge)}
    # Do not authorize citations to hidden rule audit fields or old rule JSON copies.
    allowed=set(context)|set(view['source_units'])|set(mp.evidence_sources(knowledge))
    for r in semantic:
        raw=main['rules'][int(r['context_path'].split('/')[-1])]
        for key in RULE_FIELDS:
            if key not in raw:continue
            for path,value in leaves(raw[key]):allowed.add('main:'+r['context_path']+'/'+key+path)
    sources={k:v for k,v in sources.items() if k in allowed}
    return payload,schema,sources


def validate_response(response,payload,sources,knowledge):
    tasks=[x['id'] for x in response['tasks']];needs=[x['id'] for x in response['requirements']]
    d.exact(tasks,tasks,'Task IDs');d.exact(needs,needs,'Requirement IDs')
    rules={r['id'] for r in payload['project_rules']}
    mp.validate_requirements(response['requirements'],knowledge)
    def evidence(spans):
        d.evidence_check(spans,sources)
        d.evidence_check([e for e in spans if e['source'] in payload['source_units']],payload['source_units'])
    for task in response['tasks']:evidence(task['evidence'])
    for need in response['requirements']:
        if need['task_id'] not in tasks or not set(need['rule_ids'])<=rules:sf.fail('Unknown task or project rule')
        evidence(need['evidence'])
    d.exact([x['item_id'] for x in response['data_links']],[x['item_id'] for x in payload['data_profiles']],'Post-source item coverage')
    d.exact([x['source'] for x in response['objective_coverage']],payload['objective_source_ids'],'Post-source objective coverage')
    for link in response['data_links']+response['objective_coverage']:
        if len(link['requirement_ids'])!=len(set(link['requirement_ids'])) or not set(link['requirement_ids'])<=set(needs):sf.fail('Unknown or repeated new requirement association')
        if not link['reason'].strip():sf.fail('Every association or explicit non-assignment needs a reason')
        evidence(link['evidence'])
    for link in response['data_links']:
        if not any(e['source']==link['item_id'] or e['source'].startswith(link['item_id']+':') for e in link['evidence']):
            sf.fail('An item association or non-assignment needs evidence from that actual item')
    for row in response['objective_coverage']:
        allowed={row['source']}
        mi=re.fullmatch(r'main:/missing_information/items/(\d+)/field',row['source'])
        if mi:
            allowed.update('main:/missing_information/items/'+mi[1]+'/'+field
                for field in ('field','clarification','impact','why_it_matters'))
        if not any(e['source'] in allowed for e in row['evidence']):sf.fail('Objective coverage must cite its own exact source or same canonical MI record')
    return True


def validate_method_feasibility(rows,tasks,sources,knowledge):
    d.exact([x['task_id'] for x in rows],[x['id'] for x in tasks],'Task method feasibility')
    profiles={p['id'] for p in mp.check_context(knowledge)['profiles']}
    for row in rows:
        d.validate_schema(row,METHOD_FEASIBILITY);d.evidence_check(row['evidence'],sources)
        if not any(e['source'].startswith(('main:','rule:')) for e in row['evidence']):sf.fail('Task feasibility must retain project authority')
        if not row['reason'].strip():sf.fail('Method feasibility requires an explicit reason')
        for approach in row['approaches']:
            ids=approach['method_profile_ids'];cited={e['source'].removeprefix('method:') for e in approach['evidence'] if e['source'].startswith('method:')}
            if len(ids)!=len(set(ids)) or not set(ids)<=profiles or cited!=set(ids):sf.fail('Candidate method profile references/evidence differ')
            if not approach['applicability_conditions']:sf.fail('A possible method must remain conditional')
            if not any(not e['source'].startswith('method:') for e in approach['evidence']):sf.fail('Method library alone cannot establish project/data feasibility')
            d.evidence_check(approach['evidence'],sources)
    return True


def organize(run,*,generator=None):
    run=Path(run);manifest,verified=sf.verify_run(run)
    if (run/'requirements.json').exists():sf.fail('Post-source DR already published; do not resample')
    view=read_json(run/'source_view.json')
    if view['pending_item_ids']:sf.fail('Complete explicitly pending source repairs before DR')
    inv=read_json(run/'inventory.json')
    source_refs=[item[k] for item in inv['items'] for k in ('source','snapshot') if item.get(k)]
    for reference in source_refs:d.check_ref(reference)
    knowledge=mp.planning_context();payload,schema,sources=build_payload(verified['main'],view,knowledge)
    knowledge_ref=file_ref(write_json(run/'data_agents/method_context.json',knowledge))
    source_ref=file_ref(write_json(run/'data_agents/source_first_evidence.json',sources))
    write_json(run/'organize_stage_bindings.json',{'code_ref':file_ref(__file__),'source_view_ref':file_ref(run/'source_view.json'),
        'method_knowledge_ref':knowledge_ref,'source_catalog_ref':source_ref,'scientific_approval':False})
    result=sf.invoke(run,'DR',payload,schema,generator=generator,
        check=lambda r:validate_response(r,payload,sources,knowledge))
    sf.verify_run(run)
    for reference in source_refs+list(read_json(run/'organize_stage_bindings.json').values()):
        if isinstance(reference,dict) and 'sha256' in reference:d.check_ref(reference)
    return publish_checked(run,result,knowledge_ref,source_ref,file_ref(run/'organize_stage_bindings.json'))


def publish_checked(run,result,knowledge_ref,source_ref,stage_ref):
    """Publish an already checked complete candidate; scoped repairs pass their own derivation proof."""
    run=Path(run);manifest,verified=sf.verify_run(run)
    if (run/'requirements.json').exists():sf.fail('An organized candidate is already published')
    for reference in (knowledge_ref,source_ref,stage_ref):d.check_ref(reference)
    view=read_json(run/'source_view.json');inv=read_json(run/'inventory.json')
    payload,schema,sources=build_payload(verified['main'],view,read_json(knowledge_ref['path']))
    base={k:v for k,v in result.items() if k!='method_feasibility'}
    d.validate_schema(base,schema);validate_response(base,payload,sources,read_json(knowledge_ref['path']))
    if 'method_feasibility' in result:
        validate_method_feasibility(result['method_feasibility'],result['tasks'],sources,read_json(knowledge_ref['path']))
    permissions=read_json(run/'permissions.json')['access']
    links={x['item_id']:x for x in result['data_links']}
    access=[{**copy.deepcopy(a),'requirement_ids':links.get(a['item_id'],{}).get('requirement_ids',[])} for a in permissions]
    requirement_path=write_json(run/'requirements.json',{'schema_version':d.VERSION,**result,'main':manifest['bindings']['main'],
        'inventory':file_ref(run/'inventory.json'),'access':access,'method_knowledge_ref':knowledge_ref,
        'source_first_evidence_ref':source_ref,'source_view_ref':file_ref(run/'source_view.json'),
        'source_first_stage_ref':stage_ref,'scientific_approval':False})
    imported=read_json(run/'legacy_import.json');fixed=read_json(run/'repaired_document.json')
    labels=copy.deepcopy(imported['labels']+fixed['labels'])
    for label in labels:
        label['requirement_ids']=links[label['item_id']]['requirement_ids']
        # Keep historical reason text intact but never let it limit the new association.
    stated,conflicts=d.stated_values(labels,{i['id']:i for i in inv['items']})
    coverage=list(imported['coverage'])+[{'item_id':fixed['labels'][0]['item_id'],'status':'BODY_REVIEWED','pages':1,
        'units_read':len([k for k in view['source_units'] if k.startswith(fixed['labels'][0]['item_id']+':')])}]
    present={x['item_id'] for x in coverage}
    coverage += [{'item_id':a['item_id'],'status':a['disposition'],'reason':a['reason'],'units_read':0}
                 for a in permissions if a['item_id'] not in present]
    d.exact([x['item_id'] for x in coverage],[i['id'] for i in inv['items']],'Complete source coverage')
    findings=copy.deepcopy(view['legacy_findings'])
    for finding in conflicts:
        if finding not in findings:findings.append(finding)
    write_json(run/'labels.json',{'schema_version':d.VERSION,'requirements':file_ref(requirement_path),
        'labels':labels,'stated_values':stated,'coverage':coverage,'findings':findings,'fit_ready':False,
        'model':'MIXED_PROVENANCE','original_label_model':'gpt-6-sol','citation_patch_model':sf.MODEL,
        'association_model':sf.MODEL,'legacy_association_history_ref':file_ref(run/'source_view.json'),
        'interpretation':'Scientific labels and historical reasons were preserved; only requirement_ids were assigned by post-source DR. Historical finding target IDs do not bind new SFQ requirements.',
        'scientific_approval':False})
    sf.bind_outputs(run,('requirements.json','labels.json','organize_stage_bindings.json'))
    return {'status':'POST_SOURCE_REQUIREMENTS_ORGANIZED','tasks':len(result['tasks']),
        'requirements':len(result['requirements']),'labels':len(labels),'model':sf.MODEL,
        'can_enter_qc':False,'scientific_approval':False}
