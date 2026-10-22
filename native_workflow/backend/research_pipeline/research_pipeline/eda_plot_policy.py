"""Deterministic EDA display policy; never edits source rows or grants analysis permission."""
import copy
import hashlib
import html
import json
import math
import re
from pathlib import Path
from .common import read_json

CONFIG=Path(__file__).parent/'resources/eda/plot_policy.v1.json'
POLICY_TEXT=("Use one time axis in each main figure. Prefer explicitly evidenced paper sampling times; "
 "otherwise retain the declared source/digitized basis without calling it paper-verified. Keep original pixel times "
 "and source cells in immutable records; omit only confirmed redundant pixel fields from working copies. Offer separate time-check figures only for an explicit "
 "time-source conflict or requested check; numerical differences alone do not create extra plots. "
 "Each figure is standalone with its own X/Y titles, ticks, units/basis, legend and figure index. "
 "Never combine different administration routes in one figure; compare doses only within a route. "
 "Use readable range-aware Y ticks and finer early X ticks for time profiles, preserving linear time spacing. Use uniform observation markers; no special first-point marks, time callouts or automatic zoom views. "
 'Label the displayed time basis in plain English: nominal study-method sampling times, reported sampling schedule, or digitized figure times, as supported by the selected column and its evidence. A paper sampling schedule does not establish actual per-animal collection times. Do not print internal time-basis codes in captions or imply that a display choice finalizes the modeling time axis. '
 "Display selection does not reconcile the modeling time axis or change Rules/data permissions.")

def number(value):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value)

def quantified(r,col):
    return r.get('value_status',{}).get(col)=='QUANTIFIED' and number(r['source_raw_values'].get(col))

def _matrix_scope(text):
    text=text.lower()
    result=set()
    for key,pattern in [('plasma',r'\bplasma\b|\bblood\b'),('serum',r'\bserum\b'),
                        ('elf',r'\belf\b'),('balf',r'\bbalf\b'),('whole_lung',r'whole[- ]lung')]:
        if re.search(pattern,text):result.add(key)
    if re.search(r'\btissue\b',text):result.add('whole_lung')
    return result


def clause_applies(clause,table):
    """Scope warnings/schedules to this table, not every dataset sharing study notes."""
    notes=html.unescape(table.get('notes',''))
    match=re.search(r'\bMatrix:\s*([^;.\n]+)',notes,re.I)
    matrix=_matrix_scope(match.group(1) if match else table.get('title',''))
    stated=_matrix_scope(clause)
    if stated and (not matrix or matrix.isdisjoint(stated)):return False
    # 'especially SC' qualifies a plasma-wide conflict; it does not exempt IT plasma.
    explicit_routes=_route_tokens(re.sub(r',?\s*especially\s+[A-Z]+','',clause))
    local_routes=_route_tokens(table.get('title',''))
    if explicit_routes and (not local_routes or local_routes.isdisjoint(explicit_routes)):return False
    return True


def time_decision(table,config=None):
    columns={c['id']:c for c in table['columns'] if c.get('meaning')=='TIME'}
    pixels=[c for c,v in columns.items() if re.search(r'pixel|digitiz',v.get('header','')+' '+c,re.I)]
    nominal=[c for c in columns if c not in pixels]
    if len(pixels)!=1 or len(nominal)!=1:return None
    pixel,nominal=pixels[0],nominal[0]
    notes=html.unescape(table.get('notes',''));meta=table.get('time_axis') or {}
    clauses=[c.strip(' -') for c in re.split(r'\n|;|, and |\.\s+',notes) if c.strip(' -')]
    cited=meta.get('paper_time_column')==nominal and bool(meta.get('evidence'))
    evidence=meta.get('evidence') if cited else ''
    for clause in clauses:
        if not clause_applies(clause,table):continue
        matched=re.search(r'(?:nominal|sampling) times? (?:from|reported in|specified in) (?:the )?(?:PK methods|paper|publication|methods)',clause,re.I)
        if matched and not re.search(r'\b(?:no|not|never|assume)\b',clause[:matched.start()],re.I):
            if not evidence:evidence=clause
        # Explicit source schedules are accepted only when this SAME matrix/route
        # is named and every existing source time already belongs to the schedule.
        schedule=re.search(r'\bnominal (?:sampling )?times?\s+([0-9.,\s]+)\s*h\b',clause,re.I)
        if schedule and _matrix_scope(clause) and columns[nominal].get('unit')=='h' and not re.search(r'\b(?:no|not|never|assume)\b',clause[:schedule.start()],re.I):
            values=[float(x) for x in re.findall(r'\d+(?:\.\d+)?',schedule.group(1))]
            rows=table['records']
            if rows and values and all(quantified(r,nominal) and any(math.isclose(r['source_raw_values'][nominal],v,rel_tol=0,abs_tol=1e-12) for v in values) for r in rows):
                if not evidence:evidence=clause
    verified=bool(evidence);chosen=nominal if verified else pixel
    basis='PAPER_SAMPLING_TIMES' if verified else 'DIGITIZED_TIME_UNCONFIRMED_NOMINAL'
    reasons=[];excluded=[]
    if meta.get('source_conflict') is True:reasons.append('Explicit structured time-source conflict')
    if meta.get('diagnostic_requested') is True:reasons.append('Explicitly requested time-source check')
    for clause in clauses:
        if re.search(r'\b(?:time|times|sampling)\b',clause,re.I) and re.search(r'conflict|contradict|differ from|discrepan',clause,re.I) and not re.search(r'\b(?:no|not|without)\b',clause,re.I):
            (reasons if clause_applies(clause,table) else excluded).append(clause)
    alternate=pixel if chosen==nominal else nominal
    return {'dataset_id':table['dataset_id'],'primary':chosen,'alternate':alternate,
        'basis':basis,'evidence':evidence or 'No explicit paper-time provenance found; preserve digitized basis.',
        'trigger':bool(reasons),'reasons':reasons,'out_of_scope_conflicts':excluded,
        'diagnostic_available':all(quantified(r,alternate) for r in table['records']),
        'pixel_time_retained':pixel,'nominal_time_retained':nominal,'source_rows_modified':False}


def scoped_caption(caption,tables):
    """Keep source warnings in records, but do not attach another series' conflict to a figure."""
    caption=caption.replace('Plasma timing/protocol discrepancy and SC whole-lung peak conflict remain open.',
        'Plasma timing/protocol discrepancy remains open. SC whole-lung peak conflict remains open.')
    sentences=re.split(r'(?<=[.!?])\s+',caption.strip())
    return ' '.join(sentence for sentence in sentences if not re.search(r'conflict|discrepan',sentence,re.I)
        or any(clause_applies(sentence,t) for t in tables))



def selected_records(table,spec):
    ids=spec.get('record_scope',{}).get(table['dataset_id'])
    return [r for r in table['records'] if ids is None or r['record_id'] in ids]

def _panel_pieces(spec,tables):
    if spec['kind']=='source_projection':
        # Validate the complete registered recipe before splitting it.
        from .eda_display_catalog import materialize
        materialize(spec,tables)
        groups={}
        for s in spec['source_recipe']['series']:groups.setdefault(s['panel'],[]).append(s)
        for panel,series in groups.items():
            child=copy.deepcopy(spec);r=child['source_recipe'];r['series']=copy.deepcopy(series)
            scope={}
            for s in series:
                scope.setdefault(s['dataset_id'],set()).update(x['record_id'] for x in tables[s['dataset_id']]['records'] if all(x['source_raw_values'].get(k)==v for k,v in s['filters'].items()))
            child['record_scope']={k:sorted(v) for k,v in scope.items()}
            r['record_scope']=copy.deepcopy(child['record_scope'])
            child['panels']=[{'label':panel,'series':[{'dataset_id':s['dataset_id']} for s in series]}]
            child['x_label']=r['x_label'];child['y_label']=r['y_label']
            if 'unit shown in each panel' in child['y_label']:
                units={c['unit'] for s in series for c in tables[s['dataset_id']]['columns'] if c['id']==s['y']}
                if len(units)!=1:raise ValueError('EDA display: concentration units must remain separate')
                child['y_label']=child['y_label'].replace('unit shown in each panel',next(iter(units)))
            yield child
    else:
        for panel in spec['panels']:
            if spec['kind']=='reported_interval':
                t=tables[panel['dataset_id']];cols=[panel['facet']]+([panel['unit_column']] if panel.get('unit_column') else [])
                groups={}
                for r in t['records']:
                    key=tuple(str(r['source_raw_values'].get(c,'')) for c in cols)
                    groups.setdefault(key,[]).append(r['record_id'])
                for key,ids in groups.items():
                    child=copy.deepcopy(spec);child['panels']=[copy.deepcopy(panel)]
                    child['panels'][0]['label']=' | '.join(key)
                    child['record_scope']={t['dataset_id']:ids}
                    if len(key)>1:child['y_label']=key[0]+' ('+key[1]+')'
                    yield child
            else:
                child=copy.deepcopy(spec);child['panels']=[copy.deepcopy(panel)]
                if panel.get('x_label'):child['x_label']=panel['x_label']
                if panel.get('y_label'):child['y_label']=panel['y_label']
                yield child


def _route_tokens(text):
    # Abbreviations are case-sensitive: ordinary English "it" is not a route.
    text=str(text or '')
    routes=set(re.findall(r'\b(?:IT|IV|SC|IM|IP|PO)\b',text))
    names={'intratracheal':'IT','intravenous':'IV','subcutaneous':'SC',
           'intramuscular':'IM','intraperitoneal':'IP','oral':'PO'}
    routes.update(code for name,code in names.items() if re.search(r'\b'+name+r'\b',text,re.I))
    return routes


def _selector_route(selector,tables):
    table=tables[selector['dataset_id']]
    # Use explicit route metadata/title/series labels, not contextual notes that
    # may discuss other administration routes or other studies.
    meta=table.get('metadata',{})
    routes=_route_tokens(table.get('route'))|_route_tokens(meta.get('route'))
    routes|=_route_tokens(table.get('title'))
    routes|=_route_tokens(selector.get('route'))|_route_tokens(selector.get('label'))
    routes|=_route_tokens(selector.get('group'))
    if len(routes)>1:
        raise ValueError('EDA display: conflicting route labels for '+selector['dataset_id'])
    return next(iter(routes)) if routes else 'UNSPECIFIED:'+selector['dataset_id']


def _pieces(spec,tables):
    for piece in _panel_pieces(spec,tables):
        groups={}
        for selector in _selectors(piece):
            groups.setdefault(_selector_route(selector,tables),[]).append(selector)
        # Route-unrelated displays need no invented administration assignment.
        if not any(not key.startswith('UNSPECIFIED:') for key in groups):
            yield piece
            continue
        for route,series in groups.items():
            child=copy.deepcopy(piece)
            ids={s['dataset_id'] for s in series}
            if child['kind']=='source_projection':
                recipe=child['source_recipe'];recipe['series']=copy.deepcopy(series)
                child['panels'][0]['series']=[{'dataset_id':s['dataset_id']} for s in series]
                if 'record_scope' in recipe:recipe['record_scope']={k:v for k,v in recipe['record_scope'].items() if k in ids}
                recipe['administration_route']=route
            elif 'series' in child['panels'][0]:
                child['panels'][0]['series']=copy.deepcopy(series)
            if 'record_scope' in child:child['record_scope']={k:v for k,v in child['record_scope'].items() if k in ids}
            child['administration_route']=route
            child['panels'][0]['label']=child['panels'][0].get('label','Source observations')+' | '+route
            yield child


def _selectors(spec):
    if spec['kind']=='source_projection':return spec['source_recipe']['series']
    return spec['panels'][0].get('series',[spec['panels'][0]])

def _axis(spec,tables):
    selectors=[s for s in _selectors(spec) if s.get('x')]
    time_columns=[next((c for c in tables[s['dataset_id']]['columns'] if c['id']==s['x'] and c.get('meaning')=='TIME'),None) for s in selectors]
    if selectors and all(time_columns):
        units={c['unit'] for c in time_columns}
        if len(units)!=1:raise ValueError('EDA display: mixed time units must use independent figures')
        checks=spec.get('display_policy',{}).get('time_decisions',[])
        label='Time'
        if checks and all(s['x']==d['primary'] and d['basis']=='PAPER_SAMPLING_TIMES' for s in selectors for d in checks if s['dataset_id']==d['dataset_id']):label='Nominal sampling time'
        elif all(re.search(r'pixel|digitiz',c['header'],re.I) for c in time_columns):label='Digitized time'
        spec['x_label']=label+' ('+next(iter(units))+')'


def axis_detail_policy(spec,tables):
    """Refine early time ticks only for time profiles; keep categorical/index X axes intact."""
    if spec['kind']=='source_projection' and spec['source_recipe'].get('categorical'):
        return {'enabled':False}
    units=set()
    for selector in _selectors(spec):
        cols={c['id']:c for c in tables[selector['dataset_id']]['columns']}
        x=cols.get(selector.get('x'))
        if x and x.get('meaning')=='TIME':units.add(x.get('unit',''))
        elif selector.get('x_from_header'):units.add(selector.get('x_header_unit','h'))
        else:return {'enabled':False}
    result={'enabled':len(units)==1,'time_unit':next(iter(units)) if len(units)==1 else ''}
    if any(s.get('x_from_header') for s in _selectors(spec)):result['time_from_headers']=True
    return result


def time_caption(spec):
    """Describe the selected display column, never upgrade it to actual sampling or fit approval."""
    checks={d['dataset_id']:d for d in spec.get('display_policy',{}).get('time_decisions',[])}
    statements=[]
    for selector in _selectors(spec):
        d=checks.get(selector['dataset_id'])
        if not d:continue
        col=selector.get('x')
        if col==d['pixel_time_retained']:
            text='Digitized figure times are shown; nominal/source times remain in the source records.'
        elif col==d['nominal_time_retained']:
            if d['basis']=='PAPER_SAMPLING_TIMES':
                if re.search(r'\bnominal\b',str(d.get('evidence','')),re.I):
                    text=('Nominal sampling times from the study methods are shown.' if re.search(r'methods',str(d.get('evidence','')),re.I) else 'Reported nominal sampling times are shown.')
                else:
                    text='The reported sampling schedule is shown; actual per-animal collection times are not established by this schedule.'
            else:
                text='Recorded source times are shown; their relation to the study sampling schedule remains unconfirmed.'
            text+=' Digitized times remain in the source records.'
        else:continue
        if text not in statements:statements.append(text)
    if statements:
        statements.append('This display choice does not finalize the modeling time basis.')
    return ' '.join(statements)


def readable_heading(spec):
    """Presentation-only normalization of the existing terminal-PD title grammar."""
    prefix='Terminal lung bacterial burden | '
    title=spec.get('title','')
    parts=title.split(' | ')
    if len(parts)>1 and all(p.strip()==parts[0].strip() for p in parts):
        title=parts[0].strip();spec['title']=title
    if spec.get('kind')!='categorical_raw' or not title.startswith(prefix):return
    parts=title[len(prefix):].split(' | ')
    if len(parts)!=2:return
    strain,treatment=parts
    dose=re.fullmatch(r'(.+?)\s*\((\d+(?:\.\d+)?)\s*mg/kg/d(?:ay)?\)',treatment)
    if not dose:return  # Unknown forms remain literal; the renderer wraps them.
    spec['title']=strain+' | Lung bacterial burden'
    line=dose.group(1).strip()+' '+dose.group(2)+' mg/kg/day'
    subtitle=spec.get('subtitle','')
    spec['subtitle']=line+('\n'+subtitle if subtitle else '')


def normalize(candidates,tables):
    decisions={k:d for k,t in tables.items() if (d:=time_decision(t)) is not None}
    out={};seen=set()
    for spec in candidates.values():
        for i,piece in enumerate(_pieces(spec,tables),1):
            primary=copy.deepcopy(piece);checks=[]
            for s in _selectors(primary):
                d=decisions.get(s['dataset_id'])
                if d and s.get('x') in {d['primary'],d['alternate']}:
                    s['x']=d['primary'];checks.append(d)
            variants=[(primary,False)]
            if any(d['trigger'] and d['diagnostic_available'] for d in checks):
                diagnostic=copy.deepcopy(primary)
                diagnostic['y_scale']='linear'
                if diagnostic['kind']=='source_projection':diagnostic['source_recipe']['scale']='linear'
                for s in _selectors(diagnostic):
                    d=decisions.get(s['dataset_id'])
                    if d and d['trigger'] and d['diagnostic_available']:s['x']=d['alternate']
                variants.append((diagnostic,True))
            for child,diagnostic in variants:
                # Ignore panel captions/time labels in identity: same selector, scale and
                # record set cannot be re-offered as a separate pixel-time main view.
                selectors=copy.deepcopy(_selectors(child))
                for s in selectors:s.pop('panel',None);s.pop('label',None)
                key=json.dumps([child['kind'],child['y_scale'],selectors,child.get('record_scope',{}),diagnostic],sort_keys=True)
                if key in seen:continue
                seen.add(key)
                vid=spec['id']+'__S'+str(i)+('__TIME_CHECK' if diagnostic else '')
                child['id']=vid;child['ncol']=1
                child['standalone']=True;child['legend_title']='Series / group'
                child['display_policy']={'version':'EDA_PLOT_POLICY_1','role':'TIME_CHECK' if diagnostic else 'MAIN',
                    'parent_view':spec['id'],'time_decisions':copy.deepcopy(checks),'one_panel':True}
                label=piece['panels'][0].get('label','Source observations')
                label=re.sub(r'\s*\|\s*(?:Recorded source time|Pixel time alternative)\s*','',label,flags=re.I)
                child['title']=('Time-source check | ' if diagnostic else '')+spec['title']+' | '+label
                readable_heading(child)
                child['caption']=child['caption'].replace('Both time columns remain unresolved alternatives.','').replace('Unresolved alternative time columns stay separately labeled.','')
                child['caption']=scoped_caption(child['caption'],[tables[s['dataset_id']] for s in _selectors(child)])
                if checks:
                    child['caption']+=' '+time_caption(child)
                    if diagnostic:child['caption']+=' Diagnostic only: '+'; '.join(sorted({r for d in checks for r in d['reasons']}))+'.'
                _axis(child,tables)
                child.pop('first_observation',None)
                child['axis_detail']=axis_detail_policy(child,tables)
                if child['kind']=='source_projection':
                    r=child['source_recipe'];r.update(id=vid,title=child['title'],caption=child['caption'],ncol=1,
                        x_label=child['x_label'],y_label=child['y_label'],standalone=True,legend=True,axis_detail=copy.deepcopy(child['axis_detail']))
                    r.pop('first_observation',None)
                from .eda_study_annotations import annotate
                child=annotate(child,tables)
                out[vid]=child
    return finalize(out)

def finalize(candidates):
    for index,s in enumerate(candidates.values(),1):
        s['figure_index']=f'EDA-{index:03}'
        if s['kind']=='source_projection':s['source_recipe']['figure_index']=s['figure_index']
    return candidates

def validate(specs,tables):
    indices=[]
    for s in specs:
        if not s.get('standalone') or len(s['panels'])!=1:raise ValueError('EDA display: standalone candidate required')
        if not s.get('x_label') or not s.get('y_label') or not s.get('figure_index'):raise ValueError('EDA display: axes and figure index required')
        indices.append(s['figure_index'])
        pol=s.get('display_policy',{})
        if pol.get('role') not in {'MAIN','TIME_CHECK'}:raise ValueError('EDA display: missing time/display policy')
        routes={_selector_route(sel,tables) for sel in _selectors(s)}
        if len(routes)>1 and any(not r.startswith('UNSPECIFIED:') for r in routes):
            raise ValueError('EDA display: different administration routes require separate figures')
        fresh={sel['dataset_id']:time_decision(tables[sel['dataset_id']]) for sel in _selectors(s)}
        if pol['role']=='TIME_CHECK' and not any(d and d['trigger'] and d['diagnostic_available'] for d in fresh.values()):
            raise ValueError('EDA display: time-check view has no live source trigger')
        for sel in _selectors(s):
            d=fresh[sel['dataset_id']]
            if d and sel.get('x') in {d['primary'],d['alternate']}:
                expected=d['alternate'] if pol['role']=='TIME_CHECK' and d['trigger'] and d['diagnostic_available'] else d['primary']
                if sel['x']!=expected:raise ValueError('EDA display: wrong time selector')
    if len(indices)!=len(set(indices)):raise ValueError('EDA display: duplicate figure index')

def audit(candidates,tables):
    return {'policy':read_json(CONFIG),'time_axes':[time_decision(t) for t in tables.values() if time_decision(t)],
        'views':[{'id':s['id'],'index':s['figure_index'],'role':s['display_policy']['role']} for s in candidates.values()],
        'source_values_changed':False,'model_calls':0}


def working_tables(tables):
    """Remove redundant digitized time from copies, preserving source and permissions.

    Only evidenced paper times without a recorded conflict/request qualify.
    Raw EC tables remain the verification source; this view is not model approval.
    """
    result=copy.deepcopy(tables)
    for did,t in result.items():
        d=time_decision(t)
        if not d or d['basis']!='PAPER_SAMPLING_TIMES' or d['trigger']:
            continue
        # Do not replace any missing or censored time with the paper schedule.
        if not t['records'] or not all(quantified(r,d['primary']) for r in t['records']):
            continue
        col=d['pixel_time_retained']
        t['columns']=[c for c in t['columns'] if c['id']!=col]
        for r in t['records']:
            r.pop(col,None)
            for field in ('source_raw_values','source_cells','value_status'):
                r.get(field,{}).pop(col,None)
        t['working_view']={'omitted_columns':[col], 'time_column':d['primary'],
            'reason':'Redundant digitized time omitted; evidenced paper sampling time retained.',
            'source_notes_scope':'Notes describe the original source. Original records remain archived; scientific restrictions are unchanged.'}
    return result
