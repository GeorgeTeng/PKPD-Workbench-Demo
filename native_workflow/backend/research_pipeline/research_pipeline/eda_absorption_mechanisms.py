"""Generate the English modeling handoff from the completed r4.3 study boards."""
import hashlib
import json
from html import escape
from pathlib import Path

from .eda_absorption_assessment import assess
from .eda_absorption_reader import READINGS, alternatives, modeling_check
from .eda_absorption_reader_evidence import support_text


CATALOG_FILE = "absorption_mechanisms_r43.json"
FAMILIES = {
    "onset": "Onset and delay", "shape": "Input shape and release",
    "multiphase": "Shoulders, troughs and secondary peaks", "tail": "Terminal decline and disposition",
    "dose": "Dose dependence", "extent": "Extent of systemic availability",
    "condition": "Changes between conditions or occasions", "baseline": "Observation and dosing alternatives",
}
DME = {
    "enterohepatic": "metabolism and elimination", "flip_flop": "distribution and elimination",
    "ongoing_input": "distribution and elimination", "multicompartment": "distribution",
    "binding_distribution": "distribution and protein binding", "changing_clearance": "elimination",
    "nonlinear_elimination": "elimination", "parallel_linear_saturable_elimination": "elimination",
    "cl_v_coscaling": "distribution and elimination", "first_pass_saturation": "metabolism",
    "shared_one_compartment": "distribution and elimination", "mixed_rate_extent": "distribution, metabolism and elimination",
}
GUIDE = ("Choose a study and open a candidate to read what its observations show, which explanations remain "
         "possible and how to distinguish them. Each entry ends with the test results and links to the study evidence.")
READER_FIELDS = (("support", "What the curve supports"), ("alternatives", "What remains possible"),
                 ("modeling_check", "How to distinguish them in modeling"))
WEIBULL = ("Weibull β describes the distribution of times at which the eventual systemic input arrives. "
           "With no lag, β < 1 gives a decreasing rate, β = 1 gives first-order input, and β > 1 gives a rate "
           "that rises and then falls. A fixed positive lag adds a period of exactly zero input before any of these shapes. "
           "A plasma peak or an early BLQ sample alone cannot identify β or the lag.")
STYLE = """body{font:16px/1.55 system-ui,sans-serif;color:#203749;max-width:1000px;margin:2em auto;padding:0 1.2em}
h1,h2,h3{line-height:1.2;color:#15364b}h2{margin-top:2em}h3{margin-top:1.6em}a{color:#075b85}
summary{cursor:pointer;padding:.4em 0}details{border-top:1px solid #cfdae1;margin:.25em 0}
details>div{padding:0 .9em .7em}nav a{margin-right:1.2em}li{margin-bottom:.3em}.meta{color:#495e68}
.candidate h5{font-size:1em;margin:1.05em 0 .15em}.candidate h5+p{margin-top:0}.technical{margin-top:1em}
@media print{details>div{display:block}body{max-width:none}}"""


def read_catalog(path, rule_version):
    data = path.read_bytes()
    catalog = json.loads(data)
    if catalog["rule_version"] != rule_version:
        raise ValueError("Mechanism catalogue and calculation rule versions differ")
    entries = catalog["candidates"]
    ids = {c["id"] for c in entries}
    if len(ids) != len(entries) or not entries:
        raise ValueError("Mechanism catalogue requires unique candidate IDs")
    for c in entries:
        if (c["family"] not in FAMILIES or not c["questions"] or not set(c["questions"]) <= set(range(1, 10))
                or not set(c["sources"]) <= catalog["sources"].keys() or not c["next_check"]):
            raise ValueError(f"Invalid mechanism catalogue entry: {c['id']}")
    # These six cells have distinct lag/shape premises, even where one parameterization is equivalent.
    required = {f"weibull_{shape}_{lag}" for shape in ("lt1", "eq1", "gt1") for lag in ("immediate", "lag")}
    if not required <= ids:
        raise ValueError("Incomplete Weibull lag-by-shape coverage")
    for key in ids:
        if key not in READINGS or not set(READINGS[key][1].split()) <= ids:
            raise ValueError(f"Missing reader interpretation or comparison partners for {key}")
    return catalog, hashlib.sha256(data).hexdigest()


def friendly(value):
    return str(value or "").replace("_", " ").lower()


def html_link(url, label):
    return f'<a href="{escape(url, quote=True)}">{escape(label)}</a>'


def profile_notes(profile):
    name = profile["dataset_id"] + (" · " + profile["series_label"] if profile["series_label"] else "")
    for t in profile["tests"]:
        if t["test"] == "T1":
            count = f"{t['positive_count']} of {t['eligible_count']} time pairs had a positive margin."
        else:
            count = f"{t['positive_count']} of {t['eligible_count']} ordered triples had a positive margin."
        text = f"{name} · {t['test']} {t['formal_status']}. "
        if t["executed"] or t["eligible_count"]:
            text += count + " "
        if t["test"] == "T2" and not t["executed"]:
            text += "A formal within-animal test was unavailable. "
        if t["margin"] is not None:
            text += f"Maximum margin {t['margin']:.4g} {t['margin_unit']}. "
        if t["witness_times_h"]:
            text += "Times " + ", ".join(f"{v:g}" for v in t["witness_times_h"]) + " h. "
        if t["witness_records"]:
            text += "Source records " + ", ".join(str(v) for v in t["witness_records"]) + ". "
        if t["flags"]:
            text += ", ".join(t["flags"]) + ". "
        if t["missing"]:
            text += "Unverified assumptions: " + ", ".join(t["missing"]) + "."
        yield text.strip()


def render(payload):
    catalog = {c["id"]: c for c in payload["catalog"]}
    sources = payload["sources"]
    studies = payload["studies"]
    title = "Absorption hypotheses for modeling"
    h = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">',
         f"<title>{title}</title><style>{STYLE}</style><main>",
         '<nav><a href="index.html">Absorption overview</a><a href="mechanism_assessment.md">Text handoff</a>'
         '<a href="mechanism_candidates.json">Structured evidence</a></nav>', f"<h1>{title}</h1>"]
    m = ["# " + title, "", "[Absorption overview](index.html) · [Structured evidence](mechanism_candidates.json)", ""]

    def paragraph(value):
        if value:
            h.append("<p>" + escape(str(value)) + "</p>")
            m.extend([str(value), ""])

    def heading(level, value):
        h.append(f"<h{level}>{escape(value)}</h{level}>")
        m.extend(["#" * level + " " + value, ""])

    paragraph(GUIDE)
    h.append("<nav>" + " ".join(html_link(f"#study-{i}", s["study_id"]) for i, s in enumerate(studies, 1)) + "</nav>")
    paragraph(WEIBULL)
    paragraph("Formal results apply only to the named profiles, comparisons and assumptions. An open candidate may have weak data, "
              "a missing reference, or equivalent predictions. A mechanism that requires a different route is retained with its scope.")
    for i, study in enumerate(studies, 1):
        h.append(f'<section id="study-{i}">')
        species = study["species"]
        heading(2, study["study_id"] + " · " + (", ".join(species) if isinstance(species, list) else species))
        question_links = {q["q"]: q.get("link") for q in study["questions"]}
        anchor = f"answers-{i}"
        h.append('<p>' + html_link("#" + anchor, "Read the nine study answers") + '</p>')

        heading(3, "Candidate mechanisms and alternatives")
        for family, group in FAMILIES.items():
            rows = [r for r in study["candidate_assessments"] if r["family"] == family]
            if not rows:
                continue
            heading(4, group)
            for row in rows:
                c = catalog[row["id"]]
                state = friendly(row["status"])
                label = row["label"]
                h.append(f'<details class="candidate" id="study-{i}-{escape(c["id"])}" data-candidate="{escape(c["id"])}">'
                         f"<summary><strong>{escape(label)}</strong> · {escape(state)}</summary><div>")
                m.extend([f"**{label}** · {state}", ""])
                for field, prompt in READER_FIELDS:
                    h.append(f"<h5>{prompt}</h5>")
                    m.extend([f"**{prompt}**", ""])
                    paragraph(row["reader_explanation"][field])
                h.append('<details class="technical"><summary>Technical details and source evidence</summary><div>')
                m.extend(["**Technical details and source evidence**", ""])
                if c["t1"]:
                    paragraph("T1 asks whether concentration divided by time since dosing rises beyond the stated bounds. "
                              "A positive pair is a potential counterexample. Zero positive pairs also occurs with other input shapes.")
                if c["t2"]:
                    paragraph("T2 looks for a fall and subsequent rise within one animal. Group means can show this pattern, "
                              "but their points can come from different animals.")
                if c["t1"] or c["t2"]:
                    paragraph(payload["premises"])
                for profile in row["profile_assessments"]:
                    for note in profile_notes(profile):
                        paragraph(note)
                seen = set()
                for item in sorted(row["evidence"], key=lambda e: -e["score"]):
                    if item["kind"] in {"T1", "T2"} or item["kind"] in seen:
                        continue
                    seen.add(item["kind"])
                    if item["score"] > 0:
                        paragraph(f"Q{item['question']} · {item['text']}")
                for contrast in row.get("contrast_assessments", ()):
                    paragraph(f"{contrast['test']} · {', '.join(contrast['dataset_ids'])} · "
                              f"{friendly(contrast['formal_status'])}. {contrast['scope']}")
                if c["id"] in DME:
                    paragraph("Pending review of " + DME[c["id"]] + ".")
                refs = [sources[k][0] for k in c["sources"]]
                refs_text = " · ".join([f"r4.3 {c['rule']}", *refs])
                h.append('<p class="meta">' + escape(refs_text) + " · " + " / ".join(
                    html_link(question_links[n], f"Q{n}") for n in c["questions"] if question_links.get(n)) + "</p></div></details></div></details>")
                m.extend([refs_text + " · " + ", ".join(f"[Q{n}]({question_links[n]})" for n in c["questions"] if question_links.get(n)), ""])
        h.append(f'<div id="{anchor}">')
        signals = dict.fromkeys(row["reader_explanation"]["support"] for row in study["candidate_assessments"]
                                if row["score"] >= 2)
        if signals:
            heading(3, "Observations to check in modeling")
            for observation in signals:
                paragraph(observation)
        heading(3, "Answers to the nine questions")
        for q in study["questions"]:
            link = q.get("link")
            label = f"Q{q['q']}. {q['label']}"
            text = str(q["conclusion"])
            state = friendly(q["status_code"])
            h.append("<p><strong>" + (html_link(link, label) if link else escape(label))
                     + "</strong> · " + escape(state) + "<br>" + escape(text) + "</p>")
            m.extend([f"**{label}** · {state}. {text}" + (f" [Evidence]({link})" if link else ""), ""])
        h.append("</div>")
        h.append("</section>")
    heading(2, "Sources and scope")
    paragraph(payload["scope"])
    for name, url, note in sources.values():
        paragraph(f"{name}. {note} {url}")
    h.append("</main></html>")
    return "\n".join(h), "\n".join(m)


def write_handoff(out, result, rules_dir):
    rules_dir = Path(rules_dir)
    registered = json.loads((rules_dir / "eda_rules.json").read_bytes())["source"]["absorption_mechanism_catalog"]
    catalog, digest = read_catalog(rules_dir / CATALOG_FILE, result["rule_specification"]["version"])
    if (digest, catalog["version"], CATALOG_FILE) != (registered["sha256"], registered["version"], registered["file"]):
        raise ValueError("Mechanism catalogue differs from the registered rules package")
    studies = assess(result, catalog["candidates"])
    ids = [c["id"] for c in catalog["candidates"]]
    datasets = [*result.get("datasets", []), *result.get("reported_parameters", [])]
    for study in studies:
        if ([c["id"] for c in study["candidate_assessments"]] != ids or
                [q["q"] for q in study["questions"]] != list(range(1, 10))):
            raise ValueError(f"Incomplete mechanism handoff for {study['study_id']}")
        rows = {row["id"]: row for row in study["candidate_assessments"]}
        for c in catalog["candidates"]:
            row = rows[c["id"]]
            check = modeling_check(c)
            if row["status"] in {"OUTSIDE_ROUTE_SCOPE", "ROUTE_SCOPE_UNRESOLVED"}:
                check = "Verify that the required route applies before fitting this pathway. " + check
            elif row["status"].startswith("EXCLUDED_IN_"):
                check = "Use this combination as a reference for the specified exclusion and compare a model that relaxes the challenged assumption. " + check
            row["reader_explanation"] = {
                "support": support_text(row, c, datasets,
                                        result.get("dose_series", []), result.get("ev_iv", []), result.get("conditions", [])),
                "alternatives": alternatives(row, rows), "modeling_check": check,
            }
    payload = {"version": catalog["version"], "rule_specification": result["rule_specification"],
               "catalog_sha256": digest, "absorption_sha256": hashlib.sha256((out / "absorption.json").read_bytes()).hexdigest(),
               "scope": catalog["scope"], "premises": catalog["premises"], "sources": catalog["sources"],
               "catalog": catalog["candidates"], "studies": studies}
    html, markdown = render(payload)
    (out / "mechanism_candidates.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "mechanism_assessment.html").write_text(html, encoding="utf-8")
    (out / "mechanism_assessment.md").write_text(markdown, encoding="utf-8")
