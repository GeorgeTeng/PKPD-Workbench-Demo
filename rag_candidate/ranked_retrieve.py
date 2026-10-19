"""Read-only reviewed retrieval with interchangeable lexical rankers.

Reuses the existing pinned publication, evidence packet and model_background
contract. Rankings never establish applicability or context sufficiency.
"""
from collections import Counter
import copy
import importlib.util
import math
from pathlib import Path
import re

from .rag_v1 import RagError, canonical, check_refs, digest, file_ref, read_json, text_hash
from .reviewed_retrieve import VERSION, ELIGIBLE_LAYERS, ROUTES
from . import task_evidence
from . import knowledge_view

RANKERS = {'overlap', 'bm25', 'bm25f'}


def _strings(value):
    if isinstance(value, str): return value
    if isinstance(value, dict): return ' '.join(_strings(v) for v in value.values())
    if isinstance(value, list): return ' '.join(_strings(v) for v in value)
    return ''


def _terms(value, catalog):
    # Controlled lexical variants, not scientific equivalence or permission.
    aliases = {'censored':'censor', 'censoring':'censor', 'noncompartmental':'nca',
               'covariates':'covariate', 'covariances':'covariance'}
    return [aliases.get(t,t) for t in tokens(_strings(value), catalog)]


FIELDS = {'title':4.0, 'method_keywords':4.0, 'claim':2.0, 'required_inputs':2.0,
          'conditions':2.0, 'limitations':1.0, 'method_recipe':0.5, 'claim_support':0.5}


def relevance_terms(catalog, query):
    docs = [set(_terms({k:c.get(k) for k in FIELDS}, catalog)) for c in catalog['cards']
            if c['id'] in catalog['binding']['eligible_card_ids']]
    df = Counter(t for d in docs for t in d)
    known = set(_terms(query,catalog)) & set(df)
    # Rare query concepts distinguish binding from generic concentration prose.
    anchors = sorted(known, key=lambda t:(df[t],t))[:3]
    return anchors, min(2,len(anchors))


def load_catalog(binding_path):
    binding_ref = file_ref(binding_path)
    binding = read_json(binding_path)
    if binding.get('version') != VERSION:
        raise RagError('Unsupported reviewed binding')
    check_refs(binding['bindings'])
    root = Path(binding['root']).resolve(strict=True)
    cards = read_json(root / 'cards.json')
    sources = {s['id']: s for s in read_json(root / 'source_registry.json')}
    chunks = {}
    for line in (root / 'chunks.jsonl').read_text(encoding='utf-8').splitlines():
        import json
        chunk = json.loads(line)
        if chunk['id'] in chunks:
            raise RagError('Duplicate chunk identity')
        chunks[chunk['id']] = chunk
    spec = importlib.util.spec_from_file_location('_bound_method_terms', root / 'layered_context.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    check_refs(binding['bindings'])
    check_refs({'binding': binding_ref})
    return {'binding': binding, 'binding_ref': binding_ref, 'root': root,
            'cards': cards, 'sources': sources, 'chunks': chunks,
            'aliases': copy.deepcopy(module.ALIASES), 'stop': set(module.STOP),
            'legacy_words': module.words}


def tokens(text, catalog):
    for term, expansion in catalog['aliases'].items():
        if term in text:
            text += ' ' + expansion
    words = re.findall(r'[a-z][a-z0-9_]*', text.lower())
    return [w[:-1] if len(w) > 5 and w.endswith('s') else w
            for w in words if w not in catalog['stop']]


def rank_cards(catalog, query, stage, allowed_source_ids, branches=(), *, ranker='bm25'):
    if ranker not in RANKERS:
        raise RagError('Unknown method ranker')
    scope = set(allowed_source_ids)
    if not scope or not scope <= set(catalog['sources']):
        raise RagError('Explicit known source scope required')
    eligible = set(catalog['binding']['eligible_card_ids'])
    candidates = [c for c in catalog['cards'] if c['id'] in eligible
                  and c.get('knowledge_layer') in ELIGIBLE_LAYERS
                  and stage in c['topics'] and set(c['source_ids']) <= scope
                  and not any(s.startswith('IN_') for s in c['source_ids'])
                  and set(c.get('required_branches', [])) <= set(branches)]
    if ranker == 'bm25f':
        anchors, required = relevance_terms(catalog, query)
        documents = [{field: Counter(_terms(c.get(field), catalog)) for field in FIELDS} for c in candidates]
        df = Counter(t for d in documents for t in set().union(*(set(v) for v in d.values())))
        averages = {f:sum(sum(d[f].values()) for d in documents)/max(1,len(documents)) for f in FIELDS}
        query_terms = set(_terms(query,catalog))
        scores=[]
        for card,doc in zip(candidates,documents):
            present=set().union(*(set(v) for v in doc.values()))
            if not required or len(set(anchors)&present)<required: continue
            score=0.0
            for term in query_terms:
                tf=sum(weight*doc[field][term]/(.25+.75*sum(doc[field].values())/max(averages[field],1))
                       for field,weight in FIELDS.items())
                if tf:
                    score+=math.log(1+(len(documents)-df[term]+.5)/(df[term]+.5))*tf*2.2/(tf+1.2)
            scores.append((score,card))
    elif ranker == 'overlap':
        words = catalog['legacy_words']
        q = words(query)
        scores = [(len(q & words(c['title'] + ' ' + ' '.join(c.get('method_keywords', [])))) /
                   math.sqrt(max(1, len(words(c['title'] + ' ' + ' '.join(c.get('method_keywords', [])))))), c)
                  for c in candidates]
    else:
        # Method fields only: source drug names and clinical examples cannot
        # silently drive a general-method search. No learned model or DB needed.
        documents = [tokens(c['title'] + ' ' + ' '.join(c.get('method_keywords', []))
                            + ' ' + c.get('claim', ''), catalog) for c in candidates]
        counts = [Counter(d) for d in documents]
        df = Counter(term for doc in counts for term in doc)
        avg = sum(map(len, documents)) / max(1, len(documents))
        query_terms = set(tokens(query, catalog))
        scores = []
        for card, document, count in zip(candidates, documents, counts):
            score = 0.0
            for term in query_terms:
                tf = count[term]
                if tf:
                    idf = math.log(1 + (len(documents) - df[term] + .5) / (df[term] + .5))
                    score += idf * tf * 2.2 / (tf + 1.2 * (.25 + .75 * len(document) / max(avg, 1)))
            scores.append((score, card))
    return [{'card_id': c['id'], 'score': score} for score, c in
            sorted(scores, key=lambda row: (-row[0], row[1]['id'])) if score > 0]


def retrieve_ranked(binding_path, *, question, query, stage, project_context,
                    allowed_source_ids, branches=(), allow_draft=False,
                    consumer_route='method_background', max_methods=2,
                    character_budget=32768, ranker='bm25', method_ids=(), catalog=None,
                    task_profile=None, evidence_mode='primary_excerpt', card_projection=True):
    if not allow_draft or consumer_route not in ROUTES:
        raise RagError('Explicit background route and draft configuration required')
    if (not isinstance(project_context, dict) or not project_context.get('objective')
            or not isinstance(question, str) or not question.strip()
            or not isinstance(query, str) or not query.strip()):
        raise RagError('Concrete task objective and information need required')
    if type(max_methods) is not int or not 1 <= max_methods <= 6:
        raise RagError('Invalid method count')
    if type(character_budget) is not int or not 1 <= character_budget <= 48000:
        raise RagError('Invalid method budget')
    cat = catalog or load_catalog(binding_path)
    delivery = knowledge_view.mode_for(task_profile, evidence_mode)
    check_refs({'binding': cat['binding_ref'], **cat['binding']['bindings']})
    if file_ref(binding_path) != cat['binding_ref']:
        raise RagError('Catalog belongs to a different binding')
    ranking = rank_cards(cat, query, stage, allowed_source_ids, branches, ranker=ranker)
    by_id = {c['id']: c for c in cat['cards']}
    # Exact references bypass ranking, never authorization or stage/branch filters.
    if method_ids:
        scoped = set(cat['binding']['eligible_card_ids'])
        for cid in method_ids:
            c = by_id.get(cid, {})
            if (cid not in scoped or c.get('knowledge_layer') not in ELIGIBLE_LAYERS
                    or stage not in c.get('topics', [])
                    or not set(c.get('source_ids', [])) <= set(allowed_source_ids)
                    or any(s.startswith('IN_') for s in c.get('source_ids', []))
                    or not set(c.get('required_branches', [])) <= set(branches)):
                raise RagError('Exact method reference outside current authorization')
        ranking = [{'card_id': cid, 'score': None} for cid in dict.fromkeys(method_ids)]
    selected, evidence, originals, omitted = [], {}, {}, []
    used = 0
    for hit in ranking:
        # Earlier deletion estimates depended on visible original excerpts.
        # Do not reuse them when originals are host-only: retain all card prose.
        card = task_evidence.project(by_id[hit['card_id']],
            task_profile if card_projection and delivery == 'primary_excerpt' else None)
        added, refs = {}, {}
        for cid in card['evidence_chunk_ids']:
            if cid not in cat['chunks']:
                raise RagError('Dangling method citation')
            chunk = cat['chunks'][cid]
            if chunk['source_id'] not in allowed_source_ids or text_hash(chunk['text']) != chunk['sha256']:
                raise RagError('Invalid source scope or changed excerpt')
            if cid not in evidence:
                added[cid] = chunk
        if {cat['chunks'][cid]['source_id'] for cid in card['evidence_chunk_ids']} != set(card['source_ids']):
            raise RagError('Method source/citation mismatch')
        for sid in card['source_ids']:
            s = cat['sources'][sid]
            path = (cat['root'] / s['local_path']).resolve(strict=True)
            if not path.is_relative_to(cat['root']) or file_ref(path)['sha256'] != s['sha256']:
                raise RagError('Changed or escaped cited original')
            if sid not in originals:
                refs[sid] = {k: s[k] for k in ('id', 'title', 'url', 'document_url', 'local_path',
                    'sha256', 'access_level', 'source_status', 'document_type', 'limitations',
                    'applicability', 'source_example') if k in s}
        # Per-recall budget applies to delivery; primary originals remain complete
        # in the host packet even when the consumer only needs card references.
        delivered = added if delivery == 'primary_excerpt' else {k:knowledge_view.reference(v) for k,v in added.items()}
        size = len(canonical(card)) + len(canonical(delivered)) + len(canonical(refs))
        if used + size > character_budget:
            omitted.append(card['id'])
            continue
        selected.append(card)
        evidence.update(added)
        originals.update(refs)
        used += size
        if len(selected) == max_methods:
            break
    context = {'status': 'RECALLED_NOT_YET_ASSESSED' if selected else 'NO_MATCH_NOT_PROOF_OF_ABSENCE',
               'general_methods': selected,
               'applicability_and_examples': {'cited_originals': originals,
                   'evidence': list(evidence.values()), 'named_example_matches': []},
               'selection': {'method_query': query, 'stage': stage, 'ranker': ranker,
                             'budget_omitted': omitted, 'background_characters': used,
                             'task_profile': task_profile,
                             'evidence_mode': delivery,
                             'relevance_anchors': relevance_terms(cat, query)[0] if ranker == 'bm25f' else [],
                             'no_match_reason': 'NO_ELIGIBLE_RELEVANT_METHOD' if not ranking else None}}
    body = {'version': VERSION, 'question': question, 'publication': cat['binding']['publication'],
            'revision': cat['binding']['revision'], 'library_binding': cat['binding_ref'],
            'context': context, 'scientific_approval': False, 'production_dispatch_authorized': False,
            'usage_boundary': 'Method evidence only; project facts and Rules remain authoritative. '
                              'Recalled methods do not establish task sufficiency or scientific approval.'}
    check_refs({'binding': cat['binding_ref'], **cat['binding']['bindings']})
    return {**body, 'packet_sha256': digest(body)}
