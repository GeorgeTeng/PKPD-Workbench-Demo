"""Source-ledger rules: inventory -> consolidation -> independent delivery review.

The ledger is audit data. Published/consumed rules retain the four-field contract.
Historical policies never enter this pipeline. No LLM can directly write used_in.
"""
import copy
import re
from pathlib import Path

from ctxcomp.io import digest
from ctxcomp.schemas import S, arr, enum, obj, validate_schema
from ctxcomp.retention import span_check
from ctxcomp.governance import attach_governance
from .common import PipelineError, read_json, write_json

MARKER='OBLIGATION_LEDGER_V1'
MODULE_TAGS={'intake':[], 'context_bundle':[], 'data_bundle':['adequacy','prepare'],
    'eda':['eda'], 'dispatch':['dispatch'], 'pk':['animal_pk'],
    'translation':['pk_translation','human_validation'], 'index':['index'],
    'targets':['index'], 'pta':['pta'], 'results':['clinical'], 'clinical':['clinical']}


def enabled(value):
    return value.get('extraction_policy',{}).get('pipeline')==MARKER


def source_routing(value):
    return value['extraction_policy'].get('routing_owner')=='SOURCE_OBLIGATION'


def operation_schema(value):
    return arr(enum(*value['extraction_policy']['operations'],'UNRESOLVED'),1)


def derived_tags(value,codes):
    tags={t for code in codes if code!='UNRESOLVED' for t in value['extraction_policy']['operations'][code]['used_in']}
    return [s for s in value['extraction_policy']['steps'] if s in tags]


def rule_operations(value,inventory,rule):
    if not source_routing(value):return rule['operations']
    obs={o['id']:o for o in obligations(inventory)}
    return sorted({code for oid in rule['obligation_ids'] for code in obs[oid]['operations']})


def fail(message):
    raise PipelineError('PROJECT_RULES_CONTRACT_INVALID',message)


def exact(actual,expected,label):
    if len(actual)!=len(set(actual)) or set(actual)!=set(expected):
        fail(label+' must account for every expected ID exactly once.')


def segments(value):
    """Lossless non-whitespace line spans, with original source-unit offsets.

    Long lines stay intact: arbitrary character cuts can sever a qualifier.
    Surrounding full source units remain available in every request.
    """
    authority={p['source_id'] for p in value['source_permissions'] if p['may_supply_project_authority']}
    result=[]
    for u in value['source_units']:
        if u['source_id'] not in authority: continue
        for m in re.finditer(r'[^\r\n]+',u['text']):
            if not m.group().strip():continue
            result.append({'id':u['id']+':'+str(m.start()),'unit_id':u['id'],
                'source_id':u['source_id'],'start':m.start(),'end':m.end(),'text':m.group()})
    return result


def inventory_schema(value):
    from .project_rule_agent import SPAN
    ids=[s['id'] for s in segments(value)]
    obligation=obj(id=S,text=S,evidence=arr(SPAN,1))
    if source_routing(value):
        obligation['properties']['operations']=operation_schema(value);obligation['required'].append('operations')
    row=obj(segment_id=enum(*ids) if ids else S,disposition=enum('OBLIGATIONS','CONTEXT','UNRESOLVED'),reason=S,
        obligations=arr(obligation))
    return obj(request_sha256=S,segments={**arr(row),'minItems':len(ids),'maxItems':len(ids)})


def base_request(value,stage,schema,instructions,**extra):
    from .project_rule_compact import policy_for,validate_workflow_reference
    policy=policy_for(value);validate_workflow_reference(value)
    payload={'stage':stage,'instructions':instructions,'policy_version':policy['version'],
        'policy_sha256':value['policy_sha256'],'processing_rules':value['processing_rules'],
        'source_units':value['source_units'],'source_segments':segments(value),
        'source_permissions':value['source_permissions'],
        'source_roles':[{k:s[k] for k in ('id','name','role') if k in s} for s in value['sources']],
        'objective':value['objective'],'existing_rules':value['existing_rules'],
        'required_original_rule_paths':[f'/rules/{i}' for i in range(len(value['existing_rules']))],
        'workflow_reference':value['workflow_reference'],'workflow_reference_sha256':value['workflow_reference_sha256'],
        'operation_contract':policy['operations'],'delivery_contract':MODULE_TAGS,'schema':schema,**extra}
    attach_governance(payload,value['governance'])
    return {'request_sha256':digest(payload),'payload':payload}


def inventory_request(value):
    return base_request(value,'project_rules_inventory',inventory_schema(value),value['extraction_policy']['prompts']['inventory'])


def validate_inventory(inv,value,req=None):
    req=req or inventory_request(value)
    validate_schema(inv,req['payload']['schema'])
    if inv['request_sha256']!=req['request_sha256']:fail('Inventory belongs to a different source request.')
    by_segment={s['id']:s for s in segments(value)}
    exact([r['segment_id'] for r in inv['segments']],by_segment,'Inventory segments')
    authority={p['source_id'] for p in value['source_permissions'] if p['may_supply_project_authority']}
    for row in inv['segments']:
        if not row['reason'].strip():fail('Inventory disposition needs a reason.')
        ids=[o['id'] for o in row['obligations']];exact(ids,ids,'Local obligation IDs')
        if (row['disposition']=='OBLIGATIONS') != bool(ids) and row['disposition']!='UNRESOLVED':
            fail('Inventory disposition contradicts its obligations.')
        for o in row['obligations']:
            if source_routing(value):exact(o['operations'],o['operations'],'Source obligation operations')
            if not o['text'].strip() or not o['id'].strip():fail('Empty obligation.')
            if not any(s['source_id'] in authority for s in o['evidence']):fail('Obligation lacks project authority.')
            source_segment=by_segment[row['segment_id']]
            if not any(s['unit_id']==source_segment['unit_id'] and
                (s['quote'] in source_segment['text'] or source_segment['text'].strip() in s['quote']) for s in o['evidence']):
                fail('Obligation must anchor the source segment being inventoried.')
            for span in o['evidence']:span_check(span,value['source_units'])
    return inv


def obligations(inv):
    return [{**copy.deepcopy(o),'id':r['segment_id']+'/'+o['id'],'segment_id':r['segment_id']}
        for r in sorted(inv['segments'],key=lambda r:r['segment_id']) for o in sorted(r['obligations'],key=lambda o:o['id'])]


def draft_schema(value,inv):
    ids=[o['id'] for o in obligations(inv)]
    identifier=enum(*ids) if ids else S
    rule=obj(id=S,text=S,obligation_ids=arr(identifier,1))
    if not source_routing(value):
        rule['properties']['operations']=operation_schema(value);rule['required'].append('operations')
    return obj(request_sha256=S,rules=arr(rule),excluded=arr(obj(obligation_id=identifier,reason=S)),
        original_rule_mapping=arr(obj(path=S,item_ids=arr(),reason=S)))


def consolidation_request(value,inv):
    obs=obligations(inv)
    if source_routing(value):
        for o in obs:o['derived_used_in']=derived_tags(value,o['operations'])
    return base_request(value,'project_rules_consolidate',draft_schema(value,inv),
        value['extraction_policy']['prompts']['consolidate'],obligation_inventory=obs)


def validate_draft(draft,value,inv,req=None):
    req=req or consolidation_request(value,inv)
    validate_schema(draft,req['payload']['schema'])
    if draft['request_sha256']!=req['request_sha256']:fail('Consolidation belongs to a different inventory.')
    ids=[r['id'] for r in draft['rules']];exact(ids,ids,'Rule IDs')
    accounted=[o for r in draft['rules'] for o in r['obligation_ids']]+[e['obligation_id'] for e in draft['excluded']]
    exact(accounted,[o['id'] for o in obligations(inv)],'Obligation dispositions')
    texts=set()
    obs={o['id']:o for o in obligations(inv)}
    for r in draft['rules']:
        if not r['id'].strip() or not r['text'].strip():fail('Empty rule.')
        normalized=' '.join(r['text'].casefold().split())
        if normalized in texts:fail('Duplicate rule text independent of routing: consolidate its evidence.')
        texts.add(normalized)
        if source_routing(value):
            footprints={tuple(derived_tags(value,obs[oid]['operations'])) for oid in r['obligation_ids']}
            if len(footprints)!=1:
                detail={oid:derived_tags(value,obs[oid]['operations']) for oid in r['obligation_ids']}
                fail('Consolidation cannot merge obligations with different frozen routes: '+r['id']+' '+str(detail))
        else:exact(r['operations'],r['operations'],'Operation codes')
    for e in draft['excluded']:
        if not e['reason'].strip():fail('Excluded obligation needs a reason.')
    exact([r['path'] for r in draft['original_rule_mapping']],
        [f'/rules/{i}' for i in range(len(value['existing_rules']))],'Inherited rules')
    for row in draft['original_rule_mapping']:
        if not row['reason'].strip() or not set(row['item_ids'])<=set(ids):fail('Invalid inherited-rule mapping.')
        exact(row['item_ids'],row['item_ids'],'Inherited mapping IDs')
    return draft


def materialize(value,inv,draft,lineage=None):
    obs={o['id']:o for o in obligations(inv)};policy=value['extraction_policy']
    items=[]
    for r in sorted(draft['rules'],key=lambda r:r['id']):
        evidence=[]
        for oid in sorted(r['obligation_ids']):
            for span in obs[oid]['evidence']:
                if span not in evidence:evidence.append(copy.deepcopy(span))
        tags=derived_tags(value,rule_operations(value,inv,r))
        items.append({'id':r['id'],'text':r['text'],'used_in':tags,'evidence':evidence})
    coverage=[]
    unresolved_units={s['unit_id'] for s in segments(value) if any(r['segment_id']==s['id'] and r['disposition']=='UNRESOLVED' for r in inv['segments'])}
    for u in value['source_units']:
        ids=[r['id'] for r in items if any(s['unit_id']==u['id'] for s in r['evidence'])]
        coverage.append({'unit_id':u['id'],'item_ids':ids,'disposition':'UNRESOLVED' if u['id'] in unresolved_units else 'CLASSIFIED' if ids else 'NO_REQUIREMENT',
            'reason':'See source-segment ledger and explicit obligation dispositions.' if any(s['unit_id']==u['id'] for s in segments(value)) else 'Supporting evidence has no project authority; retained in original sources.'})
    return {'pipeline':MARKER,'request_sha256':inventory_request(value)['request_sha256'],
        'items':items,'source_coverage':coverage,'original_rule_mapping':copy.deepcopy(draft['original_rule_mapping']),
        'findings':[],'inventory':copy.deepcopy(inv),'consolidation':copy.deepcopy(draft),'lineage':copy.deepcopy(lineage)}


def validate_candidate(candidate,value,depth=0):
    if depth>value['extraction_policy']['max_repairs']:fail('Repair limit exceeded.')
    inv=candidate['inventory'];draft=candidate['consolidation'];lineage=candidate['lineage']
    if lineage is None:
        validate_inventory(inv,value);validate_draft(draft,value,inv)
    else:
        from . import project_rule_agent as a
        for key in ('candidate_ref','review_ref','patch_ref'):a.check_ref(lineage[key])
        before=read_json(lineage['candidate_ref']['path']);review=read_json(lineage['review_ref']['path'])
        validate_candidate(before,value,depth+1)
        validate_review(review,review_request(value,before),before,value)
        patch=read_json(lineage['patch_ref']['path']);req=repair_request(value,before,review,lineage.get('diagnostic_reviews'))
        if lineage.get('contract_correction'):
            req=contract_correction_request(req,value,before,lineage['contract_correction'])
        updated_inv,updated_draft=apply_patch_response(patch,req,value,before)
        if inv!=updated_inv or draft!=updated_draft:fail('Candidate differs from its bounded repair.')
    if candidate!=materialize(value,inv,draft,lineage):fail('Rule text, routing, evidence or coverage differs from its ledger.')
    return candidate


def module_views(candidate):
    return [{'module_id':m,'tags':tags,'rule_ids':[r['id'] for r in candidate['items'] if set(tags)&set(r['used_in'])]}
        for m,tags in MODULE_TAGS.items()]


def duplicate_candidates(rules):
    """High-recall review shortlist; similarity never authorizes merging.

    No species or numeric tokens are discarded. Different applicability is a
    reason for the reviewer to KEEP a pair, not a reason to hide it from review.
    """
    stop=set('a an the and or of to for in on with as by is are be do not only from its their where when before after this that'.split())
    def tokens(text):
        return [t for t in re.findall(r'\w+',text.casefold()) if t not in stop]
    rows=sorted(rules,key=lambda r:r['id']);result=[]
    for i,a in enumerate(rows):
        ta=tokens(a['text']);sa=set(ta)
        for b in rows[i+1:]:
            tb=tokens(b['text']);sb=set(tb);common=sa&sb
            tri_a={tuple(ta[n:n+3]) for n in range(len(ta)-2)}
            tri_b={tuple(tb[n:n+3]) for n in range(len(tb)-2)}
            if (len(common)>=4 and len(common)/max(1,min(len(sa),len(sb)))>=.35) or len(tri_a&tri_b)>=2:
                result.append({'id':'PAIR_'+digest([a['id'],b['id']])[:12],
                    'rule_ids':[a['id'],b['id']],'shared_terms':sorted(common)})
    return result


def projection(rules,target,reference,steps):
    aliases={'human_pk':['pk_translation'],'pk_longitudinal':['animal_pk'],'pkpd_index':['index']}
    tags=MODULE_TAGS.get(target,aliases.get(target,[target]))
    if not set(tags)<=set(steps):raise ValueError('Unknown project-rule destination: '+target)
    selected=[];audit=[]
    for i,r in enumerate(rules):
        include=bool(set(tags)&set(r['used_in']))
        if include:selected.append({**copy.deepcopy(r),'text':r['id']+': '+r['text'],
            'context_path':f'/rules/{i}','project_rules_ref':reference,'projection_version':MARKER})
        audit.append({'id':r['id'],'included':include,'reason':'Reviewed operation contract and module delivery'})
    return {'version':'1.3','target':target,'rules':selected,'unresolved':[],'audit':audit,'project_rules_ref':reference,
        'method':MARKER,'scientific_approval':False,'source_rule_count':len(rules),'selected_rule_count':len(selected)}


def review_request(value,candidate):
    from .project_rule_agent import VERDICT,FINDING
    from .project_rule_compact import CHECKS
    def checks(key,ids):
        return {**arr(obj(**{key:enum(*ids) if ids else S},verdict=VERDICT,reason=S)),'minItems':len(ids),'maxItems':len(ids)}
    rules=candidate['items'];oids=[o['id'] for o in obligations(candidate['inventory'])];sids=[s['id'] for s in segments(value)]
    schema=obj(request_sha256=S,candidate_sha256=enum(digest(candidate)),final_rules_sha256=enum(digest(rules)),decision=VERDICT,
        final_rule_checks=checks('rule_id',[r['id'] for r in rules]),source_checks=checks('unit_id',[u['id'] for u in value['source_units']]),
        original_rule_checks=checks('path',[f'/rules/{i}' for i in range(len(value['existing_rules']))]),global_checks=checks('id',CHECKS),
        segment_checks=checks('segment_id',sids),obligation_checks=checks('obligation_id',oids),module_checks=checks('module_id',list(MODULE_TAGS)),
        repair_targets=arr(obj(rule_ids=arr(enum(*[r['id'] for r in rules]) if rules else S),segment_ids=arr(enum(*sids) if sids else S),reason=S)),
        findings=arr(copy.deepcopy(FINDING)))
    extra={}
    if value['extraction_policy'].get('duplicate_review')=='LEXICAL_PAIRS_V1':
        pairs=duplicate_candidates(rules)
        schema['properties']['duplicate_checks']=checks('pair_id',[r['id'] for r in pairs])
        schema['properties']['operation_checks']=checks('rule_id',[r['id'] for r in rules])
        schema['required']+=['duplicate_checks','operation_checks']
        extra['duplicate_candidates']=pairs
    return base_request(value,'project_rules_review',schema,value['extraction_policy']['prompts']['review'],
        candidate_sha256=digest(candidate),publication_candidate={'rules':rules,'final_rules_sha256':digest(rules)},
        inventory=candidate['inventory'],consolidation=candidate['consolidation'],module_views=module_views(candidate),**extra)


def validate_review(response,req,candidate,value):
    from .project_rule_compact import CHECKS
    validate_schema(response,req['payload']['schema'])
    if response['request_sha256']!=req['request_sha256']:fail('Review belongs to a different request.')
    specs=[('final_rule_checks','rule_id',[r['id'] for r in candidate['items']]),
        ('source_checks','unit_id',[u['id'] for u in value['source_units']]),
        ('original_rule_checks','path',[f'/rules/{i}' for i in range(len(value['existing_rules']))]),('global_checks','id',CHECKS),
        ('segment_checks','segment_id',[s['id'] for s in segments(value)]),
        ('obligation_checks','obligation_id',[o['id'] for o in obligations(candidate['inventory'])]),('module_checks','module_id',list(MODULE_TAGS))]
    if value['extraction_policy'].get('duplicate_review')=='LEXICAL_PAIRS_V1':
        specs += [('duplicate_checks','pair_id',[r['id'] for r in duplicate_candidates(candidate['items'])]),
                  ('operation_checks','rule_id',[r['id'] for r in candidate['items']])]
    blocking=False
    for field,key,ids in specs:
        exact([r[key] for r in response[field]],ids,field)
        if any(not r['reason'].strip() for r in response[field]):fail('Review check needs a reason.')
        blocking|=any(r['verdict']!='PASS' for r in response[field])
    blocking|=any(r['disposition']=='UNRESOLVED' for r in candidate['inventory']['segments'])
    blocking|=any('UNRESOLVED' in rule_operations(value,candidate['inventory'],r) for r in candidate['consolidation']['rules'])
    if source_routing(value):blocking|=any('UNRESOLVED' in o['operations'] for o in obligations(candidate['inventory']))
    blocking|=any(f['severity']=='REQUIRES_CLARIFICATION' for f in response['findings'])
    if response['decision']=='PASS' and (blocking or response['repair_targets']):fail('PASS contradicts failed checks or unresolved ledger.')
    for t in response['repair_targets']:
        if not (t['rule_ids'] or t['segment_ids']) or not t['reason'].strip():fail('Repair needs concrete affected records.')
    if response['decision']=='REVISE' and not response['repair_targets']:fail('REVISE needs localized repair targets.')
    return response


def extract(value,output,model=None,generator=None):
    from . import project_rule_agent as a
    output=Path(output)
    if output.exists() and any(output.iterdir()):fail('Use a new immutable extraction directory.')
    req=inventory_request(value)
    inv=a._call(req,output/'inventory',model,generator,lambda r:validate_inventory(r,value,req),'inventory.json')
    req=consolidation_request(value,inv)
    draft=a._call(req,output/'consolidation',model,generator,lambda r:validate_draft(r,value,inv,req),'consolidation.json')
    candidate=materialize(value,inv,draft);validate_candidate(candidate,value)
    write_json(output/'candidate.json',candidate)
    return candidate


def repair_scope(candidate,review):
    sids={s for t in review['repair_targets'] for s in t['segment_ids']}
    rids={r for t in review['repair_targets'] for r in t['rule_ids']}
    affected={o['id'] for o in obligations(candidate['inventory']) if o['segment_id'] in sids}
    # A changed source segment may affect an already consolidated rule. Expand
    # only this explicit dependency, never all rules sharing a topic or module.
    rids|={r['id'] for r in candidate['consolidation']['rules'] if affected&set(r['obligation_ids'])}
    affected|={oid for r in candidate['consolidation']['rules'] if r['id'] in rids for oid in r['obligation_ids']}
    return sorted(sids),sorted(rids),sorted(affected)


def repair_request(value,candidate,review,diagnostic_reviews=None):
    if review['decision']!='REVISE':fail('Only a localized REVISE review can trigger repair.')
    if candidate['lineage'] is not None:fail('Bounded repair exhausted; preserve failure for human inspection.')
    supplemental=[]
    if diagnostic_reviews:
        from . import project_rule_agent as a
        # A diagnostic branch can combine independently recorded failures from
        # a prior bounded attempt. It still starts from the original candidate,
        # preserves that attempt, and requires one new independent final review.
        for record in diagnostic_reviews:
            for key in ('candidate_ref','review_ref'):a.check_ref(record[key])
            dc=read_json(record['candidate_ref']['path']);dr=read_json(record['review_ref']['path'])
            if not dc.get('lineage') or dc['lineage'].get('diagnostic_reviews'):
                fail('Diagnostic feedback must come from the first bounded repair, not a recursive branch.')
            a.check_ref(dc['lineage']['candidate_ref'])
            if read_json(dc['lineage']['candidate_ref']['path'])!=candidate:
                fail('Diagnostic feedback belongs to another original candidate.')
            validate_candidate(dc,value);validate_review(dr,review_request(value,dc),dc,value)
            if dr['decision']!='REVISE':fail('Diagnostic feedback needs a real failed review.')
            known={r['id'] for r in candidate['items']}
            diagnostic_rules={r['id']:r for r in dc['consolidation']['rules']}
            diagnostic_obs={o['id']:o for o in obligations(dc['inventory'])}
            for target in dr['repair_targets']:
                target=copy.deepcopy(target);added_segments=set()
                for rid in set(target['rule_ids'])-known:
                    # A prior repair may split a rule. Translate that new ID
                    # back to its source segments before branching from the
                    # original; no semantic rewrite or foreign IDs are allowed.
                    row=diagnostic_rules[rid]
                    added_segments|={diagnostic_obs[oid]['segment_id'] for oid in row['obligation_ids']}
                    target['reason']+=' Diagnostic split '+rid+': '+row['text']
                target['rule_ids']=[rid for rid in target['rule_ids'] if rid in known]
                if added_segments:
                    target['segment_ids']=target['segment_ids']+sorted(added_segments-set(target['segment_ids']))
                if not set(target['segment_ids'])<={s['id'] for s in segments(value)}:
                    fail('Diagnostic split has no original source segment.')
                supplemental.append(target)
    combined={**review,'repair_targets':review['repair_targets']+supplemental}
    sids,rids,oids=repair_scope(candidate,combined)
    segment_schema=inventory_schema(value)['properties']['segments']['items']
    rule_schema=copy.deepcopy(draft_schema(value,candidate['inventory'])['properties']['rules']['items'])
    rule_schema['properties']['obligation_ids']=arr(S,1) # New obligations only from changed segments, checked after patch.
    schema=obj(request_sha256=S,segments=arr(segment_schema),rules=arr(rule_schema),removed_rule_ids=arr(S),
        excluded=arr(obj(obligation_id=S,reason=S)))
    if source_routing(value):
        schema['properties']['route_updates']=arr(obj(obligation_id=S,operations=operation_schema(value)))
        schema['required'].append('route_updates')
    instructions=('Apply only the listed local repair targets. Return complete replacement rows for exactly allowed_segment_ids; '
        'return replacements for every affected existing rule or list its ID in removed_rule_ids. New rules may be added using newly '
        'inventoried or affected obligations only. Preserve unrelated records; do not return them. Local obligation IDs belong to their '
        'segment; draft obligation IDs are segment_id/local_id. Return excluded entries only for affected obligations that are no longer '
        'retained. Do not delete a substantive obligation to silence a review. Preserve exact evidence and the entire source meaning. '
        'No used_in field: use operation codes. A separate fresh review follows. '+value['extraction_policy']['prompts']['consolidate'])
    if source_routing(value):instructions+=(
        ' Operation classifications belong to inventory obligations, never to draft rules. For route-only corrections to existing '
        'affected obligations use route_updates; do not change unrelated obligations. Segment replacements can change operations '
        'for their own obligations; do not also list those obligations in route_updates. Preserve identical routes within every merged rule.')
    extra={'additional_review_findings':supplemental} if diagnostic_reviews else {}
    return base_request(value,'project_rules_repair',schema,instructions,previous_inventory=candidate['inventory'],
        previous_consolidation=candidate['consolidation'],review=review,allowed_segment_ids=sids,allowed_rule_ids=rids,affected_obligation_ids=oids,**extra)


def apply_patch_response(patch,req,value,before):
    validate_schema(patch,req['payload']['schema'])
    if patch['request_sha256']!=req['request_sha256']:fail('Patch belongs to another review.')
    p=req['payload'];sids=set(p['allowed_segment_ids']);rids=set(p['allowed_rule_ids']);oids=set(p['affected_obligation_ids'])
    if source_routing(value):
        # A model may echo a neighbouring unchanged segment with a paraphrased
        # audit reason. Ignore that echo and retain the ORIGINAL complete row.
        # Never accept out-of-scope obligation, classification or evidence edits.
        ids=[s['segment_id'] for s in patch['segments']];exact(ids,ids,'Patch segment IDs')
        original={s['segment_id']:s for s in before['inventory']['segments']}
        keep=[]
        for row in patch['segments']:
            old=original.get(row['segment_id'])
            if row['segment_id'] not in sids and old and all(row[k]==old[k] for k in ('disposition','obligations')):
                continue
            keep.append(row)
        patch={**patch,'segments':keep}
    exact([s['segment_id'] for s in patch['segments']],sids,'Patched segments')
    inv=copy.deepcopy(before['inventory']);rows={s['segment_id']:s for s in patch['segments']}
    inv['segments']=[copy.deepcopy(rows.get(s['segment_id'],s)) for s in inv['segments']]
    if source_routing(value):
        updates=patch['route_updates'];exact([r['obligation_id'] for r in updates],[r['obligation_id'] for r in updates],'Route update IDs')
        if any(r['obligation_id'] not in oids for r in updates):fail('Route update touched an unrelated obligation.')
        by_id={r['obligation_id']:r['operations'] for r in updates}
        for row in inv['segments']:
            for o in row['obligations']:
                oid=row['segment_id']+'/'+o['id']
                if oid in by_id:
                    if row['segment_id'] in sids:fail('Route updated twice via segment and route_updates.')
                    o['operations']=copy.deepcopy(by_id[oid])
    validate_inventory(inv,value)
    new_oids={o['id'] for o in obligations(inv) if o['segment_id'] in sids}
    allowed_oids=oids|new_oids
    existing={r['id']:r for r in before['consolidation']['rules']}
    if source_routing(value):
        ids=[r['id'] for r in patch['rules']];exact(ids,ids,'Patch rules')
        # Ignore byte-identical echoes, never changes, outside the edit boundary.
        patch={**patch,'rules':[r for r in patch['rules'] if r['id'] in rids or existing.get(r['id'])!=r]}
    ids=[r['id'] for r in patch['rules']];exact(ids,ids,'Patch rules')
    removed=patch['removed_rule_ids'];exact(removed,removed,'Removed rules')
    if not set(removed)<=rids or set(removed)&set(ids):fail('Invalid removed rule IDs.')
    if not {r for r in ids if r in existing}<=rids:fail('Patch touched unrelated rules.')
    if any(not set(r['obligation_ids'])<=allowed_oids for r in patch['rules']):fail('Patch consumed an unrelated obligation.')
    if any(e['obligation_id'] not in allowed_oids for e in patch['excluded']):fail('Patch excluded an unrelated obligation.')
    draft=copy.deepcopy(before['consolidation'])
    # Allowed dependencies are an edit boundary, not a deletion list. Missing
    # replacement rows retain their original text and bindings; a fresh review
    # must still resolve every reported defect.
    replaced=set(ids)|set(removed)
    draft['rules']=[r for r in draft['rules'] if r['id'] not in replaced]+copy.deepcopy(patch['rules'])
    draft['excluded']=[e for e in draft['excluded'] if e['obligation_id'] not in allowed_oids]+copy.deepcopy(patch['excluded'])
    # Inherited mappings are deliberately immutable in a local patch. Removing a
    # mapped rule fails below; a wider migration needs a new reviewed extraction.
    draft['request_sha256']=consolidation_request(value,inv)['request_sha256']
    validate_draft(draft,value,inv)
    return inv,draft


def contract_correction_request(base,value,before,refs):
    """One auditable retry of a rejected cross-route merge; never widen scope."""
    from . import project_rule_agent as a
    for key in ('request_ref','response_ref'):a.check_ref(refs[key])
    if read_json(refs['request_ref']['path'])!=base:fail('Contract correction belongs to a different repair request.')
    rejected=read_json(refs['response_ref']['path'])
    try:apply_patch_response(rejected,base,value,before)
    except PipelineError as exc:
        if not str(exc).startswith('Consolidation cannot merge obligations with different frozen routes:'):raise
        error=str(exc)
    else:fail('Contract correction needs an actually rejected cross-route merge.')
    payload=copy.deepcopy(base['payload'])
    payload['contract_correction']={'rejected_response':rejected,'validation_error':error}
    payload['instructions']+=(
        ' The previous local patch violated the frozen route constraint; it was not accepted. Correct that structural '
        'defect within the SAME allowed records. Split differently routed complete obligations into appropriately '
        'worded rules instead of copying the entire combined text or changing routes merely to make a merge pass. '
        'Keep all other valid proposed corrections. This is the only contract retry; independent review still follows.')
    return {'request_sha256':digest(payload),'payload':payload}


def repair(input_ref,candidate_ref,review_ref,output,model=None,generator=None,diagnostic_reviews=None,contract_correction=None):
    from . import project_rule_agent as a
    value=a.validate_input(input_ref)
    for r in (candidate_ref,review_ref):a.check_ref(r)
    before=read_json(candidate_ref['path']);review=read_json(review_ref['path'])
    validate_candidate(before,value);validate_review(review,review_request(value,before),before,value)
    req=repair_request(value,before,review,diagnostic_reviews);output=Path(output)
    if contract_correction:req=contract_correction_request(req,value,before,contract_correction)
    patch_path=output/'patch.json'
    try:
        patch=a._call(req,output,model,generator,lambda x:apply_patch_response(x,req,value,before),'patch.json')
    except PipelineError as exc:
        if contract_correction or not str(exc).startswith('Consolidation cannot merge obligations with different frozen routes:'):raise
        contract_correction={'request_ref':a.file_ref(output/'request.json'),'response_ref':a.file_ref(output/'response.json')}
        req=contract_correction_request(req,value,before,contract_correction)
        retry=output/'contract_correction';patch_path=retry/'patch.json'
        patch=a._call(req,retry,model,generator,lambda x:apply_patch_response(x,req,value,before),'patch.json')
    inv,draft=apply_patch_response(patch,req,value,before)
    lineage={'candidate_ref':candidate_ref,'review_ref':review_ref,'patch_ref':a.file_ref(patch_path)}
    if diagnostic_reviews:lineage['diagnostic_reviews']=copy.deepcopy(diagnostic_reviews)
    if contract_correction:lineage['contract_correction']=copy.deepcopy(contract_correction)
    candidate=materialize(value,inv,draft,lineage);validate_candidate(candidate,value)
    write_json(output/'candidate.json',candidate)
    return candidate


def review_with_repair(input_ref,candidate_ref,output,model=None,generator=None):
    """One review, at most one local patch, then a fresh full review.

    Selection is explicit for the caller. Failed attempts are never overwritten.
    The ordinary agent.review API remains a single independent review call.
    """
    from . import project_rule_agent as a
    output=Path(output)
    if output.exists() and any(output.iterdir()):fail('Review output is immutable.')
    initial_ref=copy.deepcopy(candidate_ref)
    result=a.review(input_ref,candidate_ref,output/'initial',model=model,generator=generator)
    review_ref=a.file_ref(output/'initial/review.json');attempts=0
    if result['decision']=='REVISE':
        repair(input_ref,candidate_ref,review_ref,output/'repair',model=model,generator=generator)
        candidate_ref=a.file_ref(output/'repair/candidate.json');attempts=1
        result=a.review(input_ref,candidate_ref,output/'final',model=model,generator=generator)
        review_ref=a.file_ref(output/'final/review.json')
    selection={'initial_candidate_ref':initial_ref,'candidate_ref':candidate_ref,'review_ref':review_ref,'repairs':attempts}
    write_json(output/'selection.json',selection)
    write_json(output/'review.json',result)
    return selection
