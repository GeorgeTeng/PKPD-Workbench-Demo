"""Compression rules 1.25.0 (CC002 host requirement): the requirements inventory in parts.

One call used to write the whole inventory (100+ items, 18-40 minutes on 2026-10-09). The proposal part runs
first; supporting parts, each owning some attachment questions and their passages, then run at the same time
and may link to the proposal items. The host merges the parts in a fixed order and the merged inventory goes
through the same checks, binding repair and review as a single answer. A part that fails is the only one
called again on retry; validated parts are reused for the exact same request and executor.

From 1.31.0 (requirements_parts PARALLEL) every part starts at once. On 2026-10-09 the supporting parts waited 12 of the
27 minutes of PMB's inventory for the proposal part. Supporting parts no longer see the proposal items; they read the
proposal text, which every part has, and write only supporting facts the proposal does not state. They cannot link to
proposal item IDs, and a fact both sides write stays for the review to flag.
"""
import copy
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .io import digest, read_json, write_json
from .schemas import validate_schema
from .retention import requirements_check
from .bindings import BindingValidationError, without, options as binding_options
from .binding_repair import REPAIRABLE, DROPPABLE
from .unconfirmed import bindings_dropped
from . import candidate_proof, schema_repair
from .rules import host_requirement

MODE = 'PROPOSAL_THEN_SUPPORTING'
PARALLEL = 'PARALLEL'
MODES = (MODE, PARALLEL)
PROPOSAL = 'proposal'
DEFAULT_SUPPORTING_PARTS = 3
PROOF = 'requirements_parts_proof.json'
# Binding issues the single binding repair of the merged inventory may correct (see providers.run_model).
SPLIT_SENTENCE = "otherwise give the needed supporting fact its own item under proposition_contract."


class PartOutputError(ValueError):
    code = 'MODEL_REQUIREMENTS_PART_INVALID'


def part_count(payload):
    return int(host_requirement(payload, 'CC002').get('supporting_parts', DEFAULT_SUPPORTING_PARTS))


def mode(payload):
    return host_requirement(payload, 'CC002').get('requirements_parts')


def enabled(payload):
    """Parts only pay off with supporting passages; a proposal-only inventory stays one call."""
    return (mode(payload) in MODES and payload.get('stage') == 'requirements'
            and bool(supporting_groups(payload, part_count(payload))))


def _patterns(schema, item_pattern, question_pattern, allow_empty):
    inv = schema['properties']['requirements']['properties']
    item = inv['items']['items']['properties']
    item['id'] = {'type': 'string', 'pattern': item_pattern,
                  'description': 'Unique ID with this part\'s prefix (inventory_part.item_id_format).'}
    if allow_empty:
        inv['items'] = {**inv['items'], 'minItems': 0}
    if 'potential_questions' in inv:
        question = inv['potential_questions']['items']['properties']
        question['id'] = {'type': 'string', 'pattern': question_pattern,
                          'description': 'Unique ID with this part\'s prefix (inventory_part.question_id_format).'}


def supporting_groups(payload, count):
    """Attachment questions with supporting passages, in order, split into at most `count` groups of similar
    passage length. Each passage is owned by the first group whose question cites it."""
    sizes = {s['id']: len(s.get('text', '')) for s in payload['sources'] if s.get('role') == 'SUPPORTING_EVIDENCE'}
    heads = {s['id']: s.get('table_header_ids', []) for s in payload['sources'] if s.get('role') == 'SUPPORTING_EVIDENCE'}
    # A question's passages: the ones it cites, then the title and header rows of their tables (rules 1.27.0).
    linked = lambda q: list(dict.fromkeys([i for i in q.get('cited_passage_ids', []) if i in sizes]
                                          + [h for i in q.get('cited_passage_ids', []) for h in heads.get(i, []) if h in sizes]))
    questions = [q for q in payload.get('supporting_questions', []) if linked(q)]
    cited = {i for q in questions for i in linked(q)}
    orphans = [i for i in sizes if i not in cited]
    if not questions and not orphans:
        return []
    weight = lambda q: sum(sizes[i] for i in linked(q)) or 1
    count = max(1, min(count, len(questions) or 1)); total = sum(weight(q) for q in questions)
    groups, current, done = [], [], 0
    for index, q in enumerate(questions):
        current.append(q); done += weight(q)
        needed = count - len(groups) - 1
        if needed and (done >= total * (len(groups) + 1) / count or len(questions) - index - 1 == needed):
            groups.append(current); current = []
    if current or not groups:
        groups.append(current)
    owned, result = set(), []
    for n, group in enumerate(groups):
        passages = [i for q in group for i in linked(q) if i not in owned]
        passages = list(dict.fromkeys(passages)); owned |= set(passages)
        result.append({'letter': chr(ord('A') + n), 'question_ids': [q['question_id'] for q in group],
                       'passage_ids': passages})
    # A supplied passage that no question cites still needs an owner, never silent loss.
    smallest = min(result, key=lambda g: sum(sizes[i] for i in g['passage_ids']))
    smallest['passage_ids'] += orphans
    return result


def proposal_request(base):
    payload = copy.deepcopy(base['payload']); parallel = mode(payload) == PARALLEL
    payload['parent_request_sha256'] = base['request_sha256']
    payload['inventory_part'] = {'part': PROPOSAL, 'item_id_format': 'P01, P02, ...',
                                 'question_id_format': 'PQ01, PQ02, ...'}
    _patterns(payload['schema'], '^P[0-9]{2,3}$', '^PQ[0-9]{2,3}$', allow_empty=False)
    if SPLIT_SENTENCE not in payload['instructions']:
        raise ValueError('Requirements task text changed; update requirements_parts.proposal_request')
    payload['instructions'] = payload['instructions'].replace(SPLIT_SENTENCE,
        'otherwise leave that supporting fact to the supporting parts described in inventory_part.')
    payload['instructions'] += (
        '\nThis inventory is written in parts. You write the proposal part: every item whose subject is a statement '
        'of the proposal (compression_scope.source_ids), and the potential questions it raises. Supporting passages '
        'may be component evidence of a proposal item as described above. Supporting facts that need an item of '
        'their own are written ' + ('at the same time by separate supporting parts' if parallel else
        'afterwards by separate supporting parts, which see your inventory and may link to it') + '; '
        'do not write those items yourself. Number items P01, P02, ... and potential questions PQ01, PQ02, ....')
    return {'request_sha256': digest(payload), 'payload': payload}


def proposal_view(inventory):
    """What a supporting part needs to link to the proposal items and not repeat them."""
    return {'items': [{'id': r['id'], 'kind': r['kind'], 'statement': r['statement'],
                       'role': r['science']['role'], 'evidence_status': r['science']['evidence_status'],
                       'components': [{'id': c['id'], 'role': c['role'], 'text': c['text'],
                                       'unit_ids': sorted({e['unit_id'] for e in c['evidence']})}
                                      for c in r['components']]}
                      for r in inventory['items']],
            'potential_questions': [{'id': q['id'], 'statement': q['statement']}
                                    for q in inventory.get('potential_questions', [])]}


def supporting_request(base, group, groups, proposal_inventory=None):
    """proposal_inventory: the proposal part's items, read-only; None when every part runs at once (PARALLEL)."""
    payload = copy.deepcopy(base['payload'])
    letter = group['letter']
    payload['parent_request_sha256'] = base['request_sha256']
    payload['inventory_part'] = {'part': 'supporting_' + letter, 'parts': len(groups),
        'question_ids': group['question_ids'], 'passage_ids': group['passage_ids'],
        'item_id_format': f'S{letter}01, S{letter}02, ...', 'question_id_format': f'PQ{letter}01, PQ{letter}02, ...'}
    _patterns(payload['schema'], f'^S{letter}[0-9]{{2,3}}$', f'^PQ{letter}[0-9]{{2,3}}$', allow_empty=True)
    numbering = (f'Number items S{letter}01, S{letter}02, ... and any potential questions PQ{letter}01, ....')
    if proposal_inventory is None:
        payload['instructions'] += (
            f'\nThis inventory is written in parts, all at the same time. A proposal part writes every item whose subject '
            f'is a statement of the proposal (compression_scope.source_ids). You write supporting part {letter} of '
            f'{len(groups)}, which owns the attachment questions in inventory_part.question_ids and the supporting '
            'passages in inventory_part.passage_ids; other supporting parts own the other questions and passages. Write '
            'an item only for a supporting fact that your questions or the proposal\'s gaps need and that the proposal '
            'text does not state, with consequential values, conditions, conflicts and restrictions, under '
            'proposition_contract. Cite your passages; other supplied sources may add evidence. method_refs, relations '
            'and adoption_relations name only your own items. Do not restate proposal statements, and do not describe '
            'supporting tables block by block. Return an empty items list when nothing is needed. ' + numbering)
        return {'request_sha256': digest(payload), 'payload': payload}
    payload['proposal_inventory'] = proposal_view(proposal_inventory)
    payload['instructions'] += (
        f'\nThis inventory is written in parts. The proposal part is done: proposal_inventory lists its items, '
        f'read-only. You write supporting part {letter} of {len(groups)}, which owns the attachment questions in '
        'inventory_part.question_ids and the supporting passages in inventory_part.passage_ids. Other supporting '
        'parts own the other questions and passages at the same time. Write an item only for a supporting fact '
        'that your questions or the proposal\'s gaps need and that proposal_inventory does not already carry, '
        'with consequential values, conditions, conflicts and restrictions, under proposition_contract. Cite your '
        'passages; other supplied sources may add evidence. method_refs, relations and adoption_relations may name '
        'proposal_inventory items or your own items. Do not repeat or restate proposal items, and do not describe '
        'supporting tables block by block. Return an empty items list when nothing is needed. ' + numbering)
    return {'request_sha256': digest(payload), 'payload': payload}


def merge(base, proposal, supporting):
    """One inventory in a fixed order: proposal items, then supporting parts A, B, ..."""
    parts = [proposal] + supporting
    inventory = {'version': proposal['requirements']['version'],
                 'items': [r for p in parts for r in p['requirements']['items']],
                 'potential_questions': [q for p in parts for q in p['requirements'].get('potential_questions', [])]}
    if 'potential_questions' not in proposal['requirements']:
        inventory.pop('potential_questions')
    return {'request_sha256': base['request_sha256'], 'requirements': inventory}


def check_part(request, response, units, proposal=None):
    """Schema, IDs and every check of the merged inventory except issues the one binding repair may fix."""
    validate_schema(response, request['payload']['schema'])
    if response['request_sha256'] != request['request_sha256']:
        raise ValueError('Stale requirements part response')
    inventory = response['requirements']
    if proposal is not None:
        inventory = {**inventory, 'items': proposal['items'] + inventory['items'],
                     'potential_questions': proposal.get('potential_questions', []) + inventory.get('potential_questions', [])}
    options = binding_options(request['payload'])
    try:
        requirements_check(inventory, units, options)
    except BindingValidationError as error:
        issues = error.validation_details['issues']
        # 1.29.0: a binding with an invalid component selection is dropped after the merge instead of failing the part.
        if any(i['reason'] not in REPAIRABLE | (DROPPABLE if bindings_dropped(request['payload']) else set()) for i in issues):
            raise
        requirements_check(without(inventory, issues), units, options)


def _identity(executor_id):
    from .split_review import _validator_fingerprint
    return {'id': executor_id, 'validator_sha256': _validator_fingerprint()} if executor_id else None


def _reusable(run, request, identity):
    if not identity:
        return None
    key = digest({'request': request, 'executor': identity}); index = run/'requirements_parts_cache'/(key + '.json')
    if not index.is_file():
        return None
    record = read_json(index)
    path = (run/record['response']).resolve()
    if record.get('key') != key or not path.is_relative_to(run.resolve()):
        raise ValueError('Reusable requirements part does not match its request; inspect the audit before retrying')
    response = read_json(path)
    if digest(response) != record['response_sha256']:
        raise ValueError('Reusable requirements part changed; inspect the audit before retrying')
    return response, {'from': record['response'], 'key': key}


def workers(calls):
    """CTXCOMP_REQUIREMENTS_WORKERS caps concurrent supporting parts; default all at once."""
    value = os.getenv('CTXCOMP_REQUIREMENTS_WORKERS', '').strip()
    if not value: return max(1, calls)
    if not value.isdigit() or int(value) < 1:
        raise ValueError('CTXCOMP_REQUIREMENTS_WORKERS must be a whole number of at least 1')
    return min(int(value), max(1, calls))


def execute(run, base, invocation, generate, executor_id=None, reuse=True):
    """generate(request, label, cancel) calls the model once. Returns the merged response.
    reuse=False (a person asked to run the stage again) calls every part afresh."""
    run = Path(run); directory = run/'requirements_parts'/invocation
    units = base['payload']['source_units']; identity = _identity(executor_id)
    cancel = threading.Event(); records = {}; started = time.monotonic()

    def worker(label, request, proposal=None):
        req_path = directory/(label + '.request.json'); write_json(req_path, request)
        before = time.monotonic()
        try:
            reused = _reusable(run, request, identity) if reuse else None
            response = reused[0] if reused else generate(request, label, cancel)
            repaired = None
            if not reused and schema_repair.enabled(request['payload']):
                # Compression rules 1.25.0: a few malformed records are repaired by one small call.
                write_json(directory/(label + '.model_response.json'), response)
                try:
                    repaired = schema_repair.execute(request, response, directory/(label + '--schema_repair'),
                        lambda r: generate(r, label + '--schema_repair', cancel))
                except Exception as exc:
                    exc.model_call = f'audit/model_calls/{invocation}/requirements--{label}--schema_repair/call.json'
                    raise
                response = repaired or response
            response_path = directory/(label + '.response.json'); write_json(response_path, response)
            try:
                check_part(request, response, units, proposal)
            except BindingValidationError:
                raise
            except (ValueError, KeyError, TypeError) as exc:
                raise PartOutputError(f'requirements part {label}: {exc}') from exc
            record = {'request': req_path.relative_to(run).as_posix(), 'request_sha256': digest(request),
                      'response': response_path.relative_to(run).as_posix(), 'response_sha256': digest(response),
                      'elapsed_seconds': round(time.monotonic() - before, 3), 'status': 'VALIDATED',
                      'execution': 'REUSED' if reused else 'GENERATED'}
            if repaired:
                record['schema_repair'] = (directory/(label + '--schema_repair')/'result.json').relative_to(run).as_posix()
            if reused:
                record['reused_from'] = reused[1]
            elif identity:
                key = digest({'request': request, 'executor': identity})
                write_json(run/'requirements_parts_cache'/(key + '.json'), {'key': key, 'executor': identity,
                    'response': record['response'], 'response_sha256': record['response_sha256']})
            write_json(directory/(label + '.receipt.json'), record)
            return response, record
        except BaseException as exc:
            write_json(directory/(label + '.failure.json'), {'status': 'FAILED', 'reason': str(exc),
                'elapsed_seconds': round(time.monotonic() - before, 3)})
            exc.stage = 'requirements'
            if not getattr(exc, 'model_call', None):
                exc.model_call = f'audit/model_calls/{invocation}/requirements--{label}/call.json'
            if not getattr(exc, 'failed_request_sha256', None):  # A format repair names its own request.
                exc.failed_request_sha256 = request['request_sha256']
            raise

    parallel = mode(base['payload']) == PARALLEL
    groups = supporting_groups(base['payload'], part_count(base['payload']))
    responses, errors = {}, {}
    if parallel:
        requests = {PROPOSAL: proposal_request(base),
                    **{'supporting_' + g['letter']: supporting_request(base, g, groups) for g in groups}}
        context = None
    else:
        responses[PROPOSAL], records[PROPOSAL] = worker(PROPOSAL, proposal_request(base))
        context = responses[PROPOSAL]['requirements']
        requests = {'supporting_' + g['letter']: supporting_request(base, g, groups, context) for g in groups}
    if requests:
        # PARALLEL: the proposal part counts as one more worker, so all parts start together by default.
        with ThreadPoolExecutor(max_workers=workers(len(requests)), thread_name_prefix='requirements-part') as pool:
            futures = {pool.submit(worker, label, request, None if label == PROPOSAL else context): label
                       for label, request in requests.items()}
            try:
                for future in as_completed(futures):
                    label = futures[future]
                    # A failed part does not stop its siblings; their validated answers are kept for the retry.
                    try: responses[label], records[label] = future.result()
                    except Exception as exc: errors[label] = exc
            except BaseException:
                cancel.set()
                for future in futures: future.cancel()
                raise
    if errors:
        raise next(errors[label] for label in requests if label in errors)
    merged = merge(base, responses[PROPOSAL], [responses['supporting_' + g['letter']] for g in groups])
    write_json(run/PROOF, {'mode': mode(base['payload']), 'parent_request_sha256': base['request_sha256'], 'invocation': invocation,
        'groups': groups, 'parts': records, 'merged_sha256': digest(merged), 'accepted_candidate': None,
        'elapsed_seconds': round(time.monotonic() - started, 3), 'scientific_validity': 'NOT_INDEPENDENTLY_ESTABLISHED'})
    return merged


def record_repair(run, merged, repaired, repair_dir):
    candidate_proof.record_repair(run, PROOF, 'Requirements parts', merged, repaired, repair_dir)


def produced_by_parts(run, base, response):
    return candidate_proof.produced(run, PROOF, base, response)


def verify_proof(run, base, response):
    """The response is the merge of validated parts built from this request, or its recorded binding repair."""
    run = Path(run)
    if not (run/PROOF).is_file():
        raise ValueError('Requirements parts proof is missing')
    proof = read_json(run/PROOF)
    if proof.get('mode') != mode(base['payload']) or proof.get('parent_request_sha256') != base['request_sha256']:
        raise ValueError('Requirements parts proof belongs to another request')
    artifact = lambda record, kind: candidate_proof.artifact(run, record, kind, 'Requirements part')
    first = proof['parts'][PROPOSAL]
    if artifact(first, 'request') != proposal_request(base):
        raise ValueError('Requirements proposal part request changed')
    proposal = artifact(first, 'response')
    groups = supporting_groups(base['payload'], part_count(base['payload']))
    if groups != proof['groups']:
        raise ValueError('Requirements supporting parts changed')
    labels = ['supporting_' + g['letter'] for g in groups]
    if set(proof['parts']) != {PROPOSAL, *labels}:
        raise ValueError('Requirements parts proof does not list every part')
    supporting = []
    for group, label in zip(groups, labels):
        record = proof['parts'][label]
        context = None if proof['mode'] == PARALLEL else proposal['requirements']
        if artifact(record, 'request') != supporting_request(base, group, groups, context):
            raise ValueError(f'Requirements part {label} request changed')
        supporting.append(artifact(record, 'response'))
    merged = merge(base, proposal, supporting)
    if digest(merged) != proof['merged_sha256']:
        raise ValueError('Requirements parts merge changed')
    return candidate_proof.accepted(run, proof, response, 'the merged parts')
