import copy
import pytest
from jsonschema import Draft202012Validator,ValidationError
from research_pipeline import eda_questions_v3 as q,eda_questions as old
from research_pipeline import eda_inheritance as inheritance
from research_pipeline.common import read_json,write_json
from research_pipeline import context_builder as cb
from ctxcomp.io import digest

def finding():
    return dict(finding_id='context',analysis_ids=[x[0] for x in q.QUESTIONS],artifact_refs=['V'],
        record_scope=[],observation='Separate source panels.',interpretation_if_useful='',
        alternative_if_interpretation='',downstream_implication='Do not pool studies.',
        visual_support=dict(status='OBSERVED',figure_ids=['V'],features='Separate panels.',limitations=[]),
        anomaly_assessment=dict(status='NOT_ASSESSED',record_ids=[],observation='Not assessed.',
            possible_explanations=[],recommended_action='Review.',affected_analysis='Q_CONTEXT',data_changed=False))

def payload(f):
    return dict(version='QUESTION_FINDINGS_3',input_refs=['V'],findings=[f],limitations=[],open_items=[])

TABLES={'D':{'records':[{'record_id':'R'}], 'columns':[{'id':'y','meaning':'RESPONSE'},{'id':'time','meaning':'TIME'}]}}

def test_original_schema_reproduces_missing_anchor_conflict():
    value=payload(finding())
    Draft202012Validator(old.findings_schema(TABLES,['V'])).validate(value)
    with pytest.raises(ValueError,match='record anchors'):
        old.validate_findings(value,[x[0] for x in q.QUESTIONS],['V'],TABLES)
    with pytest.raises(ValidationError):
        Draft202012Validator(q.findings_schema(TABLES,['V'])).validate(value)

@pytest.mark.parametrize('status,records,figures,valid',[
    ('OBSERVED',['R'],['V'],True),('OBSERVED',[],['V'],False),
    ('OBSERVED',['R'],[],False),('OBSERVED',['invented'],['V'],False),
    ('NON_GRAPHICAL',[],[],True),('NOT_ASSESSED',[],[],True)])
def test_conditional_record_anchors_in_host_and_wire(status,records,figures,valid):
    f=finding();f['record_scope']=records;f['visual_support'].update(status=status,figure_ids=figures)
    value=payload(f)
    for schema in [q.findings_schema(TABLES,['V']),q.strict_schema(q.findings_schema(TABLES,['V']))]:
        if valid:Draft202012Validator(schema).validate(value)
        else:
            with pytest.raises(ValidationError):Draft202012Validator(schema).validate(value)
    if valid:q.validate_findings(value,[x[0] for x in q.QUESTIONS],['V'],TABLES)

def test_unshown_fields_exclude_time_and_prose():
    schema=q.disposition_schema(TABLES)
    d=dict(dataset_id='D',status='CONTEXT_ONLY',reason='Retained source.',unshown_columns=['y'])
    Draft202012Validator(schema).validate([d])
    for bad in ['time','y: unavailable']:
        d['unshown_columns']=[bad]
        with pytest.raises(ValidationError):Draft202012Validator(schema).validate([d])

@pytest.mark.parametrize('interpretation,alternative,valid',[
    ('','',True),('Hypothesis','',False),('Hypothesis','   ',False),
    ('Hypothesis','Plausible alternative',True)])
def test_interpretation_requires_alternative_in_wire_schema(interpretation,alternative,valid):
    f=finding();f['record_scope']=['R']
    f.update(interpretation_if_useful=interpretation,alternative_if_interpretation=alternative)
    validator=Draft202012Validator(q.strict_schema(q.findings_schema(TABLES,['V'])))
    assert validator.is_valid(payload(f)) is valid

@pytest.mark.parametrize('records,explanations,valid',[
    ([],[],False),(['R'],[],False),([],['Explanation'],False),(['R'],['Explanation'],True)])
def test_anomaly_candidates_need_both_records_and_explanations(records,explanations,valid):
    f=finding();f['record_scope']=['R']
    f['anomaly_assessment'].update(status='CANDIDATES',record_ids=records,possible_explanations=explanations)
    assert Draft202012Validator(q.strict_schema(q.findings_schema(TABLES,['V']))).is_valid(payload(f)) is valid

def setup_scope(tmp_path):
    metadata={}
    for did,sid in [('D1','S1'),('D2','S2')]:
        p=write_json(tmp_path/(did+'.json'),{'metadata':{'source_item_id':sid}});metadata[did]=cb.file_ref(p)
    issue={'affected_id':'DR001','reason':'Missing count'}
    request={'payload':{'item_id':'S2'}};request['request_sha256']=digest(request['payload'])
    response={'request_sha256':request['request_sha256'],'labels':[{'item_id':'S2'}],'findings':[issue]}
    rq=write_json(tmp_path/'request.json',request);rs=write_json(tmp_path/'response.json',response)
    manifest=write_json(tmp_path/'manifest.json',{'version':'EDA_INHERITANCE_SCOPE_1','dataset_metadata':metadata,
        'lineage':[{'request':cb.file_ref(rq),'response':cb.file_ref(rs)}]})
    inp=write_json(tmp_path/'input.json',{'task_context':{'rules':['preserve']},'data_handoff':{
        'files':[{'id':'D1','metadata_file':metadata['D1']}],'unknowns':[issue,issue],
        'unresolved_items':[{'id':'U','record':issue,'status':'OPEN'}]}})
    return inp,manifest,rq

def test_bound_scope_excludes_only_verified_other_source(tmp_path):
    inp,m,_=setup_scope(tmp_path)
    out=inheritance.prepare(inp,tmp_path/'out',m)
    result=read_json(out);audit=read_json(tmp_path/'out/inheritance_audit.json')
    assert len(audit['excluded'])==3 and audit['exact_round_trip']
    assert result['task_context']==read_json(inp)['task_context']
    cb.check_refs(audit['lineage_refs'])

def test_no_lineage_retains_ambiguous_occurrences_losslessly(tmp_path):
    inp,_,_=setup_scope(tmp_path)
    result=read_json(inheritance.prepare(inp,tmp_path/'out'))['data_handoff']
    assert len(result['inherited_issue_registry'])==1
    assert result['unknowns'][0]['original_indices']==[0,1]
    assert result['unresolved_items'][0]['status']=='OPEN'

def test_changed_lineage_fails_before_output(tmp_path):
    inp,m,rq=setup_scope(tmp_path)
    request=read_json(rq);request['payload']['item_id']='S1';write_json(rq,request)
    with pytest.raises(ValueError):inheritance.prepare(inp,tmp_path/'out',m)
    assert not (tmp_path/'out').exists()

def test_resigned_but_inconsistent_lineage_digest_fails(tmp_path):
    inp,m,rq=setup_scope(tmp_path)
    request=read_json(rq);request['payload']['item_id']='S1';write_json(rq,request)
    manifest=read_json(m);manifest['lineage'][0]['request']=cb.file_ref(rq);write_json(m,manifest)
    with pytest.raises(ValueError,match='digest mismatch'):inheritance.prepare(inp,tmp_path/'out',m)

def test_formal_cli_routes_current_adapter_and_scope(monkeypatch):
    import sys
    from research_pipeline import eda_workflow
    captured={}
    def run(*args,**kwargs):captured.update(args=args,kwargs=kwargs);return {'status':'TEST'}
    from research_pipeline import eda_questions_v6 as current
    monkeypatch.setattr(current,'run_questions',run)
    monkeypatch.setattr(sys,'argv',['eda','run-questions','--inputs','i','--completed-run','ec',
        '--catalog','c','--out','o','--until','ER','--inheritance-scope','m'])
    eda_workflow.main()
    assert captured['args']==('i','ec','c','o')
    assert captured['kwargs']['inheritance_scope']=='m'

def test_current_runner_applies_inheritance_before_intake(tmp_path,monkeypatch):
    calls=[]
    def prepare(*args):calls.append(args);return 'scoped'
    def intake(*args):
        assert args[0]=='scoped'
        raise RuntimeError('intake reached')
    monkeypatch.setattr(inheritance,'prepare',prepare);monkeypatch.setattr(q,'intake',intake)
    with pytest.raises(RuntimeError,match='intake reached'):
        q.run_questions('raw','ec','catalog',tmp_path/'run',inheritance_scope='manifest')
    assert calls==[('raw',tmp_path/'run/admitted_inputs','manifest')]

def test_real_r_categorical_figures_have_independent_axes(tmp_path):
    import subprocess
    from research_pipeline import eda_display_catalog_v2 as dc
    from research_pipeline.engine import rscript_path
    rows=[dict(dataset_id="SYNTHETIC",record_id=p+str(i),y_column="y",x=i,y=y,error=None,n=None,panel=p,group=p,category=str(i),bound='',
        plot_eligible=True,original_status='QUANTIFIED',raw_y=y)
        for p,ys in [('MIC',[.01,.2]),('ED50',[10,100])] for i,y in enumerate(ys,1)]
    plots=[dict(id=scale+'_'+panel,rows=[r for r in rows if r['panel']==panel],
            categorical=True,scale='linear',facet_scales=scale,standalone=True,
            figure_index='EDA-'+str(i*2+j+1),ncol=1,title='Source quantities',
            question='Independent axes',x_label='Strain',y_label=panel,
            caption='Different units; no pooling.',legend=True)
            for i,scale in enumerate(['fixed','free_x','free_y','free'])
            for j,panel in enumerate(['MIC','ED50'])]
    request=write_json(tmp_path/'request.json',{'plots':plots})
    proc=subprocess.run([rscript_path(),'--vanilla',str(dc.SOURCE_HANDLER),str(request),str(tmp_path),
        str(dc.PROJECT/'pkpd_r/eda/plot_style.R')],capture_output=True,text=True)
    assert proc.returncode==0,proc.stderr
    manifest=read_json(tmp_path/'manifest.json')
    for a in manifest['artifacts']:
        ranges=a['panel_y_ranges']
        assert a['panels']==1 and len(ranges)==1
        if a['id'].endswith('_MIC'):assert ranges[0][1]<1
        else:assert ranges[0][1]>100
