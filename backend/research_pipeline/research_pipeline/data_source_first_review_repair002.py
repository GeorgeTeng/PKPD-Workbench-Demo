"""Eight fixed REVIEW_002 rows with per-requirement source-choice schemas."""
import copy,json
from ctxcomp.schemas import obj,arr,S,enum
from . import data_source_first_review_repair as r

VERSION='SOURCE_FIRST_REVIEW_PATCH_CONTINUATION_2.0'
TARGETS=[('SFQ6','FULL_REQUIREMENT'),('SFQ8','FULL_REQUIREMENT'),('SFQ15','SCOPE_ALIGNMENT'),
         ('SFQ16','FIELD_003'),('SFQ16','FIELD_004'),('SFQ16','SCOPE_ALIGNMENT'),('SFQ17','FIELD_006'),('SFQ17','SCOPE_ALIGNMENT')]


def prepare(parent_contract,request_path,response_path,out):
    c={'version':VERSION,'parent_contract_ref':r.file_ref(parent_contract),'original_patch_request_ref':r.file_ref(request_path),
       'fixed_patch_ref':r.file_ref(response_path),'targets':[{'requirement_id':rid,'criterion_id':cid,'key':rid+'__'+cid} for rid,cid in TARGETS],
       'deferred_target':'SFQ16/0','scientific_approval':False}
    load(c);r.write_json(out,c);return c


def load(c):
    if c['version']!=VERSION or c['targets']!=[{'requirement_id':rid,'criterion_id':cid,'key':rid+'__'+cid} for rid,cid in TARGETS] or c['deferred_target']!='SFQ16/0':r.sf.fail('Unknown REVIEW_002 continuation scope')
    for key in ['parent_contract_ref','original_patch_request_ref','fixed_patch_ref']:r.check_ref(c[key])
    parent=r.read_json(c['parent_contract_ref']['path']);q=r.read_json(c['original_patch_request_ref']['path']);a=r.read_json(c['fixed_patch_ref']['path'])
    if parent['part_id']!='REVIEW_002' or q!=r.request_for(r.payload(parent),r.schema(parent)) or a['request_sha256']!=q['request_sha256']:r.sf.fail('Saved REVIEW_002 patch binding differs')
    r.d.validate_schema(a,r.schema(parent));full,part,old=r._load(parent)
    return parent,full,part,old,a


def sources(c):
    parent,full,part,old,raw=load(c);p=r.payload(parent);visible=r.review.visible_sources(p);catalog={};targets={}
    for target in c['targets']:
        rid=target['requirement_id'];plan=next(x for x in full['criterion_plans'] if x['requirement_id']==rid)
        need=next(x for x in full['requirements']['requirements'] if x['id']==rid);choices=[];body=[]
        for source in plan['allowed_source_ids']:
            entry=full['evidence_catalog'].get(source)
            if not entry or source not in visible:continue
            field='CONTENT';quote=entry['content']
            if source.startswith('rule:'):
                projected=next((x for x in p['project_rules'] if source=='rule:'+x['id']),None)
                if not projected:continue
                field='text';quote=json.dumps(projected['text'],ensure_ascii=False)
            if not quote.strip() or quote not in visible[source] or quote not in entry['content']:continue
            catalog[source]={'kind':entry['kind'],'content':quote,'selector':{'source':source,'field':field}}
            choices.append({'choice':source,'kind':entry['kind']})
            if entry['kind']=='SOURCE_CONTENT':body.append(source)
        if not choices:r.sf.fail('No verified visible choices for target '+target['key'])
        targets[target['key']]={'requirement':copy.deepcopy(need),'criterion':next(x for x in plan['criteria'] if x['id']==target['criterion_id']),
            'allowed_source_choices':choices,'body_evidence_choices':body,
            'search_scope':copy.deepcopy(plan['search_scope']),'unresolved_review_items':copy.deepcopy(plan['unresolved_review_items']),
            'task':next(t for t in full['requirements']['tasks'] if t['id']==need['task_id'])}
    source='main:/rules/10/text';entry=full['evidence_catalog'][source]
    plan=next(x for x in full['criterion_plans'] if x['requirement_id']=='SFQ16')
    if source not in plan['allowed_source_ids'] or entry['kind']!='MAIN' or entry['content'] not in visible.get(source,''):r.sf.fail('Fixed deferred authorization source differs')
    catalog[source]={'kind':'MAIN','content':entry['content'],'selector':{'source':source,'field':'CONTENT'}}
    return targets,catalog,p['project_rules']


def schema(c):
    targets,catalog,rules=sources(c);rows={}
    for key,target in targets.items():
        props={'status':r.STATUS,'reason':S,'needed_material':S,'evidence_choices':arr(enum(*(x['choice'] for x in target['allowed_source_choices'])))}
        if key.endswith('__FULL_REQUIREMENT'):
            props['body_evidence_choice']=enum('NONE',*target['body_evidence_choices'])
            if not target['body_evidence_choices']:props['status']=enum('UNRESOLVED','CONFLICT','MISSING','DEFERRED')
        rows[key]=obj(**props)
    return obj(request_sha256=S,row_replacements=obj(**rows),deferred_evidence_choice=enum('main:/rules/10/text'))


def payload(c):
    parent,full,part,old,raw=load(c);targets,catalog,rules=sources(c)
    selected_rules={source.removeprefix('rule:') for source in catalog if source.startswith('rule:')}
    selected_rules|={rid for target in targets.values() for rid in target['requirement']['rule_ids']}
    deferred=next(m for m in old['matches'] if m['requirement_id']=='SFQ16')['deferred_outputs'][0]
    return {'operation':'REPAIR_EIGHT_ROWS_OF_FIXED_REVIEW002_PATCH','part_id':'REVIEW_002_TARGET_CONTINUATION','version':VERSION,
        'fixed_patch_sha256':c['fixed_patch_ref']['sha256'],'targets':targets,'source_catalog':catalog,
        'project_rules':[x for x in rules if x['id'] in selected_rules],
        'deferred_target':{'target':'SFQ16/0','producer_task':deferred['producer_task'],'output':deferred['output'],
            'only_authorization_choice':'main:/rules/10/text'},
        'instructions':'Return the eight named row properties ONLY, plus the explicitly requested deferred evidence choice. '
            'Each target has its OWN requirement, criterion and allowed_source_choices with original kinds. Only choose from THAT target list; '
            'a source allowed to another SFQ is not transferable. All unchanged prior output and original valid criteria stay fixed. '
            'Source original text appears once in source_catalog; each choice explicitly maps to a canonical source/field. Do not invent main '
            'leaf addresses or neighboring rule indices. source_catalog.content is the unchanged text, or exact JSON-encoded operative rule '
            'text field for rule:Rxxx; the host materializes those quotes. '
            'For a DATA FULL_REQUIREMENT, SUPPORTED or PARTIAL needs a selected body_evidence_choice whose original kind is SOURCE_CONTENT. '
            'Numeric SOURCE_HEADER/SOURCE_NOTE/MAIN text is not observation-body evidence. If no body support can substantiate availability, '
            'choose an honest unresolved status and action; preserve contradictions and conditions rather than selecting a convenient source. '
            'For other criteria, decide against the complete need and its scope, with original evidence or explicit uncertainty. '
            'SFQ16 is the held-out horse branch: in-vitro MIC rules and Rabbit statements are not its evidence. '
            'The deferred producer/output stay locked; select only the displayed already-correct main:/rules/10/text authorization. The prior '
            'README citation remains in audit and other criteria; it is not an adopted project-rule authorization. '
            'No models, fits or scientific approvals are performed. Host source scope, body checks and aggregation are unchanged. '+r.review.coverage.INSTRUCTIONS}


def derive(answer,c):
    parent,full,part,old,fixed=load(c);r.d.validate_schema(answer,schema(c));targets,catalog,rules=sources(c);corrected=copy.deepcopy(fixed)
    for target in c['targets']:
        row=answer['row_replacements'][target['key']];choices=list(row['evidence_choices'])
        if len(choices)!=len(set(choices)):r.sf.fail('Duplicate selector choices')
        if 'body_evidence_choice' in row:
            body=row['body_evidence_choice']
            if row['status'] in {'SUPPORTED','PARTIAL'} and body=='NONE':r.sf.fail('Positive FULL_REQUIREMENT requires explicit body evidence choice')
            if body!='NONE' and body not in choices:choices.append(body)
        replacement={'requirement_id':target['requirement_id'],'criterion_id':target['criterion_id'],
            **{k:row[k] for k in ['status','reason','needed_material']},'evidence_selectors':[copy.deepcopy(catalog[key]['selector']) for key in choices]}
        index=next(i for i,x in enumerate(corrected['criterion_corrections']) if x['requirement_id']==target['requirement_id'] and x['criterion_id']==target['criterion_id'])
        corrected['criterion_corrections'][index]=replacement
    corrected['deferred_evidence_corrections']=[{'target':'SFQ16/0','evidence_selectors':[copy.deepcopy(catalog[answer['deferred_evidence_choice']]['selector'])]}]
    result,audit=r.derive(corrected,parent)
    return result,corrected,[{'operation':'REPLACE_ONLY_EIGHT_SAVED_PATCH_ROWS_AND_MISSING_DEFERRED_SELECTOR','fixed_patch_ref':c['fixed_patch_ref'],
        'targets':c['targets'],'deferred_target':'SFQ16/0'},*audit]
