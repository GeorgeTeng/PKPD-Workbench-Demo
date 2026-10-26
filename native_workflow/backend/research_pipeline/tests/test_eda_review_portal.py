"""Synthetic presentation tests; no original research data or model calls."""
import hashlib
import json
import pytest
from research_pipeline.eda_review_portal import build


def setup(root):
    from PIL import Image
    root.mkdir(exist_ok=True)
    image = root/'figure.png'
    Image.new('RGB',(24,12),'white').save(image)
    (root/'dataset_routing.json').write_text('{"datasets": []}',encoding='utf8')
    figures=[{'figure_id':'SYNTHETIC','analysis_ids':['Q_CONTEXT'],
              'image_ref':{'path':str(image),'sha256':hashlib.sha256(image.read_bytes()).hexdigest()}}]
    packet={'content_sha256':'synthetic-packet','review_decision':'REVISE',
            'summary':{'findings':[],'limitations':['Unresolved synthetic scope'],'open_items':[]}}
    card=f'<article class="figure" id="figure-SYNTHETIC" data-figure="SYNTHETIC" data-search="synthetic"><img src="{image.as_uri()}"><p>Value 0.5; value 0.5; UNKNOWN.</p></article>'
    return packet,figures,card,[('Q_CONTEXT','Context','Inspect source context.')]


def test_home_is_summary_first_and_category_retains_full_figure(tmp_path):
    args=setup(tmp_path);before=(tmp_path/'figure.png').read_bytes()
    build(tmp_path,*args)
    home=(tmp_path/'index.html').read_text(encoding='utf8')
    category=(tmp_path/'sections/Q_CONTEXT/index.html').read_text(encoding='utf8')
    assert '<article class="figure"' not in home
    assert home.index('Handoff summary')<home.index('Review by category')
    assert 'sections/Q_CONTEXT/index.html' in home
    assert 'Value 0.5; value 0.5; UNKNOWN.' in category
    assert '../../figure.png' in category and 'file:' not in category
    assert '.zip' not in home and 'download=' not in home
    assert (tmp_path/'figure.png').read_bytes()==before
    nav=json.loads((tmp_path/'review_navigation.json').read_text())
    assert nav['figure_count']==1 and nav['groups'][0]['figure_ids']==['SYNTHETIC']


def test_stale_overview_cannot_summarize_new_packet(tmp_path):
    args=setup(tmp_path)
    (tmp_path/'review_overview.json').write_text('{"packet_sha256":"different"}',encoding='utf8')
    with pytest.raises(ValueError,match='different evidence packet'):build(tmp_path,*args)


def test_missing_or_duplicate_cards_fail_before_page_generation(tmp_path):
    packet,figures,card,groups=setup(tmp_path)
    for text in ['',card+card]:
        with pytest.raises(ValueError,match='exactly match'):build(tmp_path,packet,figures,text,groups)
    assert not (tmp_path/'index.html').exists()


@pytest.mark.parametrize('family,tags,expected',[
    ('PD_THIGH_INTERVAL',['Q_PK_VARIABILITY','Q_PD_EFFECT'],'Q_PD_EFFECT'),
    ('PD_RABBIT_INTERVAL',['Q_PK_VARIABILITY','Q_PD_EFFECT'],'Q_PD_EFFECT'),
    ('BINDING_ASSAYS',['Q_PK_VARIABILITY','Q_CONTEXT'],'Q_CONTEXT'),
    ('MIC_STUDIES',['Q_INDEX','Q_CONTEXT'],'Q_CONTEXT'),
    ('INDEX_ECOLI',['Q_INDEX'],'Q_INDEX'),
    ('PK_MOUSE',['Q_PK_SHAPE','Q_PK_VARIABILITY'],'Q_PK_SHAPE'),
])
def test_scientific_membership_order_does_not_misclassify_display(family,tags,expected):
    import copy
    from research_pipeline.eda_figure_review_ui import category_for
    figure={'figure_id':family+'__S1','analysis_ids':tags,
            'render_recipe':{'display_policy':{'parent_view':family}}}
    original=copy.deepcopy(figure)
    assert category_for(figure)==expected and figure==original
    figure['analysis_ids']=list(reversed(tags))
    assert category_for(figure)==expected


def test_regrouped_render_keeps_all_figures_and_retires_old_navigation(tmp_path):
    import copy
    import re
    from research_pipeline.eda_figure_review_ui import render
    packet,base,_,_=setup(tmp_path)
    packet['summary'].update(issues=[],unreviewed_items=[])
    cases=[('PD_THIGH_INTERVAL__S1',['Q_PK_VARIABILITY','Q_PD_EFFECT']),
           ('PD_THIGH_INTERVAL__S2',['Q_PK_VARIABILITY','Q_PD_EFFECT']),
           ('PD_RABBIT_INTERVAL__S1',['Q_PK_VARIABILITY','Q_PD_EFFECT'])]
    cases += [('BINDING_ASSAYS__S'+str(i),['Q_PK_VARIABILITY','Q_CONTEXT']) for i in range(1,5)]
    cases += [('MIC_STUDIES__S1',['Q_INDEX','Q_CONTEXT'])]
    figures=[dict(base[0],figure_id=fid,analysis_ids=tags) for fid,tags in cases]
    before=copy.deepcopy(figures);image_before=(tmp_path/'figure.png').read_bytes()
    retired=tmp_path/'sections/Q_PK_VARIABILITY/index.html'
    retired.parent.mkdir(parents=True)
    retired.write_text('Old category',encoding='utf8')
    render(tmp_path,packet,figures)
    nav=json.loads((tmp_path/'review_navigation.json').read_text())
    assert {g['id']:len(g['figure_ids']) for g in nav['groups']}=={'Q_PD_EFFECT':3,'Q_CONTEXT':5}
    ids=[]
    for group in nav['groups']:
        page=(tmp_path/group['path']).read_text(encoding='utf8')
        ids+=re.findall('data-figure="([^"]+)"',page)
        assert 'interpreting variability' not in page
    assert sorted(ids)==sorted(fid for fid,_ in cases) and len(set(ids))==8
    assert 'PK variability' not in (tmp_path/'index.html').read_text(encoding='utf8')
    assert 'Protein binding</h2>' in (tmp_path/'sections/Q_CONTEXT/index.html').read_text(encoding='utf8')
    assert 'data-figure=' not in retired.read_text(encoding='utf8')
    assert figures==before and (tmp_path/'figure.png').read_bytes()==image_before
