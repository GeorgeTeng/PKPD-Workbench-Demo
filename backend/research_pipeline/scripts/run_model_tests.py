"""Run model/API regressions in a fresh, preserved workspace output directory.

Creates pytest's parent directory before fixture initialization. Never reuses a
basetemp directory, because pytest may recursively remove an existing one.
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from research_pipeline.common import sha256, write_json, utcnow
from research_pipeline.model_catalog import load_catalog


ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--catalog', type=Path, help='Explicit candidate CSV to snapshot and use in catalog integration tests')
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = (args.out or ROOT.parent / 'outputs' / f'Model_Debug_{stamp}').resolve()
    allowed = (ROOT.parent / 'outputs').resolve()
    if output == allowed or not output.is_relative_to(allowed):
        raise ValueError('Test output must be a new child directory inside workspace/outputs.')
    output.mkdir(parents=True, exist_ok=False)
    base = (output / 'pytest_tmp').resolve()
    if not base.is_relative_to(output) or base.exists():
        raise ValueError('Refusing an existing or out-of-run pytest temporary directory.')
    junit = output / 'tests.junit.xml'
    command = [sys.executable, '-I', '-X', 'utf8', '-m', 'pytest',
               'research_pipeline/tests',
               '-q', '-x', '--basetemp', str(base), '--junitxml', str(junit)]
    record = {'status': 'RUNNING', 'started_at': utcnow(), 'launcher_pid': os.getpid(),
              'command': command, 'cwd': str(ROOT), 'script_sha256': sha256(__file__),
              'fresh_basetemp': str(base), 'first_error_stops_tests': True,
              'previous_failed_logs_preserved': True,
              'scope': 'Software regression tests, including synthetic R fits and the existing rat-data regression; not a three-species or PMB index project run.'}
    write_json(output / 'execution.json', record)
    env = os.environ.copy()
    if args.catalog:
        catalog = load_catalog(args.catalog)
        snapshot = output/'inputs/model_library_catalog.csv'
        snapshot.parent.mkdir()
        snapshot.write_bytes(args.catalog.read_bytes())
        if sha256(snapshot) != catalog['source']['sha256']:
            raise ValueError('Catalog changed during snapshot')
        write_json(output/'model_catalog.json',catalog)
        env['MODEL_CATALOG_TEST_PATH'] = str(snapshot)
        record['model_catalog'] = {'original':catalog['source'],'snapshot':str(snapshot),'candidates':len(catalog['models'])}
        write_json(output/'execution.json',record)
    print(f'Test output: {output}', flush=True)
    with (output / 'tests.stdout.log').open('w', encoding='utf-8') as stdout, \
         (output / 'tests.stderr.log').open('w', encoding='utf-8') as stderr:
        process = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr, env=env,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        record['pytest_pid'] = process.pid
        write_json(output / 'execution.json', record)
        code = process.wait()
    record.update(status='PASSED' if code == 0 else 'STOPPED_ON_ERROR',
                  exit_code=code, finished_at=utcnow())
    if junit.exists():
        suites = ET.parse(junit).findall('.//testsuite')
        record['tests'] = {key: sum(int(s.get(key, 0)) for s in suites)
                           for key in ('tests', 'errors', 'failures', 'skipped')}
        record['junit_sha256'] = sha256(junit)
    write_json(output / 'execution.json', record)
    print((output / 'tests.stdout.log').read_text(encoding='utf-8'))
    print((output / 'tests.stderr.log').read_text(encoding='utf-8'))
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
