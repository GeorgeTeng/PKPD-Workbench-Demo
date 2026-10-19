"""Compile only frozen, explicit clause replacements. Never infer applicability."""
import copy
from ctxcomp.io import digest


def compile_rules(payload):
    binding=payload.get('effective_rule_binding')
    if not binding or payload.get('compression_profile',{}).get('id')!='LEAN_1.0':
        return payload,[]
    full_binding={**binding,'processing_rules':payload['processing_rules'],'governance':payload['governance']}
    if digest(full_binding)!=payload.get('effective_rule_binding_sha256') or digest(payload['processing_rules'])!=payload.get('processing_rules_sha256'):
        raise ValueError('Frozen rule binding/hash mismatch before compilation')
    wire=copy.deepcopy(payload);pack=wire['processing_rules'];audit=[]
    by_id={r['id']:i for i,r in enumerate(pack['rules'])}
    if len(by_id)!=len(pack['rules']):raise ValueError('Duplicate rule IDs')
    for override in binding['execution_overrides']:
        target=override['source_id'];paths=set(override['clause_paths']);removed={}
        if not override['effective_instruction'].strip():raise ValueError('Empty effective instruction')
        if target not in by_id and target!='scientific_extraction':raise ValueError('Unknown override target')
        original=pack['rules'][by_id[target]] if target in by_id else pack[target]
        def project(value,prefix=''):
            if isinstance(value,(list,dict)):
                result=[] if isinstance(value,list) else {}
                for key,child in (enumerate(value) if isinstance(value,list) else value.items()):
                    path=prefix+'/'+str(key).replace('~','~0').replace('/','~1')
                    if path in paths:removed[path]=copy.deepcopy(child);continue
                    child=project(child,path)
                    if isinstance(result,list):result.append(child)
                    else:result[key]=child
                return result
            return value
        compiled=project(original)
        absent=paths-removed.keys()
        # host_requirement is intentionally not part of the frozen model pack.
        if absent-{'/host_requirement'}:
            raise ValueError('Override points to an absent clause: '+str(sorted(absent)))
        compiled['effective_execution_instruction']=override['effective_instruction']
        if target in by_id:pack['rules'][by_id[target]]=compiled
        else:pack[target]=compiled
        audit.append({'source_id':target,'clause_paths':override['clause_paths'],
                      'superseded_clauses':removed,'already_host_only':sorted(absent),
                      'effective_instruction':override['effective_instruction'],
                      'original_sha256':digest(original),'compiled_sha256':digest(compiled)})
    wire['effective_rule_binding'].pop('execution_overrides')
    wire['effective_rule_binding']['execution_overrides']='Applied by the host to processing_rules. Each affected rule/companion includes its exact effective_execution_instruction; only named procedural clauses were replaced. Full original clauses and bindings remain in the host audit.'
    old='Read effective_rule_binding.precedence and its explicit clause overrides:'
    wire['instructions']=wire['instructions'].replace(old,
        'Follow the compiled processing_rules, including each effective_execution_instruction, and effective_rule_binding.precedence:')
    return wire,audit
