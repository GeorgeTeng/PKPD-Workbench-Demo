"""Narrow technical-demo deferral; never changes the independent review verdict."""
import os
from pathlib import Path
from .io import read_json, write_json, digest
from .intake import file_hash

PROFILE = 'DEMO_CONTEXT_CANONICAL_PLACEMENT_1.0'
CHECK = 'canonical_placement_no_duplicate_gaps'


def eligible(review):
    if os.getenv('PKPD_DEMO_LIGHTWEIGHT_DATA') != '1':
        return False
    failed = [c for c in review['checks'] if c['verdict'] != 'PRESERVED']
    known = {r['id'] for r in review['records']}
    return (review['decision'] == 'REVISE' and not review['critical_errors']
            and bool(review['records']) and bool(review['source_units'])
            and all(r[k] == 'PRESERVED' for r in review['records'] for k in ('faithfulness', 'completeness'))
            and all(u['verdict'] == 'PRESERVED' for u in review['source_units'])
            and len(failed) == 1 and failed[0]['id'] == CHECK and failed[0]['verdict'] == 'ALTERED'
            and bool(review['fixes']) and all(f['target'] in known for f in review['fixes']))


def receipt(response, review_path):
    if not eligible(response['review']):
        raise ValueError('Context review is not eligible for canonical-placement demo deferral.')
    review = response['review']
    findings = []
    for item in [c for c in review['checks'] if c['verdict'] != 'PRESERVED'] + review['fixes']:
        findings.append({'code': 'CONTEXT_CANONICAL_PLACEMENT_DEFERRED',
            'affected_id': item.get('target', item['id']), 'reason': item['reason'],
            'needed_material': 'Resolve the retained Context review finding before scientific analysis.',
            'required_by': 'BEFORE_EDA', 'severity': 'HUMAN_REVIEW'})
    return {'profile': PROFILE, 'scope': 'THROUGH_DATA_TECHNICAL_DEMO_ONLY',
        'original_review_decision': review['decision'], 'candidate_sha256': response['candidate_sha256'],
        'review_ref': {'path': str(Path(review_path).resolve()), 'sha256': file_hash(review_path)},
        'review_sha256': digest(response), 'candidate_changed': False,
        'independent_review_passed': False, 'scientific_release': False, 'findings': findings}


def publish(run, response, review_path):
    path = Path(run)/'audit/demo_context_review.json'
    write_json(path, receipt(response, review_path))
    return {'path': str(path.resolve()), 'sha256': file_hash(path)}


def verify(reference):
    path = Path(reference['path'])
    if file_hash(path) != reference['sha256']:
        raise ValueError('Demo Context review receipt changed.')
    value = read_json(path)
    ref = value['review_ref']
    if file_hash(ref['path']) != ref['sha256']:
        raise ValueError('Independent Context review changed.')
    response = read_json(ref['path'])
    if value != receipt(response, ref['path']):
        raise ValueError('Demo Context review deferral changed.')
    return value
