"""Model-facing projection: semantic connections stay; mechanical bindings stay on host.

Only explicit known audit fields are moved. Never recursively strip IDs, paths,
Rules, source text, conditions or the schema. The immutable host request and its
response-binding SHA remain unchanged, as with ctxcomp.model_view.
"""
import copy
import json
from pathlib import Path
from ctxcomp import model_view
from ctxcomp.io import digest
from .common import read_json, sha256
from . import context_effective_rules as effective
from . import context_optimization as optimization, context_routes
from . import context_minimal_policy as minimal_policy, minimal_context_reducer as minimal_reducer

PREMISES = Path(__file__).parent/'resources/context_builder/premises.v1.json'
VERSION = 'MODEL_CONTEXT_VIEW_2.4'


def _base_project(request):
    context_routes.reject_repairs(request['payload'])
    # One historical adapter explicitly requests Chinese prose. Do not mix it
    # with the project's English contract or silently rewrite the frozen prompt.
    instructions = ' '.join(request['payload'].get('instructions', '').split())
    if 'Use concise Chinese explanations with original scientific terms.' in instructions:
        raise ValueError('Legacy Chinese output instruction conflicts with the English project contract; rebuild using the current stage adapter')
    wire = copy.deepcopy(model_view.view(request))
    # Compile against original hashes before the earlier model view strips metadata.
    compiled, compiled_audit = effective.compile_rules(request['payload'])
    if compiled_audit:
        wire = copy.deepcopy(model_view.view({**request,'payload':compiled}))
    payload = wire['payload']
    config = read_json(PREMISES)
    stage = payload.get('stage')
    if stage not in config['stages']:
        raise ValueError('No premise for stage: '+str(stage))
    if 'premise' in payload:
        raise ValueError('Stage adapter already has a premise; resolve explicitly')
    moved = {}

    def move(obj, key, prefix='payload'):
        if key in obj:
            moved[prefix+'/'+key] = obj.pop(key)

    for key in ('governance_sha256','processing_rules_sha256','effective_rule_binding_sha256'):
        move(payload,key)
    move(payload, 'context_task_bindings')
    if stage in context_routes.EDA:
        move(payload, 'eda_context_bindings')
    binding = payload.get('effective_rule_binding')
    if isinstance(binding,dict):
        prefix='payload/effective_rule_binding'
        for key in ('source_pack_sha256','source_rule_sha256','source_companion_sha256','audit_source','included_rule_fields'):
            move(binding,key,prefix)
        # These contain actual exceptions, precedence and scientific limits.
        # Keep them verbatim. Only repeated authorization text is consolidated.
        authorizations=[]
        overrides=binding.get('execution_overrides',[])
        for i,clause in enumerate(overrides if isinstance(overrides,list) else []):
            loc=prefix+'/execution_overrides/'+str(i)
            move(clause,'source_clause_hashes',loc)
            if 'authorization' in clause:
                text=clause['authorization']
                if text not in authorizations:
                    authorizations.append(text)
                move(clause,'authorization',loc)
        if authorizations:
            binding['authorizations']=authorizations
    checks=payload.get('host_input_checks')
    if isinstance(checks,dict):
        for key in ('source_units_sha256','coverage_state_sha256','coverage_reference'):
            move(checks,key,'payload/host_input_checks')
    units=payload.get('source_units')
    if isinstance(units,list):
        for i,unit in enumerate(units):
            if isinstance(unit,dict):
                move(unit,'text_sha256','payload/source_units/'+str(i))
    registry=payload.get('source_registry')
    if isinstance(registry,list):
        for i,source in enumerate(registry):
            if isinstance(source,dict):
                move(source,'original_sha256','payload/source_registry/'+str(i))
    # Keep the existing operation contract unchanged. The short premise makes
    # the actor, starting assumptions and responsibility boundary explicit.
    premise = config['stages'][stage]
    if stage == 'HUMAN_REVIEW_SUMMARY_ONLY' and 'analyses' in payload and 'action_decisions' not in payload:
        premise = config['legacy_summary_premise']
    wire['payload']={'premise':premise+'\n\n'+config['common'], **payload}
    wire['payload'], optimization_audit = optimization.optimize(wire['payload'])
    before=len(json.dumps(model_view.view(request),ensure_ascii=False))
    after=len(json.dumps(wire,ensure_ascii=False))
    return wire, {'version':VERSION,'host_request_sha256':request['request_sha256'],
        'bindings':{name:{'path':str(Path(path).resolve()),'sha256':sha256(path)}
                    for name,path in [('projection',__file__),('effective_rules',effective.__file__),('premises',PREMISES),('base_view',model_view.__file__),('optimization',optimization.__file__),('stage_scope',optimization.POLICY),('route_selector',context_routes.__file__)]},
        'model_input_sha256':digest(wire),'baseline_model_characters':before,
        'model_characters':after,'character_reduction':before-after,
        'units':'Serialized characters, not tokenizer counts.',
        'host_only_fields':moved,'premises_version':config['version'],
        'compiled_rules_audit':compiled_audit,
        'optimization':optimization_audit,
        'request_identity':'Echo the original host request SHA; do not recompute it from the projected payload.',
        'retained':'Rules, exception clauses, precedence, source scope, evidence, required record links and response schema.',
        'automatic_retries':0,'automatic_patches':0}


def project(request):
    """One explicit minimum-semantic-context gate for every managed stage.

    Preserve the full host request and its response identity. Only the separate
    model view changes; historical artifacts are not rewritten or reauthorized.
    """
    route = '.'.join(context_routes.select(request['payload']))
    policy, policy_ref = minimal_policy.load_policy()
    if route not in policy['routes']:
        raise ValueError('No minimum-context task contract for ' + route)
    bindings = {'minimal_context_policy': policy_ref,
                'minimal_context_policy_loader': {'path': str(Path(minimal_policy.__file__).resolve()), 'sha256': sha256(minimal_policy.__file__)},
                'minimal_context_reducer': {'path': str(Path(minimal_reducer.__file__).resolve()), 'sha256': sha256(minimal_reducer.__file__)}}
    wire, audit = _base_project(request)
    # Decode any earlier experimental factoring before the single new contract.
    # Keep explicit navigation aids; they are not hidden model state.
    payload = optimization.expand(wire['payload'])
    for key in ('stage_context', 'output_focus'):
        if key in wire['payload']:
            payload[key] = copy.deepcopy(wire['payload'][key])
    from .context_task import validate_selection
    payload, reference_audit, reference_bindings = validate_selection(payload, route)
    # Projection controls are host audit, not another instruction for the model.
    payload.pop('context_selection', None)
    audit['reference_selection'] = reference_audit
    audit['bindings'].update(reference_bindings)
    audit['bindings']['task_orchestrator'] = {'path': str(Path(__file__).with_name('context_task.py').resolve()),
                                             'sha256': sha256(Path(__file__).with_name('context_task.py'))}
    wire['payload'], contract_audit = minimal_reducer.reduce_payload(payload, route, policy)
    audit['bindings'].update(bindings)
    audit['minimal_context'] = contract_audit
    audit['model_input_sha256'] = digest(wire)
    audit['model_characters'] = len(json.dumps(wire, ensure_ascii=False))
    audit['character_reduction'] = audit['baseline_model_characters'] - audit['model_characters']
    audit['retained'] = 'Required rule clauses, evidence scope and response references under an explicit stage-specific minimum-context contract; full host inputs retained.'
    for ref in audit['bindings'].values():
        if sha256(ref['path']) != ref['sha256']:
            raise ValueError('Projection input changed during minimum-context assembly: ' + ref['path'])
    return wire, audit


def view(request):
    return project(request)[0]
