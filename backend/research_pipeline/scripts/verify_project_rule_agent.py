"""Small live-provider integration check using labeled synthetic source text only."""
from pathlib import Path
import argparse
from research_pipeline import project_rule_agent as agent
from research_pipeline.common import write_json, utcnow
from research_pipeline.graph_execution import run_controlled


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True);args=parser.parse_args()
    root=Path(args.out).resolve()
    if root.exists() and any(root.iterdir()):raise ValueError('Choose a fresh verification directory')
    root.mkdir(parents=True,exist_ok=True)
    proposal=('Synthetic software verification project, not a scientific study.\n\n'
        'Objective: describe animal PK.\n\n'
        'Human PK data may be used only for final validation. This data-use restriction applies during animal_pk, human_pk and clinical tasks.\n\n'
        'For preparation and EDA, preserve source units.\n\n'
        'A literature method is a candidate only; this project does not mandate a compartment number.')
    sources=[{'id':'S1','name':'synthetic_proposal.txt','role':'PROPOSAL','text':proposal},
        {'id':'P1','name':'synthetic_paper_excerpt.txt','role':'SUPPORTING_EVIDENCE','locator':'Methods, paragraph 1',
         'text':'In this synthetic example paper, investigators fitted a two-compartment model.'}]
    main_value={'version':'3.0','objective':'Describe animal PK.',
        'study':dict(drug='Synthetic compound',regimen='NOT_FOUND',population='animal',system='NOT_FOUND',measurements='NOT_FOUND',methods='NOT_FOUND'),
        'data':{'available':[],'required':[],'files':[]},
        'rules':['R001: Human PK data may be used only for final validation.',
                 'R002: For preparation and EDA, preserve source units.'],
        'checks':[],'uncertainties':[]}
    main_ref=agent.file_ref(write_json(root/'fixture/main.json',main_value))
    sources_ref=agent.file_ref(write_json(root/'fixture/sources.json',sources))
    input_ref=agent.file_ref(write_json(root/'fixture/input.json',agent._input_value(main_ref,sources,[sources_ref])))
    write_json(root/'VERIFICATION_ONLY.json',{'kind':'SYNTHETIC_PROVIDER_INTEGRATION_TEST',
        'real_project_sources_used':False,'compression_reexecuted':False,'scientific_results':False,
        'purpose':'Exercise two fresh model calls and deterministic publication through the actual scheduler.'})
    spec={'id':'project_rules_verification','created_at':utcnow(),'mode':'project_rules',
        'stop_after':'project_rules','job_dir':str(root/'job'),'out':str(root/'run'),
        'project_rules_input':input_ref,'model':None}
    request=write_json(root/'job/request.json',spec)
    result=run_controlled(str(request),target='project_rules')
    write_json(root/'verification_result.json',result)
    print(__import__('json').dumps({'disposition':result['control']['disposition'],'runtime':result['status']}))
    if result['status']!='PROJECT_RULES_PUBLISHED':raise SystemExit(1)


if __name__=='__main__':main()
