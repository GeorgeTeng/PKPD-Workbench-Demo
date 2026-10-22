"""Shared authored review fixtures; these do not measure semantic model accuracy."""
from ctxcomp.engine import prepare
from ctxcomp import split_review as split
from test_retention import reference_run
from test_split_review import split_run, authored_response


def branch_case(fixture, branch):
    run, original = fixture
    base = prepare(run, 'context_review')
    prior = None
    if branch == split.GLOBAL:
        prior = {b: authored_response(split.request_for(base, b), original)
                 for b in (split.FAITH, split.COMPLETE)}
    request = split.request_for(base, branch, prior)
    return base, request, authored_response(request, original)


def validate(case, branch):
    base, request, response = case
    split.validate_branch(base, request, response, branch)
