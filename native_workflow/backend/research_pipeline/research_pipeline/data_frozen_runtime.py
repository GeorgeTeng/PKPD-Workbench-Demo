"""Process-local, read-only resolution of explicitly frozen Data runtime bindings.

Install before importing the pipeline in a fresh process. Existing artifacts keep
their logical path and expected hash; actual hashing, reads and Python execution
all use the recorded, verified snapshot. Every other file is untouched.
"""
import hashlib
import importlib
import importlib.machinery
import json
import os
import sys
from pathlib import Path

EXPECTED_SHA256 = 'b05474d466a366f974866532cff07899729f851fb822f4f0df57a9aae7094d20'
RULE_SHA256 = {
    'dp_preparation.json': '0f4c18e3f47f2d27711e184e8f553b78592c1fcf9aafa838be2ea8e2dc72939d',
    'dh_handoff.json': '1b823022f92007931b7e0351795146cd5def15c9f8abae8b1bf3ba4891246bb6'}
_INSTALLED = None


def _key(path):
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _bytes(path):
    # Built-in open intentionally observes the real disk, outside the overlay.
    with open(path, 'rb') as stream:
        return stream.read()


def _ref(path):
    return {'path': str(Path(path).resolve()), 'sha256': hashlib.sha256(_bytes(path)).hexdigest()}


def _check(ref):
    if _ref(ref['path']) != ref:
        raise ValueError('FROZEN_RUNTIME: resolution reference changed: ' + ref['path'])


def _read(path):
    return json.loads(_bytes(path).decode('utf-8-sig'))


def register(build_path, snapshot_path, resolution_path, *, rule_snapshots=None):
    """Append one exact resolution; never change original build/source/receipts."""
    build = _read(build_path)
    original = build['bindings']['invocation_code']
    expected_path = Path(__file__).with_name('data_agents.py')
    if _key(original['path']) != _key(expected_path) or original['sha256'] != EXPECTED_SHA256:
        raise ValueError('FROZEN_RUNTIME: only the explicitly identified data_agents version may be resolved')
    snapshot = _ref(snapshot_path)
    if snapshot['sha256'] != original['sha256'] or _key(snapshot['path']) == _key(original['path']):
        raise ValueError('FROZEN_RUNTIME: snapshot does not exactly reproduce the bound source bytes')
    resolution = {'version': 'EXACT_FROZEN_INVOCATION_1.0', 'original_binding': original,
        'snapshot': snapshot, 'bound_build': _ref(build_path), 'resolver_code': _ref(__file__),
        'external_current_observed': _ref(original['path']),
        'scope': 'THIS_PROCESS_ONLY; EXACT_SINGLE_SOURCE_PATH; ALL_OTHER_REFERENCES_NORMAL',
        'execution': 'PATH_READS_AND_SOURCEFILELOADER_USE_VERIFIED_SNAPSHOT; NO_HASH_CHECK_SKIPPED',
        'original_files_modified': False}
    resolution_path = Path(resolution_path)
    resolution_path.parent.mkdir(parents=True, exist_ok=True)
    if rule_snapshots:
        if set(rule_snapshots) != set(RULE_SHA256):
            raise ValueError('FROZEN_RUNTIME: only the two identified DR baseline execution rules may be resolved')
        _check(build['bindings']['plan'])
        plan = _read(build['bindings']['plan']['path'])
        baseline_ref = plan['bindings']['input_baseline']
        _check(baseline_ref)
        refs = []
        def walk(value):
            if isinstance(value, dict):
                if 'path' in value and 'sha256' in value:
                    refs.append(value)
                else:
                    for item in value.values(): walk(item)
            elif isinstance(value, list):
                for item in value: walk(item)
        walk(_read(baseline_ref['path']))
        resolution['additional_resolutions'] = []
        for name, expected in RULE_SHA256.items():
            path = Path(__file__).resolve().parents[2]/'rules/data'/name
            original_rule = {'path': str(path), 'sha256': expected}
            if original_rule not in refs:
                raise ValueError('FROZEN_RUNTIME: execution rule is not bound by the original DR baseline')
            snapshot_rule = _ref(rule_snapshots[name])
            if snapshot_rule['sha256'] != expected:
                raise ValueError('FROZEN_RUNTIME: execution-rule snapshot does not match its exact baseline hash')
            rule_resolution = {'version': 'EXACT_FROZEN_EXECUTION_RULE_1.0',
                'original_binding': original_rule, 'snapshot': snapshot_rule,
                'baseline': baseline_ref, 'external_current_observed': _ref(path),
                'reason': 'Restore only the exact execution Rule already frozen by the original DR; no new Rule substituted.'}
            import difflib
            rule_resolution['current_diff'] = list(difflib.unified_diff(
                _bytes(snapshot_rule['path']).decode('utf-8-sig').splitlines(),
                _bytes(path).decode('utf-8-sig').splitlines(), fromfile='frozen_original', tofile='external_current'))
            rule_path = resolution_path.with_name(name.replace('.json', '_resolution.json'))
            with rule_path.open('x', encoding='utf-8') as stream:
                json.dump(rule_resolution, stream, ensure_ascii=False, indent=2)
            resolution['additional_resolutions'].append(_ref(rule_path))
    with resolution_path.open('x', encoding='utf-8') as stream:
        json.dump(resolution, stream, ensure_ascii=False, indent=2)
    return _ref(resolution_path)


def install(resolution_path):
    """Load the frozen module and scope every alias narrowly to its logical path."""
    global _INSTALLED
    resolution_ref = _ref(resolution_path)
    if _INSTALLED is not None:
        if _INSTALLED != resolution_ref:
            raise ValueError('FROZEN_RUNTIME: a different resolution is already active')
        return _INSTALLED
    resolution = _read(resolution_path)
    original, snapshot = resolution['original_binding'], resolution['snapshot']
    logical_path = _key(Path(__file__).with_name('data_agents.py'))
    if _key(original['path']) != logical_path or original['sha256'] != EXPECTED_SHA256:
        raise ValueError('FROZEN_RUNTIME: unsupported logical source identity')
    for key in ('snapshot', 'bound_build', 'resolver_code'):
        _check(resolution[key])
    if resolution['resolver_code'] != _ref(__file__) or snapshot['sha256'] != original['sha256']:
        raise ValueError('FROZEN_RUNTIME: resolver or snapshot identity mismatch')
    if _read(resolution['bound_build']['path'])['bindings']['invocation_code'] != original:
        raise ValueError('FROZEN_RUNTIME: resolution does not match the bound build')
    bindings = {logical_path: (original, snapshot)}
    for extra_ref in resolution.get('additional_resolutions', []):
        _check(extra_ref)
        extra = _read(extra_ref['path'])
        rule, saved = extra['original_binding'], extra['snapshot']
        name = Path(rule['path']).name
        rule_path = Path(__file__).resolve().parents[2]/'rules/data'/name
        if (name not in RULE_SHA256 or _key(rule['path']) != _key(rule_path) or
                rule['sha256'] != RULE_SHA256[name] or saved['sha256'] != rule['sha256']):
            raise ValueError('FROZEN_RUNTIME: unexpected additional binding')
        _check(saved)
        _check(extra['baseline'])
        if _key(rule_path) in bindings:
            raise ValueError('FROZEN_RUNTIME: duplicate logical binding')
        bindings[_key(rule_path)] = (rule, saved)
    if any(_key(module.__file__) == logical_path for module in tuple(sys.modules.values())
           if isinstance(getattr(module, '__file__', None), str)):
        raise ValueError('FROZEN_RUNTIME: install before data_agents import in a fresh process')

    def frozen_bytes(key=logical_path):
        _check(resolution_ref)
        _check(resolution['resolver_code'])
        for ref in resolution.get('additional_resolutions', []): _check(ref)
        expected, saved = bindings[key]
        value = _bytes(saved['path'])
        if hashlib.sha256(value).hexdigest() != expected['sha256']:
            raise ValueError('FROZEN_RUNTIME: frozen source bytes changed')
        return value

    original_open = Path.open
    original_get_code = importlib.machinery.SourceFileLoader.get_code
    original_get_data = importlib.machinery.SourceFileLoader.get_data
    original_exec = importlib.machinery.SourceFileLoader.exec_module

    def path_open(path, mode='r', *args, **kwargs):
        key = _key(path)
        if key not in bindings:
            return original_open(path, mode, *args, **kwargs)
        if any(flag in mode for flag in 'wax+'):
            raise ValueError('FROZEN_RUNTIME: logical frozen source is read-only')
        frozen_bytes(key)
        return original_open(Path(bindings[key][1]['path']), mode, *args, **kwargs)

    def get_code(loader, fullname):
        if _key(loader.path) == logical_path:
            # Never consume a current-checkout .pyc for this frozen source.
            return compile(frozen_bytes(), original['path'], 'exec', dont_inherit=True)
        return original_get_code(loader, fullname)

    def get_data(loader, path):
        if _key(path) == logical_path:
            return frozen_bytes()
        return original_get_data(loader, path)

    def exec_module(loader, module):
        original_exec(loader, module)
        if _key(loader.path) == logical_path:
            module.__frozen_source_ref__ = dict(snapshot)
            module.__frozen_resolution_ref__ = dict(resolution_ref)
            module.__spec__.origin = snapshot['path']

    Path.open = path_open
    importlib.machinery.SourceFileLoader.get_code = get_code
    importlib.machinery.SourceFileLoader.get_data = get_data
    importlib.machinery.SourceFileLoader.exec_module = exec_module
    try:
        module = importlib.import_module('research_pipeline.data_agents')
        if module.__frozen_source_ref__ != snapshot or _key(module.__file__) != logical_path:
            raise ValueError('FROZEN_RUNTIME: frozen execution identity was not installed')
    except BaseException:
        Path.open = original_open
        importlib.machinery.SourceFileLoader.get_code = original_get_code
        importlib.machinery.SourceFileLoader.get_data = original_get_data
        importlib.machinery.SourceFileLoader.exec_module = original_exec
        raise
    _INSTALLED = resolution_ref
    return resolution_ref
