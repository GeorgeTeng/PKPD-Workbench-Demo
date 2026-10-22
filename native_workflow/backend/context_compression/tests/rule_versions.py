"""Rule packs as runs froze them before a version's switches, for tests that keep earlier behaviour."""
import copy

import pytest

from ctxcomp import engine
from ctxcomp.rules import load_rules

SWITCHES_1_29 = ('quote_matching', 'unconfirmed_citations', 'binding_locations', 'unconfirmed_bindings', 'automatic_revisions')
SWITCHES_1_30 = ('model_payload', 'unknown_review_records')


def without(keys, pack=None):
    earlier = copy.deepcopy(pack or load_rules())
    switches = next(r for r in earlier['rules'] if r['id'] == 'CC002')['host_requirement']
    for key in keys:
        switches.pop(key, None)
    return earlier


def before_1_31(pack=None):
    """The current pack with the sequential requirements parts and the single requirements review of rules 1.30.0."""
    earlier = copy.deepcopy(pack or load_rules())
    switches = next(r for r in earlier['rules'] if r['id'] == 'CC002')['host_requirement']
    switches['requirements_parts'] = 'PROPOSAL_THEN_SUPPORTING'
    switches.pop('review_parts', None)
    return earlier


def before_1_30(pack=None):
    """The current pack without the CC002 changes of compression rules 1.30.0 and later."""
    return without(SWITCHES_1_30, before_1_31(pack))


def before_1_29(pack=None):
    """The current pack without the CC002 changes of compression rules 1.29.0 and later."""
    return without(SWITCHES_1_29 + SWITCHES_1_30, before_1_31(pack))


def freeze(monkeypatch, pack):
    """New runs freeze this pack."""
    monkeypatch.setattr(engine, 'load_rules', lambda: copy.deepcopy(pack))


def cc002(**switches):
    """processing_rules carrying only these CC002 switches, for payloads built by hand."""
    return {'rules': [{'id': 'CC002', 'host_requirement': switches}]}


@pytest.fixture
def rules_1_30(monkeypatch):
    """New runs freeze the 1.30.0 pack: sequential requirements parts and one requirements review call."""
    freeze(monkeypatch, before_1_31())
