"""Bound input-planning views. Unknown cards/profiles retain the full card."""
import copy
from .rag_v1 import digest, canonical, check_refs
from .projection_policy import SAFE_PROJECTIONS
INPUT_PROFILES = {'requirements_planning', 'impact_advice'}
def project(card, task_profile=None):
    original = copy.deepcopy(card)
    if task_profile not in INPUT_PROFILES or not isinstance(card.get('method_recipe'), dict): return original
    rule = SAFE_PROJECTIONS.get(digest(card))
    if not rule: return original
    check_refs(rule['bindings'])
    omitted = sorted(set(rule['fields']) & set(card['method_recipe']))
    projected = copy.deepcopy(card)
    for key in omitted: del projected['method_recipe'][key]
    projected['task_reference_projection'] = {'profile':task_profile, 'parent_card_sha256':digest(card),
        'omitted_recipe_fields':omitted, 'scope':'Input planning and impact advice only; cannot authorize numerical execution.'}
    # Audit metadata must not make the task view larger than the full card.
    return projected if len(canonical(projected)) < len(canonical(original)) else original
def bindings():
    return {'projection:'+sha+':'+key:ref for sha,rule in SAFE_PROJECTIONS.items() for key,ref in rule['bindings'].items()}
