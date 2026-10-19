"""Study-design checks derived from the user's species_selection_evidence.md.

No default biological variability, precision target, or fixed animal count.
"""
import math
import statistics
from .common import PipelineError
from .references import canonical_drug
from .tables import load_table

RULESET_VERSION = '2026-09-16.1'
RULES = [
    {'id':'identity', 'source_section':'先填写研究问题，再回答“几种、多少只”', 'rule':'Split drug/analyte/species/route/matrix/basis/formulation/parameter definitions; do not pool incompatible records.'},
    {'id':'independence', 'source_section':'第二问：每个物种要多少只独立动物？', 'rule':'Count unique independent animals, not concentration rows or crossover periods.'},
    {'id':'species', 'source_section':'第一问：要几种动物物种？', 'rule':'Unknown allometric exponent: <2 species is unidentified, 2 has no residual df, 3 is only an exploratory start with 1 df.'},
    {'id':'variance', 'source_section':'从指定文档取得规划变异', 'rule':'Use documented between-animal parameter variation; never substitute residual error, TVCL RSE, assay CV, or in-vitro replicate SD.'},
    {'id':'precision', 'source_section':'从指定文档取得规划变异', 'rule':'Without supported variance, CI precision M, confidence, and assurance A, return NOT_CALCULABLE. No assumed CV.'},
    {'id':'sampling', 'source_section':'真正立项时的模拟–重估步骤', 'rule':'Sparse/terminal sampling and joint parameter/species success require design-specific simulation and refitting.'},
    {'id':'translation', 'source_section':'既有 CMS 项目的默认规则（不是法规或通用物种最低数）', 'rule':'CL != CL/F or CL_col/f_m; plasma != ELF != sputum; animal fit/precision cannot prove human predictive validity.'},
    {'id':'human_confirmation', 'source_section':'User instruction 2026-09-16', 'rule':'Human must confirm rules, prepared datasets and intended scope before release to modeling. Hard data errors cannot be waived.'},
]


def known(value):
    return value is not None and str(value).strip().upper() not in {'','NOT_FOUND','NOT_VERIFIED','UNKNOWN'}


def number(value, positive=False):
    if isinstance(value, bool):
        raise ValueError('Boolean is not a numeric measurement.')
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError('Expected finite'+(' positive' if positive else '')+' number.')
    return result


def critical_t(confidence,df):
    from scipy.special import stdtrit
    return float(stdtrit(df,(1+confidence)/2))


def width_assurance(n, sigma_log, multiplier, confidence):
    from scipy.special import gammainc
    critical = critical_t(confidence,n-1)
    threshold = (n-1)*n*math.log(multiplier)**2/(critical**2*sigma_log**2)
    return float(gammainc((n-1)/2,threshold/2))


def precision_assessment(item, attachments, groups):
    result = {'id':item.get('id','NOT_FOUND'), 'status':'NOT_CALCULABLE', 'required_n':None,
              'scope':'Conditional marginal CI-width planning, not observed precision or human prediction reliability.',
              'missing':[], 'assumptions':['Independent lognormal individual parameters; supplied sigma treated as fixed.',
              'Pilot/model variance uncertainty is not integrated; evaluate sensitivity or simulate-refit.',
              'No joint assurance across species or parameters is claimed.']}
    try:
        meta = item.get('scope',{})
        keys = ('drug','analyte','species','route','matrix','concentration_basis','parameter_definition')
        if any(not known(meta.get(key)) for key in keys):
            raise ValueError('Explicit same-drug/species/analyte/route/matrix/basis/parameter scope required.')
        matching = [g for g in groups if all((canonical_drug(g['metadata'].get(k,'')) == canonical_drug(meta[k])) if k=='drug'
                    else str(g['metadata'].get(k,'')) == str(meta[k]) for k in keys)]
        if not matching:
            raise ValueError('Variance scope does not match a prepared dataset; no cross-drug substitution.')
        if item.get('sampling_design') != 'serial_individual_parameters':
            raise ValueError('Sparse/terminal/PopPK design needs simulation-refitting; closed-form individual-mean planning is inapplicable.')
        src = item.get('source',{})
        if src.get('attachment') not in attachments or not known(src.get('locator')):
            raise ValueError('Variance requires an attached source and an explicit locator.')
        result['source'] = {'attachment':src['attachment'],'sha256':attachments[src['attachment']]['sha256'],'locator':src['locator']}
        method = item.get('variance_type')
        allowed = {'individual_parameters','arithmetic_sd','arithmetic_se','log_t_ci','arithmetic_t_ci','pop_iiv_variance','pop_iiv_cv'}
        if method not in allowed:
            raise ValueError('Residual/assay/timepoint variation or TVCL precision is not between-animal parameter variability.')
        n0 = item.get('n0')
        if method == 'individual_parameters':
            records = load_table(attachments[src['attachment']]['path'],src.get('table'))
            for key,value in src.get('filter',{}).items():
                records = [r for r in records if str(r.get(key))==str(value)]
            idcol = src.get('id_column','subject_id'); valuecol = src.get('value_column','CL')
            ids = [r.get(idcol) for r in records]
            if any(not known(i) for i in ids) or len(set(ids))!=len(ids) or len(ids)<2:
                raise ValueError('Raw parameter variance requires at least two unique independent animal IDs.')
            values = [number(r[valuecol],True) for r in records]
            sigma = statistics.stdev([math.log(v) for v in values]); n0=len(values)
        elif method in {'pop_iiv_variance','pop_iiv_cv'}:
            if item.get('iiv_definition') != 'parameter_i=typical*exp(eta); eta~N(0,omega2)':
                raise ValueError('Verify the exponential IIV definition before conversion.')
            sigma = math.sqrt(number(item['omega2'],True)) if method=='pop_iiv_variance' else math.sqrt(math.log1p((number(item['iiv_cv_percent'],True)/100)**2))
        else:
            if not isinstance(n0,int) or isinstance(n0,bool) or n0<2:
                raise ValueError('n0 must be the source independent-animal count, integer >=2.')
            if method in {'log_t_ci','arithmetic_t_ci'}:
                ci = number(item['source_confidence'])
                if not 0<ci<1 or item.get('ci_method')!='two_sided_t':
                    raise ValueError('Source confidence and two-sided t CI definition required.')
                lower=number(item['lower'],True); upper=number(item['upper'],True)
                if upper<=lower: raise ValueError('CI limits must be increasing.')
                critical=critical_t(ci,n0-1)
                sd=(math.log(upper)-math.log(lower))*math.sqrt(n0)/(2*critical) if method=='log_t_ci' else (upper-lower)*math.sqrt(n0)/(2*critical)
            else:
                sd=number(item['sd'] if method=='arithmetic_sd' else item['se'],True)
                if method=='arithmetic_se': sd*=math.sqrt(n0)
            sigma=sd if method=='log_t_ci' else math.sqrt(math.log1p((sd/number(item['mean'],True))**2))
        sigma=number(sigma,True)
        target=item.get('target',{})
        missing=[key for key in ('multiplier','confidence','assurance','source_locator') if not known(target.get(key))]
        if missing: raise ValueError('Missing pre-specified precision target: '+', '.join(missing))
        mult=number(target['multiplier']); conf=number(target['confidence']); assurance=number(target['assurance'])
        if mult<=1 or not 0<conf<1 or not 0<assurance<1: raise ValueError('Require M>1, 0<confidence<1, 0<assurance<1.')
        limit=item.get('max_n',10000)
        if not isinstance(limit,int) or not 2<=limit<=100000: raise ValueError('max_n must be 2..100000 (search cap, not animal-number recommendation).')
        required=next((n for n in range(2,limit+1) if width_assurance(n,sigma,mult,conf)>=assurance),None)
        ids={i for g in matching for i in g['independent_ids']}
        current=len(ids)
        result.update(status='CONDITIONAL_PLAN' if required else 'SEARCH_LIMIT_REACHED',required_n=required,
                      sigma_log=sigma,CV=math.sqrt(math.expm1(sigma*sigma)),n0=n0,current_independent_units=current,
                      current_planned_width_assurance=width_assurance(current,sigma,mult,conf) if current>=2 else None,
                      current_meets_conditional_plan=(current>=required) if required else None,
                      target=target,variance_type=method)
    except (ValueError,KeyError,TypeError,OverflowError) as exc:
        result['missing'].append(str(exc))
    return result


def assess_study(plan, groups, precision, issue):
    result={'purpose':plan.get('purpose','NOT_FOUND'), 'species_count':0, 'status':'NOT_ASSESSED',
            'human_validation':'NOT_ESTABLISHED', 'note':'Availability audit only; no allometry fit or human prediction is executed here.'}
    if not known(plan.get('purpose')):
        issue('STUDY_PURPOSE_MISSING','REVIEW',None,'先声明研究用途，才能判断数据是否足够。')
        return result
    if plan['purpose']=='within_species_fit':
        result['status']='EXPLORATORY_FIT_ONLY'
    elif plan['purpose']=='human_translation':
        target=plan.get('target',{})
        fields=('drug','analyte','route','matrix','concentration_basis','parameter_definition','human_population','decision_quantity')
        missing=[k for k in fields if not known(target.get(k))]
        if missing: issue('TARGET_INCOMPLETE','REVIEW',None,'人体目标字段缺失：'+', '.join(missing))
        if '/' in str(target.get('parameter_definition','')) or 'per_kg' in str(target.get('parameter_definition','')):
            issue('PARAMETER_DEFINITION_REVIEW','REVIEW',None,'表观或体重归一化参数不能当作绝对 CL 直接套用缩放指数。')
        compatible=[g for g in groups if g['kind']=='pk' and g['readiness']!='BLOCKED' and all(
            (canonical_drug(g['metadata'].get(k,''))==canonical_drug(target.get(k,''))) if k=='drug' else
            str(g['metadata'].get(k,''))==str(target.get(k,'')) for k in fields[:6])]
        species={g['metadata']['species'].casefold() for g in compatible if known(g['metadata'].get('species'))}
        result['species_count']=len(species); result['species_with_compatible_observations']=sorted(species)
        scaling=plan.get('scaling',{}); mode=scaling.get('mode','NOT_FOUND')
        result['scaling_mode']=mode
        if mode=='unknown_exponent':
            result['species_residual_df']=max(0,len(species)-2)
            result['status']='INSUFFICIENT' if len(species)<3 else 'EXPLORATORY_ONLY'
            if len(species)<2: issue('SLOPE_UNIDENTIFIABLE','REVIEW',None,'少于两个可比物种，不能从本药数据估计未知体重指数。')
            elif len(species)==2: issue('NO_SPECIES_RESIDUAL_DF','REVIEW',None,'两个物种无物种间残差自由度；未达到文档三物种探索起点。')
            elif len(species)==3: issue('ONE_SPECIES_RESIDUAL_DF','REVIEW',None,'三个物种仅一个物种间残差自由度，不是可靠性验证。')
            weights={}
            for g in compatible:
                w=g['metadata'].get('species_weight_kg')
                if known(w):
                    try:
                        species_key=g['metadata']['species'].casefold()
                        value=number(w,True)
                        if species_key in weights and weights[species_key]!=value:
                            issue('INCONSISTENT_SPECIES_WEIGHT','REVIEW',None,'同一物种的代表体重声明不一致，需人工确认取值依据。')
                        weights[species_key]=value
                    except (ValueError,TypeError): pass
            if set(weights)!=species or len(set(weights.values()))<2:
                issue('WEIGHT_INFORMATION_INSUFFICIENT','REVIEW',None,'缺可比物种代表体重或体重无跨度，不能确认体重回归可识别。')
                result['status']='INSUFFICIENT'
            else:
                result['weight_ratio']=max(weights.values())/min(weights.values())
                result['weight_span_decision']='HUMAN_REVIEW_REQUIRED; no universal numerical cutoff imposed'
        elif mode=='fixed_exponent':
            try:
                number(scaling['exponent'])
                if not known(scaling.get('source_locator')) or not species: raise ValueError()
                result['status']='CONDITIONAL_ONLY'
            except (KeyError,TypeError,ValueError):
                result['status']='INSUFFICIENT'; issue('FIXED_EXPONENT_UNSUPPORTED','REVIEW',None,'外定指数、依据或可比物种数据缺失。')
        else:
            issue('SCALING_METHOD_MISSING','REVIEW',None,'未声明固定或未知指数等外推方法。')
        if target.get('matrix') in {'ELF','sputum','lung'}:
            issue('SITE_IDENTIFIABILITY_REVIEW','REVIEW',None,'部位暴露需配对部位—血浆数据、递送及分析物定义；痰液不等于 ELF。')
        if canonical_drug(target.get('drug'))=='cms':
            issue('CMS_FORMATION_REVIEW','REVIEW',None,'区分 CMS、形成的 colistin、真 CL 与 CL/f_m；简单单分析物 PK 不能替代联合形成模型。')
        issue('HUMAN_PREDICTION_NOT_VALIDATED','REVIEW',None,'没有完成预先锁定的独立人体检验；动物拟合或 CI 精度不等于人体预测有效。')
        if missing: result['status']='INSUFFICIENT'
    if not precision:
        issue('PRECISION_NOT_CALCULABLE','REVIEW',None,'没有文档支持的参数变异和预设精度方案；不能给正式动物数。')
    for p in precision:
        if p['status']=='NOT_CALCULABLE': issue('PRECISION_NOT_CALCULABLE','REVIEW',None,p['id']+': '+'; '.join(p['missing']))
        elif p.get('current_meets_conditional_plan') is False: issue('PRECISION_TARGET_NOT_MET','REVIEW',None,p['id']+': 当前独立动物数未达到条件性规划值。')
    return result
