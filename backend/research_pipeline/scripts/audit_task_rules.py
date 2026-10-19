"""Audit a proposal's rules without changing its approved source or approvals."""
import argparse
from pathlib import Path
from research_pipeline.common import read_json, write_json, utcnow
from research_pipeline.adequacy import file_ref
from research_pipeline.task_rules import project_rules, scoped_context


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--main',required=True);p.add_argument('--pk-context',required=True)
    p.add_argument('--out',required=True)
    args=p.parse_args();out=Path(args.out)
    source=read_json(args.main);pk=read_json(args.pk_context)
    view,animal=scoped_context(pk,'animal_pk')
    write_json(out/'animal_pk_context.json',view)
    stages={stage:project_rules(source,stage) for stage in ['animal_pk','human_pk','index','clinical','prepare','eda']}
    report={'generated_at':utcnow(),'source_main':file_ref(args.main),'source_pk_context':file_ref(args.pk_context),
        'status':'RULE_SCOPE_AUDITED_NOT_SCIENTIFIC_MODEL_APPROVAL',
        'source_rules_unchanged':True,'model_fit_calls':0,'human_approval_created':False,
        'project_rule_count':len(source.get('rules',[])), 'projections':stages,
        'current_animal_task':animal,
        'limitations':['Scope classification is deterministic and limited to recognized clauses or explicit stage metadata.',
            'Unknown clauses require scope review before agent execution.',
            'Project thresholds and primary-analysis parameter permissions are preserved; applicability is not scientific validation.']}
    write_json(out/'rule_scope_audit.json',report)
    lines=['# Project rule routing audit','',f"Source rules reviewed: {report['project_rule_count']}. Animal PK rules retained: {len(animal['rules'])}.",'',
        'The original approved context remains unchanged. Effective instructions use the current drug declaration. Published-parameter restrictions remain in force.',
        '', '| Rule | Animal PK | Human prediction | Index | Clinical validation / PTA |', '|---|---|---|---|---|']
    for i,r in enumerate(stages['animal_pk']['audit']):
        lines.append('| '+r['id']+' | '+' | '.join('Included' if stages[s]['audit'][i]['included'] else 'Excluded' for s in ['animal_pk','human_pk','index','clinical'])+' |')
    lines+=['','## Effective animal PK rules','']+[r['text']+'\n' for r in animal['rules']]
    lines+=['','## Execution status','','No numerical model has been fitted by this audit. The refreshed workflow draft requires the existing pre-fit review; this report creates no approval.']
    (out/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print({'rules_audited':report['project_rule_count'],'animal_pk_rules':len(animal['rules']),
        'unresolved':len(animal['unresolved']),'report':str((out/'README.md').resolve())})


if __name__=='__main__':main()
