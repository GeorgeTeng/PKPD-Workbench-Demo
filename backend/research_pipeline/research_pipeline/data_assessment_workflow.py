"""Coverage -> scoped Necessity opinion -> English summary -> human decision."""
import os
import time
from pathlib import Path
from . import data_coverage_scoped as coverage, data_necessity_scoped as necessity
from . import data_human_summary_scoped as human_summary, data_direct_runtime as rt
from .common import read_json, write_json, utcnow, PROJECT


def run(plan, source_view, main, local_mp, out, *, build_only=False, generator=None,
        review_state=None, reuse_coverage=None, reuse_necessity=None, contract=None):
    if contract not in (None, 'original'):
        rt.fail('Unknown explicit assessment contract')
    # New current plan contract selects matching consumers. Historical v4 inputs
    # keep their original scoped readers and signatures for replay/tests.
    if contract == 'original':
        from . import data_coverage_direct as coverage, data_necessity_decisions as necessity
        from . import data_human_summary_v3 as human_summary
    elif read_json(plan).get('version') == 'REQUIREMENT_PLAN_6.0':
        from . import data_coverage_scoped_v3 as coverage, data_necessity_scoped_v6 as necessity
        from . import data_human_summary_scoped_v5 as human_summary
    elif read_json(plan).get('version') in {'REQUIREMENT_PLAN_5.0','REQUIREMENT_PLAN_5.1'}:
        from . import data_coverage_scoped_v3 as coverage, data_necessity_scoped_v5 as necessity
        from . import data_human_summary_scoped_v4 as human_summary
    else:
        coverage, necessity, human_summary = (globals()[name] for name in
            ('coverage','necessity','human_summary'))
    from .data_direct_workflow import report
    out=Path(out).resolve()
    selection_path=out/'execution_contract.json'
    selection={'contract':'original','coverage':'DIRECT_DR_COVERAGE_1.0',
               'necessity':'DIRECT_NECESSITY_3.0','summary':'DATA_HUMAN_SUMMARY_3.0'}
    if selection_path.exists():
        if contract != 'original' or read_json(selection_path)!=selection:
            rt.fail('Assessment resume requires the same explicit original contract option')
    elif contract == 'original':
        if out.exists() and any(out.iterdir()):
            rt.fail('Existing assessment has no original contract binding; use a new directory')
        write_json(selection_path,selection)
    refs={k:rt.file_ref(p) for k,p in [('plan',plan),('source_view',source_view),('main',main),('local_mp',local_mp)]}
    if reuse_coverage:
        refs['reused_coverage']=rt.file_ref(reuse_coverage)
    if reuse_necessity:
        refs['reused_necessity']=rt.file_ref(reuse_necessity)
    if (out/'inputs.json').exists() and read_json(out/'inputs.json')!=refs:
        rt.fail('Assessment run belongs to different inputs')
    write_json(out/'inputs.json',refs)
    started=time.monotonic()
    state={'pid':os.getpid(),'started_at':utcnow(),'aggregate_time_limit':None,
           'scientific_approval':False,'downstream_executed':False}
    def emit(stage,status):
        state.update(stage=stage,status=status,at=utcnow(),elapsed_seconds=time.monotonic()-started)
        write_json(out/'runner_status.json',state)
        print(stage+': '+status,flush=True)
    try:
        cp=Path(reuse_coverage).resolve() if reuse_coverage else out/'coverage/coverage.json'
        if reuse_coverage:
            emit('COVERAGE','REUSING_VERIFIED_RESULT')
            cov=coverage.verify_result(cp)
            if any(cov['bindings'][k]!=refs[k] for k in ('plan','source_view','main')):
                rt.fail('Reused Coverage belongs to different inputs')
        else:
            emit('COVERAGE','PREPARING')
            if not (out/'coverage/build.json').exists():
                coverage.prepare(plan,source_view,main,out/'coverage')
            coverage.verify_prepared(out/'coverage')
            if build_only:
                emit('COVERAGE','PREPARED_NO_PROVIDER_CALLS')
                return read_json(out/'coverage/preflight.json')
            emit('COVERAGE','RUNNING')
            coverage.run_prepared(out/'coverage',generator=generator)
            cov=coverage.verify_result(cp)
        np=Path(reuse_necessity).resolve() if reuse_necessity else out/'necessity/necessity.json'
        if reuse_necessity:
            emit('NECESSITY','REUSING_VERIFIED_RESULT')
            nec=necessity.verify_result(np)
            if any(nec['bindings'][k]!=rt.file_ref(p) for k,p in [('coverage',cp),('main',main),('local_method_profiles',local_mp)]):
                rt.fail('Reused Necessity belongs to different inputs')
            write_json(out/'necessity_ref.json',rt.file_ref(np))
        else:
            emit('NECESSITY','PREPARING')
            if (out/'necessity/prepared.json').exists():
                prepared=read_json(out/'necessity/prepared.json')
                rt.verify_refs(prepared['bindings'])
                if any(prepared['bindings'][k]!=rt.file_ref(p) for k,p in [('coverage',cp),('main',main),('local_method_profiles',local_mp)]):
                    rt.fail('Prepared Necessity belongs to different inputs')
            else:
                if necessity.__name__.endswith('data_necessity_decisions'):
                    from .data_necessity_prompt import prepare as prepare_necessity
                    prepare_necessity(cp,main,local_mp,out/'necessity')
                else:
                    necessity.prepare(cp,main,local_mp,out/'necessity')
        if build_only:
            emit('NECESSITY','PREPARED_NO_PROVIDER_CALLS')
            return {'reused_coverage':rt.file_ref(cp),'provider_calls':0}
        if not reuse_necessity:
            emit('NECESSITY','RUNNING')
            necessity.run_prepared(out/'necessity',generator=generator)
            nec=necessity.verify_result(np)
        emit('HUMAN_SUMMARY','RUNNING')
        human_summary.prepare(np,out/'human_summary')
        human_summary.run_prepared(out/'human_summary',generator=generator)
        human_summary.verify_result(out/'human_summary/summary.json')
        rt.verify_refs(refs)
        result=report(out,cov,nec,necessity_path=np)
        if generator is None:
            from .data_direct_review import DirectDataReview
            gate=DirectDataReview(review_state or PROJECT/'outputs/workbench_state',PROJECT/'outputs').publish(out)
            write_json(out/'human_gate.json',gate)
            emit('HUMAN_GATE','AWAITING_HUMAN_REVIEW')
        else:
            emit('REPORT','COMPLETE')
        return result
    except BaseException as exc:
        state['error']=str(exc)
        emit(state.get('stage','UNKNOWN'),'FAILED_RETAINED')
        raise
