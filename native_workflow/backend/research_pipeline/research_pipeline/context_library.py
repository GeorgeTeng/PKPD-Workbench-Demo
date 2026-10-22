"""Pinned current library and deterministic task-view assembly. No model calls.

Upstream owns questions, record assignments and source scope. This adapter only
loads the configured immutable publication and calls the existing assembler.
"""
import importlib
import importlib.util
import copy
from contextlib import contextmanager
from pathlib import Path
import sys
import threading

from . import context_builder as cb, context_task
from .common import read_json, write_json

CONFIG = Path(__file__).parent / 'resources/context_builder/active_library.v1.json'
_lock = threading.RLock()


def load_runtime(config):
    cb.check_refs(config['runtime_bindings'])
    root = Path(config['runtime_root']).resolve(strict=True)
    identity = config['runtime_bindings']['context_resolver.py']['sha256']
    name = '_pkpd_rag_' + identity
    with _lock:
        if name not in sys.modules:
            spec = importlib.util.spec_from_file_location(name, root / '__init__.py',
                submodule_search_locations=[str(root)])
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            try:
                spec.loader.exec_module(module)
            except BaseException:
                del sys.modules[name]
                raise
        runtime = importlib.import_module(name + '.context_resolver')
    cb.check_refs(config['runtime_bindings'])
    return runtime


def pin_run(run_directory, *, config_path=CONFIG):
    """Read current ONCE for a new run; saved runs never follow later updates."""
    root = Path(run_directory).resolve()
    path = root / 'library_selection.json'
    if path.exists():
        selected = read_json(path)
    else:
        ref = cb.file_ref(config_path)
        selected = read_json(config_path)
        if selected.get('version') != 'ACTIVE_CONTEXT_LIBRARY_1.0':
            raise ValueError('Unsupported active library selection')
        cb.check_refs({'binding': selected['library_binding'], **selected['runtime_bindings']})
        # Only a receipt of the pointer, never a mutable pointer dependency.
        selected['selection_origin'] = ref
        root.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8') as stream:
            import json
            json.dump(selected, stream, ensure_ascii=False, indent=2)
        cb.check_refs({'config_during_selection': ref})
    cb.check_refs({'binding': selected['library_binding'], **selected['runtime_bindings']})
    binding = read_json(selected['library_binding']['path'])
    cb.check_refs(binding['bindings'])
    return selected, cb.file_ref(path)


def assemble_current(bundle, *, context_request, run_directory,
                     allowed_source_ids, branches=(), config_path=CONFIG):
    """Existing context_request contract; explicit permissions, no question planner.

    No semantic checker is installed. Recall remains unassessed evidence for the
    consuming agent; this adapter never turns a retrieval hit into permission.
    """
    selected, selection_ref = pin_run(run_directory, config_path=config_path)
    runtime = load_runtime(selected)
    root = Path(run_directory)
    resolver = runtime.ContextResolver(selected['library_binding']['path'],
        source_scope=allowed_source_ids, branches=branches,
        packet_path=root / 'resolution.json', allow_draft=selected['allow_draft_background'],
        semantic_checker=None)
    route = bundle['context_manifest']['route']
    pinned = cb.build_context(*route.split('.', 1), bundle['request']['payload'],
        bundle['request']['payload']['schema'], input_bindings={
            **bundle['context_manifest']['input_bindings'],
            'library_selection': selection_ref, 'context_library_adapter': cb.file_ref(__file__),
            **{'library_runtime:' + k: v for k, v in selected['runtime_bindings'].items()}})
    result = context_task.assemble(pinned, context_request=context_request, context_resolver=resolver)
    cb.check_refs({'selection': selection_ref, **selected['runtime_bindings']})
    write_json(root / 'assembled_request.json', result['request'])
    write_json(root / 'assembly_receipt.json', {
        'selection': selection_ref, 'library_binding': selected['library_binding'],
        'base_request_sha256': bundle['request']['request_sha256'],
        'assembled_request_sha256': result['request']['request_sha256'],
        'model_calls': 0, 'scientific_approval': False,
        'boundary': 'Deterministic context delivery; scientific interpretation belongs to the consumer.'})
    return result


@contextmanager
def request_scope(run_directory):
    """Reuse existing route/MP questions for fresh pre-EDA DR and Necessity.

    The full authoritative payload stays intact. Explicit upstream task views
    use assemble_current directly; method topics are not dataset readiness.
    """
    from ctxcomp import governance
    from . import context_routes
    from ctxcomp.io import digest
    root = Path(run_directory)

    def prepare(request):
        if not context_routes.managed(request):
            return request
        p = request['payload']
        route = '.'.join(context_routes.select(p))
        if route not in {'data.requirements', 'data.necessity'} or 'context_support' in p:
            return request
        selected, _ = pin_run(root)
        runtime = load_runtime(selected)
        folder = root / request['request_sha256'][:20]
        saved = folder / 'assembled_request.json'
        if saved.exists():
            if read_json(folder / 'base_request.json') != request:
                raise ValueError('Context request cache collision')
            restored = read_json(saved)
            cb.verify_bundle(cb.build_context(*route.split('.', 1), restored['payload'], p['schema']))
            return restored
        needs = runtime.derive_needs(p, output_ids=['pending'])
        if not needs:
            return request
        records = []
        for need in needs:
            rid = 'method_topic:' + need['id']
            need['needed_for'] = [rid]
            records.append({'id': rid, 'question': need['question'], 'criteria': need['criteria']})
        objective = p.get('objective') or p.get('project_context', {}).get('objective')
        write_json(folder / 'base_request.json', request)
        formal = write_json(folder / 'method_questions.json', {'objective': objective,
            'records': records, 'boundary': 'Method questions only; original project conditions and relations stay in base_request.'})
        bundle = cb.build_context(*route.split('.', 1), p, p['schema'],
            input_bindings={'context_source_request': cb.file_ref(folder / 'base_request.json')})
        envelope = runtime.prepare_request(bundle, {'questions': cb.file_ref(formal)}, upstream_needs=needs)
        catalog = runtime.load_catalog(selected['library_binding']['path'])
        scope = sorted({s for c in catalog['cards'] if c['id'] in catalog['binding']['eligible_card_ids']
            for s in c['source_ids']})
        # Pin the run selection into each task without following CONFIG again.
        write_json(folder / 'library_selection.json', selected)
        assembled = assemble_current(bundle, context_request=envelope,
            run_directory=folder, allowed_source_ids=scope)
        restored = copy.deepcopy(assembled['request']['payload'])
        restored.pop('context_support'); restored.pop('context_task_bindings')
        if restored != p:
            raise ValueError('Context assembly changed authoritative inputs')
        return assembled['request']

    with governance.request_transform(prepare):
        yield
