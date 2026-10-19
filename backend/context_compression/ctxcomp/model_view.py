"""Compression rules 1.30.0 (CC002 model_payload COMPACT): what the model reads, without the copies.

Every requirements, review and context request carried each source's text twice, in sources and in source_units,
plus a source registry repeating the sources' names and roles, unit text hashes and, for reviews, the host's own
evidence audit: on 2026-10-09 the PMB requirements_review request was 1 MB, about 40 percent of it repeated. The
request, its hash and every host check stay as they are; only the copy sent to the model leaves out a source's text
when its units hold all of it, the registry when sources carry the same fields, hashes, and the requirements
evidence audit."""
from .rules import host_requirement

MODE = 'COMPACT'
INSTRUCTION = ('\nEach source\'s text is given once, in source_units (in order, with start_char and end_char); sources '
               'lists each source\'s name, role, locator and table_header_ids.')


def enabled(payload):
    # Other agents (including Project Rules) use a list of their own rules.
    # Only a compression rule pack can opt into this model-only projection.
    if not isinstance(payload.get('processing_rules'), dict):
        return False
    return host_requirement(payload, 'CC002').get('model_payload') == MODE


def view(request):
    """The request as sent to the model; the host keeps and checks the full request."""
    payload = request.get('payload') if isinstance(request, dict) else None
    if not isinstance(payload, dict) or not enabled(payload):
        return request
    compact = {k: v for k, v in payload.items() if k != 'requirements_evidence_audit'}
    units = payload.get('source_units') or []
    if units:
        by_source = {}
        for unit in units:
            by_source.setdefault(unit['source_id'], []).append(unit)
        def covered(source):
            parts = sorted(by_source.get(source['id'], []), key=lambda u: u['start_char'])
            return bool(parts) and ''.join(u['text'] for u in parts) == source.get('text')
        compact['source_units'] = [{k: v for k, v in u.items() if k != 'text_sha256'} for u in units]
        if isinstance(payload.get('sources'), list):
            compact['sources'] = [{k: v for k, v in s.items()
                                   if k != 'original_sha256' and not (k == 'text' and covered(s))}
                                  for s in payload['sources']]
            compact.pop('source_registry', None)
    return {**request, 'payload': compact}
