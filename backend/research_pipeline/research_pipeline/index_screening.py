"""Read-only eligibility screen for matched PK/PD indices, never substitute raw C."""
import math

INDICES = ('fAUC_MIC_h', 'fCmax_MIC', 'fT_MIC_percent')
PRIMARY_SPECS = [{'name':name,'unit':unit,'tier':'primary'} for name,unit in
                 zip(INDICES,('h','dimensionless','%'))]
EXPANDED_SPECS = PRIMARY_SPECS + [
    {'name':'fCtrough_MIC','unit':'dimensionless','tier':'exploratory',
     'trough_definition':'pre_dose_left_limit'},
    {'name':'fT_4MIC_percent','unit':'%','tier':'exploratory','threshold_mic_multiplier':4}]


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def proportional_pairs(records, columns=INDICES):
    """Positive rescaling is absorbed by EC50: such Emax index fits are equivalent."""
    pairs=[]
    for i,left in enumerate(columns):
        for right in columns[i+1:]:
            x=[r[left] for r in records];y=[r[right] for r in records]
            denominator=sum(v*v for v in x)
            if not denominator: continue
            scale=sum(a*b for a,b in zip(x,y))/denominator
            if scale>0 and all(math.isclose(b,scale*a,rel_tol=1e-8,abs_tol=1e-10) for a,b in zip(x,y)):
                pairs.append({'left':left,'right':right,'right_equals_scale_times_left':scale})
    return pairs


def screen_index_dataset(payload, candidate_specs=None):
    specs=PRIMARY_SPECS if candidate_specs is None else candidate_specs
    indices=tuple(s['name'] for s in specs)
    if len(indices)<2 or len(set(indices))!=len(indices): raise ValueError('Declare distinct candidate indices')
    rows=payload.get('records',[]);meta=payload.get('metadata',{})
    columns=sorted({k for r in rows for k in r})
    issues=[]
    def issue(code,detail): issues.append({'code':code,'detail':detail})
    complete=[r for r in rows if all(finite(r.get(k)) for k in (*indices,'response'))]
    if len(complete)!=len(rows) or not rows:
        issue('IDX01_MATCHED_INDICES_MISSING',f'Every included endpoint requires {len(indices)} explicit numeric indices and a matched response; no values are synthesized.')
    if meta.get('exposure_design')=='static' or (len(complete)!=len(rows) and 'nominal_concentration_mg_L' in columns):
        issue('IDX02_STATIC_SUPPORT_ONLY','Nominal static exposure/time-kill rows do not supply an independent three-index comparison.')
    if 'concentration_mg_L' in columns and 'response' not in columns:
        issue('IDX03_PK_WITHOUT_PD','Concentration-time observations have no matched efficacy response in this table.')
    if meta.get('record_level') in ('parameter_summary','context_only','population_frequency','relative_summary','group_summary','summary'):
        issue('IDX04_DIFFERENT_DATA_ROLE','The current independent-endpoint fitter does not reinterpret summaries or context as individual matched records.')
    details={}
    if meta.get('record_level')=='terminal_individual':
        treated=[r for r in rows if r.get('group')=='PMB']
        schedules=sorted({(str(r.get('route')),str(r.get('daily_dose_mg_kg')),str(r.get('interval_h'))) for r in treated})
        details['treated_endpoint_rows']=len(treated);details['pmb_regimens_observed']=schedules
        if len(schedules)<2: issue('IDX05_SINGLE_PMB_REGIMEN','Only one PMB regimen within this strain table; endpoints cannot establish a multi-regimen index-response curve.')
    if len(complete)==len(rows) and rows:
        required=('unit_id','regimen_id','strain','mic_mg_L','response_time_h')
        if any(any(r.get(k) in (None,'','NOT_FOUND') for k in required) for r in rows):
            issue('IDX06_MATCH_KEYS','Need explicit unit, regimen, strain, MIC and endpoint-time fields.')
        units=[r.get('unit_id') for r in rows]
        if len(set(units))!=len(units): issue('IDX07_REPEATED_ENDPOINT','Repeated unit IDs require a repeated-outcome model.')
        if any(not finite(r.get('mic_mg_L')) or r['mic_mg_L']<=0 for r in rows):
            issue('IDX08_MIC','Strain-matched numeric positive MIC is required.')
        percent_names=[s['name'] for s in specs if s['unit']=='%']
        if any(r[k]<0 for r in rows for k in indices) or any(r[k]>100 for r in rows for k in percent_names):
            issue('IDX09_RANGE','Index values must be nonnegative and percent time cannot exceed 100.')
        if len({r.get('response_time_h') for r in rows})!=1:
            issue('IDX10_ENDPOINT_WINDOW','Use a common efficacy endpoint time; no pooling different follow-up times.')
        if len({r.get('strain') for r in rows})!=1:
            issue('IDX11_STRAIN_EFFECT','Strain pooling needs an explicit baseline/strain-effect model; split first.')
        definitions=meta.get('index_definitions',{});windows=[]
        for spec in specs:
            name=spec['name']
            d=definitions.get(name,{})
            expected=spec['unit']
            w=d.get('window_h')
            if d.get('concentration_basis')!='free' or d.get('unit')!=expected or not isinstance(w,list) or len(w)!=2 or not all(finite(t) for t in w) or w[0]>=w[1]:
                issue('IDX12_DEFINITION',f'{name}: declare free basis, expected unit {expected}, and an increasing time window.')
            else: windows.append(tuple(w))
            if 'threshold_mic_multiplier' in spec and d.get('threshold_mic_multiplier')!=spec['threshold_mic_multiplier']:
                issue('IDX18_THRESHOLD',f'{name}: threshold multiplier must match the declared candidate specification.')
            if 'trough_definition' in spec and (d.get('trough_definition')!=spec['trough_definition'] or not finite(d.get('trough_time_h'))):
                issue('IDX19_TROUGH',f'{name}: declare the pre-dose left limit and exact time; an arbitrary sampled minimum is not a trough.')
        if len(windows)==len(indices) and len(set(windows))!=1: issue('IDX13_UNMATCHED_WINDOWS','All indices must refer to the same exposure window.')
        if not meta.get('exposure_provenance'):
            issue('IDX14_EXPOSURE_PROVENANCE','Document measured free exposure or matched PK model and binding conversion.')
        for name in indices:
            if len({r[name] for r in rows})<4:
                issue('IDX15_EXPOSURE_SUPPORT',f'{name}: fewer than four distinct levels; fails this Emax implementation gate, not a universal sample-size rule.')
        if len(rows)<6: issue('IDX16_ENDPOINT_SUPPORT','This standard Emax implementation needs >=6 endpoints; reliability is a separate question.')
        pairs=proportional_pairs(rows,indices)
        if pairs: issue('IDX17_PROPORTIONAL_INDICES',pairs)
        details['proportional_pairs']=pairs
    return {'status':'BLOCKED' if issues else 'CANDIDATE_REQUIRES_HUMAN_REVIEW',
      'n_records':len(rows),'n_complete_index_response_rows':len(complete),'columns':columns,
      'source_table':meta.get('source_table'),'record_level':meta.get('record_level'),
      'strain':meta.get('strain'),'issues':issues,'design_facts':details,
      'fit_executed':False,'scientific_reliability':'NOT_ESTABLISHED'}
