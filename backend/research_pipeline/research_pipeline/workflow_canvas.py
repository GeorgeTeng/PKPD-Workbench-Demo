"""Empty workflow canvas and server-enforced, artifact-bound review gates.

Canvas sessions are independent of historical result runs. Completion comes
only from the existing local executor, never from a browser-supplied status.
"""
import copy
import hashlib
import json
import threading
from pathlib import Path
from uuid import uuid4
import zipfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Literal

from .attachments import uploaded_path
from .common import RULES, read_json, write_json, require_id, sha256, utcnow


from datetime import datetime, timezone
from .workflow_definition import NODES, EDGES, BY_ID, VERSION, CLINICAL_FIELDS
from .graph_control import ReviewController
from .scope_amendments import ScopeAmendment, save_amendment


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def blank_session(identifier=None):
    return {'id': identifier, 'definition_version': VERSION, 'created_at': utcnow() if identifier else None,
            'uploads': [], 'job_id': None, 'control_status': 'READY', 'parent_cycle': None,
            'nodes': {n['id']: {'execution': 'NOT_STARTED', 'review': None, 'artifacts': [], 'error': None,
                              'segments': []} for n in NODES}, 'events': []}


def seconds_between(start, end):
    return max(0.0, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())


def stop_clock(n, at=None):
    for segment in n.get('segments', []):
        if not segment.get('stopped_at'): segment['stopped_at'] = at or utcnow()


def run_timing(nodes, now):
    intervals = sorted((part['started_at'], part.get('stopped_at') or now)
                       for n in nodes for part in n.get('segments', []))
    merged = []
    for start, end in intervals:
        if merged and datetime.fromisoformat(start) <= datetime.fromisoformat(merged[-1][1]):
            merged[-1][1] = max(merged[-1][1], end)
        else: merged.append([start, end])
    return {'elapsed_seconds': sum(seconds_between(a, b) for a, b in merged),
            'started_at': intervals[0][0] if intervals else None,
            'running': any(not seg.get('stopped_at') for n in nodes for seg in n.get('segments', [])), 'as_of': now}


class FilesInput(BaseModel):
    upload_ids: list[str] = Field(min_length=1, max_length=100)
    project_materials: list[dict] = Field(default_factory=list)


class PreEdaRun(BaseModel):
    confirmed_user_authorization: Literal[True]



class Decision(BaseModel):
    decision: Literal['APPROVE', 'REQUEST_CHANGES', 'REJECT']
    reviewer: str = Field(min_length=1, max_length=100)
    rationale: str = Field(default='', max_length=10000)
    output_signature: str
    confirmed: Literal[True]
    # CC004: the Context review is where a human judges the compressed overall objective.
    objective_decision: Literal['CONFIRMED', 'CORRECTED', 'INCORRECT', 'OFF_SCOPE', 'MISSING'] | None = None
    objective_correction: str = Field(default='', max_length=10000)


class CoverageResolution(BaseModel):
    gap_ids: list[str] = Field(min_length=1, max_length=200)
    decision: Literal['IRRELEVANT_TO_TASK']
    reviewer: str = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=5, max_length=10000)
    confirmed: Literal[True]


OBJECTIVE_DECISIONS = {
    'CONFIRMED': 'The compressed objective is correct.',
    'CORRECTED': 'The reviewer supplies the correct objective; it is recorded as an explicit user scope change.',
    'INCORRECT': 'The objective is wrong; compression must be revised.',
    'OFF_SCOPE': 'The objective drifts from the project; compression must be revised.',
    'MISSING': 'No usable objective; supply it (CORRECTED) or revise compression.'}


class PreparationPlan(BaseModel):
    output_signature: str
    plan: dict
    rationale: str = Field(min_length=5, max_length=10000)
    confirmed: Literal[True]


class ClinicalSpec(BaseModel):
    values: dict[str, str]
    reviewer: str = Field(min_length=1, max_length=100)
    confirmed: Literal[True]
    index_exposure_source: Literal['AVAILABLE_MATCHED_DATA', 'REQUIRES_PK_PREDICTIONS', 'UNKNOWN']
    draft_signature: str | None = None


class CycleRequest(BaseModel):
    target: Literal['intake', 'context', 'adequacy', 'prepare', 'eda', 'dispatch', 'pk', 'index', 'results']
    source_node: Literal['intake', 'context', 'adequacy', 'prepare', 'eda', 'dispatch', 'pk', 'index', 'results', 'clinical'] = 'clinical'
    change_type: Literal['REVISE_PROPOSAL', 'ADD_DATA', 'RETRIEVE_EVIDENCE', 'REASSESS_ADEQUACY',
        'CORRECT_DATA', 'REVISE_EDA', 'REVISE_CLINICAL_QUESTION', 'REVISE_PK', 'REVISE_INDEX', 'REVIEW_RESULTS'] | None = None
    reason: str = Field(min_length=5, max_length=10000)
    requested_changes: str = Field(min_length=5, max_length=10000)
    reviewer: str = Field(min_length=1, max_length=100)
    confirmed: Literal[True]


class CanvasStore:
    def __init__(self, state, outputs, launch, resume, job_status, pause=None):
        self.state, self.outputs = Path(state), Path(outputs).resolve()
        self.root = self.state / 'canvas_sessions'
        self.launch, self.resume, self.job_status = launch, resume, job_status
        self.pause_job = pause
        self.graph_reviews = ReviewController(self.state)
        self.lock = threading.RLock()
        self.tributaries = None
        self.launch_adequacy = None
        self.launch_preparation = None
        self.launch_dispatch = None

    def path(self, identifier):
        require_id(identifier)
        path = self.root / identifier / 'session.json'
        if not path.is_file(): raise HTTPException(404, '流程不存在')
        return path

    def create(self):
        session = blank_session('flow_' + uuid4().hex)
        write_json(self.root / session['id'] / 'session.json', session)
        return self.view(session)

    def owns_job(self, identifier):
        with self.lock:
            if any((self.outputs/'pk_reference_runs').glob('*/'+identifier+'.json')): return True
            return any(identifier in [read_json(p).get('job_id'), *read_json(p).get('job_history', [])] for p in self.root.glob('*/session.json')) or bool(self.tributaries and self.tributaries.owns_job(identifier))

    def collect_outputs(self, s, node_id):
        spec = read_json(self.state / 'workbench_jobs' / s['job_id'] / 'request.json')
        run = Path(spec['out']).resolve()
        if not run.is_relative_to(self.outputs): raise HTTPException(409, '运行路径超出本项目')
        names = {'intake': [('manifest.json', 'context_work/intake/manifest.json')],
                 'context': [('main.json', 'B1/main.json')],
                 'adequacy': [('adequacy.json', 'adequacy/adequacy.json'), ('qc_context.json', 'adequacy/qc_context.json'),
                              ('inventory.json', 'adequacy/inventory.json'), ('assessment.json', 'adequacy/assessment.json'),
                              ('effective_main.json', 'B1/main.json'), ('context_provenance.json', 'B1/context_provenance.json')],
                 'prepare': [('data_report.json', 'data_preparation/main.json'), ('source_tables.json', 'source_preparation/output.json')],
                 'eda': [('eda_report.json','eda/eda_report.json'),('eda_context.json','eda/eda_context.json')],
                 'dispatch': [('dispatch_report.json','dispatch/dispatch_report.json')]}
        artifacts = []
        if node_id == 'prepare' and (run / 'data_preparation/data_report.json').is_file():
            names['prepare'][0] = ('data_report.json', 'data_preparation/data_report.json')
        for label, relative in names[node_id]:
            p = run / relative
            if not p.is_file(): raise HTTPException(409, '缺少本步骤声明的输出：' + label)
            read_json(p)  # An existing but invalid JSON file is not completion.
            artifacts.append({'name': label, 'path': str(p), 'sha256': sha256(p), 'kind': 'context'})
        def add_file(p, kind, label=None, source=None):
            p = Path(p).resolve()
            if not p.is_relative_to(run) or not p.is_file(): raise ValueError('附件路径缺失或超出本轮输出目录')
            if any(a['path'] == str(p) for a in artifacts): return
            if source and source.get('sha256') and source['sha256'] != sha256(p): raise ValueError('数据文件版本已改变')
            artifacts.append({'name': label or p.name, 'path': str(p), 'sha256': sha256(p),
                              'kind': kind, 'bytes': p.stat().st_size})
        coverage = None
        if node_id == 'intake':
            manifest = read_json(run / 'context_work/intake/manifest.json')
            for name in ['agent_contract.json', 'readability_report.json', 'coverage_report.json']:
                p = run / 'context_work/intake' / name
                if p.is_file(): add_file(p, 'evidence')
            coverage = self.coverage_state(run)
            if (run / 'context_work/coverage_resolutions.json').is_file():
                add_file(run / 'context_work/coverage_resolutions.json', 'evidence')
            s['intake_run'] = str(run)
            for item in manifest.get('files', []):
                if item.get('role') == 'REFERENCE_ONLY': continue
                if item.get('raw_path'):
                    add_file(run / 'context_work/intake' / item['raw_path'],
                             'data' if item.get('kind') in {'csv', 'xlsx', 'json'} else 'evidence', source=item)
        if node_id == 'context':
            published = run / 'project_rules/published'
            base = read_json(run / 'B1/main.json')
            if base.get('demo_context_review_ref'):
                from ctxcomp.demo_review import verify as verify_context_deferral
                deferred=verify_context_deferral(base['demo_context_review_ref'])
                add_file(base['demo_context_review_ref']['path'],'evidence','demo_context_review.json')
                add_file(deferred['review_ref']['path'],'evidence','independent_context_review.json')
            if base.get('rule_publication') == 'PROJECT_RULES_AGENT' or (published / 'report.json').is_file():
                from .project_rule_agent import verify_published, file_ref
                pack_ref = file_ref(published / 'project_rules.json')
                verify_published(pack_ref)
                s['project_rules_ref'] = pack_ref
                for filename in ['project_rules.json', 'main.json', 'rule_audit.json', 'report.json']:
                    add_file(published / filename, 'context' if filename in {'project_rules.json', 'main.json'} else 'evidence',
                             'published_main.json' if filename == 'main.json' else filename)
            for name in ['processing_rules.json', 'supporting_evidence.json', 'missing_information_review.json']:
                audit_path = run / 'context_work/audit' / name
                if audit_path.is_file():
                    report = read_json(audit_path)
                    add_file(audit_path, 'evidence')
                    if name == 'missing_information_review.json':
                        s['nodes'][node_id]['missing_information_review'] = report
            for item in read_json(run / 'B1/main.json').get('data', {}).get('files', []):
                if item.get('role') == 'REFERENCE_ONLY': continue
                if item.get('path'): add_file(item['path'], 'data', source=item)
            main = read_json(run / 'B1/main.json')
            s['nodes'][node_id]['objective_review'] = {
                'rule_id': 'CC004', 'objective': main.get('objective'), 'status': 'PENDING_HUMAN_DECISION',
                'options': OBJECTIVE_DECISIONS, 'correction_available': not s.get('project_rules_ref'),
                'note': 'Approve only with CONFIRMED or CORRECTED. INCORRECT, OFF_SCOPE and MISSING require REQUEST_CHANGES or REJECT. '
                        'CORRECTED is unavailable once project rules are published for this Context; rerun compression instead.'}
            if 'missing_information' in main:
                s['nodes'][node_id]['missing_information'] = main['missing_information']
        if node_id == 'adequacy':
            for name in ['requirements.json','data_labels.json','review.json','requirement_matrix.json','condition_checklist.json','unresolved_ledger.json','retained_inputs.json']:
                p=run/'adequacy'/name
                if p.is_file(): add_file(p,'context',name)
            for p in sorted((run/'pk_references').rglob('*')):
                if p.is_file(): add_file(p,'evidence','pk_references__'+p.relative_to(run/'pk_references').as_posix().replace('/','__'))
            if (run / 'B1/scope_amendment.json').is_file(): add_file(run / 'B1/scope_amendment.json', 'context')
            for relative in ['adequacy/evidence_gaps.csv', 'adequacy/report.md']:
                add_file(run / relative, 'evidence')
            for name in ['checkpoint.json', 'checkpoint.md']:
                p = run / 'adequacy' / name
                if p.is_file(): add_file(p, 'evidence')
            for p in sorted((run / 'adequacy/audit').rglob('*')):
                if p.is_file(): add_file(p, 'evidence', p.relative_to(run / 'adequacy').as_posix().replace('/', '__'))
        if node_id == 'prepare':
            for item in read_json(run / 'source_preparation/output.json').get('tables', []):
                add_file(run / 'source_preparation' / item['records_path'], 'data', source=item)
            normalized = run / 'data_preparation/normalization_manifest.json'
            if normalized.is_file():
                add_file(normalized, 'context', 'normalized_manifest.json')
                for item in read_json(normalized).get('datasets', []):
                    for key in ['csv', 'json']:
                        if item.get(key): add_file(item[key]['path'], 'data', source=item[key])
                    if item.get('metadata_file'): add_file(item['metadata_file']['path'], 'context', source=item['metadata_file'])
                    if item.get('quarantine'): add_file(item['quarantine']['path'], 'data', source=item['quarantine'])
            for relative in ['partition_manifest.json', 'data_dictionary.json', 'cleaning_log.json',
                             'program_qc.json', 'qc_findings.json', 'preparation_execution.json', 'metadata_validation.json',
                             'unresolved_ledger.json', 'handoff_review.json', 'evidence_gaps.csv', 'stated_values.json',
                             'preparation_plan.template.json', 'issues.csv', 'report.md',
                             'handoffs/eda_context.json', 'handoffs/pk_context.json', 'handoffs/index_context.json']:
                p = run / 'data_preparation' / relative
                if p.is_file(): add_file(p, 'context' if p.suffix == '.json' else 'evidence')
        if node_id in {'adequacy','prepare'}:
            for p in sorted((run/'data_agents').rglob('*.json')):
                add_file(p,'evidence','data_agents__'+p.relative_to(run/'data_agents').as_posix().replace('/','__'))
        if node_id == 'eda':
            manifest=read_json(run/'eda/artifact_manifest.json')
            add_file(run/'eda/artifact_manifest.json','context')
            add_file(run/'eda/report.md','evidence','eda_report.md')
            for ref in manifest['files']:
                add_file(ref['path'],'data' if Path(ref['path']).suffix=='.csv' else 'context',source=ref)
            for ref in manifest['figures']: add_file(ref['path'],'figure',source=ref)
            allowed={(a['path'],a['sha256']) for a in s['nodes']['prepare']['artifacts']}
            for item in manifest['data_refs']:
                for key in ['data','csv','metadata_file','quarantine']:
                    ref=item[key]
                    if (ref['path'],ref['sha256']) not in allowed or not self.artifacts_valid([ref]):
                        raise HTTPException(409,'EDA forwarded an unapproved or changed QC file')
                    artifacts.append({'name':Path(ref['path']).name,**ref,'kind':'context' if key=='metadata_file' else 'data',
                                      'bytes':Path(ref['path']).stat().st_size,'source_node':'prepare'})
        if node_id == 'dispatch':
            manifest=read_json(run/'dispatch/artifact_manifest.json')
            for ref in manifest['files']: add_file(ref['path'],ref['kind'],ref['name'],source=ref)
            s['nodes'][node_id]['dispatch_report']=read_json(run/'dispatch/dispatch_report.json')
        self.record_completion(s, node_id, artifacts)
        if node_id == 'intake':
            self.apply_coverage(s, coverage)
        if node_id == 'eda':
            s['nodes'][node_id]['eda_report']=read_json(run/'eda/eda_report.json')
        if node_id == 'prepare':
            report_path = run / 'data_preparation/data_report.json'
            if not report_path.is_file(): report_path = run / 'data_preparation/main.json'
            report = read_json(report_path)
            s['nodes'][node_id]['preparation_report'] = report
            if report.get('preparation_policy') == 'DATASET_ACTION_V1':
                if report.get('technical_processing_complete') is not True:
                    s['nodes'][node_id].update(execution='NEEDS_ATTENTION', error='Technical processing did not complete; inspect the report and retained artifacts.')
                    s['events'].append({'at': utcnow(), 'node': node_id, 'action': 'TECHNICAL_PROCESSING_INCOMPLETE'})
            elif not report.get('cleaning_complete'):
                s['nodes'][node_id].update(execution='NEEDS_ATTENTION', error='新数据尚需字段映射与科学 QC；不能把拆表完成当作数据审核通过。')
                s['events'].append({'at': utcnow(), 'node': node_id, 'action': 'NEEDS_ATTENTION'})

    def load(self, identifier):
        s = read_json(self.path(identifier)); changed = False
        if s.get('context_revision') and s['nodes']['intake']['execution'] == 'NOT_STARTED':
            receipt = self.state / 'workbench_jobs' / s['job_id'] / 'receipts/intake.json'
            if receipt.is_file():
                from .workflow_runtime import verify_refs
                try:
                    verify_refs(read_json(receipt)['outputs'])
                    self.collect_outputs(s, 'intake')
                except (ValueError, OSError, HTTPException) as exc:
                    s['nodes']['intake'].update(execution='STALE', error=str(exc))
                changed = True
        if s.get('definition_version') != VERSION:
            fresh = blank_session(identifier)
            for key, value in fresh.items(): s.setdefault(key, value)
            for key, value in fresh['nodes'].items(): s['nodes'].setdefault(key, value)
            s['definition_version'] = VERSION; changed = True
            # A previous approval cannot skip a newly introduced prerequisite.
            for definition in NODES:
                n = s['nodes'][definition['id']]
                if n['execution'] != 'NOT_STARTED' and any(not self.approved(s['nodes'][d]) for d in definition['depends_on']):
                    n.update(execution='STALE', review=None, error='流程增加了前置步骤，需在新轮次重新审核')
        for node_id, n in s['nodes'].items():
            if n.get('clinical_spec_ref') and not self.artifacts_valid([n['clinical_spec_ref']]):
                n.update(execution='STALE', review=None, error='临床问题定义已改变或缺失，需建立新轮次'); changed = True
            if n['execution'] in {'RUNNING', 'PAUSING'}:
                job = self.job_status(s['job_id'])
                if job.get('model_progress'):
                    n['model_progress'] = job['model_progress']; changed = True
                if job['status'] == 'PAUSED':
                    n.update(execution='PAUSED', error=None); stop_clock(n, job.get('finished_at'))
                    s['control_status'] = 'PAUSED'; changed = True
                    s['events'].append({'at': utcnow(), 'node': node_id, 'action': 'PAUSED'})
                elif job['status'] in {'STOPPED_ON_ERROR', 'REVISION_REQUIRED'}:
                    n.update(execution='FAILED', error=job.get('error', '执行失败')); stop_clock(n, job.get('finished_at')); changed = True
                    if job.get('technical_error'): n['technical_error'] = job['technical_error']
                    if s['control_status'] == 'PAUSING': s['control_status'] = 'PAUSED'
                elif job['status'] == 'WAITING_FOR_HUMAN_REVIEW':
                    if (s.get('context_revision') or n.get('requires_control_trace')) and not job.get('control'): continue
                    stop_clock(n, job.get('finished_at'))
                    if job.get('target') != BY_ID[node_id]['target']:
                        n.update(execution='FAILED', error='运行返回的阶段与当前节点不一致'); changed = True; continue
                    try: self.collect_outputs(s, node_id)
                    except (HTTPException, OSError, ValueError) as exc:
                        n.update(execution='FAILED', error=str(exc.detail if isinstance(exc, HTTPException) else exc))
                    if s['control_status'] == 'PAUSING': s['control_status'] = 'PAUSED'
                    changed = True
            if node_id == 'context' and n['execution'] in {'FAILED', 'REVISION_REQUIRED'} and s.get('job_id'):
                from .context_feedback import context_feedback
                spec_path = self.state / 'workbench_jobs' / s['job_id'] / 'request.json'
                if spec_path.is_file():
                    job = self.job_status(s['job_id'])
                    try:
                        feedback = context_feedback(read_json(spec_path)['out'], job.get('started_at'))
                    except (OSError, ValueError, KeyError) as exc:
                        feedback = None
                        n.update(execution='FAILED', error='Context review evidence cannot be verified: ' + str(exc)); changed = True
                    if feedback:
                        if n.get('context_feedback', {}).get('signature') != feedback['signature'] or n['execution'] != 'REVISION_REQUIRED':
                            n.update(execution='REVISION_REQUIRED', context_feedback=feedback,
                                     technical_error=n.get('technical_error') or n.get('error'), error=feedback['summary'])
                            changed = True
                    elif n.get('context_feedback'):
                        n.pop('context_feedback', None)
                        n.update(execution='FAILED', error='The previous semantic stop is no longer current. Inspect the latest execution diagnostics.')
                        changed = True
            if n['execution'] == 'FAILED':
                from .execution_feedback import execution_feedback
                spec_path = self.state / 'workbench_jobs' / str(s.get('job_id')) / 'request.json'
                if spec_path.is_file():
                    job = self.job_status(s['job_id'])
                    technical = job.get('technical_error') or n.get('technical_error') or n.get('error','')
                    failure = job.get('failure') or execution_feedback(read_json(spec_path)['out'], technical, job.get('started_at'), node_id)
                    if n.get('failure') != failure:
                        n.update(failure=failure, technical_error=technical, error=failure['summary']); changed = True
            if n['execution'] in {'COMPLETED', 'NEEDS_ATTENTION'} and not self.artifacts_valid(n['artifacts']):
                n.update(execution='STALE', review=None, error='输出文件已改变或缺失；旧审核失效。请建立新流程。'); changed = True
                s['events'].append({'at': utcnow(), 'node': node_id, 'action': 'STALE'})
        # Revoking an upstream artifact invalidates descendants, including old approvals.
        for definition in NODES:
            n = s['nodes'][definition['id']]
            if n['execution'] != 'NOT_STARTED' and any(s['nodes'][d]['execution'] == 'STALE' for d in self.dependencies(s, definition['id'])):
                n.update(execution='STALE', review=None, error='上游已改变，需重新执行和审核'); changed = True
        if s.get('control_status') == 'PAUSING' and not any(n['execution'] in {'RUNNING', 'PAUSING'} for n in s['nodes'].values()):
            branches = self.tributaries.summaries(identifier) if self.tributaries else []
            if not any(b['status'] in {'RUNNING', 'PAUSING'} for b in branches):
                s['control_status'] = 'PAUSED'; changed = True
        if changed: write_json(self.path(identifier), s)
        return s

    @staticmethod
    def coverage_state(run):
        from ctxcomp.coverage import coverage_state
        work = Path(run) / 'context_work'
        return coverage_state(work / 'intake', work / 'coverage_resolutions.json')

    @staticmethod
    def apply_coverage(s, coverage):
        """IN001: unresolved source-content gaps keep File intake open and Context locked."""
        n = s['nodes']['intake']
        if not coverage: return
        n['coverage'] = {'rule_id': 'IN001', 'status': coverage['status'],
            'gaps': coverage['gaps'], 'unresolved_gap_ids': [g['id'] for g in coverage['unresolved']],
            'resolutions': coverage['resolutions'], 'limitations': coverage.get('limitations', []),
            'decisions': ['IRRELEVANT_TO_TASK'],
            'alternative': 'Supply corrected or readable files in a new workflow; changed inputs are checked again.'}
        if coverage['unresolved']:
            n.update(execution='NEEDS_ATTENTION', error=(
                f"IN001：发现 {len(coverage['unresolved'])} 处原文内容可能未被提取（例如扫描页、图片、公式、文本框、脚注）。"
                '请逐项确认与本任务无关，或上传修正后的文件新建流程。处理完之前不能运行 Context compression。'))
            n.pop('automatic_validation', None)
            s['events'].append({'at': utcnow(), 'node': 'intake', 'action': 'SOURCE_INCOMPLETE',
                                'gap_ids': [g['id'] for g in coverage['unresolved']]})

    def resolve_coverage(self, identifier, request):
        from ctxcomp.coverage import resolve
        with self.lock:
            s = self.load(identifier); n = s['nodes']['intake']
            if n['execution'] != 'NEEDS_ATTENTION' or not (n.get('coverage') or {}).get('unresolved_gap_ids'):
                raise HTTPException(409, '资料接收没有待处理的 IN001 覆盖缺口')
            if s.get('control_status') != 'READY': raise HTTPException(409, '流程已暂停或正在停止')
            if not s.get('intake_run'): raise HTTPException(409, '找不到本轮资料接收的输出')
            run = Path(s['intake_run']).resolve()
            if not run.is_relative_to(self.outputs): raise HTTPException(409, '运行路径超出本项目')
            work = run / 'context_work'
            manifest = read_json(work / 'intake/manifest.json')
            scope = {'stage': 'context_compression', 'workflow_session': identifier,
                     'proposal_file_id': (manifest.get('compression_scope') or {}).get('proposal_file_id'),
                     'intake_manifest_sha256': manifest['manifest_sha256']}
            try:
                resolve(work / 'intake', work / 'coverage_resolutions.json', request.gap_ids,
                        request.reviewer, request.reason, decision=request.decision, scope=scope)
            except ValueError as exc: raise HTTPException(422, str(exc)) from exc
            s['events'].append({'at': utcnow(), 'node': 'intake', 'action': 'COVERAGE_GAPS_RESOLVED',
                                'gap_ids': request.gap_ids, 'reviewer': request.reviewer, 'decision': request.decision})
            artifacts = [a for a in n['artifacts'] if a['name'] != 'coverage_resolutions.json']
            p = work / 'coverage_resolutions.json'
            artifacts.append({'name': p.name, 'path': str(p), 'sha256': sha256(p), 'kind': 'evidence', 'bytes': p.stat().st_size})
            self.record_completion(s, 'intake', artifacts)
            self.apply_coverage(s, self.coverage_state(run))
            write_json(self.path(identifier), s); return self.view(s)

    def artifacts_valid(self, artifacts):
        return bool(artifacts) and all(Path(a['path']).resolve().is_relative_to(self.outputs) and
            Path(a['path']).is_file() and sha256(a['path']) == a['sha256'] for a in artifacts)

    def record_completion(self, s, node_id, artifacts):
        """Executor-side hook, deliberately not exposed as a public endpoint."""
        if node_id == 'dispatch' and s['nodes'][node_id].get('clinical_spec_ref'):
            artifacts = [*artifacts, s['nodes'][node_id]['clinical_spec_ref']]
        if not self.artifacts_valid(artifacts): raise HTTPException(409, '执行产物未通过核验')
        stop_clock(s['nodes'][node_id])
        s['nodes'][node_id].update(execution='COMPLETED', review=None, artifacts=artifacts,
                                  output_signature=fingerprint(artifacts), error=None)
        n = s['nodes'][node_id]
        if node_id == 'adequacy':
            report = next((a for a in artifacts if a['name'] == 'adequacy.json'), None)
            n['adequacy_status'] = read_json(report['path']).get('assessment_status', 'NOT_CALCULABLE') if report else 'NOT_CALCULABLE'
            n['adequacy_report'] = read_json(report['path']) if report else {}
        requires_review = node_id not in {'intake', 'results'}
        if node_id in {'adequacy', 'eda', 'prepare'}:
            report_name = {'adequacy':'adequacy.json','eda':'eda_report.json','prepare':'data_report.json'}[node_id]
            report_file = next((a for a in artifacts if a['name'] == report_name), None)
            report = read_json(report_file['path']) if report_file else {}
            # A positive, explicit processor assessment is required for automatic continuation.
            requires_review = not (report.get('assessment_status') == 'SUFFICIENT_FOR_DEFINED_SCOPE'
                and (report.get('findings') == [] or (node_id == 'adequacy' and report.get('can_enter_qc') is True
                    and all(f.get('severity') == 'FOLLOW_UP' for f in report.get('findings', []))))
                and report.get('requires_human_review') is False)
            if node_id=='prepare':
                requires_review=not (report.get('agent_workflow_version')=='2.0' and report.get('cleaning_complete') is True
                    and report.get('requires_human_review') is False and report.get('assessment_status')=='SUFFICIENT_FOR_DEFINED_SCOPE')
                if getattr(self, 'require_final_data_review', False):
                    requires_review = True
            if node_id == 'adequacy' and report.get('agent_workflow_version') == '2.0':
                requires_review = True  # DC008 requires confirmation even when the independent review passes.
        n['requires_human_review'] = requires_review
        n['gate_reason'] = 'Scientific interpretation or unresolved findings require review.' if requires_review else 'Technical checks completed; no separate human signature required.'
        if node_id == 'adequacy' and report.get('agent_workflow_version') == '2.0':
            n['gate_reason'] = 'Human approval of this exact Data checkpoint is required before DP, including after a clean technical PASS. Approval covers DP only.'
        if requires_review:
            review_rules=self.project_rules(s)
            if node_id=='eda' and report.get('eda_rules'):
                review_rules=[*review_rules,{'kind':'EDA_CONTEXT_RULE_LIBRARY','scope':'CONTEXT_GUIDANCE_ONLY',
                    'version':report['eda_rules']['library']['version'],
                    'library_ref':report['eda_rules']['library']['reference'],
                    'review_context_ref':report['eda_rules']['review_context'],
                    'applicability_status':'UNASSESSED','automatic_scientific_acceptance':False}]
            n['langgraph_review'] = self.graph_reviews.begin(s['id'], node_id, n['output_signature'],
                [{key: a[key] for key in ['name', 'sha256', 'kind'] if key in a} for a in artifacts], review_rules)
        else:
            n['automatic_validation'] = {'output_signature': n['output_signature'], 'at': utcnow(),
                                         'scientific_acceptance': False}
        s['events'].append({'at': utcnow(), 'node': node_id, 'action': 'COMPLETED_AWAITING_REVIEW' if requires_review else 'TECHNICALLY_VERIFIED'})

    @staticmethod
    def approved(n):
        if n.get('requires_human_review') is False:
            return n['execution'] == 'COMPLETED' and n.get('automatic_validation', {}).get('output_signature') == n.get('output_signature')
        return n['execution'] == 'COMPLETED' and (n.get('review') or {}).get('decision') == 'APPROVE' and n['review'].get('output_signature') == n.get('output_signature') and (n.get('langgraph_review') or {}).get('status') == 'APPROVED'

    def project_rules(self, s):
        if s.get('project_rules_ref'):
            from .project_rule_agent import verify_published
            return [r['id'] + ': ' + r['text'] for r in verify_published(s['project_rules_ref'])['rules']]
        context = s['nodes']['context']
        for artifact in context['artifacts']:
            if artifact['name'] == 'main.json' and self.artifacts_valid([artifact]):
                main = read_json(artifact['path'])
                if s.get('scope_amendment'):
                    from .scope_amendments import apply_amendment
                    from .adequacy import check_ref
                    check_ref(s['scope_amendment'])
                    main = apply_amendment(main, read_json(s['scope_amendment']['path']))
                rules = main.get('rules', [])
                return rules if isinstance(rules, list) else []
        return []

    def dependency_ready(self, s, identifier):
        n = s['nodes'][identifier]
        return self.approved(n) and (identifier != 'adequacy' or n.get('adequacy_status') == 'SUFFICIENT_FOR_DEFINED_SCOPE')

    def dependency_for_step(self, s, step, identifier):
        if step == 'prepare' and identifier == 'adequacy':
            node = s['nodes'][identifier]
            if node.get('adequacy_status') == 'SUFFICIENT_FOR_DEFINED_SCOPE': return self.approved(node)
            if node.get('adequacy_report',{}).get('agent_workflow_version')=='2.0': return False
            review = node.get('adequacy_report', {}).get('llm_review', {})
            return (self.approved(node) and node.get('adequacy_status') == 'NOT_CALCULABLE'
                and review.get('validated') is True and review.get('decision') == 'PASS'
                and any(a['name'] == 'qc_context.json' for a in node.get('artifacts', [])))
        return self.dependency_ready(s, identifier)

    @staticmethod
    def dependencies(s, node_id):
        deps = list(BY_ID[node_id]['depends_on'])
        clinical = s['nodes']['dispatch'].get('clinical_spec')
        if node_id == 'index' and clinical and clinical['index_exposure_source'] == 'REQUIRES_PK_PREDICTIONS':
            deps.append('pk')
        return deps

    def view(self, s):
        nodes = copy.deepcopy(NODES); now = utcnow()
        supplements = self.tributaries.summaries(s['id']) if self.tributaries else []
        for definition in nodes:
            current = copy.deepcopy(s['nodes'][definition['id']])
            if definition['id']=='adequacy' and s.get('scope_amendment'):
                from .adequacy import check_ref
                check_ref(s['scope_amendment']); amendment=read_json(s['scope_amendment']['path'])
                current['scope_amendment']={k:amendment[k] for k in ['at','instruction','submitted_by','changes']}
            if current.get('adequacy_report'):
                current['adequacy_report'].pop('evidence_refs', None)
            current['can_revise_context'] = (definition['id'] == 'context' and current['execution'] == 'REVISION_REQUIRED'
                and s.get('control_status') == 'READY' and not s.get('context_revision_child'))
            current['can_retry_context'] = (definition['id'] == 'context' and current['execution'] == 'FAILED'
                and current.get('failure',{}).get('retry_supported',False) and s.get('control_status') == 'READY' and not s.get('context_revision_child'))
            current['can_retry_adequacy'] = (definition['id'] == 'adequacy' and current['execution'] == 'FAILED'
                and s.get('control_status') == 'READY' and self.dependency_ready(s, 'context'))
            # Raw filesystem paths stay behind artifact links, not in the canvas contract.
            for artifact in current['artifacts']: artifact.pop('path', None)
            if current.get('clinical_spec_ref'): current['clinical_spec_ref'].pop('path', None)
            if current.get('clinical_draft'):
                for artifact in current['clinical_draft'].get('artifacts',[]): artifact.pop('path',None)
                current['clinical_draft'].pop('snapshot',None)
            if definition['id'] in {'pk','index','clinical'}:
                dispatch=s['nodes']['dispatch']; draft=dispatch.get('clinical_draft',{})
                report=dispatch.get('dispatch_report') or draft.get('report',{})
                branch=report.get('branches',{}).get(definition['id'])
                if branch:
                    current['assigned_handoff']={'name':definition['id']+'_context.json',
                        'status':'DISPATCH_APPROVED' if self.approved(dispatch) else 'PENDING_DISPATCH_REVIEW',
                        'dataset_ids':branch['dataset_ids'],'task_ids':branch['task_ids'],
                        'model_release':False,'source':'dispatch' if dispatch.get('dispatch_report') else 'draft'}
            blocked = [d for d in definition['depends_on'] if not self.dependency_for_step(s, definition['id'], d)]
            clinical = s['nodes']['dispatch'].get('clinical_spec')
            if definition['id'] == 'index' and clinical and clinical['index_exposure_source'] == 'REQUIRES_PK_PREDICTIONS':
                definition['depends_on'].append('pk')
                if not self.approved(s['nodes']['pk']): blocked.append('pk')
            reason = '、'.join(BY_ID[d]['title'] for d in blocked) + '尚未完成并审核通过' if blocked else ''
            if 'intake' in blocked and (s['nodes']['intake'].get('coverage') or {}).get('unresolved_gap_ids'):
                reason = 'IN001：资料接收发现原文内容覆盖缺口，需先逐项确认或上传修正文件'
            if 'adequacy' in blocked and self.approved(s['nodes']['adequacy']): reason = '数据不足或不可计算；需补充证据并重新判断充分性'
            can_run = bool(s['id']) and not blocked and current['execution'] == 'NOT_STARTED'
            current['can_retry_preparation'] = (definition['id'] == 'prepare' and not blocked
                and current['execution'] in {'FAILED','NEEDS_ATTENTION','COMPLETED'}
                and s.get('control_status') == 'READY' and not any(s['nodes'][k]['execution'] != 'NOT_STARTED' for k in ['eda','dispatch','pk','index']))
            current['can_retry_eda'] = False
            if definition['id'] == 'context' and self.approved(current) and s.get('job_id'):
                current['pre_eda_source_job_id'] = s['job_id']
                current['pre_eda_rules_available'] = bool(s.get('project_rules_ref'))
            else:
                current['pre_eda_source_job_id'] = None
                current['pre_eda_rules_available'] = False
            if definition['id'] == 'prepare' and not blocked and s['nodes']['adequacy'].get('adequacy_status') == 'NOT_CALCULABLE':
                current['preparation_scope'] = 'DIAGNOSTIC_PREPARATION_ONLY'
            if definition['id'] == 'intake' and not s['uploads']:
                can_run = False; reason = '等待添加本轮文件'
            if not definition['target'] and not blocked:
                can_run = False; reason = '等待接入已审核数据的执行适配器'
            if definition['id']=='dispatch' and (not clinical or clinical.get('index_exposure_source')=='UNKNOWN'):
                can_run=False
                if not blocked: reason='Confirm task definitions and the index exposure dependency before assigning tasks.'
            if definition['id']=='dispatch' and not current.get('clinical_draft'):
                can_run=False
                if not blocked: reason='Prepare task packages from the reviewed inputs, then confirm their definitions.'
            current['can_retry_dispatch']=(definition['id']=='dispatch' and not blocked and current['execution']=='FAILED'
                and s.get('control_status')=='READY' and bool(clinical) and clinical.get('index_exposure_source')!='UNKNOWN'
                and not any(s['nodes'][k]['execution']!='NOT_STARTED' for k in ['pk','index','results','clinical']))
            if s.get('control_status') != 'READY':
                can_run = False; reason = '流程已暂停；继续后才可启动步骤' if s.get('control_status') == 'PAUSED' else '正在停止当前计算，请等待暂停确认'
            elif definition['id']=='context' and current['execution']=='FAILED':
                reason = ('A retry already exists. Open the latest retry to continue.' if s.get('context_revision_child') else
                    'Execution failed. Inspect the diagnosis and use Retry context.' if current['can_retry_context'] else
                    'Execution failed. Inspect the diagnosis before retrying.')
            if not s['id'] and not blocked and definition['id'] != 'intake': reason = '请先创建空白运行'
            can_review = current['execution'] == 'COMPLETED' and not blocked and not self.approved(current)
            incoming = [b for b in supplements if definition['id'] in b['targets'] and b['status'] not in {'REJECTED', 'SUPERSEDED'}]
            if any(b['status'] != 'APPROVED' for b in incoming):
                can_run = can_review = False
                reason = 'Supplemental data need processing and approval. See Additional data for reasons and missing materials.'
            current['supplemental_inputs'] = [{'branch_id': b['id'], 'label': b['label'], 'status': b['status'],
                'files': [h['name'] for h in b.get('handoffs', []) if h['target'] == definition['id']] if b['status'] == 'APPROVED' else []} for b in incoming]
            if definition['id'] == 'dispatch' and (not clinical or clinical['index_exposure_source'] == 'UNKNOWN'): can_review = False
            if definition.get('execution_adapter') == 'DISABLED':
                can_run = False
                reason = definition['availability_reason']
            definition['state'] = {**current, 'locked_by': blocked, 'reason': reason, 'timing': run_timing([current], now),
                'can_run': can_run, 'can_review': can_review,
                'approved': self.approved(current)}
        return {'schema_version': VERSION, 'template_id': 'translational_pkpd_clinical_loop', 'nodes': nodes,
            'edges': EDGES, 'session_id': s['id'], 'uploads': s['uploads'], 'events': s['events'],
            'supplements': [self.tributaries.public(b) for b in supplements],
            'control_status': s.get('control_status', 'READY'), 'timing': run_timing(list(s['nodes'].values()) + supplements, now),
            'can_pause': bool(s['id']) and s.get('control_status') == 'READY',
            'can_continue': s.get('control_status') == 'PAUSED', 'parent_cycle': s.get('parent_cycle'),
            'context_revision_child': s.get('context_revision_child'),
            'clinical_fields': [{'key': key, 'label': label, 'help': help} for key, label, help in CLINICAL_FIELDS],
            'cycle_sources': [{'id': key, 'title': BY_ID[key]['title'], 'execution': value['execution'],
                'output_signature': value.get('output_signature')} for key, value in s['nodes'].items()
                if value['execution'] in {'COMPLETED', 'NEEDS_ATTENTION'} and value.get('output_signature')],
            'architecture': {'controller': 'LangGraph', 'scheduler': 'Prefect', 'file_executor': 'Snakemake',
                'review': 'LangGraph interrupt + SQLite checkpoint', 'generic_rules_status': 'DRAFT_NOT_ENABLED'},
            'can_publish': bool(s['id']) and all(self.dependency_ready(s, key) for key in s['nodes']) and s['control_status'] == 'READY'
                and all(b['status'] in {'APPROVED', 'REJECTED', 'SUPERSEDED'} for b in supplements),
            'stats': {'files': len(s['uploads']), 'completed': sum(n['execution'] == 'COMPLETED' for n in s['nodes'].values()),
                      'approved': sum(self.approved(n) for n in s['nodes'].values())}}

    def bind_files(self, identifier, ids, project_materials=None):
        with self.lock:
            s = self.load(identifier)
            if s['nodes']['intake']['execution'] != 'NOT_STARTED': raise HTTPException(409, '文件已进入执行；修改输入请新建流程')
            uploads = []
            for i in dict.fromkeys(ids):
                path = uploaded_path(self.state, i); meta = read_json(path.parent / 'metadata.json')
                uploads.append({'upload_id': i, 'name': meta['filename'], 'sha256': meta['sha256']})
            if len(uploads) > 1 and any(x['name'].lower().endswith('.zip') for x in uploads): raise HTTPException(422, '请选择一个 ZIP 或多个独立文件')
            s['uploads'] = uploads
            s['project_materials'] = project_materials or []
            write_json(self.path(identifier), s); return self.view(s)

    def start(self, identifier, node_id):
        with self.lock:
            s = self.load(identifier)
            definition = next((n for n in self.view(s)['nodes'] if n['id'] == node_id), None)
            if not definition: raise HTTPException(404, '步骤不存在')
            if definition.get('execution_adapter') == 'DISABLED':
                raise HTTPException(409, definition['availability_reason'])
            if not (definition['state']['can_run'] or (node_id == 'adequacy' and definition['state'].get('can_retry_adequacy'))
                    or (node_id == 'prepare' and definition['state'].get('can_retry_preparation'))
                    or (node_id == 'dispatch' and definition['state'].get('can_retry_dispatch'))):
                raise HTTPException(409, definition['state']['reason'] or 'This step cannot run yet')
            if node_id == 'intake':
                for u in s['uploads']: uploaded_path(self.state, u['upload_id'])
                args = ([u['upload_id'] for u in s['uploads']], definition['target'])
                job = self.launch(*args, project_materials=s['project_materials']) if s.get('project_materials') else self.launch(*args)
                s['job_id'] = job['id']
            elif node_id == 'adequacy':
                if not self.launch_adequacy: raise HTTPException(409, 'Adequacy executor is unavailable')
                if not self.artifacts_valid(s['nodes']['context']['artifacts']): raise HTTPException(409, 'Approved context inputs changed')
                previous = s.get('job_id')
                job = self.launch_adequacy(s)
                if previous: s.setdefault('job_history', []).append(previous)
                s['job_id'] = job['id']
            elif node_id == 'prepare' and self.launch_preparation:
                if not self.artifacts_valid(s['nodes']['adequacy']['artifacts']): raise HTTPException(409, 'Approved data assessment changed')
                previous = s.get('job_id'); job = self.launch_preparation(s)
                if previous: s.setdefault('job_history', []).append(previous)
                if s['nodes'][node_id].get('output_signature'):
                    s.setdefault('preparation_history', []).append(copy.deepcopy(s['nodes'][node_id]))
                s['nodes'][node_id] = copy.deepcopy(blank_session()['nodes'][node_id])
                s['job_id'] = job['id']
            elif node_id == 'dispatch':
                if not self.launch_dispatch: raise HTTPException(409,'Clinical dispatch executor is unavailable')
                previous=s.get('job_id'); job=self.launch_dispatch(s)
                if previous: s.setdefault('job_history',[]).append(previous)
                if s['nodes'][node_id]['execution']=='FAILED':
                    s.setdefault('dispatch_history',[]).append(copy.deepcopy(s['nodes'][node_id]))
                s['job_id']=job['id']
            else:
                if node_id == 'prepare':
                    gate = self.state / 'workbench_jobs' / s['job_id'] / 'qc_release.json'
                    write_json(gate, {'at': utcnow(), 'session_id': s['id'], 'adequacy': s['nodes']['adequacy']})
                self.resume(s['job_id'], definition['target'])
            s['nodes'][node_id].update(execution='RUNNING', error=None, failure=None, model_progress=None,
                job_id=s['job_id'], requires_control_trace=True)
            s['nodes'][node_id].setdefault('segments', []).append({'started_at': utcnow(), 'stopped_at': None})
            s['events'].append({'at': utcnow(), 'node': node_id, 'action': 'STARTED'})
            write_json(self.path(identifier), s); return self.view(s)

    def pause(self, identifier):
        with self.lock:
            s = self.load(identifier)
            if s['control_status'] != 'READY': return self.view(s)
            active = [key for key, n in s['nodes'].items() if n['execution'] == 'RUNNING']
            active_branches = []
            if self.tributaries:
                for b in self.tributaries.summaries(identifier):
                    if b['status'] == 'RUNNING':
                        self.tributaries.control(identifier, b['id'], 'pause'); active_branches.append(b['id'])
            if active:
                if not self.pause_job: raise HTTPException(409, '当前执行器尚未接入暂停控制')
                self.pause_job(s['job_id'])
                for key in active: s['nodes'][key]['execution'] = 'PAUSING'
                s['control_status'] = 'PAUSING'
            else: s['control_status'] = 'PAUSING' if active_branches else 'PAUSED'
            s['events'].append({'at': utcnow(), 'node': active[0] if active else 'intake', 'action': 'PAUSE_REQUESTED'})
            write_json(self.path(identifier), s); return self.view(s)

    def continue_run(self, identifier):
        with self.lock:
            s = self.load(identifier)
            if s['control_status'] != 'PAUSED': raise HTTPException(409, '尚未完成暂停，不能继续')
            if s['nodes']['eda']['execution'] == 'PAUSED':
                raise HTTPException(409, BY_ID['eda']['availability_reason'])
            for key, n in s['nodes'].items():
                if n['execution'] != 'PAUSED': continue
                if any(not self.dependency_ready(s, d) for d in self.dependencies(s, key)):
                    raise HTTPException(409, '前置审核已失效，不能继续计算')
                self.resume(s['job_id'], BY_ID[key]['target'])
                n.update(execution='RUNNING', error=None)
                n.setdefault('segments', []).append({'started_at': utcnow(), 'stopped_at': None})
                s['events'].append({'at': utcnow(), 'node': key, 'action': 'RESUMED'})
            s['control_status'] = 'READY'
            write_json(self.path(identifier), s); return self.view(s)

    def clinical_spec(self, identifier, request):
        with self.lock:
            s = self.load(identifier); n = s['nodes']['dispatch']
            if n['execution'] not in {'NOT_STARTED','FAILED'} or any(s['nodes'][k]['execution']!='NOT_STARTED' for k in ['pk','index','results','clinical']):
                raise HTTPException(409, 'Released or active questions are immutable; create a new study cycle for revised definitions.')
            draft=n.get('clinical_draft')
            if draft:
                self.validate_clinical_draft(s)
                if request.draft_signature != draft['signature']:
                    raise HTTPException(409,'Clinical draft changed. Reload the questions before confirming them.')
            keys = {key for key, _, _ in CLINICAL_FIELDS}
            if set(request.values) != keys or any(len(v.strip()) < 2 or len(v) > 10000 for v in request.values.values()) or not request.reviewer.strip():
                raise HTTPException(422, '请逐项填写临床问题；未知请写 UNKNOWN: 原因，并填写确认人')
            value = {**request.model_dump(), 'at': utcnow(), 'scope': 'RESEARCH_QUESTION_CONFIRMATION_ONLY'}
            value['upstream_signatures']={k:s['nodes'][k].get('output_signature') for k in ['context','adequacy','prepare','eda']}
            p = write_json(self.outputs / 'canvas_cycles' / identifier / ('clinical_questions_'+uuid4().hex+'.json'), value)
            if n.get('clinical_spec_ref'): s.setdefault('clinical_spec_history',[]).append(n['clinical_spec_ref'])
            n['clinical_spec'] = value
            n['clinical_spec_ref'] = {'name': 'confirmed_clinical_questions.json', 'path': str(p), 'sha256': sha256(p), 'kind': 'context'}
            s['events'].append({'at': utcnow(), 'node': 'dispatch', 'action': 'CLINICAL_QUESTIONS_CONFIRMED'})
            write_json(self.path(identifier), s); return self.view(s)

    def new_cycle(self, identifier, request):
        with self.lock:
            s = self.load(identifier); n = s['nodes'][request.source_node]
            # Requesting a study revision is not acceptance of results or scientific release.
            # An early adequacy/QC finding may require more data or a revised proposal
            # before any downstream model or final clinical report can be produced.
            if n['execution'] not in {'COMPLETED', 'NEEDS_ATTENTION'} or not self.artifacts_valid(n['artifacts']):
                raise HTTPException(409, 'A completed output or a valid data-issue report is required to request a study revision')
            routes = {'REVISE_PROPOSAL': 'intake', 'ADD_DATA': 'intake', 'RETRIEVE_EVIDENCE': 'context',
                'REASSESS_ADEQUACY': 'adequacy', 'CORRECT_DATA': 'prepare', 'REVISE_EDA': 'eda',
                'REVISE_CLINICAL_QUESTION': 'dispatch', 'REVISE_PK': 'pk', 'REVISE_INDEX': 'index', 'REVIEW_RESULTS': 'results'}
            change_type = request.change_type or next(key for key, target in routes.items() if target == request.target)
            if routes[change_type] != request.target:
                raise HTTPException(422, 'The requested change type does not match its target stage')
            if not request.reviewer.strip() or len(request.reason.strip()) < 5 or len(request.requested_changes.strip()) < 5:
                raise HTTPException(422, '请填写具体反馈、改动要求与确认人')
            child = blank_session('flow_' + uuid4().hex)
            child['parent_cycle'] = {'session_id': identifier, 'target': request.target, 'reason': request.reason,
                'requested_changes': request.requested_changes, 'reviewer': request.reviewer, 'at': utcnow(),
                'source_node': request.source_node, 'change_type': change_type,
                'source_signature': n['output_signature'], 'requires_fresh_review': True,
                'decision': 'REQUEST_NEW_STUDY_CYCLE', 'scientific_acceptance': False,
                'entry_stage': 'intake', 'target_is_revision_scope': True,
                'source_review': n.get('review'),
                'evidence_refs': [{'name': a['name'], 'sha256': a['sha256'],
                    'node_id': request.source_node} for a in n['artifacts']]}
            write_json(self.root / child['id'] / 'session.json', child)
            request_path = self.outputs / 'canvas_cycles' / identifier / ('next_cycle_' + child['id'] + '.json')
            write_json(request_path, {**child['parent_cycle'], 'next_session_id': child['id']})
            s['events'].append({'at': utcnow(), 'node': request.source_node, 'action': 'NEW_CYCLE_REQUESTED',
                'change_type': change_type, 'target': request.target, 'next_session_id': child['id']})
            write_json(self.path(identifier), s)
            return {'new_session': self.view(child), 'request': read_json(request_path)}

    def publish(self, identifier):
        with self.lock:
            s = self.load(identifier)
            if not self.view(s)['can_publish']: raise HTTPException(409, '完整流程与最终临床解释必须先经人工接受')
            dest = self.outputs / 'canvas_cycles' / identifier / ('publication_' + uuid4().hex)
            dest.mkdir(parents=True)
            audit = {'session_id': identifier, 'created_at': utcnow(), 'scope': 'ACCEPTED_RESEARCH_REPORT',
                'architecture': self.view(s)['architecture'], 'project_rules': self.project_rules(s),
                'events': s['events'], 'parent_cycle': s.get('parent_cycle'), 'context_revision': s.get('context_revision'),
                'reviews': {key: n['review'] for key, n in s['nodes'].items()},
                'timing': self.view(s)['timing'],
                'review_checkpoints': {key: self.graph_reviews.export_history(n['langgraph_review']) for key, n in s['nodes'].items() if n.get('langgraph_review')},
                'automatic_validations': {key: n['automatic_validation'] for key, n in s['nodes'].items() if n.get('automatic_validation')},
                'artifacts': {key: [{k: a[k] for k in ['name', 'sha256', 'kind'] if k in a} for a in n['artifacts']] for key, n in s['nodes'].items()}}
            supplements = self.tributaries.summaries(identifier) if self.tributaries else []
            audit['supplemental_branches'] = [self.tributaries.public(b) for b in supplements]
            audit['supplemental_review_checkpoints'] = {b['id']: self.graph_reviews.export_history(b['langgraph_review'])
                for b in supplements if b.get('langgraph_review')}
            execution_files = []
            job_ids = list(dict.fromkeys([*s.get('job_history', []), *([s['job_id']] if s.get('job_id') else [])]))
            for job_id in job_ids:
                job_root = self.state / 'workbench_jobs' / job_id
                for pattern in ['request.json', 'status.json', 'plan.json', 'snakemake_command.json',
                                'qc_release.json', 'contracts/*.json', 'receipts/*.json', 'control_traces/*.json',
                                'attempts/*/*/execution.json', 'attempts/*/*/*.log', '*.log']:
                    execution_files.extend(job_root.glob(pattern))
            execution_root = self.state / 'workbench_jobs'
            execution_files = sorted(set(p for p in execution_files if p.is_file() and p.resolve().is_relative_to(execution_root.resolve())))
            audit['execution_files'] = [{'name': p.relative_to(execution_root).as_posix(), 'sha256': sha256(p)} for p in execution_files]
            audit['execution_audit_status'] = 'RECORDED' if execution_files else 'NO_WORKER_RECORDS'
            write_json(dest / 'audit.json', audit)
            with zipfile.ZipFile(dest / 'report_and_audit.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.write(dest / 'audit.json', 'audit.json')
                for p in execution_files: archive.write(p, 'execution/' + p.relative_to(execution_root).as_posix())
                for key, n in s['nodes'].items():
                    for i, a in enumerate(n['artifacts']): archive.write(a['path'], key + '/' + str(i) + '_' + Path(a['name']).name)
                for i, uploaded in enumerate(s['uploads']):
                    archive.write(uploaded_path(self.state, uploaded['upload_id']), 'inputs/' + str(i) + '_' + Path(uploaded['name']).name)
                for branch in supplements:
                    for item in branch['artifacts'] + branch['handoffs']:
                        if self.artifacts_valid([item]): archive.write(item['path'], 'supplements/' + branch['id'] + '/' + item['name'])
                    for name in ['request.json', 'review.json']:
                        p = Path(branch['request_path']).parent / name
                        if p.is_file(): archive.write(p, 'supplements/' + branch['id'] + '/' + name)
            s['events'].append({'at': utcnow(), 'node': 'clinical', 'action': 'REPORT_PUBLISHED', 'path': str(dest)})
            write_json(self.path(identifier), s)
            return dest / 'report_and_audit.zip'

    def review(self, identifier, node_id, decision):
        with self.lock:
            s = self.load(identifier)
            definition = next((n for n in self.view(s)['nodes'] if n['id'] == node_id), None)
            if not definition: raise HTTPException(404, '步骤不存在')
            if not definition['state']['can_review']: raise HTTPException(409, '步骤未完成、上游未通过或本结果已冻结，不能提交审核')
            n = s['nodes'][node_id]
            if decision.output_signature != n['output_signature']: raise HTTPException(409, '审核对象已改变，请重新检查输出')
            if not decision.reviewer.strip(): raise HTTPException(422, '请填写审核人')
            if decision.decision != 'APPROVE' and len(decision.rationale.strip()) < 5:
                raise HTTPException(422, '要求修改或不通过时，请填写具体原因（至少 5 个字符）')
            amendment = self.objective_gate(s, node_id, decision)
            value = {**decision.model_dump(), 'rationale': decision.rationale.strip(), 'at': utcnow(), 'scope': 'THIS_STEP_ONLY_NO_HUMAN_EXTRAPOLATION', 'id': uuid4().hex}
            if node_id != 'context':
                value.pop('objective_decision'); value.pop('objective_correction')
            if (n.get('langgraph_review') or {}).get('status') != 'INTERRUPTED':
                n['langgraph_review'] = self.graph_reviews.begin(identifier, node_id, n['output_signature'],
                    [{key: a[key] for key in ['name', 'sha256', 'kind'] if key in a} for a in n['artifacts']], self.project_rules(s))
            n['langgraph_review'] = self.graph_reviews.resume(n['langgraph_review'], value)
            value['langgraph'] = n['langgraph_review']
            write_json(self.root / identifier / 'reviews' / (value['id'] + '.json'), value)
            n['review'] = value; s['events'].append({'at': utcnow(), 'node': node_id, 'action': value['decision']})
            if node_id == 'context':  # Sessions from before CC004 publication have no pending record yet.
                n.setdefault('objective_review', {'rule_id': 'CC004'}).update(status=decision.objective_decision,
                    reviewer=decision.reviewer, at=value['at'], review_id=value['id'])
            if amendment and n['langgraph_review'].get('status') == 'APPROVED':
                p = write_json(self.outputs / 'canvas_cycles' / identifier / ('scope_amendment_' + uuid4().hex + '.json'), amendment)
                s['scope_amendment'] = {'path': str(p), 'sha256': sha256(p)}
                n['objective_review']['scope_amendment'] = {'sha256': s['scope_amendment']['sha256'], 'path_field': '/objective'}
                s['events'].append({'at': utcnow(), 'node': 'context', 'action': 'USER_OBJECTIVE_CORRECTED',
                    'changed_paths': ['/objective'], 'scientific_results_accepted': False})
            write_json(self.path(identifier), s); return self.view(s)

    def objective_gate(self, s, node_id, decision):
        """CC004 human gate: Context is approved only with an explicit objective judgement."""
        if node_id != 'context':
            if decision.objective_decision or decision.objective_correction.strip():
                raise HTTPException(422, '目标判断只用于 Context compression 审核')
            return None
        choice = decision.objective_decision
        if not choice:
            raise HTTPException(422, 'CC004：请先判断压缩后的整体研究目标（CONFIRMED / CORRECTED / INCORRECT / OFF_SCOPE / MISSING）')
        if decision.decision == 'APPROVE' and choice not in {'CONFIRMED', 'CORRECTED'}:
            raise HTTPException(422, 'CC004：目标写错、写偏或缺失时不能通过；请选择要求修改或不通过，或填写正确目标（CORRECTED）')
        if decision.decision != 'APPROVE' and choice == 'CORRECTED':
            raise HTTPException(422, 'CC004：填写了正确目标时请选择通过；否则请选择 INCORRECT、OFF_SCOPE 或 MISSING')
        correction = decision.objective_correction.strip()
        if choice != 'CORRECTED':
            if correction: raise HTTPException(422, 'CC004：只有 CORRECTED 才填写更正后的目标')
            return None
        if s.get('project_rules_ref'):
            # A rule pack describes one exact Context; adequacy refuses to combine it with a later amendment.
            raise HTTPException(409, 'CC004：本 Context 的项目规则已按原目标发布，不能在审核时直接改目标；'
                                     '请选择 INCORRECT 并要求修改（在原因里写出正确目标），再用更正后的 proposal 重跑压缩和项目规则')
        if len(correction) < 5: raise HTTPException(422, 'CC004：请填写更正后的完整研究目标（至少 5 个字符）')
        if len(decision.rationale.strip()) < 5: raise HTTPException(422, 'CC004：更正目标时请说明原因（至少 5 个字符）')
        main = next((a for a in s['nodes']['context']['artifacts'] if a['name'] == 'main.json'), None)
        if not main or not self.artifacts_valid([main]): raise HTTPException(409, 'Context 输出已改变，请重新检查')
        before = read_json(main['path'])['objective']
        if correction == before.strip(): raise HTTPException(422, 'CC004：更正后的目标与原目标相同；请选择 CONFIRMED')
        from .scope_amendments import apply_amendment
        amendment = {'schema_version': '1.0', 'at': utcnow(), 'context_signature': s['nodes']['context']['output_signature'],
            'instruction': 'CC004 objective correction at Context review: ' + decision.rationale.strip(),
            'submitted_by': decision.reviewer.strip(), 'changes': [{'path': '/objective', 'before': before, 'after': correction}],
            'confirmed': True, 'base_main': {'path': main['path'], 'sha256': main['sha256']},
            'authority': 'EXPLICIT_USER_SCOPE_CHANGE', 'origin': 'CC004_CONTEXT_REVIEW',
            'scientific_results_accepted': False, 'supersedes': s.get('scope_amendment')}
        try: apply_amendment(read_json(main['path']), amendment)
        except ValueError as exc: raise HTTPException(422, str(exc)) from exc
        return amendment

    def clinical_snapshot(self, s):
        from .adequacy import file_ref
        p=write_json(self.outputs/'canvas_cycles'/s['id']/('dispatch_inputs_'+uuid4().hex+'.json'),
            {'at':utcnow(),'session_id':s['id'],'nodes':{k:copy.deepcopy(s['nodes'][k]) for k in ['context','adequacy','prepare','eda']}})
        return file_ref(p)

    def validate_clinical_draft(self, s):
        from .clinical_dispatch import inputs
        draft=s['nodes']['dispatch'].get('clinical_draft')
        if not draft: raise HTTPException(409,'Prepare the clinical question draft first.')
        if not self.artifacts_valid(draft['artifacts']): raise HTTPException(409,'Clinical draft files changed. Prepare a new draft.')
        snapshot, *_=inputs(draft['snapshot'])
        for key,node in snapshot['nodes'].items():
            if node['output_signature'] != s['nodes'][key].get('output_signature'):
                raise HTTPException(409,'Upstream '+key+' changed. Prepare a new clinical draft.')
        return draft

    def clinical_draft(self, identifier):
        from .clinical_dispatch import build
        with self.lock:
            s=self.load(identifier); n=s['nodes']['dispatch']
            if n['execution'] not in {'NOT_STARTED','FAILED'} or any(s['nodes'][k]['execution']!='NOT_STARTED' for k in ['pk','index','results','clinical']):
                raise HTTPException(409,'Released or active dispatch is immutable. Create a new study cycle for revised questions.')
            if s.get('control_status')!='READY': raise HTTPException(409,'Resume the workflow before preparing a clinical draft.')
            snapshot=self.clinical_snapshot(s)
            folder=self.outputs/'canvas_cycles'/identifier/('clinical_draft_'+uuid4().hex)
            report=build(snapshot,folder)
            artifacts=read_json(folder/'artifact_manifest.json')['files']
            questions=read_json(folder/'clinical_questions.json')
            if n.get('clinical_draft'): s.setdefault('clinical_draft_history',[]).append(n['clinical_draft'])
            n['clinical_draft']={'snapshot':snapshot,'signature':fingerprint(artifacts),'artifacts':artifacts,
                'values':questions['values'],'index_exposure_source':questions['index_exposure_source'],'report':report,
                'generator_version':questions.get('generator_version'),
                'field_evidence':questions.get('field_evidence',{}),'evidence_catalog':questions.get('evidence_catalog',{})}
            # A replacement draft never silently inherits a prior confirmation.
            n.pop('clinical_spec',None);n.pop('clinical_spec_ref',None)
            if n['execution']=='FAILED':
                s.setdefault('dispatch_history',[]).append(copy.deepcopy(n))
                n.update(execution='NOT_STARTED',error=None,failure=None)
            s['events'].append({'at':utcnow(),'node':'dispatch','action':'CLINICAL_DRAFT_PREPARED'})
            write_json(self.path(identifier),s);return self.view(s)

    def assigned_context(self, identifier, branch):
        if branch not in {'pk','index','clinical'}: raise HTTPException(404,'Unknown downstream branch')
        with self.lock:
            s=self.load(identifier); node=s['nodes']['dispatch']
            if not self.approved(node) or any(not self.dependency_ready(s,k) for k in ['context','prepare','eda']):
                raise HTTPException(409,'The branch handoff is pending approved EDA and the exact Clinical questions dispatch review. Drafts are available for inspection only.')
            if not self.artifacts_valid(node['artifacts']): raise HTTPException(409,'Dispatch artifacts changed; handoff is blocked.')
            artifact=next((a for a in node['artifacts'] if a['name']==branch+'_context.json'),None)
            if not artifact: raise HTTPException(409,'The branch context was not generated.')
            value=read_json(artifact['path'])
            from .context_builder import verify_branch_handoff
            try:
                verify_branch_handoff(value)
            except (ValueError, OSError) as exc:
                raise HTTPException(409, 'Branch context inputs changed; rebuild dispatch.') from exc
            incoming=self.tributaries.incoming(identifier,branch) if self.tributaries else []
            if any(item['status']!='APPROVED' for item in incoming):
                raise HTTPException(409,'Assigned supplemental data still need processing and approval.')
            supplemental=[]
            for item in incoming:
                approved_branch=self.tributaries.load(identifier,item['branch_id'])
                supplemental.extend(h for h in approved_branch['handoffs'] if h['target']==branch)
            for dataset in value.get('data_files',[]):
                for field in ['data','csv','metadata','excluded_records']:
                    if not self.artifacts_valid([dataset[field]]): raise HTTPException(409,'An assigned data file changed. Return to QC.')
            from .task_rules import scoped_context
            value, projection = scoped_context(value, 'animal_pk' if branch=='pk' else branch)
            return {'status':'ROUTING_APPROVED_NOT_MODEL_RELEASE','context':value,
                'source_context_ref':artifact,'rule_audit':projection,
                'projection_notice':'Task-scoped view of the approved source; source files and scientific approvals are unchanged.',
                'dispatch_output_signature':node['output_signature'],'review':node['review'],
                'supplemental_handoffs':supplemental,'model_release':False}

    def save_preparation_plan(self, identifier, request):
        with self.lock:
            s = self.load(identifier); n = s['nodes']['prepare']
            state = next(x for x in self.view(s)['nodes'] if x['id'] == 'prepare')['state']
            if not state.get('can_retry_preparation'): raise HTTPException(409, 'Finish or pause the current attempt before submitting corrections; downstream work must not have started.')
            if request.output_signature != n.get('output_signature', ''): raise HTTPException(409, 'Preparation output changed; reload before correcting its mapping.')
            if not isinstance(request.plan.get('ranges', {}), dict) or not isinstance(request.plan.get('tables', {}), dict):
                raise HTTPException(422, 'ranges and tables must be JSON objects.')
            for key, value in request.plan.get('tables', {}).items():
                if not isinstance(value, dict) or not isinstance(value.get('columns', {}), dict): raise HTTPException(422, 'Each table needs a columns object.')
                if set(value.get('columns', {})) - {'time_h','concentration_mg_L'}: raise HTTPException(422, 'Supported normalized fields are time_h and concentration_mg_L. Other source columns remain intact.')
                if any(not isinstance(v,str) or not v.strip() for v in value.get('columns',{}).values()): raise HTTPException(422, 'Map each field to an exact source header.')
            if len(request.rationale.strip()) < 5: raise HTTPException(422, 'Describe the mapping correction.')
            from .adequacy import file_ref
            record = {'schema_version':'1.0','ranges':request.plan.get('ranges',{}),
                'tables':{k:{'columns':v.get('columns',{})} for k,v in request.plan.get('tables',{}).items()},
                'rationale':request.rationale.strip(),'at':utcnow(),'base_output_signature':request.output_signature,
                'adequacy_signature':s['nodes']['adequacy']['output_signature'], 'scientific_approval':False}
            path = write_json(self.outputs/'canvas_cycles'/identifier/('preparation_plan_'+uuid4().hex+'.json'), record)
            s['preparation_plan'] = file_ref(path)
            s['events'].append({'at':utcnow(),'node':'prepare','action':'PREPARATION_PLAN_SAVED','plan':file_ref(path)})
            write_json(self.path(identifier),s)
            return self.view(s)


def canvas_router(store):
    router = APIRouter(prefix='/workflow')
    from .ui_rule_files import router as rule_files_router
    router.include_router(rule_files_router)
    @router.get('/template')
    def template(): return store.view(blank_session())
    @router.get('/rules-draft')
    def rules_draft():
        # Read-only review material, deliberately never loaded by project_rules().
        return read_json(RULES / 'drafts/general_pkpd_rules.json')
    @router.post('/sessions', status_code=201)
    def create(): return store.create()
    @router.get('/sessions/{identifier}')
    def session(identifier: str):
        with store.lock: return store.view(store.load(identifier))
    @router.post('/sessions/{identifier}/files')
    def bind(identifier: str, request: FilesInput): return store.bind_files(identifier, request.upload_ids, request.project_materials)
    @router.post('/sessions/{identifier}/pause', status_code=202)
    def pause(identifier: str): return store.pause(identifier)
    @router.post('/sessions/{identifier}/continue', status_code=202)
    def continue_run(identifier: str): return store.continue_run(identifier)
    @router.post('/sessions/{identifier}/clinical-questions')
    def clinical_questions(identifier: str, request: ClinicalSpec): return store.clinical_spec(identifier, request)
    @router.post('/sessions/{identifier}/clinical-questions/draft')
    def clinical_draft(identifier: str): return store.clinical_draft(identifier)
    @router.get('/sessions/{identifier}/clinical-questions/draft/files/{name}')
    def clinical_draft_file(identifier: str, name: str):
        with store.lock:
            draft=store.validate_clinical_draft(store.load(identifier))
            artifact=next((a for a in draft['artifacts'] if a['name']==name),None)
            if not artifact: raise HTTPException(404,'Draft artifact not found')
            return FileResponse(artifact['path'],filename=name)
    @router.get('/sessions/{identifier}/nodes/{branch}/assigned-context')
    def assigned_context(identifier: str, branch: str): return store.assigned_context(identifier,branch)
    @router.post('/sessions/{identifier}/scope-amendments')
    def scope_amendment(identifier: str, request: ScopeAmendment): return save_amendment(store, identifier, request)
    @router.post('/sessions/{identifier}/preparation-plan')
    def preparation_plan(identifier: str, request: PreparationPlan): return store.save_preparation_plan(identifier, request)
    @router.get('/sessions/{identifier}/preparation-plan')
    def current_preparation_plan(identifier: str):
        from .adequacy import check_ref
        with store.lock:
            s = store.load(identifier)
            if s.get('preparation_plan'):
                check_ref(s['preparation_plan']); value = read_json(s['preparation_plan']['path'])
                return {k:value[k] for k in ['schema_version','ranges','tables']}
            for n in [s['nodes']['prepare'], *reversed(s.get('preparation_history',[]))]:
                for artifact in n.get('artifacts',[]):
                    if artifact['name'] == 'preparation_plan.template.json':
                        check_ref(artifact); return read_json(artifact['path'])
            return {'schema_version':'1.0','ranges':{},'tables':{}}
    @router.post('/sessions/{identifier}/cycles', status_code=201)
    def cycle(identifier: str, request: CycleRequest): return store.new_cycle(identifier, request)
    @router.post('/sessions/{identifier}/publish')
    def publish(identifier: str): return FileResponse(store.publish(identifier), filename='report_and_audit.zip')
    @router.post('/sessions/{identifier}/nodes/{node_id}/start', status_code=202)
    def start(identifier: str, node_id: str): return store.start(identifier, node_id)
    @router.post('/sessions/{identifier}/nodes/{node_id}/review')
    def review(identifier: str, node_id: str, request: Decision): return store.review(identifier, node_id, request)
    @router.post('/sessions/{identifier}/nodes/intake/coverage-resolutions')
    def coverage_resolution(identifier: str, request: CoverageResolution): return store.resolve_coverage(identifier, request)
    @router.get('/sessions/{identifier}/nodes/{node_id}/artifacts/{name}')
    def artifact(identifier: str, node_id: str, name: str):
        with store.lock:
            s = store.load(identifier); n = s['nodes'].get(node_id)
            if not n or not store.artifacts_valid(n['artifacts']): raise HTTPException(409, '尚无有效产物')
            value = next((a for a in n['artifacts'] if a['name'] == name), None)
            if not value: raise HTTPException(404, '文件不存在')
            return FileResponse(value['path'], filename=name)
    return router
