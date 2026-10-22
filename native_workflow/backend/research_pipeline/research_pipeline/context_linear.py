"""Opt-in ContextBuilder execution. One dispatch per task, no model repair loop.

Existing stage adapters select evidence and validate
science; this module assembles, records and serializes their model requests.
"""
import argparse
import html
import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from ctxcomp import context_dispatch, engine, model_view, providers
from ctxcomp.io import canonical, digest
from . import context_builder as cb
from . import context_model_view as cmv
from . import context_budget, context_effective_rules, context_routes, context_optimization
from .common import read_json, write_json

ROUTES = {
    'context': ('compression', 'extract'),
    'context_review': ('compression', 'review'),
    'DR': ('data', 'requirements'),
    'DIRECT_DR_COVERAGE': ('data', 'coverage'),
    'NECESSITY_IMPACT_AND_ADVICE_ONLY': ('data', 'necessity'),
    'NECESSITY_SCOPED_ASSESSMENT': ('data', 'necessity'),
    'HUMAN_REVIEW_SUMMARY_ONLY': ('data', 'human_summary'),
    **{call: ('eda', operation) for call, operation in context_routes.EDA.items()},
}
ORDER = {'compression.extract': 0, 'compression.review': 1,
         'data.requirements': 2, 'data.coverage': 3,
         'data.necessity': 4, 'data.human_summary': 5, 'data.human_summary_legacy': 5,
         'eda.plan': 6, 'eda.finalize': 6.5, 'eda.findings': 7, 'eda.review': 8}


def assemble(request, bindings=None):
    if digest(request['payload']) != request['request_sha256']:
        cb.fail('Request hash mismatch before dispatch')
    route = context_routes.select(request['payload'])
    bundle = cb.build_context(*route, request['payload'], request['payload']['schema'],
                              input_bindings=bindings)
    # Validators bind the original adapter request, so a builder cannot silently
    # alter its instructions, evidence, governance or schema at the provider edge.
    if bundle['request'] != request:
        cb.fail('Stage adapter and ContextBuilder disagree on the request')
    return bundle


def export_preview(request, out, bindings=None):
    bundle = assemble(request, bindings)
    cb.save_bundle(out, bundle)
    out = Path(out)
    visible, projection = cmv.project(bundle['request'])
    write_json(out/'projection_manifest.json', projection)
    (out/'premise.txt').write_text(visible['payload']['premise'], encoding='utf-8')
    write_json(out/'model_input.json', visible)
    prompt = providers.PROMPT + canonical(visible)
    write_json(out/'budget.json',context_budget.check(prompt,request['payload']['schema']))
    (out/'model_prompt.txt').write_text(prompt, encoding='utf-8')
    manifest = bundle['context_manifest']
    write_json(out/'execution_policy.json', {
        'linear': True, 'automatic_retries': 0, 'automatic_patches': 0,
        'model_calls': 0, 'status': 'PREVIEW_AWAITING_USER_REVIEW',
        'legacy_profile_patch_allowance': 'Not used by this executor.',
        'scientific_approval': False, 'downstream_executed': False})
    parts = []
    for key, value in visible['payload'].items():
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
        parts.append('<details'+(' open' if key in {'premise','source_registry'} else '')+
                     '><summary>'+html.escape(key)+'</summary><pre>'+html.escape(text)+'</pre></details>')
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><title>Compression context preview</title>
<style>body{max-width:1100px;margin:36px auto;padding:0 24px;font:16px/1.6 system-ui;color:#203040;background:#f6f8fb}
details{background:white;padding:12px 18px;margin:10px 0;border:1px solid #d8e0e8;border-radius:8px}summary{cursor:pointer;font-weight:600}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.6 monospace}a{color:#165fa8}</style>
<h1>Compression — exact context preview</h1><p><strong>No model call has been made.</strong> This is the first extraction request, before independent full-source review.</p>
<p>The host selects the route, preserves the applicable rule text, includes authorized evidence, and adds the response schema. No scientific rule or evidence is dropped by ContextBuilder.</p>
<p>Execution: extract once → validate → review once → validate → stop. A rejection or error stops execution; no automatic patch or retry. A successful run still does not approve downstream science.</p>'''
    page += '<p>Route: '+manifest['route']+' · Source units: '+str(len(visible['payload'].get('source_units',[])))
    page += ' · Request characters: '+str(manifest['request_characters'])+' (not tokens).</p>'
    page += '<p>Model-visible characters: '+str(projection['model_characters'])+'; reduction: '+str(projection['character_reduction'])+'. Engineering bindings are retained in the host audit. Rule exceptions and evidence links remain visible.</p>'
    page += '<p><a href="premise.txt">Stage premise</a> · <a href="projection_manifest.json">Host-only binding record</a></p>'
    page += '<p>Existing clause replacements compiled by the host: '+str(len(projection['compiled_rules_audit']))+'. Original Rules and superseded clauses remain in the full request and audit. <a href="budget.json">Final input-size check</a> includes the actual prompt, transport schema and an application-level output reserve; it is not a model token count.</p>'
    page += '<p><a href="request.json">Full host request JSON</a> · <a href="model_input.json">Model input JSON</a> · <a href="model_prompt.txt">Exact CLI prompt</a> · <a href="context_manifest.json">Context manifest</a></p>'
    page += '<details><summary>Provider instruction prefix</summary><pre>'+html.escape(providers.PROMPT)+'</pre></details>'
    page += ''.join(parts)+'</html>'
    if manifest['route'].startswith('eda.'):
        page = page.replace('Compression context preview', 'EDA context preview').replace(
            'Compression — exact context preview', 'EDA — exact context preview').replace(
            'This is the first extraction request, before independent full-source review.',
            'This is a context-only preview. EDA execution and R workers remain disabled.').replace(
            'Execution: extract once → validate → review once → validate → stop.',
            'Contract: plan once → R calculation → EP display review once → R plotting → findings once → review once → host human checkpoint. This preview executes none of these steps.')
    (out/'preview.html').write_text(page, encoding='utf-8')
    return bundle


class LinearSession:
    """Durable at-most-once ledger; uncertain/failed dispatches are never retried.

    Coverage may have distinct, pre-partitioned requirement sets. Overlap is
    forbidden. A scientific validation failure must escape the caller so this
    session stops, rather than being interpreted as a new correction request.
    """
    def __init__(self, out, bindings=None):
        self.out = Path(out).resolve()
        self.bindings = bindings or {}
        self.lock = threading.Lock()
        self.state = {'status':'READY', 'calls':[], 'last_order':-1,
                      'input_bindings':self.bindings,
                      'runtime_bindings':{name:cb.file_ref(path) for name,path in
                          [('builder',cb.__file__),('routes',cb.CONFIG),('runner',__file__),
                           ('provider',providers.__file__),('dispatch',context_dispatch.__file__)]},
                      'automatic_retries':0, 'automatic_patches':0}
        self.state['runtime_bindings'].update(model_projection=cb.file_ref(cmv.__file__),
                                              optimization=cb.file_ref(context_optimization.__file__),
                                              stage_scope=cb.file_ref(context_optimization.POLICY),
                                              route_selector=cb.file_ref(context_routes.__file__),
                                              premises=cb.file_ref(cmv.PREMISES),
                                              effective_rules=cb.file_ref(context_effective_rules.__file__),
                                              budget_code=cb.file_ref(context_budget.__file__),
                                              budget_policy=cb.file_ref(context_budget.POLICY))

    @staticmethod
    def model_input(request):
        return cmv.view(request)

    def save(self):
        write_json(self.out/'session.json', self.state)

    @contextmanager
    def activate(self):
        self.out.mkdir(parents=True, exist_ok=True)
        lock = self.out/'session.lock'
        # Exclusive filesystem creation also protects against another process.
        with lock.open('x', encoding='utf-8') as f:
            f.write(str(os.getpid()))
        try:
            if (self.out/'session.json').exists():
                self.state = read_json(self.out/'session.json')
                if self.state['input_bindings'] != self.bindings:
                    cb.fail('Session belongs to different inputs')
                if self.state['status'] in {'FAILED', 'RUNNING'}:
                    cb.fail('Previous failed or uncertain session retained; no automatic resume')
            cb.check_refs(self.bindings)
            cb.check_refs(self.state['runtime_bindings'])
            self.save()
            with context_dispatch.install(self.dispatch):
                yield self
            if self.state['status'] == 'FAILED':
                cb.fail('Session stopped after a caught dispatch error')
            self.state['status'] = 'STOPPED'
            self.save()
        except BaseException as exc:
            self.state.update(status='FAILED', error=str(exc))
            self.save()
            raise
        finally:
            lock.unlink()

    def dispatch(self, request, *, transport, **kwargs):
        with self.lock:
            try:
                return self._dispatch(request, transport=transport, **kwargs)
            except BaseException as exc:
                self.state.update(status='FAILED',error=str(exc))
                self.save()
                raise

    def _dispatch(self, request, *, transport, **kwargs):
        cb.check_refs(self.state['runtime_bindings'])
        if self.state['status'] == 'FAILED':
            cb.fail('Session has stopped after an error')
        bundle = assemble(request, self.bindings)
        route = bundle['context_manifest']['route']
        from .context_gateway import task_identity
        identity=task_identity(request['payload'])
        requirement_ids = []
        if route == 'data.coverage':
            values = request['payload']['requirements']
            requirement_ids = sorted(values if isinstance(values, dict) else [r['id'] for r in values])
            if not requirement_ids:
                cb.fail('Empty Coverage task')
        review_partition=None
        if route=='eda.review' and request['payload'].get('task_context',{}).get('review_batch'):
            from .eda_review_batches import validate_scope
            review_partition=validate_scope(request['payload'])
            requirement_ids=review_partition['figure_ids']
        previous = [c for c in self.state['calls'] if c['route'] == route]
        if review_partition and any(c.get('review_partition_manifest')!=review_partition['manifest'] for c in previous):
            cb.fail('ER cannot switch its frozen image partition or follow an unpartitioned review')
        if '.adapter_' in route:
            previous=[c for c in previous if c.get('task_identity')==identity]
        if previous and (not requirement_ids or any(set(c['requirement_ids']) & set(requirement_ids) for c in previous)):
            cb.fail('Logical task was already dispatched; no repeat or patch allowed')
        order=ORDER.get(route,self.state['last_order'])
        if order < self.state['last_order']:
            cb.fail('Backward stage transition is not allowed')
        slot = self.out/f"{len(self.state['calls'])+1:03d}_{route.replace('.', '_')}"
        cb.save_bundle(slot, bundle)
        visible, projection = cmv.project(bundle['request'])
        write_json(slot/'projection_manifest.json',projection)
        write_json(slot/'model_input.json', visible)
        (slot/'model_prompt.txt').write_text(providers.PROMPT+canonical(visible), encoding='utf-8')
        write_json(slot/'transport_schema.json', kwargs.get('cli_schema') or request['payload']['schema'])
        write_json(slot/'budget.json',context_budget.check(providers.PROMPT+canonical(visible),kwargs.get('cli_schema') or request['payload']['schema']))
        record = {'route':route, 'requirement_ids':requirement_ids,
                  'task_identity':identity,
                  'review_partition_manifest':review_partition['manifest'] if review_partition else None,
                  'request_sha256':request['request_sha256'], 'status':'DISPATCHING',
                  'requested_model':providers.provider_model(kwargs.get('model')),
                  'provider':providers.model_provider(), 'directory':str(slot)}
        self.state['calls'].append(record)
        self.state.update(status='RUNNING', last_order=order)
        self.save()  # Persist before transport, including uncertain crashes.
        started = time.monotonic()
        try:
            cb.verify_bundle(bundle)
            cb.check_refs(projection['bindings'])
            if kwargs.get('diagnostics_dir') is None:
                kwargs['diagnostics_dir'] = slot/'provider'
            with context_dispatch.sending(bundle['request'],visible,kwargs.get('cli_schema')):
                raw = transport(bundle['request'], **kwargs)
            write_json(slot/'response.json', raw)
            cb.check_refs(self.state['runtime_bindings'])
            cb.verify_bundle(bundle)
            cb.check_refs(projection['bindings'])
            record['status'] = 'RETURNED_PENDING_STAGE_VALIDATION'
            return raw
        except BaseException as exc:
            record.update(status='FAILED', error=str(exc))
            self.state['status'] = 'FAILED'
            raise
        finally:
            record['elapsed_seconds'] = time.monotonic()-started
            self.save()


def run_compression(run, session, model=None, until=None, budget_seconds=None):
    """Lean extraction + full-source review, once each. Never enter patch logic."""
    from uuid import uuid4
    run = Path(run).resolve()
    bundle, state = engine.load_run(run)
    if bundle.get('compression_profile', {}).get('id') != 'LEAN_1.0':
        cb.fail('Linear Compression requires LEAN_1.0')
    bindings = {'inputs':cb.file_ref(run/'inputs.json')}
    started=time.monotonic(); invocation=uuid4().hex;stage='context'
    budget_path=run/'lean/execution_budget.json'
    ledger=read_json(budget_path) if budget_path.exists() else {'elapsed_seconds':0,'invocations':[]}
    prior=ledger['elapsed_seconds']
    diagnostics=None
    try:
        with LinearSession(session, bindings).activate():
            for stage in ('context', 'context_review'):
                _, state = engine.load_run(run)
                if stage in state['accepted']:
                    if until==stage:return {'status':'STAGE_READY','stage':stage}
                    continue
                request = engine.prepare(run, stage)
                remaining=None if budget_seconds is None else budget_seconds-prior-(time.monotonic()-started)
                if remaining is not None and remaining<=0:
                    cb.fail('Existing Compression execution budget exhausted')
                diagnostics=run/'audit/model_calls'/invocation/stage
                raw = providers.codex_generate(request, model=model,timeout=remaining,diagnostics_dir=diagnostics)
                outcome = engine.accept(run, stage, raw, provider=providers.model_provider())
                write_json(Path(session)/(stage+'_validation.json'), outcome)
                if outcome['status'] not in {'ACCEPTED','ALREADY_ACCEPTED'}:
                    cb.fail('Compression stopped at '+stage+': '+outcome['status'])
                if until==stage:return {'status':'STAGE_READY','stage':stage}
            result = engine.verify_context(run)
            write_json(Path(session)/'compression_verification.json', result)
            return result
    except BaseException as exc:
        stop={'stage':stage,'status':'ERROR','reason':str(exc),
            'error_code':getattr(exc,'code','CONTEXT_EXECUTION_ERROR'),
            'model_call':str((diagnostics/'call.json').relative_to(run)).replace(chr(92),'/') if diagnostics else None}
        write_json(Path(session)/'execution_stop.json',stop)
        if not (run/'stopped.json').exists():write_json(run/'stopped.json',stop)
        raise
    finally:
        elapsed=time.monotonic()-started
        ledger['elapsed_seconds']=prior+elapsed
        ledger['invocations'].append({'id':invocation,'elapsed_seconds':elapsed,'automatic_retries':0})
        write_json(budget_path,ledger)


def run_data(plan, source_view, main, local_mp, out, session, **kwargs):
    """Use accepted extraction/DR, then Coverage → Necessity → human summary.

    Existing adapters retain scientific verification and human-gate publication.
    Model calls use the real provider path; no synthetic-generator flag is set.
    """
    from . import data_assessment_workflow
    if kwargs.get('generator') is not None:
        cb.fail('Use provider transport stubs only in offline tests')
    refs = {k:cb.file_ref(p) for k,p in [('plan',plan),('source_view',source_view),('main',main),('local_mp',local_mp)]}
    kwargs.setdefault('contract', 'original')
    with LinearSession(session, refs).activate():
        return data_assessment_workflow.run(plan,source_view,main,local_mp,out,**kwargs)


def run_dr(source_run, out, session, input_bindings=None):
    from . import data_requirement_plan_v6 as dr
    with LinearSession(session).activate():
        return dr.run(source_run, out, input_bindings=input_bindings)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    preview = sub.add_parser('preview-compression')
    preview.add_argument('--run', required=True)
    preview.add_argument('--out', required=True)
    comp = sub.add_parser('run-compression')
    comp.add_argument('--run', required=True)
    comp.add_argument('--session', required=True)
    comp.add_argument('--model', default=None)
    dr = sub.add_parser('run-dr')
    for name in ('source-run', 'out', 'session'):
        dr.add_argument('--'+name, required=True)
    dr.add_argument('--input-bindings')
    data = sub.add_parser('run-data')
    for name in ('plan','source-view','main','local-mp','out','session'):
        data.add_argument('--'+name, required=True)
    args = vars(parser.parse_args())
    command = args.pop('command')
    if command == 'preview-compression':
        run = Path(args['run'])
        request = engine.prepare(run, 'context')
        export_preview(request, args['out'], {'inputs':cb.file_ref(run/'inputs.json')})
        print(json.dumps({'status':'PREVIEW_READY','model_calls':0,'out':args['out']}))
    elif command == 'run-compression':
        print(json.dumps(run_compression(**args)))
    elif command == 'run-dr':
        run_dr(**args)
    else:
        run_data(**args)


if __name__ == '__main__':
    main()
