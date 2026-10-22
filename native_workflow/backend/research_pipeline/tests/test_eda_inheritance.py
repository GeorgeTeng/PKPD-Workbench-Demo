import copy
from research_pipeline.eda_inheritance import project, digest


def fixture():
    global_issue={'code':'GLOBAL','affected_id':'DR001','reason':'Retain project boundary.'}
    selected_issue={'code':'MISSING_N','affected_id':'DR002','reason':'Sample count unknown.'}
    other_issue={'code':'OTHER','affected_id':'MC002','reason':'Other source limitation.'}
    cross_issue={'code':'CONFLICT','affected_id':'F003:S2:T1','reason':'Conflict with F003:S1:T1.'}
    items=[global_issue,selected_issue,copy.deepcopy(selected_issue),other_issue,cross_issue]
    unresolved=[{'id':str(i),'record':copy.deepcopy(x),'resolution_status':'OPEN','history':[]} for i,x in enumerate(items)]
    inputs={'data_handoff':{'unknowns':items,'unresolved_items':unresolved,'rows':[{'v':'BLQ'}]}}
    owners={digest(selected_issue):{'F003:S1:T1'},digest(other_issue):{'F003:S2:T1'}}
    return inputs,owners


def test_lineage_scopes_requirement_ids_without_text_inference():
    inputs,owners=fixture()
    result,audit=project(inputs,{'F003:S1:T1'},{'F003:S1:T1','F003:S2:T1'},{'T0001'},{'T0001','T0002'},owners)
    assert audit['kept_original_indices']['unknowns']==[0,1,2,4]
    assert len(audit['excluded'])==2
    assert len(result['data_handoff']['inherited_issue_registry'])==3
    assert result['data_handoff']['rows']==inputs['data_handoff']['rows']
    assert audit['exact_round_trip'] is True
    assert inputs['data_handoff']['unknowns'][1]==inputs['data_handoff']['unknowns'][2]


def test_unknown_ownership_remains_visible():
    inputs,_=fixture()
    _,audit=project(inputs,{'F003:S1:T1'},{'F003:S1:T1','F003:S2:T1'},{'T0001'},{'T0001','T0002'})
    assert audit['excluded']==[]
    assert audit['kept_original_indices']['unknowns']==list(range(5))


def test_shared_ownership_keeps_issue_if_either_source_is_selected():
    inputs,owners=fixture()
    owners[digest(inputs['data_handoff']['unknowns'][3])]={'F003:S1:T1','F003:S2:T1'}
    _,audit=project(inputs,{'F003:S1:T1'},{'F003:S1:T1','F003:S2:T1'},{'T0001'},{'T0001','T0002'},owners)
    assert audit['excluded']==[]

