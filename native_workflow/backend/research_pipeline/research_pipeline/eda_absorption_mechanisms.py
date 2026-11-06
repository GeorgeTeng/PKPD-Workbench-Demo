"""Generate the English modeling handoff from the completed r4.3 study boards."""
import hashlib
import json
from html import escape
from pathlib import Path

from .eda_absorption_assessment import assess
from .eda_absorption_species import build_species_priorities
from .eda_absorption_brief import modeling_plan, study_brief
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
READER_FIELDS = (("support", "What the curve supports"), ("alternatives", "What remains possible"),
                 ("modeling_check", "How to distinguish them in modeling"))
WEIBULL = ("Weibull β describes the distribution of times at which the eventual systemic input arrives. "
           "With no lag, β < 1 gives a decreasing rate, β = 1 gives first-order input, and β > 1 gives a rate "
           "that rises and then falls. A fixed positive lag adds a period of exactly zero input before any of these shapes. "
           "A plasma peak or an early BLQ sample alone cannot identify β or the lag.")
STYLE = """body{font:17px/1.5 system-ui,sans-serif;color:#203749;max-width:780px;margin:3em auto;padding:0 1.3em}
h1,h2{line-height:1.15;color:#15364b}h1{font-size:2rem}.species-priority{padding:.7em 0 1.2em;border-bottom:1px solid #cbd8de}
h2{font-size:1.3rem;margin:.5em 0}p{margin:.4em 0}a{color:#075b85}section>a,nav{font-size:.9em}
nav{display:flex;flex-wrap:wrap;gap:1.2em;margin-top:1.6em}@media print{body{margin:0;max-width:none}nav,section>a{display:none}}"""
OLD_BOOKMARKS = """<script>
function locateStudy() {
  const match = /^#(?:study|context|answers)-(\\d+)(?:-|$)/.exec(location.hash);
  if (match) document.querySelector('[data-studies~="' + match[1] + '"]')?.scrollIntoView();
}
window.addEventListener('hashchange', locateStudy);
locateStudy();
</script>"""


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
    """Render the single-page priorities and the separate full-text evidence handoff."""
    titles = {c["id"]: c for c in payload["catalog"]}
    sources = payload["sources"]
    h = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width, initial-scale=1">',
         '<title>Absorption modeling priorities by species</title><style>' + STYLE + '</style></head><body>',
         '<main><h1>Absorption modeling priorities by species</h1>']
    m = ["# Absorption modeling priorities by species", ""]
    study_numbers = {s["study_id"]: i for i, s in enumerate(payload["studies"], 1)}
    citations = {q["link"]: f"{study['study_id']} · Q{q['q']}" for study in payload["studies"]
                 for q in study["questions"] if q.get("link")}
    for i, row in enumerate(payload["species_priorities"], 1):
        species, priority, summary = row["species"], row["priority"], row["summary"]
        # Preserve old study/candidate bookmarks as links to the corresponding species.
        numbers = " ".join(str(study_numbers[s["study_id"]]) for s in payload["studies"]
                           if (s.get("species_group") or s["species"]) == species)
        h.append(f'<section class="species-priority" id="species-{i}" data-studies="{numbers}">'
                 f'<h2>{escape(species)}</h2><p><strong>{escape(priority)}</strong> {escape(summary)}</p>')
        m.extend(["## " + species, "", f"**{priority}** {summary}", ""])
        links = [(link, "Evidence · " + citations.get(link, species)) for link in row["evidence_links"]]
        if row["kind"] == "no_unique_leader":
            links = [(check["evidence_link"], check["label"] + " · " + check["study_id"])
                     for check in row["linked_checks"] if check["evidence_link"]]
        for link, label in links:
            h.append(html_link(link, label) + " ")
            m.extend([f"[{label}]({link})", ""])
        h.append("</section>")
    if not payload["species_priorities"]:
        h.append("<p>No species has an admitted absorption record. Verify the study and species assignments first.</p>")
    h.append('<nav aria-label="Supporting material"><a href="index.html#species">Figure overview</a>'
             '<a href="mechanism_assessment.md">Full context (Markdown)</a>'
             '<a href="mechanism_candidates.json">Structured evidence</a></nav></main>' + OLD_BOOKMARKS + '</body></html>')
    m.extend(["## Modeling context", "", payload["modeling_plan"], ""])
    for study in payload["studies"]:
        species = study.get("species_group") or study["species"]
        m.extend(["## " + study["study_id"] + " · " + (", ".join(species) if isinstance(species, list) else species), ""])
        question_links = {q["q"]: q.get("link") for q in study["questions"]}
        for item in study["reader_brief"]:
            m.extend(["**" + item["title"] + "**", "", item["observation"], "", "**Next check.** " + item["check"], ""])
        for family, group in FAMILIES.items():
            rows = [r for r in study["candidate_assessments"] if r["family"] == family]
            if not rows:
                continue
            m.extend(["### " + group, ""])
            for row in rows:
                c = titles[row["id"]]
                m.extend([f"**{row['label']}** · {friendly(row['status'])}", ""])
                for field, prompt in READER_FIELDS:
                    m.extend([f"**{prompt}**", "", row["reader_explanation"][field], ""])
                m.extend(["**Technical details and source evidence**", ""])
                if c["t1"]:
                    m.extend(["T1 checks whether concentration divided by time since dosing increases beyond the stated bounds.", ""])
                if c["t2"]:
                    m.extend(["T2 checks for a fall and subsequent rise in a verified individual trajectory.", ""])
                if c["t1"] or c["t2"]:
                    m.extend([payload["premises"], ""])
                for profile in row["profile_assessments"]:
                    for note in profile_notes(profile):
                        m.extend([note, ""])
                seen = set()
                for item in sorted(row["evidence"], key=lambda e: -e["score"]):
                    if item["kind"] not in seen and item["kind"] not in {"T1", "T2"} and item["score"] > 0:
                        m.extend([f"Q{item['question']} · {item['text']}", ""])
                    seen.add(item["kind"])
                for contrast in row.get("contrast_assessments", ()):
                    m.extend([f"{contrast['test']} · {', '.join(contrast['dataset_ids'])} · "
                              f"{friendly(contrast['formal_status'])}. {contrast['scope']}", ""])
                if c["id"] in DME:
                    m.extend(["Pending review of " + DME[c["id"]] + ".", ""])
                refs = [f"r4.3 {c['rule']}", *(sources[k][0] for k in c["sources"]),
                        *(f"[Q{n}]({question_links[n]})" for n in c["questions"] if question_links.get(n))]
                m.extend([" · ".join(refs), ""])
        m.extend(["### Answers to the nine questions", ""])
        for q in study["questions"]:
            link = q.get("link")
            m.extend([f"**Q{q['q']}. {q['label']}** · {friendly(q['status_code'])}. {q['conclusion']}"
                      + (f" [Evidence]({link})" if link else ""), ""])
    m.extend(["## Methods, sources and scope", "", WEIBULL, "", payload["scope"], ""])
    for name, url, note in sources.values():
        m.extend([f"{name}. {note} {url}", ""])
    return "\n".join(h), "\n".join(m)


def write_handoff(out, result, rules_dir):
    rules_dir = Path(rules_dir)
    registry = json.loads((rules_dir / "eda_rules.json").read_bytes())["source"]
    registered = registry["absorption_mechanism_catalog"]
    priority_rule = registry["absorption_species_priority_rules"]
    policy_bytes = (rules_dir / priority_rule["file"]).read_bytes()
    policy = json.loads(policy_bytes)
    if (hashlib.sha256(policy_bytes).hexdigest() != priority_rule["sha256"] or policy["version"] != priority_rule["version"]
            or policy["rule_version"] != result["rule_specification"]["version"]):
        raise ValueError("Species priority policy differs from the registered rules package")
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
        study["reader_brief"] = study_brief(study, result)
    payload = {"version": catalog["version"], "rule_specification": result["rule_specification"],
               "catalog_sha256": digest, "absorption_sha256": hashlib.sha256((out / "absorption.json").read_bytes()).hexdigest(),
               "scope": catalog["scope"], "premises": catalog["premises"], "sources": catalog["sources"],
               "catalog": catalog["candidates"], "studies": studies, "modeling_plan": modeling_plan(studies, result)}
    payload["priority_rule_specification"] = priority_rule
    payload["species_priorities"] = build_species_priorities(studies, result, policy)
    html, markdown = render(payload)
    (out / "mechanism_candidates.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "mechanism_assessment.html").write_text(html, encoding="utf-8")
    (out / "mechanism_assessment.md").write_text(markdown, encoding="utf-8")
