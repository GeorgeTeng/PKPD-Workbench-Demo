"""Source-bound semantic stops. These are revision requests, never approvals."""
import re
import hashlib
import json
from datetime import datetime
from pathlib import Path
from .common import read_json, sha256

def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class ContextRevisionRequired(ValueError):
    """A valid review returned a revision decision; no success receipt is allowed."""


def _lean_findings(work, response, review):
    """Use the reviewed canonical records, without hiding findings behind a summary."""
    from ctxcomp.io import digest
    from ctxcomp.lean_compression import content
    state_path = work / 'state.json'
    state = read_json(state_path)
    record = state['accepted']['context']
    candidate_path = (work / record['file']).resolve()
    if not candidate_path.is_relative_to(work.resolve()) or not candidate_path.is_file():
        raise ValueError('Lean review candidate is missing or outside the run')
    accepted = read_json(candidate_path)
    if digest(accepted) != record['sha256'] or digest(content(accepted)) != response.get('candidate_sha256'):
        raise ValueError('Lean review candidate changed after review')
    evidence = {e['id']: e.get('citations', []) for e in accepted['evidence']}
    failed = [x for x in review.get('records', [])
              if x.get('faithfulness') != 'PRESERVED' or x.get('completeness') != 'PRESERVED']
    rows = []
    for fix in review.get('fixes', []):
        target = fix['target']
        ids = [] if target == 'NEW' else [target]
        details = [x for x in failed if x['id'] in ids]
        spans = list(fix.get('citations', []))
        for rid in ids:
            for span in evidence.get(rid, []):
                if span not in spans: spans.append(span)
        rows.append((ids, fix['reason'], details, spans,
                     target == 'NEW' or any(x.get('completeness') == 'MISSING' for x in details)))
    represented = {rid for row in rows for rid in row[0]}
    for item in failed:
        if item['id'] not in represented:
            rows.append(([item['id']], item['reason'], [item], evidence.get(item['id'], []),
                         item.get('completeness') == 'MISSING'))
    # Global checks and source coverage may expose omissions absent from the record list.
    for item in review.get('source_units', []) + review.get('checks', []):
        if item.get('verdict') != 'PRESERVED':
            rows.append((item.get('record_ids', []), item['reason'], [item], [], item.get('verdict') == 'MISSING'))
    reasons = {row[1] for row in rows}
    for message in review.get('critical_errors', []):
        if str(message) not in reasons:
            rows.append(([], str(message), [], [], False))
    if not rows: rows.append(([], 'Independent review requires attention.', [], [], False))
    issues = []
    for ids, reason, details, spans, missing in rows:
        issues.append({'id': f'ISSUE_{len(issues)+1:02d}', 'requirement_ids': ids,
            'category': 'EXTRACTION_OMISSION' if missing else 'REVIEW_FINDING',
            'title': 'Restore omitted proposal content' if missing else 'Correct the canonical record using its original source',
            'reason': reason, 'reviewer_details': details, 'source_evidence': spans,
            'what_to_change': 'Correct only the identified extraction issue and retain source conditions, numbers, uncertainty and provenance. Scientific changes require a revised proposal.',
            'downstream_effect': 'Compression remains blocked until the corrected candidate passes independent source review.'})
    return issues, [state_path, candidate_path]


def context_feedback(run, started_at=None):
    work = Path(run) / 'context_work'
    stopped_path = work / 'stopped.json'
    if not stopped_path.is_file(): return None
    stopped = read_json(stopped_path)
    if stopped.get('status') not in {'REVISE', 'NEEDS_REVIEW'}: return None
    if started_at and datetime.fromisoformat(stopped['at']) < datetime.fromisoformat(started_at): return None
    response_path = (work / stopped.get('response', '')).resolve()
    if not response_path.is_relative_to(work.resolve()) or not response_path.is_file():
        raise ValueError('Semantic review evidence is missing or outside the run')
    response = read_json(response_path)
    review = response.get('review', {})
    if review.get('decision') != stopped['status']:
        raise ValueError('Semantic stop does not match its recorded review')
    inputs_path = work / 'inputs.json'
    inputs = read_json(inputs_path)
    requirements_path = work / 'critical_requirements.json'
    requirements = read_json(requirements_path).get('items', []) if requirements_path.is_file() else []
    failed = [x for x in review.get('items', []) if x.get('verdict') != 'PRESERVED']
    errors = review.get('critical_errors', [])
    messages = errors or [x.get('reason', str(x)) for x in failed] or [stopped.get('reason', 'Review requires attention')]
    issues = []
    lean = (inputs.get('compression_profile') or {}).get('id') == 'LEAN_1.0'
    extra_paths = []
    prior_candidate = None
    if lean:
        issues, extra_paths = _lean_findings(work, response, review)
        from ctxcomp.lean_compression import content
        from ctxcomp.io import digest
        prior_candidate = content(read_json(extra_paths[-1]))
        if digest(prior_candidate) != response['candidate_sha256']:
            raise ValueError('Lean review candidate changed while reading feedback')
        messages = []
    for i, message in enumerate(messages):
        message = message if isinstance(message, str) else str(message)
        ids = list(dict.fromkeys(re.findall(r'\bR\d+\b', message)))
        if not ids and re.search(r'omit|missing', message, re.I):
            ids = [x['requirement_id'] for x in failed if x.get('verdict') == 'MISSING' and x.get('requirement_id')]
        related = [x for x in failed if x.get('requirement_id') in ids]
        missing = bool(related) and all(x.get('verdict') == 'MISSING' for x in related)
        evidence = []
        for item in requirements:
            if item['id'] not in ids: continue
            for component in item.get('components', []):
                for e in component.get('evidence', []):
                    if e not in evidence: evidence.append(e)
        issues.append({'id': f'ISSUE_{i+1:02d}', 'requirement_ids': ids,
            'category': 'EXTRACTION_OMISSION' if missing else 'REVIEW_FINDING',
            'title': 'Restore omitted proposal content' if missing else 'Clarify the source requirement or preserve its unresolved boundary',
            'reason': message, 'reviewer_details': related, 'source_evidence': evidence,
            'what_to_change': ('Restore the missing requirement using the original proposal and cite its source. Do not invent a threshold or value.' if missing else
                'Check the cited proposal passages. For extraction repair, retain all stated constraints and explicitly record any unresolved conflict. To change their scientific meaning or permissions, upload a revised proposal.'),
            'downstream_effect': 'Context remains blocked until a new extraction and semantic review pass.'})
    affected_units = {x.get('unit_id') for x in review.get('source_units', []) if x.get('verdict') != 'PRESERVED'}
    units = [x for x in inputs.get('source_units', []) if x.get('id', x.get('unit_id')) in affected_units]
    paths = [stopped_path, response_path, inputs_path] + extra_paths + ([requirements_path] if requirements_path.is_file() else [])
    refs = [{'path': str(p.resolve()), 'sha256': sha256(p)} for p in paths]
    return {'status': 'REVISION_REQUIRED', 'stage': stopped['stage'], 'decision': stopped['status'],
        'stopped_at': stopped.get('at'), 'summary': f'Context needs revision: {len(issues)} review finding(s). No downstream handoff was released.',
        'issues': issues, 'source_units': units, 'raw_review': review, 'evidence_refs': refs,
        **({'prior_candidate': prior_candidate} if prior_candidate is not None else {}),
        'signature': fingerprint(refs), 'scientific_release': False, 'can_approve': False,
        'available_actions': ['REPAIR_EXTRACTION', 'REPLACE_PROPOSAL']}
