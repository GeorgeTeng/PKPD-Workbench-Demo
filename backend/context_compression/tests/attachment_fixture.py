"""Authored empty search decisions for tests of unrelated downstream gates.

These are explicit mocked responses, not evidence of semantic completeness.
"""
from ctxcomp.engine import prepare, accept


def accept_empty_search(run):
    for stage, field in [('attachment_plan', 'questions'), ('attachment_evidence', 'answers')]:
        request = prepare(run, stage)
        accept(run, stage, {'request_sha256': request['request_sha256'], field: []})
