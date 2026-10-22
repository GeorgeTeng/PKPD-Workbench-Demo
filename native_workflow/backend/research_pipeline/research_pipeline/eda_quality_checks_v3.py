"""Three bounded EDA checks. Display semantics never reclassify scientific Data."""
import copy
import re
import textwrap
from pathlib import Path
from .common import read_json
from . import context_builder as cb

CONFIG=Path(__file__).parent/'resources/eda/table_blocks.v1.json'
ELEMENTS=['POINTS','CONNECTING_LINES','ERROR_BARS','STATUS_TEXT','CONTEXT_TABLE','BARS']
INSTRUCTION=(
 'Three checks are mandatory: (1) use semantic_audit row roles and table-block meanings; '
 'structural/context rows are not missing numeric observations, and source summaries are not individual observations. '
 '(2) use render_facts from the current image: literal status text, summary labels, zero qualifications, units and coordinates. '
 '(3) match every visual assertion to the actual elements and record scope of that figure. '
 'In visual_support.element_claims, enumerate the elements actually inspected for each cited figure. '
 'Do not describe connecting lines, drawn uncertainty bars, or overlapping assays when they are absent or in separate figures. '
 'Table-only error-bar endpoints support a NON_GRAPHICAL statement, never a claim that bars are visible. '
 'Describe late increases when present without assigning a mechanism or calling them errors. Last quantified/plotted times indicate sampled evidence coverage, not the end or duration of exposure. '
 'Stage evidence distinguishes transport from inspection. EP/EP_FINALIZE have no generated images yet; their open items are historical stage-scoped statements. '
 'EI/ER receive generated EDA images; original publication images and reconstruction fidelity remain a distinct unreviewed object. '
 'ER must independently check semantic accuracy, readability, and figure/text/stage consistency; PASS requires all three checks PASS. '
 'A finding may combine table and visual evidence, but the claimed visible elements must be supported by its own cited figures.')

def require(ok,message):
    if not ok:raise ValueError('EDA quality: '+message)

def table_roles(table):
    contracts=[c for c in read_json(CONFIG)['tables'] if c['title']==table['title']]
    if not contracts:return None
    require(len(contracts)==1,'ambiguous table-block contract')
    c=contracts[0]
    require(table['columns']==c['columns'] and table['notes']==c['notes'],'table-block schema changed; review mapping')
    actual=[{'source_row':r['source_row'],'raw':r['source_raw_values'],'status':r['value_status']} for r in table['records']]
    expected=[{k:v for k,v in r.items() if k!='role'} for r in c['rows']]
    require(actual==expected,'table-block records changed; review mapping before rendering')
    return c,{r['record_id']:m['role'] for r,m in zip(table['records'],c['rows'],strict=True)}

def prepare(candidates,tables):
    """Apply explicit block scopes after standalone splitting, retaining all source rows."""
    out=copy.deepcopy(candidates)
    roles={did:table_roles(t) for did,t in tables.items()}
    for s in out.values():
        if s['kind']!='source_projection':continue
        recipe=s['source_recipe'];companions=[];account=[]
        for did in sorted({x['dataset_id'] for x in recipe['series']}):
            mapped=roles[did]
            if not mapped:continue
            contract,role=mapped
            admitted=s.get('record_scope',{}).get(did,[r['record_id'] for r in tables[did]['records']])
            keep=[rid for rid in admitted if role[rid]=='OBSERVATION']
            s.setdefault('record_scope',{})[did]=keep
            recipe.setdefault('record_scope',{})[did]=keep
            for r in tables[did]['records']:
                account.append({'dataset_id':did,'record_id':r['record_id'],'role':role[r['record_id']],
                                'source_row':r['source_row']})
                if role[r['record_id']]=='CONTEXT_OBSERVATION':
                    companions.append({'dataset_id':did,'record_id':r['record_id'],
                        'values':{label:r['source_raw_values'][col] for label,col in contract['context_columns'].items()},
                        'source_cells':r['source_cells'],'raw_values':r['source_raw_values'],
                        'value_status':r['value_status'],'source_sha256':r['source_sha256']})
            s['caption']+=' A separate source block is retained below as a literal context table; its headings and organism names are not missing strain MICs. The numeric isolate plot and the literal context table each retain their source units; no unit harmonization or cross-study pooling.'
        recipe['context_rows']=companions
        recipe['semantic_audit']={'rows':account,'source_values_changed':False,'source_status_changed':False}
        # Source-native unit labels: do not manufacture a unit for NOT_FOUND.
        cols=[next(c for c in tables[x['dataset_id']]['columns'] if c['id']==x['y']) for x in recipe['series']]
        recipe['label_low_positive']=all(c.get('meaning')=='CONCENTRATION' for c in cols)
        xcols=[next((c for c in tables[x['dataset_id']]['columns'] if c['id']==x.get('x')),None) for x in recipe['series']]
        if all(c.get('meaning')=='DOSE' for c in cols) and all(c and re.search(r'\binterval\b',c['header'],re.I) for c in xcols):
            require(len({c['header'] for c in xcols})==1,'different interval definitions share an axis')
            s['x_label']=xcols[0]['header']
            s['axis_detail']={'enabled':False,'source_interval_ticks':True}
            recipe.update(x_label=s['x_label'],axis_detail=copy.deepcopy(s['axis_detail']))
        if 'unit in panel label' in s['y_label'] or 'unit shown in each panel' in s['y_label']:
            require(len({(c['header'],c['unit']) for c in cols})==1,'different source quantities share an axis')
            c=cols[0];s['y_label']=c['header']+(' (unit not reported)' if c['unit'] in {'NOT_FOUND',''} else '')
        if any('ED50' in c['header'] for c in cols):
            s['caption']+=' ED50 is the source-reported fitted quantity; its effect reference is not established by this display.'
        for did in sorted({x['dataset_id'] for x in recipe['series']}):
            notes=tables[did].get('notes','')
            if re.search(r'\bND not determined\b',notes,re.I):s['caption']+=' ND = not determined (source definition).'
            if 'not detected, assay limit below 0.5' in notes:s['caption']+=' N.D. = not detected; source assay limit below 0.5 µg/ml. No value is imputed.'
            if 'Table 2 gives Cmin 0.36' in notes and any(x['dataset_id']==did and x['y']=='c002_10_mg_kg_mean_mg_l' for x in recipe['series']):
                s['caption']+=' Source-recorded digitized zeros at 8 and 12 h: reading uncertainty about ±0.2 mg/L; analytical zero or BLQ is not established. Conflict with reported Cmin 0.36 mg/L remains unresolved.'
        # Correct stale inherited caption wording without reinterpreting intervals.
        s['caption']=s['caption'].replace('bar endpoints have unspecified uncertainty type and remain in the companion table.',
            'the source caption calls its bars SD, while mean definitions conflict. Digitized bar endpoints remain table-only, not drawn or resolved here.')
        s['y_label']='\n'.join(textwrap.wrap(s['y_label'],width=37))
        recipe.update(caption=s['caption'],y_label=s['y_label'])
    return out

def annotate(projection,tables):
    """Display-only labels; raw source status and value stay byte-equivalent."""
    p=copy.deepcopy(projection)
    for r in p['rows']:
        label=re.sub(r'^T[0-9]+ \| ','',r.get('category','')).strip()
        summary=bool(re.fullmatch(r'(?:Avg\.?|Average|Mean(?:\s*±\s*SD)?)',label,re.I))
        r['display_role']='SOURCE_SUMMARY' if summary else 'SOURCE_OBSERVATION'
        r['category_label']=label+('\n[source summary]' if summary else '')
        raw=r['raw_y']
        r['status_label']=('Empty source cell' if raw is None else str(raw))
        if r.get('display_exclusion_reason'):r['status_label']+=' | '+r['display_exclusion_reason']
        if summary and raw is None:r['status_label']='Not reported for summary row'
        r['zero_qualification']=''
        if raw==0 and 'digitiz' in tables[r['dataset_id']].get('notes','').lower():
            r['zero_qualification']='Source-recorded digitized zero; analytical zero / BLQ not established'
    return p

def inspect_render(out,specs,tables):
    """Check actual R surface facts against source-bound projection expectations."""
    from . import eda_display_catalog_v5 as catalog
    by_id={s['id']:s for s in specs};results={}
    for a in read_json(out/'manifest.json')['artifacts']:
        s=by_id[a['id']];rows=read_json(out/a['data'])
        facts=a.get('render_facts')
        require(facts is not None,'renderer omitted surface facts: '+s['id'])
        require(facts['x_label']==s['x_label'] and facts['y_label']==s['y_label'],'rendered axis title differs')
        require(facts['figure_index']==s['figure_index'],'rendered figure index differs')
        require(facts['panels']==1,'rendered figure is not standalone')
        if s['kind']=='source_projection':
            p,_=catalog.materialize(s,tables)
            require(rows==p['rows'],'source/display row annotations changed')
            valid=[r for r in rows if r['y'] is not None and r.get('plot_eligible',True)]
            missing=[r for r in rows if r not in valid]
            require(facts['point_count']==len(valid),'point count mismatch')
            positive=[r for r in valid if r['y']>0]
            low=[r['raw_y'] for r in positive if r['y']<=max(z['y'] for z in positive)*.02] if positive and p.get('label_low_positive') and p['scale']=='linear' else []
            require(len(facts['low_positive_values'])==len(low) and all((float(a)==b if isinstance(b,(int,float)) else a==b) for a,b in zip(facts['low_positive_values'],low)), 'low positive source labels missing or altered')
            require(facts['line_segments']==0,'unexpected connecting lines')
            if not p['categorical'] and len({r['x'] for r in rows})<=12:
                require(set(facts['x_breaks'])=={r['x'] for r in rows},'source header times missing from axis')
            errors=[r for r in valid if r['error'] is not None and (p['scale']!='log10' or r['y']-r['error']>0)]
            require(facts['error_bar_count']==len(errors),'drawn uncertainty differs from source projection')
            require(facts['status_labels']==[r['status_label'] for r in missing],'literal status labels lost')
            require(facts.get('status_display')=='caption' and not facts['status_y'],'status subplot must be replaced by a note')
            require(facts.get('status_record_ids')==[r['record_id'] for r in missing],'status note source records lost')
            require(bool(facts.get('status_note'))==bool(missing),'status note missing or spurious')
            require(all(label in facts['status_note'] for label in facts['status_labels']),'literal status missing from caption')
            require(facts['context_rows']==len(p.get('context_rows',[])),'context block omitted')
            require(read_json(out/(s['id']+'.context_rows.json'))==p.get('context_rows',[]),'context block content changed')
            if p['categorical']:
                expected=list(dict.fromkeys(r['category_label'] for r in rows))
                require(facts['category_labels']==expected,'category names/order changed or missing categories dropped')
            require(facts['zero_qualifications']==list(dict.fromkeys(r['zero_qualification'] for r in rows if r['zero_qualification'])), 'zero qualification omitted')
        results[s['id']]={'status':'PASS','render_facts':facts,'image_ref':cb.file_ref(out/a['png']),
            'record_ids':sorted({r['record_id'] for r in rows}|{r['record_id'] for r in s.get('source_recipe',{}).get('context_rows',[])}),
            'semantic_audit':s.get('source_recipe',{}).get('semantic_audit',{})}
    return {'version':'EDA_THREE_CHECKS_1','preplot_semantics':'PASS','render_surface':'PASS',
            'narrative_consistency':'PENDING','figures':results,'scientific_release':False}

def current_plan(plan,final):
    p=copy.deepcopy(plan)
    p.update(analyses=copy.deepcopy(final['task_decisions']),open_items=copy.deepcopy(final['open_items']),
             dataset_dispositions=copy.deepcopy(final['dataset_dispositions']))
    p['open_items_scope']='EP_FINALIZE before rendered images existed; evaluate current review-stage evidence separately.'
    p['historical_EP_open_items']={'stage':'EP_BEFORE_RENDER','items':copy.deepcopy(plan['open_items'])}
    return p

def stage_evidence(stage,inputs):
    figures=inputs.get('figure_bundle',{}).get('figures',[])
    return {'stage':stage,'generated_eda_images':[
        {'figure_id':f['figure_id'],'sha256':f['image_ref']['sha256'],
         'transported_to_this_call':f.get('image_supplied_to_model',False),
         'inspection':'TO_BE_DECLARED_BY_REVIEWER'} for f in figures],
        'original_publication_images':{'provided_in_this_call':False,'reconstruction_fidelity':'NOT_ASSESSED'},
        'rule':'Historical absence of generated images at EP is not their current absence. Attachment does not prove inspection. Publication-figure review is a separate object.'}

def validate_consistency(findings,quality):
    """Reject impossible visual claims, missing inspections, and wrong record anchors."""
    views=quality['figures'];checks=findings['figure_checks']
    require(len(checks)==len(views) and {c['figure_id'] for c in checks}==set(views),'figure inspection accounting incomplete')
    inspected={c['figure_id'] for c in checks if c['inspection']=='INSPECTED'}
    for f in findings['findings']:
        v=f['visual_support'];claims=v['element_claims']
        require(len(claims)==len({c['figure_id'] for c in claims}),'duplicate element claim')
        require({c['figure_id'] for c in claims}==set(v['figure_ids']),'each visual reference needs an element claim')
        for c in claims:
            require(c['figure_id'] in inspected,'claim cites an uninspected figure')
            facts=views[c['figure_id']]['render_facts']
            require(bool(c['elements']) and set(c['elements'])<=set(facts['elements']),'claimed graphical element absent from figure')
        if v['status']=='OBSERVED':
            records=set().union(*(set(views[i]['record_ids']) for i in v['figure_ids']))
            require(bool(set(f['record_scope']) & records),'visual claim has no record in its cited figures')
    return {'status':'PASS','scope':'Structured image/element/record consistency; prose independently reviewed by ER.',
            'inspected_figures':sorted(inspected),'not_assessed_figures':sorted(set(views)-inspected)}

def validate_review(review):
    require(review['decision']!='PASS' or all(v=='PASS' for v in review['quality_checks'].values()),
            'ER PASS requires all three checks PASS')
