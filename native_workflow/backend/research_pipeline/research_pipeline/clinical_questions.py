"""Source-bound question defaults. Fixed field names do not imply fixed answers.

Reads reviewed context and task assessment only. Relevance matching retrieves
verbatim statements; it cannot resolve their semantics or certify completeness.
Unsupported, missing and conflicting definitions remain for human confirmation.
"""
import re
import hashlib
import json
from .workflow_definition import CLINICAL_FIELDS

GENERATOR_VERSION = '2.0'
MISSING = {'', 'NOT_FOUND', 'UNKNOWN', 'NOT_ESTABLISHED', 'MIXED_OR_NOT_FOUND', 'NONE'}
DIRECT = {
    'decision_question': [('objective',)],
    'pd_endpoint': [('study','pd_endpoint'),('study','endpoint')],
    'endpoint_window': [('study','endpoint_window')],
    'experimental_unit': [('study','experimental_unit')],
    'pathogen_infection_site': [('study','pathogen'),('study','infection_site')],
    'target_population': [('study','population')],
    'exposure_definition': [('study','exposure_definition'),('study','measurements')],
    'mic_and_binding_source': [('study','mic_and_binding_source'),('study','binding_policy')],
    'regimen_constraints': [('study','regimen')],
    'safety_endpoints': [('study','safety_endpoints')],
    'translation_assumptions': [('study','translation_assumptions')],
    'decision_criteria': [('study','decision_criteria')],
}
RELEVANCE = {
    'pd_endpoint': r'PD endpoint|bacterial.burden|response endpoint|tumou?r|log.?kill|log.?reduction|stasis|CFU|PD.?终点',
    'endpoint_window': r'time.?window|exposure window|endpoint window|\d[\d.]*.?h(?:our)?|\d[\d.]*.?day|时间窗|小时|随访',
    'experimental_unit': r'experimental.unit|independent.*replic|animal.*identit|subject.*identit|group.mean|terminal.sampl|实验单位|独立重复',
    'pathogen_infection_site': r'pathogen|strain|infection|pneumonia|thigh|plasma|ELF|lung|bacter|感染|病原',
    'target_population': r'target.population|patients|healthy.volunteers|organ.function|renal.impair|人群|患者|健康受试',
    'exposure_definition': r'AUC|Cmax|T.?[>＞]|exposure|free.drug|total.concentration|unbound|暴露|游离|总浓度',
    'mic_and_binding_source': r'\bMIC\b|binding|unbound.fraction|结合率|蛋白结合',
    'regimen_constraints': r'\bdos(?:e|ing)\b|regimen|infusion|q\d+h|route|给药|输注|剂量',
    'safety_endpoints': r'safety|toxicity|toxicological|nephrotox|adverse.event|renal.injury|安全|毒性',
    'translation_assumptions': r'translat|allometr|scaling|animal.to.human|in.vitro.to|bridge|extrapolat|外推|转化|桥接',
    'decision_criteria': r'acceptance|criterion|criteria|threshold|R2|R\^2|AIC|BIC|likelihood|freeze|sensitivity|validate|validation|判据|阈值|验证',
}
TASK_FIELDS = {
    'pd_endpoint':['endpoint'], 'endpoint_window':['endpoint_window'],
    'experimental_unit':['experimental_unit'], 'exposure_definition':['units','exposure_basis'],
    'safety_endpoints':['safety_endpoints'], 'decision_criteria':['decision_criteria'],
}


def known(value):
    return isinstance(value,str) and value.strip().upper() not in MISSING and not re.match(r'^(UNKNOWN|NOT_FOUND)\b',value.strip(),re.I)


def get_path(value, path):
    for key in path:
        if not isinstance(value,dict): return None
        value=value.get(key)
    return value


def statements(value):
    """Keep exact substrings; splitting changes neither negation nor thresholds."""
    if not isinstance(value,str): return []
    return [s.strip() for s in re.split(r'(?<=[.!?。])\s+(?=[A-Z\u4e00-\u9fff])|[\r\n]+',value) if s.strip()]


def context_statements(main, rule_target='dispatch'):
    paths=[(('objective',),main.get('objective'))]
    paths += [(('study',k),v) for k,v in main.get('study',{}).items()]
    if main.get('project_rules_ref'):
        from .project_rule_agent import project
        projected = project(main['project_rules_ref'], rule_target)
        for rule in projected['rules']:
            yield {'source':'project_rules.json', 'path':rule['context_path']+'/text',
                   'quote':rule['text'].removeprefix(rule['id']+': '),
                   'project_rules_ref':main['project_rules_ref'], 'rule_id':rule['id'],
                   'scope':rule.get('scope', {'stages':rule.get('used_in', [])}),
                   'usage':rule.get('usage', {})}
    elif main.get('rule_publication') == 'PROJECT_RULES_AGENT':
        raise ValueError('Published project_rules.json is required before clinical question routing')
    else:
        paths += [(('rules',str(i)),r) for i,r in enumerate(main.get('rules',[]))]
    for path,value in paths:
        if isinstance(value,list):
            for i,entry in enumerate(value):
                if known(entry): yield {'source':'effective_main.json','path':'/'+'/'.join((*path,str(i))),'quote':entry}
            continue
        for quote in statements(value):
            if known(quote): yield {'source':'effective_main.json','path':'/'+'/'.join(path),'quote':quote}


def derive_questions(main, assessment, classify, task_ids=None):
    tasks=assessment.get('tasks',[]); requirements=assessment.get('requirements',[])
    values={}; info={}; evidence={}
    def register(item):
        key='E'+hashlib.sha256(json.dumps(item,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:16]
        evidence[key]=item;return key
    source_statements=list(context_statements(main))
    for field,_,_ in CLINICAL_FIELDS:
        definitions=[]; related=[]; gaps=[]
        def add(target,item):
            identifier=register(item)
            if identifier not in target: target.append(identifier)
        paths=[('clinical_questions',field),*DIRECT[field]]
        for path in paths:
            value=get_path(main,path)
            if known(value): add(definitions,{'source':'effective_main.json','path':'/'+'/'.join(path),'quote':value})
        for i,task in enumerate(tasks):
            if task_ids is not None and task['id'] not in task_ids: continue
            if field=='pd_endpoint' and classify(task)!='index': continue
            for key in TASK_FIELDS.get(field,[]):
                if known(task.get(key)):
                    add(definitions,{'source':'assessment.json','path':f'/tasks/{i}/{key}',
                        'task_id':task['id'],'quote':task[key]})
        pattern=RELEVANCE.get(field)
        if pattern:
            for item in source_statements:
                if re.search(pattern,item['quote'],re.I): add(related,item)
            for i,req in enumerate(requirements):
                if task_ids is not None and req.get('task_id') not in task_ids: continue
                text=' '.join(str(req.get(k,'')) for k in ['description','condition','needed_material'])
                if re.search(pattern,text,re.I) and req.get('status') in {'MISSING','UNRESOLVED','DEFERRED'}:
                    gap={'requirement_id':req.get('id'),'status':req['status'],'task_id':req.get('task_id'),
                         'reason':req.get('reason'),'needed_material':req.get('needed_material'),'path':f'/requirements/{i}'}
                    gaps.append(gap)
        related=[key for key in related if not any(evidence[key]['source']==evidence[d]['source']
            and evidence[key]['path']==evidence[d]['path'] and evidence[key]['quote'] in evidence[d]['quote'] for d in definitions)]
        lines=[]
        for key in definitions:
            item=evidence[key];label=item.get('task_id',item['path'])
            lines.append(f"[{key}; {label}] {item['quote']}")
        if not definitions: lines.append('UNKNOWN: no explicit '+field.replace('_',' ')+' field was resolved in the reviewed inputs. Review the source statements below; this does not establish that the original proposal omitted it.')
        if related:
            lines.append('Related project statements (verbatim; scope and conditions require confirmation):')
            lines += [f"[{key}] {evidence[key]['quote']}" for key in related]
        if gaps:
            lines.append('Open reviewed requirements: '+', '.join(f"{g['requirement_id']} ({g['status']})" for g in gaps)+'. See the evidence details; deferred items are not immediate missing-data demands.')
        values[field]='\n'.join(lines)
        info[field]={'status':'SOURCE_DEFINITION_REQUIRES_CONFIRMATION' if definitions else 'UNKNOWN_REVIEW_SOURCE_STATEMENTS',
            'definition_evidence':definitions,'related_evidence':related,'open_requirements':gaps,
            'semantic_completeness_verified':False}
    return {'values':values,'field_evidence':info,'evidence_catalog':evidence,'generator_version':GENERATOR_VERSION,
        'method':'DETERMINISTIC_RETRIEVAL_FROM_REVIEWED_CONTEXT_AND_LLM_REVIEWED_TASKS',
        'limitation':'Related statements are exact retrievals, not a new semantic LLM interpretation. Human confirmation resolves applicability and conflicts.'}


# Recognizers identify declarations; their presence here never selects an index.
INDEX_TOKEN=re.compile(r'(?<![A-Za-z])(?:f?AUC(?:0?[-–]?\d+)?\s*/\s*MIC|f?Cmax\s*/\s*MIC|%?f?T\s*[>＞]\s*MIC)(?![A-Za-z])',re.I)


def index_scope(main):
    found={};excluded=set();mentions=[]
    for item in context_statements(main, 'index'):
        if item['path']!='/study/methods' and not item['path'].startswith('/rules/') and not item['path'].startswith('/study/candidate_indices'): continue
        for match in INDEX_TOKEN.finditer(item['quote']):
            name=re.sub(r'\s+','',match.group()).replace('＞','>')
            lower=name.lower();name=('f' if lower.lstrip('%').startswith('f') else '')+('Cmax/MIC' if 'cmax' in lower else 'T>MIC' if 't>' in lower else re.sub('auc','AUC',re.sub('mic','MIC',lower.lstrip('f')),flags=re.I))
            before=re.split(r'[;,；]',item['quote'][:match.start()])[-1]
            negative=bool(re.search(r'\b(?:not|never|exclude|excluding|prohibit|prohibited)\b|不比较|不使用|排除',before,re.I))
            mentions.append({'index':name,'polarity':'EXCLUDED_OR_AMBIGUOUS' if negative else 'MENTIONED','evidence':item})
            if negative: excluded.add(name)
            else: found[name]=True
    return {'candidates':[x for x in found if x not in excluded], 'mentions':mentions,
        'status':'REQUIRES_SCOPE_CONFIRMATION', 'excluded_or_ambiguous':sorted(excluded),
        'limitation':'Recognized declarations only. Absence is not permission to add default indices; unsupported or conflicting definitions need review.'}


def pathogen_scope(main):
    explicit=get_path(main,('study','pathogen'))
    if known(explicit): return {'names':[explicit.strip()], 'status':'EXPLICIT_FIELD'}
    text=' '.join(str(v) for v in main.get('study',{}).values())
    # Generic binomial recognition, restricted to common pathogen genera; new
    # unrecognized organisms require a structured pathogen field or confirmation.
    patterns=[r'(?:Klebsiella|K\.)\s*pneumoniae',r'(?:Pseudomonas|P\.)\s*aeruginosa',
              r'(?:Acinetobacter|A\.)\s*baumannii',r'(?:Staphylococcus|S\.)\s*aureus',
              r'(?:Escherichia|E\.)\s*coli',r'(?:Streptococcus|S\.)\s*(?:pneumoniae|pyogenes)',
              r'(?:Enterococcus|E\.)\s*(?:faecium|faecalis)']
    found=[p for p in patterns if re.search(p,text,re.I)]
    return {'patterns':found,'names':[re.search(p,text,re.I).group() for p in found],
        'status':'MENTIONS_REQUIRE_CONFIRMATION' if found else 'UNRESOLVED'}


def matches_pathogen(scope, text):
    if scope.get('patterns'): return any(re.search(p,text,re.I) for p in scope['patterns'])
    return any(name.casefold() in text.casefold() for name in scope.get('names',[]))
