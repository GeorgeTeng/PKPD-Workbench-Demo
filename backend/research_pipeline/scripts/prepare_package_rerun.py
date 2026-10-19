"""Refresh a portable B1 handoff from a new ZIP with an unchanged proposal.

The reviewed scientific context is reused only after exact proposal SHA equality.
Benchmark bytes are retained and hashed, never parsed or sent to model inputs.
"""
import argparse
import copy
import os
from pathlib import Path, PurePosixPath

from ctxcomp.handoff import verify_main
from ctxcomp.intake import inputs_from, parse_file
from research_pipeline.common import read_json, write_json, sha256, utcnow
from research_pipeline.source_preparation import prepare_sources


def ref(path):
    return {'path': str(Path(path).resolve()), 'sha256': sha256(path)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package', type=Path, required=True)
    p.add_argument('--previous-main', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    audit = {'status': 'RUNNING', 'started_at': utcnow(), 'pid': os.getpid(),
             'script': ref(__file__), 'package': ref(a.package),
             'previous_main': ref(a.previous_main), 'model_calls': 0}
    write_json(out / 'execution.json', audit)
    try:
        previous = read_json(a.previous_main)
        verify_main(previous)
        expected = {PurePosixPath(f['name']).name: f for f in previous['data']['files']}
        files, changes = [], []
        seen = set()
        for name, content, origin in inputs_from(package=a.package):
            basename = PurePosixPath(name).name
            if basename not in expected or basename in seen:
                raise ValueError('New or duplicate attachment needs explicit routing: ' + name)
            seen.add(basename)
            old = expected[basename]
            dest = out / 'attachments' / (old['id'] + PurePosixPath(name).suffix)
            dest.parent.mkdir(exist_ok=True)
            dest.write_bytes(content)
            checksum = sha256(dest)
            if old['role'] == 'PROPOSAL' and checksum != old['sha256']:
                raise ValueError('Proposal changed: fresh context compression required')
            access = 'BYTES_HASHED_ONLY_REFERENCE_CONTENT_NOT_PARSED'
            if old['role'] != 'REFERENCE_ONLY':
                parsed = parse_file(dest)
                write_json(out / 'snapshots' / (old['id'] + '.json'), parsed)
                access = 'PARSED_COMPLETE'
            files.append({**old, 'name': name, 'path': str(dest), 'sha256': checksum})
            changes.append({'id': old['id'], 'name': name, 'origin': origin,
                            'previous_sha256': old['sha256'], 'sha256': checksum,
                            'changed': old['sha256'] != checksum, 'content_access': access})
        if seen != set(expected):
            raise ValueError('Attachments missing: ' + repr(set(expected) - seen))
        current = copy.deepcopy(previous)
        current['data']['files'] = files
        verify_main(current)
        write_json(out / 'B1/main.json', current)
        write_json(out / 'package_changes.json', {'files': changes,
            'proposal_context': 'REUSED_REVIEWED_CONTEXT_EXACT_PROPOSAL_SHA_MATCH',
            'reference_read_status_note': 'B1 READ_COMPLETE describes complete byte intake; benchmark content was not parsed.',
            'previous_context': ref(a.previous_main)})
        result = prepare_sources(out / 'B1/main.json', out / 'source_preparation')
        if result['status'] == 'FAILED':
            raise RuntimeError('Source preparation failed: ' + repr(result['errors']))
        audit.update(status='SOURCES_PREPARED', tables=len(result['tables']),
                     main=ref(out / 'B1/main.json'))
    except Exception as exc:
        audit.update(status='STOPPED_ON_ERROR', error=str(exc))
        raise
    finally:
        audit['finished_at'] = utcnow()
        write_json(out / 'execution.json', audit)
    print(audit['status'], 'tables=' + str(audit['tables']), out)


if __name__ == '__main__':
    main()
