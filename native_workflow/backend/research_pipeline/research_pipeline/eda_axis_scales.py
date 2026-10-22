"""Declare source representation and rendering scales before EP; never alter values."""
import copy
import hashlib
import json
from pathlib import Path

CONFIG = Path(__file__).with_name('resources') / 'eda' / 'verified_axis_scales.json'
POLICY = (
    'For every selected view use axis_scales to distinguish stored values, the verified '
    'source-figure scale, and the requested display scale. In scale_rationale explain '
    'the choice for the question and any difference from the source. Source scale UNKNOWN '
    'is not a verified linear source axis. Already-log10 values (including log10 CFU and '
    'delta log10 CFU) use a linear display axis; never log them again. A logarithmic axis '
    'changes spacing only, not stored values. Never add pseudocounts, move zeros, resolve '
    'censoring or change units to enable a log axis. Unsupported log-X coordinates require '
    'a scoped linear/table fallback, not silent dropping. Select the offered, executable '
    'scale contract; if the required scale is absent, state NEEDS_CAPABILITY rather than '
    'promising a different scale in prose. EV must execute and report the same X/Y scales. '
    'Colour and point shape do not change data validity; retained uncertainty flags remain '
    'in companion records and the caption.'
)

def fingerprint(records):
    return hashlib.sha256(json.dumps(records,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def _selectors(spec):
    if spec['kind']=='source_projection':
        return spec['source_recipe']['series']
    return [s for p in spec['panels'] for s in p.get('series',[p])]

def prepare(candidates,tables):
    config=json.loads(CONFIG.read_text('utf8'));verified=config['verified_fields']
    approved=config.get('approved_display_fields',[])
    out=copy.deepcopy(candidates)
    hashes={did:fingerprint(t['records']) for did,t in tables.items()}
    for spec in out.values():
        if spec['kind']=='independent_points' and spec['id'].startswith(('INDEX_ECOLI__S','INDEX_KPN__S')):
            spec['palette_index']=int(spec['id'].rsplit('__S',1)[1])
        axis_fields={'x':[], 'y':[]}
        for sel in _selectors(spec):
            did=sel['dataset_id']; columns={c['id']:c for c in tables[did]['columns']}
            for axis in ('x','y'):
                keys=([sel[axis]] if sel.get(axis) else sel.get('value_columns',[]) if axis=='y' else [])
                for key in keys:
                    c=columns[key]; text=(c.get('header','')+' '+c.get('unit','')).lower()
                    match=next((v for v in verified if v['dataset_id']==did and v['column']==key and v['records_sha256']==hashes[did]),None)
                    field={'dataset_id':did,'column':key,'unit':c.get('unit','NOT_FOUND'),
                           'data_values':'ALREADY_LOG10' if 'log10' in text or 'log_10' in text else 'SOURCE_VALUES',
                           'source_plot_scale':match['scale'] if match else 'UNKNOWN',
                           'source_evidence':match['evidence'] if match else ''}
                    if field not in axis_fields[axis]:axis_fields[axis].append(field)
        source_x={f['source_plot_scale'] for f in axis_fields['x'] if f['source_plot_scale']!='UNKNOWN'}
        if 'x_scale' not in spec:
            spec['x_scale']=next(iter(source_x)) if len(source_x)==1 else 'linear'
        display_matches=[a for a in approved if any(f['dataset_id']==a['dataset_id'] and f['column']==a['column'] for f in axis_fields['x']) and hashes[a['dataset_id']]==a['records_sha256']]
        if display_matches and len(axis_fields['x'])==1:
            spec['x_scale']=display_matches[0]['scale']
            spec['display_scale_reason']=display_matches[0]['reason']
        if len(source_x)>1:raise ValueError('Conflicting source X scales need separate candidates: '+spec['id'])
        spec['axis_scales']={axis:{'fields':axis_fields[axis],'display_scale':spec[axis+'_scale'],
            'value_transform':'NONE'} for axis in ('x','y')}
        validate_spec(spec,tables)
    return out

def validate_spec(spec,tables):
    contract=spec['axis_scales']
    for axis in ('x','y'):
        scale=spec.get(axis+'_scale','linear')
        if scale not in {'linear','log10'}:raise ValueError('Unsupported '+axis+' scale')
        if contract[axis]['display_scale']!=scale:raise ValueError('Axis contract changed: '+spec['id'])
        if scale=='log10' and any(f['data_values']=='ALREADY_LOG10' for f in contract[axis]['fields']):
            raise ValueError('Double-log display prohibited: '+spec['id']+'/'+axis)
    if spec['x_scale']=='log10':
        if spec['kind'] in {'categorical_raw','frequency_bars','source_projection'}:
            raise ValueError('Log-X not implemented for this handler: '+spec['id'])
        for sel in _selectors(spec):
            t=tables[sel['dataset_id']]; scope=spec.get('record_scope',{}).get(sel['dataset_id'])
            for r in t['records']:
                if scope is not None and r['record_id'] not in scope:continue
                if spec['kind']=='source_id_profile' and r['source_raw_values'].get('c003_amt_cmt')!=1:continue
                if r['value_status'].get(sel['x'])=='QUANTIFIED':
                    v=r['source_raw_values'][sel['x']]
                    if not isinstance(v,(int,float)) or isinstance(v,bool) or v<=0:
                        raise ValueError('Log-X requires a scoped nonpositive/status fallback: '+spec['id'])

def validate(selected,candidates,tables):
    for vid in selected:validate_spec(candidates[vid],tables)

def verify_render(audit,spec):
    expected={axis:spec.get(axis+'_scale','linear') for axis in ('x','y')}
    if audit.get('rendered_scales')!=expected:
        raise ValueError('Renderer did not confirm requested axes: '+spec['id'])
