"""One synchronous resolver: reuse -> recall -> bounded refill -> optional judge.

No question planner, scheduler or per-step question inventory. Existing route
and MP definitions seed method topics; upstream needs refine those topics.
All mutable judgments are per-output, never a global sufficient=true flag.
"""
from __future__ import annotations

import copy
from . import ranked_retrieve
from . import reviewed_retrieve
from . import evidence_budget
from . import knowledge_view
from pathlib import Path

from .rag_v1 import RagError, canonical, check_refs, digest, file_ref, read_json
from .ranked_retrieve import load_catalog, retrieve_ranked
from .reviewed_retrieve import model_background
from .retrieval_plan import QUESTIONS

VERSION = 'AUTOMATIC_CONTEXT_RESOLUTION_1.0'

# Shared data roles, not per-step question inventories. Existing method-profile
# associations below continue to own non-EDA method topic selection.
ROLE_TOPICS = {
    'PK': 'concentration time plotting group mean experimental unit',
    'PD': 'response time plotting baseline reference integrity',
    'MIC': 'raw points summary statistics uncertainty labels',
    'BINDING': 'binding assay depletion time exploratory plots',
}


def prepare_request(bundle, artifacts, *, assigned_ids=None, upstream_needs=None, view_budget=24000):
    """Build the small resolver envelope from existing route and formal outputs.

    artifacts must already be authorized by the caller's stage adapter. No
    directory scans or model-selected paths. assigned_ids optionally reuses the
    workflow's existing artifact -> record-ID assignment; otherwise the entire
    supplied artifact is the explicit assigned scope. No upstream re-summary.
    """
    from research_pipeline import context_builder as cb, context_task
    from research_pipeline import context_handoff_selection as context_handoff
    cb.verify_bundle(bundle)
    task = context_task.contract(bundle['context_manifest']['route'])
    payload = bundle['request']['payload']
    project = context_task.at(payload, task['method_retrieval'].get('project_path', [])) or {}
    objective = project.get('objective') or payload.get('objective')
    if not objective:
        objective = payload.get('task_context', {}).get('objective')
    if not isinstance(objective, str) or not objective.strip():
        raise RagError('Current authoritative task objective is required')
    cb.check_refs(artifacts)
    assignments, needs = [], list(copy.deepcopy(upstream_needs or []))
    records = {}
    for aid, ref in artifacts.items():
        formal = read_json(ref['path'])
        index = context_handoff.index_result(formal)
        ids = list(index['records']) if assigned_ids is None else assigned_ids.get(aid, [])
        for rid in ids:
            if rid not in index['records']:
                raise RagError('Workflow assignment references absent record')
            output_id = rid if len(artifacts) == 1 else aid + ':' + rid
            assignments.append({'output_id': output_id, 'artifact_id': aid, 'record_ids': [rid]})
            records[output_id] = index['records'][rid]['value']
        if upstream_needs is None:
            needs.extend(copy.deepcopy(formal.get('context_needs', [])))
    if not assignments:
        raise RagError('No assigned formal outputs')
    if task['method_retrieval']['mode'] == 'EXPLICIT_UNANSWERED_QUESTIONS':
        if task['profile'] == 'eda_plan' and not needs:
            # Existing profile.role selects a topic; ambiguous roles remain
            # explicitly unsupported by automatic seeding, never guessed.
            for output_id, record in records.items():
                role = str(record.get('profile', {}).get('role', record.get('role', ''))).upper()
                if role in ROLE_TOPICS:
                    needs.append({'id': 'display:' + output_id, 'needed_for': [output_id],
                                  'kind': 'method', 'question': 'Display and interpretation conditions for ' + role,
                                  'query': ROLE_TOPICS[role], 'stage': 'data_eda',
                                  'criteria': ['Provide relevant display conditions and limits for the actual '
                                               'record level, units, censoring and relationships in this assigned result.']})
        elif task['profile'] in {'requirements_planning', 'impact_advice'}:
            needs = derive_needs(payload, output_ids=list(records), upstream_needs=needs)
    cb.verify_bundle(bundle)
    cb.check_refs(artifacts)
    return {'version': 'CONTEXT_NEEDS_1.0', 'objective': objective, 'artifacts': copy.deepcopy(artifacts),
            'assignments': assignments, 'needs': needs, 'view_budget': view_budget}


def derive_needs(payload, *, output_ids, upstream_needs=()):
    """Reuse existing MP associations. Does not grant methods or source access.

    No MP and no upstream need means zero method retrieval, not proof that the
    task needs no knowledge. Callers retain their original required context.
    """
    knowledge = payload.get('method_knowledge', payload.get('local_method_knowledge', {}))
    profiles = knowledge.get('profiles', []) if isinstance(knowledge, dict) else []
    allowed = {p['id'] for p in profiles if isinstance(p, dict) and 'id' in p}
    needs = list(copy.deepcopy(upstream_needs))
    declared = {n['id'] for n in needs}
    for name, mps, query in QUESTIONS:
        if allowed.intersection(mps) and name not in declared:
            stage = 'pkpd' if name == 'pd_inputs' else 'pta' if name == 'pta_inputs' else 'animal_pk'
            needs.append({'id': name, 'needed_for': list(output_ids), 'kind': 'method',
                          'question': 'Conditions and limitations for ' + name.replace('_', ' '),
                          'query': query, 'stage': stage,
                          'criteria': ['Explain the applicable input requirements, limitations and fallback '
                                       'for the assigned task; source examples are not project observations.']})
    return needs


def _merge(packets):
    methods, evidence, sources = {}, {}, {}
    for packet in packets:
        view = model_background(packet)
        for item in view['general_methods']:
            if item['id'] in methods and methods[item['id']] != item:
                raise RagError('Conflicting reused method')
            methods[item['id']] = item
        for item in view['applicability_and_examples']['evidence']:
            if item['id'] in evidence and evidence[item['id']] != item:
                raise RagError('Conflicting evidence identity')
            evidence[item['id']] = item
        for key, item in view['applicability_and_examples']['cited_originals'].items():
            if key in sources and sources[key] != item:
                raise RagError('Conflicting original source')
            sources[key] = item
    return {'methods': list(methods.values()), 'evidence': list(evidence.values()),
            'sources': sources}


def _background(view, knowledge, ledger, selected_need_ids=None):
    rows = copy.deepcopy(ledger)
    if selected_need_ids is not None:
        for row in rows:
            if row['status'] in {'SEMANTIC_CHECK_REQUIRED', 'REFERENCE_GUIDANCE_AVAILABLE'} and row['need_id'] not in selected_need_ids:
                row.update(status='BUDGET_GAP', reason='Complete evidence unit omitted by shared task budget',
                           omitted_method_ids=row['method_ids'], method_ids=[], evidence_ids=[], source_reference_ids=[])
    outputs = []
    for item in view['outputs']:
        unresolved = [r['need_id'] for r in rows if item['output_id'] in r['needed_for'] and r['status'] != 'SUPPORTED']
        outputs.append({'output_id': item['output_id'],
            'status': 'LIMITED' if unresolved or item['status'] != 'INPUT_LOADED' else 'READY_WITHIN_DECLARED_SCOPE',
            'unresolved_needs': unresolved, 'input_status': item['status']})
    return {'version': VERSION, 'task_view': view, 'knowledge': knowledge, 'resolutions': rows, 'outputs': outputs,
        'boundary': 'Card guidance and source locators are not visible primary evidence. '
            'REFERENCE_GUIDANCE_AVAILABLE permits conditional input-planning/advice only and is not SUPPORTED. '
            'Per-output assessment of declared dependencies only. No global sufficiency or '
            'scientific approval. LIMITED outputs may describe their gaps but must not execute '
            'the dependent operation. Missing project data cannot be supplied by method literature.'}


class ContextResolver:
    """Configured once per workflow run, with host-owned source permissions.

    semantic_checker, when configured, receives one bounded batch and returns
    {decisions:[{need_id,status,criterion_evidence,reason}],bindings:{...}}.
    Each criterion_evidence is a nonempty list of visible chunk IDs, one per
    criterion. Its binding must identify an audited request/response receipt.
    A judge is never called for every step or every question independently.
    """
    def __init__(self, library_binding, *, source_scope, packet_path, allow_draft=False,
                 branches=(), character_budget=64000, semantic_character_budget=48000,
                 ranker='bm25f', reuse_packets=(), semantic_checker=None, task_projection=True,
                 evidence_mode='auto'):
        if type(character_budget) is not int or not 4000 <= character_budget <= 192000:
            raise RagError('Context budget outside supported bounds')
        if type(semantic_character_budget) is not int or not 1000 <= semantic_character_budget <= 64000:
            raise RagError('Semantic-check budget outside supported bounds')
        self.binding = library_binding
        self.scope = tuple(sorted(set(source_scope)))
        self.packet_path = Path(packet_path)
        self.allow_draft = allow_draft
        self.branches = tuple(branches)
        self.budget = character_budget
        self.semantic_budget = semantic_character_budget
        self.ranker = ranker
        self.reuse = tuple(reuse_packets)
        self.checker = semantic_checker
        self.task_projection = task_projection
        if evidence_mode not in knowledge_view.MODES:
            raise RagError('Unknown evidence delivery mode')
        self.evidence_mode = evidence_mode

    def __call__(self, request, *, task):
        """Called once by context_task.assemble; all refills happen before dispatch."""
        from research_pipeline import context_handoff_selection as context_handoff
        allowed = {'version', 'objective', 'artifacts', 'assignments', 'needs', 'view_budget'}
        if (not isinstance(request, dict) or set(request) - allowed
                or request.get('version') != 'CONTEXT_NEEDS_1.0'
                or not isinstance(request.get('objective'), str) or not request['objective'].strip()):
            raise RagError('Invalid shared context-needs contract')
        view_result = context_handoff.build_view(request['artifacts'], request['assignments'],
                                                character_budget=request.get('view_budget', 24000))
        view = view_result['view']
        output_ids = {o['output_id'] for o in view['outputs']}
        needs = request.get('needs', [])
        if not isinstance(needs, list) or len(needs) > 8:
            raise RagError('At most eight independent needs per task')
        if len({n.get('id') for n in needs}) != len(needs):
            raise RagError('Repeated context need')
        spec = task['method_retrieval']
        can_retrieve = spec['mode'] == 'EXPLICIT_UNANSWERED_QUESTIONS'
        for n in needs:
            if (not isinstance(n, dict) or set(n) - {'id', 'needed_for', 'kind', 'question', 'query',
                    'stage', 'criteria', 'method_ids', 'evidence_mode'} or not isinstance(n.get('id'), str)
                    or not n['id'] or not isinstance(n.get('needed_for'), list)
                    or not n['needed_for'] or not set(n['needed_for']) <= output_ids
                    or n.get('kind') not in {'method', 'project_data'}
                    or not isinstance(n.get('criteria'), list) or not n['criteria']
                    or not all(isinstance(c, str) and c.strip() for c in n['criteria'])):
                raise RagError('Invalid need or affected-output mapping')
            if n['kind'] == 'method' and (not isinstance(n.get('question'), str)
                    or not n['question'].strip() or not isinstance(n.get('query'), str)
                    or not n['query'].strip() or not isinstance(n.get('stage'), str)):
                raise RagError('Method needs require a task and method topic')
            if can_retrieve and n['kind'] == 'method' and n['stage'] not in spec['allowed_stages']:
                raise RagError('Method stage outside registered route')
            knowledge_view.mode_for(task['profile'], n.get('evidence_mode', self.evidence_mode))
        # An assigned input overflow is not repaired by literature retrieval.
        # If any need consumes references only, keep one complete card body for
        # every need. A shared card must not acquire conflicting projections.
        allow_recipe_projection = self.task_projection and all(
            knowledge_view.mode_for(task['profile'], n.get('evidence_mode', self.evidence_mode)) == 'primary_excerpt'
            for n in needs)
        unavailable = {o['output_id'] for o in view['outputs'] if o['status'] != 'INPUT_LOADED'}
        catalog = load_catalog(self.binding) if any(n['kind'] == 'method' for n in needs) else None
        refs = dict(view_result['bindings'])
        refs['resolver:implementation'] = file_ref(__file__)
        refs['resolver:ranker'] = file_ref(ranked_retrieve.__file__)
        refs['resolver:reviewed_retrieve'] = file_ref(reviewed_retrieve.__file__)
        refs['resolver:evidence_budget'] = file_ref(evidence_budget.__file__)
        refs['resolver:knowledge_view'] = file_ref(knowledge_view.__file__)
        refs['resolver:task_evidence'] = file_ref(ranked_retrieve.task_evidence.__file__)
        refs.update(ranked_retrieve.task_evidence.bindings())
        if catalog:
            refs['resolver:library_binding'] = catalog['binding_ref']
            refs.update({'resolver:library:' + k: v for k, v in catalog['binding']['bindings'].items()})
        cached = {}
        for path in self.reuse:
            ref = file_ref(path)
            old = read_json(path)
            if old.get('version') != VERSION or digest({k: v for k, v in old.items() if k != 'sha256'}) != old.get('sha256'):
                raise RagError('Invalid prior context resolution')
            check_refs(old['bindings'])
            refs['resolver:reuse:' + ref['sha256']] = ref
            # Only immutable evidence is reused. Judgments never transfer to a
            # new task, criterion, scope, project state or output assignment.
            for record in old['recalls']:
                cached[record['key']] = record['packet']
        recalls, ledger, candidates, candidate_recalls = [], [], [], []
        retrieval_calls = reuse_hits = 0
        base = {'task_view': view, 'knowledge': _merge([])}
        if len(canonical(base)) + 3000 > self.budget:
            raise RagError('Task view alone exceeds final context budget; narrow assigned work')
        for need in needs:
            delivery = knowledge_view.mode_for(task['profile'], need.get('evidence_mode', self.evidence_mode))
            row = {'need_id': need['id'], 'needed_for': need['needed_for'],
                   'status': 'UNRESOLVED', 'reason': '', 'method_ids': [], 'evidence_ids': [],
                   'evidence_mode':delivery, 'source_reference_ids':[]}
            ledger.append(row)
            if set(need['needed_for']) <= unavailable:
                row.update(status='INPUT_NOT_LOADED', reason='Required project view unavailable')
                continue
            if need['kind'] == 'project_data':
                row.update(status='PROJECT_DATA_GAP', reason='Literature cannot supply missing project observations')
                continue
            if not self.allow_draft:
                raise RagError('Workflow must explicitly configure draft method use')
            if not can_retrieve:
                row.update(status='RETRIEVAL_NOT_PERMITTED', reason='Route consumes assigned upstream evidence only')
                continue
            # The second query is a deterministic expansion of the already
            # supplied acceptance criteria; no separate query-planning model.
            queries = [need['query'], need['query'] + ' ' + ' '.join(need['criteria'])]
            for attempt, query in enumerate(queries):
                key = digest({'library': catalog['binding']['revision'], 'query': query,
                              'stage': need['stage'], 'scope': self.scope, 'branches': self.branches,
                              'ranker': self.ranker, 'method_ids': need.get('method_ids', []),
                              'task_profile': task['profile'] if allow_recipe_projection else None,
                              'evidence_mode':delivery,
                              'max_methods': 1 if attempt == 0 else 2})
                if key in cached:
                    packet = cached[key]
                    reuse_hits += 1
                else:
                    packet = retrieve_ranked(self.binding, question=need['question'], query=query,
                        stage=need['stage'], project_context={'objective': request['objective']},
                        allowed_source_ids=self.scope, branches=self.branches, allow_draft=True,
                        consumer_route=spec['consumer_route'], max_methods=1 if attempt == 0 else 2,
                        character_budget=48000, ranker=self.ranker,
                        method_ids=need.get('method_ids', ()), catalog=catalog,
                        task_profile=task['profile'], card_projection=allow_recipe_projection,
                        evidence_mode=delivery)
                    retrieval_calls += 1
                methods = packet['context']['general_methods']
                if not methods:
                    omitted = packet['context']['selection']['budget_omitted']
                    if omitted:
                        row.update(status='BUDGET_GAP', reason='Relevant complete evidence unit exceeds per-recall budget',
                                   omitted_method_ids=omitted)
                    else:
                        row.update(status='NO_RELEVANT_METHOD', reason='No eligible method passed the lexical relevance gate; not proof of absence')
                    # Generic acceptance-criterion text must not replace the
                    # original topic's relevance gate on a second attempt.
                    break
                # Nonempty fields are only a structural check, not entailment.
                valid = all(c.get('claim') and c.get('conditions') and c.get('required_inputs')
                            and c.get('limitations') and c.get('claim_support') for c in methods)
                valid = valid and all(isinstance(s, dict) and s.get('claim')
                    and s.get('evidence_chunk_ids') and set(s['evidence_chunk_ids']) <= set(c['evidence_chunk_ids'])
                    for c in methods for s in c.get('claim_support', []))
                if not valid:
                    row['reason'] = 'Method lacks conditions, limitations or support mapping'
                    continue
                # Recall first for every need. Allocate once across the complete
                # task rather than spending its budget in caller order.
                task_knowledge, projection = knowledge_view.project(_merge([packet]), delivery)
                candidate_recalls.append({'need_id': need['id'], 'key': key, 'packet': packet, 'task_projection':projection})
                candidates.append({'need_id': need['id'], 'knowledge':task_knowledge})
                row.update(status='SEMANTIC_CHECK_REQUIRED' if delivery == 'primary_excerpt' else 'REFERENCE_GUIDANCE_AVAILABLE',
                           reason='Primary evidence recalled; criteria not yet assessed' if delivery == 'primary_excerpt' else
                           'Task card guidance delivered; source originals retained on host, not visible evidence. No scientific sufficiency verdict.',
                           method_ids=[c['id'] for c in methods],
                           evidence_ids=[c['id'] for c in task_knowledge['evidence']],
                           source_reference_ids=list(task_knowledge.get('source_references', {})))
                break
        background, chosen, allocation = evidence_budget.allocate(candidates,
            lambda selected, packed: _background(view, packed, ledger, selected), budget=self.budget)
        ledger = background['resolutions']
        knowledge = background['knowledge']
        raw_knowledge = evidence_budget.expand(knowledge)
        recalls = [{'key': item['key'], 'packet': item['packet']} for item in candidate_recalls if item['need_id'] in chosen]
        for sid, original in raw_knowledge['sources'].items():
            refs['resolver:original:' + sid] = {
                'path': str((catalog['root'] / original['local_path']).resolve()),
                'sha256': original['sha256']}
        check_refs(refs)
        pending = [n for n in needs if next(r for r in ledger if r['need_id'] == n['id'])['status'] == 'SEMANTIC_CHECK_REQUIRED']
        check_status = 'NOT_NEEDED'
        if pending:
            judge_input = {'objective': request['objective'], 'needs': [{**n, 'evidence_scope': next(r['evidence_ids'] for r in ledger if r['need_id'] == n['id'])} for n in pending],
                           'task_view': view, 'knowledge': knowledge,
                           'instructions': 'For each need assess every criterion against the visible evidence and '
                               'project view. Return SUPPORTED, PARTIAL or UNSUPPORTED. Cite chunk IDs per criterion. '
                               'Each need may cite only its own evidence_scope IDs, even when other needs have '
                               'additional visible excerpts. Missing support remains PARTIAL or UNSUPPORTED. '
                               'Source examples are not project observations. Unknown inputs may permit a limited '
                               'operation, never an unsupported quantitative claim.'}
            if self.checker is None:
                check_status = 'UNAVAILABLE'
            elif len(canonical(judge_input)) > self.semantic_budget:
                check_status = 'CHECK_INPUT_OVER_BUDGET'
            else:
                # One optional batched check, after evidence packing. Never
                # retry or initiate further retrieval on a judge's instructions.
                check_status = 'ATTEMPTED'
                response = self.checker(copy.deepcopy(judge_input))
                check_refs(refs)
                if (not isinstance(response, dict) or set(response) != {'decisions', 'bindings'}
                        or not response['bindings']):
                    raise RagError('Semantic check requires decisions and an audited receipt')
                check_refs(response['bindings'])
                if set(response['bindings']) & set(refs):
                    raise RagError('Semantic receipt binding collision')
                refs.update(response['bindings'])
                decisions = response['decisions']
                if (not isinstance(decisions, list) or len(decisions) != len(pending)
                        or {d.get('need_id') for d in decisions} != {n['id'] for n in pending}):
                    raise RagError('Semantic check omitted or duplicated a need')
                by_need = {n['id']: n for n in pending}
                for decision in decisions:
                    row = next(r for r in ledger if r['need_id'] == decision['need_id'])
                    if (set(decision) != {'need_id', 'status', 'criterion_evidence', 'reason'}
                            or decision['status'] not in {'SUPPORTED', 'PARTIAL', 'UNSUPPORTED', 'UNVERIFIED'}
                            or not isinstance(decision['reason'], str) or not decision['reason'].strip()):
                        raise RagError('Invalid semantic decision')
                    cites = decision['criterion_evidence']
                    if (not isinstance(cites, list) or len(cites) != len(by_need[row['need_id']]['criteria'])
                            or any(not isinstance(c, list) or not set(c) <= set(row['evidence_ids']) for c in cites)
                            or (decision['status'] == 'SUPPORTED' and any(not c for c in cites))):
                        raise RagError('Semantic verdict lacks valid per-criterion evidence')
                    row.update(status=decision['status'], reason=decision['reason'], criterion_evidence=cites)
                check_status = 'COMPLETED_AUTOMATIC_ESTIMATE'
                if any(d['status'] == 'UNVERIFIED' for d in decisions):
                    check_status = 'COMPLETED_WITH_UNVERIFIED_NEEDS'
        background = _background(view, knowledge, ledger)
        if len(canonical(background)) > self.budget:
            raise RagError('Final packed support exceeds budget; nothing truncated')
        context_handoff.verify_view(view_result, request['artifacts'], request['assignments'],
                                    character_budget=request.get('view_budget', 24000))
        check_refs(refs)
        packet = {'version': VERSION, 'request_sha256': digest(request), 'context_request': copy.deepcopy(request),
                  'route': task['route'],
                  'background': background, 'bindings': refs, 'recalls': recalls,
                  'candidate_recalls': candidate_recalls, 'allocation': allocation,
                  'metrics': {'retrieval_calls': retrieval_calls, 'reuse_hits': reuse_hits,
                              'semantic_check': check_status, 'background_characters': len(canonical(background)),
                              'ranker': self.ranker}, 'scientific_approval': False}
        packet['metrics']['visible_primary_chunks'] = len(raw_knowledge['evidence'])
        packet['metrics']['source_reference_count'] = len(raw_knowledge.get('source_references', {}))
        packet['sha256'] = digest(packet)
        self.packet_path.parent.mkdir(parents=True, exist_ok=True)
        with self.packet_path.open('x', encoding='utf-8') as stream:
            stream.write(canonical(packet))
        return {'background': background,
                'bindings': {**refs, 'resolver:packet': file_ref(self.packet_path)}}


def require_supported(background, output_ids):
    """Host gate before executing a dependent operation, not a prompt-only warning."""
    rows = {o['output_id']: o for o in background['outputs']}
    if not output_ids or any(i not in rows or rows[i]['status'] != 'READY_WITHIN_DECLARED_SCOPE' for i in output_ids):
        raise RagError('Requested operation has unresolved context dependencies')

# Runtime revision 1.9: paired semantic deletion guard restores uncertain cards.
