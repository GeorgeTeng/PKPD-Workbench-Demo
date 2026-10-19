"""Version 4 first-part main: embedded reviewed rules and one source-bound review.

No Data execution or human/scientific approval. Historical v3 and PRC packs remain
immutable. A fixed sibling receipt binds the exact reviewed main bytes.
"""
import copy
import re
import shutil
import time
from pathlib import Path

from ctxcomp.io import digest
from ctxcomp.schemas import S, arr, enum, obj, validate_schema
from ctxcomp.retention import exact_ids, span_check
from ctxcomp.providers import codex_generate
from . import project_rule_agent as prc
from .common import PipelineError, read_json, write_json, utcnow

VERSION = '4.0'
CONTRACT = 'FIRST_PART_REVIEW_1.0'
DEFAULT_MODEL = 'gpt-6-luna'
REVIEW_MODELS = ('gpt-6-sol', 'gpt-6-luna')
CHECKS = ('DUPLICATION', 'FAITHFULNESS', 'COMPLETENESS')
VERDICT = enum('PASS', 'REVISE', 'UNRESOLVED')
INSTRUCTIONS = (
    'Independently review the entire main against every supplied original source unit. '
    'Return no rewritten main. Check DUPLICATION (unnecessary synonymous narrative), '
    'FAITHFULNESS (numbers, units, conditions, scope, attribution, negation, timing and relationships), '
    'and COMPLETENESS (no material source fact, obligation, limitation, qualifier or missingness omitted). '
    'Check every clause within each source unit, not merely whether that unit is cited somewhere. '
    'Overview may summarize canonical scientific records using IDs. Scientific facts/methods and '
    'operational Rules can share subject matter for distinct purposes; explain necessary cross-purpose '
    'overlap rather than deleting facts or obligations. Exact evidence quotations, authority/field '
    'bindings and provenance legitimately repeat; do not label those redundant narrative. '
    'True duplicate full prose serving the same purpose is REVISE, including among scientific records '
    'and among Rules. Never remove distinct conditions, needed_at, missingness states or source attribution. '
    'Missing or deferred information is not new available data. data.available and data.required must '
    'remain empty; preserved gaps are neither completed evidence nor permission to fit. '
    'Only sources with may_supply_project_authority=true can impose requirements. SUPPORTING_EVIDENCE '
    'regimen cells are attributed facts; curator advice is NOT_ADOPTED. Do not request or infer held-out '
    'Horse/Human/benchmark values. Registry attachments are metadata, not sources to open. '
    'For every source unit provide exact contiguous source spans and concrete main JSON pointers for '
    'the material content or its explicit gap representation. A genuine omission may point to its '
    'nearest containing section but must be reported as a finding and non-PASS. Every finding needs '
    'valid main locations, source spans, category and a precise reason. Do not invent quotations or '
    'concatenate nonadjacent source lines. PASS requires all three checks and all source units PASS, '
    'with no findings. This is an independent content review, never human approval or scientific validation.')


def _new(directory):
    path = Path(directory).resolve()
    if path.exists() and any(path.iterdir()):
        raise PipelineError('FIRST_PART_EXISTS', 'Use a new directory; preserve prior evidence.')
    path.mkdir(parents=True, exist_ok=True)
    return path


def integrate(pack):
    """Only two field changes: version and complete structured rules."""
    value = copy.deepcopy(read_json(pack['main_ref']['path']))
    if value['data']['available'] or value['data']['required']:
        raise PipelineError('FIRST_PART_DATA_SCOPE', 'This contract requires empty data available/required.')
    value['version'] = VERSION
    value['rules'] = copy.deepcopy(pack['rules'])
    return value


def _context(pack_ref):
    pack = prc.verify_published(pack_ref)
    value = prc.validate_input(pack['input_ref'])
    from ctxcomp.engine import verify_context
    if not value.get('compression_run'):
        raise PipelineError('FIRST_PART_SOURCE', 'A verified compression lineage is required.')
    checked = verify_context(value['compression_run'])
    if checked['status'] != 'VALID':
        raise PipelineError('FIRST_PART_SOURCE', 'Compression provenance is not valid.')
    return pack, value, checked


def _pointer(value, pointer):
    if not pointer.startswith('/'):
        raise ValueError('Expected an absolute main JSON pointer')
    current = value
    for part in pointer[1:].split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        if isinstance(current, list):
            if not re.fullmatch(r'0|[1-9][0-9]*', part):
                raise ValueError('JSON pointer arrays require a nonnegative canonical index')
            current = current[int(part)]
        else:
            current = current[part]
    return current


LOCATION_CONTRACT = 'EXISTING_MAIN_LOCATIONS_1.0'


def review_locations(main):
    """Host supplies section/record pointers; the reviewer selects, never invents."""
    paths = set()
    def visit(value, path):
        if isinstance(value, dict):
            if path and 'id' in value:
                paths.add(path)
            for key, child in value.items():
                pointer = path + '/' + str(key).replace('~', '~0').replace('/', '~1')
                if not path:
                    paths.add(pointer)
                visit(child, pointer)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, path + '/' + str(index))
    visit(main, '')
    return sorted(paths)


def review_request(main, main_sha256, value, location_contract=None):
    span = obj(source_id=S, unit_id=S, quote=S)
    if location_contract not in (None, LOCATION_CONTRACT):
        raise PipelineError('FIRST_PART_CONTRACT', 'Unknown review location contract.')
    locations = arr(enum(*review_locations(main)) if location_contract else S, 1)
    schema = obj(main_sha256=enum(main_sha256), request_sha256=S, decision=VERDICT,
        checks=arr(obj(id=enum(*CHECKS), verdict=VERDICT, reason=S), 3),
        source_coverage=arr(obj(unit_id=enum(*[u['id'] for u in value['source_units']]),
            verdict=VERDICT, locations=locations, source_spans=arr(span, 1), reason=S), 1),
        findings=arr(obj(id=S, category=enum(*CHECKS), locations=locations,
            source_spans=arr(span, 1), reason=S, requested_change=S)),
        necessary_overlap_explanation=S)
    payload = {'stage':'first_part_review', 'contract':CONTRACT, 'instructions':INSTRUCTIONS,
        'main_sha256':main_sha256, 'main':main,
        'source_units':value['source_units'], 'source_permissions':value['source_permissions'],
        'source_roles':[{k:s[k] for k in ('id','name','role')} for s in value['sources']],
        'governance':value['governance'], 'processing_rules':value['processing_rules'],
        'scientific_preservation':value['scientific_preservation'], 'schema':schema}
    if location_contract:
        payload['location_contract'] = location_contract
        payload['instructions'] += (' Select existing section or record pointers from the locations schema enum. '
            'Array records use numeric indices, not record IDs. The selected record owns its complete fields; '
            'report an omission at the nearest existing section. Do not invent nested locations.')
    return {'request_sha256':digest(payload), 'payload':payload}


def validate_review(response, request):
    p = request['payload']
    validate_schema(response, p['schema'])
    if response['request_sha256'] != request['request_sha256']:
        raise PipelineError('FIRST_PART_REVIEW_BINDING', 'Review is bound to a different request.')
    exact_ids([x['id'] for x in response['checks']], CHECKS, 'Three review checks')
    exact_ids([x['unit_id'] for x in response['source_coverage']],
              [u['id'] for u in p['source_units']], 'Original source coverage')
    exact_ids([x['id'] for x in response['findings']],
              [x['id'] for x in response['findings']], 'Finding IDs')
    for record in response['source_coverage'] + response['findings']:
        for path in record['locations']:
            _pointer(p['main'], path)
        for span in record['source_spans']:
            span_check(span, p['source_units'])
        if 'unit_id' in record and not any(s['unit_id'] == record['unit_id'] for s in record['source_spans']):
            raise PipelineError('FIRST_PART_COVERAGE', 'Coverage must cite its own source unit.')
    nonpass = any(x['verdict'] != 'PASS' for x in response['checks'] + response['source_coverage'])
    if response['decision'] == 'PASS' and (nonpass or response['findings']):
        raise PipelineError('FIRST_PART_FALSE_PASS', 'PASS cannot conceal findings or incomplete coverage.')
    return response


def prepare(pack_ref, output):
    out = _new(output)
    pack, value, verified = _context(pack_ref)
    main_ref = prc.file_ref(write_json(out/'main.json', integrate(pack)))
    request = review_request(read_json(main_ref['path']), main_ref['sha256'], value, LOCATION_CONTRACT)
    request_ref = prc.file_ref(write_json(out/'request.json', request))
    proof = {'contract':CONTRACT, 'version':VERSION, 'location_contract':LOCATION_CONTRACT, 'pack_ref':pack_ref,
        'original_main_ref':pack['main_ref'], 'input_ref':pack['input_ref'],
        'main_ref':main_ref, 'request_ref':request_ref, 'compression_verification':verified,
        'source_refs':value['source_refs'], 'transformation':'ONLY_VERSION_AND_EMBED_FULL_RULES',
        'scientific_approval':False, 'data_started':False}
    write_json(out/'preparation.json', proof)
    return proof


def _verify_preparation(proof):
    if proof['contract'] != CONTRACT or proof['version'] != VERSION:
        raise PipelineError('FIRST_PART_CONTRACT', 'Unknown first-part contract.')
    for key in ('main_ref','request_ref','original_main_ref','input_ref'):
        prc.check_ref(proof[key])
    pack, value, _ = _context(proof['pack_ref'])
    main = read_json(proof['main_ref']['path'])
    if (main != integrate(pack) or proof['original_main_ref'] != pack['main_ref']
            or proof['input_ref'] != pack['input_ref'] or proof['source_refs'] != value['source_refs']):
        raise PipelineError('FIRST_PART_CHANGED', 'Main or source lineage differs from the exact integration.')
    req = review_request(main, proof['main_ref']['sha256'], value, proof.get('location_contract'))
    if req != read_json(proof['request_ref']['path']):
        raise PipelineError('FIRST_PART_REQUEST_CHANGED', 'Frozen independent review request changed.')
    return main, req


def review(prepared_dir, model=DEFAULT_MODEL, timeout=1500, generator=None):
    if model not in REVIEW_MODELS:
        raise PipelineError('FIRST_PART_MODEL', 'Use an explicitly supported first-part review model.')
    out = Path(prepared_dir).resolve()
    if (out/'review.json').exists():
        raise PipelineError('FIRST_PART_EXISTS', 'Never silently resample an existing review.')
    proof = read_json(out/'preparation.json')
    _, req = _verify_preparation(proof)
    start = time.monotonic()
    response = (generator or codex_generate)(req, model=model, timeout=timeout, diagnostics_dir=out/'model')
    # Preserve raw response even when host validation rejects it.
    write_json(out/'review.json', response)
    write_json(out/'model_timing.json', {'model':model, 'elapsed_seconds':time.monotonic()-start,
        'request_ref':proof['request_ref'], 'main_ref':proof['main_ref'], 'at':utcnow()})
    validate_review(response, req)
    return response


def _review_model(proof):
    """Read the actual recorded call identity; never relabel a different model."""
    timing = read_json(Path(proof['request_ref']['path']).parent/'model_timing.json')
    if (timing.get('model') not in REVIEW_MODELS or timing.get('request_ref') != proof['request_ref']
            or timing.get('main_ref') != proof['main_ref']):
        raise PipelineError('FIRST_PART_MODEL', 'Model timing is not bound to this supported review.')
    return timing['model']


def publish(prepared_dir, output):
    src = Path(prepared_dir).resolve()
    proof_ref = prc.file_ref(src/'preparation.json')
    proof = read_json(proof_ref['path'])
    _, req = _verify_preparation(proof)
    response_ref = prc.file_ref(src/'review.json')
    response = validate_review(read_json(response_ref['path']), req)
    actual_model = _review_model(proof)
    if response['decision'] != 'PASS':
        raise PipelineError('FIRST_PART_REVIEW_REQUIRED', 'Unified review must PASS before publication.')
    out = _new(output)
    shutil.copyfile(proof['main_ref']['path'], out/'main.json')
    main_ref = prc.file_ref(out/'main.json')
    if main_ref['sha256'] != proof['main_ref']['sha256']:
        raise PipelineError('FIRST_PART_CHANGED', 'Publication must preserve the reviewed bytes.')
    receipt = {'contract':CONTRACT, 'status':'FIRST_PART_REVIEWED', 'main_ref':main_ref,
        'preparation_ref':proof_ref, 'review_ref':response_ref, 'pack_ref':proof['pack_ref'],
        'review_model':actual_model, 'scientific_approval':False, 'data_started':False}
    write_json(out/'receipt.json', receipt)
    return verify_final_main(out/'main.json')


def verify_final_main(mainpath):
    """Data entry: only --main is needed; fixed sibling receipt verifies full lineage."""
    main_ref = prc.file_ref(mainpath)
    receipt_ref = prc.file_ref(Path(mainpath).resolve().parent/'receipt.json')
    receipt = read_json(receipt_ref['path'])
    if (receipt.get('contract') != CONTRACT or receipt.get('status') != 'FIRST_PART_REVIEWED'
            or receipt['main_ref'] != main_ref or receipt.get('scientific_approval') is not False):
        raise PipelineError('FIRST_PART_RECEIPT', 'Invalid or mismatched first-part receipt.')
    for key in ('preparation_ref','review_ref','pack_ref'):
        prc.check_ref(receipt[key])
    proof = read_json(receipt['preparation_ref']['path'])
    main, req = _verify_preparation(proof)
    if receipt.get('review_model') != _review_model(proof):
        raise PipelineError('FIRST_PART_MODEL', 'Receipt model does not match the actual recorded call.')
    if (receipt['pack_ref'] != proof['pack_ref'] or main_ref['sha256'] != proof['main_ref']['sha256']
            or read_json(main_ref['path']) != main):
        raise PipelineError('FIRST_PART_CHANGED', 'Published main is not the exact reviewed document.')
    response = validate_review(read_json(receipt['review_ref']['path']), req)
    if response['decision'] != 'PASS':
        raise PipelineError('FIRST_PART_REVIEW_REQUIRED', 'Review is not PASS.')
    return {'status':'VALID', 'main':main, 'rules':copy.deepcopy(main['rules']),
        'main_ref':main_ref, 'receipt_ref':receipt_ref, 'review_ref':receipt['review_ref'],
        'project_rules_ref':receipt['pack_ref'], 'scientific_approval':False}
