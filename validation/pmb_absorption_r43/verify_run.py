"""Verify the native r4.3 PMB run and compare its local standalone replay."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy


def verify_handoff(src, folder, rules, require, sha):
    ledger = json.loads((folder / "mechanism_candidates.json").read_bytes())
    reg = json.loads((rules / "eda_rules.json").read_bytes())["source"]["absorption_mechanism_catalog"]
    catalog = json.loads((rules / reg["file"]).read_bytes())
    require(ledger["catalog_sha256"] == reg["sha256"] == sha(rules / reg["file"]), "mechanism catalogue binding")
    require(ledger["catalog"] == catalog["candidates"] and ledger["version"] == reg["version"], "published candidate definitions")
    require(ledger["absorption_sha256"] == sha(src / "absorption.json"), "handoff evidence binding")
    boards = json.loads((src / "absorption.json").read_bytes())["status_boards"]
    require([s["study_id"] for s in ledger["studies"]] == [b["study"] for b in boards], "study coverage")
    expected = [c["id"] for c in catalog["candidates"]]
    html = (folder / "mechanism_assessment.html").read_text(encoding="utf-8")
    md = (folder / "mechanism_assessment.md").read_text(encoding="utf-8")
    for study in ledger["studies"]:
        rows = study["candidate_assessments"]
        require([r["id"] for r in rows] == expected, "missing candidate or changed order")
        require([q["q"] for q in study["questions"]] == list(range(1, 10)), "mechanism question coverage")
        require(all(not r["status"].startswith("EXCLUDED") for r in rows), "unsupported formal PMB exclusion")
        for q in study["questions"]:
            link = q["link"]
            page, anchor = link.split("#")
            require(link in html and link in md and f'id="{anchor}"' in (folder / page).read_text(encoding="utf-8"), "study evidence link")
    return {"edition": ledger["version"], "studies": len(boards), "candidates_per_study": len(expected),
            "assessments": len(boards) * len(expected), "catalog_sha256": reg["sha256"]}


def inspect(run, replay):
    base = Path(__file__).resolve().parents[2]
    common = runpy.run_path(str(base / "validation/pmb_absorption_retry030/verify_run.py"))
    evidence = common["inspect"](run, expected_version="EDA_ABSORPTION_R4_3")
    require = common["require"]
    src = run / "eda/run/absorption"
    result = json.loads((src / "absorption.json").read_bytes())
    rules = base / "native_workflow/backend/rules/eda"
    spec = json.loads((rules / "eda_rules.json").read_bytes())["source"]["absorption_rule_specification"]
    require(result["rule_specification"]["sha256"] == spec["sha256"] == common["sha"](rules/spec["file"]), "rule source mismatch")
    linked = {}
    folder = replay / "absorption"
    newer = (folder / "mechanism_candidates.json").is_file()
    handoff = verify_handoff(src, folder, rules, require, common["sha"]) if newer else None
    for ext in ("json", "html", "png"):
        a,b = ({p.name:common["sha"](p) for p in d.glob("*."+ext)} for d in (src, folder))
        if newer and ext == "json":
            b.pop("mechanism_candidates.json")
        if newer and ext == "html":
            b.pop("mechanism_assessment.html")
            link = ('<p><a href="mechanism_assessment.html"><strong>Open absorption hypotheses for modeling</strong></a> '
                    'for the study findings, competing explanations and the evidence that could separate them.</p>')
            index = (folder / "index.html").read_text(encoding="utf-8")
            require(index.count(link) == 1 and index.replace(link, "") == (src / "index.html").read_text(encoding="utf-8"),
                    "overview differs beyond the mechanism handoff link")
            a.pop("index.html")
            b.pop("index.html")
        require(a and a==b,f"standalone replay differs for {ext}")
        linked[ext]=len(a)
    for board in result["status_boards"]:
        require([q["q"] for q in board["questions"]]==list(range(1,10)), "question order")
    for item in result["ev_iv"]:
        require(item["t4_label"]=="CANNOT_ASSESS" and item["absolute_f"] is None, "unsupported PMB IV inference")
    rabbit = next(c for c in result["conditions"] if c["a"]=="T0048" and c["b"]=="T0047")
    require(rabbit["exact_pairs"]==0 and len(rabbit["intervals"])==6 and
            rabbit["t5_label"]=="CANNOT_ASSESS" and rabbit["timing_sensitivity"]["margin"]>0, "rabbit T5 scope")
    mouse = next(d for d in result["dose_series"] if "T0028" in d["dataset_ids"])
    require(mouse["t3_label"]=="CANNOT_ASSESS" and mouse["t3p"]["t3p_label"]=="CANNOT_ASSESS" and
            mouse["observed_window"]["same_grid"] is False, "mouse dose comparison scope")
    labelled = next(d for d in result["datasets"] if d["card"]["dataset_id"]=="T0001")
    require(all(s["metrics"].get("terminal_selected") is None for s in labelled["series"]),"unverified animal identity")
    if newer:
        evidence["mechanism_handoff"] = handoff
    return evidence | {"rule_sha256":spec["sha256"],"replayed_files_with_identical_sha256":linked,
                       "pmb_scientific_scope_checks":{"rabbit_exact_pairs":0,"rabbit_sensitivity_pairs":6,
                            "rabbit_formal_T5":rabbit["t5_label"],"mouse_formal_T3":mouse["t3_label"],
                            "mouse_summary_interior_grids_equal":False,"per_animal_terminal_estimates_withheld_for_unverified_labels":True}}


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("run",type=Path)
    p.add_argument("replay",type=Path)
    args=p.parse_args()
    print(json.dumps(inspect(args.run.resolve(),args.replay.resolve()),indent=2))
