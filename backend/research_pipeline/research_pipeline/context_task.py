"""Common task orchestration for registered workflow steps; no model execution.

Stage adapters own scientific intake and output contracts. This module arranges
their immutable input, optional question-scoped methods and projection controls.
Accepted upstream artifacts are supplied directly, never routed through RAG.
"""
import copy

from . import context_builder as cb, context_minimal_policy as policy


def at(value, path):
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def contract(route):
    value, reference = policy.load_policy()
    if route not in value['routes']:
        raise ValueError('No task orchestration contract for ' + route)
    entry = value['routes'][route]
    profile = value['profiles'][entry['profile']]
    return {'route': route, 'profile': entry['profile'], **copy.deepcopy(profile),
            **copy.deepcopy(entry), 'policy_ref': reference}


def validate_selection(payload, route):
    """Resolve only explicitly declared method-reference fields; never Rules/data."""
    selection = payload.get('context_selection')
    if selection is None:
        return copy.deepcopy(payload), {}, {}
    if (not isinstance(selection, dict) or set(selection) != {'references'}
            or not isinstance(selection['references'], list) or not selection['references']):
        raise ValueError('Context selection must declare method-reference sections')
    from . import context_reference_scope
    task = contract(route)
    projected, audit, refs = context_reference_scope.project(
        payload, selection['references'], allowed_paths=task['reference_fields'])
    refs['reference_scope:implementation'] = cb.file_ref(context_reference_scope.__file__)
    return projected, audit, refs


def assemble(bundle, *, retrieval_needs=None, retriever=None, reference_selection=None,
             context_request=None, context_resolver=None):
    """Assemble any registered task using its declared source and handoff boundary.

The retriever callback receives explicit needs, project context and consumer
route. It returns ``background`` plus nonempty immutable file ``bindings``.
It must freeze its packet before returning. No callback is invoked by default.
"""
    cb.verify_bundle(bundle)
    route = bundle['context_manifest']['route']
    task = contract(route)
    if (context_request is None) != (context_resolver is None):
        raise ValueError('Automatic context requires a request and one resolver callback')
    if context_request is not None and (retrieval_needs is not None or retriever is not None):
        raise ValueError('Use either automatic context or legacy explicit questions')
    if not retrieval_needs and retriever is None and reference_selection is None and context_request is None:
        return bundle
    original = copy.deepcopy(bundle['request']['payload'])
    payload = copy.deepcopy(original)
    refs = copy.deepcopy(bundle['context_manifest']['input_bindings'])
    refs.update({'task_orchestrator': cb.file_ref(__file__),
                 'task_contract_policy': task['policy_ref']})
    if context_request is not None:
        if 'context_support' in payload:
            raise ValueError('Task already contains resolved context support')
        project = at(original, task['method_retrieval'].get('project_path', ['task_context']))
        objective = project.get('objective') if isinstance(project, dict) else None
        objective = objective or original.get('objective')
        if isinstance(objective, str) and context_request.get('objective') != objective:
            raise ValueError('Automatic context objective differs from the authoritative task')
        response = context_resolver(copy.deepcopy(context_request), task=copy.deepcopy(task))
        cb.verify_bundle(bundle)
        if (not isinstance(response, dict) or set(response) != {'background', 'bindings'}
                or not isinstance(response['background'], dict) or not response['background']
                or not isinstance(response['bindings'], dict) or not response['bindings']
                or 'resolver:packet' not in response['bindings']):
            raise ValueError('Automatic resolver must return frozen support and packet bindings')
        if set(refs) & set(response['bindings']):
            raise ValueError('Automatic context bindings collide with authoritative inputs')
        cb.check_refs(response['bindings'])
        refs.update(response['bindings'])
        payload['context_support'] = copy.deepcopy(response['background'])
    if reference_selection is not None:
        if 'context_selection' in payload:
            raise ValueError('Task already declares reference selection')
        payload['context_selection'] = {'references': copy.deepcopy(reference_selection)}
        _, _, added = validate_selection(payload, route)
        refs.update(added)
    if retrieval_needs:
        spec = task['method_retrieval']
        if spec['mode'] != 'EXPLICIT_UNANSWERED_QUESTIONS':
            raise ValueError('Method retrieval is outside this task responsibility: ' + route)
        if not isinstance(retrieval_needs, list) or not 1 <= len(retrieval_needs) <= 8:
            raise ValueError('Declare one to eight independent unanswered questions')
        permitted = {'question', 'query', 'stage', 'allowed_source_ids', 'branches',
                     'allow_draft', 'max_methods', 'character_budget'}
        for need in retrieval_needs:
            if (not isinstance(need, dict) or set(need) - permitted
                    or need.get('stage') not in spec['allowed_stages']
                    or not isinstance(need.get('question'), str) or not need['question'].strip()
                    or not isinstance(need.get('query'), str) or not need['query'].strip()
                    or not isinstance(need.get('allowed_source_ids'), list)
                    or not need['allowed_source_ids']):
                raise ValueError('Invalid explicit method question')
        if len({n['question'] for n in retrieval_needs}) != len(retrieval_needs):
            raise ValueError('Duplicate unanswered question')
        if retriever is None:
            raise ValueError('Explicit unanswered questions require a retriever')
        path = spec['target']
        parent = at(payload, path[:-1])
        if not isinstance(parent, dict) or path[-1] in parent:
            raise ValueError('Missing task container or prepopulated method background')
        project = at(payload, spec['project_path'])
        if not isinstance(project, dict):
            project = {'objective': payload.get('objective')}
        # Method recall does not need a second copy of the entire task input.
        # Permissions, stage and branches are explicit on every question.
        project = {key: copy.deepcopy(project[key]) for key in spec.get('project_fields', ['objective'])
                   if key in project}
        response = retriever(copy.deepcopy(retrieval_needs), copy.deepcopy(project),
                             consumer_route=spec['consumer_route'])
        # Recheck authoritative input after retrieval, before final hashing.
        cb.verify_bundle(bundle)
        if (not isinstance(response, dict) or set(response) != {'background', 'bindings'}
                or not isinstance(response['background'], dict) or not response['background']
                or not isinstance(response['bindings'], dict) or not response['bindings']):
            raise ValueError('Retriever must return bound background and packet references')
        if set(refs) & set(response['bindings']):
            raise ValueError('Retrieved bindings collide with task inputs')
        cb.check_refs(response['bindings'])
        refs.update(response['bindings'])
        parent[path[-1]] = copy.deepcopy(response['background'])
    elif retriever is not None:
        raise ValueError('No unanswered question: do not configure a retrieval call')
    cb.check_refs(refs)
    # Provider gateways may reconstruct a bundle from the request alone. Carry
    # the immutable host bindings in that request so provenance cannot vanish
    # at this boundary. The model projection keeps them entirely host-side.
    payload['context_task_bindings'] = copy.deepcopy(refs)
    stage, operation = route.split('.', 1)
    result = cb.build_context(stage, operation, payload, original['schema'], input_bindings=refs)
    # Only the declared optional field and projection controls may be added.
    restored = copy.deepcopy(result['request']['payload'])
    if 'context_task_bindings' in original:
        restored['context_task_bindings'] = copy.deepcopy(original['context_task_bindings'])
    else:
        restored.pop('context_task_bindings')
    if retrieval_needs:
        path = task['method_retrieval']['target']
        del at(restored, path[:-1])[path[-1]]
    if reference_selection is not None:
        restored.pop('context_selection')
    if context_request is not None:
        restored.pop('context_support')
    if restored != original:
        raise ValueError('Task orchestration changed authoritative stage inputs')
    cb.verify_bundle(result)
    return result
