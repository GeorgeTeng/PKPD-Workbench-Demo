"""Source-bound presentation annotations. No inference of study joins or n units."""
import copy,json,re
from pathlib import Path
CONFIG=Path(__file__).parent/'resources/eda/study_annotations.v1.json'

def timekill_annotations(spec,tables,config):
    out=copy.deepcopy(spec)
    if len(out.get('panels',[]))!=1:return out
    selectors=out['panels'][0].get('series',[])
    dids={x['dataset_id'] for x in selectors}
    if len(dids)!=1:return out
    did=next(iter(dids));bindings=[b for b in config.get('timekill_bindings',[]) if b['dataset_id']==did]
    if not bindings:return out
    if len(bindings)!=1:raise ValueError('Ambiguous time-kill annotation binding')
    b=bindings[0];t=tables[did]
    if t['title']!=b['table_title'] or not t['records'] or not all(all(r.get(k)==b[k] for k in ['source_file_id','source_sha256','source_sheet']) for r in t['records']):
        raise ValueError('Time-kill study identity changed; annotation requires review')
    notes=t.get('notes','')
    if b['mic_evidence'] not in notes or b['exposure_evidence'] not in notes:
        raise ValueError('Time-kill MIC or exposure evidence changed')
    matches=re.findall(r'\b'+re.escape(b['compound_in_source'])+r'\s+MIC\s+(\d+(?:\.\d+)?)\s+mg/L\b',notes)
    values={float(x) for x in matches}
    if len(values)!=1 or next(iter(values))<=0:raise ValueError('Missing or conflicting time-kill MIC')
    value=next(iter(values))
    out['subtitle']=f"{b['compound_label']} · MIC {value:g} mg/L · Static in-vitro exposure"
    out['timekill_annotations']={'version':'EDA_TIMEKILL_MIC_1','dataset_id':did,'mic':value,'unit':'mg/L','method':'broth microdilution','evidence':b['mic_evidence'],'exposure_evidence':b['exposure_evidence'],'source_sha256':b['source_sha256'],'observations_changed':False}
    return out


def binding_annotations(spec,tables):
    """Use source table identity and selected assay header; never infer binding context."""
    out=copy.deepcopy(spec);r=out.get('source_recipe',{});series=r.get('series',[])
    if len(series)!=1:return out
    sel=series[0];t=tables[sel['dataset_id']]
    title=re.fullmatch(r'(Mouse|Rat) serum protein binding of (.+)',t.get('title',''),re.I)
    if not title or sel.get('projection')!='reported_mean_sd':return out
    species,compound=title.groups();species=species.capitalize()
    col=next((c for c in t['columns'] if c['id']==sel['y']),{})
    match=re.fullmatch(re.escape(species)+r' (ED|UF) % bound',col.get('header',''),re.I)
    if not match or col.get('unit')!='%':return out
    assay=match[1].upper();method={'ED':'Equilibrium dialysis','UF':'Ultrafiltration'}[assay]
    notes=t.get('notes','').lower()
    if method.lower() not in notes:return out
    short=f'{species} serum protein binding — {assay}'
    subtitle=f'{compound[0].upper()+compound[1:]} · {method}'
    caption=out.get('caption',r.get('caption',''))
    original='Source mean ± SD from triplicate pooled-serum experiments.'
    if 'triplicate' in notes and 'pooled serum' in notes and original in caption:
        caption=caption.replace(original,'Points = mean; error bars = SD. Triplicate pooled-serum experiments.',1)
    out.update(title=short,subtitle=subtitle,caption=caption)
    r.update(title=short,subtitle=subtitle,caption=caption,compact_single_series_legend=True)
    return out


def source_presentation(spec,tables):
    out=copy.deepcopy(spec);r=out.get('source_recipe',{})
    series=r.get('series',[])
    if not out.get('title'):return out
    # Internal dataset IDs remain in provenance, not in the display heading.
    title=' | '.join(p.strip() for p in out.get('title','').split(' | ') if not re.fullmatch(r'T\d{4}',p.strip()))
    if title!=out.get('title'):
        out['title']=title;r['title']=title
    if len(series)==1:
        sel=series[0];t=tables[sel['dataset_id']];cols={c['id']:c for c in t['columns']}
        notes=t.get('notes','')
        if 'Polymyxin B 1 mg/kg IV over 1 minute' in notes and '1 mg/kg IV |' in title:
            title=title.replace('1 mg/kg IV |','1 mg/kg IV over 1 min |')
            out['title']=title;r['title']=title
        if cols.get(sel.get('x'),{}).get('unit')=='h' and re.fullmatch(r'(?:Dose |Dosing )?Interval \(h\)',r.get('x_label',''),re.I):
            r['x_label_format']='REGIMEN_Q_HOURS'
        if cols.get(sel.get('y'),{}).get('meaning')=='MIC':r['y_tick_policy']='MIC_DOUBLING'
    return binding_annotations(out,tables)


def annotate(spec,tables,config=None):
    config=config or json.loads(CONFIG.read_text(encoding='utf8'))
    out=copy.deepcopy(spec)
    if out.get('kind')=='source_projection':return source_presentation(out,tables)
    if out.get('kind')=='source_id_profile':return timekill_annotations(out,tables,config)
    if out.get('kind')!='reported_interval' or len(out.get('panels',[]))!=1:return out
    panel=out['panels'][0];did=panel.get('dataset_id')
    bindings=(config or json.loads(CONFIG.read_text(encoding='utf8')))['bindings']
    matches=[b for b in bindings if b['dataset_id']==did]
    if not matches:return out
    if len(matches)!=1:raise ValueError('Ambiguous study annotation binding')
    b=matches[0];t=tables[did];mic=tables[b['mic_dataset_id']]
    def require(ok,message):
        if not ok:raise ValueError('EDA study annotation: '+message)
    for table in [t,mic]:
        require(all(r.get('source_sha256')==b['source_sha256'] and r.get('source_file_id')==b['source_file_id'] and r.get('source_sheet')==b['source_sheet'] for r in table['records']),'source binding changed')
    require(all(b[k] in t.get('notes','') for k in ['regimen_evidence','nd_evidence','baseline_evidence']),'study notes changed; recheck annotation')
    require(b['mic_drug_evidence'] in mic.get('notes',''),'MIC compound evidence missing')
    cols={c['id']:c for c in t['columns']};mcols={c['id']:c for c in mic['columns']}
    require(panel['facet']==b['strain_field'] and panel['x']==b['dose_field'],'unsupported endpoint selector')
    require(cols[panel['x']]['unit']==b['dose_unit'] and mcols[b['mic_field']]['unit']==b['mic_unit'],'annotation unit mismatch')
    scope=out.get('record_scope',{}).get(did)
    rows=[r for r in t['records'] if scope is None or r['record_id'] in scope]
    strains={r['source_raw_values'][b['strain_field']] for r in rows}
    require(len(strains)==1,'split strain panels before annotation')
    strain=next(iter(strains));mr=[r for r in mic['records'] if r['source_raw_values'][b['mic_strain_field']]==strain]
    require(len(mr)==1,'MIC match absent or ambiguous')
    mr=mr[0];v=mr['source_raw_values'];value=v[b['mic_field']]
    require(mr['value_status'][b['mic_field']]=='QUANTIFIED' and isinstance(value,(int,float)) and not isinstance(value,bool) and value>0,'MIC is not a supported positive value')
    species=v[b['mic_species_field']]
    require(isinstance(species,str) and bool(species),'organism missing')
    out['subtitle']=f"{b['animal']} | {species} {strain} | {b['drug']} MIC {value:g} {b['mic_unit']} | {b['regimen']}"
    quantified=[r for r in rows if r['value_status'].get(panel['y'])=='QUANTIFIED']
    ns=[r['source_raw_values'].get(panel['n']) for r in quantified]
    known_n=bool(ns) and all(r['value_status'].get(panel['n'])=='QUANTIFIED' and isinstance(n,(int,float)) and not isinstance(n,bool) and n>0 for r,n in zip(quantified,ns))
    ntext=f"Reported n={ns[0]:g} per quantified dose group; counting unit not further specified in the supplied records." if known_n and len(set(ns))==1 else 'Sample sizes and their stated basis remain as reported per group.'
    # Existing source qualifiers remain; remove only the already-explicit generic duplicate.
    caption=out['caption']
    for sentence in ['Error bars are reported mean +/- SD, not confidence intervals.','Dashed baselines are the source-reported 0 h means.','ND remains unavailable; no fitted dose-response curve or baseline pairing.']:
        caption=caption.replace(sentence,'')
    prefix=f"Points = means; bars = {out['error_type']}. {ntext} Dashed line = this experiment's 0 h mean. No fitted dose-response curve or baseline pairing."
    # Idempotent rebuild for already-annotated specs.
    prior=out.get('study_annotations',{})
    if prior:caption=prior['original_caption_tail']
    out['caption']=prefix+(' '+caption.strip() if caption.strip() else '')
    missing=[r for r in rows if r not in quantified]
    # Only this source-defined ND category is expanded. Unknown categories stay literal.
    status_note='; '.join(f"{r['source_raw_values'][panel['x']]:g} mg/kg/day: ND (not determined)" if r['source_raw_values'].get(panel['y'])=='ND' else f"{r['source_raw_values'][panel['x']]:g} mg/kg/day: {r['source_raw_values'].get(panel['y'])!s} (source status: {r['value_status'].get(panel['y'])})" for r in missing)
    out['study_annotations']={'version':'EDA_STUDY_ANNOTATIONS_1','original_caption_tail':caption.strip(),'mic_source':{'dataset_id':b['mic_dataset_id'],'record_id':mr['record_id'],'source_cell':mr['source_cells'][b['mic_field']],'value':value,'unit':b['mic_unit']},'endpoint_record_ids':[r['record_id'] for r in rows],'status_record_ids':[r['record_id'] for r in missing],'status_note':status_note,'regimen_evidence':b['regimen_evidence'],'n_basis':'REPORTED_COUNT; NOT_INFERRED_ANIMAL_IDENTITY','scope_evidence':b['scope_evidence']}
    return out
