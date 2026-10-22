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
