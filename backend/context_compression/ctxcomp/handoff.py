"""Proposal-only model input and deterministic attachment routing (no fitting)."""
import re
import copy
from pathlib import Path, PurePosixPath

from .io import digest, read_json, write_json


def proposal_scope(intake_root, intake, selector=None):
    files = intake['manifest']['files']
    documents = [f for f in files if f['kind'] == 'document' and f['role'] != 'REFERENCE_ONLY']
    if selector:
        matches = [f for f in documents if selector in (f['id'], f['original_name'])]
        if not matches:
            matches = [f for f in documents if PurePosixPath(f['original_name']).name == selector]
    else:
        matches = [f for f in documents if re.search(r'proposal|研究计划|研究方案',
                                                    PurePosixPath(f['original_name']).stem, re.I)]
    if len(matches) != 1:
        raise ValueError('Identify exactly one proposal with --proposal-entry (file ID or exact package entry); '
                         'no proposal is guessed from unrelated documents')
    selected = matches[0]['id']
    sources = [s for s in intake['sources'] if s.get('file_id') == selected and s['role'] != 'FILE_REGISTRY']
    if not sources:
        raise ValueError('Selected proposal has no readable content')
    registry = [s for s in intake['sources'] if s['role'] == 'FILE_REGISTRY']
    for file in files:
        file['content_sent_to_context'] = file['id'] == selected
        snapshot = read_json(Path(intake_root) / file['snapshot_path'])
        purpose, receivers, _ = route_file(file, snapshot, selected)
        file['handoff_purpose'] = purpose
        file['receivers'] = receivers
    manifest = intake['manifest']
    manifest['compression_scope'] = {'mode': 'PROPOSAL_ONLY', 'proposal_file_id': selected,
                                     'source_ids': [s['id'] for s in sources]}
    manifest['manifest_sha256'] = digest({k: v for k, v in manifest.items() if k != 'manifest_sha256'})
    write_json(Path(intake_root) / 'manifest.json', manifest)
    # The complete local source registry is retained; the separate model source
    # file makes the boundary reviewable without losing any attachment content.
    write_json(Path(intake_root) / 'compression_sources.json', sources)
    return sources, registry, manifest['compression_scope']


def route_file(file, snapshot, proposal_id):
    if file['id'] == proposal_id:
        return 'PROPOSAL', ['context_compression'], 'Compress this proposal; downstream receives the reviewed context.'
    if file['role'] == 'REFERENCE_ONLY':
        return 'REFERENCE_ONLY', ['validation'], 'Keep isolated until model choices are locked; never fitting input.'
    if snapshot['kind'] == 'csv' and snapshot['rows'] and 'model_id' in snapshot['rows'][0]:
        return 'MODEL_CATALOG', ['literature_search'], 'Catalog header contains model_id; model reliability still requires review.'
    if snapshot['kind'] in {'xlsx', 'csv'}:
        return 'DATA_CANDIDATE', ['data_preparation'], 'B2 determines table boundaries, cleans and checks adequacy before branch allocation.'
    return 'SUPPORTING_DOCUMENT', ['data_preparation'], 'Preserve original content for downstream interpretation; do not add it to proposal compression.'


def file_handoff(run, bundle, state):
    run = Path(run).resolve()
    files = []
    if bundle.get('intake'):
        manifest_path = run / bundle['intake']['manifest_path']
        manifest = read_json(manifest_path)
        for file in manifest['files']:
            snapshot = read_json(manifest_path.parent / file['snapshot_path'])
            purpose, receivers, reason = route_file(file, snapshot, bundle['compression_scope']['proposal_file_id'])
            files.append({
                'id': file['id'], 'original_name': file['original_name'], 'purpose': purpose, 'kind': file['kind'],
                'raw_path': str((manifest_path.parent / file['raw_path']).resolve()), 'sha256': file['sha256'],
                'snapshot_path': str((manifest_path.parent / file['snapshot_path']).resolve()),
                'snapshot_sha256': file['snapshot_sha256'], 'read_status': file['read_status'],
                'qc_status': file['qc_status'], 'receivers': receivers, 'routing_basis': reason,
                'compression_input': file['content_sent_to_context'] or (bool(bundle.get('compression_profile')) and file['id'] in bundle.get('explicit_clarification_file_ids', [])), 'fit_ready': False,
                'branch_assignment': 'B2_AFTER_QC_AND_HUMAN_REVIEW' if purpose == 'DATA_CANDIDATE' else 'NOT_APPLICABLE',
            })
        intake_reference = {'path': str(manifest_path), 'sha256': manifest['manifest_sha256']}
    else:
        intake_reference = None
        for file in bundle.get('document_files', []):
            proposal = file['id'] == 'S1'
            files.append({**file, 'purpose': 'PROPOSAL' if proposal else 'SUPPORTING_DOCUMENT', 'kind': 'document',
                          'read_status': 'READ_COMPLETE', 'qc_status': 'NOT_RUN',
                          'receivers': ['context_compression'] if proposal else ['data_preparation'],
                          'compression_input': proposal or (bool(bundle.get('compression_profile')) and file['id'] in bundle['compression_scope']['source_ids']), 'fit_ready': False,
                          'branch_assignment': 'NOT_APPLICABLE'})
    reviewed = 'context_review' in state['accepted']
    context = read_json(run / state['accepted']['context']['file'])['context'] if reviewed else None
    result = {
        'schema_version': '1.0', 'stage': 'B1_FILE_HANDOFF',
        'status': 'READY_FOR_DATA_PREPARATION' if reviewed else 'FILES_CHECKED_CONTEXT_PENDING',
        'compression_scope': bundle['compression_scope'],
        'context': {'path': str(run / 'compressed_context.json'), 'sha256': digest(context) if reviewed else None,
                    'status': 'REVIEWED' if reviewed else 'NOT_READY',
                    'receivers': ['data_preparation', 'pk_longitudinal', 'pkpd_index', 'literature_search']},
        'intake_manifest': intake_reference, 'files': files,
        'declared_inventory': bundle['inventory'],
        'checks': {'all_explicit_files_read': True, 'scientific_qc': 'NOT_RUN',
                   'proposal_claims_compared_to_data': 'NOT_RUN', 'declared_paths_followed': False},
        'downstream': {'source_preparation_entrypoint': 'research_pipeline.source_preparation.prepare_sources',
                       'input_argument': 'intake_manifest.path', 'automatic_execution': False,
                       'parallel_modules_after_human_review': ['pk_longitudinal', 'pkpd_index'],
                       'model_catalog_consumers': ['pk_longitudinal', 'pkpd_index'],
                       'fit_release': 'BLOCKED_UNTIL_DATA_QC_AND_HUMAN_REVIEW'},
    }
    result['handoff_sha256'] = digest(result)
    return result


def main_handoff(run, bundle, state):
    """Publish the scientific content itself, never an unfinished file pointer."""
    from . import lean_compression
    if lean_compression.enabled(bundle):
        return lean_compression.main_handoff(run, bundle, state)
    from .schemas import MAIN, validate_schema
    if 'context_review' not in state['accepted']:
        raise ValueError('No downstream JSON until proposal context review passes')
    context = read_json(Path(run) / state['accepted']['context']['file'])['context']
    result = copy.deepcopy(context)
    result['rules'] = [f'R{i:03d}: {rule}' for i, rule in enumerate(context['rules'], 1)]
    if bundle.get('processing_rules', {}).get('project_rule_owner') == 'PROJECT_RULES_AGENT':
        if context['rules']:
            raise ValueError('Compression preserves source requirements but cannot publish project rules')
        result['rule_publication'] = 'PROJECT_RULES_AGENT'
    result['data']['files'] = [
        {'id': f['id'], 'name': f['original_name'], 'path': f['raw_path'], 'sha256': f['sha256'],
         'kind': f['kind'], 'role': f['purpose'], 'receivers': f['receivers'],
         'read_status': f['read_status'], 'qc_status': f['qc_status'], 'fit_ready': False,
         # Data reuses the intake parse instead of reading each file again.
         **({'snapshot_path': f['snapshot_path'], 'snapshot_sha256': f['snapshot_sha256']} if f.get('snapshot_path') else {})}
        for f in file_handoff(run, bundle, state)['files']]
    from .supporting import warning_contract, published_warnings
    if warning_contract(bundle):
        # CC019: the reviewed warning records, published once with their identity unchanged.
        result['missing_information'] = published_warnings(bundle)
    from .scientific import enabled
    if enabled(bundle):
        from .engine import make_request
        # Identical to the object shown to all final reviewers, not a new LLM
        # summary generated after the review. verify_context rechecks equality.
        reviewed = make_request(run, 'context_review')['payload']['scientific_context']
        result['version'] = '3.2' if reviewed['version'] == '2.0' else '3.1'
        result['scientific_context'] = copy.deepcopy(reviewed)
    validate_schema(result, MAIN)
    return result


def verify_main(value, check_files=True):
    """Validate a portable main JSON without accessing B1's internal sidecars."""
    from .schemas import MAIN, validate_schema
    from .intake import file_hash
    validate_schema(value, MAIN)
    if 'demo_context_review_ref' in value:
        from .demo_review import verify as verify_demo_review
        verify_demo_review(value['demo_context_review_ref'])
    if 'scientific_context' in value:
        from .scientific import validate_handoff
        validate_handoff(value['scientific_context'])
    if 'missing_information' in value:
        ids = [w['id'] for w in value['missing_information']['items']]
        if len(set(ids)) != len(ids):
            raise ValueError('CC019: duplicate missing-information warning ID')
        texts = value['uncertainties'] + value['data']['required']
        unreferenced = [i for i in ids if not any(f'[{i}]' in t for t in texts)]
        if unreferenced:
            raise ValueError('CC019: structured warnings are not referenced in uncertainties/data.required: ' + ', '.join(unreferenced))
    identifiers = [f['id'] for f in value['data']['files']]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError('Duplicate attachment ID')
    if any(not rule.startswith(f'R{i:03d}: ') for i, rule in enumerate(value['rules'], 1)):
        raise ValueError('Rules must have consecutive IDs R001, R002, ...')
    expected_receivers = {'PROPOSAL': ['context_compression'], 'DATA_CANDIDATE': ['data_preparation'],
                          'MODEL_CATALOG': ['literature_search'], 'REFERENCE_ONLY': ['validation'],
                          'SUPPORTING_DOCUMENT': ['data_preparation']}
    for file in value['data']['files']:
        if file['receivers'] != expected_receivers[file['role']]:
            raise ValueError('Attachment routing contradicts its role: ' + file['id'])
        if check_files:
            path = Path(file['path'])
            if not path.is_absolute() or not path.is_file() or file_hash(path) != file['sha256']:
                raise ValueError('Attachment is missing or changed: ' + file['id'])
    return value
