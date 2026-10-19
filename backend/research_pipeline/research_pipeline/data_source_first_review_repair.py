"""Bound, target-only completion of saved independent review responses.

No original review, source or scientific input is overwritten. Selectors are
explicit model operations; all materialization and aggregation has a replay proof.
"""
import argparse
import copy
import json
import os
from pathlib import Path
from ctxcomp.io import digest
from ctxcomp.schemas import obj,arr,S,enum
from . import data_agents as d,data_source_first_workflow as sf,data_source_first_review as review
from .common import read_json,write_json
from .adequacy import file_ref,check_ref

VERSION='SOURCE_FIRST_REVIEW_REPAIR_1.0'
CONTINUATION='SOURCE_FIRST_REVIEW_PATCH_CONTINUATION_1.0'
INDEX='review_repair_index.json'
SELECTOR=obj(source=S,field=enum('CONTENT','text','usage','conditions','exceptions','scope','requirement'))
STATUS=enum('SUPPORTED','PARTIAL','MISSING','CONFLICT','UNRESOLVED','DEFERRED')


def request_for(part,schema=d.ADEQUACY_REVIEW):
    if schema==d.ADEQUACY_REVIEW:return review.governed_part_request(part)
    class Captured(Exception):
        def __init__(self,value):self.value=value
    module=sf.private_module()
    # Capture before original invoke performs audit, cache or provider I/O.
    def capture(p):raise Captured(d.governed_request(p))
    module.governed_request=capture
    try:module.invoke(Path('.'),'DC-review',{**copy.deepcopy(part),'source_first_contract':sf.VERSION,'scientific_approval':False},schema,model=sf.MODEL)
    except Captured as result:return result.value
    sf.fail('Request capture unexpectedly reached execution')


def frozen_part(current,original_request):
    """Restore only lossless catalog row ordering, then require the full frozen request."""
    part=copy.deepcopy(current);catalog=original_request['payload']['evidence_catalog']
    if review.unpack_catalog(part['evidence_catalog'])!=review.unpack_catalog(catalog):sf.fail('Original catalog content differs')
    part['evidence_catalog']=copy.deepcopy(catalog)
    if request_for(part)!=original_request:sf.fail('Current part differs beyond catalog transport ordering')
    return part


def _bad_criteria(response,part,full):
    targets=[];missing=[]
    got={m['requirement_id']:m for m in response['matches']}
    for plan in part['criterion_plans']:
        rid=plan['requirement_id'];plan=next(p for p in full['criterion_plans'] if p['requirement_id']==rid)
        need=next(n for n in full['requirements']['requirements'] if n['id']==rid)
        if rid not in got:missing.append(rid);continue
        for cr in got[rid]['criteria']:
            errors=[]
            for e in cr['evidence']:
                entry=full['evidence_catalog'].get(e['source'])
                if e['source'] not in plan['allowed_source_ids'] or not entry or not e['quote'].strip() or e['quote'] not in entry['content']:errors.append('UNSUPPORTED_OR_UNASSIGNED_SPAN')
            if cr['status'] in {'SUPPORTED','PARTIAL','CONFLICT'} and not cr['evidence']:errors.append('EVIDENCE_REQUIRED')
            if cr['status']!='SUPPORTED' and cr['needed_material'].strip().upper() in {'NONE','NOT_FOUND','N/A'}:errors.append('NEXT_ACTION_REQUIRED')
            if need['kind']=='DATA' and cr['id']=='FULL_REQUIREMENT' and cr['status'] in {'SUPPORTED','PARTIAL'} and not any(full['evidence_catalog'].get(e['source'],{}).get('kind')=='SOURCE_CONTENT' for e in cr['evidence']):errors.append('ORIGINAL_BODY_EVIDENCE_REQUIRED')
            if errors:targets.append({'requirement_id':rid,'criterion_id':cr['id'],'errors':sorted(set(errors))})
    return targets,missing


def _bad_deferred(response,full):
    targets=[]
    for m in response['matches']:
        plan=next(p for p in full['criterion_plans'] if p['requirement_id']==m['requirement_id'])
        for i,output in enumerate(m['deferred_outputs']):
            if any(e['source'] not in plan['allowed_source_ids'] or e['source'] not in full['evidence_catalog']
                   or full['evidence_catalog'][e['source']]['kind'] not in {'MAIN','RULE'}
                   or e['quote'] not in full['evidence_catalog'][e['source']]['content'] for e in output['evidence']):
                targets.append({'target':m['requirement_id']+'/'+str(i),'requirement_id':m['requirement_id'],'output_index':i,
                                'producer_task':output['producer_task'],'output':output['output']})
    return targets


def _part_core(q):
    return {k:v for k,v in q['payload'].items() if k not in {'stage','agent','policy_version','processing_rules','schema','governance','governance_sha256','source_first_contract','scientific_approval'}}


def prepare(run,full_payload_path,out):
    run=Path(run);out=Path(out);manifest,_=sf.verify_run(run);full=read_json(full_payload_path)
    req=read_json(run/'requirements.json')
    if full['requirements']['requirements']!=req['requirements']:sf.fail('Review source requirements changed')
    parts={p['part_id']:p for p in review.plan_parts(full)};contracts=[]
    audits={read_json(p/'request.json')['payload']['part_id']:p for p in (run/'data_agents/audit/DC-review').iterdir() if (p/'response.json').exists()}
    for pid in ['REVIEW_001','REVIEW_002','REVIEW_004']:
        folder=audits[pid];q=read_json(folder/'request.json');a=read_json(folder/'response.json');part=frozen_part(parts[pid],q)
        if request_for(part)!=q or a['request_sha256']!=q['request_sha256']:sf.fail('Full governed original review differs: '+pid)
        targets,missing=_bad_criteria(a,part,full)
        if pid=='REVIEW_001' and (len(targets)!=3 or missing!=['SFQ5']):sf.fail('Unexpected REVIEW_001 repair scope')
        if pid=='REVIEW_002' and (len(targets)!=16 or missing):sf.fail('Unexpected REVIEW_002 repair scope')
        c={'version':VERSION,'part_id':pid,'kind':'GLOBAL_SUPPLEMENT' if pid=='REVIEW_004' else 'CRITERION_REPAIR',
           'original_request_ref':file_ref(folder/'request.json'),'original_response_ref':file_ref(folder/'response.json'),
           'full_payload_ref':file_ref(full_payload_path),'input_refs':[file_ref(run/n) for n in ['inventory.json','requirements.json','labels.json']],
           'requirements_ref':file_ref(run/'requirements.json'),
           'main_ref':manifest['bindings']['main'],'targets':targets,'missing_requirements':missing,'part_sha256':digest(part),
           'deferred_targets':_bad_deferred(a,full),
           'scientific_approval':False}
        path=write_json(out/(pid+'.json'),c);contracts.append(file_ref(path))
    return {'version':VERSION,'contracts':contracts,'scientific_approval':False}


def _load(c):
    if c['version']!=VERSION:sf.fail('Unknown review repair version')
    for ref in c['input_refs']+[c[k] for k in ['original_request_ref','original_response_ref','full_payload_ref','main_ref']]:check_ref(ref)
    full=read_json(c['full_payload_ref']['path']);part=next(p for p in review.plan_parts(full) if p['part_id']==c['part_id'])
    q=read_json(c['original_request_ref']['path']);old=read_json(c['original_response_ref']['path']);part=frozen_part(part,q)
    if digest(part)!=c['part_sha256'] or request_for(part)!=q or old['request_sha256']!=q['request_sha256']:sf.fail('Review parent scope or request binding changed')
    targets,missing=_bad_criteria(old,part,full)
    if targets!=c['targets'] or missing!=c['missing_requirements']:sf.fail('Authorized repair targets changed')
    if _bad_deferred(old,full)!=c['deferred_targets']:sf.fail('Deferred evidence target scope changed')
    return full,part,old


def schema(c):
    if c['kind']=='GLOBAL_SUPPLEMENT':
        return obj(request_sha256=S,checks=arr(d.CHECK),scope_finding=d.FINDING,additional_findings=arr(d.FINDING),
                   explicit_claim_review=obj(source=enum('main:/scientific_context/items/33/statement'),
                       decision=enum('NEEDS_REVIEW','REVISE'),reason=S,evidence_selectors=arr(SELECTOR,1),finding=d.FINDING))
    criterion=obj(requirement_id=S,criterion_id=S,status=STATUS,reason=S,needed_material=S,evidence_selectors=arr(SELECTOR))
    missing=obj(requirement_id=S,reason=S,needed_material=S,criteria=arr(criterion))
    return obj(request_sha256=S,criterion_corrections=arr(criterion),missing_matches=arr(missing),
               deferred_evidence_corrections=arr(obj(target=S,evidence_selectors=arr(SELECTOR,1))))


def payload(c):
    full,original,old=_load(c)
    if c['kind']=='GLOBAL_SUPPLEMENT':
        p=copy.deepcopy(original)
        check_ref(c['requirements_ref']);knowledge_ref=read_json(c['requirements_ref']['path'])['method_knowledge_ref'];check_ref(knowledge_ref)
        knowledge=read_json(knowledge_ref['path'])
        ids={pid for task in full.get('post_source_method_feasibility',[]) for approach in task['approaches'] for pid in approach['method_profile_ids']}
        profiles=[x for x in knowledge['library']['profiles'] if x['id'] in ids]
        p['method_knowledge']={'profiles':profiles,'authority':'UNADOPTED_CANDIDATE_LIBRARY_NOT_PROJECT_REQUIREMENTS'}
        p['previous_checks_non_evidence']=old['checks']
        p['scope_finding_to_correct']=next(f for f in old['findings'] if f['code']=='CRITERION_PLANS_ABSENT')
        p['explicit_claim_to_recheck']=next(x for x in full['post_source_objective_coverage'] if x['source']=='main:/scientific_context/items/33/statement')
        p['instructions']=('This is ONLY the GLOBAL_OBJECTIVE supplement of an already completed five-part review. '
            'Criterion matches are owned by REVIEW_001/002, item checks by their owning parts, and all cross-source values by REVIEW_005. '
            'Empty criterion_plans here is intentional, not missing input. Complete candidate method profiles are supplied; their full original '
            'source records are also in the evidence catalog. They are unadopted proposals, not verified applicability or formal new requirements. '
            'Independently check ALL post_source_dr_claims_to_review: objectives, associations and method feasibility against original evidence. '
            'In particular verify the scientific_context index33 Rabbit S22 source against its current DR reason/association; do not overlook a '
            'mouse/rabbit mismatch. Return all four original check IDs once, preserve adverse scientific conclusions and add concrete findings '
            'for explicit_claim_to_recheck, returning explicit_claim_review with the exact source key and original source evidence. Its finding '
            'affected_id must equal that source key and request correction of the mismatched DR claim, without changing published inputs. '
            'for incorrect/unresolved claims. Correct only the engineering scope finding; other original findings remain locked. '
            'Do not repeat body extraction, criterion review, or close a missing-information item. The nine ledger ESCALATED outcomes remain '
            'unchanged; the host only moves their existing risk text out of the accepted-limitation field with explicit provenance.')
    else:
        ids=list(dict.fromkeys([t['requirement_id'] for t in c['targets']]+c['missing_requirements']))
        p=review.make_part(full,requirement_ids=ids,part_id=c['part_id']+'_REPAIR')
        p['repair_targets']=c['targets'];p['missing_requirement_ids']=c['missing_requirements']
        p['deferred_evidence_targets']=c['deferred_targets']
        p['locked_criterion_context']=[{'requirement_id':m['requirement_id'],'criteria':[x for x in m['criteria'] if not any(t['requirement_id']==m['requirement_id'] and t['criterion_id']==x['id'] for t in c['targets'])]}
                                      for m in old['matches'] if m['requirement_id'] in ids]
        p['instructions']=('Correct ONLY repair_targets, and return a complete criterion checklist for missing_requirement_ids. '
            'All other review checks, findings, valid criteria and scientific rationale are locked. Source selectors are explicit operations: '
            'use field=CONTENT for the exact displayed evidence_catalog original text; for rule:Rxxx only, an operative field such as text '
            'selects its exact JSON-encoded field value. The host materializes original quotes and runs unchanged source/criterion validation. '
            'Each criterion may select ONLY its criterion_plans.allowed_source_ids; a source visible elsewhere is not permitted. '
            'For DATA, FULL_REQUIREMENT SUPPORTED/PARTIAL requires actual SOURCE_CONTENT, not merely header, note, main summary or descriptor. '
            'If no permitted original evidence supports that judgment, retain uncertainty/change status and explain the missing next action; '
            'do not fabricate support. Preserve conflicts and scientific restrictions. Do not compute or fit. Missing SFQ5 needs every criterion '
            'in its plan, including scope, rather than inferring availability from a title. Match source_ids and summary status are explicitly '
            'host-derived from final criteria by the original aggregate algorithm; do not return those redundant fields. '
            ' For listed deferred_evidence_targets ONLY, select MAIN/RULE evidence for the unchanged producer_task/output; '
            'a document SOURCE_CONTENT citation cannot be used as project authorization for a deferred producer. '
            +review.coverage.INSTRUCTIONS)
    p['operation']='REPAIR_SAVED_REVIEW_TARGETS';p['repair_version']=VERSION;p['original_response_sha256']=c['original_response_ref']['sha256']
    return p


def _span(selector,p,full,*,main=None,audit=None):
    source=selector['source'];field=selector['field'];visible=review.visible_sources(p)
    if field=='text' and source.startswith('main:/'):
        entry=full['evidence_catalog'].get(source);value=main
        try:
            for token in source[len('main:/'):].split('/'):
                token=token.replace('~1','/').replace('~0','~')
                value=value[int(token)] if isinstance(value,list) else value[token]
        except (KeyError,IndexError,TypeError,ValueError):sf.fail('MAIN text alias is not a bound scalar leaf')
        if entry is None and source.startswith('main:/rules/') and source.endswith('/text'):
            tokens=source[len('main:/'):].split('/')
            if len(tokens)!=3 or not tokens[1].isdigit() or str(int(tokens[1]))!=tokens[1]:sf.fail('Rule leaf alias requires a canonical index')
            index=int(tokens[1]);original=main['rules'][index];context_path='/rules/'+tokens[1]
            projected=[rule for rule in p['project_rules'] if rule.get('id')==original.get('id') and rule.get('context_path')==context_path]
            if len(projected)!=1 or sum(rule.get('context_path')==context_path for rule in p['project_rules'])!=1:sf.fail('Rule leaf alias must identify one projected rule')
            rule=projected[0];canonical_source='rule:'+original['id'];catalog=full['evidence_catalog'].get(canonical_source)
            if not isinstance(value,str) or rule.get('text') not in {value,original['id']+': '+value} or not catalog or catalog.get('kind')!='RULE':sf.fail('Rule leaf alias is not the unchanged operative text')
            try:canonical=json.loads(catalog['content'])
            except (ValueError,TypeError):sf.fail('Rule source is not a canonical rule record')
            if (canonical.get('id')!=original['id'] or canonical.get('context_path')!=context_path
                or any(canonical.get(k)!=v for k,v in rule.items())):sf.fail('Projected rule differs from the canonical evidence record')
            quote=json.dumps(canonical['text'],ensure_ascii=False)
            evidence={'source':canonical_source,'quote':quote};d.evidence_check([evidence],visible)
            if quote not in catalog['content']:sf.fail('Canonical rule field is not verbatim')
            if audit is not None:audit.append({'operation':'CANONICAL_RULE_LEAF_SELECTOR_ALIAS','original_selector':copy.deepcopy(selector),
                'bound_main_leaf':source,'context_path':context_path,'rule_id':original['id'],
                'projection_text_form':'ID_PREFIXED' if rule['text']!=value else 'IDENTICAL',
                'canonical_selector':{'source':canonical_source,'field':'text'},'materialized_evidence':evidence})
            return evidence
        if not entry or entry.get('kind')!='MAIN' or not isinstance(value,str) or entry['content']!=value:
            sf.fail('MAIN text alias must resolve to the identical original string leaf')
        field='CONTENT'
        if audit is not None:audit.append({'operation':'MAIN_SCALAR_TEXT_SELECTOR_ALIAS','original_selector':copy.deepcopy(selector),
            'canonical_selector':{'source':source,'field':'CONTENT'},'materialized_evidence':{'source':source,'quote':value}})
    if field=='CONTENT':
        entry=full['evidence_catalog'].get(source)
        if not entry:sf.fail('Selector is not an original evidence catalog entry')
        quote=entry['content']
    else:
        if not source.startswith('rule:'):sf.fail('Field selectors apply only to operative project rules')
        rule=next((r for r in p['project_rules'] if source=='rule:'+r['id']),None)
        if not rule or field not in rule:sf.fail('Unknown rule field selector')
        quote=json.dumps(rule[field],ensure_ascii=False)
    d.evidence_check([{'source':source,'quote':quote}],visible)
    return {'source':source,'quote':quote}


def derive(answer,c):
    full,part,old=_load(c);p=payload(c);d.validate_schema(answer,schema(c));new=copy.deepcopy(old);audit=[]
    main=read_json(c['main_ref']['path'])
    def span(selector):return _span(selector,p,full,main=main,audit=audit)
    if c['kind']=='GLOBAL_SUPPLEMENT':
        d.exact([x['id'] for x in answer['checks']],part['expected_check_ids'],'Global supplemental checks')
        by={x['id']:x for x in old['checks']}
        for check in answer['checks']:
            if d.DECISIONS.index(check['decision'])<d.DECISIONS.index(by[check['id']]['decision']):sf.fail('Global correction cannot upgrade an existing adverse decision')
        new['checks']=copy.deepcopy(answer['checks'])
        i=next(i for i,f in enumerate(old['findings']) if f['code']=='CRITERION_PLANS_ABSENT')
        if answer['scope_finding']['affected_id']!=old['findings'][i]['affected_id']:sf.fail('Scope finding target changed')
        new['findings'][i]=copy.deepcopy(answer['scope_finding']);new['findings']+=copy.deepcopy(answer['additional_findings'])
        claim=answer['explicit_claim_review'];source='main:/scientific_context/items/33/statement'
        if claim['finding']['affected_id']!=source or not claim['reason'].strip():sf.fail('Explicit incorrect DR claim was not handled')
        spans=[span(s) for s in claim['evidence_selectors']]
        if not any(e['source']==source for e in spans):sf.fail('Explicit claim needs its own original source')
        new['findings'].append(copy.deepcopy(claim['finding']))
        audit.append({'operation':'EXPLICIT_DR_CLAIM_REVIEW','source':source,'review':copy.deepcopy(claim),'materialized_evidence':spans})
        for o in new['ledger_outcomes']:
            if o['outcome']!='ESCALATED':sf.fail('Unexpected ledger scope')
            original=copy.deepcopy(o)
            if o['limitation'].strip().upper() not in {'NONE','N/A'}:
                o['reason']+=' Original unresolved risk (not accepted): '+o['limitation'];o['limitation']='NONE'
            audit.append({'operation':'MOVE_UNACCEPTED_RISK_TO_REASON','before':original,'after':copy.deepcopy(o)})
    else:
        keys=lambda xs:[x['requirement_id']+'/'+x['criterion_id'] for x in xs]
        d.exact(keys(answer['criterion_corrections']),keys(c['targets']),'Only failed criteria')
        def materialize(row):
            return {'id':row['criterion_id'],'status':row['status'],'reason':row['reason'],'needed_material':row['needed_material'],
                    'evidence':[span(s) for s in row['evidence_selectors']]}
        for row in answer['criterion_corrections']:
            m=next(m for m in new['matches'] if m['requirement_id']==row['requirement_id']);i=next(i for i,x in enumerate(m['criteria']) if x['id']==row['criterion_id'])
            m['criteria'][i]=materialize(row)
        d.exact([m['requirement_id'] for m in answer['missing_matches']],c['missing_requirements'],'Missing match completion')
        for row in answer['missing_matches']:
            rid=row['requirement_id'];plan=next(x for x in full['criterion_plans'] if x['requirement_id']==rid)
            d.exact([x['criterion_id'] for x in row['criteria']],[x['id'] for x in plan['criteria']],'Missing requirement criteria')
            if any(x['requirement_id']!=rid for x in row['criteria']):sf.fail('Cross-requirement criterion')
            new['matches'].append({'requirement_id':rid,'status':'UNRESOLVED','source_ids':[],'reason':row['reason'],'needed_material':row['needed_material'],
                                  'criteria':[materialize(x) for x in row['criteria']],'deferred_outputs':[]})
        d.exact([x['target'] for x in answer['deferred_evidence_corrections']],[x['target'] for x in c['deferred_targets']],'Only failed deferred citations')
        for op in answer['deferred_evidence_corrections']:
            target=next(t for t in c['deferred_targets'] if t['target']==op['target'])
            m=next(m for m in new['matches'] if m['requirement_id']==target['requirement_id'])
            m['deferred_outputs'][target['output_index']]['evidence']=[span(s) for s in op['evidence_selectors']]
        for m in new['matches']:
            before={k:copy.deepcopy(m[k]) for k in ['source_ids','status','reason']}
            m['source_ids']=list(dict.fromkeys(e['source'] for cr in m['criteria'] for e in cr['evidence']))
            agg=review.coverage.aggregate(m['criteria']);status='UNRESOLVED' if agg in {'PARTIAL','CONFLICT'} else agg
            if status!=m['status']:
                m['reason']+=f' Host aggregate from the preserved/corrected criteria is {status}; original model rationale above is retained for audit.'
            m['status']=status
            audit.append({'operation':'ORIGINAL_HOST_AGGREGATION','requirement_id':m['requirement_id'],'before':before,
                          'after':{k:copy.deepcopy(m[k]) for k in before}})
    # The old part request identity stays explicit; the new patch has its own bound request/proof.
    d.validate_schema(new,d.ADEQUACY_REVIEW);review.validate_part(new,part,full)
    return new,audit


def verify_proof(path):
    proof=read_json(path)
    if proof.get('attribution')=='HOST_DERIVED_SAVED_PATCH_CONTINUATION':return verify_continuation_proof(path)
    if proof['version']!=VERSION or proof['attribution']!='HOST_DERIVED_TARGETED_REVIEW':sf.fail('Invalid review repair attribution')
    for k in ['contract_ref','patch_request_ref','raw_patch_ref','derived_response_ref','derivation_audit_ref']:check_ref(proof[k])
    c=read_json(proof['contract_ref']['path']);q=read_json(proof['patch_request_ref']['path']);a=read_json(proof['raw_patch_ref']['path'])
    if q!=request_for(payload(c),schema(c)) or a['request_sha256']!=q['request_sha256']:sf.fail('Repair actual request binding differs')
    new,audit=derive(a,c)
    if new!=read_json(proof['derived_response_ref']['path']) or audit!=read_json(proof['derivation_audit_ref']['path']):sf.fail('Review derivation replay differs')
    return new,c


def execute(run,contract_path,*,generator=None):
    run=Path(run);sf.verify_run(run);c=read_json(contract_path);bound=file_ref(contract_path);checked={}
    def check(a):check_ref(bound);checked[a['request_sha256']]=derive(a,c);return True
    a=sf.invoke(run,'DC-review',payload(c),schema(c),generator=generator,check=check);new,audit=checked[a['request_sha256']]
    qs=[q for q in (run/'data_agents/audit/DC-review').glob('*/request.json') if read_json(q)['request_sha256']==a['request_sha256']]
    if not qs:sf.fail('Actual repair request missing')
    return _publish_saved(run,contract_path,qs[0],qs[0].parent/'response.json',new,audit,replayed=False)


def _publish_saved(run,contract_path,request_path,response_path,new,audit,*,replayed):
    run=Path(run);c=read_json(contract_path);a=read_json(response_path)
    folder=run/'data_agents/review_fix'/a['request_sha256'][:12]
    proof={'version':VERSION,'attribution':'HOST_DERIVED_TARGETED_REVIEW','contract_ref':file_ref(contract_path),'patch_request_ref':file_ref(request_path),
           'raw_patch_ref':file_ref(response_path),'derived_response_ref':file_ref(write_json(folder/'response.json',new)),
           'derivation_audit_ref':file_ref(write_json(folder/'derivation.json',audit)),'code_ref':file_ref(__file__),'scientific_approval':False,
           'publication_mode':'REPLAY_SAVED_MODEL_PATCH' if replayed else 'AFTER_MODEL_PATCH',
           'new_provider_calls_at_publication':0}
    pp=write_json(folder/'proof.json',proof);verify_proof(pp)
    index=read_json(run/INDEX) if (run/INDEX).exists() else {'version':VERSION,'parts':{}}
    index['parts'][c['part_id']]=file_ref(pp);write_json(run/INDEX,index)
    return {'status':'REVIEW_PART_REPAIRED','part_id':c['part_id'],'proof_ref':file_ref(pp),'decision':new['decision'],'scientific_approval':False}


def replay_saved_patch(run,contract_path,request_path,response_path):
    """Validate and publish exactly a saved response. Never invokes a provider."""
    run=Path(run).resolve();lock=run/'.stage.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
    try:
        sf.verify_run(run);c=read_json(contract_path);q=read_json(request_path);a=read_json(response_path)
        refs=[file_ref(p) for p in [contract_path,request_path,response_path]]
        if q!=request_for(payload(c),schema(c)) or a['request_sha256']!=q['request_sha256']:sf.fail('Saved repair request/response binding differs')
        new,audit=derive(a,c)
        for ref in refs:check_ref(ref)
        result=_publish_saved(run,contract_path,request_path,response_path,new,audit,replayed=True)
        sf.emit(run,'SAVED_REVIEW_PATCH_REPLAYED',part=c['part_id'],model_calls=0,result=result)
        return {**result,'model_calls':0,'replayed_saved_response_ref':refs[2]}
    finally:lock.unlink()


def prepare_continuation(parent_contract,request_path,response_path,output):
    parent=read_json(parent_contract);q=read_json(request_path);a=read_json(response_path)
    if q!=request_for(payload(parent),schema(parent)) or a['request_sha256']!=q['request_sha256']:sf.fail('Continuation saved patch binding differs')
    d.validate_schema(a,schema(parent))
    if parent['part_id']!='REVIEW_001' or parent['missing_requirements']!=['SFQ5']:sf.fail('Unexpected continuation scope')
    c={'version':CONTINUATION,'parent_contract_ref':file_ref(parent_contract),'original_patch_request_ref':file_ref(request_path),
       'fixed_patch_ref':file_ref(response_path),'requirement_id':'SFQ5','criterion_ids':['FULL_REQUIREMENT','FIELD_008'],
       'scientific_approval':False}
    write_json(output,c);return c


def _continuation_load(c):
    if c['version']!=CONTINUATION or c['requirement_id']!='SFQ5' or c['criterion_ids']!=['FULL_REQUIREMENT','FIELD_008']:sf.fail('Unknown continuation target scope')
    for key in ['parent_contract_ref','original_patch_request_ref','fixed_patch_ref']:check_ref(c[key])
    parent=read_json(c['parent_contract_ref']['path']);q=read_json(c['original_patch_request_ref']['path']);a=read_json(c['fixed_patch_ref']['path'])
    if q!=request_for(payload(parent),schema(parent)) or a['request_sha256']!=q['request_sha256']:sf.fail('Original continuation request differs')
    if parent['part_id']!='REVIEW_001':sf.fail('Unexpected original review part')
    full,part,old=_load(parent)
    return parent,full,part,old,a


def continuation_schema(c):
    if c['version']=='SOURCE_FIRST_REVIEW_PATCH_CONTINUATION_2.0':
        from .data_source_first_review_repair002 import schema as target_schema
        return target_schema(c)
    row=obj(criterion_id=enum(*c['criterion_ids']),status=STATUS,reason=S,needed_material=S,evidence_selectors=arr(SELECTOR))
    return obj(request_sha256=S,row_replacements=arr(row))


def continuation_payload(c):
    if c['version']=='SOURCE_FIRST_REVIEW_PATCH_CONTINUATION_2.0':
        from .data_source_first_review_repair002 import payload as target_payload
        return target_payload(c)
    parent,full,part,old,a=_continuation_load(c);rid=c['requirement_id']
    need=next(n for n in full['requirements']['requirements'] if n['id']==rid)
    plan=next(p for p in full['criterion_plans'] if p['requirement_id']==rid)
    original_visible=review.visible_sources(payload(parent));allowed=set(plan['allowed_source_ids'])
    catalog={s:copy.deepcopy(v) for s,v in full['evidence_catalog'].items() if s in allowed and s in original_visible
             and v['content'] in original_visible[s]}
    rules=[copy.deepcopy(rule) for rule in payload(parent)['project_rules'] if rule['id'] in need['rule_ids'] or 'rule:'+rule['id'] in allowed]
    fixed=next(m for m in a['missing_matches'] if m['requirement_id']==rid)
    return {'operation':'REPAIR_TWO_ROWS_OF_FIXED_REVIEW_PATCH','part_id':'REVIEW_001_SFQ5_CONTINUATION','version':CONTINUATION,
        'fixed_patch_sha256':c['fixed_patch_ref']['sha256'],'requirement':need,
        'task':next(t for t in full['requirements']['tasks'] if t['id']==need['task_id']),
        'criterion_plan':plan,'repair_criterion_ids':c['criterion_ids'],
        'locked_other_criteria_non_evidence':[x for x in fixed['criteria'] if x['criterion_id'] not in c['criterion_ids']],
        'evidence_catalog':catalog,'context_sources':{},'project_rules':rules,'method_knowledge':None,
        'instructions':'Only replace the two specified SFQ5 criterion rows of the fixed saved model patch. All eleven other returned rows '
        'and all remaining response fields stay locked. For FULL_REQUIREMENT, the prior PARTIAL cited only SOURCE_HEADER and MAIN; '
        'for a DATA requirement, supported/partial availability needs actual SOURCE_CONTENT, not a numeric statement in a header or note. '
        'Choose genuinely supporting allowed body evidence if present, or state UNRESOLVED/CONFLICT/MISSING as justified with explicit next action. '
        'Do not invent support or automatically downgrade merely to pass. Preserve source-specific binding conflicts and all applicability limits. '
        'FIELD_008 previously selected F0004:S1:T15:A210 outside this requirement allowed set. Use only visible allowed entries or keep the issue '
        'unresolved. Every catalog entry shows its original kind and content. Select source with field=CONTENT; for rule:Rxxx only use its '
        'operative field selector. No measurements, bindings, species, matrix, dose basis or source distinctions may be fabricated or merged. '
        'The host explicitly materializes selected original text, preserves all other rows, and runs every original validation and aggregation. '
        +review.coverage.INSTRUCTIONS}


def derive_continuation(answer,c):
    if c['version']=='SOURCE_FIRST_REVIEW_PATCH_CONTINUATION_2.0':
        from .data_source_first_review_repair002 import derive as target_derive
        return target_derive(answer,c)
    parent,full,part,old,fixed=_continuation_load(c);d.validate_schema(answer,continuation_schema(c))
    d.exact([x['criterion_id'] for x in answer['row_replacements']],c['criterion_ids'],'Exactly two failed criterion rows')
    corrected=copy.deepcopy(fixed);match=next(m for m in corrected['missing_matches'] if m['requirement_id']==c['requirement_id'])
    supplied=continuation_payload(c);main=read_json(parent['main_ref']['path']);local_audit=[]
    for row in answer['row_replacements']:
        # New selectors must be visible in this small continuation, not merely in the old large request.
        for selector in row['evidence_selectors']:_span(selector,supplied,full,main=main,audit=local_audit)
        index=next(i for i,x in enumerate(match['criteria']) if x['criterion_id']==row['criterion_id'])
        match['criteria'][index]={'requirement_id':c['requirement_id'],**copy.deepcopy(row)}
    result,audit=derive(corrected,parent)
    return result,corrected,[{'operation':'REPLACE_ONLY_TWO_SAVED_PATCH_ROWS','fixed_patch_ref':c['fixed_patch_ref'],
        'requirement_id':c['requirement_id'],'criterion_ids':c['criterion_ids']},*local_audit,*audit]


def verify_continuation_proof(path):
    p=read_json(path)
    if p['version'] not in {CONTINUATION,'SOURCE_FIRST_REVIEW_PATCH_CONTINUATION_2.0'}:sf.fail('Unknown saved patch continuation proof')
    for key in ['contract_ref','patch_request_ref','raw_patch_ref','corrected_patch_ref','derived_response_ref','derivation_audit_ref']:check_ref(p[key])
    c=read_json(p['contract_ref']['path']);q=read_json(p['patch_request_ref']['path']);a=read_json(p['raw_patch_ref']['path'])
    if q!=request_for(continuation_payload(c),continuation_schema(c)) or a['request_sha256']!=q['request_sha256']:sf.fail('Continuation actual request differs')
    result,corrected,audit=derive_continuation(a,c)
    if (result!=read_json(p['derived_response_ref']['path']) or corrected!=read_json(p['corrected_patch_ref']['path'])
        or audit!=read_json(p['derivation_audit_ref']['path'])):sf.fail('Continuation replay differs')
    return result,read_json(c['parent_contract_ref']['path'])


def execute_continuation(run,contract_path,*,generator=None):
    run=Path(run);sf.verify_run(run);c=read_json(contract_path);bound=file_ref(contract_path);checked={}
    def check(a):check_ref(bound);checked[a['request_sha256']]=derive_continuation(a,c);return True
    a=sf.invoke(run,'DC-review',continuation_payload(c),continuation_schema(c),generator=generator,check=check)
    result,corrected,audit=checked[a['request_sha256']]
    qs=[q for q in (run/'data_agents/audit/DC-review').glob('*/request.json') if read_json(q)['request_sha256']==a['request_sha256']]
    if not qs:sf.fail('Actual continuation request missing')
    folder=run/'data_agents/review_fix'/a['request_sha256'][:12]
    p={'version':c['version'],'attribution':'HOST_DERIVED_SAVED_PATCH_CONTINUATION','contract_ref':bound,
       'patch_request_ref':file_ref(qs[0]),'raw_patch_ref':file_ref(qs[0].parent/'response.json'),
       'corrected_patch_ref':file_ref(write_json(folder/'corrected_patch.json',corrected)),
       'derived_response_ref':file_ref(write_json(folder/'response.json',result)),
       'derivation_audit_ref':file_ref(write_json(folder/'derivation.json',audit)),'scientific_approval':False,'code_ref':file_ref(__file__)}
    if c['version']=='SOURCE_FIRST_REVIEW_PATCH_CONTINUATION_2.0':
        from . import data_source_first_review_repair002 as target_module
        p['target_code_ref']=file_ref(target_module.__file__)
    pp=write_json(folder/'proof.json',p);verify_proof(pp)
    index=read_json(run/INDEX) if (run/INDEX).exists() else {'version':VERSION,'parts':{}}
    part_id=read_json(c['parent_contract_ref']['path'])['part_id']
    index['parts'][part_id]=file_ref(pp);write_json(run/INDEX,index)
    return {'status':'REVIEW_PART_CONTINUED','part_id':part_id,'proof_ref':file_ref(pp),'decision':result['decision'],'scientific_approval':False}


def load_checked_response(run,part,full):
    path=Path(run)/INDEX
    if not path.exists():return None
    index=read_json(path)
    if index['version']!=VERSION:sf.fail('Unknown repair index')
    ref=index['parts'].get(part['part_id'])
    if ref is None:return None
    check_ref(ref);new,c=verify_proof(ref['path'])
    bound=frozen_part(part,read_json(c['original_request_ref']['path']))
    if digest(bound)!=c['part_sha256']:sf.fail('Current review part differs from repaired original request')
    review.validate_part(new,part,full);return new


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',required=True);parser.add_argument('--contract',required=True);parser.add_argument('--continue-patch',action='store_true')
    args=parser.parse_args();run=Path(args.out).resolve();lock=run/'.stage.lock';fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.close(fd)
    try:
        sf.emit(run,'STAGE_START',stage='review_target_repair',model_for_new_calls=sf.MODEL)
        result=(execute_continuation if args.continue_patch else execute)(run,args.contract)
        sf.emit(run,'STAGE_END',stage='review_target_repair',result=result);print(json.dumps(result,ensure_ascii=False))
    except Exception as exc:
        sf.emit(run,'STAGE_ERROR',stage='review_target_repair',error=str(exc));raise
    finally:lock.unlink()


if __name__=='__main__':main()
