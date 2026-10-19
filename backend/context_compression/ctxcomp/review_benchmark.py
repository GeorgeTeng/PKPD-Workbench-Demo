"""Opt-in paired semantic regression. Synthetic proposals; never research approval.

One clean control and six single-defect mutations. Use --live to call the real
provider; otherwise only materialize the inputs. No authored model verdicts.
"""
import argparse
import copy
import time
from pathlib import Path
from .engine import RESOURCE, DEFAULT_POLICY, DEFAULT_BUDGET
from .io import write_json, read_json, digest, leaves
from .schemas import SCHEMAS, validate_schema
from .retention import source_units, requirements_check, context_coverage_check
from .validation import context_check, review_check
from .providers import codex_generate
from .split_review import execute
from .rules import load_rules, attach_rules

RULES = [
 'Freeze MIC inputs before prediction.',
 'Literature development parameters may be used; held-out benchmark parameters must not be used for development.',
 'Use free plasma concentration for exposure calculations.',
 'Express plasma concentrations in mg/L.',
 'Only if a verified MIC distribution is available, calculate CFR.',
 'Do not use human validation observations to tune the model.',
]
MUTATIONS = {
 'MIC_FREEZE_OMITTED':(0,None),
 'PARAMETER_PERMISSION_CONFLICT':(1,'Literature development parameters and held-out benchmark parameters may be used for development.'),
 'FREE_TOTAL_CHANGED':(2,'Use total plasma concentration for exposure calculations.'),
 'UNITS_CHANGED':(3,'Express plasma concentrations in ug/L.'),
 'CONDITION_LOST':(4,'Calculate CFR.'),
 'NEGATION_LOST':(5,'Use human validation observations to tune the model.'),
}
REVIEW_MODES = ['legacy', 'parallel_v1', 'parallel_v2', 'parallel_v3']


def fixture(case):
    facts={'objective':'Review polymyxin B translation.', 'drug':'polymyxin B',
        'regimen':'IV bolus', 'population':'rats', 'system':'plasma',
        'measurements':'concentration', 'methods':'compartmental PK'}
    intro='\n'.join(f'{key}: {value}' for key,value in facts.items())
    source={'id':'S1','role':'PROPOSAL','name':'synthetic_proposal.txt','text':intro+'\n\n'+'\n\n'.join(RULES)}
    units=source_units([source])
    context={'version':'3.0','objective':facts['objective'],
        'study':{k:v for k,v in facts.items() if k!='objective'},
        'data':{'available':[],'required':[]},'rules':list(RULES),'checks':[],'uncertainties':[]}
    affected=None
    if case!='CLEAN':
        index,replacement=MUTATIONS[case]; affected=f'Q{index+1}'
        if replacement is None: context['rules'].pop(index)
        else: context['rules'][index]=replacement
    evidence=[]
    for path,value in leaves(context):
        if path=='/version': continue
        original=value
        if path.startswith('/rules/'):
            index=int(path.rsplit('/',1)[1])
            source_index=index+1 if case=='MIC_FREEZE_OMITTED' else index
            original=RULES[source_index]
        evidence.append({'path':path,'status':'EXPLICIT','source_id':'S1','quote':original,
            'reason':'Candidate extraction evidence; the reviewer must independently check entailment.'})
    items=[]
    for index,rule in enumerate(RULES):
        unit=next(u for u in units if rule in u['text'])
        items.append({'id':f'Q{index+1}','kind':'RULE','statement':rule,'critical':True,
            'rationale':'Preserve the stated constraint.','downstream_effect':'Controls calculation or data use.',
            'selection':{'explicit':True,'applicable':True,'technical':True,'material':True},
            'components':[{'id':'C1','role':'ACTION','text':rule,
                'evidence':[{'source_id':'S1','unit_id':unit['id'],'quote':rule}]}]})
    for index,(key,value) in enumerate(facts.items()):
        quote=f'{key}: {value}'
        items.append({'id':f'F{index+1}','kind':'FACT','statement':value,'critical':True,
            'rationale':'Defines the study scope.','downstream_effect':'Controls interpretation.',
            'selection':{'explicit':True,'applicable':True,'technical':True,'material':True},
            'components':[{'id':'C1','role':'FACT','text':value,
                'evidence':[{'source_id':'S1','unit_id':units[0]['id'],'quote':quote}]}]})
    requirements={'version':'1.0','items':items}
    payload={'stage':'context_review','instructions':(RESOURCE/'instructions.md').read_text(encoding='utf-8'),
        'sources':[source],'source_units':units,'inventory':[],
        'compression_scope':{'mode':'PROPOSAL_ONLY','source_ids':['S1']},
        'budget':DEFAULT_BUDGET,'policy':DEFAULT_POLICY,'schema':SCHEMAS['context_review'],
        'requirements':requirements,'requirements_evidence_audit':requirements_check(requirements,units),
        'context':context,'evidence':evidence,
        'evidence_audit':context_check(context,evidence,[source],DEFAULT_BUDGET)[0]}
    attach_rules(payload,load_rules())
    return {'request_sha256':digest(payload),'payload':payload},affected


def score(response,affected):
    review=response['review']; decision=review['decision']
    finding=next((x for x in review['coverage'] if x['requirement_id']==affected),None)
    detected=bool(finding and (finding['verdict']!='PRESERVED' or any(c['verdict']!='PRESERVED' for c in finding['components']))) if affected else None
    return {'decision':decision,'expected':'BLOCK' if affected else 'PASS',
        'defect_detected_in_requirement_coverage':detected,
        'false_release':bool(affected and decision=='PASS'),
        'false_rejection':bool(not affected and decision!='PASS')}


def with_mode(request, mode):
    """The same review request run in another parallel mode."""
    payload = {**request['payload'], 'context_review_mode': mode}
    return {'request_sha256': digest(payload), 'payload': payload}


def benchmark(out,live=False,model=None,cases=None,modes=('legacy','parallel_v1')):
    out=Path(out)
    if out.exists() and any(out.iterdir()): raise ValueError('Use a new benchmark directory; preserve previous evidence')
    out.mkdir(parents=True,exist_ok=True)
    selected=cases or ['CLEAN',*MUTATIONS]
    report={'synthetic_only':True,'live':live,'requested_model':model or 'CLI_DEFAULT',
        'cases':[],'limitations':['One repetition per case; synthetic English controls do not establish production accuracy or speed.',
         'Detection is scored using the mutated requirement verdict; validate the saved reasons manually.',
         'Engineering errors are not counted as successful semantic detection. No research handoff is published.']}
    for index,case in enumerate(selected):
        request,affected=fixture(case); case_dir=out/case
        write_json(case_dir/'input.json',request)
        write_json(case_dir/'expected.json',{'affected_requirement':affected,'defect':case,'expected_decision':'PASS' if case=='CLEAN' else 'BLOCK'})
        if not live: continue
        for mode in (list(modes) if index%2==0 else list(reversed(modes))):
            before=time.monotonic(); row={'case':case,'mode':mode,'status':'RUNNING'}
            report['cases'].append(row); write_json(out/'report.json',report)
            try:
                if mode=='legacy':
                    response=codex_generate(request,model=model,diagnostics_dir=case_dir/'legacy/model_call')
                    write_json(case_dir/'legacy/response.json',response)
                    validate_schema(response,SCHEMAS['context_review'])
                    if response['request_sha256']!=request['request_sha256']: raise ValueError('Stale legacy benchmark response')
                    p=request['payload']; review_check(response['review'],p['context'],p['sources'],'context_review')
                    context_coverage_check(response['review'],p['requirements'],p['context'],p['evidence'],p['source_units'])
                else:
                    response=execute(case_dir/mode,request if mode=='parallel_v1' else with_mode(request,mode),'benchmark',
                        lambda req,branch,cancel:codex_generate(req,model=model,cancel_event=cancel,
                            diagnostics_dir=case_dir/mode/'model_calls'/branch))
                    write_json(case_dir/mode/'response.json',response)
                row.update(status='VALID_REVIEW',**score(response,affected))
            except Exception as exc:
                row.update(status='ENGINEERING_ERROR',error=str(exc))
                report['stopped_on_error']=True
            row['elapsed_seconds']=round(time.monotonic()-before,3)
            write_json(out/'report.json',report)
            print(f'{case} {mode}: {row["status"]} {row.get("decision", "")} {row["elapsed_seconds"]}s',flush=True)
            if row['status']=='ENGINEERING_ERROR': return report
    report['complete']=True
    report['summary']={mode:{'valid_reviews':sum(r['status']=='VALID_REVIEW' for r in report['cases'] if r['mode']==mode),
        'false_releases':sum(r.get('false_release',False) for r in report['cases'] if r['mode']==mode),
        'false_rejections':sum(r.get('false_rejection',False) for r in report['cases'] if r['mode']==mode),
        'detected_defects':sum(r.get('defect_detected_in_requirement_coverage') is True for r in report['cases'] if r['mode']==mode),
        'total_seconds':round(sum(r['elapsed_seconds'] for r in report['cases'] if r['mode']==mode),3)} for mode in modes}
    write_json(out/'report.json',report)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--out',required=True);p.add_argument('--live',action='store_true');p.add_argument('--model');p.add_argument('--cases',nargs='+',choices=['CLEAN',*MUTATIONS])
    p.add_argument('--modes',nargs='+',choices=REVIEW_MODES,default=['legacy','parallel_v1'])
    a=p.parse_args(); benchmark(a.out,a.live,a.model,a.cases,a.modes)
