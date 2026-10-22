"""Answers shared between runs: a stage request that an earlier run already sent to the same executor and
accepted is answered from that run instead of calling the model again.

The key is the request hash and the executor, so any change to sources, rules, code that builds the request,
earlier accepted stages or the model gives a different key. A reused answer still goes through every check
of accept(); only accepted answers are stored, never rejected or REVISE ones."""
from pathlib import Path

from .io import read_json, write_json, digest


def key(stage, request, executor):
    return digest({'stage': stage, 'request_sha256': request['request_sha256'], 'executor': executor})


def lookup(root, stage, request, executor):
    """The stored answer and its record for this exact request and executor, or None."""
    if root is None or not executor:
        return None
    path = Path(root) / stage / (key(stage, request, executor) + '.json')
    if not path.is_file():
        return None
    record = read_json(path)
    response = record.get('response')
    if (record.get('key') != path.stem or record.get('executor') != executor
            or not isinstance(response, dict) or digest(response) != record.get('response_sha256')
            or response.get('request_sha256') != request['request_sha256']):
        return None  # A damaged or foreign entry is ignored; the stage calls the model as usual.
    return response, {k: record[k] for k in ('key', 'source_run', 'stored_at', 'executor')}


def store(root, stage, request, executor, response, run, at):
    if root is None or not executor:
        return
    name = key(stage, request, executor)
    write_json(Path(root) / stage / (name + '.json'), {'key': name, 'stage': stage, 'executor': executor,
        'request_sha256': request['request_sha256'], 'response_sha256': digest(response), 'response': response,
        'source_run': str(Path(run).resolve()), 'stored_at': at})
