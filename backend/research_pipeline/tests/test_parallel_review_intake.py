from research_pipeline.workflow_runtime import execute_builtin
from ctxcomp.io import read_json


def test_fresh_workbench_intake_binds_parallel_mode_without_accepting_science(tmp_path):
    proposal=tmp_path/'proposal.txt'; proposal.write_text('Study polymyxin B in rats. Preserve free exposure.',encoding='utf-8')
    work=tmp_path/'run/context_work'
    execute_builtin({'kind':'intake','options':{'work':str(work),
        'uploads':[{'name':proposal.name,'path':str(proposal)}], 'proposal_entry':proposal.name}})
    assert read_json(work/'inputs.json')['context_review_mode']=='parallel_v3'
    assert read_json(work/'state.json')['accepted']=={}
    assert not (work/'handoff/main.json').exists()
