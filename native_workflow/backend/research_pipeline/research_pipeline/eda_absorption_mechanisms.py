"""Generate the English modeling handoff from the completed r4.3 study boards."""
import hashlib
import json
from html import escape
from pathlib import Path

from .eda_absorption_assessment import assess


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
GUIDE = ("Read the nine answers first. Each candidate below links to the observations and the next "
         "comparison that could distinguish it. A clue sets a priority for checking an observation. "
         "Mechanism probabilities and fitted parameter values require separate modeling.")
WEIBULL = ("Weibull β describes the distribution of times at which the eventual systemic input arrives. "
           "With no lag, β < 1 gives a decreasing rate, β = 1 gives first-order input, and β > 1 gives a rate "
           "that rises and then falls. A fixed positive lag adds a period of exactly zero input before any of these shapes. "
           "A plasma peak or an early BLQ sample alone cannot identify β or the lag.")
STYLE = """body{font:16px/1.55 system-ui,sans-serif;color:#203749;max-width:1000px;margin:2em auto;padding:0 1.2em}
h1,h2,h3{line-height:1.2;color:#15364b}h2{margin-top:2em}h3{margin-top:1.6em}a{color:#075b85}
summary{cursor:pointer;padding:.4em 0}details{border-top:1px solid #cfdae1;margin:.25em 0}
details>div{padding:0 .9em .7em}nav a{margin-right:1.2em}li{margin-bottom:.3em}.meta{color:#495e68}
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
    return catalog, hashlib.sha256(data).hexdigest()


def friendly(value):
    return str(value or "").replace("_", " ").lower()


def html_link(url, label):
    return f'<a href="{escape(url, quote=True)}">{escape(label)}</a>'


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
    paragraph(payload["premises"])
    paragraph("Formal results apply only to the named profiles, comparisons and assumptions. An open candidate may have weak data, "
              "a missing reference, or equivalent predictions. A mechanism that requires a different route is retained with its scope.")
    for i, study in enumerate(studies, 1):
        h.append(f'<section id="study-{i}">')
        species = study["species"]
        heading(2, study["study_id"] + " · " + (", ".join(species) if isinstance(species, list) else species))
        heading(3, "Answers to the nine questions")
        question_links = {}
        for q in study["questions"]:
            n = q["q"]
            link = q.get("link")
            label = f"Q{n}. {q['label']}"
            question_links[n] = link
            text = str(q["conclusion"])
            state = friendly(q["status_code"])
            h.append("<p><strong>" + (html_link(link, label) if link else escape(label))
                     + "</strong> · " + escape(state) + "<br>" + escape(text) + "</p>")
            m.extend([f"**{label}** · {state}. {text}" + (f" [Evidence]({link})" if link else ""), ""])

        # Put distinct observations together before the full unranked inventory.
        signals = {}
        for row in study["candidate_assessments"]:
            for item in row["evidence"]:
                if item["score"] >= 2:
                    key = (item["question"], item["kind"])
                    if key not in signals or item["score"] > signals[key]["score"]:
                        signals[key] = item
        if signals:
            heading(3, "Observations to check in modeling")
            for (n, _), item in sorted(signals.items()):
                paragraph(f"Q{n} · {item['text']}")

        heading(3, "Candidate mechanisms and alternatives")
        for family, group in FAMILIES.items():
            rows = [r for r in study["candidate_assessments"] if r["family"] == family]
            if not rows:
                continue
            heading(4, group)
            for row in rows:
                c = catalog[row["id"]]
                state = friendly(row["status"]) + " · " + row["priority"]
                label = row["label"]
                h.append(f"<details><summary><strong>{escape(label)}</strong> · {escape(state)}</summary><div>")
                m.extend([f"**{label}** · {state}", ""])
                paragraph(row["evidence_balance"])
                paragraph(row["rationale"])
                # The structured file retains every profile, test and witness. Show one example
                # of each distinct observation in the reader, omitting repeated rationale text.
                seen = set()
                for item in sorted(row["evidence"], key=lambda e: -e["score"]):
                    if item["kind"] in seen:
                        continue
                    seen.add(item["kind"])
                    if item["text"] not in row["rationale"] and item["score"] > 0:
                        paragraph(f"Q{item['question']} · {item['text']}")
                for contrast in row.get("contrast_assessments", ()):
                    paragraph(f"{contrast['test']} · {', '.join(contrast['dataset_ids'])} · "
                              f"{friendly(contrast['formal_status'])}. {contrast['scope']}")
                if c["t1"] or c["t2"]:
                    tests = ", ".join(t for t in ("T1", "T2") if c[t.lower()])
                    paragraph(f"Applicable shape guarantee under the stated premises: {tests}.")
                paragraph("Modeling check: " + c["next_check"])
                if c["id"] in DME:
                    paragraph("Pending review of " + DME[c["id"]] + ".")
                refs = [sources[k][0] for k in c["sources"]]
                refs_text = " · ".join([f"r4.3 {c['rule']}", *refs])
                h.append('<p class="meta">' + escape(refs_text) + " · " + " / ".join(
                    html_link(question_links[n], f"Q{n}") for n in c["questions"] if question_links.get(n)) + "</p></div></details>")
                m.extend([refs_text + " · " + ", ".join(f"Q{n}" for n in c["questions"]), ""])
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
    for study in studies:
        if ([c["id"] for c in study["candidate_assessments"]] != ids or
                [q["q"] for q in study["questions"]] != list(range(1, 10))):
            raise ValueError(f"Incomplete mechanism handoff for {study['study_id']}")
    payload = {"version": catalog["version"], "rule_specification": result["rule_specification"],
               "catalog_sha256": digest, "absorption_sha256": hashlib.sha256((out / "absorption.json").read_bytes()).hexdigest(),
               "scope": catalog["scope"], "premises": catalog["premises"], "sources": catalog["sources"],
               "catalog": catalog["candidates"], "studies": studies}
    html, markdown = render(payload)
    (out / "mechanism_candidates.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "mechanism_assessment.html").write_text(html, encoding="utf-8")
    (out / "mechanism_assessment.md").write_text(markdown, encoding="utf-8")
