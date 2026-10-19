"""Lossless model-input factoring and explicit stage boundaries.

No retrieval agent, truncation, scientific rule rewrite or automatic retry.
Experimental profiles are task-local; source files never change between trials.
"""
import copy
import json
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from ctxcomp.io import digest
from .common import read_json
from . import context_routes

POLICY = Path(__file__).parent/'resources/context_builder/stage_scope.v1.json'
VERSION = 'CONTEXT_OPTIMIZATION_1.1'
_profile = ContextVar('context_experiment_profile', default=None)
PROFILES = ('baseline', 'dedup', 'scoped', 'focused')
RESERVED = {'context_rule_defaults', 'context_quotes', 'context_encoding', 'stage_context', 'output_focus'}


@contextmanager
def experiment_profile(name):
    """Explicit, isolated evaluation override; production dispatch guards remain."""
    if name not in PROFILES:
        raise ValueError('Unknown context experiment profile: '+str(name))
    token = _profile.set(name)
    try:
        yield
    finally:
        _profile.reset(token)


def serialized(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def merge_defaults(row, defaults):
    for key, value in defaults.items():
        if key not in row:
            row[key] = copy.deepcopy(value)
        elif isinstance(value, dict):
            merge_defaults(row[key], value)


def rule_defaults(payload):
    defaults = {}
    for section in ('rules', 'project_rules'):
        rows = payload.get(section)
        if not isinstance(rows, list) or len(rows) < 3 or not all(isinstance(r, dict) for r in rows):
            continue
        shared = {}
        # Operative text, IDs, conditions, exceptions and provenance stay inline.
        for container in (None, 'scope', 'requirement', 'usage'):
            objects = rows if container is None else [r.get(container) for r in rows]
            if not all(isinstance(obj, dict) for obj in objects):
                continue
            keys = {'kind'} if container is None else set.intersection(*(set(obj) for obj in objects))
            for key in sorted(keys):
                if not all(key in obj for obj in objects):
                    continue
                counts = Counter(serialized(obj[key]) for obj in objects)
                value_json, count = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[0]
                # Do not add a default for tiny or uncommon values.
                if count < 3 or (count-1)*(len(key)+len(value_json)+4) < 120:
                    continue
                value = json.loads(value_json)
                target = shared if container is None else shared.setdefault(container, {})
                target[key] = value
                for obj in objects:
                    if serialized(obj[key]) == value_json:
                        del obj[key]
        if shared:
            defaults[section] = shared
    if defaults:
        payload['context_rule_defaults'] = defaults


QUOTE_SECTIONS = ('recorded_shortages', 'coverage_summary', 'requirements',
                  'project_context', 'data_overviews', 'overview_notes')


def quote_nodes(value):
    if isinstance(value, list):
        for child in value:
            yield from quote_nodes(child)
    elif isinstance(value, dict):
        # Complete evidence-object identity must match, including study/item scope.
        # No cross-source or cross-item deduplication based on text similarity.
        if isinstance(value.get('quote'), str) and value.get('source') and 'item_id' in value:
            yield value
        else:
            for key, child in value.items():
                if key not in {'schema', 'source_units', 'raw_tables', 'actual_data'}:
                    yield from quote_nodes(child)


def factor_quotes(payload):
    groups = {}
    for section in QUOTE_SECTIONS:
        for node in quote_nodes(payload.get(section)):
            groups.setdefault(serialized(node), []).append(node)
    quotes = {}
    for identity, nodes in sorted(groups.items()):
        text = nodes[0]['quote']
        if len(nodes) < 2 or (len(nodes)-1)*len(text) < 160:
            continue
        name = 'Q'+str(len(quotes)+1)
        quotes[name] = text
        for node in nodes:
            if 'quote_ref' in node:
                raise ValueError('Source evidence already contains a quote_ref')
            del node['quote']
            node['quote_ref'] = name
    if quotes:
        payload['context_quotes'] = quotes


def expand(payload):
    """Restore the exact pre-optimization payload, independent of host artifacts."""
    out = copy.deepcopy(payload)
    defaults = out.pop('context_rule_defaults', {})
    for section, values in defaults.items():
        for row in out[section]:
            merge_defaults(row, values)
    quotes = out.pop('context_quotes', {})
    def restore(value):
        if isinstance(value, list):
            for child in value:
                restore(child)
        elif isinstance(value, dict):
            if 'quote_ref' in value and value['quote_ref'] in quotes:
                if 'quote' in value:
                    raise ValueError('Ambiguous encoded quote')
                value['quote'] = quotes[value.pop('quote_ref')]
            else:
                for child in value.values():
                    restore(child)
    for section in QUOTE_SECTIONS:
        restore(out.get(section))
    out.pop('context_encoding', None)
    out.pop('stage_context', None)
    out.pop('output_focus', None)
    return out


ENCODING = (
    'Lossless input encoding only; the response schema is unchanged. For rules/project_rules, '
    'recursively inherit absent keys from context_rule_defaults for that section; explicit '
    'per-rule values override defaults, including empty values. Defaults retain NOT_SPECIFIED '
    'as unknown, never as satisfied. A quote_ref resolves to the verbatim text in context_quotes '
    'inside this input. Keep each occurrence\'s source, item and other scope fields. '
    'Q labels are internal text aliases, never evidence IDs; output original source IDs and '
    'resolved verbatim quotations. No external lookup is needed.'
)


def optimize(payload):
    context_routes.reject_repairs(payload)
    if RESERVED.intersection(payload):
        raise ValueError('Reserved ContextBuilder encoding fields supplied by adapter')
    config = read_json(POLICY)
    profile = _profile.get() or config['default_profile']
    if profile not in PROFILES:
        raise ValueError('Unknown production context profile')
    before = copy.deepcopy(payload)
    out = copy.deepcopy(payload)
    route = '.'.join(context_routes.select(payload))
    scope = config['routes'].get(route, config['legacy'])
    # Only adapter fields are checked. Never inspect arbitrary source text for instructions.
    forbidden = set(scope.get('forbidden_input_sections', [])).intersection(payload)
    if forbidden:
        raise ValueError('Out-of-stage evidence sections: '+', '.join(sorted(forbidden)))
    if profile != 'baseline':
        rule_defaults(out)
        factor_quotes(out)
        if 'context_rule_defaults' in out or 'context_quotes' in out:
            out['context_encoding'] = ENCODING
        if len(serialized(out)) >= len(serialized(before)):
            out = copy.deepcopy(before)
    if profile in {'scoped', 'focused'}:
        out['stage_context'] = scope['instruction']
        # Put operative instructions, defaults and evidence definitions before their uses.
        order = ['premise', 'stage_context', 'instructions', 'context_encoding',
                 'context_rule_defaults', 'context_quotes', 'governance']
        out = {**{k: out[k] for k in order if k in out},
               **{k: v for k, v in out.items() if k not in order}}
    if profile == 'focused':
        # A deterministic index into the existing contract, not feedback from a
        # rejected answer. This profile is an experiment until explicitly selected.
        gaps = before.get('recorded_shortages')
        instructions = before.get('instructions', '')
        actions = before.get('schema', {}).get('properties', {}).get('action_decisions', {}).get('properties', {})
        expected_limits = ('Keep all generated prose under 1100 words',
                           'Each action finding <=45 words; next_step <=25 words; source_scope <=20 words.',
                           'The assessment opinion is one direct sentence, <=30 words.')
        if (route != 'data.necessity' or not isinstance(gaps, dict) or not actions
                or not all(text in instructions for text in expected_limits)):
            raise ValueError('Focused profile requires the explicit 1100-word Necessity action contract')
        out['output_focus'] = {
            'purpose': 'Navigation and brevity aids for the existing contract; no new scientific requirements.',
            'analysis_gap_ids_exactly_once': list(gaps),
            'action_decision_keys': list(actions),
            'original_limits': 'All generated prose under 1100 words excluding gap IDs and copied evidence. Each action: source_scope <=20, finding <=45, next_step <=25 words. Assessment opinion <=30 words.',
            'writing_plan': 'Aim for at most 60 prose words per analysis group across all its prose fields, 50 per action decision, and 40 across assessment scope/opinion. Use concrete short clauses. Keep all distinct impacts and the original limits; do not repeat evidence narrative.',
            'consistency': 'Assess one next action per analysis. OPTIONAL_IMPROVEMENT implies NO_CURRENT_BLOCK; FUTURE_DEPENDENCY importance implies FUTURE_DEPENDENCY impact. Explain current blockers as current blockers, never optional improvements.',
            'accounting': 'Each listed gap must appear in analyses exactly once; related action_decisions may cite it again. Resolve context quote aliases to original evidence before writing. No external lookup, repair call or extra task.'}
    restored = expand(out)
    if restored != before:
        raise ValueError('Context optimization failed exact reconstruction')
    audit = {'version': VERSION, 'profile': profile, 'route': route,
             'roundtrip_exact': True, 'before_sha256': digest(before),
             'restored_sha256': digest(restored), 'after_sha256': digest(out),
             'characters_before': len(serialized(before)), 'characters_after': len(serialized(out)),
             'quote_definitions': len(out.get('context_quotes', {})),
             'rule_defaults_sections': list(out.get('context_rule_defaults', {})),
             'scope': scope, 'dropped_scientific_rules': [], 'dropped_evidence': [],
             'selection_policy': 'Explicit stage contract; preserve all supplied authorized MP and uncertain applicability. No keyword-only rule filtering.'}
    return out, audit
