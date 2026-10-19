"""Task-scoped card references, separate from primary-source evidence.

Complete cards and chunks remain in bound candidate packets. This module does
not summarize, infer adequacy, or authorize numerical execution. Only existing
input-planning/advice profiles default to a secondary methodological reference.
"""
import copy
from .rag_v1 import RagError, digest

MODES = {'auto', 'card_reference', 'primary_excerpt'}
REFERENCE_PROFILES = {'requirements_planning', 'impact_advice'}
# Indexing/storage fields only. Unknown fields and all semantic text stay.
HOST_FIELDS = {'origin_job', 'retrieval_keywords', 'method_keywords'}


def mode_for(profile, requested='auto'):
    if requested not in MODES:
        raise RagError('Unknown evidence delivery mode')
    if requested == 'card_reference' and profile not in REFERENCE_PROFILES:
        raise RagError('Card-reference delivery is outside this task responsibility')
    if requested != 'auto':
        return requested
    return 'card_reference' if profile in REFERENCE_PROFILES else 'primary_excerpt'


def reference(chunk):
    # Preserve all source metadata, not just a guessed subset of locator fields.
    result = copy.deepcopy({k:v for k,v in chunk.items() if k != 'text'})
    result['text_delivery'] = 'HOST_ONLY_REFERENCE_NOT_VISIBLE_EVIDENCE'
    result['text_characters'] = len(chunk['text'])
    return result


def project(knowledge, mode):
    if mode not in {'card_reference', 'primary_excerpt'}:
        raise RagError('Resolve evidence delivery mode before projection')
    result = copy.deepcopy(knowledge)
    for card in result['methods']:
        for field in HOST_FIELDS:
            card.pop(field, None)
    if mode == 'card_reference':
        refs = {e['id']:reference(e) for e in knowledge['evidence']}
        for card in knowledge['methods']:
            if not set(card['evidence_chunk_ids']) <= set(refs):
                raise RagError('Task card has an unresolved source reference')
            for support in card.get('claim_support', []):
                if not set(support['evidence_chunk_ids']) <= set(refs):
                    raise RagError('Task card claim has an unresolved source reference')
        result['evidence'] = []
        result['source_references'] = refs
    audit = {'mode':mode, 'full_knowledge_sha256':digest(knowledge),
        'view_sha256':digest(result), 'removed_index_fields':sorted(HOST_FIELDS),
        'primary_text_visible':mode == 'primary_excerpt',
        'boundary':'Card guidance is secondary reference material. Source locators are not visible '
                   'primary evidence and do not establish entailment or project sufficiency.'}
    return result, audit
