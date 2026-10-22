"""Compression rules 1.29.0: evidence the host cannot confirm is removed and the run goes on.

Each removal is listed in the run's audit/unconfirmed_evidence.json for a person to check. Nothing removed here is
treated as confirmed, and nothing is added in its place: a finding that lost a citation is no longer FOUND, and a
dropped value binding leaves the item's statement without that value."""
from pathlib import Path

from .io import read_json, write_json
from .rules import host_requirement

FILE = 'unconfirmed_evidence.json'
CITATIONS = 'REMOVE_AND_MARK'
BINDINGS = 'DROP'


def citations_marked(source):
    """CC002 unconfirmed_citations: a citation no review can confirm is removed and its finding marked."""
    return host_requirement(source, 'CC002').get('unconfirmed_citations') == CITATIONS


def bindings_dropped(source):
    """CC002 unconfirmed_bindings: a value binding that stays unconfirmed after its repair is dropped."""
    return host_requirement(source, 'CC002').get('unconfirmed_bindings') == BINDINGS


def record(audit, kind, request_sha256, entries):
    """Replace this request's entries of kind ('citations', 'bindings' or, from 1.30.0, 'review_records') in
    audit/unconfirmed_evidence.json."""
    path = Path(audit)/FILE
    data = read_json(path) if path.is_file() else {'schema_version': '1.0', 'citations': [], 'bindings': [],
        'description': 'Evidence the host could not confirm, and review records it could not place, set aside instead '
                       'of stopping the run (compression rules 1.29.0 and later). Nothing set aside is treated as '
                       'confirmed; check it against the source.'}
    data[kind] = [e for e in data.get(kind, []) if e['request_sha256'] != request_sha256] + [
        {**e, 'request_sha256': request_sha256} for e in entries]
    write_json(path, data)
    return data
