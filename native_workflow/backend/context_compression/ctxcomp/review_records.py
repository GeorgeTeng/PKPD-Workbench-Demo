"""Compression rules 1.30.0 (CC002 unknown_review_records SET_ASIDE): a requirements_review record the host cannot
place no longer stops the run.

On 2026-10-09 the PMB review returned 180 item records for 179 IDs: it added a PRESERVED note under an ID of its own
("SA34_DUP_NOTE"), and the run stopped before its REVISE could be revised. For runs that opt in, the reviewer is told
to give exactly one record per ID, and the host moves a record whose ID the request does not have into
review.limitations, with its verdict and reason, and merges exact repeats of a record. Both are listed in
audit/unconfirmed_evidence.json. A missing ID, repeats with different verdicts, and a record outside the request that
reports a defect while the review says PASS still stop the run."""
import copy
from pathlib import Path

from .io import digest
from .rules import host_requirement
from .unconfirmed import record

MODE = 'SET_ASIDE'
INSTRUCTION = ('\nGive review.items exactly one record for each inventory item and potential question ID and no others, '
               'and review.source_units exactly one record for each unit in review_source_unit_ids. A note about '
               'several records, such as a duplicate pair, goes in the reason of each record it concerns or in limitations.')


def enabled(source):
    return host_requirement(source, 'CC002').get('unknown_review_records') == MODE


def set_aside(run, request, response):
    """The response with unknown records moved to limitations and exact repeats merged; the submission is unchanged."""
    from .scientific import item_ids
    payload = request['payload']
    expected = {'items': ('requirement_id', set(item_ids(payload['requirements']))),
                'source_units': ('unit_id', set(payload.get('review_source_unit_ids')
                                                or [u['id'] for u in payload['source_units']]))}
    fixed = copy.deepcopy(response); review = fixed['review']; entries = []
    for collection, (key, ids) in expected.items():
        kept, seen = [], {}
        for rec in review[collection]:
            rid = rec[key]
            if rid not in ids:
                if review['decision'] == 'PASS' and rec['verdict'] != 'PRESERVED':
                    raise ValueError(f'PASS contradicts a review record outside this request: {rid} ({rec["verdict"]})')
                review['limitations'].append(f'Set aside by the host: review.{collection} gave a {rec["verdict"]} '
                                             f'record for {rid}, which is not an ID of this request. {rec["reason"]}')
                entries.append({'collection': collection, 'id': rid, 'verdict': rec['verdict'], 'reason': rec['reason'],
                                'action': 'MOVED_TO_LIMITATIONS'})
                continue
            first = seen.get(rid)
            if first is not None and {k: v for k, v in first.items() if k != 'reason'} == \
                    {k: v for k, v in rec.items() if k != 'reason'}:
                if rec['reason'] != first['reason']:
                    first['reason'] += ' ' + rec['reason']
                entries.append({'collection': collection, 'id': rid, 'verdict': rec['verdict'], 'reason': rec['reason'],
                                'action': 'MERGED_REPEAT'})
                continue
            seen.setdefault(rid, rec); kept.append(rec)
        review[collection] = kept
    audit = Path(run)/'audit'
    if entries or (audit/'unconfirmed_evidence.json').is_file():
        record(audit, 'review_records', request['request_sha256'],
               [{**e, 'submitted_sha256': digest(response)} for e in entries])
    return fixed
