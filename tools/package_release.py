"""Build a portable release after the real through-Data acceptance suite passes.

Runtime state, credentials and failed-run logs never enter the distribution.
The accepted evidence remains a read-only snapshot, not a relocatable live run.
"""
import argparse
import csv
from datetime import datetime
import hashlib
import importlib.util
from html import escape
import json
from pathlib import Path
from urllib.parse import quote
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {'.git', '.venv', '.pytest_cache', '__pycache__'}
EXAMPLES = {'pmb', 'meropenem', 'voriconazole'}
FRESH_EXAMPLES = EXAMPLES | {'imidocarb'}
TITLES = {'pmb':'PMB', 'meropenem':'Meropenem', 'voriconazole':'Voriconazole', 'imidocarb':'Imidocarb (cattle)'}
NODES = {'intake', 'context', 'adequacy', 'prepare'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def files():
    for path in sorted(ROOT.rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if relative.parts[0] in {'state','outputs'}:
            continue
        if any(part in EXCLUDED or part.startswith('.venv') for part in relative.parts):
            continue
        if path.suffix in {'.pyc', '.log'} or path.name.startswith('.env'):
            continue
        if path.name in {'auth.json', 'credentials.json', 'checksums.sha256', 'source_manifest.json'}:
            continue
        yield path, relative.as_posix()


def accepted_examples(report):
    """Require the independently verified suite and its actual driver results."""
    fresh = report.get('status') == 'ALL_FOUR_PASSED_FRESH_THROUGH_DATA'
    collection = report.get('status') == 'FOUR_VERIFIED_DATA_EXAMPLES'
    if not (fresh or collection) and report.get('status') != 'ALL_THREE_PASSED_THROUGH_DATA':
        raise ValueError('Release blocked: the complete example suite must pass through Data.')
    if report.get('eda_executed') or report.get('pk_executed') or report.get('scientific_release'):
        raise ValueError('Release blocked: acceptance exceeded the technical Data boundary.')
    examples = report.get('examples', [])
    expected = FRESH_EXAMPLES if fresh or collection else EXAMPLES
    if len(examples) != len(expected) or {item['example'] for item in examples} != expected:
        raise ValueError('Release blocked: example set does not match the acceptance mode.')
    if fresh:
        if not all(report.get(k) is True for k in ('code_unchanged','no_reuse_verified','response_reuse_disabled')):
            raise ValueError('Fresh release lacks the unchanged-code and no-reuse verification')
        if report.get('manual_repairs') != 0 or report.get('automatic_retries') != 0:
            raise ValueError('Fresh release contains repairs or retries')
    accepted = []
    for item in examples:
        if collection:
            ref = item['source_report']
            raw = Path(ref['path']).read_bytes()
            if sha(raw) != ref['sha256']:
                raise ValueError('Collected source report changed')
            source = json.loads(raw)
            original = next(i for i in source['examples'] if i['example'] == item['example'])
            if (original.get('status') != 'PASSED_THROUGH_DATA' or
                    item['state_root'] != source['state_root'] or
                    {k:v for k,v in item.items() if k not in {'source_report','state_root','source_round'}} != original):
                raise ValueError('Collected example differs from its verified source record')
        if (fresh or collection) and (len(item.get('attempts', [])) != 1 or not item.get('model_calls') or
                      not all(c.get('new_or_changed') and c.get('status') == 'RETURNED' and
                              c.get('requested_model') == 'gpt-6.1-sol' and
                              c.get('requested_reasoning_effort') == 'high' for c in item['model_calls'])):
            raise ValueError('Fresh release contains non-fresh or unexpected model calls')
        driver = json.loads(Path(item['driver_report']).read_text(encoding='utf-8-sig'))
        if item.get('status') != 'PASSED_THROUGH_DATA' or driver.get('status') != 'PASSED_THROUGH_DATA':
            raise ValueError('Release blocked: incomplete example ' + item['example'])
        if driver.get('eda_executed') or driver.get('pk_executed'):
            raise ValueError('Release blocked: downstream execution in ' + item['example'])
        session = driver['final_session']
        if session['session_id'] != item['session_id']:
            raise ValueError('Driver and verified session differ')
        actual = set()
        for node in session['nodes']:
            state = node['state']
            if node['id'] not in NODES:
                if state['execution'] != 'NOT_STARTED':
                    raise ValueError('Downstream stage started: ' + node['id'])
                continue
            if state['execution'] != 'COMPLETED' or not state.get('approved'):
                raise ValueError('Unapproved or incomplete stage: ' + node['id'])
            actual.update((node['id'], a['name'], a['sha256']) for a in state['artifacts'])
        verified = {(a['node'], a['name'], a['sha256']) for a in item['verified_artifacts']}
        if actual != verified or not actual:
            raise ValueError('Driver artifacts differ from independently verified artifacts')
        accepted.append((item['example'], driver))
    return accepted


def write_review_index(evidence, report):
    cards = []
    for item in report['examples']:
        name = item['example']
        title = TITLES[name]
        gate_titles = {'context':'Context review', 'adequacy':'Data scope review', 'prepare':'Completed Data review'}
        gates = ''.join(f'<li><b>{escape(gate_titles[g["node"]])}</b> — automatically approved for this demo'
                        f'<small>Output signature: {escape(g["output_signature"])}</small></li>' for g in item['gates'])
        calls = item['model_calls']
        requested_models = sorted({c['requested_model'] for c in calls if c.get('requested_model')})
        model_note = ('Requested models in source receipts: ' + ', '.join(requested_models) +
                      '. Original receipts distinguish fresh calls and reused outputs; requested identity does not verify the served model.')
        if report.get('no_reuse_verified') or report.get('status') == 'FOUR_VERIFIED_DATA_EXAMPLES':
            elapsed = int((datetime.fromisoformat(item['finished_at'].replace('Z', '+00:00')) -
                           datetime.fromisoformat(item['started_at'].replace('Z', '+00:00'))).total_seconds())
            model_note = (f'Elapsed: {elapsed // 60} min {elapsed % 60:02d} sec, including verification. '
                          'Fresh model calls; requested gpt-6.1-sol / high. No response reuse, resume or manual repair. '
                          'Provider-served identity was not reported.')
        counts = item['data_report']['summary']
        deferred = ''
        if (evidence/name/'context/demo_context_review.json').is_file():
            deferred = f'''<p class="review-note">Context retained a canonical-placement review finding. The independent verdict remains REVISE; continuation covers this technical demo only.</p><a href="{name}/context/demo_context_review.json">Context deferral receipt</a><a href="{name}/context/independent_context_review.json">Original Context review</a>'''
        cards.append(f'''<article><div class="kicker">ACCEPTED THROUGH DATA</div><h2>{title}</h2>
<div class="metrics"><div><strong>{item['normalized_dataset_count']}</strong>prepared datasets</div>
<div><strong>{counts['retained_records']}</strong>retained records</div>
<div><strong>{counts['quarantined_records']}</strong>quarantined records</div></div>
<p class="muted">{item['requirement_count']} requirements and {item['data_label_count']} labels retained. {escape(model_note)}</p>
<h3>Visible Human checkpoints</h3><ul>{gates}</ul>
<h3>Inspect the evidence</h3><div class="links">
<a href="{name}/review.html"><b>Browse findings and prepared tables →</b></a>
<a href="{name}/handoffs/index.html">Agent requests, responses and context</a>
<a href="{name}/context/main.json">Compressed Context</a><a href="{name}/context/project_rules.json">Project Rules</a>
<a href="{name}/adequacy/requirements.json">Requirements</a><a href="{name}/adequacy/data_labels.json">Source labels</a>
<a href="{name}/prepare/data_report.json">Data report &amp; findings</a><a href="{name}/prepare/program_qc.json">Program QC</a>
<a href="{name}/prepare/normalized_manifest.json">Prepared data manifest</a><a href="{name}/prepare/cleaning_log.json">Cleaning log</a>
<a href="{name}/prepare/unresolved_ledger.json">Unresolved issues</a><a href="{name}/acceptance.json">Full run &amp; gate record</a>
{deferred}
</div><small class="flow">{escape(item['session_id'])}</small></article>''')
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Accepted Data runs · PK/PD Workbench</title><style>
*{box-sizing:border-box}body{margin:0;background:#f3f6f3;color:#20382f;font:16px/1.6 system-ui,sans-serif}
main{max-width:1280px;margin:auto;padding:48px 28px}h1{font-size:40px;line-height:1.2;letter-spacing:-1px}h2{font-size:28px;margin:8px 0 20px}
h3{font-size:16px;margin:26px 0 12px}.kicker{font-size:11px;letter-spacing:2px;font-weight:700;color:#47745a}
.lead{max-width:870px;font-size:19px}.note{padding:20px 24px;border-left:4px solid #b49d65;background:#f7f2e6;margin:28px 0}
.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:22px}article{background:white;border:1px solid #d9e3db;border-radius:16px;padding:26px}
.metrics{display:flex;gap:18px}.metrics div{flex:1;font-size:12px;color:#607166}.metrics strong{display:block;color:#2f614d;font-size:28px}
.muted,small{color:#69776e;font-size:12px}ul{padding-left:18px;font-size:13px}li{margin:10px 0}li small{display:block;overflow-wrap:anywhere;font-size:10px}
.links{display:grid;gap:7px}.links a{color:#2f614d;text-decoration:none;border-bottom:1px solid #e6ece6;padding:5px 0;font-size:14px}
.review-note{font-size:12px;padding:12px;background:#f7f2e6;margin:12px 0 0}
a{color:#2f614d}.flow{display:block;overflow-wrap:anywhere;margin-top:26px}footer{margin-top:30px;color:#69776e;font-size:13px}
@media(max-width:1000px){.grid{grid-template-columns:1fr}h1{font-size:32px}}</style><main>
<div class="kicker">PK/PD RESEARCH WORKBENCH · RECORDED ACCEPTANCE</div><h1>Three examples, through Data.</h1>
<p class="lead">Source registration, Context compression, key Rules, requirements, source labels, source-preserving preparation and technical QC. Every checkpoint remains traceable.</p>
<div class="note"><b>Technical demonstration scope.</b> Human gates were automatically approved with explicit user authorization. Scientific adequacy and modeling readiness remain unassessed. All findings remain available; EDA and PK were not executed.</div>
<div class="grid">''' + ''.join(cards) + '''</div><footer>
<a href="three_examples_acceptance.json">Independent verification report</a> · <a href="../inputs/manifest.json">Input ZIPs and checksums</a>
<p>This is a read-only snapshot. References retain their original paths and hashes. Import an example into the running workbench to create a fresh workflow; these files do not resume the original session.</p></footer></main></html>'''
    if report.get('no_reuse_verified'):
        page = page.replace('Three examples, through Data.', 'Four fresh examples, through Data.').replace(
            'three_examples_acceptance.json', 'fresh_examples_acceptance.json').replace(
            'repeat(3,minmax(0,1fr))', 'repeat(2,minmax(0,1fr))')
    elif report.get('status') == 'FOUR_VERIFIED_DATA_EXAMPLES':
        page = page.replace('Three examples, through Data.', 'Four verified examples, through Data.').replace(
            'three_examples_acceptance.json', 'verified_examples.json').replace(
            'repeat(3,minmax(0,1fr))', 'repeat(2,minmax(0,1fr))').replace(
            '<div class="note"><b>Technical demonstration scope.</b>',
            '<div class="note"><b>Results from different code versions.</b> The three original examples passed in an earlier fresh round; Imidocarb passed after two scoped Data fixes. The user stopped the redundant full rerun. This collection is not a four-case run on one unchanged code version.<br><b>Technical demonstration scope.</b>')
    (evidence/'index.html').write_text(page, encoding='utf-8')


def write_timings(evidence, report, accepted, state_root):
    """Summarize recorded wall time; never add parallel call durations to totals."""
    rows, sources = [], {}
    def instant(value):
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    def read(path):
        data = path.read_bytes()
        value = json.loads(data)
        key = str(path.resolve())
        fields = ('status', 'stage', 'at', 'started_at', 'finished_at', 'elapsed_seconds',
                  'last_checked_at', 'cli_process_exited_at', 'cli_exit_elapsed_seconds')
        sources[key] = {'sha256': sha(data), 'timing_fields': {k: value[k] for k in fields if k in value}}
        return value, key
    def add(example, level, step, start, end, refs, calls='', cumulative=''):
        elapsed = (instant(end) - instant(start)).total_seconds()
        if elapsed < 0:
            raise ValueError('Negative recorded duration: ' + step)
        rows.append(dict(example=example, level=level, step=step, started_at_utc=start,
                         finished_at_utc=end, wall_seconds=round(elapsed, 3), model_calls=calls,
                         cumulative_call_seconds=cumulative, evidence_paths='; '.join(refs)))
    collection = report.get('status') == 'FOUR_VERIFIED_DATA_EXAMPLES'
    _, suite_ref = read(evidence/('verified_examples.json' if collection else 'fresh_examples_acceptance.json'))
    for name, driver in accepted:
        item = next(i for i in report['examples'] if i['example'] == name)
        _, driver_ref = read(Path(item['driver_report']))
        sources[driver_ref]['timing_events'] = [
            {k: e[k] for k in ('at', 'event', 'node') if k in e}
            for e in driver['events'] if e['event'] in ('STARTED', 'COMPLETED', 'AUTOMATIC_GATE')]
        add(name, 'total', 'Complete example including verification', item['started_at'],
            item['finished_at'], [suite_ref])
        intake = next(n['state'] for n in driver['final_session']['nodes'] if n['id'] == 'intake')
        item_state = Path(item.get('state_root', state_root))
        receipt, ref = read(item_state/'workbench_state/workbench_jobs'/intake['job_id']/'receipts/intake.json')
        add(name, 'workflow', 'File intake', receipt['started_at'], receipt['finished_at'], [ref], 0, 0)
        for node, title in [('context', 'Context and Rules'), ('adequacy', 'Data requirements and labels'),
                            ('prepare', 'Data preparation and handoff')]:
            start = next(e['at'] for e in driver['events'] if e['event'] == 'STARTED' and e['node'] == node)
            end = next(e['at'] for e in driver['events'] if e['event'] == 'COMPLETED' and e['node'] == node)
            add(name, 'workflow', title, start, end, [driver_ref])
        groups = {}
        for entry in item['model_calls']:
            path = Path(entry['path'])
            if 'data_agents' in path.parts and 'audit' in path.parts:
                step = {'DR': 'Data requirements', 'DR-access': 'Source access',
                        'DC-split': 'Source table boundaries',
                        'DC-label': 'Data labels (parallel batch)'}.get(
                            path.parent.parent.name, path.parent.parent.name)
                value, ref = read(path)
                start, end = value['started_at'], value['finished_at']
            elif ('context_work' in path.parts and path.parent.name in ('context', 'context_review')) or (
                    'project_rules' in path.parts and path.parent.name == 'model_call'):
                step = {'context': 'Context generation', 'context_review': 'Context review'}.get(
                    path.parent.name, 'Key Rules extraction')
                value, ref = read(path.with_name('progress.json'))
                start, end = value['started_at'], value['cli_process_exited_at']
            else:
                continue  # Provider receipts duplicate the native Data call receipts.
            groups.setdefault(step, []).append((start, end, float(value['elapsed_seconds']), ref))
        for step, calls in sorted(groups.items(), key=lambda item: min(instant(c[0]) for c in item[1])):
            add(name, 'model', step, min(c[0] for c in calls), max(c[1] for c in calls),
                [c[3] for c in calls], len(calls), round(sum(c[2] for c in calls), 3))
    notes = ('Final accepted round only; earlier diagnostic rounds are excluded. Workflow rows include '
             'scheduling, polling and automatic gate recording. Model rows are nested inside workflow rows '
             'and measure client-observed call duration, not server compute time. Parallel call durations '
             'are reported separately and must not be added to wall time. Source timing fields are copied '
             'from the referenced receipts; SHA-256 values bind their original files. All timestamps are UTC.')
    if collection:
        notes = notes.replace('Final accepted round only; earlier diagnostic rounds are excluded.',
            'Completed examples from different code versions, not one unchanged-code suite. Failed and user-stopped attempts are excluded and recorded separately in validation/diagnostic_timings.csv.')
    (evidence/'runtime_summary.json').write_text(json.dumps(
        {'notes': notes, 'suite_started_at': report.get('started_at'), 'suite_finished_at': report.get('finished_at'),
         'suite_wall_seconds': (instant(report['finished_at']) - instant(report['started_at'])).total_seconds()
                              if report.get('finished_at') and report.get('started_at') else None,
         'rows': rows, 'source_receipts': sources}, indent=2), encoding='utf-8')
    with (evidence/'runtime_summary.csv').open('w', encoding='utf-8-sig', newline='') as output:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_example_review(destination, item, driver):
    """Human-readable navigation over unchanged, hash-verified evidence files."""
    findings=item['data_report']['findings']
    rows=''.join('<tr>'+''.join('<td>'+escape(str(f.get(k,'')))+'</td>' for k in
        ('severity','code','affected_id','reason','needed_material','required_by'))+'</tr>' for f in findings)
    node=next(n for n in driver['final_session']['nodes'] if n['id']=='prepare')
    artifacts={(a['local_path'],a['sha256']):a['name'] for a in item['verified_artifacts'] if a['node']=='prepare'}
    manifest=json.loads((destination/'prepare/normalized_manifest.json').read_text(encoding='utf-8'))
    tables=[]
    for dataset in manifest['datasets']:
        links=[]
        for key,label in [('csv','Source values CSV'),('data','Data JSON'),('metadata_file','Metadata'),('quarantine','Quarantine')]:
            ref=dataset[key];name=artifacts[(ref['path'],ref['sha256'])]
            links.append(f'<a href="prepare/{escape(quote(name))}">{label}</a>')
        metadata=dataset.get('metadata',{})
        cells=[dataset['id'],metadata.get('source_item_id',''),metadata.get('species',''),
               dataset['role'],str(dataset['summary']['retained_records'])]
        tables.append('<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in cells)+'<td>'+' · '.join(links)+'</td></tr>')
    title=TITLES[item['example']]
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>'''+title+''' · Data review evidence</title><style>
*{box-sizing:border-box}body{margin:0;background:#f3f6f3;color:#20382f;font:15px/1.55 system-ui,sans-serif}
main{max-width:1500px;margin:auto;padding:38px 28px}h1{font-size:36px;margin:18px 0 8px}h2{font-size:23px;margin-top:36px}
a{color:#2f614d}header p{max-width:960px;color:#5d7064}.note{padding:18px 22px;background:#f7f2e6;border-left:4px solid #b49d65;margin:24px 0}
input{padding:13px 16px;border:1px solid #cad8cc;border-radius:8px;width:min(650px,100%);font:inherit}
.table-wrap{overflow:auto;border:1px solid #d9e3db;border-radius:12px;margin-top:16px;background:white}
table{border-collapse:collapse;width:100%;font-size:13px}th,td{text-align:left;vertical-align:top;padding:13px;border-bottom:1px solid #e5ebe5;overflow-wrap:anywhere}
th{background:#eaf1eb;position:sticky;top:0}td:nth-child(4),td:nth-child(5){min-width:180px}small{color:#65756b}
</style><main><header><a href="../index.html">← Three-example overview</a><h1>'''+title+''' · Human review evidence</h1>
<p>Inspect preserved source values, metadata and open findings from the accepted technical Data run. This page is read-only; workflow decisions remain in the recorded, signature-bound checkpoints.</p></header>
<div class="note">All three Human gates were automatically approved with user authorization for this demo. Open findings retain their original severity and phase. Scientific adequacy and analysis readiness remain unassessed; no EDA or PK model ran.</div>
<label for="filter"><b>Find a dataset or issue</b></label><p><input id="filter" type="search" placeholder="Search species, table ID, units, dose, or finding code…"></p>
<small id="count">'''+str(len(findings))+''' findings · '''+str(len(tables))+''' prepared datasets</small>
<h2>Prepared source tables</h2><div class="table-wrap"><table><thead><tr><th>Dataset</th><th>Source item</th><th>Species / subject</th><th>Role</th><th>Retained rows</th><th>Files</th></tr></thead><tbody>'''+''.join(tables)+'''</tbody></table></div>
<h2>Open findings</h2><p><a href="prepare/data_report.json">Original Data report</a> · <a href="prepare/unresolved_ledger.json">Unresolved ledger</a> · <a href="acceptance.json">Checkpoint decisions</a></p>
<div class="table-wrap"><table><thead><tr><th>Severity</th><th>Code</th><th>Affected source</th><th>Finding</th><th>Needed information</th><th>Required phase</th></tr></thead><tbody>'''+rows+'''</tbody></table></div></main>
<script>document.querySelector('#filter').addEventListener('input',function(){const q=this.value.toLowerCase();let visible=0;document.querySelectorAll('tbody tr').forEach(row=>{row.hidden=!row.textContent.toLowerCase().includes(q);if(!row.hidden)visible++;});document.querySelector('#count').textContent=visible+' matching datasets / findings';});</script></html>'''
    (destination/'review.html').write_text(page,encoding='utf-8')


def export_handoffs(destination, session, item, base, state=None):
    """Export allowlisted requests for the jobs supplying the accepted outputs."""
    jobs=set()
    def add_job(path):
        parts=Path(path).parts
        if 'workbench_outputs' in parts:
            jobs.add(parts[parts.index('workbench_outputs')+1])
    for artifact in item['verified_artifacts']:
        add_job(artifact['local_path'])
        if artifact['name']=='retained_inputs.json':
            retained=json.loads((destination/artifact['node']/artifact['name']).read_text(encoding='utf-8'))
            for ref in retained['input_refs'].values():
                add_job(ref['path'])
    spec=importlib.util.spec_from_file_location('release_handoffs',ROOT/'demo/handoffs.py')
    adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
    state=Path(state) if state else ROOT/'state'
    stored=json.loads((state/'workbench_state/canvas_sessions'/session['session_id']/'session.json').read_text(encoding='utf-8'))
    index={'session_id':session['session_id'],'read_only':True,'scientific_release':False,
           'calls':adapter.handoff_index(state,stored)}
    calls=[entry for entry in index['calls'] if entry['job_id'] in jobs]
    if not calls:
        raise ValueError('No accepted-job handoff evidence found')
    root=destination/'handoffs';root.mkdir(exist_ok=True)
    sections=[]
    for entry in calls:
        links=[]
        for file in entry['files']:
            name=file['name']
            if Path(name).name!=name or '/' in name or '\\' in name:
                raise ValueError('Unsafe handoff filename')
            source=Path(file.pop('_path')).resolve()
            if not source.is_relative_to((state/'workbench_outputs').resolve()):
                raise ValueError('Handoff file outside registered output root')
            data=source.read_bytes();expected=sha(data)
            target=root/entry['id']/name;target.parent.mkdir(exist_ok=True);target.write_bytes(data)
            file['sha256']=expected;file['local_path']=entry['id']+'/'+name
            links.append(f'<a href="{escape(quote(file["local_path"]))}">{escape(name)}</a>')
        sections.append('<details><summary>'+escape(entry['stage'])+' · '+escape(entry['status'])+'</summary><p>'+
            escape(entry['sender']+' → '+entry['receiver'])+'</p><p>'+escape(entry['purpose'])+'</p><small>Job: '+
            escape(entry['job_id'])+' · Requested model: '+escape(str(entry.get('requested_model') or 'See source receipt'))+
            '</small><div>'+''.join(links)+'</div></details>')
    index.update(calls=calls,selection='Jobs bound to accepted stage artifacts; original paths remain read-only references.')
    (root/'index.json').write_text(json.dumps(index,indent=2),encoding='utf-8')
    (root/'index.html').write_text('''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Agent context evidence</title><style>body{font:16px/1.6 system-ui;color:#20382f;background:#f3f6f3;margin:0}main{max-width:1000px;margin:auto;padding:40px 24px}a{color:#2f614d}details{padding:18px 22px;background:white;border:1px solid #d9e3db;border-radius:12px;margin:14px 0}summary{cursor:pointer;font-weight:650}small{color:#68796e}details div{display:flex;flex-wrap:wrap;gap:12px;margin-top:14px}details a{font-size:13px}.note{padding:18px;background:#f7f2e6;border-left:4px solid #b49d65}</style><main>
<a href="../../index.html">← Three-example overview</a><h1>Agent requests, responses and context</h1>
<p>Read-only evidence from the jobs that supplied this accepted Data run. Expand a call to inspect its retained files.</p>
<p class="note">A recorded response is not a scientific approval. Reuse receipts retain the original model identity. Assembled inputs appear where the original call recorded them; direct or reused calls may contain only the exact request and response.</p>
'''+''.join(sections)+'''<p><a href="index.json">File index and SHA-256 checksums</a></p></main></html>''',encoding='utf-8')
    print(json.dumps({'event':'HANDOFFS_EXPORTED','example':destination.name,'calls':len(calls)}),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acceptance', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--base', default='http://127.0.0.1:8772')
    args = parser.parse_args()
    report = json.loads(args.acceptance.read_text(encoding='utf-8'))
    accepted = accepted_examples(report)
    fresh = report.get('no_reuse_verified') is True
    collection = report.get('status') == 'FOUR_VERIFIED_DATA_EXAMPLES'
    state_root = Path(report['state_root']) if fresh else ROOT/'state'
    if args.output.resolve().is_relative_to(ROOT):
        raise SystemExit('Choose an output ZIP outside the demo folder.')
    evidence = ROOT/'examples/acceptance'
    evidence.mkdir(parents=True, exist_ok=True)
    report_name = 'verified_examples.json' if collection else 'fresh_examples_acceptance.json' if fresh else 'three_examples_acceptance.json'
    (evidence/report_name).write_text(json.dumps(report, indent=2), encoding='utf-8')
    for example, driver in accepted:
        session = driver['final_session']
        item=next(i for i in report['examples'] if i['example']==example)
        item_state = Path(item.get('state_root', state_root))
        sources={(a['node'],a['name'],a['sha256']):Path(a['local_path']) for a in item['verified_artifacts']}
        destination_root = evidence/example
        destination_root.mkdir(parents=True, exist_ok=True)
        (destination_root/'acceptance.json').write_text(json.dumps(driver, indent=2), encoding='utf-8')
        for node in session['nodes']:
            if node['id'] not in NODES:
                continue
            for artifact in node['state']['artifacts']:
                name = artifact['name']
                if Path(name).name != name or '/' in name or '\\' in name:
                    raise ValueError('Unsafe artifact filename: ' + name)
                destination = destination_root/node['id']/name
                if destination.is_file() and sha(destination.read_bytes()) == artifact['sha256']:
                    continue
                source=sources[(node['id'],name,artifact['sha256'])].resolve()
                if not source.is_relative_to((item_state/'workbench_outputs').resolve()):
                    raise ValueError('Accepted artifact outside registered output root')
                data=source.read_bytes()
                if sha(data) != artifact['sha256']:
                    raise ValueError('Accepted artifact changed: ' + name)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
        print(json.dumps({'event': 'ACCEPTED_EVIDENCE_EXPORTED', 'example': example,
                          'session_id': session['session_id']}), flush=True)
        write_example_review(destination_root,next(i for i in report['examples'] if i['example']==example),driver)
        export_handoffs(destination_root,session,item,args.base,item_state)
    write_review_index(evidence, report)
    if fresh or collection:
        write_timings(evidence, report, accepted, state_root)
        index = evidence/'index.html'
        index.write_text(index.read_text(encoding='utf-8').replace('<footer>',
            '<footer><p><a href="runtime_summary.csv">Runtime table (CSV)</a> · '
            '<a href="runtime_summary.json">Runtime details and source receipts</a></p>'), encoding='utf-8')
        for path in evidence.rglob('*.html'):
            path.write_text(path.read_text(encoding='utf-8').replace('Three-example overview','Four-example overview'),encoding='utf-8')
    (evidence/'README.txt').write_text(
        'Recorded technical acceptance through Data. Human gates were automatically passed with explicit user authorization. '
        'This is not independent human scientific review or model release. Original path references and hashes are preserved; '
        'do not use this relocated snapshot to resume the original run. Import an example to create a new live run.\n', encoding='utf-8')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    checksums = []
    with ZipFile(args.output, 'w', compression=ZIP_DEFLATED, compresslevel=6) as archive:
        for path, name in files():
            data = path.read_bytes()
            archive.writestr('demo/' + name, data)
            checksums.append(f'{sha(data)}  {name}')
        archive.writestr('demo/checksums.sha256', '\n'.join(checksums) + '\n')
    with ZipFile(args.output) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError('ZIP integrity failure: ' + bad)
    checksum = sha(args.output.read_bytes())
    args.output.with_suffix('.zip.sha256').write_text(f'{checksum}  {args.output.name}\n', encoding='ascii')
    print(json.dumps({'file': str(args.output.resolve()), 'bytes': args.output.stat().st_size,
                      'sha256': checksum, 'files': len(checksums), 'acceptance': report['status']}))


if __name__ == '__main__':
    main()
