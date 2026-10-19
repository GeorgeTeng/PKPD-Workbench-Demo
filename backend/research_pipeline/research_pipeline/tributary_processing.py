"""Prepare and describe supplemental data; no fitting or scientific acceptance."""
import copy
import math
import shutil
from collections import defaultdict
from pathlib import Path
from .common import read_json, write_json, sha256, PipelineError
from .data_preparation import prepare_dataset, IDENTITY
from .data_rules import known
from .dataset_metadata import reference, export_dataset
from .tables import load_table

ROLE_TARGETS = {
    'pk_observations': {'pk'}, 'exposure_response': {'index'},
    'mic': {'index'}, 'binding': {'pk', 'index'},
    'pd_observations': {'index'}, 'clinical_evidence': {'clinical'},
}
# These are adapter input requirements, not newly approved biological cutoffs.
REMEDIES = {
    'IDENTITY_MISSING': ('Dataset identity is incomplete.', 'Supply drug, analyte, species, route, matrix and free/total definitions from the source.'),
    'COMPARABILITY_METADATA_MISSING': ('Formulation or parameter definition is missing.', 'Document formulation and parameter definitions; review comparability.'),
    'UNIT_UNSUPPORTED': ('Time or concentration units are missing or unsupported.', 'Declare supported source units and an explicit conversion.'),
    'DOSE_UNIT_UNSUPPORTED': ('The PK adapter needs an explicit dose basis.', 'Supply mg or mg/kg and the corresponding dose fields.'),
    'DOSE_MISSING': ('A dosing schedule is missing.', 'Supply dose amount, dose time and infusion duration, with units.'),
    'DOSE_UNIT_MISMATCH': ('Dose fields do not match the declared units.', 'Correct the dosing schedule and dose-unit declaration.'),
    'DOSE_INVALID': ('A dosing value is invalid.', 'Check positive dose and nonnegative infusion duration against the source.'),
    'ROUTE_MODEL_MISMATCH': ('The current PK adapter supports IV data only.', 'Use a reviewed adapter for this route; do not relabel the route.'),
    'REQUIRED_VALUE_MISSING': ('A required observation value is missing.', 'Supply or correct the identified source fields; missing observations are retained in quarantine.'),
    'INVALID_NUMBER': ('A numerical value is invalid.', 'Verify the reported value, units and missing-value code.'),
    'ZERO_LOGNORMAL': ('Zero concentration is incompatible with the selected lognormal error model.', 'Verify quantification status and review the error model.'),
    'BLQ_POLICY_REQUIRED': ('BLQ handling is unresolved.', 'Supply status and assay limits; specify and review a censoring policy.'),
    'UNKNOWN_STATUS': ('An observation status is unrecognized.', 'Map missingness and censoring codes explicitly.'),
    'CONFLICTING_DUPLICATE': ('Conflicting observations share a unit/time key.', 'Verify animal, occasion and sampling identities; do not average automatically.'),
    'NO_USABLE_DATA': ('No usable observations remain.', 'Provide observations with the required identity, units and values.'),
    'INDEPENDENCE_UNVERIFIED': ('Individual animal identities are not established.', 'Supply individual data or a separately supported summary-data model.'),
    'INDIVIDUAL_PK_UNSUPPORTED': ('The sampling design does not support the selected individual-profile adapter.', 'Review serial/sparse/terminal sampling and choose a compatible model.'),
    'PK_SUPPORT_INSUFFICIENT': ('The selected PK implementation lacks sufficient computational support.', 'Review time coverage, observations per animal and model complexity. This is not a validated sample-size target.'),
    'EMAX_SUPPORT_INSUFFICIENT': ('The Emax/Hill adapter lacks observations or distinct exposure levels.', 'Supply matched independent exposure-response observations or revise the candidate model.'),
    'INDEX_CANDIDATES_MISSING': ('Candidate index columns are missing or duplicated.', 'Declare at least two distinct candidate columns for comparison.'),
    'INDEX_DEFINITION_MISSING': ('An index definition is incomplete.', 'Supply its unit, exposure window and free/total basis.'),
    'INDEX_COMPARABILITY': ('Candidate indices have incompatible windows or exposure bases.', 'Provide comparable candidate definitions and matched response rows.'),
    'ENDPOINT_DEFINITION_MISSING': ('The PD endpoint definition is incomplete.', 'Supply endpoint definition and response units.'),
    'ENDPOINT_TIME_MISMATCH': ('PD observation windows are inconsistent.', 'Split or correctly match endpoint times before comparison.'),
    'INDEX_WINDOW_INVALID': ('An exposure window is invalid.', 'Supply two increasing finite times in hours.'),
    'PERCENT_RANGE': ('A percentage is outside 0–100.', 'Verify units; do not silently convert a fraction to a percentage.'),
    'RESPONSE_CONSTANT': ('The response does not vary.', 'Review endpoint information and whether the proposed model can be estimated.'),
    'CV_GROUPS_INSUFFICIENT': ('The configured grouped validation lacks distinct groups.', 'Supply verified group identities or revise the validation plan.'),
    'DATA_SPLIT': ('Data were split by scientific identity.', 'Confirm each resulting dataset and its downstream assignment.'),
    'QUARANTINE_PROPOSED': ('Censored or missing observations were quarantined.', 'Review the source statuses and the impact of exclusion; no values were imputed.'),
    'DUPLICATE_REMOVAL_PROPOSED': ('An exact duplicate was quarantined.', 'Confirm duplicate identity and the proposed exclusion.'),
    'SAMPLING_MODEL_REVIEW': ('Sampling-design compatibility needs review.', 'Confirm which observations belong to the same animal.'),
    'PK_IDENTIFIABILITY_PENDING': ('PK identifiability requires model diagnostics.', 'Review sampling coverage now; inspect parameter uncertainty after fitting.'),
    'INDEX_RELIABILITY_PENDING': ('Index reliability requires subsequent model assessment.', 'Review exposure coverage, independence and predictive diagnostics after fitting.'),
}


def finding(code, severity, dataset, reason=None, missing=None, source=None, targets=None):
    default = REMEDIES.get(code, ('The input needs review: ' + code, 'Inspect the cited input and provide a corrected declaration or source evidence.'))
    return {'code': code, 'severity': severity, 'dataset_id': dataset,
        'category': 'DATA_ADEQUACY' if 'SUPPORT' in code else 'DATA_QUALITY',
        'reason': reason or default[0], 'required_material': missing or default[1],
        'source': source, 'affected_targets': targets or [], 'blocks_release': severity == 'ERROR'}


def prepare_support(spec, attachment, folder, issue):
    rows = load_table(attachment['path'], spec.get('table')); partitions = defaultdict(list)
    for row in rows:
        row = {k: v.strip() if isinstance(v, str) else v for k, v in row.items()}
        meta = {k: row.get(k, spec['metadata'].get(k, 'NOT_FOUND')) for k in IDENTITY}
        row['_source'] = {'source_sha256': attachment['sha256'], 'row': row.get('source_row'),
                          'sheet': spec.get('table', {}).get('sheet')}
        partitions[tuple(str(meta[k]) for k in IDENTITY)].append(row)
    groups = []
    role = spec['metadata']['role']
    required = {'mic': ['strain', 'mic_mg_L'], 'binding': ['fu'],
                'pd_observations': ['unit_id', 'response', 'response_time_h'],
                'clinical_evidence': ['claim', 'source_locator']}[role]
    for n, (key, values) in enumerate(sorted(partitions.items()), 1):
        identifier = spec['id'] + '__' + str(n).zfill(3)
        meta = {**spec['metadata'], **dict(zip(IDENTITY, key))}
        clean, quarantine = [], []
        for name in (['drug'] if role == 'clinical_evidence' else ['drug', 'species', 'matrix']):
            if not known(meta.get(name)): issue('IDENTITY_MISSING', 'ERROR', identifier, 'Missing ' + name)
        if role == 'pd_observations':
            for name in ['endpoint_definition', 'response_unit']:
                if not known(meta.get(name)): issue('ENDPOINT_DEFINITION_MISSING', 'ERROR', identifier, 'Missing ' + name)
        for row in values:
            bad = False
            if row.get('status', 'QUANTIFIED') != 'QUANTIFIED':
                quarantine.append({'record': row, 'reason': 'SOURCE_STATUS'})
                issue('QUARANTINE_PROPOSED', 'REVIEW', identifier, 'Check source status', row['_source']); continue
            for name in required:
                if not known(row.get(name)):
                    issue('REQUIRED_VALUE_MISSING', 'ERROR', identifier, 'Missing ' + name, row['_source']); bad = True
            for name in ['mic_mg_L', 'fu', 'response', 'response_time_h']:
                if name not in required or not known(row.get(name)): continue
                try:
                    if isinstance(row[name], bool): raise ValueError()
                    value = float(row[name])
                    if not math.isfinite(value) or (name == 'fu' and not 0 <= value <= 1) or (name == 'mic_mg_L' and value <= 0): raise ValueError()
                    row[name] = value
                except (ValueError, TypeError):
                    issue('INVALID_NUMBER', 'ERROR', identifier, 'Invalid ' + name, row['_source']); bad = True
            if bad: quarantine.append({'record': row, 'reason': 'UNRESOLVED_ERROR'})
            else: clean.append(row)
        if not clean: issue('NO_USABLE_DATA', 'ERROR', identifier, 'Empty candidate')
        issue('SUPPORTING_EVIDENCE_ONLY', 'REVIEW', identifier,
              'Supporting data do not independently establish a matched exposure-response table or clinical validity.')
        groups.append({'id': identifier, 'metadata': meta, 'records': clean, 'quarantine': quarantine,
                       'summary': {'input_rows': len(values), 'candidate_rows': len(clean), 'quarantined_rows': len(quarantine)},
                       'analysis_options': spec['analysis_options']})
    return groups, []


def prepare_tributary(request_path, output):
    request = read_json(request_path); output = Path(output); output.mkdir(parents=True, exist_ok=True)
    findings, groups, changes, entries, source_refs = [], [], [], [], []
    def issue(code, severity, dataset, message, source=None):
        value = finding(code, severity, dataset, source=source, targets=request['targets'])
        value['source_detail'] = message  # Preserve original processor evidence, including field names.
        findings.append(value)
    for spec in request['datasets']:
        attachment = request['attachments'][spec['upload_id']]
        if sha256(attachment['path']) != attachment['sha256']: raise ValueError('Source file changed')
        snapshot = output / 'sources' / (spec['id'] + Path(attachment['path']).suffix)
        snapshot.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(attachment['path'], snapshot)
        original = {**reference(snapshot), 'original_name': attachment['name'], 'upload_id': spec['upload_id'],
                    'table': spec['table'], 'evidence_locators': spec.get('evidence_locators', [])}
        source_refs.append(original)
        local = {**attachment, 'path': str(snapshot)}
        role = spec['metadata']['role']
        if not set(request['targets']) & ROLE_TARGETS[role]:
            findings.append(finding('ROUTE_INCOMPATIBLE', 'ERROR', spec['id'],
                'The declared dataset role is incompatible with every selected downstream target.',
                'Correct the role using source evidence or select a compatible target.', targets=request['targets']))
        try:
            if role in {'pk_observations', 'exposure_response'}:
                part, log = prepare_dataset({**spec, 'kind': 'pk' if role == 'pk_observations' else 'index'}, local, output, issue)
            else: part, log = prepare_support(spec, local, output, issue)
        except (PipelineError, ValueError, TypeError, KeyError) as exc:
            findings.append(finding('DATASET_READ_FAILED', 'ERROR', spec['id'], str(exc),
                'Supply a readable rectangular table; verify sheet, header and column mapping.', targets=request['targets'])); continue
        for group in part:
            group['readiness'] = 'BLOCKED' if any(f['blocks_release'] and f['dataset_id'] in {group['id'], spec['id']} for f in findings) else 'READY_FOR_HUMAN_REVIEW'
            group['metadata']['role'] = role
            group['metadata']['sampling_design'] = group['metadata'].get('sampling_design', 'NOT_FOUND')
            entries.append({**export_dataset(output / 'datasets', group, [original]), 'analysis_options': group['analysis_options']})
        groups.extend(part); changes.extend(log)
    for target in request['targets']:
        if not any(target in ROLE_TARGETS[e['role']] for e in entries):
            findings.append(finding('TARGET_DATA_MISSING', 'ERROR', None,
                'No compatible dataset is available for ' + target + '.',
                'Upload compatible data or remove this target from a new request.', targets=[target]))
    findings.append(finding('PRECISION_NOT_ASSESSED', 'REVIEW', None,
        'This processing assessment does not establish sufficient sample size for a precision target.',
        'To assess precision, supply the target parameter, confidence level, desired interval width and applicable variability/design evidence.', targets=request['targets']))
    for i, item in enumerate(findings): item['id'] = 'finding_' + str(i + 1).zfill(4)
    # Readiness here is scoped to processing/exploratory handoff, never sample-size reliability.
    result = {'schema_version': '1.0', 'stage': 'PREPARE_QC_ADEQUACY', 'datasets': entries,
        'source_refs': source_refs, 'findings': findings, 'change_log': changes,
        'targets': request['targets'], 'input_contract': reference(request_path),
        'assessment_status': 'BLOCKED' if not entries or any(f['blocks_release'] for f in findings) else 'READY_FOR_HUMAN_REVIEW',
        'precision_status': 'NOT_ASSESSED', 'human_prediction_status': 'NOT_ESTABLISHED',
        'scope': 'Input compatibility and exploratory handoff only; model adequacy requires subsequent diagnostics.',
        'rules': request.get('rules', []), 'scientific_release': False}
    write_json(output / 'preparation.json', result)
    return result
