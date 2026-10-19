"""Exact text sharing and bounded global allocation; no semantic selection.

Reuses the existing reducer's literal-frequency/savings rule. A validated task
view is indivisible: card guidance with references, or primary evidence when
requested. Complete source packets stay on host. Ranking is unchanged here.
"""
import copy
from collections import Counter
from itertools import combinations

from .rag_v1 import RagError, canonical, digest

TEXT_REF = 'rag_verbatim_ref'
ENCODING = 'RAG_EXACT_TEXT_SHARING_1.0'


def compact(knowledge):
    counts = Counter()
    def collect(value):
        if isinstance(value, dict):
            if TEXT_REF in value or 'rag_text_encoding' in value:
                raise RagError('Reserved RAG literal encoding marker')
            for child in value.values(): collect(child)
        elif isinstance(value, list):
            for child in value: collect(child)
        elif isinstance(value, str) and len(value) >= 120:
            counts[value] += 1
    collect(knowledge)
    names = {}
    for value, count in sorted(counts.items()):
        if count < 2: continue
        name = 'T' + str(len(names) + 1)
        before = count * len(canonical(value))
        after = count * len(canonical({TEXT_REF: name})) + len(canonical({name: value})) + 1
        if before - after >= 80:
            names[value] = name
    def encode(value):
        if isinstance(value, str) and value in names: return {TEXT_REF: names[value]}
        if isinstance(value, list): return [encode(child) for child in value]
        if isinstance(value, dict): return {key: encode(child) for key, child in value.items()}
        return value
    packed = encode(knowledge)
    if names:
        packed['rag_text_encoding'] = {'version': ENCODING,
            'instructions': 'Replace each rag_verbatim_ref object with the exact string in this dictionary. '
                'Each occurrence keeps its own method/source/condition scope. These labels are not evidence IDs. '
                'No text is summarized, and all source IDs, locators, hashes, conditions and limitations remain.',
            'verbatim': {name: value for value, name in names.items()}}
    if len(canonical(packed)) >= len(canonical(knowledge)):
        packed = copy.deepcopy(knowledge)
    if expand(packed) != knowledge:
        raise RagError('Exact RAG text sharing lost content')
    return packed


def expand(packed):
    encoding = packed.get('rag_text_encoding')
    if encoding is None: return copy.deepcopy(packed)
    if encoding.get('version') != ENCODING:
        raise RagError('Unsupported RAG text encoding')
    def decode(value):
        if isinstance(value, dict):
            if set(value) == {TEXT_REF}:
                if value[TEXT_REF] not in encoding['verbatim']:
                    raise RagError('Missing verbatim RAG text')
                return encoding['verbatim'][value[TEXT_REF]]
            return {key: decode(child) for key, child in value.items()}
        if isinstance(value, list): return [decode(child) for child in value]
        return value
    return decode({key: value for key, value in packed.items() if key != 'rag_text_encoding'})


def union(views):
    methods, evidence, sources, references = {}, {}, {}, {}
    for view in views:
        for target, items, label in ((methods, view['methods'], 'method'), (evidence, view['evidence'], 'evidence')):
            for item in items:
                key = item['id']
                if key in target and target[key] != item:
                    raise RagError('Conflicting ' + label + ' identity')
                target[key] = item
        for key, item in view['sources'].items():
            if key in sources and sources[key] != item:
                raise RagError('Conflicting source identity')
            sources[key] = item
        for key, item in view.get('source_references', {}).items():
            if key in references and references[key] != item:
                raise RagError('Conflicting source reference identity')
            references[key] = item
    # A primary excerpt and reference may coexist only for the same source text.
    for key in set(references) & set(evidence):
        from .knowledge_view import reference
        if references[key] != reference(evidence[key]):
            raise RagError('Primary evidence differs from its task reference')
    result = {'methods': [methods[k] for k in sorted(methods)],
            'evidence': [evidence[k] for k in sorted(evidence)],
            'sources': {k: sources[k] for k in sorted(sources)}}
    if references:
        result['source_references'] = {k:references[k] for k in sorted(references)}
    return result


def allocate(candidates, build_background, *, budget):
    """At most 2**8 subsets: maximize needs with intact first-choice evidence.

    Equal-priority needs; ties minimize actual serialized size, then stable IDs.
    No caller-order priority, method substitutions, partial cards or follow-up calls.
    """
    if len(candidates) > 8:
        raise RagError('At most eight candidates per bounded allocation')
    by_id = {c['need_id']: c for c in candidates}
    if len(by_id) != len(candidates):
        raise RagError('Duplicate allocation need')
    # Validate collisions across all candidates, including those later omitted.
    all_raw = union([c['knowledge'] for c in candidates])
    full = build_background(set(by_id), compact(all_raw))
    best = None
    considered = 0
    ids = sorted(by_id)
    for count in range(len(ids), -1, -1):
        for chosen in combinations(ids, count):
            considered += 1
            raw = union([by_id[key]['knowledge'] for key in chosen])
            packed = compact(raw)
            background = build_background(set(chosen), packed)
            size = len(canonical(background))
            if size > budget: continue
            score = (size, chosen)
            if best is None or score < best[0]:
                best = (score, chosen, raw, background)
        if best is not None: break
    if best is None:
        raise RagError('Task view and complete gap ledger exceed context budget')
    _, chosen, raw, background = best
    selected = set(chosen)
    return background, selected, {
        'policy': 'MAX_COMPLETE_NEEDS_THEN_MIN_SERIALIZED_SIZE',
        'budget_characters': budget, 'candidate_needs': len(ids),
        'selected_need_ids': list(chosen), 'omitted_need_ids': sorted(set(ids) - selected),
        'subsets_examined': considered, 'raw_union_characters': len(canonical(all_raw)),
        'all_candidates_background_characters': len(canonical(full)),
        'selected_raw_knowledge_characters': len(canonical(raw)),
        'selected_packed_knowledge_characters': len(canonical(background['knowledge'])),
        'selected_knowledge_sha256': digest(raw), 'lossless_roundtrip_verified': True,
        'background_characters': len(canonical(background)),
        'boundary': 'Allocated evidence is not a semantic sufficiency verdict.'}
