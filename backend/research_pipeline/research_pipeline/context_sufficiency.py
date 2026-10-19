"""Optional single-batch semantic check through the existing audited gateway."""
from pathlib import Path
from jsonschema import Draft202012Validator
from ctxcomp import providers
from . import context_builder as cb
from .common import write_json


def schema(need_ids, evidence_ids=None):
    text = {'type': 'string', 'minLength': 1}
    citations = {'type': 'array', 'items': text}
    if evidence_ids is not None:
        if evidence_ids:
            citations['items'] = {'type': 'string', 'enum': sorted(set(evidence_ids))}
        else:
            citations['maxItems'] = 0
    return {'type': 'object', 'additionalProperties': False, 'required': ['decisions'],
            'properties': {'decisions': {'type': 'array', 'minItems': len(need_ids), 'maxItems': len(need_ids),
                'items': {'type': 'object', 'additionalProperties': False,
                    'required': ['need_id', 'status', 'criterion_evidence', 'reason'],
                    'properties': {'need_id': {'type': 'string', 'enum': need_ids},
                        'status': {'type': 'string', 'enum': ['SUPPORTED', 'PARTIAL', 'UNSUPPORTED']},
                        'criterion_evidence': {'type': 'array', 'items': citations},
                        'reason': text}}}}}


def checker(run_directory, *, model=None, timeout=90, max_input_characters=64000):
    """Configured at the existing workflow boundary. No model override by default.

    A separate task identity/scope is used before downstream dispatch. Provider
    failure leaves dependent outputs unverified; no retry or hand-edited answer.
    Integrity/schema failures propagate, rather than masquerading as insufficiency.
    """
    root = Path(run_directory)
    def check(value):
        root.mkdir(parents=True, exist_ok=False)
        contract = schema([n['id'] for n in value['needs']],
                          [e['id'] for e in value['knowledge'].get('evidence', [])])
        payload = {**value, 'stage': 'RAG-sufficiency', 'operation': 'ASSESS_CONTEXT_SUFFICIENCY'}
        bundle = cb.build_context('context', 'sufficiency', payload, contract)
        request_path = root / 'request.json'
        write_json(request_path, bundle['request'])
        identity = providers.executor_identity(model)
        failure = None
        try:
            from . import context_model_view
            from ctxcomp.io import canonical
            visible, _ = context_model_view.project(bundle['request'])
            if len(providers.PROMPT + canonical(visible)) + len(canonical(contract)) > max_input_characters:
                raise providers.ModelProviderError('SEMANTIC_BUDGET', 'Semantic check exceeds its final application character budget')
            answer = providers.codex_generate(bundle['request'], model=model, timeout=timeout,
                diagnostics_dir=root / 'provider', context_scope=root / 'dispatch')
            Draft202012Validator(contract).validate(answer)
            decisions = answer['decisions']
        except (providers.ModelProviderError, TimeoutError) as exc:
            failure = {'type': type(exc).__name__, 'message': str(exc)}
            decisions = [{'need_id': n['id'], 'status': 'UNVERIFIED',
                          'criterion_evidence': [[] for _ in n['criteria']],
                          'reason': 'Semantic provider unavailable; no sufficiency decision was obtained.'}
                         for n in value['needs']]
            answer = None
        cb.verify_bundle(bundle)
        receipt = {'version': 'AUTOMATIC_SEMANTIC_CHECK_1.0', 'request_sha256': bundle['request']['request_sha256'],
                   'executor': identity, 'response': answer, 'decisions': decisions, 'failure': failure,
                   'served_identity_verified': False, 'automatic_retries': 0}
        path = root / 'receipt.json'
        write_json(path, receipt)
        refs = {'semantic:request': cb.file_ref(request_path), 'semantic:receipt': cb.file_ref(path),
                'semantic:implementation': cb.file_ref(__file__),
                **{'semantic:input:' + k: v for k, v in bundle['context_manifest']['input_bindings'].items()}}
        for name in ('call.json',):
            source = root / 'provider' / name
            if source.exists():
                refs['semantic:provider:' + name] = cb.file_ref(source)
        return {'decisions': decisions, 'bindings': refs}
    return check
