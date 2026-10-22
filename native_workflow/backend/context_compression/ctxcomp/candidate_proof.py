"""The proof a host-built requirements candidate leaves for acceptance: the parts merge (1.25.0) and the revision
patch (1.26.0) both record their artifacts, the candidate they produced and, after a binding repair, the repaired
candidate that replaced it."""
from pathlib import Path

from .io import digest, read_json, write_json


def record_repair(run, proof_file, name, merged, repaired, repair_dir):
    """The binding repair replaced the host's candidate; keep the link for verify."""
    run = Path(run); proof = read_json(run/proof_file)
    if proof['merged_sha256'] != digest(merged):
        raise ValueError(f'{name} proof belongs to another candidate')
    proof['accepted_candidate'] = {'sha256': digest(repaired),
        'binding_repair_result': (Path(repair_dir)/'result.json').relative_to(run).as_posix()}
    write_json(run/proof_file, proof)


def produced(run, proof_file, base, response):
    """Whether the host built this response for this request (its candidate or that candidate's binding repair).
    A whole inventory submitted another way is accepted on its own checks."""
    path = Path(run)/proof_file
    if not path.is_file():
        return False
    proof = read_json(path)
    return (proof.get('parent_request_sha256') == base['request_sha256']
            and digest(response) in {proof.get('merged_sha256'), (proof.get('accepted_candidate') or {}).get('sha256')})


def artifact(run, record, kind, name):
    """A recorded request or response, unchanged and inside the run."""
    run = Path(run); path = (run/record[kind]).resolve()
    if not path.is_relative_to(run.resolve()): raise ValueError(f'{name} artifact outside run')
    value = read_json(path)
    if digest(value) != record[kind + '_sha256']: raise ValueError(f'{name} artifact changed')
    return value


def accepted(run, proof, response, candidate):
    """The response is the recomputed candidate, or the binding repair recorded for it. Returns the proof digest."""
    if digest(response) == proof['merged_sha256']:
        return digest(proof)
    repaired = proof.get('accepted_candidate') or {}
    if repaired.get('sha256') != digest(response):
        raise ValueError(f'Requirements response is neither {candidate} nor its recorded binding repair')
    result = read_json(Path(run)/repaired['binding_repair_result'])
    if result.get('original_sha256') != proof['merged_sha256'] or result.get('corrected_sha256') != digest(response):
        raise ValueError(f'Requirements binding repair record does not link {candidate} to this response')
    return digest(proof)
