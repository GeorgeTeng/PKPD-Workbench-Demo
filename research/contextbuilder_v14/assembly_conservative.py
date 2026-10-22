"""Existing ContextBuilder interface with reversible knowledge bindings.

The semantic map remains unknown: selection uses complete declared units.
The existing 64,000 raw-character guard and caller's full-wire guard both apply.
"""
import builder_engine_conservative as engine
import contracts
from knowledge_structure import normalize_card, validate_normalized


def assemble_support(base, request, task, view, recalls, allowed_sources,
                     *, character_budget=64000, final_fits=lambda value: True, retained_roots=()):
    if type(character_budget) is not int or not 0 < character_budget <= 64000:
        raise ValueError('Invalid unchanged raw context budget')
    normalized = {}
    for rec in recalls:
        for card in rec['packet']['context']['general_methods']:
            item = normalize_card(card)
            if not validate_normalized(item, card):
                raise ValueError('Knowledge normalization binding failure')
            key = item['card_sha256']
            normalized[key] = item
    ledger = engine.demand_ledger(base, task, request)
    def complete(raw):
        full = contracts.bind_need_boundaries(raw, request, ledger)
        return len(engine.canonical(full)) <= character_budget and final_fits(full)
    raw, audit = engine.assemble(base, request, task, view, recalls, allowed_sources,
                                character_budget=character_budget, final_fits=complete, retained_roots=retained_roots)
    full = contracts.bind_need_boundaries(raw, request, ledger)
    assert len(engine.canonical(full)) <= character_budget
    audit['knowledge_structure'] = normalized
    audit['source_bindings_are_not_semantic_approval'] = True
    return full, audit

choose_encoding = engine.choose_encoding
