"""Explicitly pinned reviewed-library retrieval; no model calls or approval."""
import copy
import importlib.util
from pathlib import Path

from .rag_v1 import RagError, canonical, check_refs, digest, file_ref, read_json
from .library_connector import _validate_manifest

VERSION = 'REVIEWED_METHOD_PACKET_1.0'
ELIGIBLE_LAYERS = {'general_method', 'conditional_method'}
ROUTES = {'data.requirements', 'data.necessity', 'method_background'}


def pin_reviewed(root, run_dir, *, snapshot_manifest=None):
    """A local reviewed manifest is its own identity, not the raw download archive."""
    root = Path(root).resolve(strict=True)
    run_dir = Path(run_dir).resolve()
    if run_dir == root or root in run_dir.parents:
        raise RagError('Write test bindings outside the knowledge library')
    if snapshot_manifest is None:
        manifest, members = _validate_manifest(root, root / 'result_manifest.json')
        manifest_ref = file_ref(root / 'result_manifest.json')
    else:
        manifest_ref = file_ref(snapshot_manifest)
        snapshot = read_json(snapshot_manifest)
        manifest = snapshot['file_hashes']
        if digest(manifest) != snapshot['manifest_sha256'] or len(manifest) != snapshot['file_count']:
            raise RagError('Snapshot manifest identity mismatch')
        declared_root = (Path(snapshot_manifest).parent.parent / snapshot['root']).resolve(strict=True)
        if declared_root != root:
            raise RagError('Snapshot belongs to another library')
        members = {}
        for relative, expected in manifest.items():
            path = (root / relative).resolve(strict=True)
            if not path.is_relative_to(root) or path == root:
                raise RagError('Snapshot member escapes library')
            members['manifest:' + relative] = {'path': str(path), 'sha256': expected}
        check_refs(members)
    required = ('cards.json', 'chunks.jsonl', 'source_registry.json', 'retrieval_policy.json',
                'layered_context.py', 'interface_contract.json')
    refs = {'manifest': manifest_ref}
    for name in required:
        if name not in manifest:
            raise RagError('Reviewed manifest omits ' + name)
        refs[name] = members['manifest:' + name]
    # Preserve the complete upstream snapshot identity without modifying it.
    refs.update(members)
    cards = read_json(root / 'cards.json')
    eligible = [c['id'] for c in cards if c.get('knowledge_layer') in ELIGIBLE_LAYERS]
    binding = {'version': VERSION, 'root': str(root), 'revision': refs['manifest']['sha256'],
               'publication': root.parent.name, 'bindings': refs,
               'eligible_card_ids': eligible, 'catalog_count': len(cards),
               'pending_count': len(cards) - len(eligible),
               'scientific_approval': False, 'production_dispatch_authorized': False}
    check_refs(refs)
    run_dir.mkdir(parents=True, exist_ok=False)
    path = run_dir / 'reviewed_library_binding.json'
    path.write_text(canonical(binding), encoding='utf-8')
    return path


def retrieve_reviewed(binding_path, *, question, query, stage, project_context,
                      allowed_source_ids, branches=(), consumer_route='method_background',
                      allow_draft=False, max_methods=2, character_budget=32768):
    """Execute one concrete information need, using the library's reviewed API."""
    binding_ref = file_ref(binding_path)
    binding = read_json(binding_path)
    if binding.get('version') != VERSION:
        raise RagError('Unknown reviewed-library binding')
    check_refs(binding['bindings'])
    if consumer_route not in ROUTES or not allow_draft:
        raise RagError('Explicit reviewed-background route and draft opt-in required')
    if not isinstance(question, str) or not question.strip():
        raise RagError('A concrete unanswered question is required')
    if binding.get('scientific_approval') is not False or binding.get('production_dispatch_authorized') is not False:
        raise RagError('Reviewed draft binding cannot grant approval')
    root = Path(binding['root'])
    implementation = root / 'layered_context.py'
    spec = importlib.util.spec_from_file_location('_pinned_reviewed_library', implementation)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    context = module.build_context(root, query=query, stage=stage,
        project_context=copy.deepcopy(project_context), allowed_source_ids=list(allowed_source_ids),
        branches=tuple(branches), consumer_route=consumer_route, allow_draft=True,
        max_methods=max_methods, character_budget=character_budget)
    if any(c['id'] not in binding['eligible_card_ids'] for c in context['general_methods']):
        raise RagError('An unreviewed catalog card entered the reviewed interface')
    check_refs(binding['bindings'])
    check_refs({'binding': binding_ref})
    packet = {'version': VERSION, 'question': question, 'publication': binding['publication'],
              'revision': binding['revision'], 'library_binding': binding_ref,
              'context': context, 'scientific_approval': False,
              'production_dispatch_authorized': False,
              'usage_boundary': 'Reviewed draft method background only. Original project Rules and task '
                  'inputs remain authoritative. Source examples are not project observations.'}
    return {**packet, 'packet_sha256': digest(packet)}


def model_background(packet):
    """Keep methods, evidence, limits and review state; avoid repeating project context."""
    if packet.get('version') == 'REVIEWED_METHOD_QUESTIONS_1.0':
        body = {k:v for k,v in packet.items() if k != 'packet_sha256'}
        if packet.get('packet_sha256') != digest(body):
            raise RagError('Reviewed question packet changed')
        views = [model_background(item) for item in packet['questions']]
        methods, evidence, originals, examples = {}, {}, {}, {}
        questions = []
        for view in views:
            questions.append({'question': view['question'], 'status': view['status'],
                              'method_ids': [m['id'] for m in view['general_methods']],
                              'selection': view['selection']})
            for method in view['general_methods']:
                key = method['id']
                if key in methods and methods[key] != method:
                    raise RagError('Conflicting reviewed methods across questions')
                methods[key] = method
            app = view['applicability_and_examples']
            for key, original in app['cited_originals'].items():
                if key in originals and originals[key] != original:
                    raise RagError('Conflicting reviewed source across questions')
                originals[key] = original
            for item in app['evidence']:
                evidence[canonical(item)] = item
            for item in app['named_example_matches']:
                examples[canonical(item)] = item
        return {'questions': questions, 'usage_boundary': packet['usage_boundary'],
                'general_methods': list(methods.values()),
                'applicability_and_examples': {
                    'applicability_status': 'REVIEWED_DRAFT_BACKGROUND_REQUIRES_TASK_APPLICABILITY_CHECK',
                    'cited_originals': originals, 'evidence': list(evidence.values()),
                    'named_example_matches': list(examples.values())},
                'scientific_approval': False}
    body = {k:v for k,v in packet.items() if k != 'packet_sha256'}
    if packet.get('packet_sha256') != digest(body):
        raise RagError('Reviewed packet changed')
    check_refs({'reviewed_library_binding': packet['library_binding']})
    binding = read_json(packet['library_binding']['path'])
    check_refs(binding['bindings'])
    context = packet['context']
    root = Path(binding['root']).resolve()
    for source in context['applicability_and_examples']['cited_originals'].values():
        path = (root / source['local_path']).resolve(strict=True)
        if not path.is_relative_to(root) or file_ref(path)['sha256'] != source['sha256']:
            raise RagError('Reviewed cited original changed or escaped its source root')
    return {'question': packet['question'], 'status': context['status'],
            'usage_boundary': packet['usage_boundary'], 'general_methods': context['general_methods'],
            'applicability_and_examples': context['applicability_and_examples'],
            'selection': context['selection'], 'scientific_approval': False}


def retrieve_questions(binding_path, needs, *, project_context, consumer_route='method_background'):
    """Recall each distinct task question independently; deduplicate only the view."""
    if not isinstance(needs, list) or not 1 <= len(needs) <= 8:
        raise RagError('Supply one to eight explicit method questions')
    permitted = {'question', 'query', 'stage', 'allowed_source_ids', 'branches',
                 'allow_draft', 'max_methods', 'character_budget'}
    if any(not isinstance(need, dict) or set(need) - permitted for need in needs):
        raise RagError('Unknown reviewed method question fields')
    if len({need.get('question') for need in needs}) != len(needs):
        raise RagError('Repeated method question')
    start = file_ref(binding_path)
    packets = [retrieve_reviewed(binding_path, project_context=project_context,
                                consumer_route=consumer_route, **copy.deepcopy(need))
               for need in needs]
    check_refs({'binding': start})
    body = {'version': 'REVIEWED_METHOD_QUESTIONS_1.0', 'questions': packets,
            'usage_boundary': packets[0]['usage_boundary'],
            'scientific_approval': False, 'production_dispatch_authorized': False}
    return {**body, 'packet_sha256': digest(body)}
