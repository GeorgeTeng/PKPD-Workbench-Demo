"""Figure-first human review; presentation only, no new analysis or approvals."""
import html
from pathlib import Path
from .common import read_json

GROUPS = [
 ('Q_PK_SHAPE','PK profiles','Understand the recorded concentration-time shape before PK input qualification.'),
 ('Q_PK_VARIABILITY','PK variability','Check the available replication and observation levels before interpreting variability.'),
 ('Q_PD_EFFECT','PD endpoints','Compare recorded endpoint responses within the displayed study and treatment groups.'),
 ('Q_INDEX','Exposure–response indices','Inspect each source exposure–response panel separately before assessing index-analysis inputs.'),
 ('Q_TIMEKILL','Time-kill','Inspect the recorded time course and its measurement limits before PD input qualification.'),
 ('Q_CONTEXT','Supporting context','Review source-specific MIC, binding, regimen or tissue context for the relevant downstream analysis.')]

CSS='''
:root{--ink:#173547;--muted:#5f747c;--line:#dbe5e7;--accent:#126b66}*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:20px}body{margin:0;color:var(--ink);background:#f3f6f6;font:16px/1.6 "Segoe UI",Arial,sans-serif}
a{color:var(--accent);text-underline-offset:3px}button,input,select{font:inherit}button,select{cursor:pointer}
.layout{display:grid;grid-template-columns:200px minmax(0,1fr);gap:32px;max-width:1570px;margin:auto;padding:32px}
aside{position:sticky;top:26px;align-self:start}.brand{font-size:13px;font-weight:750;letter-spacing:.12em}nav{margin:25px 0}nav a{display:block;padding:9px 0;text-decoration:none;font-size:14px}
.muted{color:var(--muted)}.small{font-size:13px}h1{font-size:38px;line-height:1.2;letter-spacing:-.035em;margin:8px 0 14px}h2{font-size:26px;line-height:1.3;margin:0}h3{font-size:20px;line-height:1.4;margin:5px 0;overflow-wrap:anywhere}
header p{max-width:760px}.badge{display:inline-block;border:1px solid #c5dcdb;border-radius:30px;padding:3px 10px;color:var(--accent);font-size:12px;vertical-align:middle}
.state{background:#fff5df;border:1px solid #e8d6b4;border-radius:10px;padding:13px 17px;font-size:14px;margin:20px 0}
.toolbar{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin:25px 0 12px}.toolbar input{flex:1;min-width:220px}.toolbar input,.toolbar select,.toolbar button{border:1px solid #cddcdd;background:white;border-radius:8px;padding:9px 12px;color:var(--ink)}
.group{margin-top:38px}.group-heading{display:flex;justify-content:space-between;align-items:center;margin-bottom:17px;gap:12px}
.figure{background:white;border:1px solid var(--line);border-radius:14px;margin:0 0 26px;overflow:hidden;scroll-margin-top:20px}.figure-head{padding:20px 24px 10px}.index{color:var(--accent);font-size:13px;font-weight:700;letter-spacing:.06em}.metadata{font-size:13px;color:var(--muted);margin:7px 0 0}
.figure img{width:100%;height:auto;display:block;background:white}.explanation{padding:17px 24px 22px;border-top:1px solid #edf1f1}.explanation p{margin:6px 0;font-size:15px}.explanation strong{font-weight:650}.full-notes{margin-top:14px;font-size:13px;color:var(--muted)}summary{cursor:pointer;font-weight:600}details p{overflow-wrap:anywhere}.caption{white-space:pre-line}
.box{background:white;border:1px solid var(--line);border-radius:12px;padding:22px;margin:20px 0}.box>summary{font-size:18px}.issue{padding:14px 0;border-bottom:1px solid var(--line)}.issue p{font-size:14px;margin:6px 0}.flag{color:#925d18;font-size:12px;font-weight:700}
.links{display:flex;flex-wrap:wrap;gap:18px;margin-top:12px;font-size:13px}footer{margin:30px 0;font-size:13px;color:var(--muted)}[hidden]{display:none!important}
:focus-visible{outline:3px solid #599daf;outline-offset:3px}.skip{position:absolute;left:-10000px}.skip:focus{left:20px;top:10px;background:white;padding:12px;z-index:5}
@media(max-width:950px){.layout{display:block;padding:20px}aside{position:static}nav{display:flex;flex-wrap:wrap;gap:14px;margin:12px 0}nav a{padding:4px 0}aside .small{display:none}h1{font-size:31px}.figure-head,.explanation{padding:16px}}
@media print{aside,.toolbar,.links{display:none}.layout{display:block;padding:0}.figure{break-inside:avoid}.figure[hidden],.group[hidden]{display:block!important}body{background:white}}
'''

JS='''
const cards=[...document.querySelectorAll('[data-figure]')];
const sections=[...document.querySelectorAll('[data-section]')];
const search=document.querySelector('#search'), group=document.querySelector('#group-filter');
function filter(){let n=0;for(const c of cards){const show=(group.value==='all'||c.dataset.group===group.value)&&c.dataset.search.includes(search.value.toLowerCase());c.hidden=!show;if(show)n++;}
 for(const s of sections)s.hidden=![...s.querySelectorAll('[data-figure]')].some(c=>!c.hidden);
 document.querySelector('#count').textContent=`${n} of ${cards.length} figures shown`;
 document.querySelector('#empty').hidden=n!==0;
}
search.addEventListener('input',filter);group.addEventListener('change',filter);
document.querySelector('#reset').addEventListener('click',()=>{search.value='';group.value='all';filter();});
document.querySelectorAll('[data-group-link]').forEach(a=>a.addEventListener('click',()=>{search.value='';group.value='all';filter();}));
'''


def render(root, packet, figures):
    root=Path(root);e=lambda x:html.escape(str(x),quote=True)
    routing_path=root/'dataset_routing.json'
    ledger=read_json(routing_path)['datasets'] if routing_path.exists() else []
    routing={r['dataset_id']:r for r in ledger}
    grouped={q:[] for q,_,_ in GROUPS}
    for f in figures:
        qs=f.get('analysis_ids',[])
        key=next((q for q,_,_ in GROUPS if q in qs),'Q_CONTEXT')
        grouped[key].append(f)
    s=packet['summary']
    from .eda_run_summary import review_state
    current=review_state(root)
    factpath=root/'review_claim_fact_check.json';notepath=root/'post_run_review_notes.json'
    contradictions=set()
    if factpath.exists():
        facts=read_json(factpath)
        if facts.get('status')=='REVIEW_CLAIM_FACT_CHECK_NOT_APPROVAL':
            for c in facts.get('checks',[]):
                if c['source_value']==c['decoded_model_input_value']==c['plotted_value']:
                    # Exact known issue IDs are identified in this companion report's conclusion.
                    for batch,issue in [('ER_001','ER001-01'),('ER_003','ER003-01'),('ER_004','ER004-01')]:
                        if c['batch']==batch and issue in facts.get('conclusion',''):contradictions.add(batch+':'+issue)
    if notepath.exists():
        for c in read_json(notepath).get('visual_checks',[]):
            if c['assessment']=='CONTRADICTED_BY_EXACT_RENDER':contradictions.add(c['issue_id'])
    parts=['<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>EDA · Figure review</title><style>'+CSS+'</style></head><body><a class="skip" href="#main">Skip to figures</a><div class="layout"><aside><div class="brand">PK / PD WORKBENCH</div><nav aria-label="Figure groups">']
    for q,label,_ in GROUPS:
        if grouped[q]:parts.append(f'<a href="#{q}" data-group-link>{e(label)} <span class="muted">{len(grouped[q])}</span></a>')
    parts+=['<a href="#review-notes">Review notes</a><a href="#handoff">Handoff</a></nav><p class="small muted">Every figure is shown at full column width.<br><br>Reviewing this page does not approve or start modeling.</p></aside><main id="main"><header><span class="badge">Human review · Pending</span><h1>Review the figures.</h1><p class="muted">Start with the plots. Each has a short purpose, reading guide and limitation. Original captions and source details are available below each figure.</p>',
        f'<div class="state">{len(figures)} existing figures · {len(ledger)} datasets · ER: <b>{e(packet["review_decision"])}</b>. ']
    if contradictions:parts.append(f'{len(contradictions)} of the {len(s["issues"])} raw review flags are contradicted by follow-up evidence checks. ')
    parts+=[e(current['status'])+'. '+e(current['next_step'])+' <a href="#review-notes">See review notes</a>.</div></header><div class="toolbar"><input id="search" type="search" placeholder="Find a strain, dataset or figure…" aria-label="Search figures"><select id="group-filter" aria-label="Figure group"><option value="all">All figures</option>']
    for q,label,_ in GROUPS:
        if grouped[q]:parts.append(f'<option value="{q}">{e(label)}</option>')
    parts+=['</select><button id="reset">Show all</button></div>',f'<p id="count" class="small muted" aria-live="polite">{len(figures)} of {len(figures)} figures shown</p><p id="empty" hidden>No figures match. Choose Show all to reset.</p>']
    for q,label,purpose in GROUPS:
        if not grouped[q]:continue
        parts.append(f'<section id="{q}" class="group" data-section><div class="group-heading"><h2>{e(label)}</h2><span class="badge">{len(grouped[q])} figures</span></div>')
        for f in grouped[q]:
            fid=f['figure_id'];recipe=f.get('render_recipe',{});audit=f.get('audit',{});facts=f.get('render_facts',{})
            title=recipe.get('title') or fid
            index=recipe.get('figure_index') or facts.get('figure_index') or fid
            datasets=sorted({r['dataset_id'] for r in f.get('plotted_rows',[])+f.get('context_rows',[])})
            destinations=sorted({d for tid in datasets for d in routing.get(tid,{}).get('destinations',[])})
            roles=sorted({routing.get(tid,{}).get('role','') for tid in datasets}- {''})
            scales=audit.get('rendered_scales',{})
            x=recipe.get('x_label') or facts.get('x_label','See source axis')
            y=recipe.get('y_label') or facts.get('y_label','See source axis')
            reading=f'X: {x} ({scales.get("x",recipe.get("x_scale","linear"))}). Y: {y} ({scales.get("y",recipe.get("y_scale","linear"))}).'
            caption=f.get('caption','')
            # Quote one existing sentence; never invent curve interpretation.
            note=next((v.strip() for v in caption.split('. ') if v.strip()),'See the original source caption below.')
            if len(note)>260:note='Source-specific limitations remain; see the complete original caption below.'
            if note and note[-1] not in '.!?':note+='.'
            uri=Path(f['image_ref']['path']).as_uri()
            search=' '.join([fid,title,caption,' '.join(datasets)]).lower()
            parts.append(f'<article class="figure" id="figure-{e(fid)}" data-figure="{e(fid)}" data-group="{q}" data-search="{e(search)}"><div class="figure-head"><span class="index">{e(index)}</span><h3>{e(title)}</h3><p class="metadata">{e(" · ".join(datasets))} · Next: {e(" / ".join(destinations) or "See routing ledger")} · {e(" / ".join(roles))}</p></div><a href="{e(uri)}" target="_blank" rel="noopener" aria-label="Open full-size {e(index)}"><img loading="lazy" src="{e(uri)}" alt="{e(index+" — "+title)}"></a><div class="explanation"><p><strong>Purpose.</strong> {e(purpose)}</p><p><strong>Read.</strong> {e(reading)}</p><p><strong>Note.</strong> {e(note)}</p><details class="full-notes"><summary>Original caption & source details</summary><p class="caption">{e(caption)}</p><p>Figure ID: {e(fid)} · {len(f.get("plotted_rows",[]))} plotted-row records. Source values and statuses are retained in the bound evidence package.</p><p>SHA-256: {e(f["image_ref"]["sha256"])}</p><div class="links"><a href="{e(uri)}" target="_blank" rel="noopener">Open original image</a><a href="handoff_context.json">Bound source and plot evidence</a><a href="dataset_routing.json">Dataset routing</a></div></details></div></article>')
        parts.append('</section>')
    parts.append('<section id="review-notes"><details class="box"><summary>Independent review & follow-up checks</summary><p>Raw ER result: '+e(packet['review_decision'])+'. Review opinions below are retained, including any contradicted by follow-up checks. No automatic approval.</p>')
    for issue in s['issues']:
        flag='Contradicted by follow-up evidence check; original opinion retained.' if issue['issue_id'] in contradictions else 'Reviewer-reported issue; check against the exact figure and source.'
        parts.append(f'<div class="issue"><span class="flag">{e(flag)}</span><p><b>{e(issue["issue_id"])} · {e(issue["affected_artifact"])}</b></p><p>{e(issue["evidence"])}</p><p>Suggested action: {e(issue["smallest_correction"])}</p></div>')
    parts.append('<details class="full-notes"><summary>Review scope exclusions</summary><ul>'+''.join('<li>'+e(x)+'</li>' for x in s['unreviewed_items'])+'</ul></details><div class="links"><a href="independent_review.json">Original ER</a>')
    for name,label in [('review_claim_fact_check.json','Numeric fact checks'),('post_run_review_notes.json','Follow-up review notes')]:
        if (root/name).exists():parts.append(f'<a href="{name}">{label}</a>')
    parts.append('</div></details></section><section id="handoff"><details class="box"><summary>Handoff summary & remaining limitations</summary>')
    for finding in s['findings']:
        parts.append('<p>'+e(finding['observation'])+'</p><p class="muted">'+e(finding['downstream_implication'])+'</p>')
    parts.append('<ul>'+''.join('<li>'+e(x)+'</li>' for x in s['limitations']+s['open_items'])+'</ul></details><div class="box"><h2>Human review, then PK / PD</h2><p>'+e(current['next_step'])+'</p><div class="links"><a href="human_review.json">Review packet</a><a href="branch_drafts.json">Branch drafts</a><a href="human_decision.template.json">Pending decision template</a></div></div></section><footer>Existing images and data reused unchanged. Figure explanations are deterministic display guidance, not new model conclusions.<details><summary>Packet identity</summary><p>'+e(packet['content_sha256'])+'</p></details></footer></main></div><script>'+JS+'</script></body></html>')
    from .eda_review_portal import build as build_portal
    build_portal(root, packet, figures, ''.join(parts), GROUPS)
