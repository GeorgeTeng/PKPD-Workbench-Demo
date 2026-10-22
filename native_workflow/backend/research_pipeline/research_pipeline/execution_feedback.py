"""Deterministic explanations of execution failures, separate from scientific review."""
from datetime import datetime, timezone
import ast
import re
from pathlib import Path
from .common import read_json, sha256
from .context_feedback import fingerprint

# The workbench reports a worker that ended without recording an outcome with this prefix.
WORKER_EXITED = 'WORKER_EXITED'

STAGE_LABELS = {'intake':'Check uploaded files', 'pk_reference_review':'Assess PK reference applicability',
    'binding_repair':'Automatically correct source bindings (one attempt)',
    'attachment_plan':'Plan proposal-specific attachment searches', 'attachment_evidence':'Check retrieved supporting evidence',
    'main_reference_revision':'Propose main.json revisions', 'main_reference_revision_review':'Independently review main.json revisions',
    'requirements':'Extract proposal requirements', 'requirements_review':'Review extracted requirements',
    'context':'Build structured context', 'context_review':'Review structured context',
    'context_faithfulness':'Context faithfulness review', 'context_completeness':'Context completeness review',
    'context_conflicts':'Global context conflict review', 'adequacy_inventory':'Inspect input structure',
    'adequacy_assessment':'Assess project data requirements', 'adequacy_review':'Independently review data adequacy',
    'reviewed_data':'Verify approved preparation inputs', 'partition_sources':'Split and isolate source tables',
    'clean_and_assess':'Clean data and report QC findings','reviewed_preparation':'Verify approved QC files',
    'eda_describe':'Generate descriptive EDA','eda_report':'Assemble EDA report', 'clinical_dispatch':'Assign clinical questions and scoped branch contracts'}


def stage_label(stage):
    """Split faithfulness and completeness reviews name their parts context_faithfulness--part_N, context_completeness--part_N."""
    base, _, part = (stage or '').partition('--')
    if base in {'context_faithfulness', 'context_completeness'} and part.startswith('part_'):
        return STAGE_LABELS[base] + ' · part ' + part.removeprefix('part_')
    if base == 'requirements' and part.startswith('patch'):
        # Compression rules 1.26.0: a redo after a review is one patch of the reviewed inventory.
        return STAGE_LABELS[base] + ' · revision of the reviewed inventory'
    if base == 'requirements' and part:
        # Compression rules 1.25.0: the inventory runs as requirements--proposal, then requirements--supporting_X.
        return STAGE_LABELS[base] + ' · ' + part.replace('_', ' ')
    return STAGE_LABELS.get(stage, stage or 'Executor')


def parallel_note(run, stage):
    """Attachment evidence and the first review group run several calls; a failed call lets the others finish.
    The conflict review joins that group only in parallel_v3."""
    base = (stage or '').split('--')[0]
    if base in {'attachment_evidence', 'context_faithfulness', 'context_completeness'} or (
            base == 'requirements' and (stage or '').startswith('requirements--supporting')) or (
            base == 'context_conflicts' and context_review_mode(run) == 'parallel_v3'):
        return ['Parallel calls that had already started were allowed to finish; validated ones are kept for the retry.']
    return []


def current_record(path, started_at):
    try:
        value = read_json(path)
        if not isinstance(value, dict) or not value.get('at'): return None
        if started_at and datetime.fromisoformat(value['at']) < datetime.fromisoformat(started_at): return None
    except (OSError, ValueError, TypeError): return None
    return value


def legacy_citation_diagnosis(work, stopped):
    """Read-only replay of the exact failed invocation; never release its outputs."""
    if not stopped or stopped.get('stage') != 'attachment_evidence' or stopped.get('reason') != "Citation is not in this question's searched evidence":
        return None
    recorded = (work / stopped.get('model_call', '')).resolve()
    calls_root = (work / 'audit/model_calls').resolve()
    if not recorded.is_relative_to(calls_root): return None
    parts = recorded.relative_to(calls_root).parts
    if len(parts) != 3 or parts[1:] != ('attachment_evidence', 'call.json'): return None
    root = (work / 'audit/attachment_agents' / parts[0]).resolve()
    if not root.is_relative_to((work / 'audit/attachment_agents').resolve()): return None
    from ctxcomp.io import digest
    from ctxcomp.supporting import validate, citation_registry, EvidenceCitationError
    matches = []
    for response_path in root.glob('*/response.json'):
        request_path = response_path.with_name('request.json')
        try:
            request = read_json(request_path); response = read_json(response_path)
            if digest(request['payload']) != request['request_sha256'] or response['request_sha256'] != request['request_sha256']: continue
            p = request['payload']; registry = citation_registry(p)
            allowed = {s['question_id']:set(s['passage_ids']) for s in p['searches']}
            previously_rejected = [(a['question_id'], c['passage_id']) for a in response['answers']
                for c in a['citations'] if c['passage_id'] not in allowed[a['question_id']]]
            if not previously_rejected: continue
            try:
                validate(request, response)
            except EvidenceCitationError as exc:
                code = exc.code; details = exc.validation_details
            else:
                if not all(registry[cid]['source_type']=='PROPOSAL' for _,cid in previously_rejected): continue
                code = 'MODEL_CITATION_CONTRACT_MISMATCH'
                details = {'reason':'PROPOSAL_SOURCE_OMITTED_FROM_VALIDATOR', 'source_type':'PROPOSAL',
                    'rejected_citation_count':len(previously_rejected),
                    'question_ids':sorted({qid for qid,_ in previously_rejected}),
                    'citation_ids':sorted({cid for _,cid in previously_rejected}),
                    'replay_scope':'Citation and output-contract validation only; no semantic approval.'}
            matches.append((code, details, [{'path':str(f.resolve()), 'sha256':sha256(f)} for f in (request_path,response_path)]))
        except (OSError, ValueError, KeyError, TypeError): continue
    # A historical error with ambiguous retained responses is not guessed.
    return matches[0] if len(matches)==1 else None


def legacy_binding_diagnosis(work, stopped):
    """Diagnose only the recorded failed response, with its frozen request."""
    if not stopped or stopped.get('stage') != 'requirements' or stopped.get('reason') != (
            'Binding value must occur in its cited source components; preserve original units/wording'):
        return None
    try:
        calls_root = (work/'audit/model_calls').resolve()
        call_path = (work/stopped.get('model_call', '')).resolve()
        if not call_path.is_relative_to(calls_root): return None
        parts = call_path.relative_to(calls_root).parts
        if len(parts)!=3 or parts[1:]!=('requirements','call.json'): return None
        request_path = work/'requests/requirements.json'
        response_path = work/'responses'/f'requirements.{parts[0]}.json'
        request, response, call = map(read_json, (request_path, response_path, call_path))
        from ctxcomp.io import digest
        from ctxcomp.schemas import validate_schema
        from ctxcomp.bindings import binding_diagnostics, options
        key = request['request_sha256']
        if digest(request['payload'])!=key or response['request_sha256']!=key or call['request_sha256']!=key: return None
        if datetime.fromisoformat(call['at'])>datetime.fromisoformat(stopped['at']): return None
        validate_schema(response, request['payload']['schema'])
        details = binding_diagnostics(response['requirements'], request['payload']['source_units'], options(request['payload']))
        if not details['issue_count']: return None
        return 'MODEL_BINDING_INVALID', details, [
            {'path':str(p.resolve()), 'sha256':sha256(p)} for p in (request_path,response_path,call_path)]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def legacy_log_replace_diagnosis(work, stopped):
    """Identify the recorded Windows progress-file replacement, without changing history."""
    if not stopped or stopped.get('error_code') != 'CONTEXT_EXECUTION_ERROR': return None
    match = re.fullmatch(r'\[WinError (5|32|33)\][^:]*: (.+) -> (.+)', stopped.get('reason', ''))
    if not match: return None
    try:
        source, target = (Path(ast.literal_eval(x)).resolve() for x in match.groups()[1:])
        root = (work/'audit/model_calls').resolve()
        call_path = (work/stopped.get('model_call', '')).resolve()
        if not call_path.is_relative_to(root): return None
        parts = call_path.relative_to(root).parts
        if len(parts) != 3 or parts[-1] != 'call.json': return None
        if target != call_path.with_name('progress.json') or source.parent != target.parent: return None
        if not source.name.startswith('.writing-'): return None
        call = read_json(call_path)
        if not stopped.get('failed_request_sha256') or call.get('request_sha256') != stopped['failed_request_sha256']: return None
        if datetime.fromisoformat(call['at']) > datetime.fromisoformat(stopped['at']): return None
        details = {'operation':'atomic_replace','path':str(target),'winerror':int(match[1]),
            'attempts':1,'retry_wait_seconds':0,'occupying_process':'NOT_IDENTIFIED',
            'historical_single_attempt':True}
        return 'LOCAL_FILE_REPLACE_BLOCKED', details, []
    except (OSError, ValueError, TypeError, KeyError, SyntaxError):
        return None


def execution_feedback(run, error, started_at=None, stage=None):
    work = Path(run) / 'context_work'; refs = []; call = {}; stderr = ''
    if stage == 'adequacy' or (stage or '').startswith('adequacy_'): work = Path(run) / 'adequacy'
    if stage == 'data_preparation': work = Path(run) / 'data_preparation'
    if stage == 'eda': work = Path(run) / 'eda'
    if stage == 'clinical_dispatch': work = Path(run) / 'dispatch'
    pilot_stop=Path(run)/'pk_references/review/stopped.json'
    if stage=='pk_reference_pilot' or (stage=='adequacy' and pilot_stop.is_file() and current_record(pilot_stop,started_at)):
        work=Path(run)/'pk_references/review'
    if stage=='pk_reference_pilot':
        stops=[p for p in (Path(run)/'pk_references').glob('*/stopped.json') if current_record(p,started_at)]
        if stops: work=max(stops,key=lambda p:read_json(p)['at']).parent
    reference_work=work.parent==Path(run)/'pk_references'
    stop_path = work / 'stopped.json'
    stopped = current_record(stop_path, started_at) if stop_path.is_file() else None
    if stopped and stopped.get('status') != 'ERROR': stopped = None
    if stopped:
        refs.append({'path':str(stop_path.resolve()), 'sha256':sha256(stop_path)})
        stage = stopped.get('stage', stage)
        # Scope telemetry to this stage, current request, and current attempt.
        req = work / 'requests' / f'{stage}.json'
        if work.name == 'adequacy': req = work / 'audit' / stage / 'request.json'
        if reference_work: req=work/'audit/request.json'
        request_hash = stopped.get('failed_request_sha256') or (read_json(req).get('request_sha256') if req.is_file() else None)
        candidates = []
        paths = list((work / 'audit/model_calls').glob(f'*/{stage}/call.json'))
        if stopped.get('model_call'):
            recorded = (work / stopped['model_call']).resolve()
            if recorded.is_relative_to((work / 'audit/model_calls').resolve()) and recorded.is_file() and recorded not in paths:
                paths.append(recorded)
        for p in paths:
            value = current_record(p, started_at)
            if value and (not request_hash or value.get('request_sha256') == request_hash) and value.get('at','') <= stopped['at']:
                candidates.append((value['at'], p, value))
        if candidates:
            _, path, call = max(candidates, key=lambda x:x[0])
            refs.append({'path':str(path.resolve()), 'sha256':sha256(path)})
            log = path.parent / 'stderr.log'
            if log.is_file(): stderr = log.read_text(encoding='utf-8', errors='replace')
            if log.is_file(): refs.append({'path':str(log.resolve()), 'sha256':sha256(log)})
        if stopped.get('validation_record'):
            path = (work / stopped['validation_record']).resolve()
            if any(path.is_relative_to((work / folder).resolve()) for folder in ('audit/attachment_agents','audit/validation','audit/binding_repairs')):
                record = current_record(path, started_at)
                if record and record.get('request_sha256')==request_hash and record['at']<=stopped['at']:
                    refs.append({'path':str(path), 'sha256':sha256(path)})
                    for name in ('request.json','response.json'):
                        retained = path.with_name(name)
                        if retained.is_file() and read_json(retained).get('request_sha256')==request_hash:
                            refs.append({'path':str(retained), 'sha256':sha256(retained)})
    reason = (stopped or {}).get('reason') or str(error)
    code = (stopped or {}).get('error_code', 'EXECUTION_FAILED')
    if not stopped and str(error).startswith(WORKER_EXITED): code = WORKER_EXITED
    checklist = (stopped or {}).get('validation_details')
    legacy = (legacy_citation_diagnosis(work, stopped) or legacy_binding_diagnosis(work, stopped)
              or legacy_log_replace_diagnosis(work, stopped))
    if legacy:
        code, checklist, retained_refs = legacy
        refs.extend(retained_refs)
    if work.name=='adequacy' and stopped and 'path checklist must cover every expected item exactly once' in reason:
        # Explain historical failures using their own retained request/response, without editing them.
        request_path=work/'audit'/stage/'request.json'; response_path=work/'audit'/stage/'response.json'
        if request_path.is_file() and response_path.is_file():
            request=read_json(request_path); response=read_json(response_path)
            if response.get('request_sha256')==request.get('request_sha256'):
                expected=request['payload']['required_context_paths']; actual=[x['path'] for x in response['context_coverage']]
                checklist={'field':'path','missing':sorted(set(expected)-set(actual)), 'unexpected':sorted(set(actual)-set(expected)),
                           'duplicates':sorted({x for x in actual if actual.count(x)>1})}
                code='MODEL_CHECKLIST_MISMATCH'
    if call.get('status') == 'TIMEOUT': code = 'MODEL_TIMEOUT'
    if 'input_too_large' in stderr or 'Input exceeds the maximum length' in stderr:
        code = 'MODEL_INPUT_TOO_LARGE'
    # Legacy typed diagnostics may be unavailable; this exact provider message is a bounded fallback.
    if reason.startswith('Model request exceeded ') and 'seconds; no candidate accepted' in reason: code = 'MODEL_TIMEOUT'
    facts = []; actions = []; limits = 'The recorded diagnostics do not establish the underlying cause.'
    if code == 'LOCAL_FILE_REPLACE_BLOCKED':
        details = checklist or {}
        is_log = Path(details.get('path','')).name in {'progress.json','events.jsonl','stderr.log','call.json'}
        title = 'A local log file could not be updated' if is_log else 'A local file could not be replaced'
        summary = 'Windows refused the atomic file replacement. This attempt stopped before releasing its outputs.'
        facts = ['File: ' + str(details.get('path','Not recorded')),
            f"Windows error: {details.get('winerror','unknown')}; replacement attempts: {details.get('attempts','unknown')}"]
        if details.get('historical_single_attempt'):
            facts.append('This retained run used the previous single-attempt writer. The updated writer retries brief access conflicts.')
        else:
            facts.append(f"Local retry wait: {details.get('retry_wait_seconds','unknown')} seconds; the retry limit was reached.")
        actions = ['Retry context with the original files using the updated writer; brief file-access conflicts are retried locally without another model request.',
            'If the same file remains blocked, check which program holds it open and whether the file or folder is read-only or access-restricted. Resolve that condition before retrying.']
        limits = 'The recorded Windows error does not identify an occupying process or distinguish a file lock from a permission restriction. It is not evidence of a proposal, model-response or scientific-data error.'
    elif code in {'UPLOAD_READ_FAILED', 'UPLOAD_INTAKE_FAILED'}:
        title = 'Uploaded files did not pass intake'
        summary = reason
        facts = ['Intake did not release its dependency receipt; compression remains blocked.']
        diagnosis_path = work / 'intake/read_error.json'
        diagnosis = current_record(diagnosis_path, started_at) if diagnosis_path.is_file() else None
        if diagnosis:
            summary = f"Cannot read {diagnosis['original_name']}: {diagnosis['reason']}"
            facts.append('Failed file: ' + diagnosis['original_name'])
            if diagnosis.get('error_class'): facts.append('Error class: ' + diagnosis['error_class'])
            actions.append(diagnosis['corrective_action'])
            refs.append({'path': str(diagnosis_path.resolve()), 'sha256': sha256(diagnosis_path)})
        actions.append('Create a new workflow, upload the corrected files or resolve the proposal selection, and run File intake again.')
        limits = 'This is a technical file or input-selection failure, not a finding about scientific data adequacy.'
    elif code == 'SOURCE_INCOMPLETE':
        gaps = (checklist or {}).get('unresolved_gaps') or []
        title = 'File intake found content that text extraction may omit (IN001)'
        summary = 'Compression did not start because detected source-content gaps are unresolved.'
        facts = [g['original_name'] + ': ' + g['label'] + ' (' + str(g['count']) + ')'
                 + (' at ' + '; '.join(g['locations'][:3]) if g.get('locations') else '') for g in gaps] or [reason]
        actions = ['If the listed content is irrelevant to this task, record that decision for each gap in File intake; this does not claim the content was extracted.',
                   'Otherwise supply a readable version of the affected file (for example typed equations, table values or figure data) in a new workflow.']
        limits = 'Detection is structural. It does not establish whether the omitted content matters scientifically or what it contains.'
    elif reference_work and work.name in {'revision','revised'}:
        title='Main.json revision needs attention'
        summary=reason
        facts=[reason]
        actions=['Open the saved candidate, model response and independent review in the reference pilot.',
                 'Correct the specific patch or citation described in the review, then use Check and revise main.json for a new attempt. The original accepted context remains unchanged.']
        limits='This concerns the proposed context revision. It does not establish missing experimental data or authorize a change to project rules.'
    elif work==Path(run)/'pk_references/review':
        title='PK reference assessment stopped'
        summary=reason if stopped else 'The optional reference assessment did not finish. Its advisory handoff was not released.'
        facts=[reason]
        actions=['Inspect the saved request, rejected response and model diagnostics in the PK reference pilot.',
                 'Correct the cited context or reference entry, then run a new pilot attempt. No proposal change or new scientific data is implied by this execution error.']
        limits='This is a reference-assessment execution failure, not evidence that the proposal or animal data are inadequate.'
    elif work.name == 'dispatch':
        title='Clinical dispatch stopped before releasing branch contracts'
        summary=reason if stopped else 'The clinical task contracts could not be verified. No downstream handoff was released.'
        facts=[reason] if stopped else []
        actions=['Check the specified upstream approval, file hash, metadata classification or question definition.',
                 'Correct the clinical definitions or refresh their draft after upstream changes, then retry dispatch.']
        limits='This is a routing/contract failure, separate from insufficient scientific evidence or model fit.'
    elif work.name == 'eda':
        title = 'EDA stopped before releasing its results'
        summary = reason if stopped else 'An EDA process failed; no downstream handoff has been released.'
        facts = [reason] if stopped else []
        actions = ['Resolve the specific file, QC approval, metadata or numeric error described above.',
                   'Use Retry EDA after repair. Changed scientific inputs require a new QC review; compression and QC are not silently rerun.']
        limits = 'A processing error is separate from a panel marked NOT_CALCULABLE for missing scientific definitions.'
    elif work.name == 'data_preparation':
        title = 'Data preparation stopped before releasing its results'
        summary = reason if stopped else 'A preparation process failed. Review its technical log; no data have been released.'
        facts = [reason] if stopped else []
        actions = ['Correct the specific source/header/unit or approval mismatch described above.',
                   'For mapping problems, use Correct mapping to save a versioned plan; then Retry preparation. Context compression is not repeated.']
        limits = 'This is a processing error. It does not establish insufficient biological sample size or poor model fit.'
    elif code in {'MODEL_BINDING_INVALID','MODEL_BINDING_REPAIR_FAILED'}:
        details = checklist or {}; issues = details.get('issues', [])
        title = 'Source excerpts in the model extraction need correction'
        summary = (f"{details.get('issue_count', 'Some')} binding entries do not satisfy the exact-source contract. "
            'The response is retained; no downstream main.json was released.')
        facts = [f"Affected items: {details.get('affected_item_count', 'unknown')}",
            'A binding must copy one continuous excerpt of its cited source: the quote, its line or source unit, its spreadsheet row, sheet name or column header.']
        if issues:
            first = issues[0]
            facts.append(f"First issue: {first['item_id']} / {first['field']} — {first['reason']}")
        actions = ['Inspect Binding corrections or download the diagnosis JSON for every item, field, submitted value and cited excerpt.',
            'Use exact excerpts in private binding.value fields. Put faithful summaries in statement; split separately located values and retain their relationships, units and conditions.',
            'Retry context with the current extraction contract. Only reviewed compact text and required file references enter main.json; evidence details remain in the audit.']
        if stage=='binding_repair':
            title = 'Automatic binding correction could not resolve every issue'
            summary = 'The one permitted correction attempt did not produce a fully valid extraction. No downstream main.json was released.'
            facts.insert(0, reason)
            actions[-1] = 'Review the remaining issue before an explicit retry. The workflow will not keep repeating the same correction or waive independent semantic review.'
            if details.get('post_repair_error'):
                summary = ('The one permitted correction fixed every flagged entry, but the corrected extraction then failed '
                    'another check. No downstream main.json was released.')
                facts = [f"Corrected entries: {len(details.get('corrected_issues', []))}",
                    'Later check that failed: ' + details['post_repair_error']]
        limits = 'These counts are source-contract failures, not counts of proven scientific errors. Exact wording alone does not prove scientific pairing or completeness; independent reviews are still required.'
    elif code == 'MODEL_CITATION_CONTRACT_MISMATCH':
        title = 'A valid proposal citation was rejected by the previous validator'
        summary = 'The file agent received the proposal and cited its exact text, but the previous validator accepted only attachment citations. This backend contract mismatch is now corrected.'
        facts = ['Previously rejected proposal citations: '+str(checklist['rejected_citation_count']),
            'Questions: '+', '.join(checklist['question_ids']), 'Source IDs: '+', '.join(checklist['citation_ids']),
            'The retained response passes the corrected citation and output-contract checks. Its scientific interpretation has not been approved.']
        actions = ['Retry context using the existing proposal and attachments. The current agents and validator use the same permitted source list.',
            'The failed attempt remains in the audit history. The retry must complete all remaining reviews before releasing a handoff.']
        limits = 'This was a backend source-contract error. The replay does not establish semantic completeness or scientific adequacy.'
    elif code in {'MODEL_CITATION_INVALID','MODEL_CITATION_REPAIR_FAILED'}:
        title = 'An evidence citation needs correction'
        details = checklist or {}
        summary = ('Question '+details.get('question_id','unknown')+' cited '+details.get('citation_id','an unidentified source')+'. '+
            ('The quoted text is not an exact excerpt of that source.' if details.get('reason')=='QUOTE_NOT_IN_SOURCE' else
             'That source was not permitted for this question in this model call.'))
        facts = [summary, 'Source type: '+details.get('source_type','UNKNOWN'),
            'The rejected response is retained; no downstream handoff was released.']
        actions = ['Inspect the saved request and response for the specified question and source ID. Use only supplied proposal sources or attachment passages assigned to that question, with exact quotations.',
            'Retry context after the citation issue is corrected. This error does not ask you to rewrite the proposal or supply new scientific data.']
        limits = 'This is a citation validation failure. It does not establish that the proposal is incorrect or that scientific data are missing.'
        if code=='MODEL_CITATION_REPAIR_FAILED':
            title='The scoped citation review could not resolve the issue'
            summary=reason
            facts=['The scoped correction did not authorize a downstream handoff.',
                'The retained review states which source-to-claim relationships or quotations remain unresolved.']
            if details.get('attempts'):
                facts.insert(0,f"Bounded correction attempts: {details['attempts']}")
            actions=['Inspect the retained original answer, scoped review request and review result.',
                'Resolve the reported source/claim ambiguity or invalid correction before retrying. Do not change the proposal merely to satisfy a citation validator.']
            limits='An unresolved citation review does not prove the claim false or establish that scientific data are absent.'
    elif code == 'MODEL_INPUT_TOO_LARGE':
        title = 'Attachment evidence input exceeded the interface limit'
        summary = 'Too much text was submitted in one model call. No scientific review was completed by that call.'
        facts = ['The input was rejected by the calling interface, not by a scientific reviewer.']
        for key, label in [('actual_chars','Submitted characters'),('max_chars','Interface character limit')]:
            match = re.search(r'"'+key+r'"\s*:\s*(\d+)', stderr)
            if match: facts.append(label+': '+f'{int(match[1]):,}')
        actions = ['Use the updated file-scoped evidence agents. Large files are checked in batches with coverage and citation validation.',
                   'Open the latest retry if one already exists, then retry context. Keep the original proposal and attachments.']
        limits = 'This is an input-size limit in the calling interface. It does not establish missing research data, a login failure or the model context-window size.'
    elif code == 'MODEL_TIMEOUT':
        seconds = call.get('timeout_seconds')
        title = 'Model request timed out'
        summary = f'The model did not return a completed response within {seconds} seconds.' if seconds else 'The model request reached its configured deadline before a completed response was available.'
        facts = ['This model call did not produce an accepted candidate.', 'The workflow stopped at this stage. Downstream execution remains blocked.']
        actions = ['Retry context using the verified original files. The current default has no forced model-call deadline.',
                   'While waiting, inspect the five-minute heartbeat. Use Pause to stop the run manually.']
        limits = 'The deadline is confirmed. These logs do not distinguish slow generation, a stalled local client, or a service/network delay.'
    elif code == 'MODEL_CHECKLIST_MISMATCH':
        title='The model review checklist does not match the requested fields'
        summary='The review returned missing, extra or duplicate checklist entries. This is an output-contract error; it does not mean research data are missing.'
        if checklist:
            facts=['Missing checklist fields: '+(', '.join(checklist['missing']) or 'None'),
                'Extra checklist fields: '+(', '.join(checklist['unexpected']) or 'None'),
                'Duplicate checklist fields: '+(', '.join(checklist['duplicates']) or 'None')]
            if '/version' in checklist['unexpected']:
                facts.append('/version is the JSON format version. It is excluded from scientific data requirements.')
        limits='The original response is retained. Fixing its checklist cannot turn a scientific REVISE decision into PASS.'
    elif code == 'MODEL_REVIEW_INVALID':
        title = 'The model review contains an invalid citation or incomplete checklist'
        summary = 'The model returned a review, but it did not satisfy the required output contract. It was rejected and no downstream handoff was released.'
        facts = [reason]
        actions = ['For an atomic claim, quote must contain the exact candidate context text; original proposal quotations belong in evidence[].quote.',
            'Every required field, requirement and component must appear exactly once in the review.',
            'Retry context using the original proposal and files. The previous response and error are retained for inspection.']
        limits = 'This is a review-output validation failure. It does not establish that the proposal is incorrect or that scientific data are missing.'
    elif code == 'MODEL_REQUIREMENTS_PART_INVALID':
        title = 'One part of the requirements inventory did not pass its checks'
        summary = ('The requirements inventory runs as a proposal part and parallel supporting parts. One part returned an '
                   'inventory that failed its output checks, so nothing was merged or reviewed.')
        facts = [reason] + parallel_note(run, stage)
        actions = ['Retry context. When the code is unchanged it continues this run: validated parts are reused and only the '
                   'failed part is called again.']
        limits = 'This is an output-contract failure of one part. It does not establish that the proposal is incorrect.'
    elif code == 'MODEL_REQUIREMENTS_REVISION_INVALID':
        title = 'The revision of the requirements inventory did not pass its checks'
        summary = ('After the requirements review asked for changes, one call revised only the records it flagged. That '
                   'revision failed its checks, so the reviewed inventory was not changed and nothing was reviewed again.')
        facts = [reason]
        actions = ['Retry context. When the code is unchanged it continues this run and asks for the revision again; the '
                   'review and the reviewed inventory are kept.']
        limits = 'This is an output-contract failure of the revision. It does not establish that the proposal is incorrect.'
    elif code == 'MODEL_SCHEMA_REPAIR_FAILED':
        title = 'The format repair of the requirements inventory did not pass its checks'
        summary = ('The requirements inventory had records that broke the output format. One call was asked to rewrite only '
                   'those records, and that rewrite failed its checks, so nothing was accepted or reviewed.')
        facts = [reason]
        actions = ['Retry context. When the code is unchanged it continues this run and calls the failed step again.']
        limits = 'This is an output-format failure. It does not establish that the proposal is incorrect.'
    elif code == 'MODEL_RATE_LIMITED':
        title = 'The model service reported a rate or usage limit'
        summary = 'The model service refused this call because of a rate or usage limit. No candidate was accepted.'
        facts = [reason] + parallel_note(run, stage)
        actions = ['Wait for the limit to reset, then Retry context. When the code is unchanged it continues this run, reusing accepted steps and validated model calls.',
                   'If the limit recurs, set CTXCOMP_EVIDENCE_WORKERS and CTXCOMP_REVIEW_WORKERS to a smaller number and restart the workbench to run fewer model calls at once.']
        limits = 'The service reported a limit. The logs do not show when it resets or whether it applies to the account, the model or the number of concurrent calls.'
    elif code == 'MODEL_SILENT':
        title = 'A silent model call was stopped'
        summary = reason
        facts = ['The silence limit comes from CTXCOMP_MODEL_SILENCE_SECONDS. Without it, calls are never stopped for silence.'] + parallel_note(run, stage)
        actions = ['Retry context. When the code is unchanged it continues this run, reusing accepted steps and validated model calls; the stopped call runs again.',
                   'If calls are stopped while they are still working, raise CTXCOMP_MODEL_SILENCE_SECONDS or unset it, then restart the workbench.']
        limits = 'No output arrived for the configured time. The logs do not show whether the service was still working, the network stalled or the local CLI hung.'
    elif code == WORKER_EXITED:
        title = 'The run stopped when its worker process ended'
        summary = 'The process running this step ended without recording an outcome. Completed steps of this run are kept.'
        facts = ['No result of the interrupted step was released.']
        actions = ['Retry context. When the code is unchanged it continues this run, reusing accepted steps and validated model calls; the interrupted step runs again.']
        limits = 'The logs do not record why the process ended, for example a closed or restarted workbench, a restart of the computer or a stopped process.'
    elif code in {'MODEL_RESPONSE_UNAVAILABLE','MODEL_CLI_UNAVAILABLE'}:
        title = 'Model response unavailable'; summary = reason
        actions = ['Check the model connection and CLI login status.', 'After restoring the connection, retry context with the original files.']
        facts = ['No valid completed response was returned for this call.']
    else:
        title = 'Execution stopped'; summary = 'This step could not finish. Its outputs have not been released.'
        actions = ['Inspect the technical details to identify the failing file, validation or process.',
                   'Correct the reported input or runtime problem, then start a new run.']
        if reason and len(reason) < 500 and 'Traceback' not in reason and 'Snakemake stopped:' not in reason:
            facts.append(reason)
    if 'failed to refresh available models' in stderr:
        facts.append('The CLI also reported a timeout while refreshing the available model list. This is a diagnostic clue, not a confirmed cause of the full request delay.')
    if work.name == 'adequacy':
        actions = (['The backend must use the same field list for its prompt, output schema and validator; do not edit the proposal to fix this error.',
            'Retry data adequacy using the corrected interface and confirmed scope. Compression is not repeated; scientific findings will still be reviewed.']
            if code=='MODEL_CHECKLIST_MISMATCH' else ['Correct the cited context path, inventory quote or missing checklist in the model response; the rejected response is retained.',
            'Use Retry data adequacy to create a new assessment from the approved context. Compression is not repeated.']
            if code == 'MODEL_REVIEW_INVALID' else ['Inspect the recorded file or model error.',
            'Use Retry data adequacy after resolving the execution issue. The approved context is preserved.'])
    proposal_change = False if code.startswith(('MODEL_', 'UPLOAD_', 'LOCAL_FILE_', WORKER_EXITED)) or reference_work else None
    value = {'schema_version':'1.0', 'category':'EXECUTION_FAILURE', 'code':code,
        'stage':stage or 'executor', 'stage_label':stage_label(stage),
        'title':title, 'summary':summary, 'known_facts':facts, 'uncertainty':limits,
        'suggested_actions':actions, 'proposal_change_required':proposal_change,
        'missing_materials':[], 'materials_note':('No proposal change or additional scientific data is requested by this execution error.'
            if proposal_change is False else 'This execution failure alone does not establish which scientific materials are missing.'),
        'retry_supported':work.name in {'data_preparation','eda'} or reference_work or (code == WORKER_EXITED and work.name == 'context_work') or (code in {'LOCAL_FILE_REPLACE_BLOCKED','MODEL_CITATION_REPAIR_FAILED','MODEL_BINDING_REPAIR_FAILED','MODEL_BINDING_INVALID','MODEL_CITATION_INVALID','MODEL_CITATION_CONTRACT_MISMATCH','MODEL_INPUT_TOO_LARGE','MODEL_TIMEOUT','MODEL_RATE_LIMITED','MODEL_SILENT','MODEL_RESPONSE_UNAVAILABLE','MODEL_CLI_UNAVAILABLE','MODEL_REVIEW_INVALID','MODEL_CHECKLIST_MISMATCH','MODEL_REQUIREMENTS_PART_INVALID','MODEL_REQUIREMENTS_REVISION_INVALID','MODEL_SCHEMA_REPAIR_FAILED'} and (stage or '').split('--')[0] in STAGE_LABELS),
        'validation_details':checklist,
        'evidence_refs':refs, 'scientific_release':False}
    if code == WORKER_EXITED: value['stage_label'] = 'Workbench worker'
    value['signature'] = fingerprint({'report':value, 'technical_error':str(error)})
    return value


def model_progress(run, started_at=None):
    paths = [* (Path(run) / 'context_work/audit/model_calls').glob('*/*/progress*.json'),
             * (Path(run) / 'pk_references/review/audit/model_calls').glob('*/*/progress*.json'),
             * (Path(run) / 'pk_references/revision/audit/model_calls').glob('*/*/progress*.json'),
             * (Path(run) / 'pk_references/revised/audit/model_calls').glob('*/*/progress*.json'),
             * (Path(run) / 'adequacy/audit/model_calls').glob('*/*/progress*.json'),
             * (Path(run) / 'animal_pk').rglob('provider/progress*.json')]
    candidates = []
    for path in paths:
        if path.name not in {'progress.json','progress.error.json'}: continue
        try:
            value = read_json(path)
            if started_at and datetime.fromisoformat(value['started_at']) < datetime.fromisoformat(started_at): continue
            candidates.append((value['started_at'], path, value))
        except (OSError, ValueError, KeyError): continue
    if not candidates: return None
    # A terminal sidecar supersedes only the same call's progress snapshot. It
    # also supplies the status when the first normal snapshot could not be saved.
    by_call = {}
    for stamp, path, value in candidates:
        key = path.parent
        previous = by_call.get(key)
        rank = (stamp, value['last_checked_at'], path.name == 'progress.error.json')
        if previous is None or rank > previous[0]: by_call[key] = (rank, (stamp,path,value))
    candidates = [item[1] for item in by_call.values()]
    def public(path,value):
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(value['last_checked_at'])).total_seconds()
        label=stage_label(path.parent.name)
        if path.parent.name.startswith('attachment_evidence--'):
            label='Attachment evidence · '+path.parent.name.split('--',1)[1]
        return {**value,'stage':path.parent.name,'stage_label':label,
            'call_id':path.parent.parent.name+':'+path.parent.name,'monitor_current':age<=30,
            'process_alive':bool(value['process_alive'] and age<=30)}
    latest_invocation=max(candidates,key=lambda x:x[0])[1].parent.parent.name
    current=[public(path,value) for _,path,value in candidates if path.parent.parent.name==latest_invocation
             or ('animal_pk' in path.parts and value.get('status')=='RUNNING')]
    selected=max(current,key=lambda x:(x.get('status')=='RUNNING',x['started_at']))
    return {**selected,'parallel_calls':sorted(current,key=lambda x:x['started_at']),
            'context_review_mode':context_review_mode(run)}


_REVIEW_MODES = {}
def context_review_mode(run):
    """The context review mode frozen in the run's inputs (parallel_v1-v3), or None; inputs.json never changes."""
    path = Path(run) / 'context_work/inputs.json'
    try:
        stat = path.stat(); key = (str(path), stat.st_mtime_ns, stat.st_size)
        if key not in _REVIEW_MODES: _REVIEW_MODES[key] = read_json(path).get('context_review_mode')
        return _REVIEW_MODES[key]
    except (OSError, ValueError): return None
