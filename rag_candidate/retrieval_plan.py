"""Explicit deterministic subquestions, independent recall and shared evidence dedup.

No source permissions inferred from similarity or biological keywords. Source
IDs for each question must be supplied by the caller. No provider or embeddings.
"""
from __future__ import annotations
import copy
from contextlib import closing
from pathlib import Path
import json
from .rag_v1 import (RagError, _packet, _fits, canonical, check_refs, digest,
                    file_ref, library_policy, query_terms, read_json, retrieve, open_library, source_path)

VERSION = 'SUBQUESTION_RETRIEVAL_PLAN_1.2'

QUESTIONS = (
    ('sampling_design', ['MP001','MP003','MP004'], 'destructive serial sampling individual group mean covariance'),
    ('censoring', ['MP001','MP004'], 'BLQ LLOQ censored missing'),
    ('nca_inputs', ['MP001','MP002','MP003'], 'AUC finite window terminal slope dose concentration'),
    ('model_inputs', ['MP004'], 'population pharmacokinetic dose time covariate'),
    ('pd_inputs', ['MP009','MP012'], 'MIC dose fractionation bacterial burden exposure response'),
    ('binding_inputs', ['MP007'], 'protein binding unbound plasma concentration'),
    ('pta_inputs', ['MP010'], 'probability target attainment MIC distribution simulation'),
)


def data_requirements_demand(payload, decisions, question_source_ids):
    """Resolve declared information needs BEFORE library access.

    The caller assesses sufficiency; this function validates explicit dispositions
    and binds their exact input basis. Profile presence alone never requests RAG.
    A zero-question result means no optional background, not scientific approval.
    """
    if payload.get('stage') != 'DR' or payload.get('operation') not in {'REQUIREMENT_PLAN_4.0','REQUIREMENT_PLAN_5.0','REQUIREMENT_PLAN_5.1','REQUIREMENT_PLAN_6.0'}:
        raise RagError('Demand contract requires a supported current DR input')
    profiles = {p['id'] for p in payload['method_knowledge']['profiles']}
    required = {name for name, ids, _ in QUESTIONS if profiles.intersection(ids)}
    if (not isinstance(decisions, list) or any(not isinstance(d,dict) for d in decisions)
            or {d.get('id') for d in decisions} != required or len(decisions) != len(required)):
        raise RagError('Every applicable topic needs exactly one explicit retrieval disposition')
    unresolved = {}; checks = []
    for decision in decisions:
        name = decision['id']
        if not isinstance(decision.get('reason'), str) or not decision['reason'].strip():
            raise RagError('Retrieval disposition needs a task-specific reason')
        status = decision.get('status')
        refs = decision.get('input_refs', [])
        if not isinstance(refs, list) or (status == 'USE_EXISTING_INPUT' and not refs):
            raise RagError('Existing-input disposition needs exact supporting input pointers')
        bindings = []
        for pointer in refs:
            if not isinstance(pointer, str) or not pointer.startswith('/'):
                raise RagError('Input reference must be a JSON pointer')
            value = payload
            try:
                for raw in pointer[1:].split('/'):
                    token = raw.replace('~1', '/').replace('~0', '~')
                    value = value[int(token)] if isinstance(value, list) else value[token]
            except (KeyError, IndexError, ValueError, TypeError) as exc:
                raise RagError('Unresolved task input pointer: ' + pointer) from exc
            if value in (None, '', [], {}):
                raise RagError('Empty input cannot support a retrieval disposition')
            bindings.append({'pointer': pointer, 'sha256': digest(value)})
        if status == 'RETRIEVE':
            if not isinstance(decision.get('question'), str) or not decision['question'].strip():
                raise RagError('Retrieval needs a concrete unanswered question')
            if not isinstance(decision.get('query'), str) or not decision['query'].strip():
                raise RagError('Retrieval needs an explicit question-specific query')
            if not question_source_ids.get(name):
                raise RagError('Unanswered question needs an explicit source scope')
            unresolved[name] = decision
        elif status != 'USE_EXISTING_INPUT':
            raise RagError('Unknown retrieval disposition')
        checks.append({**copy.deepcopy(decision), 'input_bindings': bindings})
    plan = None
    if unresolved:
        plan = data_requirements_plan(payload, {key: question_source_ids[key] for key in unresolved})
        for question in plan['subquestions']:
            declared = unresolved[question['id']]
            question['query'] = declared['query']
            question['information_need'] = declared['question']
        validate_plan(plan)
    return {'version': 'TASK_RETRIEVAL_DEMAND_1.0', 'payload_sha256': digest(payload),
            'decisions': checks, 'plan': plan,
            'status': 'EXTERNAL_BACKGROUND_REQUESTED' if plan else 'NO_EXTERNAL_BACKGROUND_REQUESTED',
            'sufficiency_is_caller_assessment': True, 'scientific_approval': False}


def verify_demand(payload, demand):
    """Reject a stale sufficiency decision rather than rebinding it to new inputs."""
    if not isinstance(demand,dict) or demand.get('version') != 'TASK_RETRIEVAL_DEMAND_1.0' or demand.get('payload_sha256') != digest(payload):
        raise RagError('Retrieval demand belongs to different task inputs')
    scopes = {q['id']: q['allowed_source_ids'] for q in (demand.get('plan') or {}).get('subquestions', [])}
    decisions = [{key: value for key, value in row.items() if key != 'input_bindings'} for row in demand['decisions']]
    if data_requirements_demand(payload, decisions, scopes) != demand:
        raise RagError('Retrieval demand or its input bindings changed')
    return demand

def data_requirements_plan(payload, question_source_ids, *, max_unit_bytes=5500):
    """Use approved payload MPs only; explicit source lists determine authorization.

    Unsupported source-scoped questions are absent, and recorded as not planned;
    absence is never a claim of complete scientific coverage.
    """
    if payload.get('stage') != 'DR' or payload.get('operation') not in {'REQUIREMENT_PLAN_4.0','REQUIREMENT_PLAN_5.0','REQUIREMENT_PLAN_5.1','REQUIREMENT_PLAN_6.0'}:
        raise RagError('Automatic question template requires a supported DR payload')
    allowed = sorted(p['id'] for p in payload['method_knowledge']['profiles'])
    questions = []
    for name, profiles, query in QUESTIONS:
        used = sorted(set(profiles) & set(allowed))
        if used and name in question_source_ids:
            questions.append({'id':name, 'query':query, 'method_profile_ids':used,
                'allowed_source_ids':sorted(set(question_source_ids[name])),
                'max_units':2, 'max_units_per_source':1, 'max_unit_bytes':max_unit_bytes})
    plan = {'version':VERSION, 'stage':'data.requirements', 'topic':'data_eda',
        'context_scope':payload.get('policy',{}).get('scope'), 'allowed_method_profile_ids':allowed,
        'subquestions':questions, 'raw_only':True, 'max_total_units_per_source':2,
        'not_planned_questions':[q[0] for q in QUESTIONS if q[0] not in {v['id'] for v in questions}]}
    validate_plan(plan)
    return plan

def validate_plan(plan):
    if not isinstance(plan,dict) or plan.get('version') != VERSION or plan.get('stage') not in {'data.requirements','data.necessity'} or plan.get('topic') != 'data_eda':
        raise RagError('Unsupported subquestion plan')
    if plan.get('context_scope') != 'NONHUMAN_PLANNING':
        raise RagError('Subquestion planning needs explicit current nonhuman scope')
    if type(plan.get('raw_only')) is not bool or type(plan.get('max_total_units_per_source')) is not int or plan['max_total_units_per_source'] < 1:
        raise RagError('Invalid explicit plan quotas')
    allowed=plan.get('allowed_method_profile_ids')
    if not isinstance(allowed,list) or not allowed or allowed != sorted(set(allowed)) or any(not isinstance(v,str) or not v for v in allowed):
        raise RagError('Explicit canonical allowed MP IDs required')
    questions=plan.get('subquestions')
    if not isinstance(questions,list) or not 1 <= len(questions) <= 12:
        raise RagError('Bounded nonempty subquestion list required')
    ids=[]
    for q in questions:
        if not isinstance(q,dict) or not isinstance(q.get('id'),str) or not q['id'] or not isinstance(q.get('query'),str) or not q['query'].strip():
            raise RagError('Question identity/query required')
        ids.append(q['id'])
        for name in ('allowed_source_ids','method_profile_ids'):
            values=q.get(name)
            if not isinstance(values,list) or not values or values != sorted(set(values)) or any(not isinstance(v,str) or not v for v in values):
                raise RagError('Explicit canonical question scope required: '+name)
        if not set(q['method_profile_ids']) <= set(allowed):
            raise RagError('Question tries to add an unapproved method profile')
        for name in ('max_units','max_units_per_source','max_unit_bytes'):
            if type(q.get(name)) is not int or q[name] < 1:
                raise RagError('Positive integer question quota required')
        if q['max_units'] > 6 or q['max_unit_bytes'] > 24000:
            raise RagError('Question quota exceeds local bounded plan')
    if len(ids) != len(set(ids)): raise RagError('Duplicate question IDs')
    return plan

def verify_plan_selection(data):
    """Additional replay invariants beyond ordinary authoritative DB validation."""
    plan=data['scope'].get('retrieval_plan')
    if plan is None: return
    validate_plan(plan)
    if data['scope'].get('budget_semantics') != 'MODEL_BACKGROUND_CHARACTERS_HOST_ENVELOPE_BYTES':
        raise RagError('Planned packet lacks explicit model/host budget semantics')
    if 'subquestion_plan' in data['bindings'] and read_json(data['bindings']['subquestion_plan']['path']) != plan:
        raise RagError('Frozen plan file differs from packet plan')
    if plan['stage'] != data['scope']['stage'] or plan['topic'] != data['scope']['topic'] or plan['raw_only'] != data['scope']['raw_only']:
        raise RagError('Plan route/raw scope differs from packet')
    if sorted({sid for q in plan['subquestions'] for sid in q['allowed_source_ids']}) != data['scope']['allowed_source_ids']:
        raise RagError('Plan source authorization differs from packet')
    questions={q['id']:q for q in plan['subquestions']}
    chunks={c['id']:c for c in data['chunks']}; cards={c['id']:c for c in data['cards']}
    question_counts={key:0 for key in questions}; source_counts={}; per_question={}
    for unit in data['units']:
        item=chunks[unit['id']] if unit['kind']=='chunk' else cards[unit['id']]
        sids=[item['source_id']] if unit['kind']=='chunk' else item['source_ids']
        qids=unit.get('question_ids')
        if not isinstance(qids,list) or not qids or qids != sorted(set(qids)) or not set(qids)<=questions.keys():
            raise RagError('Selected evidence lacks valid question associations')
        for sid in sids: source_counts[sid]=source_counts.get(sid,0)+1
        for qid in qids:
            q=questions[qid]
            if not set(sids)<=set(q['allowed_source_ids']): raise RagError('Question evidence violates explicit source scope')
            evidence=[item] if unit['kind']=='chunk' else [item]+[chunks[cid] for cid in item['evidence_chunk_ids']]
            if len(canonical(evidence).encode('utf-8'))>q['max_unit_bytes']: raise RagError('Question whole-unit quota exceeded')
            question_counts[qid]+=1
            for sid in sids:
                key=(qid,sid); per_question[key]=per_question.get(key,0)+1
                if per_question[key]>q['max_units_per_source']: raise RagError('Question source quota exceeded')
    if any(source_counts[sid]>plan['max_total_units_per_source'] for sid in source_counts): raise RagError('Global source quota exceeded')
    if any(question_counts[key]>questions[key]['max_units'] for key in questions): raise RagError('Question unit quota exceeded')
    reports=data.get('subquestion_results')
    if not isinstance(reports,list) or [r['question_id'] for r in reports] != list(questions): raise RagError('Question coverage ledger differs from plan')
    for report in reports:
        qid=report['question_id']; ids=[{'kind':u['kind'],'id':u['id']} for u in data['units'] if qid in u['question_ids']]
        if report['selected_units'] != ids or report['status'] != ('BACKGROUND_RECALLED_REQUIRES_REVIEW' if ids else 'EVIDENCE_GAP'):
            raise RagError('Question coverage ledger conflicts with selected evidence')

def retrieve_plan(root, plan, *, source_statuses, card_statuses, access_levels,
                  allow_draft=False, budget_bytes=60000, limit=12,
                  config_path=None, excluded_card_ids=(), library_binding_path=None, plan_path=None):
    validate_plan(plan)
    plan=copy.deepcopy(plan)
    # Each question independently freezes and verifies its complete permitted sources.
    # All child bindings are rechecked after all retrievals and before final publication.
    children=[]; frozen={}
    if plan_path is not None:
        frozen['subquestion_plan']=file_ref(plan_path)
        if read_json(plan_path) != plan: raise RagError('Plan file differs from explicit supplied plan')
    allowed=sorted({sid for q in plan['subquestions'] for sid in q['allowed_source_ids']})
    with closing(open_library(Path(root)/'knowledge.sqlite')) as db:
        frozen['library']=file_ref(Path(root)/'knowledge.sqlite')
        for sid in allowed:
            row=db.execute('SELECT json FROM sources WHERE id=?',(sid,)).fetchone()
            if row is None: raise RagError('Unknown explicitly allowed source: '+sid)
            meta=json.loads(row[0]);frozen['source:'+sid]=file_ref(source_path(Path(root).resolve(),meta))
            if frozen['source:'+sid]['sha256']!=meta['sha256']: raise RagError('Original source hash mismatch before plan')
    check_refs(frozen)
    for q in plan['subquestions']:
        child=retrieve(root,q['query'],plan['topic'],plan['stage'],q['allowed_source_ids'],
            source_statuses=source_statuses,card_statuses=card_statuses,access_levels=access_levels,
            allow_draft=allow_draft,limit=min(q['max_units']*2,6),budget_bytes=budget_bytes,
            config_path=config_path,excluded_card_ids=excluded_card_ids,raw_only=plan['raw_only'],
            library_binding_path=library_binding_path)
        data=child.to_dict();children.append((q,data))
        for name,ref in data['bindings'].items():
            if name in frozen and frozen[name] != ref: raise RagError('Input changed between questions')
            frozen[name]=ref
    first=children[0][1]; scope=copy.deepcopy(first['scope'])
    scope.update(allowed_source_ids=sorted({sid for q in plan['subquestions'] for sid in q['allowed_source_ids']}),limit=limit,retrieval_plan=plan,
                 budget_semantics='MODEL_BACKGROUND_CHARACTERS_HOST_ENVELOPE_BYTES')
    config=read_json(first['bindings']['config']['path'])
    if type(limit) is not int or not 1<=limit<=config['max_units']: raise RagError('Plan total units outside config')
    query=' '.join(q['query'] for q in plan['subquestions']); terms,_=query_terms(query,config)
    data=copy.deepcopy(first)
    data.update(query=query,query_terms=terms,scope=scope,scope_sha256=digest(scope),units=[],cards=[],chunks=[],sources={},
        bindings={k:v for k,v in frozen.items() if not k.startswith('source:')},
        omissions={'budget_units':0,'limit_units':0,'duplicate_raw_units':0,'filtered_hits':{'cards':0,'chunks':0},'quota_units':0},
        subquestion_results=[],status='NO_MATCH_NOT_EVIDENCE_OF_ABSENCE',empty_reason='SUBQUESTIONS_HAVE_NO_FITTING_ELIGIBLE_EVIDENCE')
    data['gaps'].append('Question recall is lexical background, not completed applicability or requirement coverage.')
    policy=library_policy(data['bindings'],Path(root).resolve(),scope)
    source_counts={}; per_question={}; omitted={q['id']:{} for q in plan['subquestions']}
    def omit(qid,reason): omitted[qid][reason]=omitted[qid].get(reason,0)+1
    def reports(target):
        target['subquestion_results']=[]
        for q,child in children:
            selected=[{'kind':u['kind'],'id':u['id']} for u in target['units'] if q['id'] in u['question_ids']]
            target['subquestion_results'].append({'question_id':q['id'],'selected_units':selected,
                'status':'BACKGROUND_RECALLED_REQUIRES_REVIEW' if selected else 'EVIDENCE_GAP',
                'omissions':[{'reason':reason,'count':count} for reason,count in sorted(omitted[q['id']].items())],
                'retrieval_empty_reason':child['empty_reason']})
    reports(data)
    if not _fits(_packet(data),budget_bytes,policy): raise RagError('Plan provenance and question ledger exceed budget')
    # Round-robin preserves the first opportunity for each independent question.
    for index in range(max(len(d['units']) for q,d in children)):
        for q, child in children:
            if index>=len(child['units']): continue
            unit=child['units'][index]; key=(unit['kind'],unit['id'])
            item=next(v for v in child['chunks' if unit['kind']=='chunk' else 'cards'] if v['id']==unit['id'])
            cited=[item] if unit['kind']=='chunk' else [v for v in child['chunks'] if v['id'] in item['evidence_chunk_ids']]
            sids=sorted({c['source_id'] for c in cited})
            existing=next((u for u in data['units'] if (u['kind'],u['id'])==key),None)
            qcount=sum(q['id'] in u['question_ids'] for u in data['units'])
            if qcount>=q['max_units'] or any(per_question.get((q['id'],sid),0)>=q['max_units_per_source'] for sid in sids):
                omit(q['id'],'QUESTION_OR_SOURCE_QUOTA');data['omissions']['quota_units']+=1;continue
            if len(canonical(([item] if unit['kind']=='card' else [])+cited).encode('utf-8'))>q['max_unit_bytes']:
                omit(q['id'],'WHOLE_UNIT_TOO_LARGE');data['omissions']['quota_units']+=1;continue
            if not existing and (len(data['units'])>=limit or any(source_counts.get(sid,0)>=plan['max_total_units_per_source'] for sid in sids)):
                omit(q['id'],'GLOBAL_UNIT_OR_SOURCE_QUOTA');data['omissions']['quota_units']+=1;continue
            trial=copy.deepcopy(data)
            trial.update(status='OPTIONAL_BACKGROUND_FOR_LOCAL_REVIEW',empty_reason=None)
            if existing:
                dest=next(u for u in trial['units'] if (u['kind'],u['id'])==key);dest['question_ids']=sorted(set(dest['question_ids'])|{q['id']})
            else:
                trial['units'].append({'kind':unit['kind'],'id':unit['id'],'rank':len(trial['units'])+1,'question_ids':[q['id']]})
                if unit['kind']=='card': trial['cards'].append(item)
                seen={c['id'] for c in trial['chunks']};trial['chunks'].extend(c for c in cited if c['id'] not in seen)
                for sid in sids:
                    trial['sources'][sid]=child['sources'][sid];trial['bindings']['source:'+sid]=child['bindings']['source:'+sid]
            reports(trial)
            if not _fits(_packet(trial),budget_bytes,policy):
                omit(q['id'],'WHOLE_PACKET_BUDGET');data['omissions']['budget_units']+=1;continue
            data=trial
            for sid in sids:
                per_question[(q['id'],sid)]=per_question.get((q['id'],sid),0)+1
                if not existing: source_counts[sid]=source_counts.get(sid,0)+1
    reports(data)
    if data['units']: data.update(status='OPTIONAL_BACKGROUND_FOR_LOCAL_REVIEW',empty_reason=None)
    else: data['empty_reason']='SUBQUESTIONS_HAVE_NO_FITTING_ELIGIBLE_EVIDENCE'
    packet=_packet(data)
    if not _fits(packet,budget_bytes,policy): raise RagError('Final question ledger exceeds budget; no content truncated')
    check_refs(frozen)
    verify_plan_selection(data)
    return packet.verify()
