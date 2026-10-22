"""Compression rules 1.26.0 (CC002 revision): redo a reviewed requirements inventory as a patch.

When requirements_review returns REVISE, the requirements stage used to be generated again from nothing with the
review as previous_feedback: on 2026-10-09 the Meropenem review kept 77 of 81 items and flagged 4, and the redo
would have rewritten all 81 (18-40 minutes) with fresh chances of new defects. For runs that opt in, the host
keeps the reviewed inventory and one call returns only the changes: replacement records with their IDs, new
records and removed IDs. Every item the review marked ALTERED or MISSING must be replaced or removed. The host
applies the patch, keeps every other record byte for byte, and the result goes through the usual schema, evidence
and binding checks and a full requirements_review again. The patch is a candidate, never an approval.
"""
import copy
import time
from pathlib import Path

from .io import digest, read_json, write_json
from .schemas import obj, arr, S, enum, validate_schema
from . import candidate_proof, schema_repair
from .rules import host_requirement

MODE = 'RECORD_PATCH'
PROOF = 'requirements_revision_proof.json'
REVIEWED = 'requirements.reviewed.json'
MUST_CHANGE = {'ALTERED', 'MISSING'}


class RevisionPatchError(ValueError):
    code = 'MODEL_REQUIREMENTS_REVISION_INVALID'


def enabled(payload):
    """A requirements request that carries the reviewed inventory it revises."""
    return (host_requirement(payload, 'CC002').get('revision') == MODE and payload.get('stage') == 'requirements'
            and 'reviewed_inventory' in payload and 'revision_patch' not in payload)


def keep_reviewed(run, review, reviewed_response):
    """Engine, when requirements_review does not pass: keep the inventory it reviewed for the patch."""
    write_json(Path(run)/'feedback'/REVIEWED, {'review_sha256': digest(review), 'response': reviewed_response})


def supersede(run, rerun):
    """rerun_from: a rerun of requirements or an earlier stage starts over; it never patches an older inventory."""
    path = Path(run)/'feedback'/REVIEWED
    if path.is_file():
        record = read_json(path)
        if 'superseded_by' not in record:
            write_json(path, {**record, 'superseded_by': rerun})


def attach(run, payload):
    """make_request: give the redo the reviewed inventory, only while it answers the current review."""
    path = Path(run)/'feedback'/REVIEWED
    if 'previous_feedback' not in payload or not path.is_file():
        return
    record = read_json(path)
    if record.get('review_sha256') != digest(payload['previous_feedback']) or 'superseded_by' in record:
        return
    inventory = record['response']['requirements']
    payload['reviewed_inventory'] = inventory
    payload['reviewed_inventory_sha256'] = digest(inventory)
    payload['instructions'] += (
        '\nreviewed_inventory is the inventory that previous_feedback reviewed. Revise it: change, split, merge, '
        'add or remove records only where the review\'s item verdicts, unit verdicts or critical_errors require it, '
        'and keep every other record exactly as it is, with its ID. Every item the review marked ALTERED or MISSING '
        'must be replaced or removed. New records get IDs that reviewed_inventory does not use. Re-extract changed '
        'records from the supplied sources and cite them; the review is feedback, not evidence.')


def must_change(payload):
    inventory = payload['reviewed_inventory']
    ids = {r['id'] for r in inventory['items']} | {q['id'] for q in inventory.get('potential_questions', [])}
    return sorted({i['requirement_id'] for i in payload['previous_feedback'].get('items', [])
                   if i.get('verdict') in MUST_CHANGE and i.get('requirement_id') in ids})


def patch_schema(base_schema):
    fields = base_schema['properties']['requirements']['properties']
    inventory = {'items': {**copy.deepcopy(fields['items']), 'minItems': 0}}
    removals = {'remove_item_ids': arr(S)}
    if 'potential_questions' in fields:
        inventory['potential_questions'] = {**copy.deepcopy(fields['potential_questions']), 'minItems': 0}
        removals['remove_question_ids'] = arr(S)
    return obj(request_sha256=S, requirements=obj(**inventory), **removals,
               changes=arr(obj(id=S, action=enum('REPLACE', 'ADD', 'REMOVE'), finding=S)))


def patch_request(base):
    payload = copy.deepcopy(base['payload'])
    payload['revision_patch'] = {'mode': MODE, 'parent_request_sha256': base['request_sha256'],
                                 'must_change': must_change(base['payload'])}
    payload['schema'] = patch_schema(base['payload']['schema'])
    payload['instructions'] += (
        '\nThis call returns a patch of reviewed_inventory, not the whole inventory. In requirements.items and '
        'requirements.potential_questions return only records you replace (same ID, complete corrected record) or '
        'add (new ID, complete record). List IDs you delete in remove_item_ids and remove_question_ids. Every ID '
        'in revision_patch.must_change must be replaced or removed. Records you do not return stay exactly as they '
        'are, so check that the records you keep still fit what you change (relations, method_refs and '
        'adoption_relations must not point to removed IDs). In changes give one line per changed ID: the action '
        'and the review finding it answers.')
    return {'request_sha256': digest(payload), 'payload': payload}


def apply(base, request, response):
    """The reviewed inventory with the patch applied, as an answer to the base request."""
    validate_schema(response, request['payload']['schema'])
    if response['request_sha256'] != request['request_sha256']:
        raise RevisionPatchError('Stale requirements revision patch')
    reviewed = base['payload']['reviewed_inventory']
    merged = copy.deepcopy(reviewed)
    changed = set()
    for collection, removals in (('items', 'remove_item_ids'), ('potential_questions', 'remove_question_ids')):
        if collection not in reviewed:
            continue
        records = response['requirements'].get(collection, [])
        removed = response.get(removals, [])
        returned = [r['id'] for r in records]
        if len(returned) != len(set(returned)) or len(removed) != len(set(removed)):
            raise RevisionPatchError(f'The patch lists an ID twice in {collection}.')
        position = {r['id']: n for n, r in enumerate(merged[collection])}
        if set(returned) & set(removed):
            raise RevisionPatchError('The patch both returns and removes ' + ', '.join(sorted(set(returned) & set(removed))) + '.')
        unknown = [i for i in removed if i not in position]
        if unknown:
            raise RevisionPatchError('The patch removes IDs the reviewed inventory does not have: ' + ', '.join(unknown) + '.')
        for record in records:
            if record['id'] in position:
                if record == merged[collection][position[record['id']]]:
                    continue  # Returned as it was: not a change.
                merged[collection][position[record['id']]] = copy.deepcopy(record)
            else:
                merged[collection].append(copy.deepcopy(record))
            changed.add(record['id'])
        merged[collection] = [r for r in merged[collection] if r['id'] not in set(removed)]
        changed |= set(removed)
    if not changed:
        raise RevisionPatchError('The review asked for a revision, but the patch changes nothing.')
    ignored = [i for i in request['payload']['revision_patch']['must_change'] if i not in changed]
    if ignored:
        raise RevisionPatchError('The patch leaves items the review found ALTERED or MISSING unchanged: '
                                 + ', '.join(ignored) + '.')
    return {'request_sha256': base['request_sha256'], 'requirements': merged}


def execute(run, base, invocation, generate):
    """generate(request, label) calls the model once. Returns the patched inventory as the stage's answer."""
    run = Path(run); directory = run/'requirements_revision'/invocation; started = time.monotonic()
    request = patch_request(base)
    write_json(directory/'request.json', request)
    try:
        response = generate(request, 'patch')
        write_json(directory/'model_response.json', response)
        repaired = None
        if schema_repair.enabled(request['payload']):
            try:
                repaired = schema_repair.execute(request, response, directory/'schema_repair',
                                                 lambda r: generate(r, 'patch--schema_repair'))
            except Exception as exc:
                exc.model_call = f'audit/model_calls/{invocation}/requirements--patch--schema_repair/call.json'
                raise
            response = repaired or response
        write_json(directory/'response.json', response)
        try:
            merged = apply(base, request, response)
        except RevisionPatchError:
            raise
        except (ValueError, KeyError, TypeError) as exc:
            raise RevisionPatchError(f'requirements revision patch: {exc}') from exc
    except BaseException as exc:
        write_json(directory/'failure.json', {'status': 'FAILED', 'reason': str(exc),
                                              'elapsed_seconds': round(time.monotonic() - started, 3)})
        exc.stage = 'requirements'
        if not getattr(exc, 'model_call', None):
            exc.model_call = f'audit/model_calls/{invocation}/requirements--patch/call.json'
        if not getattr(exc, 'failed_request_sha256', None):  # A format repair names its own request.
            exc.failed_request_sha256 = request['request_sha256']
        raise
    proof = {'mode': MODE, 'parent_request_sha256': base['request_sha256'], 'invocation': invocation,
             'reviewed_inventory_sha256': base['payload']['reviewed_inventory_sha256'],
             'review_sha256': digest(base['payload']['previous_feedback']),
             'request': (directory/'request.json').relative_to(run).as_posix(), 'request_sha256': digest(request),
             'response': (directory/'response.json').relative_to(run).as_posix(), 'response_sha256': digest(response),
             'changed_ids': sorted({r['id'] for c in ('items', 'potential_questions')
                                    for r in response['requirements'].get(c, [])}
                                   | set(response.get('remove_item_ids', [])) | set(response.get('remove_question_ids', []))),
             'merged_sha256': digest(merged), 'accepted_candidate': None,
             'elapsed_seconds': round(time.monotonic() - started, 3),
             'scientific_validity': 'NOT_INDEPENDENTLY_ESTABLISHED'}
    if repaired:
        proof['schema_repair'] = (directory/'schema_repair'/'result.json').relative_to(run).as_posix()
    write_json(run/PROOF, proof)
    return merged


def record_repair(run, merged, repaired, repair_dir):
    candidate_proof.record_repair(run, PROOF, 'Requirements revision', merged, repaired, repair_dir)


def produced_by_patch(run, base, response):
    return candidate_proof.produced(run, PROOF, base, response)


def verify_proof(run, base, response):
    """The response is the reviewed inventory with this request's patch applied, or its recorded binding repair."""
    run = Path(run)
    proof = read_json(run/PROOF)
    if proof.get('mode') != MODE or proof.get('parent_request_sha256') != base['request_sha256']:
        raise ValueError('Requirements revision proof belongs to another request')
    artifact = lambda kind: candidate_proof.artifact(run, proof, kind, 'Requirements revision')
    request = artifact('request')
    if request != patch_request(base):
        raise ValueError('Requirements revision patch request changed')
    merged = apply(base, request, artifact('response'))
    if digest(merged) != proof['merged_sha256']:
        raise ValueError('Requirements revision patch result changed')
    return candidate_proof.accepted(run, proof, response, 'the patched inventory')
