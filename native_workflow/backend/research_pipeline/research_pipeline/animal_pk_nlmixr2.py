"""Trusted, source-scoped nlmixr2 adapter. No agent-authored R or shell is executed.

The first numerical adapter deliberately supports only qualified individual IV
longitudinal data. Unsupported data remain explicit scientific work, not guessed
doses, silently pooled means, or invented individual observations.
"""
import math
import os
import subprocess
import shutil
import time
from pathlib import Path

from .adequacy import check_ref, file_ref
from .animal_pk import digest
from .common import PROJECT, PipelineError, read_json, write_json, utcnow
from .engine import rscript_path

WORKER = PROJECT / 'pkpd_r/modules/animal_pk_nlmixr2.R'
STRUCTURAL = {1: ['CL', 'VC'], 2: ['CL', 'VC', 'Q', 'VP'],
              3: ['CL', 'VC', 'Q', 'VP', 'Q2', 'VP2']}
CONFIG_KEYS = {'engine', 'estimator', 'error_model', 'initial', 'bounds', 'random_effects',
               'omega_initial', 'residual_initial', 'seed', 'cores', 'max_outer_iterations'}
NUMERICAL_CHECKS = {
    'version': '1.0',
    'scope': 'Engineering numerical eligibility only; scientific adequacy requires agent and human review.',
    'requirements': ['explicit optimizer success', 'no engine critical numerical messages',
                     'finite positive structural estimates', 'finite log likelihood',
                     'finite positive definite parameter covariance', 'structural standard errors available',
                     'finite nonnegative fitted concentrations'],
    'not_evaluated': ['biological plausibility limits', 'empirical RSE thresholds', 'external prediction validity',
                      'residual pattern acceptability', 'sampling adequacy', 'human translational validity']}


def _environment(cores=1):
    env = os.environ.copy()
    env['R_LIBS_USER'] = env.get('PKPD_R_LIB') or env.get('R_LIBS_USER') or 'C:/Users/georg/Documents/Codex/ScienceEnv/R-library'
    for name in ['OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'RXODE2_NUM_THREADS']:
        env[name] = str(cores)
    # Respect host tools, while supporting this project's existing portable R.
    root = Path('C:/Users/georg/Documents/Codex/ScienceEnv/rtools45')
    if root.is_dir():
        bins = [root/'usr/bin', root/'x86_64-w64-mingw32.static.posix/bin']
        env['PATH'] = os.pathsep.join(str(p) for p in bins) + os.pathsep + env.get('PATH', '')
        env.setdefault('BINPREF', str(bins[1]).replace('\\', '/') + '/')
    return env


def engine_preflight():
    """Read-only availability probe; never installs packages or fits a model."""
    result = {'engine': 'nlmixr2', 'available': False, 'checked_at': utcnow(),
              'supported': {'compartments': [1, 2, 3], 'estimators': ['focei'],
                            'routes': ['IV_BOLUS', 'IV_INFUSION'],
                            'record_levels': ['INDIVIDUAL_LONGITUDINAL'],
                            'error_models': ['additive', 'proportional', 'combined']},
              'limitations': ['Summary/composite, extravascular, censored/BLQ and unknown-dose data require another reviewed adapter.',
                             'FOCEI likelihood is approximate; this adapter does not declare exact-ML ranking eligibility.']}
    try:
        result['rscript'] = rscript_path()
        proc = subprocess.run([result['rscript'], '--vanilla', str(WORKER), '--preflight'],
                              env=_environment(), text=True, encoding='utf-8', errors='replace',
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        import json
        marker = next((line.removeprefix('PK_ENGINE_JSON=') for line in proc.stdout.splitlines()
                       if line.startswith('PK_ENGINE_JSON=')), None)
        if marker:
            result.update(json.loads(marker))
        result['available'] = proc.returncode == 0 and result.get('packages_ready') is True
        if not result['available']:
            result['reason'] = proc.stderr.strip() or 'R package preflight did not return a valid availability report.'
    except (PipelineError, OSError, ValueError) as exc:
        result['reason'] = str(exc)
    return result


def _fail(code, message):
    raise PipelineError('PK_NLMIXR2_' + code, message)


def _positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def validate_config(config, compartments):
    if compartments not in STRUCTURAL or type(compartments) is not int:
        _fail('STRUCTURE', 'Select one, two or three compartments from the reviewed candidate plan.')
    if not isinstance(config, dict) or not CONFIG_KEYS <= set(config) or set(config) - CONFIG_KEYS - {'optimizer'}:
        _fail('CONFIG', 'Provide the complete normalized fit_config; unknown keys and executable code are rejected.')
    if config['engine'] != 'nlmixr2' or config['estimator'] != 'focei':
        _fail('ESTIMATOR', 'This adapter supports nlmixr2 FOCEI. Other estimators need a separately qualified adapter.')
    if config.get('optimizer', 'bobyqa') not in {'bobyqa', 'nlminb'}:
        _fail('OPTIMIZER', 'Supported FOCEI optimizers are bobyqa and nlminb. The engine default is bobyqa.')
    params = STRUCTURAL[compartments]
    if not isinstance(config['initial'], dict) or set(config['initial']) != set(params):
        _fail('INITIAL_VALUES', 'Explicit initial values are required for ' + ', '.join(params) + '.')
    if not isinstance(config['bounds'], dict) or set(config['bounds']) != set(params):
        _fail('BOUNDS', 'Provide explicit positive bounds for each structural parameter.')
    for p in params:
        bounds = config['bounds'][p]
        if not isinstance(bounds, list) or len(bounds) != 2 or not all(_positive(x) for x in bounds) or not _positive(config['initial'][p]) or not bounds[0] < config['initial'][p] < bounds[1]:
            _fail('BOUNDS', 'For ' + p + ', require 0 < lower < initial < upper.')
    effects = config['random_effects']
    if not isinstance(effects, list) or any(p not in params for p in effects) or len(set(effects)) != len(effects):
        _fail('RANDOM_EFFECTS', 'Random effects must be a unique subset of this model\'s structural parameters.')
    omega = config['omega_initial']
    if not isinstance(omega, dict) or set(omega) != set(effects) or not all(_positive(x) for x in omega.values()):
        _fail('OMEGA', 'Provide a positive diagonal log-scale variance for every requested random effect.')
    residual = {'additive': ['additive'], 'proportional': ['proportional'], 'combined': ['additive', 'proportional']}.get(config['error_model'])
    if residual is None or not isinstance(config['residual_initial'], dict) or set(config['residual_initial']) != set(residual) or not all(_positive(x) for x in config['residual_initial'].values()):
        _fail('RESIDUAL', 'Choose additive, proportional or combined error and provide the corresponding positive starting values.')
    for key in ['seed', 'cores', 'max_outer_iterations']:
        if type(config[key]) is not int or config[key] < 1:
            _fail('CONFIG', key + ' must be a positive integer.')
    if config['seed'] > 2147483647 or config['cores'] > (os.cpu_count() or 1):
        _fail('RESOURCES', 'Seed must fit an R integer and cores must not exceed the local CPU count.')
    return config


def validate_qualification(qualification):
    if qualification.get('fit_ready') is not True:
        _fail('NOT_QUALIFIED', 'This candidate has not received a fit-ready data qualification.')
    for key in ['candidate_id', 'species', 'analysis_id']:
        if not isinstance(qualification.get(key), str) or not qualification[key].strip():
            _fail('SCOPE', 'The qualification must declare ' + key + '.')
    if qualification['species'].lower() in {'human', 'homo sapiens'}:
        _fail('HUMAN_HOLDOUT', 'Human validation data cannot enter this animal fitting adapter.')
    config = validate_config(qualification.get('fit_config'), qualification.get('compartments'))
    refs = qualification.get('input_refs')
    if not isinstance(refs, list) or not refs:
        _fail('SOURCE', 'Supply hash-bound source input references.')
    for ref in refs:
        check_ref(ref)
    for name in ['approval_ref', 'normalized_data_ref']:
        if not qualification.get(name):
            _fail('SOURCE', 'Missing ' + name + '; qualify and approve the scoped input before fitting.')
        check_ref(qualification[name])
    approval = read_json(qualification['approval_ref']['path'])
    approved = approval.get('status') == 'APPROVED' or approval.get('decision') == 'APPROVE' or (isinstance(approval.get('decision'), dict) and approval['decision'].get('decision') == 'APPROVE')
    if not approved:
        _fail('APPROVAL', 'The supplied review record does not show APPROVED or APPROVE.')
    signature = lambda ref: (str(Path(ref['path']).resolve()), ref['sha256'])
    normalized_signature = signature(qualification['normalized_data_ref'])
    if normalized_signature not in {signature(ref) for ref in refs}:
        _fail('SOURCE_SCOPE', 'normalized_data_ref must be one of the explicitly assigned input_refs.')
    approval_refs = approval.get('input_refs', [])
    if not approval_refs or normalized_signature not in {signature(ref) for ref in approval_refs}:
        _fail('APPROVAL_SCOPE', 'The approval must include input_refs covering this exact normalized data file and hash.')
    for ref in approval_refs:
        check_ref(ref)
    if approval.get('candidate_id') not in (None, qualification['candidate_id']):
        _fail('APPROVAL_SCOPE', 'The approval record belongs to another candidate.')
    data = read_json(qualification['normalized_data_ref']['path'])
    metadata = data.get('metadata', {})
    required = {'species': qualification['species'], 'record_level': 'INDIVIDUAL_LONGITUDINAL',
                'permission': 'DEVELOPMENT_CANDIDATE', 'time_unit': 'h',
                'concentration_unit': 'mg/L'}
    for key, expected in required.items():
        if metadata.get(key) != expected:
            _fail('METADATA', f'{key} must explicitly be {expected!r}. Missing metadata, summaries and unsupported units are not inferred.')
    if metadata.get('dose_unit') == 'mg/kg':
        if metadata.get('parameter_basis') != 'PER_KG' or metadata.get('rate_unit') != 'mg/kg/h':
            _fail('METADATA', 'Mass-normalized dosing requires explicit PER_KG parameters and mg/kg/h rates; no body weight is inferred.')
    elif metadata.get('dose_unit') != 'mg':
        _fail('METADATA', 'Declare absolute mg or explicitly qualified mass-normalized mg/kg dosing.')
    if metadata.get('blq_handling') == 'QUANTIFIED_ONLY_EXPLORATORY':
        excluded = metadata.get('excluded_records_ref')
        if not excluded or metadata.get('scientific_release') is not False:
            _fail('CENSORING', 'Quantified-only exploration requires retained excluded records and scientific_release=false.')
        check_ref(excluded)
        if signature(excluded) not in {signature(r) for r in refs}:
            _fail('CENSORING', 'Excluded records must be among the hash-bound assigned inputs.')
        if approval.get('scope') != 'EXPLORATORY_RAT_INDIVIDUAL_PK' or qualification['species'] != 'rat':
            _fail('CENSORING', 'This quantified-only extension requires the explicit exploratory rat scope.')
    elif metadata.get('blq_handling') != 'NO_BLQ':
        _fail('CENSORING', 'Unsupported censoring strategy; do not silently remove or impute BLQ observations.')
    if metadata.get('route') not in {'IV_BOLUS', 'IV_INFUSION'} or metadata.get('matrix') not in {'plasma', 'serum'} or metadata.get('exposure_basis') not in {'total', 'free'}:
        _fail('METADATA', 'Declare IV_BOLUS or IV_INFUSION, plasma or serum, and total or free concentration.')
    records = data.get('records')
    if not isinstance(records, list) or not records:
        _fail('DATA', 'The normalized data have no event or observation records.')
    allowed = {'ID', 'TIME', 'DV', 'AMT', 'EVID', 'RATE', 'CMT'}
    subjects = {}
    for i, r in enumerate(records):
        if not isinstance(r, dict) or set(r) != allowed:
            _fail('DATA', f'Row {i + 1}: require exactly ID, TIME, DV, AMT, EVID, RATE, CMT; complete normalization upstream.')
        if not isinstance(r['ID'], (str, int)) or isinstance(r['ID'], bool) or not str(r['ID']).strip():
            _fail('ID', f'Row {i + 1}: require a real subject ID; summary-group IDs are not accepted.')
        for key in ['TIME', 'AMT', 'RATE']:
            if type(r[key]) not in (int, float) or not math.isfinite(r[key]) or r[key] < 0:
                _fail('DATA', f'Row {i + 1}: {key} must be a finite nonnegative number.')
        if type(r['EVID']) is not int or r['EVID'] not in {0, 1} or type(r['CMT']) is not int or r['CMT'] != 1:
            _fail('EVENT', f'Row {i + 1}: only observation EVID=0 and central-dose EVID=1 are supported.')
        if r['EVID'] == 0:
            if not _positive(r['DV']) or r['AMT'] != 0 or r['RATE'] != 0:
                _fail('OBSERVATION', f'Row {i + 1}: observed DV must be positive and uncensored; AMT and RATE must be zero.')
        else:
            if not _positive(r['AMT']) or r['DV'] is not None:
                _fail('DOSE', f'Row {i + 1}: dose requires positive absolute AMT in mg and DV=null.')
            if (metadata['route'] == 'IV_BOLUS' and r['RATE'] != 0) or (metadata['route'] == 'IV_INFUSION' and r['RATE'] <= 0):
                _fail('DOSE', 'Bolus events need RATE=0; infusion events need an explicit positive RATE in mg/h.')
        subjects.setdefault(str(r['ID']), []).append(r)
    if config['random_effects'] and len(subjects) < 2:
        _fail('IIV', 'Between-subject variability requires multiple real subjects; select a reviewed no-IIV fit or add appropriate data.')
    for subject, rows in subjects.items():
        doses = [r for r in rows if r['EVID'] == 1]
        obs = [r for r in rows if r['EVID'] == 0]
        if not doses or len({r['TIME'] for r in obs}) < 2:
            _fail('LONGITUDINAL', f'Subject {subject}: require an explicit dose history and at least two observation times. This is an input-structure check, not a sample-size adequacy claim.')
        if min(r['TIME'] for r in obs) < min(r['TIME'] for r in doses):
            _fail('DOSE_HISTORY', f'Subject {subject}: pre-dose observations require an explicitly supported baseline/history model.')
        event_keys = [(r['TIME'], r['EVID']) for r in rows]
        if len(set(event_keys)) != len(event_keys):
            _fail('DUPLICATES', f'Subject {subject}: duplicate time/event rows require upstream resolution; no automatic averaging.')
    return {'qualification': qualification, 'metadata': metadata, 'records': records, 'config': config,
            'n_subjects': len(subjects), 'n_observations': sum(r['EVID'] == 0 for r in records)}


def fit_adapter(qualification, proposal_ref, folder):
    """Inject into run_candidate; the agent may approve a reviewed spec, never supply R."""
    validated = validate_qualification(qualification)
    check_ref(proposal_ref)
    proposal = read_json(proposal_ref['path'])
    if proposal.get('decision') != 'CONTINUE':
        _fail('PROPOSAL', 'The candidate agent did not authorize continuing with this reviewed numerical configuration.')
    ready = engine_preflight()
    if not ready['available']:
        _fail('ENGINE_UNAVAILABLE', 'The nlmixr2 engine is unavailable: ' + ready.get('reason', 'required R packages are missing'))
    folder = Path(folder).resolve(); folder.mkdir(parents=True, exist_ok=True)
    if (folder/'execution.json').exists():
        _fail('ATTEMPT_EXISTS', 'This numerical attempt already exists; create a new attempt to preserve its audit evidence.')
    payload = {'schema_version': '1.0', 'compartments': qualification['compartments'],
               'config': validated['config'], 'metadata': validated['metadata'], 'records': validated['records']}
    input_path = write_json(folder/'input.json', payload)
    request_sha = digest(payload)
    execution = {'status': 'RUNNING', 'started_at': utcnow(), 'engine': ready,
                 'request_sha256': request_sha, 'proposal_ref': proposal_ref,
                 'qualification_sha256': digest(qualification), 'cores': validated['config']['cores'],
                 'timeout_seconds': None, 'fit_calls': 1, 'scientific_accepted': False}
    write_json(folder/'execution.json', execution)
    started = time.monotonic(); heartbeat = started
    worker_snapshot=folder/'animal_pk_nlmixr2.R'
    shutil.copyfile(WORKER,worker_snapshot)
    execution['worker_code_ref']=file_ref(worker_snapshot)
    command = [ready['rscript'], '--vanilla', str(worker_snapshot), str(input_path), str(folder/'raw_result.json')]
    execution['command']=command
    write_json(folder/'execution.json',execution)
    try:
        with (folder/'engine.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen(command, env=_environment(validated['config']['cores']), cwd=folder,
                                       stdout=log, stderr=subprocess.STDOUT)
            execution['pid'] = process.pid
            write_json(folder/'execution.json', execution)
            while process.poll() is None:
                if qualification.get('pause_file') and Path(qualification['pause_file']).exists():
                    from .workflow_runtime import stop_process
                    stop_process(process)
                    _fail('PAUSED', 'Rat fitting was paused; this attempt is retained and not released.')
                now = time.monotonic()
                if now - heartbeat >= 300:
                    execution.update(last_heartbeat_at=utcnow(), elapsed_seconds=now-started)
                    write_json(folder/'execution.json', execution)
                    with (folder/'heartbeat.jsonl').open('a', encoding='utf-8') as stream:
                        import json
                        stream.write(json.dumps({'at': utcnow(), 'pid': process.pid, 'elapsed_seconds': now-started,
                                                 'message': 'Local R process is running; this is not a convergence guarantee.'})+'\n')
                    heartbeat = now
                time.sleep(0.25)
            execution['returncode'] = process.returncode
        if not (folder/'raw_result.json').exists():
            _fail('ENGINE_EXIT', 'R exited without a result. Inspect engine.log and retry after correcting the reported R dependency or execution error.')
        raw = read_json(folder/'raw_result.json')
        if process.returncode != 0 or raw.get('status') != 'FITTED':
            _fail('FIT_ERROR', raw.get('reason') or 'Numerical fitting failed; inspect the retained engine log.')
        # A changed source/review or proposal must not produce a new released
        # handoff referring to an old calculation under a different contract.
        for ref in [*qualification['input_refs'], qualification['approval_ref'], proposal_ref]:
            check_ref(ref)
        execution.update(status='COMPLETED', finished_at=utcnow(), elapsed_seconds=time.monotonic()-started)
        write_json(folder/'execution.json', execution)
        checks = {'optimizer_success': raw.get('engine_convergence_signal') is True,
                  'no_critical_engine_messages': not raw.get('critical_numerical_messages'),
                  'finite_structural_parameters': bool(raw.get('parameters')) and all(_positive(p.get('estimate')) for p in raw.get('parameters', [])),
                  'finite_log_likelihood': type(raw.get('log_likelihood')) in (int, float) and math.isfinite(raw['log_likelihood']),
                  'covariance_positive_definite': raw.get('covariance_positive_definite') is True,
                  'structural_standard_errors_available': bool(raw.get('parameters')) and all(_positive(p.get('log_scale_SE')) for p in raw.get('parameters', [])),
                  'predictions_finite': raw.get('predictions_finite') is True}
        numerical_pass = all(checks.values())
        diagnostics = {'status': 'PASSED_PRESET_CHECKS' if numerical_pass else 'REQUIRES_SCIENTIFIC_REVIEW',
                       'numerical_eligibility_only': True, 'optimizer_message': raw.get('optimizer_message'),
                       'optimizer_code': raw.get('optimizer_code'), 'run_information': raw.get('run_information'),
                       'warnings': raw.get('warnings', []), 'covariance_available': raw.get('covariance_available'),
                       'engine_convergence_signal': raw.get('engine_convergence_signal'),
                       'checks': checks, 'rules': NUMERICAL_CHECKS,
                       'failed_checks': [name for name, passed in checks.items() if not passed],
                       'limitations': ['No scientific precision, plausibility, identifiability or predictive-check thresholds are silently supplied.',
                                       'Optimizer success is not model adequacy or human translational validity.']}
        diagnostics_ref = file_ref(write_json(folder/'diagnostics.json', diagnostics))
        result = {'candidate_id': qualification['candidate_id'], 'species': qualification['species'],
                  'analysis_id': qualification['analysis_id'], 'status': 'FITTED', 'engine': 'nlmixr2',
                  'compartments': qualification['compartments'], 'converged': raw.get('engine_convergence_signal'),
                  'parameters': raw.get('parameters', []), 'observation_signature': digest({'records': validated['records'], 'metadata': validated['metadata']}),
                  'response_scale': 'concentration', 'response_unit': 'mg/L',
                  'exposure_basis': validated['metadata']['exposure_basis'], 'matrix': validated['metadata']['matrix'],
                  'likelihood_definition': 'nlmixr2 FOCEI approximation; nlmixr2est=' + ready['packages']['nlmixr2est'] + '; rxode2=' + ready['packages']['rxode2'],
                  'likelihood_constants': 'Engine-reported FOCEI constants, adjLik default; same engine versions required; not exact ML.',
                  'estimation_method': 'APPROXIMATE_FOCEI', 'n_observations': validated['n_observations'],
                  'n_subjects': validated['n_subjects'], 'bic_n_definition': 'ENGINE_REPORTED_OBSERVATION_COUNT',
                  'log_likelihood': raw.get('log_likelihood'), 'n_parameters': raw.get('n_parameters'),
                  'engine_metrics': {'AIC': raw.get('AIC'), 'BIC': raw.get('BIC'), 'purpose': 'Descriptive engine output; no exact-ML ranking release.'},
                  'diagnostic_status': diagnostics['status'], 'diagnostic_rule_signature': digest(NUMERICAL_CHECKS),
                  'numerical_eligibility': numerical_pass, 'scientific_accepted': False,
                  'model_release': False, 'human_prediction_validated': False,
                  'execution_ref': file_ref(folder/'execution.json'), 'model_code_ref': file_ref(folder/'model.R'),
                  'diagnostics_ref': diagnostics_ref, 'predictions_ref': file_ref(folder/'predictions.csv'),
                  'fit_object_ref': file_ref(folder/'fit.rds'), 'raw_result_ref': file_ref(folder/'raw_result.json'),
                  'input_ref': file_ref(input_path), 'configuration_signature': digest(validated['config'])}
        write_json(folder/'fit_result.json', result)
        return result
    except Exception as exc:
        execution.update(status='FAILED', finished_at=utcnow(), elapsed_seconds=time.monotonic()-started, reason=str(exc))
        write_json(folder/'execution.json', execution)
        raise
