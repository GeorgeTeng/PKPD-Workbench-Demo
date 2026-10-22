"""Readable, exact aliases for repeated JSON values; no semantic rewriting."""
import copy
from collections import Counter

from .rag_v1 import canonical, digest, RagError

VERSION = 'EXACT_TASK_VIEW_WIRE_1'
SUPPORT_VERSION = 'EXACT_SUPPORT_WIRE_1'
RESERVED = {'$v', '$columns', '$rows', 'task_view_encoding', 'knowledge_encoding'}

_TASK_INSTRUCTIONS = (
    'Lossless task view. Expand {$v:id} using verbatim, at its original owner path. '
    'Expand {$columns:[keys],$rows:[values]} into objects matching row positions to columns. Keep all rows, order, types, nulls, units, locators and unknown relations. '
    'Shared text does not merge dataset identities or scopes. Aliases are not citations: cite the owning source and locator. '
    'This is reversible encoding, not new evidence. Unmarked arrays remain arrays. Decode to recover the exact original view.'
)
_SUPPORT_INSTRUCTIONS = (
    'Lossless knowledge encoding. Expand {$v:id} using verbatim at its original owner path. '
    'Expand {$columns:[keys],$rows:[values]} into objects matching row positions to columns. '
    'Keep every row, order, type, null, unit, locator, source identity, condition and need. '
    'Shared text does not merge dataset identities or scopes. Aliases are not citations: cite the owning source and locator. '
    'This is reversible encoding, not new evidence. Unmarked arrays remain arrays. Decode to recover the exact original knowledge.'
)


def _pack(value, marker):
    counts = Counter()

    def scan(item):
        if isinstance(item, dict):
            if RESERVED & set(item):
                raise RagError('Reserved delivery wire marker in source')
            for child in item.values():
                scan(child)
        elif isinstance(item, list):
            for child in item:
                scan(child)
        elif isinstance(item, str) and len(item) >= 40:
            counts[item] += 1
    scan(value)

    aliases = {}
    for text, count in sorted(counts.items()):
        name = 'v' + str(len(aliases) + 1)
        reference_cost = count * len(canonical({'$v': name})) + len(canonical({name: text}))
        if count >= 2 and count * len(canonical(text)) - reference_cost > 80:
            aliases[text] = name

    def encode(item):
        if isinstance(item, str) and item in aliases:
            return {'$v': aliases[item]}
        if isinstance(item, dict):
            return {key: encode(child) for key, child in item.items()}
        if isinstance(item, list):
            regular = [encode(child) for child in item]
            if (len(item) >= 3 and all(isinstance(row, dict) for row in item)
                    and all(set(row) == set(item[0]) for row in item)):
                keys = sorted(item[0])
                table = {'$columns': keys, '$rows': [[encode(row[key]) for key in keys] for row in item]}
                if len(canonical(table)) < len(canonical(regular)):
                    return table
            return regular
        return item

    packed = {marker: {'version': SUPPORT_VERSION if marker == 'knowledge_encoding' else VERSION,
                       'parent_sha256': digest(value),
                       'instructions': _SUPPORT_INSTRUCTIONS if marker == 'knowledge_encoding' else _TASK_INSTRUCTIONS,
                       'verbatim': {name: text for text, name in aliases.items()}},
              'payload': encode(value)}
    # The encoding is selected only when its canonical representation is smaller.
    if len(canonical(packed)) >= len(canonical(value)):
        return copy.deepcopy(value)
    if _unpack(packed, marker) != value:
        raise RagError('Delivery wire roundtrip failed')
    return packed


def _unpack(packed, marker):
    if not isinstance(packed, dict) or marker not in packed:
        return copy.deepcopy(packed)
    if set(packed) != {marker, 'payload'}:
        raise RagError('Unexpected delivery wire fields')
    meta = packed[marker]
    expected_version = SUPPORT_VERSION if marker == 'knowledge_encoding' else VERSION
    if not isinstance(meta, dict) or meta.get('version') != expected_version:
        raise RagError('Unknown delivery wire version')
    aliases = meta.get('verbatim')
    if not isinstance(aliases, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in aliases.items()):
        raise RagError('Invalid exact shared values')

    def decode(item):
        if isinstance(item, dict):
            if set(item) == {'$v'}:
                key = item['$v']
                if not isinstance(key, str) or key not in aliases:
                    raise RagError('Missing exact shared value')
                return aliases[key]
            if set(item) == {'$columns', '$rows'}:
                keys, rows = item['$columns'], item['$rows']
                if (not isinstance(keys, list) or any(not isinstance(k, str) for k in keys)
                        or len(set(keys)) != len(keys) or not isinstance(rows, list)):
                    raise RagError('Invalid column identity')
                if any(not isinstance(row, list) or len(row) != len(keys) for row in rows):
                    raise RagError('Lost table cell')
                return [{key: decode(child) for key, child in zip(keys, row)} for row in rows]
            return {key: decode(child) for key, child in item.items()}
        if isinstance(item, list):
            return [decode(child) for child in item]
        return item

    result = decode(packed['payload'])
    if digest(result) != meta.get('parent_sha256'):
        raise RagError('Changed delivery wire content')
    return result


def pack(view):
    """Pack a task view, returning an unchanged copy when nested markers conflict or packing grows it."""
    try:
        return _pack(view, 'task_view_encoding')
    except RagError as exc:
        if str(exc) == 'Reserved delivery wire marker in source':
            if isinstance(view, dict) and 'task_view_encoding' in view:
                raise RagError('Ambiguous task-view wrapper marker in source') from exc
            return copy.deepcopy(view)
        raise


def unpack(packed):
    """Restore a packed task view; retain the established task-view API."""
    return _unpack(packed, 'task_view_encoding')


def _project_fields(support, task_view=True, knowledge=True):
    result = copy.deepcopy(support)
    for field, marker, enabled in (('task_view', 'task_view_encoding', task_view),
                                   ('knowledge', 'knowledge_encoding', knowledge)):
        if enabled and field in support:
            try:
                result[field] = _pack(support[field], marker)
            except RagError as exc:
                if str(exc) != 'Reserved delivery wire marker in source':
                    raise
                if isinstance(support[field], dict) and marker in support[field]:
                    raise RagError('Ambiguous ' + field + ' wrapper marker in source') from exc
                result[field] = copy.deepcopy(support[field])
    if decode_support(result) != support:
        raise RagError('Lost support content on delivery')
    return result


def project(support):
    """Deterministically project repeated strings from task_view and knowledge."""
    return _project_fields(support)


def decode_support(projected):
    """Restore both projected fields and return an exact detached support object."""
    result = copy.deepcopy(projected)
    for field, marker in (('task_view', 'task_view_encoding'), ('knowledge', 'knowledge_encoding')):
        if field in projected:
            result[field] = _unpack(projected[field], marker)
    return result


def project_for_request(support, measure_request):
    """Choose the smallest complete request among raw, task-only, knowledge-only, and both.

    measure_request receives the whole support object in each candidate form. Its
    result must be a finite, nonnegative int or float. Callback exceptions propagate.
    Ties retain the earlier candidate, so raw wins ties and ordering is deterministic.
    """
    candidates = [copy.deepcopy(support)]
    candidates.append(_project_fields(support, task_view=True, knowledge=False))
    candidates.append(_project_fields(support, task_view=False, knowledge=True))
    candidates.append(_project_fields(support, task_view=True, knowledge=True))
    best, best_size = candidates[0], None
    import math
    for candidate in candidates:
        size = measure_request(candidate)
        if (isinstance(size, bool) or not isinstance(size, (int, float))
                or not math.isfinite(size) or size < 0):
            raise ValueError('measure_request must return a finite nonnegative number')
        if best_size is None or size < best_size:
            best, best_size = candidate, size
    return best
