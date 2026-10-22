"""Subprocess isolation is intentional: the source overlay is process scoped."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from research_pipeline import data_frozen_runtime as frozen

ROOT = Path(frozen.__file__).resolve().parents[3]
SNAPSHOT = ROOT/'outputs/Data_Preparation_Flow_20261013/before/backend/research_pipeline/research_pipeline/data_agents.py'


@pytest.fixture
def resolution(tmp_path):
    if not SNAPSHOT.exists():
        pytest.skip('Exact historical local snapshot is unavailable')
    build = tmp_path/'build.json'
    original = Path(frozen.__file__).with_name('data_agents.py')
    build.write_text(json.dumps({'bindings': {'invocation_code': {
        'path': str(original), 'sha256': frozen.EXPECTED_SHA256}}}), encoding='utf-8')
    path = tmp_path/'resolution.json'
    frozen.register(build, SNAPSHOT, path)
    return path


def run_script(script, resolution):
    return subprocess.run([sys.executable, '-I', '-X', 'utf8', '-c', script, str(resolution)],
                          text=True, capture_output=True, check=False)


def test_real_public_and_private_loaders_execute_exact_snapshot(resolution):
    script = '''
import sys, hashlib, json
from pathlib import Path
from research_pipeline.data_frozen_runtime import install, EXPECTED_SHA256
p=Path(sys.argv[1]); value=json.loads(p.read_text(encoding='utf-8'))
original=Path(value['original_binding']['path'])
before=hashlib.sha256(open(original,'rb').read()).hexdigest()
install(p)
from research_pipeline import data_agents as d, data_requirement_plan_v4 as plan
from research_pipeline.adequacy import file_ref, check_ref
private=plan.sf.private_module()
assert 'DH-metadata' in d.CALL_AGENT and 'preparation_checks' not in d.__dict__
assert 'DH-metadata' in private.CALL_AGENT and 'preparation_checks' not in private.__dict__
assert private.__frozen_source_ref__==d.__frozen_source_ref__==value['snapshot']
assert d.__spec__.origin==value['snapshot']['path']
assert file_ref(original)==value['original_binding']
check_ref(value['original_binding'])
assert hashlib.sha256(original.read_bytes()).hexdigest()==EXPECTED_SHA256
assert hashlib.sha256(open(original,'rb').read()).hexdigest()==before
try: original.write_text('do not write',encoding='utf-8')
except ValueError: pass
else: raise AssertionError('overlay source was writable')
other=p.parent/'unrelated.txt';other.write_text('a',encoding='utf-8')
ref=file_ref(other);other.write_text('b',encoding='utf-8')
try: check_ref(ref)
except ValueError: pass
else: raise AssertionError('unrelated hash validation was bypassed')
assert install(p)==d.__frozen_resolution_ref__
print('EXACT_PUBLIC_PRIVATE_SNAPSHOT_AND_OTHER_HASH_CHECKS_PASS')
'''
    result = run_script(script, resolution)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'EXACT_PUBLIC_PRIVATE' in result.stdout


def test_install_rejects_already_imported_live_module(resolution):
    result = run_script('''
import sys
from research_pipeline import data_agents
from research_pipeline.data_frozen_runtime import install
try: install(sys.argv[1])
except ValueError as e: assert 'fresh process' in str(e)
else: raise AssertionError('mixed live and frozen code permitted')
''', resolution)
    assert result.returncode == 0, result.stdout + result.stderr


def test_changed_snapshot_rejected_without_installing_overlay(resolution, tmp_path):
    value = json.loads(resolution.read_text(encoding='utf-8'))
    snapshot = tmp_path/'changed.py'
    snapshot.write_text('changed', encoding='utf-8')
    value['snapshot']['path'] = str(snapshot)
    resolution.write_text(json.dumps(value), encoding='utf-8')
    result = run_script('''
import sys
from research_pipeline.data_frozen_runtime import install
try: install(sys.argv[1])
except ValueError: pass
else: raise AssertionError('changed snapshot accepted')
''', resolution)
    assert result.returncode == 0, result.stdout + result.stderr
