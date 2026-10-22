"""Local, presentation-only EDA reader. Does not edit evidence or grant approval."""
import html
from pathlib import Path
from .common import read_json

TITLES={
    "F_PK_SHAPE_MOUSE":"Mouse pulmonary profiles",
    "F_PK_SHAPE_RAT_RABBIT_TISSUE":"Rat, rabbit & tissue observations",
    "F_PK_SC_DOSE_AND_VARIABILITY":"Mouse dose profiles & sampled peaks",
    "F_PD_EFFECT_RANGE":"PD response across strains",
    "F_INDEX_PANELS":"Exposure–response index panels",
    "F_TIMEKILL":"Time-kill patterns",
    "F_CONTEXT_MIC_BINDING":"MIC distribution & protein binding",
}

CSS=r"""
:root{--ink:#172d39;--muted:#526875;--teal:#146956;--line:#dce4e4;--paper:#fff;--bg:#f4f6f4;--amber:#805b16}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:24px}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.65 "Segoe UI",Arial,sans-serif}
a{color:var(--teal);text-underline-offset:4px}button,input{font:inherit}
a:focus-visible,button:focus-visible,summary:focus-visible,input:focus-visible{outline:3px solid #438cba;outline-offset:4px}
.skip{position:fixed;top:-100px;left:20px;padding:12px;background:white;z-index:10}.skip:focus{top:12px}
.layout{max-width:1500px;margin:auto;display:grid;grid-template-columns:220px minmax(0,1fr);gap:48px;padding:36px 44px 60px}
aside{position:sticky;top:36px;align-self:start}.brand{font-size:14px;letter-spacing:.16em;text-transform:uppercase;font-weight:750}
.brand span{display:block;font-size:12px;color:var(--muted);letter-spacing:.06em;margin-top:4px;font-weight:400}
nav{margin:42px 0}nav a{display:flex;gap:14px;text-decoration:none;padding:11px 12px;margin:4px 0;border-radius:8px;color:var(--muted);font-size:14px}
nav a:hover{background:#e6eeeb;color:var(--teal)}nav b{font-size:11px;line-height:24px;color:#718b90}
.sidebar-note{border-top:1px solid var(--line);padding-top:20px;font-size:12px;color:var(--muted)}
main{min-width:0;max-width:1120px}.eyebrow{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:.15em;color:var(--teal)}
h1{font-size:clamp(32px,4vw,48px);letter-spacing:-.04em;line-height:1.12;margin:12px 0 16px;font-weight:650}
h2{font-size:25px;line-height:1.25;letter-spacing:-.025em;margin:0}h3{font-size:18px;line-height:1.4;margin:0}
p{margin:10px 0}.lead{max-width:680px;font-size:17px;color:var(--muted)}
.hero{margin-bottom:34px}.hero-top,.section-head{display:flex;justify-content:space-between;align-items:flex-start;gap:20px}
.section-head{align-items:center;margin-bottom:20px}.section-head p{margin:6px 0 0;color:var(--muted);font-size:14px}
.pill{display:inline-block;white-space:nowrap;font-size:12px;font-weight:650;border-radius:30px;padding:5px 11px;line-height:1.6}
.green{background:#e2f0e8;color:#18573f}.amber{background:#fff0d4;color:var(--amber)}.neutral{background:#eaf0f1;color:var(--muted)}
.status-panel{background:var(--paper);border:1px solid var(--line);border-radius:16px;overflow:hidden;margin-top:25px}
.status-top{padding:22px 26px;display:flex;align-items:center;justify-content:space-between;gap:20px}
.status-top strong{display:block;font-size:18px}.status-top p{color:var(--muted);font-size:14px;margin:3px 0 0}
.steps{display:grid;grid-template-columns:repeat(4,1fr);border-top:1px solid var(--line);background:#fbfcfb;padding:18px 26px;gap:14px;font-size:12px;color:var(--muted)}
.step span{display:block;font-size:13px;font-weight:650;color:var(--ink)}.step.current span{color:var(--amber)}
.stats{display:flex;gap:30px;margin-top:20px;color:var(--muted);font-size:13px}.stats strong{font-size:20px;color:var(--ink);margin-right:6px;font-weight:650}
.section{margin:42px 0}.finding-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
.finding{background:var(--paper);border:1px solid var(--line);border-radius:13px;padding:24px;display:flex;flex-direction:column;min-width:0}
.finding-head{display:flex;gap:12px;align-items:flex-start;margin-bottom:12px}
.number{font-size:12px;font-variant-numeric:tabular-nums;color:#65817d;padding-top:4px}
.finding .observation{font-size:16px;line-height:1.65;margin:0 0 18px}
.implication{border-left:3px solid #bdd9ce;padding-left:13px;margin-top:auto;font-size:14px;color:var(--muted)}
.label{display:block;font-size:10px;letter-spacing:.12em;text-transform:uppercase;font-weight:750;color:var(--teal);margin-bottom:5px}
details.evidence{margin-top:18px;padding-top:12px;border-top:1px solid #eef1f1;font-size:13px;color:var(--muted)}
summary{cursor:pointer}summary:hover{color:var(--teal)}.evidence p{overflow-wrap:anywhere}
.source-id{font:11px/1.6 Consolas,monospace;color:#6b818c}.evidence a{font-size:12px}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.panel{border:1px solid var(--line);background:white;border-radius:13px;padding:25px;min-width:0}
.panel.soft{background:#f9f5eb;border-color:#e9dfc7}.panel h3{margin-bottom:15px}
.clean-list{padding-left:19px;margin:0;color:var(--muted);font-size:14px}.clean-list li{margin:0 0 13px;padding-left:5px}.clean-list li:last-child{margin:0}
.toolbar{display:flex;justify-content:space-between;flex-wrap:wrap;gap:14px;margin:20px 0 15px}
.filters{display:flex;gap:5px;flex-wrap:wrap}.filters button{border:1px solid var(--line);background:white;border-radius:24px;padding:7px 17px;font-size:13px;color:var(--muted);cursor:pointer}
.filters button[aria-pressed=true]{background:var(--ink);color:white;border-color:var(--ink)}
.search{background:white;border:1px solid var(--line);border-radius:8px;padding:8px 12px;width:250px;max-width:100%;font-size:13px}
.figure-count{font-size:12px;color:var(--muted);margin-bottom:15px}
.figure-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;align-items:start}
.figure-card{background:white;border:1px solid var(--line);border-radius:12px;overflow:hidden;min-width:0}
.figure-card summary{list-style:none;padding:12px}.figure-card summary::-webkit-details-marker{display:none}
.figure-card summary img{display:block;height:155px;width:100%;object-fit:contain;background:white;border-bottom:1px solid #eff2f2;padding-bottom:8px;margin-bottom:10px}
.figure-title{font-size:13px;font-weight:650;line-height:1.4;display:block}.figure-sub{display:block;color:var(--muted);font-size:11px;margin-top:5px;overflow-wrap:anywhere}
.figure-card[open]{grid-column:1/-1}.figure-card[open] summary img{display:none}.figure-card[open] summary{border-bottom:1px solid var(--line);padding:16px 22px}
.figure-detail{padding:20px}.figure-detail img{width:100%;height:auto;display:block}.caption{font-size:13px;line-height:1.7;color:var(--muted);max-width:850px;white-space:pre-line}
.figure-detail a{font-size:13px}.empty{padding:25px;background:white;border-radius:10px}
.branch-title{display:flex;justify-content:space-between;align-items:center;margin-bottom:12px}
.branch p{font-size:14px;color:var(--muted)}.review-note{padding:20px 24px;border-radius:12px;background:#e9f0ed;margin-top:18px;font-size:14px}
.downloads{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}.downloads a{background:white;border:1px solid var(--line);padding:10px 15px;border-radius:8px;font-size:13px;text-decoration:none}
footer{padding-top:25px;border-top:1px solid var(--line);font-size:12px;color:var(--muted);overflow-wrap:anywhere}
[hidden]{display:none!important}
@media(min-width:1200px){.finding:last-child:nth-child(odd){grid-column:1/-1}.finding:last-child:nth-child(odd) .observation{max-width:850px}}
@media(max-width:1000px){.layout{grid-template-columns:160px minmax(0,1fr);gap:25px;padding:26px 24px}.figure-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.finding-grid,.two-col{grid-template-columns:1fr}}
@media(max-width:700px){.layout{display:block;padding:22px 18px}aside{position:static}.brand span,.sidebar-note{display:none}nav{margin:18px 0 28px;display:flex;gap:5px;overflow-x:auto}nav a{padding:7px 10px;white-space:nowrap}nav b{display:none}.hero-top{display:block}.hero-top>.pill{margin-top:8px}.status-top{display:block;padding:20px}.status-top>.pill{margin-top:12px}.steps{grid-template-columns:repeat(2,1fr);padding:18px 20px}.stats{gap:18px;flex-wrap:wrap}.figure-grid{grid-template-columns:1fr}.finding{padding:21px}.section{margin:34px 0}.search{width:100%}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
@media print{body{background:white}.layout{display:block;padding:0}aside,.toolbar,.skip{display:none}.section{break-inside:avoid}.finding-grid,.two-col{display:block}.finding,.panel{margin-bottom:12px;break-inside:avoid}.figure-grid{grid-template-columns:repeat(2,1fr)}.figure-card[hidden]{display:block!important}.figure-card{break-inside:avoid}a{color:inherit}.hero{margin-bottom:15px}h1{font-size:32px}}
"""

JS=r"""
const buttons = [...document.querySelectorAll('[data-filter]')];
const cards = [...document.querySelectorAll('[data-figure]')];
const search = document.getElementById('figure-search');
let active = 'all';
function filterFigures(){
  const query=search.value.trim().toLowerCase(); let n=0;
  for(const card of cards){
    const show=(active==='all'||card.dataset.group.split(' ').includes(active)) &&
       card.dataset.search.includes(query);
    card.hidden=!show;if(show)n++;
  }
  document.getElementById('figure-count').textContent=`${n} of ${cards.length} figures shown`;
  document.getElementById('empty-figures').hidden=n!==0;
}
for(const button of buttons)button.addEventListener('click',()=>{
  active=button.dataset.filter;
  buttons.forEach(b=>b.setAttribute('aria-pressed',String(b===button)));
  filterFigures();
});
search.addEventListener('input',filterFigures);
document.querySelectorAll('[data-open-figure]').forEach(link=>link.addEventListener('click',()=>{
  active='all';search.value='';buttons.forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.filter==='all')));
  filterFigures();document.getElementById(link.dataset.openFigure).open=true;
}));
"""

def render_legacy(root,p,figures):
    root=Path(root);e=html.escape
    summary=p["summary"];passed=p["review_decision"]=="PASS"
    pending=p["status"]=="WAITING_FOR_HUMAN_REVIEW"
    state="Awaiting human review" if pending else "Review required"
    tables=read_json(p["bindings"]["source_tables"]["path"])
    figure_targets={f["figure_id"]:"figure-"+str(i+1) for i,f in enumerate(figures)}
    parts=['<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<title>EDA review · PK/PD Workbench</title><style>'+CSS+'</style></head><body>',
        '<a class="skip" href="#main">Skip to review</a><div class="layout"><aside>',
        '<div class="brand">PK/PD<span>Research workbench</span></div><nav aria-label="Review sections">']
    for i,(target,label) in enumerate([("overview","Overview"),("findings","Key findings"),("scope","Limits & open items"),("figures","Figure library"),("handoff","Human review")],1):
        parts.append(f'<a href="#{target}"><b>0{i}</b>{label}</a>')
    parts+=['</nav><p class="sidebar-note">Descriptive EDA<br>Animal & in-vitro evidence<br><br>Model design follows in the PK / PD branches.</p></aside><main id="main">',
        '<header class="hero" id="overview"><div class="hero-top"><div><div class="eyebrow">Evidence review / EDA</div>',
        '<h1>What the data shows.</h1><p class="lead">A concise review of the observed patterns, their limits, and the evidence to carry forward.</p></div>',
        '<span class="pill amber">'+e(state)+'</span></div><div class="status-panel"><div class="status-top"><div><strong>Independent review '+('passed' if passed else 'pending / requires attention')+'</strong>',
        '<p>'+('No new corrections requested. Existing data limitations remain.' if passed else 'See outstanding review items below before handoff.')+'</p></div>',
        '<span class="pill '+('green' if passed else 'amber')+'">ER · '+e(p["review_decision"])+'</span></div>',
        '<div class="steps"><div class="step"><span>01 · EDA package</span>Figures & explanations</div><div class="step"><span>02 · Independent review</span>'+e(p["review_decision"])+'</div>',
        '<div class="step current"><span>03 · Human review</span>Awaiting your decision</div><div class="step"><span>04 · PK / PD intake</span>Locked until approval</div></div></div>',
        f'<div class="stats"><span><strong>{len(tables)}</strong>datasets</span><span><strong>{len(figures)}</strong>figures</span><span><strong>{len(summary["findings"])}</strong>findings</span></div></header>',
        '<section class="section" id="findings"><div class="section-head"><div><h2>Key findings</h2><p>Observation first. Interpretation limits directly beneath.</p></div></div><div class="finding-grid">']
    for i,f in enumerate(summary["findings"],1):
        title=TITLES.get(f["finding_id"],f["finding_id"].replace("_"," ").title())
        parts+=[f'<article class="finding"><div class="finding-head"><span class="number">{i:02}</span><h3>{e(title)}</h3></div>',
            '<p class="observation">'+e(f["observation"])+'</p><div class="implication"><span class="label">Meaning & limit</span>'+e(f["downstream_implication"])+'</div>',
            '<details class="evidence"><summary>View evidence & source notes</summary><p class="source-id">'+e(f["finding_id"])+'</p>']
        links=[]
        for ref in f["artifact_refs"]:
            if ref in figure_targets:
                target=figure_targets[ref]
                links.append(f'<a href="#{target}" data-open-figure="{target}">{e(ref)}</a>')
            else:links.append(e(ref))
        parts+=['<p><b>Artifacts</b><br>'+' · '.join(links)+'</p><p><b>Record anchors</b><br>'+e(', '.join(f["record_scope"]))+'</p>']
        if f.get("anomaly_assessment"):
            a=f["anomaly_assessment"]
            parts+=['<p><b>Source-check note</b><br>'+e(a["observation"])+'</p><p>'+e(a["recommended_action"])+'</p>']
        parts+=['</details></article>']
    parts+=['</div></section><section class="section" id="scope"><div class="section-head"><div><h2>What still needs attention</h2><p>Carry these limitations forward to the relevant analysis.</p></div></div><div class="two-col">']
    for key,title,klass in [("open_items","Open items","soft"),("limitations","Interpretation boundaries","")]:
        parts+=['<div class="panel '+klass+'"><h3>'+title+'</h3><ul class="clean-list">'+''.join('<li>'+e(x)+'</li>' for x in summary[key])+'</ul></div>']
    parts+=['</div>']
    if summary["issues"] or summary["unreviewed_items"]:
        parts+=['<div class="panel" style="margin-top:18px"><h3>Outstanding review items</h3>']
        for issue in summary["issues"]:
            parts+=['<p><b>'+e(issue["affected_artifact"])+'</b>: '+e(issue["evidence"])+'</p><p>'+e(issue["smallest_correction"])+'</p>']
        parts+=['<ul class="clean-list">'+''.join('<li>'+e(x)+'</li>' for x in summary["unreviewed_items"])+'</ul></div>']
    parts+=['</section><section class="section" id="figures"><div class="section-head"><div><h2>Figure library</h2><p>Select a figure to expand the original image and its full caption.</p></div></div>',
        '<div class="toolbar"><div class="filters" role="group" aria-label="Filter figures">']
    for key,label in [("all","All figures"),("PK","PK"),("PD","PD"),("context","Context")]:
        parts.append('<button type="button" data-filter="'+key+'" aria-pressed="'+str(key=="all").lower()+'">'+label+'</button>')
    parts+=['</div><input class="search" id="figure-search" type="search" aria-label="Search figures by name or caption" placeholder="Search name or caption…"></div>',
        f'<div class="figure-count" id="figure-count" aria-live="polite">{len(figures)} of {len(figures)} figures shown</div><div class="figure-grid">']
    for f in figures:
        qs=set(f["analysis_ids"]);groups=[]
        if qs & {"Q_PK_SHAPE","Q_PK_VARIABILITY"}:groups.append("PK")
        if qs & {"Q_PD_EFFECT","Q_INDEX","Q_TIMEKILL"}:groups.append("PD")
        if "Q_CONTEXT" in qs or not groups:groups.append("context")
        fid=f["figure_id"];uri=e(Path(f["image_ref"]["path"]).as_uri(),quote=True)
        title=fid.replace("__DEFAULT_LOG10"," · semilog").replace("_"," ").title()
        search=e((fid+" "+f["caption"]).lower(),quote=True)
        parts+=[f'<details class="figure-card" id="{figure_targets[fid]}" data-figure data-group="{" ".join(groups)}" data-search="{search}"><summary>',
            f'<img loading="lazy" src="{uri}" alt="{e(title,quote=True)} preview"><span class="figure-title">{e(title)}</span>',
            '<span class="figure-sub">'+e(' / '.join(groups))+' · Expand figure</span></summary><div class="figure-detail">',
            f'<img loading="lazy" src="{uri}" alt="{e(fid,quote=True)}"><p class="source-id">{e(fid)}</p>',
            '<p class="caption">'+e(f["caption"])+'</p><a href="'+uri+'" target="_blank" rel="noopener">Open original image ↗</a></div></details>']
    parts+=['</div><p class="empty" id="empty-figures" hidden>No figures match this filter. Try another name or choose All figures.</p></section>',
        '<section class="section" id="handoff"><div class="section-head"><div><h2>Your review, then handoff</h2><p>Confirm the descriptive package and its remaining scope before releasing the two branches.</p></div></div><div class="two-col">']
    for branch,title in [("PK","Animal pharmacokinetics"),("PD","Pharmacodynamics")]:
        parts+=['<div class="panel branch"><div class="branch-title"><h3>'+branch+'</h3><span class="pill neutral">Awaiting approval</span></div><p><b>'+title+'</b></p><p>Receives its scoped datasets, figures, findings, Rules and unresolved items.</p><p>Next: qualify the required inputs, then design and fit models.</p></div>']
    parts+=['</div><div class="review-note"><b>Review scope</b><br>Inspect the figures, confirm the explanations, and acknowledge the remaining limitations. ER PASS is not human approval or modeling readiness. No model execution has started.</div>',
        '<div class="downloads"><a href="human_review.json">Full review packet ↗</a><a href="independent_review.json">ER result ↗</a><a href="branch_drafts.json">PK / PD handoffs ↗</a><a href="human_decision.template.json">Decision template ↗</a></div>',
        '<p style="font-size:13px;color:var(--muted)">This page presents the evidence. Opening a file or expanding a figure does not submit an approval.</p></section>',
        '<footer><details><summary>Traceability & packet identity</summary><p>Status: '+e(p["status"])+'</p><p>Packet SHA-256<br><span class="source-id">'+e(p["content_sha256"])+'</span></p></details></footer>',
        '</main></div><script>'+JS+'</script></body></html>']
    (root/"human_review.html").write_text(''.join(parts),encoding="utf8")


def render(root,p,figures):
    from .eda_figure_review_ui import render as figure_review
    return figure_review(root,p,figures)
