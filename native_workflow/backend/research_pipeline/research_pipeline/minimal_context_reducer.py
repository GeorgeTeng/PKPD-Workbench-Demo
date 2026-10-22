"""Pure stage-profile semantic reducer; standard library only, no I/O or calls.

Production can import reduce_payload(payload, route, policy). Full host request
is retained by its caller; the reducer returns the minimal model payload and an
explicit host-only/factoring audit. expand_payload reconstructs semantic payload.
"""
import copy
from collections import Counter
import hashlib
import json

class RagError(ValueError):
    pass

def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)

def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()

VERSION = 'WORKFLOW_CONTEXT_CONTRACT_1.6'
MARKERS = {'record_table', 'record_set', 'shared_text_ref', 'missing_record_field'}
# Keep row identity and time coordinates explicit for scientific review. Exact
# decoding alone does not ensure a reviewer correctly reads modal defaults.
IDENTITY = {'id', 'item_id', 'source_id', 'source_ids', 'source', 'evidence_chunk_ids',
            'record_id', 'observation_id', 'source_row', 'source_cell',
            'canonical_time_h', 'time_h', 'times'}
INSTRUCTION = (
    'Task-specific input contract WORKFLOW_CONTEXT_CONTRACT_1.6. A record_set contains records in original '
    'order and defaults: recursively inherit absent fields; each record is independently scoped. '
    'A record_table has named columns '
    'and rows in original order. Map each row cell to its column name; then recursively inherit '
    'absent fields from defaults. Explicit values (including null, empty lists and strings) override '
    'defaults. A missing_record_field cell means absent, not null. Resolve shared_text_ref from '
    'shared_text in this input verbatim, at every occurrence; references are internal encoding labels, '
    'never output evidence IDs. Keep every provided original rule, profile, source and experimental-unit '
    'ID and association; host-only data-inventory IDs are not response citations. Rules retain operative text, applicability, conditions and exceptions. '
    'NOT_FOUND/NOT_SPECIFIED and unresolved missing_information remain unknown. Output the unchanged '
    'response schema with original authorized IDs; return only fields permitted by that schema. '
    'Study descriptions, including later human validation plans, are context, not observed data. '
    'Optional retrieved sources remain unapproved background; they cannot add approved profiles or rules.'
)

def _reserved(value):
    if isinstance(value, dict):
        if MARKERS & value.keys():
            raise RagError('Reserved input-contract marker in original input')
        for child in value.values(): _reserved(child)
    elif isinstance(value, list):
        for child in value: _reserved(child)

def _common_defaults(rows):
    """Exact modal values only, never infer missing fields or semantic equivalence."""
    defaults = {}
    for key in sorted(set.intersection(*(set(row) for row in rows)) - IDENTITY):
        values = [row[key] for row in rows]
        if all(isinstance(v, dict) for v in values):
            common = _common_defaults(values)
            if common:
                defaults[key] = common
                for value in values:
                    _subtract(value, common)
            continue
        counts = Counter(canonical(v) for v in values)
        encoded, count = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[0]
        if count >= 3 and (count-1)*(len(key)+len(encoded)+4) > 90:
            defaults[key] = json.loads(encoded)
            for row in rows:
                if canonical(row[key]) == encoded: del row[key]
    return defaults

def _subtract(row, defaults):
    for key, value in defaults.items():
        if key in row:
            if isinstance(value, dict) and isinstance(row[key], dict):
                _subtract(row[key], value)
                if not row[key]: del row[key]
            elif canonical(row[key]) == canonical(value): del row[key]

def _encode(value, path, ledger):
    if isinstance(value, dict):
        return {key: _encode(child, path + '/' + key, ledger) for key, child in value.items()}
    if not isinstance(value, list): return value
    if len(value) >= 3 and all(isinstance(row, dict) for row in value):
        # JSON has value semantics. deepcopy preserves shared Python references,
        # so factoring one row can otherwise delete fields from another row (or
        # from a second reference in the same row). Detach every occurrence.
        rows = json.loads(canonical(value))
        defaults = _common_defaults(rows)
        columns = sorted(set.union(*(set(row) for row in rows)))
        table_ledger, set_ledger = [], []
        cells = [[_encode(row[key], path + '/' + key, table_ledger) if key in row
                  else {'missing_record_field': True} for key in columns] for row in rows]
        table = {'record_table': {'columns': columns, 'defaults': _encode(defaults, path + '/defaults', table_ledger), 'rows': cells}}
        record_set = {'record_set': {'defaults': _encode(defaults, path + '/defaults', set_ledger),
                                   'records': [{key:_encode(child,path+'/'+key,set_ledger) for key,child in row.items()} for row in rows]}}
        # All workflow steps use the same transparent representation choice.
        # Named columns are worthwhile for dense rows, keyed records for sparse
        # rows. Choose exact serialization only; never select scientific content.
        if len(canonical(record_set)) < len(canonical(table)):
            table, chosen_ledger = record_set, set_ledger
        else:
            chosen_ledger = table_ledger
        if len(canonical(table)) < len(canonical(value)):
            ledger.extend(chosen_ledger)
            ledger.append({'path': path, 'classification': 'EXACT_RECORD_TABLE_AND_SHARED_DEFAULTS', 'records': len(rows), 'columns': columns})
            return table
    return [_encode(child, path + '/' + str(i), ledger) for i, child in enumerate(value)]

def _merge(row, defaults):
    for key, value in defaults.items():
        if key not in row: row[key] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(row[key], dict): _merge(row[key], value)

def _decode(value, shared):
    if isinstance(value, list): return [_decode(v, shared) for v in value]
    if not isinstance(value, dict): return value
    if set(value) == {'shared_text_ref'}:
        if value['shared_text_ref'] not in shared: raise RagError('Unresolved shared text')
        return shared[value['shared_text_ref']]
    if set(value) == {'record_table'}:
        table = value['record_table']; columns = table['columns']
        if len(columns) != len(set(columns)): raise RagError('Duplicate record column')
        defaults = _decode(table['defaults'], shared); out = []
        for cells in table['rows']:
            if len(cells) != len(columns): raise RagError('Wrong record cell count')
            row = {key: _decode(cell, shared) for key, cell in zip(columns, cells)
                   if cell != {'missing_record_field': True}}
            _merge(row, defaults); out.append(row)
        return out
    if set(value) == {'record_set'}:
        records = value['record_set']; defaults = _decode(records['defaults'], shared)
        out = [_decode(row, shared) for row in records['records']]
        for row in out: _merge(row, defaults)
        return out
    return {key: _decode(child, shared) for key, child in value.items()}

def expand(wire):
    """Expand all semantic content without consulting host files or audit."""
    out = copy.deepcopy(wire)
    contract = out['payload'].pop('input_contract')
    if contract['version'] != VERSION: raise RagError('Unsupported input contract')
    out['payload'] = _decode(out['payload'], contract['shared_text'])
    return out

def expand_payload(payload):
    return expand({'payload':payload})['payload']


def project_background(packet):
    """Exact readable optional background; shared by reducer and plan budgets."""
    membership={}
    for unit in packet.get('units',[]):
        if unit['kind']=='chunk': membership.setdefault(unit['id'],set()).update(unit.get('question_ids',[]))
        else:
            card=next(card for card in packet['cards'] if card['id']==unit['id'])
            for cid in card['evidence_chunk_ids']: membership.setdefault(cid,set()).update(unit.get('question_ids',[]))
    evidence=[]
    source_labels={sid:'background_source_'+str(i+1) for i,sid in enumerate(packet.get('sources',{}))}
    evidence_labels={chunk['id']:'E'+str(i+1) for i,chunk in enumerate(packet.get('chunks',[]))}
    for chunk in packet.get('chunks',[]):
        meta=packet['sources'][chunk['source_id']]
        attribution={key:meta[key] for key in ('title','document_type','access_level','source_status') if key in meta}
        evidence.append({'evidence_ref':evidence_labels[chunk['id']], 'source_ref':source_labels[chunk['source_id']],
                         'source':attribution,'locator':chunk['locator'],'verbatim_excerpt':chunk['text'],
                         'subquestions':sorted(membership.get(chunk['id'],[]))})
    cards=[{**{key:value for key,value in card.items() if key not in {'id','source_ids','evidence_chunk_ids','origin_job'}},
            'evidence_refs':[evidence_labels[cid] for cid in card['evidence_chunk_ids']],
            'source_refs':[source_labels[sid] for sid in card['source_ids']]} for card in packet.get('cards',[])]
    background={'usage_boundary':packet['usage_boundary'],'status':packet['status'],
        'current_scope':{'stage':packet['scope']['stage'],'topic':packet['scope']['topic']},
        'source_attributed_evidence':evidence,'draft_interpretations':cards,
        'gaps':packet['gaps'],'empty_reason':packet['empty_reason'],'scientific_approval':False}
    if packet.get('subquestion_results'):
        background['question_coverage']=[{'question':r['question_id'],'status':r['status']} for r in packet['subquestion_results']]
        background['subquestion_plan']=[{'id':q['id'],'method_profile_ids':q['method_profile_ids'],
            **({'information_need':q['information_need']} if q.get('information_need') else {'query':q['query']})}
            for q in packet['scope']['retrieval_plan']['subquestions']]
    return background


def reduce_payload(payload, route, policy):
    if (policy.get('version') != 'MINIMAL_TASK_CONTEXT_1.0' or policy.get('implicit_full_payload_fallback') is not False
            or route not in policy.get('routes',{})):
        raise RagError('Unregistered minimum semantic task route: '+str(route))
    profile=policy['routes'][route]['profile']
    if profile not in policy['profiles']: raise RagError('Undefined task profile')
    baseline={'task_route':route,'task_profile':profile,'task_definition':policy['profiles'][profile]}
    source={'payload':copy.deepcopy(payload)}
    _reserved(source)
    if 'input_contract' in source['payload']: raise RagError('Preexisting input contract')
    work = copy.deepcopy(source)
    mechanical = []
    def move(obj, key, path, reason='File/content integrity checked by the host; not a model reasoning input.'):
        if key in obj:
            mechanical.append({'path': path + '/' + key, 'classification': 'HOST_ONLY_EXPLICIT_FIELD', 'reason':reason, 'value': obj.pop(key)})
    p = work['payload']
    # An impact opinion consumes candidate definitions, not their bibliographic
    # acquisition history. Do not project profile inputs/conditions or source
    # evidence out of Coverage, review or EDA contracts.
    local_knowledge=p.get('local_method_knowledge')
    if profile == 'impact_advice' and isinstance(local_knowledge,dict):
        for key in ('sources','source_metadata','library_sha256','general_rules_sha256','lineage'):
            move(local_knowledge,key,'/payload/local_method_knowledge',
                 'Method bibliography and library lineage are host provenance. The impact task consumes exact supplied profile definitions, alternatives, conditions and limits; response profile/source selectors and original required evidence remain visible.')
        for i,method in enumerate(local_knowledge.get('profiles',[])):
            if isinstance(method,dict):
                move(method,'source_ids','/payload/local_method_knowledge/profiles/'+str(i),
                     'Bibliographic method-source IDs are host provenance; preserve the original MP ID and every substantive profile field used for conditional advice.')
    local_context=p.get('local_mp_context')
    if profile == 'impact_advice' and isinstance(local_context,dict):
        for key in ('source_metadata','library_sha256'):
            move(local_context,key,'/payload/local_mp_context',
                 'Host-bound library bibliography/hash; complete METHOD evidence selectors and profile definitions remain supplied independently.')
    # Accepted published Rules are inherited downstream rather than re-derived.
    # A publication ref and explicit projection version identify that handoff;
    # arbitrary rule-like source records never enter this projection.
    if profile in {'impact_advice','source_assessment','preparation','handoff_review'}:
        for i,rule in enumerate(p.get('project_rules',[])):
            if not isinstance(rule,dict): continue
            ref=rule.get('project_rules_ref')
            if (not isinstance(ref,dict) or set(ref)!={'path','sha256'}
                    or not isinstance(rule.get('projection_version'),str) or not rule['projection_version']):
                continue
            for key in ('evidence','authority_evidence','field_evidence','classification_reason',
                        'routing_reason','candidate_ids','projection_version','project_rules_ref'):
                move(rule,key,'/payload/project_rules/'+str(i),
                     'Host-verified published Rule derivation and routing audit, not a new review assignment. All operative text, applicability, conditions, exceptions, requirement, usage, stages and context_path remain. Source/candidate review evidence in other sections is never removed.')
    original_stage = p.get('stage')
    is_dr = original_stage == 'DR' and p.get('operation') in {'REQUIREMENT_PLAN_4.0', 'REQUIREMENT_PLAN_5.0', 'REQUIREMENT_PLAN_5.1', 'REQUIREMENT_PLAN_6.0'}
    # DR4/5 explicitly plan reusable definitions, never per-dataset coverage.
    # Source inventory/notes are host orientation, not adopted obligations. Their
    # complete qualifiers and provenance stay available to later Coverage.
    if is_dr:
        inventory=p.get('data_overviews', [])
        rows=inventory if isinstance(inventory,list) else []
        def vocabulary(field):
            return sorted({row[field] for row in rows if isinstance(row,dict)
                and isinstance(row.get(field),str) and row[field] not in {'NOT_FOUND','NOT_SPECIFIED','NOT_APPLICABLE'}})
        columns=[column for row in rows if isinstance(row,dict) for column in row.get('columns',[])
                 if isinstance(column,dict)]
        orientation={'purpose':'Design vocabulary only; derive reusable requirements from objective, Rules and assigned method inputs.',
            'record_categories':vocabulary('record_category'), 'observation_origins':vocabulary('observation_source'),
            'source_kinds':vocabulary('kind'),
            'field_types':sorted({column['meaning'] for column in columns if isinstance(column.get('meaning'),str)
                                and column['meaning'] not in {'NOT_FOUND','NOT_SPECIFIED'}}),
            'boundary':'These independent vocabulary lists establish no observed values, source joins, matched subjects, requirements, adequacy or availability. Per-source units, sampling descriptions, conflicting qualifiers and all notes remain host-side for Coverage. Group summaries never establish individual trajectories; absent or unknown metadata remains unresolved.'}
        if 'data_overviews' in p:
            mechanical.append({'path':'/payload/data_overviews','classification':'DR4_ORIENTATION_NOT_SOURCE_ASSESSMENT',
                'reason':'Reusable input planning needs design/field vocabulary; full item/column inventory, units and individual-source qualifiers belong to later independent Coverage and cannot create project obligations.',
                'value':p['data_overviews'],'model_replacement':copy.deepcopy(orientation)})
            p['data_overviews']=orientation
        move(p,'overview_notes','/payload',
             'Overview facts are not adopted obligations and DR4 does not assess availability, assignments or matching. Preserve all exact notes and source qualifiers on host for Coverage; project scientific statements, missing information, Rules and method input constraints remain model-visible.')
    # Enumerated locations only. Scientific/source text and unknown fields remain.
    mk = p.get('method_knowledge', {})
    if not isinstance(mk,dict): mk={}
    for key in ('library_sha256', 'general_rules_sha256'): move(mk, key, '/payload/method_knowledge')
    if isinstance(mk.get('lineage'), dict):
        for key in ('file_sha256', 'path'): move(mk['lineage'], key, '/payload/method_knowledge/lineage')
    if is_dr:
        move(mk,'sources','/payload/method_knowledge',
             'Bibliographic URLs, document locators and source support notes are host provenance; DR4 output cites assigned MP IDs, not method-library paper IDs. Candidate authority, draft limits and exact profile input definitions remain visible.')
        move(mk,'lineage','/payload/method_knowledge',
             'Library ancestry is host provenance; it neither defines task inputs nor grants scientific authority.')
    for i, profile in enumerate(mk.get('profiles', []) if is_dr else []):
        if not isinstance(profile,dict): continue
        prefix='/payload/method_knowledge/profiles/'+str(i)
        for key in ('condition_triggers','data_roles'):
            move(profile,key,prefix,
                 'DC-label/role-to-profile dispatch bookkeeping belongs to later independent Coverage; all applies_when, required/conditional inputs, alternatives, data checks and cautions remain.')
        for key in ('outputs','needed_at','assessment_scope'):
            move(profile,key,prefix,
                 'Profile assessment-output bookkeeping describes a later input-assessment record, not a requested project input or its producer phase. DR4 output fields and phase rules are supplied by its task contract; operative definitions remain unchanged.')
        move(profile,'source_ids',prefix,
             'Method-source bibliography references are host provenance; unchanged response schema permits original MP IDs only as method authority.')
    for i, source_meta in enumerate(mk.get('sources', [])):
        if not isinstance(source_meta,dict): continue
        move(source_meta, 'checked_on', '/payload/method_knowledge/sources/'+str(i),
             'Historical reference-check date is host provenance, not renewed scientific approval.')
    for i, rule in enumerate(p.get('project_rules', [])):
        if not isinstance(rule,dict): continue
        provenance=rule.get('provenance',{})
        if isinstance(provenance,dict):
            pointer=provenance.get('main_pointer')
            authorized=set(p.get('direct_project_source_ids',[]))|set(p.get('project_context_source_ids',[]))
            reference='main:'+pointer+'/text' if isinstance(pointer,str) else None
            if reference in authorized and rule.get('project_source_id') != reference:
                rule['output_source_ids']=[reference]
        move(rule, 'provenance', '/payload/project_rules/' + str(i),
             'Rule audit pointer/hash is host-side; original rule ID, operative text, scope, conditions, exceptions, requirement and usage remain model-visible.')
    # Rule locations are declared by the common task contract, not stage names.
    # Source-review profiles never remove assigned source/candidate evidence.
    orchestration = policy.get('task_orchestration', {})
    collections = orchestration.get('rule_collections', {})
    if profile in collections.get('consumer_profiles', []):
        for path in policy['routes'][route].get('rule_paths', []):
            if path == ['project_rules']:
                continue  # The existing published-rule guard above owns this path.
            node = p
            for part in path:
                node = node.get(part) if isinstance(node, dict) else None
            if not isinstance(node, list):
                continue
            for i, rule in enumerate(node):
                if not isinstance(rule, dict):
                    continue
                prefix = '/payload/' + '/'.join(path) + '/' + str(i)
                for key in orchestration.get('published_rule_audit_fields', []):
                    move(rule, key, prefix,
                         'Admitted Rule derivation audit stays on host. Every operative clause, condition, exception, scope and unrecognized scientific field remains visible unchanged.')
    if is_dr:
        context=p.get('project_context',{})
        items=context.get('scientific_context',{}).get('items',[]) if isinstance(context,dict) else []
        authorized=set(p.get('direct_project_source_ids',[]))|set(p.get('project_context_source_ids',[]))
        for i,item in enumerate(items):
            reference='main:/scientific_context/items/'+str(i)+'/statement'
            if isinstance(item,dict) and reference in authorized: item['output_source_id']=reference
    if is_dr:
        context=p.get('project_context',{})
        authorized=set(p.get('direct_project_source_ids',[]))|set(p.get('project_context_source_ids',[]))
        mapped=set()
        for rule in p.get('project_rules',[]):
            if isinstance(rule,dict):
                mapped.update(rule.get('output_source_ids',[]))
                if rule.get('project_source_id') in authorized:
                    mapped.add(rule['project_source_id'])
        items=context.get('scientific_context',{}).get('items',[]) if isinstance(context,dict) else []
        for item in items:
            if isinstance(item,dict) and 'output_source_id' in item: mapped.add(item['output_source_id'])
        if isinstance(context,dict) and 'main:/objective' in authorized:
            context['objective_source_id']='main:/objective';mapped.add('main:/objective')
        unmapped=sorted(authorized-mapped)
        if unmapped:
            p['unmapped_authorized_source_refs']={key:('PROJECT_EXPLICIT_AND_METHOD_CANDIDATE' if key in p.get('direct_project_source_ids',[]) else 'METHOD_CANDIDATE_ONLY') for key in unmapped}
        for key in ('direct_project_source_ids','project_context_source_ids'):
            move(p,key,'/payload',
                 'Authorized source IDs are already given once at their rule/statement/Objective meaning, with any unmapped references explicit; the unchanged response schema retains exact authority-specific enums. No ID inference or source renumbering is needed.')
    bg = p.get('optional_rag_background_v1', {})
    if isinstance(bg, dict) and isinstance(bg.get('packet'), dict):
        packet = bg['packet']
        background=project_background(packet)
        mechanical.append({'path':'/payload/optional_rag_background_v1','classification':'SOURCE_ATTRIBUTED_OPTIONAL_EVIDENCE',
            'reason':'All exact excerpt text, locator, source title/status and draft claim content remain; internal library/card/chunk IDs, filesystem paths and integrity hashes are host replay provenance, not authorized response citation IDs.',
            'value':copy.deepcopy(bg),'model_replacement':copy.deepcopy(background)})
        p['optional_rag_background_v1']=background
    expected = copy.deepcopy(work)
    ledger = []
    # EDA review already receives source tables in a verified columnar encoding.
    # Do not encode the same evidence a second time or hide analysis/task IDs
    # behind modal defaults. Exact expansion is insufficient for model readability.
    readable = {'schema'}
    if p.get('stage') in {'EI-findings', 'ER-review'}:
        readable.update({'task_context', 'data_handoff', 'eda_plan', 'calculation_bundle',
                         'figure_bundle', 'eda_findings'})
    work['payload'] = {key: child if key in readable else _encode(child, '/payload/' + key, ledger) for key, child in p.items()}
    counts = Counter(); paths = {}
    def collect(v, path):
        if isinstance(v, str) and len(v) >= 120: counts[v] += 1; paths.setdefault(v, path)
        elif isinstance(v, list):
            for child in v: collect(child, path)
        elif isinstance(v, dict):
            for key, child in v.items(): collect(child, path + '.' + key)
    for key, child in work['payload'].items():
        if key not in readable: collect(child, key)
    candidates=sorted((value for value,count in counts.items() if count>=2),key=lambda value:(paths[value],value))
    names={};repeated=[]
    for value in candidates:
        parts=paths[value].split('.')
        section=parts[0] if parts[-1]==parts[0] else parts[0]+'.'+parts[-1]
        name=section+'.text.'+str(len(repeated)+1)
        # The complete dictionary definition plus every occurrence reference
        # must save characters. No meaning/similarity or source scope is merged.
        reference={'shared_text_ref':name}
        before=counts[value]*len(canonical(value))
        after=counts[value]*len(canonical(reference))+len(canonical({name:value}))+1
        if before-after>=80:
            repeated.append(value);names[value]=name
    def factor(v):
        if isinstance(v, str) and v in names: return {'shared_text_ref': names[v]}
        if isinstance(v,list): return [factor(child) for child in v]
        if isinstance(v,dict): return {key:factor(child) for key,child in v.items()}
        return v
    work['payload'] = {key: child if key in readable else factor(child) for key,child in work['payload'].items()}
    work['payload']['input_contract'] = {'version':VERSION, 'decode_instructions':INSTRUCTION,
                                         'task_route':baseline['task_route'], 'task_profile':baseline['task_profile'],
                                         'task_purpose':baseline['task_definition']['purpose'],
                                         'evidence_boundary':baseline['task_definition']['evidence_boundary'],
                                         'shared_text': {names[v]:v for v in repeated}}
    expanded=expand(work)
    if expanded != expected: raise RagError('Lossless semantic expansion failed')
    if canonical(source['payload'].get('schema'))!=canonical(expanded['payload'].get('schema')):
        raise RagError('Task projection changed response schema or authority-specific reference enums')
    operative=('id','kind','text','conditions','exceptions','scope','requirement','usage')
    rule_comparison=[]
    if len(source['payload'].get('project_rules',[]))!=len(expanded['payload'].get('project_rules',[])):
        raise RagError('Task projection changed project rule inventory')
    for before,after in zip(source['payload'].get('project_rules',[]),expanded['payload'].get('project_rules',[])):
        if isinstance(before,dict) and isinstance(after,dict):
            original={key:before[key] for key in operative if key in before}
            visible={key:after[key] for key in operative if key in after}
        else: original=before;visible=after
        if canonical(original)!=canonical(visible): raise RagError('Operative rule fields changed in task projection')
        rule_comparison.append({'id':before.get('id') if isinstance(before,dict) else None,
                                'operative_sha256':digest(original),'exact':True})
    # The same inventory/operative comparison applies to declared nested paths.
    for path in policy['routes'][route].get('rule_paths', []):
        if path == ['project_rules']:
            continue
        before, after = source['payload'], expanded['payload']
        for part in path:
            before = before.get(part) if isinstance(before, dict) else None
            after = after.get(part) if isinstance(after, dict) else None
        if before is None and after is None:
            continue
        if not isinstance(before, list) or not isinstance(after, list) or len(before) != len(after):
            raise RagError('Nested project rule inventory changed')
        for left, right in zip(before, after):
            if not isinstance(left, dict) or not isinstance(right, dict):
                raise RagError('Invalid nested project rule')
            original = {key:left[key] for key in operative if key in left}
            visible = {key:right[key] for key in operative if key in right}
            if canonical(original) != canonical(visible):
                raise RagError('Nested operative rule fields changed')
            rule_comparison.append({'id':left.get('id'), 'path':'/'.join(path),
                                    'operative_sha256':digest(original),'exact':True})
    return work['payload'], {'version':VERSION, 
        'model_input_sha256':digest(work), 'semantic_expansion_sha256':digest(expected),
        'semantic_expansion_exact':True, 'baseline_characters':len(canonical(source)),
        'operative_rule_comparison':rule_comparison, 'operative_rule_fields':list(operative),
        'model_characters':len(canonical(work)), 'mechanical_field_ledger':mechanical,
        'factoring_ledger':ledger, 'shared_text_count':len(repeated), 
        'task_route':baseline['task_route'], 'task_profile':baseline['task_profile'],
        'readable_sections_without_reencoding': sorted(readable - {'schema'}),
        'section_purposes':{key:('Unchanged response contract and authorized output references.' if key=='schema' else
            'All operative rules, conditions, exceptions and scientific constraints.' if key in {'project_rules','rules','processing_rules','governance'} else
            'Independent design/field vocabulary only; no source inventory, numerical facts or coverage.' if is_dr and key=='data_overviews' else
            'Complete task input retained pending explicit stage-specific exclusion; exact factoring only.') for key in expected['payload']},
        'route_specialization':'DR4 reusable definitions; source inventory and assessment bookkeeping retained only on host' if is_dr else 'Registered stage purpose and evidence boundary; exact semantic factoring, no evidence pruning.',
        'model_calls':0, 'scientific_approval':False}
