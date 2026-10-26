"""Mandatory dose applicability accounting and traceable, bounded C/dose displays.

Source contracts are exact signatures, never inferred dose conversions or permissions.
Unknown PK evidence is retained with a reason; executable multi-dose views are required.
"""
import copy
import hashlib
import html
import json
import math
import re
import subprocess
from pathlib import Path

HERE = Path(__file__).parent
REGISTRY = HERE / 'resources/eda/dose_normalization.v1.json'
HANDLER = HERE / 'resources/eda/dose_normalization.v1.R'
KIND = 'dose_normalized_profile'
POLICY = ('Assess every admitted concentration dataset for dose comparison. For comparable '
          'multiple doses render an available source-bound C(t)/Dose view. Otherwise record '
          'the exact missing dose basis, comparability, permission, or implementation. '
          'Do not infer compatibility from mg/kg alone, normalize zero-dose controls, pool '
          'species/routes/matrices, or replace raw concentration views. No AUC, fits or '
          'dose-proportionality conclusion is authorized by this arithmetic.')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def signature(table):
    if not all(k in table for k in ('title','notes','columns','records')):
        return ''
    return fingerprint({k: table[k] for k in ('title', 'notes', 'columns', 'records')
                        if k != 'columns'} | {'columns': [
        {k: c[k] for k in ('id', 'header', 'unit', 'meaning')} for c in table['columns']]})


def selectors(spec):
    return (spec['source_recipe']['series'] if spec['kind'] == 'source_projection'
            else [s for p in spec['panels'] for s in p.get('series', [p])])


def is_pk(table):
    return any(c.get('meaning') == 'CONCENTRATION' for c in table['columns'])


def permission_problem(table):
    meta = table.get('metadata') or {}
    if meta.get('observation_role') is False or meta.get('role_resolution') == 'UNRESOLVED':
        return 'Data role is context or unresolved; cannot create an observation-derived curve.'
    for owner in (table, meta):
        if owner.get('dose_normalization_allowed') is False:
            return 'Upstream dose-normalization permission is explicitly false.'
    if 'NORMALIZED_TIME_CONCENTRATION_VIEW' in table.get('notes', ''):
        return 'An unresolved source time-axis restriction explicitly affects normalized time-concentration views.'
    return ''


def assess(candidates, tables, registry=None):
    registry = registry or json.loads(REGISTRY.read_text('utf8'))
    out = []; covered = set()
    for contract in registry['groups']:
        mapping = {}; issues = []; present = []
        for src in contract['sources']:
            matches = [did for did, t in tables.items() if t.get('title') == src['title'] and signature(t) == src['signature']]
            # Title-only matches detect changed evidence, but never authorize calculation.
            titled = [did for did, t in tables.items() if t.get('title') == src['title']]
            present.extend(titled)
            if len(matches) != 1:
                issues.append(src['title'] + ': source signature missing, changed, or ambiguous.')
            else:
                mapping[src['key']] = matches[0]
        if not present:
            continue
        covered.update(present)
        item = dict(group_id=contract['id'], dataset_ids=sorted(set(present)),
                    status='NEEDS_METADATA', reason='', required_view_ids=[],
                    comparison_scope=contract['scope'], evidence=contract['evidence'])
        if not issues and contract.get('single_dose') is True:
            item.update(status='NOT_APPLICABLE', reason='One source-documented dose within this study/route/matrix scope; no multi-dose normalization comparison. Other source limitations remain unchanged.')
            out.append(item)
            continue
        issues.extend(contract.get('blockers', []))
        issues.extend(permission_problem(tables[d]) for d in present if permission_problem(tables[d]))
        if not issues:
            ss = [{**s, 'dataset_id': mapping[s['key']]} for s in contract['series']]
            # Explicit comparability is part of the bound contract, not guessed from labels.
            if len({s['dose'] for s in ss if s['dose'] > 0}) < 2:
                item.update(status='NOT_APPLICABLE', reason='Only one documented positive dose in this comparison scope.')
            else:
                matches = [v for v in candidates.values() if v.get('kind') != KIND
                           and v.get('display_policy', {}).get('role') == 'MAIN'
                           and {(s['dataset_id'], s.get('x'), s.get('y')) for s in selectors(v)}
                           == {(s['dataset_id'], s['x'], s['y']) for s in ss}]
                if not matches:
                    issues.append('No exact compatible main time/concentration selector is available.')
                else:
                    item.update(status='READY', reason='Comparable source-bound multiple doses; C/dose arithmetic is supported.',
                                required_view_ids=[contract['id'] + '__DOSE_NORMALIZED'],
                                parent_view_id=sorted(matches, key=lambda v: (v['y_scale'] != 'log10', v['id']))[0]['id'],
                                series=ss, dose_unit=contract['dose_unit'], dose_basis=contract['dose_basis'])
        if issues:
            item.update(status='BLOCKED', reason=' '.join(dict.fromkeys(issues)))
        out.append(item)
    for did, t in tables.items():
        if not is_pk(t) or did in covered:
            continue
        doses = [c for c in t['columns'] if c.get('meaning') == 'DOSE']
        values = sorted({r['source_raw_values'].get(c['id']) for c in doses for r in t['records']
                         if isinstance(r['source_raw_values'].get(c['id']), (int, float))
                         and not isinstance(r['source_raw_values'].get(c['id']), bool)})
        # Unknown single-table dose count does not prove a study has only one dose.
        out.append(dict(group_id='UNRESOLVED_' + did, dataset_ids=[did],
                        status='NEEDS_METADATA', required_view_ids=[],
                        reason=permission_problem(t) or
                        'No verified comparison contract binds study/species/route/matrix, dose basis, regimen and concentration rows. '
                        'Multiple-dose applicability remains unresolved; raw views/tables retained.',
                        observed_dose_values=values, evidence=[{'dataset_id': did, 'title': t.get('title',did)}]))
    return dict(version='EDA_DOSE_ASSESSMENT_1', policy=POLICY, groups=out,
                all_concentration_datasets_accounted=sorted(d for d,t in tables.items() if is_pk(t)),
                scientific_release=False)


def augment(candidates, tables):
    out = copy.deepcopy(candidates)
    for item in assess(candidates, tables)['groups']:
        if item['status'] != 'READY':
            continue
        parent = out[item['parent_view_id']]
        v = copy.deepcopy(parent)
        v.update(id=item['required_view_ids'][0], kind=KIND,
                 title='Dose-normalized ' + parent['title'].split('|')[0].strip(),
                 subtitle='Source mean concentration / reported single dose; descriptive comparison',
                 y_label='Concentration / dose ((mg/L)/(mg/kg))',
                 dose_contract=copy.deepcopy(item),
                 caption='C(t)/Dose calculated per source group mean using its reported single dose. '
                 + item['dose_basis'] + '. Source times retained; no interpolation or fitted curves. '
                 'Missing SD is not zero; digitization tolerance is not biological variability. '
                 'Normalization does not establish dose proportionality. ' + parent['caption'])
        v['panels']=[{'label':parent['panels'][0].get('label', ''), 'series':[
            {'dataset_id':s['dataset_id'], 'x':s['x'], 'y':s['y'], 'group':'', 'label':s['label']}
            for s in item['series']]}]
        v.pop('source_recipe', None)
        # Carry existing time semantics; add a distinct deterministic identity.
        v['figure_index']='EDA-DN-' + str(len([x for x in out.values() if x['kind']==KIND])+1).zfill(3)
        if 'axis_scales' in v:
            v['axis_scales']['y']['value_transform']='DIVIDE_BY_SOURCE_DOSE'
            v['axis_scales']['y']['output_unit']='(mg/L)/(mg/kg)'
        out[v['id']]=v
    return out


def coverage(selected, candidates, tables):
    result=assess(candidates, tables)
    for group in result['groups']:
        group['selected_view_ids']=[v for v in group['required_view_ids'] if v in selected]
        if group['status']=='READY' and set(group['required_view_ids'])-set(selected):
            raise ValueError('Mandatory dose-normalization view missing: '+group['group_id'])
    return result


def input_rows(spec, tables):
    # Re-assess against current source hashes and upstream restrictions on every use.
    item=next((g for g in assess({spec['dose_contract']['parent_view_id']:
        dict(spec, id=spec['dose_contract']['parent_view_id'], kind='summary_profile')},tables)['groups']
        if g['group_id']==spec['dose_contract']['group_id']), None)
    if item is None or item['status']!='READY' or item['series']!=spec['dose_contract']['series']:
        raise ValueError('Dose contract changed or blocked')
    rows=[]
    for s in item['series']:
        dose=s['dose']
        if not isinstance(dose,(int,float)) or isinstance(dose,bool) or not math.isfinite(dose) or dose<0:
            raise ValueError('Dose must be finite and nonnegative; zero controls stay unnormalized')
        t=tables[s['dataset_id']]; cols={c['id']:c for c in t['columns']}
        if cols[s['y']]['unit']!='mg/L' or item['dose_unit']!='mg/kg':
            raise ValueError('Unsupported units: explicit conversion required')
        for r in t['records']:
            raw=r['source_raw_values']; x=raw.get(s['x']); c=raw.get(s['y'])
            status=r['value_status'].get(s['y'])
            valid=lambda x:isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x)
            xok=valid(x) and r['value_status'].get(s['x'])=='QUANTIFIED'
            cok=valid(c) and status=='QUANTIFIED'
            eligible=dose>0 and xok and cok and (spec['y_scale']!='log10' or c>0)
            rows.append(dict(dataset_id=s['dataset_id'],record_id=r['record_id'],
                x_column=s['x'],y_column=s['y'],x_cell=r['source_cells'][s['x']],
                y_cell=r['source_cells'][s['y']],source_sha256=r['source_sha256'],
                x=x if xok else None,raw_y=c,status=status,dose=dose,dose_unit=item['dose_unit'],
                dose_basis=item['dose_basis'],dose_evidence=s['evidence'],concentration_unit='mg/L',
                group=s['label'],panel=spec['panels'][0]['label'],plot_eligible=eligible,
                exclusion_reason='' if eligible else 'Zero-dose control remains unnormalized.' if dose==0 else 'Nonquantified/nonpositive log value or unsupported time; retained without substitution.',
                formula='raw_y / dose',output_unit='(mg/L)/(mg/kg)',
                y=c/dose if cok and dose>0 else None,error=None,n=None))
    return rows


def render(out, specs, tables, rscript):
    out=Path(out)
    plots=[]
    for s in specs:
        rows=input_rows(s,tables)
        # R performs the calculation; Python's independently computed expected Y is not sent.
        plots.append({**s,'rows':[{k:v for k,v in r.items() if k!='y'} for r in rows]})
    request=out/'dose_normalization_request.json'
    request.write_text(json.dumps({'plots':plots},ensure_ascii=False,indent=2),encoding='utf8')
    from .common import PROJECT
    proc=subprocess.run([rscript,'--vanilla',str(HANDLER),str(request),str(out),str(PROJECT/'pkpd_r/eda/plot_style.R')],
                        capture_output=True,text=True,encoding='utf8')
    (out/'dose_normalization_R.log').write_text(proc.stdout+'\n'+proc.stderr,encoding='utf8')
    if proc.returncode:raise ValueError('Dose normalization R failed: '+proc.stderr)
    artifacts=json.loads((out/'dose_normalization_manifest.json').read_text('utf8'))['artifacts']
    for a in artifacts:verify(out,a,next(s for s in specs if s['id']==a['id']),tables)
    return artifacts


def verify(out, artifact, spec, tables):
    expected=input_rows(spec,tables)
    actual=json.loads((Path(out)/artifact['data']).read_text('utf8'))
    if len(actual)!=len(expected):raise ValueError('Dose normalization row loss')
    for got,want in zip(actual,expected):
        if set(got)!=set(want):raise ValueError('Dose normalization provenance fields changed')
        for key,value in want.items():
            if isinstance(value,(float,int)) and not isinstance(value,bool):
                if not isinstance(got[key],(float,int)) or not math.isclose(got[key],value,rel_tol=2e-13,abs_tol=1e-15):
                    raise ValueError('Dose normalization arithmetic/provenance mismatch: '+key)
            elif got[key]!=value:raise ValueError('Dose normalization provenance changed: '+key)
    facts=artifact['render_facts']
    if facts['point_count']!=sum(r['plot_eligible'] for r in expected):raise ValueError('Dose point count mismatch')
    if facts['y_label']!=spec['y_label']:raise ValueError('Dose output axis mismatch')
    if not (Path(out)/artifact['png']).read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('Invalid dose PNG')
    return len([r for r in expected if r['plot_eligible']])


def ui_section(root):
    root=Path(root);path=root/'dose_normalization_assessment.json'
    if not path.exists():return ''
    report=json.loads(path.read_text('utf8'));e=lambda x:html.escape(str(x))
    body='<section class="panel" id="dose-assessment"><h2>剂量归一化评估 / Dose normalization</h2><p>多剂量数据必须评估；可执行的图必须生成，缺少条件时保留具体原因。原始浓度图同时保留。</p>'
    for g in report['groups']:
        body+='<details><summary>'+e(g['group_id'])+' · '+e(g.get('execution_status',g['status']))+'</summary><p>'+e(', '.join(g['dataset_ids']))+'</p><p>'+e(g['reason'])+'</p>'
        for fid in g.get('selected_view_ids',[]):
            body+='<a href="sections/Q_PK_SHAPE/index.html#figure-'+e(fid)+'">查看 '+e(fid)+'</a> '
        body+='</details>'
    body+='<p><a href="dose_normalization_assessment.json">计算条件与来源记录</a>'
    if (root/'scientific_coverage_audit.html').exists():body+=' · <a href="scientific_coverage_audit.html">科学规则与缺图检查</a>'
    return body+'</p></section>'
