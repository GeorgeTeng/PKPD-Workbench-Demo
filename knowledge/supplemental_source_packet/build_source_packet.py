"""Build an isolated, source-hash-bound packet from already downloaded originals."""
import copy
import datetime
import hashlib
import json
import re
import shutil
from pathlib import Path

from lxml import etree, html

BASE = Path(__file__).resolve().parents[2]
SRC = BASE / "round9_external_sources"
OUT = Path(__file__).resolve().parent
FILES = OUT / "source_files"
FILES.mkdir(parents=True, exist_ok=True)
REG = json.loads((BASE / "download/d28181c50c011c0a/knowledge/source_registry.json").read_text(encoding="utf-8"))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def norm(s):
    return " ".join(s.split())

def no_formula_text(node):
    def walk(el):
        tag = etree.QName(el).localname.lower() if isinstance(el.tag, str) else ""
        cls = (el.get("class") or "").lower()
        if tag in {"math", "disp-formula", "inline-formula"} or "disp-formula" in cls or "inline-formula" in cls:
            return " [FORMULA OMITTED: inspect original MathML] "
        ret = el.text or ""
        for child in el:
            ret += walk(child)
            ret += child.tail or ""
        return ret
    return norm(walk(node))

def windows(s, limit=1700, overlap=100):
    if len(s) <= limit:
        return [(0, len(s), s)]
    out, start = [], 0
    while start < len(s):
        stop = min(len(s), start + limit)
        if stop < len(s):
            j = s.rfind(". ", start + 950, stop)
            if j > start + 950:
                stop = j + 1
        out.append((start, stop, s[start:stop]))
        if stop == len(s):
            break
        start = max(start + 1, stop - overlap)
    return out

specs = [
    {
        "id":"EXTA001", "file":"EXTA001_PMC5412686.xml", "title":"A comparative evaluation of models to predict human intestinal metabolism from nonclinical data",
        "doi":"10.1002/bdd.2068", "year":2017, "url":"https://pmc.ncbi.nlm.nih.gov/articles/PMC5412686/",
        "document_type":"original comparative method study", "stage":["translation","human_simulation"],
        "inclusion_tier":"conditional_method_only_if_oral_route_relevant",
        "applicability_trigger":"An oral animal-to-human exposure scenario is explicitly requested and absorption/first-pass inputs can be qualified.",
        "sections":["bdd2068-sec-0001","bdd2068-sec-0012","bdd2068-sec-0013","bdd2068-sec-0021","bdd2068-sec-0029","bdd2068-sec-0030"],
        "key_locators":["JATS equation bdd2068-disp-0001 (F=Fa*Fg*Fh)","JATS bdd2068-sec-0013 (indirect human Fg assumptions)","JATS bdd2068-sec-0029 (deconvolution uncertainty)","JATS bdd2068-sec-0030 (rat-human intestinal extraction limitations)"],
        "knowledge_added":"For an oral translation branch, distinguish absorption Fa, intestinal escape Fg, hepatic escape Fh and apparent oral clearance CL/F; identify IV-plus-oral deconvolution assumptions and uncertainty. Rat Fg is only a screening input in this study.",
        "affected_cards_or_G":["G08","round3_H03:K02","round2_T01:K02"],
        "limitations":"Original 31-drug CYP-mediated comparison, not a universal oral model winner. Human IV+oral data used in paper are not available for the target drug; do not transfer study estimates. Fraction-bearing formulas require original MathML."
    },
    {
        "id":"EXTA003", "file":"EXTA003_PMC1884440.html", "title":"Assessment of the relative in vivo potency of the hydroxylated metabolite of darifenacin in its ability to decrease salivary flow using pooled population pharmacokinetic-pharmacodynamic data",
        "doi":"10.1046/j.1365-2125.2003.01988.x", "year":2004, "url":"https://pmc.ncbi.nlm.nih.gov/articles/PMC1884440/",
        "document_type":"original pooled population PK/PD study", "stage":["pkpd","translation"],
        "inclusion_tier":"conditional_source_case_only_if_active_metabolite_relevant",
        "applicability_trigger":"Measured parent/metabolite PK and evidence that the metabolite may contribute to the studied PD endpoint exist.",
        "sections":["sec7","sec9","sec10","sec18","sec21","sec22","sec24"],
        "key_locators":["HTML sec9 (parent/metabolite PK and fraction-metabolized/relative-bioavailability confounding)","HTML sec10 and disp-formula1 MathML M1 (joint effect concentration)","HTML sec21 (relative-potency profile)","HTML sec22 (unbound fraction correction)"],
        "knowledge_added":"Conditional joint parent/active-metabolite PK/PD construction with observed concentrations, delay-model alternatives, potency-identifiability and binding-basis checks.",
        "affected_cards_or_G":["G06","G07","G08","source_REF_015:K03"],
        "limitations":"Darifenacin-specific human case and salivary-flow endpoint; no potency estimate, formation fraction, or efficacy result may be transferred to another drug. Some PK formation and bioavailability factors were confounded and fixed by source assumptions."
    },
    {
        "id":"EXTB003", "file":"EXTB003_EMA_first_human.pdf", "pages":"EXTB003_pages.json", "title":"Guideline on strategies to identify and mitigate risks for first-in-human and early clinical trials with investigational medicinal products",
        "document_reference":"EMEA/CHMP/SWP/28367/07 Rev. 1", "year":2017,
        "url":"https://www.ema.europa.eu/en/documents/scientific-guideline/guideline-strategies-identify-and-mitigate-risks-first-human-and-early-clinical-trials-investigational-medicinal-products-revision-1_en.pdf",
        "document_type":"official EMA guideline", "stage":["translation","human_simulation"],
        "inclusion_tier":"optional_reference_for_exposure_interpretation_only",
        "applicability_trigger":"Explaining that a prospective human exposure scenario does not itself establish first-in-human clinical suitability; do not activate a clinical starting-dose workflow.",
        "selected_pdf_pages":[10,11],
        "key_locators":["PDF p10 section 6.4 (PK/TK evidence and dose-response context)","PDF p11 section 7.1 (anticipated human exposure versus observed animal effects and uncertainty)"],
        "knowledge_added":"Optional boundary for interpreting prospective human exposure scenarios: anticipated human exposure, nonclinical effect/toxicity exposure, and uncertainty require separate evidence. This source adds no current NOAEL/HED/MRSD input requirement.",
        "affected_cards_or_G":["G10","module_human_simulation:K04","round3_H04:K02"],
        "limitations":"Guideline concerns early clinical risk mitigation, while the current workflow only simulates prospective PK/PD scenarios. No target-drug safety package or clinical dose is supplied; this packet excludes starting-dose algorithm sections. Version/date retained without claiming current supersession status."
    },
]

for s in specs:
    source = SRC / s["file"]
    dest = FILES / s["file"]
    shutil.copyfile(source, dest)
    assert sha(source) == sha(dest)
    s["sha256"] = sha(dest)
    s["bytes"] = dest.stat().st_size
    s["local_path"] = str(dest.relative_to(OUT)).replace("\\", "/")
    s["access_level"] = "full_text"
    s["source_status"] = "EXTERNAL_SOURCE_NOT_PROJECT_POLICY"
    s["default_core_ingest"] = False
    s["qwen_use"] = "Triggered bounded source-review packet only; preserve source case and applicability conditions."
    url = s["url"].rstrip("/").lower()
    s["duplicate_check"] = {
        "registry_entries_checked":len(REG),
        "same_url_ids":[x["id"] for x in REG if (x.get("url") or "").rstrip("/").lower()==url],
        "same_sha256_ids":[x["id"] for x in REG if x.get("sha256")==s["sha256"]],
        "same_normalized_title_ids":[x["id"] for x in REG if norm((x.get("title") or "").lower())==norm(s["title"].lower())],
    }
    assert not any(s["duplicate_check"][k] for k in ("same_url_ids","same_sha256_ids","same_normalized_title_ids"))

chunks = []
for s in specs:
    src_id = s["id"]
    if s["file"].endswith(".xml"):
        tree = etree.parse(str(FILES/s["file"]))
        for sid in s["sections"]:
            sec = tree.xpath('//sec[@id="'+sid+'"]')[0]
            title = norm(" ".join(sec.xpath('./title//text()')))
            paras = [no_formula_text(p) for p in sec.xpath('./p')]
            body = norm(title + " " + " ".join(paras))
            for start,stop,frag in windows(body):
                chunks.append({"source_id":src_id,"locator":f"JATS sec {sid} ({title}); normalized non-formula text chars {start}:{stop}","text":frag,"math_boundary":"MathML formulas deliberately omitted from flattened text; inspect original source."})
    elif s["file"].endswith(".html"):
        tree = html.parse(str(FILES/s["file"]))
        for sid in s["sections"]:
            sec = tree.xpath('//section[@id="'+sid+'"]')[0]
            title = norm(" ".join(sec.xpath('./h2[1]//text()|./h3[1]//text()')))
            paras = [no_formula_text(p) for p in sec.xpath('./p')]
            body = norm(title + " " + " ".join(paras))
            for start,stop,frag in windows(body):
                chunks.append({"source_id":src_id,"locator":f"HTML section {sid} ({title}); normalized non-formula text chars {start}:{stop}","text":frag,"math_boundary":"MathML formulas deliberately omitted from flattened text; inspect original source."})
    else:
        pages = json.loads((SRC/s["pages"]).read_text(encoding="utf-8"))
        for page in s["selected_pdf_pages"]:
            text = norm(next(x["text"] for x in pages if x["pdf_page"]==page))
            for start,stop,frag in windows(text):
                chunks.append({"source_id":src_id,"locator":f"Original PDF page {page}; normalized extracted page text chars {start}:{stop}","text":frag,"math_boundary":"PDF text extraction only; verify any formula/table against original page."})

for src_id in {s["id"] for s in specs}:
    for n,c in enumerate((x for x in chunks if x["source_id"]==src_id),1):
        c["id"] = f"{src_id}:{n:04d}"
        c["sha256"] = hashlib.sha256(c["text"].encode("utf-8")).hexdigest()
        c["source_sha256"] = next(s["sha256"] for s in specs if s["id"]==src_id)

# Only two short equations are transcribed here, each unambiguous in its
# source MathML. All fraction-bearing formulas remain in the original files.
equations = [
    {"source_id":"EXTA001","locator":"JATS displayed formula bdd2068-disp-0001, original MathML","text":"F = Fa * Fg * Fh","note":"Product only; each factor still needs source definitions and assumptions."},
    {"source_id":"EXTA003","locator":"HTML sec10, displayed formula disp-formula1, MathML M1","text":"Ce = Cd + Cm * Rel.Pot.","note":"Source-case assumed additive concentration-equivalent potency; not a universal parent/metabolite interaction law."},
]
for n,e in enumerate(equations,1):
    e["id"] = f"{e['source_id']}:MATH01"
    e["sha256"] = hashlib.sha256(e["text"].encode("utf-8")).hexdigest()
    e["source_sha256"] = next(s["sha256"] for s in specs if s["id"]==e["source_id"])

with (OUT/"chunks.jsonl").open("w",encoding="utf-8",newline="\n") as fh:
    for c in chunks:
        fh.write(json.dumps(c,ensure_ascii=False)+"\n")
with (OUT/"verified_equations.jsonl").open("w",encoding="utf-8",newline="\n") as fh:
    for e in equations:
        fh.write(json.dumps(e,ensure_ascii=False)+"\n")

excluded = [
    {"ids":["GEN001","GEN002","GEN003","EDA001"],"reason":"Already present in the 77-source registry, with extracted chunks; do not duplicate."},
    {"ids":["EXTA002"],"reason":"Downloaded HTML verifies only abstract and link, not article body; no full-text chunk packet."},
    {"ids":["EXTB001","EXTB002"],"reason":"Original TMDD papers are high quality but apply to a conditional saturable biologic/target-mediated branch, not a presently identified gap in the six-stage core workflow."},
    {"ids":["EXTB004"],"reason":"Official FDA MRSD guidance is high quality, but its NOAEL/HED/starting-dose algorithm would create a new clinical safety workflow not requested for current prospective human PK/PD scenarios; retain as candidate only."},
]
manifest = {
    "status":"READY_FOR_BOUNDED_QWEN_REVIEW_NOT_APPROVED_POLICY",
    "created_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "selection_basis":"Reuse only already downloaded original/official sources for conditional oral and metabolite branches plus an optional exposure-interpretation boundary in EDA -> animal PK -> PKPD -> translation -> prospective human scenarios -> conditional PTA; no new network retrieval or clinical-starting-dose workflow.",
    "existing_registry_count":len(REG),
    "default_core_ingest":False,
    "selected":specs,
    "excluded":excluded,
    "packet_files":{"chunks_jsonl":"chunks.jsonl","verified_equations_jsonl":"verified_equations.jsonl","source_files_dir":"source_files"},
    "chunk_count":len(chunks),
    "verified_equation_count":len(equations),
    "extraction_limitations":["EXTA001 and EXTA003 flat text deliberately omits MathML; inspect original for any formula beyond two separately verified short expressions.","PDF page text is extracted, not visual validation of tables/equations.","New sources are conditional evidence candidates, not approved method policy or target-drug data; none creates a mandatory metabolite, oral, or FIH clinical-starting-dose stage."],
}
(OUT/"SELECTED_SOURCES.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps({"selected":[s["id"] for s in specs],"chunks":len(chunks),"equations":len(equations),"output":str(OUT)},ensure_ascii=False))
