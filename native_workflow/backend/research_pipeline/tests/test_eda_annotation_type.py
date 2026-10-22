import copy
import pytest
from research_pipeline.eda_post_ec import apply

@pytest.mark.parametrize('notes',['Original source note.',['First source note.','Second source note.'],[]])
def test_keep_preserves_source_annotation_type_and_complete_notes(notes):
    selection={'dataset_id':'D1','x':'','y':'','group_by':'','x_scale':'linear','y_scale':'linear'}
    frozen={'tasks':[{'task_id':'T1','dataset_id':'D1','operation_id':'SOURCE_TABLE',
        'selection':selection,'columns':[],'records':[],'context':{'annotations':copy.deepcopy(notes)}}]}
    before=copy.deepcopy(frozen)
    raw={'version':'EP_FINAL_DISPLAYS_1.0','summary':'Offline fixture','open_items':[],
        'task_decisions':[{'task_id':'T1','decision':'KEEP','operation_id':'SOURCE_TABLE','selection':selection,
            'reason':'Source table remains supported.','additional_note':'Keep the source limitation.'}]}
    final=apply(raw,frozen)[0]['context']['annotations']
    assert frozen==before
    assert type(final) is type(notes)
    if isinstance(notes,list):
        assert final[:-1]==notes and len(final)==len(notes)+1
        assert final[-1]=='Post-EC display review: Source table remains supported.\nKeep the source limitation.'
    else:assert final.startswith(notes+'\nPost-EC display review:')
