"""Bound formal results -> task views. No summarization, retrieval or model calls.

Selection is by assigned record identity. Each selected record is indivisible;
its ancestors' non-collection fields, declared dependencies and touching
relations travel with it. Unknown layouts remain whole local objects.
"""
from __future__ import annotations

import copy
from . import context_builder as cb
from .common import read_json
from ctxcomp.io import canonical, digest

VERSION = 'TASK_VIEW_2.0'
COLLECTIONS = ('analyses', 'assessments', 'requirements', 'source_items', 'records')
IDENTITIES = ('analysis_id', 'item_id', 'requirement_id', 'id')
RELATION_STATES = {'CONFIRMED', 'ABSENT', 'UNKNOWN'}


def pointer(value, path):
    if path == '':
        return value
    if not isinstance(path, str) or not path.startswith('/'):
        raise ValueError('Expected a JSON pointer')
    for key in path[1:].split('/'):
        key = key.replace('~1', '/').replace('~0', '~')
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def _identity(record):
    ids = [record[k] for k in IDENTITIES if isinstance(record.get(k), str)]
    if len(set(ids)) > 1:
        return None  # Preserve the whole local object; do not guess identity scope.
    return ids[0] if ids else None


def index_result(value):
    """Index existing record collections without discarding any local qualifiers.

    Only an unambiguous root collection is split. Other layouts use a whole
    root object rather than guessing the scope of narrative conditions.
    """
    if not isinstance(value, dict):
        raise ValueError('Formal result must be an object')
    collections = [k for k in COLLECTIONS if isinstance(value.get(k), list)]
    if len(collections) != 1:
        return {'records': {'$root': {'pointer': '', 'value': value}}, 'shared': {}}
    name = collections[0]
    rows = value[name]
    ids = [_identity(r) if isinstance(r, dict) else None for r in rows]
    if not rows or any(i is None for i in ids) or len(set(ids)) != len(ids):
        return {'records': {'$root': {'pointer': '', 'value': value}}, 'shared': {}}
    return {'records': {rid: {'pointer': f'/{name}/{i}', 'value': rows[i]}
                        for i, rid in enumerate(ids)},
            'shared': {k: v for k, v in value.items() if k != name}}


def build_view(artifacts, assignments, *, character_budget=24000):
    """Artifacts are host-authorized file refs, never paths invented by a model.

    Each assignment is {output_id, artifact_id, record_ids}. Optional formal
    result context_links are {from, to, kind, state, evidence_pointers}; they
    describe dependencies without establishing the truth of a relationship.
    Both ends of *all* touching links, including ABSENT/UNKNOWN, are retained.
    """
    if type(character_budget) is not int or character_budget < 1:
        raise ValueError('Positive task-view budget required')
    if not isinstance(artifacts, dict) or not artifacts:
        raise ValueError('Host-authorized formal artifacts required')
    cb.check_refs(artifacts)
    contents = {name: read_json(ref['path']) for name, ref in artifacts.items()}
    indexes = {name: index_result(value) for name, value in contents.items()}
    if not isinstance(assignments, list) or not assignments:
        raise ValueError('Explicit output assignments required')
    outputs, included, selections, used = [], {}, [], 0
    for assignment in assignments:
        if set(assignment) != {'output_id', 'artifact_id', 'record_ids'}:
            raise ValueError('Unknown task-view assignment fields')
        aid, output = assignment['artifact_id'], assignment['output_id']
        if aid not in indexes or not isinstance(output, str) or not output:
            raise ValueError('Unknown artifact or empty output identity')
        seeds = assignment['record_ids']
        if not isinstance(seeds, list) or not seeds or len(seeds) != len(set(seeds)):
            raise ValueError('Nonempty distinct assigned record IDs required')
        index = indexes[aid]
        if not set(seeds) <= set(index['records']):
            raise ValueError('Assignment references absent formal record')
        needed = set(seeds)
        relations = contents[aid].get('context_links', []) if '$root' not in index['records'] else []
        if not isinstance(relations, list):
            raise ValueError('context_links must be a list')
        links = []
        for link in relations:
            if (not isinstance(link, dict) or set(link) !=
                    {'from', 'to', 'kind', 'state', 'evidence_pointers'}
                    or link['state'] not in RELATION_STATES
                    or not isinstance(link['kind'], str) or not link['kind']):
                raise ValueError('Invalid formal relation declaration')
            refs = link['evidence_pointers']
            if not isinstance(refs, list) or (link['state'] == 'CONFIRMED' and not refs):
                raise ValueError('Confirmed relation needs bound source evidence')
            for path in refs:
                if pointer(contents[aid], path) in (None, '', {}, []):
                    raise ValueError('Empty formal relation support')
        # Follow only declared identities. Missing local references restrict the
        # affected output; they do not suppress independent assigned work.
        gaps = []
        changed = True
        while changed:
            before = set(needed)
            for rid in list(needed):
                requires = [] if rid == '$root' else index['records'][rid]['value'].get('context_requires', [])
                if not isinstance(requires, list) or any(not isinstance(x, str) for x in requires):
                    raise ValueError('Invalid formal record dependency list')
                for target in requires:
                    if target not in index['records']:
                        gaps.append({'record_id': rid, 'kind': 'MISSING_DEPENDENCY', 'target': target})
                    else:
                        needed.add(target)
            for link in relations:
                if {link['from'], link['to']} & needed:
                    for target in (link['from'], link['to']):
                        if target not in index['records']:
                            gaps.append({'record_id': link['from'], 'kind': 'MISSING_RELATION_ENDPOINT', 'target': target})
                        else:
                            needed.add(target)
            changed = needed != before
        links = [link for link in relations if {link['from'], link['to']} & needed]
        for rid in sorted(needed):
            required = index['records'][rid]['value'].get('context_required_relations', [])
            if not isinstance(required, list) or any(not isinstance(k, str) or not k for k in required):
                raise ValueError('Invalid required relation kinds')
            for kind in required:
                declared = [link for link in links if rid in (link['from'], link['to']) and link['kind'] == kind]
                if not declared:
                    gaps.append({'record_id': rid, 'kind': 'RELATION_NOT_DECLARED', 'target': kind})
                elif any(link['state'] != 'CONFIRMED' for link in declared):
                    gaps.append({'record_id': rid, 'kind': 'REQUIRED_RELATION_UNRESOLVED', 'target': kind})
        gaps = list({canonical(g): g for g in gaps}.values())
        selections.append({'output_id': output, 'artifact_id': aid,
            'assigned_record_ids': list(seeds), 'selected_record_ids': sorted(needed),
            'dependency_record_ids': sorted(needed - set(seeds)), 'gaps': gaps,
            'relation_scope': 'DECLARED_RELATIONS_ONLY' if links else 'NO_RELATIONS_DECLARED',
            'semantic_completeness': 'NOT_ASSESSED'})
        # Shared unknowns/conditions/counterevidence remain whole. Do not infer
        # their scope from prose. Evidence pointers are materialized, not URLs.
        unit = {'artifact_id': aid,
                'shared': {k: v for k, v in index['shared'].items() if k != 'context_links'},
                'records': {rid: index['records'][rid] for rid in sorted(needed)},
                'relations': links, 'selection_gaps': gaps,
                'relation_evidence': {p: pointer(contents[aid], p)
                                      for link in links for p in link['evidence_pointers']}}
        key = digest(unit)
        addition = len(canonical(unit)) if key not in included else 0
        if used + addition > character_budget:
            outputs.append({'output_id': output, 'status': 'INPUT_NOT_LOADED',
                            'reason': 'Required complete local unit exceeds task-view budget',
                            'unit_id': None, 'missing_context': gaps,
                            'omitted_record_ids': sorted(needed)})
        else:
            included[key] = unit
            used += addition
            outputs.append({'output_id': output, 'status': 'INPUT_RELATION_GAP' if gaps else 'INPUT_LOADED',
                            'reason': 'Assigned records and declared dependency closure retained',
                            'unit_id': key, 'missing_context': gaps, 'omitted_record_ids': []})
    if len({o['output_id'] for o in outputs}) != len(outputs):
        raise ValueError('One assignment per output; group dependencies in its formal result')
    view = {'version': VERSION, 'units': included, 'outputs': outputs,
            'boundary': 'Formal result declarations remain declarations; no new scientific qualification. '
                        'Unknown/absent relationships are not positive matches. '
                        'Not loaded is distinct from absent in the formal result.'}
    cb.check_refs(artifacts)
    return {'view': copy.deepcopy(view),
            'bindings': {**{'handoff:' + k: v for k, v in artifacts.items()},
                         'handoff:implementation': cb.file_ref(__file__)},
            'audit': {'selected_characters': used, 'budget': character_budget,
                      'model_calls': 0, 'selections': selections,
                      'assignments': copy.deepcopy(assignments),
                      'artifact_hashes': {k: v['sha256'] for k, v in artifacts.items()},
                      'guarantee': 'Declared dependency closure, not proof of undeclared semantic completeness'}}


def verify_view(result, artifacts, assignments, *, character_budget=24000):
    expected = build_view(artifacts, assignments, character_budget=character_budget)
    if result != expected:
        raise ValueError('Task view omitted or changed formal content/dependencies')
    return result


def validate_support(support, bindings, route):
    """Reconstructing a request may not discard or alter its frozen resolution."""
    ref = bindings.get('resolver:packet')
    if ref is None:
        raise ValueError('Context support needs a frozen resolver packet')
    cb.check_refs({'resolver:packet': ref})
    packet = read_json(ref['path'])
    if (packet.get('version') != 'AUTOMATIC_CONTEXT_RESOLUTION_1.0'
            or digest({k: v for k, v in packet.items() if k != 'sha256'}) != packet.get('sha256')
            or packet.get('route') != route or packet.get('background') != support):
        raise ValueError('Context support differs from its bound resolution')
    if any(bindings.get(k) != v for k, v in packet['bindings'].items()):
        raise ValueError('Context support lost a source/implementation binding')
    cb.check_refs(packet['bindings'])


def require_outputs(bundle, output_ids):
    """Host-side permission for an operation; a LIMITED row cannot be ignored."""
    cb.verify_bundle(bundle)
    support = bundle['request']['payload'].get('context_support')
    if support is None:
        return  # Legacy requests keep their existing admission/validation path.
    rows = {r['output_id']: r for r in support['outputs']}
    if not output_ids or any(i not in rows or rows[i]['status'] != 'READY_WITHIN_DECLARED_SCOPE' for i in output_ids):
        raise ValueError('Operation has unresolved context dependencies')
