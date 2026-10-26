"""Two-level EDA presentation. Never changes evidence or review decisions."""
import hashlib
import html
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

CSS = '''
:root{--ink:#173547;--muted:#61747c;--line:#dce6e6;--accent:#156f68}*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:#f4f7f6;color:var(--ink);font:16px/1.65 "Segoe UI",Arial,sans-serif}a{color:var(--accent);text-underline-offset:3px}main{max-width:1220px;margin:auto;padding:36px 28px 70px}h1{font-size:38px;line-height:1.15;letter-spacing:-.03em;margin:14px 0}h2{font-size:25px;margin:0 0 14px}h3{font-size:19px;margin:0 0 6px}p{margin:8px 0}.muted,small{color:var(--muted)}.eyebrow{font-size:12px;letter-spacing:.12em;font-weight:700;text-transform:uppercase}.badge{display:inline-block;border:1px solid #c8ded7;border-radius:24px;padding:3px 12px;background:#edf6f1;font-size:12px}.panel,.category{background:white;border:1px solid var(--line);border-radius:16px;padding:25px;margin-top:22px}.lead{font-size:18px;max-width:840px}.tracks{display:grid;grid-template-columns:repeat(3,1fr);gap:22px;margin-top:22px}.tracks>div{border-left:3px solid #a4c9c2;padding-left:16px}.limits{margin-top:26px}.limit{display:grid;grid-template-columns:220px 1fr;gap:20px;padding:15px 0;border-top:1px solid var(--line)}.limit p{margin:0}.label{font-weight:650}.notice{border-left:3px solid #d7af69;padding:10px 16px;background:#fff9ed;margin:22px 0}.categories{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.category{margin:0;color:inherit;text-decoration:none;display:block;transition:box-shadow .15s,transform .15s}.category:hover{box-shadow:0 6px 24px #17354716;transform:translateY(-2px)}.thumbs{display:flex;gap:8px;margin:18px 0;align-items:center;background:#f7f9f8;padding:8px;border-radius:8px}.thumbs img{width:calc((100% - 16px)/3);height:100px;object-fit:contain;background:white}.category .open{color:var(--accent);font-weight:650;font-size:14px}.section-head{display:flex;align-items:baseline;justify-content:space-between;margin:38px 0 16px;gap:16px}.toolbar{position:sticky;top:0;background:#f4f7f6ed;padding:14px 0;z-index:2;display:flex;gap:14px;align-items:center}.toolbar input{font:inherit;padding:10px 14px;border:1px solid #c9d9d6;border-radius:8px;width:min(540px,100%)}.figure{background:white;border:1px solid var(--line);border-radius:14px;margin:20px 0 30px;overflow:hidden;scroll-margin-top:80px}.figure-head,.explanation{padding:20px 24px}.figure-head h3{font-size:23px;overflow-wrap:anywhere}.index{font-size:13px;color:var(--accent);font-weight:700}.metadata{font-size:13px;color:var(--muted)}.figure img{display:block;width:100%;height:auto}.explanation{border-top:1px solid var(--line)}.explanation p{font-size:15px}.full-notes{font-size:13px;margin-top:14px;color:var(--muted)}.caption{white-space:pre-line}.links{display:flex;flex-wrap:wrap;gap:15px;font-size:13px;margin-top:15px}details{margin-top:20px}summary{cursor:pointer;font-weight:650}.issue{padding:15px 0;border-bottom:1px solid var(--line)}.flag{color:#916024;font-size:13px}footer{font-size:13px;color:var(--muted);margin-top:30px}nav{display:flex;flex-wrap:wrap;gap:18px;margin-bottom:24px;font-size:14px}[hidden]{display:none!important}:focus-visible{outline:3px solid #4d9b9a;outline-offset:4px}.skip{position:absolute;left:-10000px}.skip:focus{left:12px;top:12px;background:white;padding:10px}@media(max-width:760px){main{padding:24px 16px}.tracks,.categories{grid-template-columns:1fr}.limit{grid-template-columns:1fr;gap:4px}h1{font-size:30px}.thumbs img{height:90px}.figure-head,.explanation{padding:16px}.section-head{display:block}}@media print{.toolbar,nav{display:none}.figure{break-inside:avoid}body{background:white}}
'''


def build(root, packet, figures, full_html, groups):
    root = Path(root)
    from .eda_run_summary import review_state
    current = review_state(root)
    e = lambda x: html.escape(str(x), quote=True)
    write = lambda p, x: p.write_text(x, encoding='utf8')
    cards = re.findall(r'<article class="figure"\s.*?</article>', full_html, re.S)
    by_id = {html.unescape(re.search(r'data-figure="([^"]+)"', c)[1]): c for c in cards}
    if set(by_id) != {f['figure_id'] for f in figures} or len(cards) != len(figures):
        raise ValueError('Figure cards do not exactly match bound figure bundle')
    overview_path = root / 'review_overview.json'
    overview = json.loads(overview_path.read_text(encoding='utf8')) if overview_path.exists() else {}
    if overview and overview.get('packet_sha256') != packet['content_sha256']:
        raise ValueError('Editorial overview belongs to a different evidence packet')
    (root/'sections').mkdir(exist_ok=True)
    (root/'thumbnails').mkdir(exist_ok=True)
    write(root/'review_portal.css', CSS)
    def shell(title, content, prefix=''):
        return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                f'<title>{e(title)} · EDA review</title><link rel="stylesheet" href="{prefix}review_portal.css"></head>'
                '<body><a class="skip" href="#main">Skip to content</a><main id="main">'+content+'</main></body></html>')
    def local_links(card, prefix):
        def link(m):
            key,url=m[1],html.unescape(m[2])
            if url.startswith('file:'):
                path=Path(unquote(urlparse(url).path).lstrip('/'))
                try:url=path.relative_to(root).as_posix()
                except ValueError:return m[0]
            if not urlparse(url).scheme and not url.startswith('#'):url=prefix+url
            return f'{key}="{e(url)}"'
        return re.sub(r'(href|src)="([^"]+)"',link,card)
    from .eda_figure_review_ui import category_for
    grouped={q:[] for q,_,_ in groups}
    for f in figures:
        q=category_for(f)
        grouped[q].append(f)
    routing=json.loads((root/'dataset_routing.json').read_text(encoding='utf8'))['datasets']
    intro=overview.get('intro','Review the existing figures and recorded limitations before PK and PD input qualification. No model fitting or approval is implied.')
    home=f'<div class="eyebrow">PK / PD workbench · EDA</div><h1>Handoff summary & remaining limitations</h1><p class="lead">{e(intro)}</p><p><span class="badge">Human review pending</span> <span class="muted">{len(figures)} figures · {len(routing)} datasets · Source data unchanged</span></p>'
    home+='<section class="panel" id="handoff"><h2>What is available for the next step</h2><div class="tracks">'
    tracks=overview.get('tracks') or [{'title':f['finding_id'],'text':f['observation']} for f in packet['summary']['findings']]
    for t in tracks:home+=f'<div><h3>{e(t["title"])}</h3><p>{e(t["text"])}</p></div>'
    home+='</div><div class="limits"><h2>What still needs attention</h2>'
    limits=overview.get('limitations') or [{'title':'Recorded limitation','impact':t} for t in packet['summary']['limitations']+packet['summary']['open_items']]
    for t in limits:home+=f'<div class="limit"><div class="label">{e(t["title"])}</div><p>{e(t["impact"])}</p></div>'
    home+='</div><p class="notice">These limitations apply to the analyses that depend on them. Reviewing the figures can continue; model input qualification must resolve the relevant checks before fitting.</p></section>'
    home+='<div class="section-head" id="categories"><h2>Review by category</h2><span class="muted">Open a category to see every figure.</span></div><div class="categories">'
    index=[]
    for q,label,purpose in groups:
        fs=grouped[q]
        if not fs:continue
        folder=root/'sections'/q;folder.mkdir(exist_ok=True)
        previews=[]
        for f in fs[:3]:
            fid=f['figure_id'];source=Path(f['image_ref']['path'])
            if hashlib.sha256(source.read_bytes()).hexdigest()!=f['image_ref']['sha256']:raise ValueError('Changed figure: '+fid)
            thumb=root/'thumbnails'/(fid+'.jpg')
            try:
                from PIL import Image
                with Image.open(source) as im:
                    im=im.convert('RGB');im.thumbnail((440,280));im.save(thumb,quality=82)
                src=thumb.relative_to(root).as_posix()
            except ImportError:
                src=source.relative_to(root).as_posix()
            previews.append(f'<img src="{e(src)}" alt="Preview of {e(fid)}" loading="lazy">')
        home+=f'<a class="category" id="{q}" href="sections/{q}/index.html"><span class="badge">{len(fs)} figures</span><h3>{e(label)}</h3><p class="muted">{e(purpose)}</p><div class="thumbs">'+''.join(previews)+f'</div><span class="open">View all {len(fs)} figures →</span></a>'
        category=f'<nav><a href="../../index.html#categories">← All categories</a><a href="../../index.html#handoff">Handoff summary</a><a href="../../index.html#review-notes">Review status</a></nav><div class="eyebrow">EDA figure review</div><h1>{e(label)}</h1><p class="lead">{e(purpose)}</p><p class="muted">{len(fs)} figures · Full-size plots with original explanations · Human review pending</p><div class="toolbar"><input type="search" id="search" aria-label="Search this category" placeholder="Find a strain, dataset or figure…"><span id="count" aria-live="polite">{len(fs)} figures</span></div><p id="empty" hidden>No figures match this search.</p>'
        binding=[f for f in fs if (f.get('render_recipe',{}).get('display_policy',{}).get('parent_view') or f['figure_id'].split('__',1)[0])=='BINDING_ASSAYS']
        if q=='Q_CONTEXT' and binding:
            category+='<h2 id="protein-binding">Protein binding</h2>'
            category+=''.join(local_links(by_id[f['figure_id']],'../../') for f in binding)
            remaining=[f for f in fs if f not in binding]
            if remaining:
                category+='<h2 id="other-context">MIC and other supporting context</h2>'
                category+=''.join(local_links(by_id[f['figure_id']],'../../') for f in remaining)
        else:
            category+=''.join(local_links(by_id[f['figure_id']],'../../') for f in fs)
        category+='<footer><a href="../../index.html#categories">← Back to all categories</a><p>Existing figures and source rows are unchanged. This page does not record approval or start modeling.</p></footer><script>const cards=[...document.querySelectorAll("[data-figure]")];document.querySelector("#search").addEventListener("input",e=>{let n=0;for(const c of cards){c.hidden=!c.dataset.search.includes(e.target.value.toLowerCase());if(!c.hidden)n++}document.querySelector("#count").textContent=`${n} of ${cards.length} figures`;document.querySelector("#empty").hidden=n!==0});</script>'
        write(folder/'index.html',shell(label,category,'../../'))
        index.append({'id':q,'label':label,'path':f'sections/{q}/index.html','figure_ids':[f['figure_id'] for f in fs]})
    home+='</div><section class="panel" id="review-notes"><h2>Review status & next step</h2>'
    home+='<p class="notice"><b>'+e(current['status'])+'</b><br>'+e(current['next_step'])+'</p>'
    if (root/'issue_dispositions.json').exists():
        home+='<p>The original ER returned <b>REVISE</b>. Corrections and follow-up checks are recorded separately; there has been no new independent ER of this revised package.</p><div class="links"><a href="issue_dispositions.json">Recorded corrections</a><a href="independent_review.json">Original ER record</a></div>'
    else:home+=f'<p>Independent review: <b>{e(packet["review_decision"])}</b>. Human confirmation remains pending.</p>'
    home+='<p>Review each category and flag anything that needs correction. PK and PD routing is prepared; neither branch has been released for modeling.</p><details><summary>Complete recorded findings and limitations</summary>'
    for f in packet['summary']['findings']:home+=f'<h3>{e(f["finding_id"])}</h3><p>{e(f["observation"])}</p><p class="muted">{e(f["downstream_implication"])}</p>'
    home+='<p class="muted">The original EI record below refers to its earlier rendering, including historical counts. The current page counts are shown above.</p><ul>'+''.join('<li>'+e(x)+'</li>' for x in packet['summary']['limitations']+packet['summary']['open_items'])+'</ul></details>'
    home+='<details><summary>Review evidence and packet identity</summary><div class="links"><a href="human_review.json">Review packet</a><a href="dataset_routing.json">Dataset destinations</a><a href="branch_drafts.json">Branch drafts</a><a href="human_decision.template.json">Pending decision template</a></div><p>'+e(packet['content_sha256'])+'</p></details></section><footer>See the bound calculation and review records for this version. This page does not grant scientific approval.</footer>'
    from .eda_dose_normalization import ui_section
    home=home.replace('<section class="panel" id="review-notes">',ui_section(root)+'<section class="panel" id="review-notes">',1)
    page=shell('Handoff summary',home)
    for name in ['index.html','human_review.html']:write(root/name,page)
    write(root/'review_navigation.json',json.dumps({'version':'EDA_TWO_LEVEL_REVIEW_1','packet_sha256':packet['content_sha256'],'figure_count':len(figures),'groups':index,'downloads':False},indent=2))
    retired=root/'sections/Q_PK_VARIABILITY/index.html'
    if retired.exists():
        write(retired,shell('Figures regrouped','<h1>Figures regrouped</h1><p>These figures are now under <a href="../Q_PD_EFFECT/index.html">PD endpoints</a> and <a href="../Q_CONTEXT/index.html#protein-binding">Supporting context / Protein binding</a>.</p><p><a href="../../index.html#categories">All categories</a></p>','../../'))
    return index
