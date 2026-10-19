"""Prefect owns run state; Snakemake owns file dependencies and parallelism."""
import os
import subprocess
import sys
from pathlib import Path
from .common import BACKEND, PROJECT, read_json, write_json, utcnow
from .workflow_runtime import make_plan
from .job_control import run_interruptible, PauseRequested, mark_paused_attempts

os.environ.setdefault('PREFECT_SERVER_ANALYTICS_ENABLED', 'false')
os.environ.setdefault('PREFECT_HOME', str(PROJECT / 'outputs/prefect_local'))
# Keep local scheduler traffic out of the machine's external HTTP proxy.
_bypass = ','.join(filter(None, [os.environ.get('NO_PROXY', os.environ.get('no_proxy', '')), 'localhost,127.0.0.1,::1']))
os.environ['NO_PROXY'] = os.environ['no_proxy'] = _bypass
from prefect import flow, task
from prefect.cache_policies import NO_CACHE
from prefect.runtime import flow_run


@task(name='execute-file-dag', retries=0, cache_policy=NO_CACHE, persist_result=False)
def run_dag(request_path, target, dry_run=False):
    try:
        return _execute_dag(request_path, target, dry_run)
    except PauseRequested as exc:
        # An intentional pause is a control result, not a failed Prefect task.
        return {'status': 'PAUSED', 'reason': str(exc)}


def _execute_dag(request_path, target, dry_run=False):
    spec = read_json(request_path); folder = Path(spec['job_dir']); plan = make_plan(spec, target=target)
    if target not in plan['targets']: raise ValueError('Unsupported target: ' + target)
    command = [sys.executable, '-I', '-X', 'utf8', '-m', 'snakemake',
        '--snakefile', str(BACKEND / 'research_pipeline/workflow/Snakefile'), '--directory', str(folder),
        '--cores', str(plan['cpu']['total_slots']), '--scheduler', 'greedy', '--force-use-threads', '--retries', '0', '--rerun-incomplete',
        '--config', 'plan=' + str(folder / 'plan.json'), 'target=' + plan['targets'][target]]
    if dry_run: command.append('--dry-run')
    logfile = folder / ('snakemake_' + utcnow().replace(':', '-') + '.log')
    write_json(folder / 'snakemake_command.json', {'command': command, 'at': utcnow(), 'dry_run': dry_run})
    with logfile.open('w', encoding='utf-8') as log:
        # A killed incomplete DAG may leave its own lock. Unlock this isolated job
        # directory only on an acknowledged pause, before restarting its executor.
        if (folder / 'needs_unlock.flag').exists():
            code = run_interruptible([*command, '--unlock'], pause_file=folder / 'pause.flag', stdout=log, cwd=PROJECT)
            if code: raise RuntimeError('Could not unlock the paused job directory')
            (folder / 'needs_unlock.flag').unlink()
        code = run_interruptible(command, pause_file=folder / 'pause.flag', stdout=log, cwd=PROJECT,
                                 process_record=folder / 'active_dag.json')
    if code: raise RuntimeError('Snakemake stopped:\n' + logfile.read_text(encoding='utf-8', errors='replace')[-10000:])
    return str(logfile)


@flow(name='pmb-file-workflow', retries=0, persist_result=False, log_prints=True)
def research_flow(request_path, target=None, dry_run=False):
    spec = read_json(request_path); folder = Path(spec['job_dir']); target = target or spec.get('stop_after', 'data_preparation')
    old = read_json(folder / 'status.json') if (folder / 'status.json').exists() else {}
    status = {**old, 'id': spec['id'], 'created_at': spec['created_at'], 'status': 'RUNNING',
        'stage': 'Prefect 调度 · Snakemake 文件工作流', 'events': old.get('events', []),
        'prefect_flow_run_id': str(flow_run.id), 'scheduler': 'Prefect', 'executor': 'Snakemake'}
    status.pop('error', None); status.update(target=target, started_at=utcnow())
    status['events'].append({'stage': status['stage'], 'at': utcnow(), 'target': target})
    write_json(folder / 'status.json', status)
    try:
        log = run_dag(request_path, target, dry_run)
        if isinstance(log, dict) and log.get('status') == 'PAUSED':
            raise PauseRequested(log['reason'])
        status.update(status='DRY_RUN_PASSED' if dry_run else ('COMPLETED_PENDING_HUMAN_REVIEW' if target == 'exploratory_results' else 'WAITING_FOR_HUMAN_REVIEW'),
            stage='依赖检查完成' if dry_run else '到达审核边界 · ' + target, finished_at=utcnow(), target=target, scientific_release=False, snakemake_log=log)
        if target == 'animal_pk_architecture' and not dry_run:
            status.update(status='ARCHITECTURE_READY',stage='Architecture files ready; no PK models fitted')
        from .workflow_runtime import context_requires_project_rules
        if (target == 'project_rules' or (target == 'context' and context_requires_project_rules(spec))) and not dry_run:
            report = read_json(Path(spec['out']) / 'project_rules/published/report.json')
            from .project_rule_agent import publication_ready
            published = publication_ready(report, allow_provisional=spec.get('demo_key_rules') is True)
            status.update(status=(('WAITING_FOR_HUMAN_REVIEW' if published else 'REVISION_REQUIRED') if target == 'context' else report['status']),
                stage=('Provisional demo key Rules ready; scientific refinement deferred' if report['status'] == 'DEMO_PROVISIONAL_RULES'
                       else 'Reviewed project rules published; ready for downstream adequacy assessment') if published else 'Project rules need revision; no downstream handoff published',
                project_rules_report=str(Path(spec['out']) / 'project_rules/published/report.json'),
                scientific_release=False)
        if target == 'pk_reference_pilot' and not dry_run:
            status.update(status='REFERENCE_ADVICE_READY',stage='PK reference pilot complete; suggestions only, no project rules activated')
            if spec.get('revise_main'):
                status.update(status='MAIN_REVISION_READY',stage='Revised main.json and independent review ready; proposed changes await scientific review')
        if target in {'animal_pk_execution','animal_pk_summary','animal_pk_individual'} and not dry_run:
            report=read_json(Path(spec['out'])/'animal_pk/report.json')
            status.update(status='WAITING_FOR_HUMAN_REVIEW' if target!='animal_pk_execution' else 'PK_AGENT_COMPLETED',stage='PK agent completed: '+report['status'],
                          pk_status=report['status'],llm_calls=report.get('llm_calls',0),fit_calls=report.get('fit_calls',0))
        if target == 'exploratory_results' and not dry_run: status['run_id'] = spec['id']
        write_json(folder / 'status.json', status); return status
    except PauseRequested:
        mark_paused_attempts(folder)
        (folder / 'needs_unlock.flag').touch()
        status.update(status='PAUSED', stage='已暂停 · 保留已完成块', finished_at=utcnow(), target=target,
                      resume_policy='RERUN_INCOMPLETE_BLOCK')
        write_json(folder / 'status.json', status)
        return status
    except Exception as exc:
        from .context_feedback import context_feedback
        feedback = context_feedback(spec['out'], status['started_at']) if target in {'context', 'data_preparation'} else None
        if feedback:
            status.update(status='REVISION_REQUIRED', stage='Context revision required', finished_at=utcnow(),
                          error=feedback['summary'], context_feedback=feedback, scientific_release=False,
                          technical_error=str(exc))
            write_json(folder / 'status.json', status)
            return status
        from .execution_feedback import execution_feedback
        failure = execution_feedback(spec['out'], str(exc), status['started_at'], target)
        if spec.get('data_agents_version')=='2.0':
            stopped=Path(spec['out'])/'data_agents/stopped.json'
            if stopped.is_file():
                diagnosis=read_json(stopped)
                action=diagnosis.get('next_action',diagnosis.get('corrective_action','Correct the cited Data input and explicitly retry.'))
                failure={**failure,'code':diagnosis.get('error_code',diagnosis.get('code','DATA_AGENT_ERROR')),
                    'stage':diagnosis['stage'],'stage_label':'Data agent: '+diagnosis['stage'],
                    'title':'Data agent requires correction','summary':diagnosis['reason'],
                    'known_facts':[diagnosis['reason']], 'proposal_change_required':False,
                    'materials_note':'Inspect the specific agent diagnosis. A contract or execution error alone does not establish missing scientific data.',
                    'suggested_actions':[action],'next_steps':[action],'evidence_refs':[{'path':str(stopped)}]}
        if target == 'project_rules':
            stopped = Path(spec['out']) / 'project_rules/stopped.json'
            if stopped.is_file():
                rules_failure = read_json(stopped)
                failure = {**failure, 'code': rules_failure['error_code'], 'stage': rules_failure['stage'],
                    'stage_label': 'Project rules agent stopped', 'summary': rules_failure['reason'],
                    'title': 'Project rule extraction or review needs correction',
                    'proposal_change_required': False,
                    'materials_note': 'This execution error requests correction of the cited agent output or input contract; it does not establish missing scientific data.',
                    'known_facts': [rules_failure['reason']],
                    'suggested_actions': [rules_failure['next_action']],
                    'evidence_refs': [{'path': str(stopped)}], 'next_steps': [rules_failure['next_action']]}
        if target=='animal_pk_execution':
            reports=sorted((Path(spec['out'])/'animal_pk').rglob('failure.json'),key=lambda p:p.stat().st_mtime)
            if reports:
                pk_failure=read_json(reports[-1])
                failure={**failure,**pk_failure,'stage':'animal_pk_execution','stage_label':'Animal PK agent stopped',
                    'evidence_refs':[{'path':str(reports[-1])}],
                    'next_steps':[pk_failure['next_action']]}
        status.update(status='STOPPED_ON_ERROR', stage=failure['stage_label'], error=failure['summary'],
                      failure=failure, technical_error=str(exc), finished_at=utcnow(), scientific_release=False)
        write_json(folder / 'status.json', status)
        return status


def main():
    import argparse
    p = argparse.ArgumentParser(); p.add_argument('request'); p.add_argument('--target'); p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()
    from .graph_execution import run_controlled
    try: run_controlled(str(Path(args.request).resolve()), args.target, args.dry_run)
    except Exception as exc:
        spec = read_json(args.request); folder = Path(spec['job_dir'])
        current = read_json(folder / 'status.json') if (folder / 'status.json').exists() else {'id': spec['id'], 'created_at': spec['created_at']}
        current.update(status='STOPPED_ON_ERROR', stage='调度或执行失败 · 已停止', error=str(exc), finished_at=utcnow())
        write_json(folder / 'status.json', current); raise

if __name__ == '__main__': main()
