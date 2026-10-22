"""Compression rules 1.31.0 (CC002 review_parts): the requirements review in parts that run at the same time.

On 2026-10-09 PMB's requirements review was one 11-minute call judging 179 inventory IDs and every proposal unit,
and it runs again after an automatic revision. Each part now judges a contiguous run of proposal units and the
items and potential questions whose evidence first cites them (items citing only supporting passages are spread
evenly), while reading the whole inventory and every source as context. The host merges the parts into one review
in the usual order, and the merged review goes through every check of a single review. A record a part gives for an
ID another part owns is kept in limitations; one reporting a defect turns a PASS into REVISE."""
import copy
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import threading

from .io import digest, write_json
from .rules import host_requirement
from .schemas import validate_schema

AUDIT = 'audit/requirements_review_parts'


def count(payload):
    return int(host_requirement(payload, 'CC002').get('review_parts') or 1)


def enabled(payload):
    return payload.get('stage') == 'requirements_review' and count(payload) > 1 and len(plan(payload)) > 1


def _unit_ids(payload):
    return list(payload.get('review_source_unit_ids') or [u['id'] for u in payload['source_units']])


def plan(payload):
    """[{'part': n, 'unit_ids': [...], 'item_ids': [...]}]: contiguous units of similar length, each with at least one ID."""
    units = _unit_ids(payload); size = {u['id']: len(u['text']) for u in payload['source_units']}
    n = max(1, min(count(payload), len(units)))
    total = sum(size[u] for u in units) or 1
    chunks, current, done = [], [], 0
    for index, unit in enumerate(units):
        current.append(unit); done += size[unit]
        left = n - len(chunks) - 1
        if left and (done >= total * (len(chunks) + 1) / n or len(units) - index - 1 == left):
            chunks.append(current); current = []
    if current or not chunks:
        chunks.append(current)
    owner = {u: k for k, chunk in enumerate(chunks) for u in chunk}
    requirements = payload['requirements']
    cited = [(r['id'], [e['unit_id'] for c in r['components'] for e in c['evidence']]) for r in requirements['items']]
    cited += [(q['id'], [s['unit_id'] for s in q.get('source_refs', [])]) for q in requirements.get('potential_questions', [])]
    items = [[] for _ in chunks]; spread = []
    for rid, refs in cited:
        first = next((owner[u] for u in refs if u in owner), None)
        (spread.append(rid) if first is None else items[first].append(rid))
    for rid in spread:
        min(items, key=len).append(rid)
    parts = [{'unit_ids': c, 'item_ids': i} for c, i in zip(chunks, items)]
    # A part with no ID to judge joins its neighbour; the review schema needs at least one record of each kind.
    while len(parts) > 1 and any(not p['item_ids'] for p in parts):
        k = next(k for k, p in enumerate(parts) if not p['item_ids']); j = k - 1 if k else 1
        parts[j] = {key: parts[min(j, k)][key] + parts[max(j, k)][key] for key in ('unit_ids', 'item_ids')}
        del parts[k]
    order = {rid: n for n, (rid, _) in enumerate(cited)}
    return [{'part': k + 1, 'unit_ids': p['unit_ids'], 'item_ids': sorted(p['item_ids'], key=order.get)}
            for k, p in enumerate(parts)]


def part_request(base, part, parts):
    payload = copy.deepcopy(base['payload'])
    from .review_records import INSTRUCTION
    payload['instructions'] = payload['instructions'].replace(INSTRUCTION, '')
    payload['parent_request_sha256'] = base['request_sha256']
    payload['review_part'] = {'part': part['part'], 'parts': len(parts), 'item_ids': part['item_ids']}
    if 'review_source_unit_ids' in payload:
        payload['review_source_unit_ids'] = part['unit_ids']
    if 'review_source_unit_links' in payload:
        payload['review_source_unit_links'] = {u: payload['review_source_unit_links'][u] for u in part['unit_ids']}
    payload['instructions'] += (
        f'\nThis review runs in {len(parts)} parts at the same time. You write part {part["part"]}: give review.items '
        'one record for each ID in review_part.item_ids and no others, and review.source_units one record for each unit '
        'in review_source_unit_ids. The rest of the inventory and every source are context, for example to see whether '
        'a unit\'s content is carried by an item another part judges or whether two items repeat each other; other parts '
        'judge those IDs. decision, critical_errors and limitations cover your part only.')
    return {'request_sha256': digest(payload), 'payload': payload}


def merge(base, parts, responses):
    """One review in inventory and unit order. A part's record for another part's ID goes to limitations."""
    from .scientific import item_ids
    payload = base['payload']; reviews = [r['review'] for r in responses]
    order = {rid: n for n, rid in enumerate(item_ids(payload['requirements']))}
    units = {u: n for n, u in enumerate(_unit_ids(payload))}
    items, unit_records, limitations, errors, outside = [], [], [], [], False
    for part, review in zip(parts, reviews):
        own_items, own_units = set(part['item_ids']), set(part['unit_ids'])
        for rec in review['items']:
            if rec['requirement_id'] in own_items or rec['requirement_id'] not in order:
                items.append(rec)  # IDs outside the inventory are left to review_records and the checks.
            else:
                outside |= rec['verdict'] != 'PRESERVED'
                limitations.append(f'Part {part["part"]} also judged {rec["requirement_id"]} ({rec["verdict"]}), which '
                                   f'another part reviews: {rec["reason"]}')
        for rec in review['source_units']:
            if rec['unit_id'] in own_units or rec['unit_id'] not in units:
                unit_records.append(rec)
            else:
                outside |= rec['verdict'] != 'PRESERVED'
                limitations.append(f'Part {part["part"]} also judged unit {rec["unit_id"]} ({rec["verdict"]}), which '
                                   f'another part reviews: {rec["reason"]}')
        limitations += [f'Part {part["part"]}: {text}' for text in review['limitations']]
        errors += review['critical_errors']
    decisions = [r['decision'] for r in reviews]
    decision = ('NEEDS_REVIEW' if 'NEEDS_REVIEW' in decisions else 'REVISE' if 'REVISE' in decisions or outside
                else 'PASS')
    last = len(order) + len(units)
    review = {'decision': decision,
              'reviewer': f'Requirements review in {len(parts)} parts: ' + ' | '.join(r['reviewer'] for r in reviews),
              'review_type': reviews[0]['review_type'],
              'items': sorted(items, key=lambda r: order.get(r['requirement_id'], last)),
              'source_units': sorted(unit_records, key=lambda r: units.get(r['unit_id'], last)),
              'critical_errors': errors, 'limitations': limitations}
    return {'request_sha256': base['request_sha256'], 'review': review}


def execute(run, base, invocation, generate):
    """generate(request, label, cancel) calls the model once. Returns the merged review response."""
    run = Path(run); directory = run/AUDIT/invocation; parts = plan(base['payload'])
    cancel = threading.Event(); started = time.monotonic(); records = {}

    def worker(part):
        label = f'part_{part["part"]}'; request = part_request(base, part, parts)
        write_json(directory/(label + '.request.json'), request); before = time.monotonic()
        try:
            response = generate(request, label, cancel)
            write_json(directory/(label + '.response.json'), response)
            validate_schema(response, request['payload']['schema'])
            if response['request_sha256'] != request['request_sha256']:
                raise ValueError(f'Stale requirements review part {label} response')
        except BaseException as exc:
            exc.stage = 'requirements_review'
            exc.model_call = getattr(exc, 'model_call', None) or \
                f'audit/model_calls/{invocation}/requirements_review--{label}/call.json'
            exc.failed_request_sha256 = request['request_sha256']
            raise
        records[label] = {'request_sha256': request['request_sha256'], 'response_sha256': digest(response),
                          'item_ids': len(part['item_ids']), 'unit_ids': len(part['unit_ids']),
                          'elapsed_seconds': round(time.monotonic() - before, 3)}
        return response

    with ThreadPoolExecutor(max_workers=len(parts), thread_name_prefix='requirements-review-part') as pool:
        futures = {pool.submit(worker, part): n for n, part in enumerate(parts)}
        responses = [None] * len(parts)
        try:
            for future in as_completed(futures):
                responses[futures[future]] = future.result()
        except BaseException:
            cancel.set()
            for future in futures: future.cancel()
            raise
    merged = merge(base, parts, responses)
    write_json(directory/'merge.json', {'parent_request_sha256': base['request_sha256'], 'parts': records,
        'merged_sha256': digest(merged), 'elapsed_seconds': round(time.monotonic() - started, 3)})
    return merged
