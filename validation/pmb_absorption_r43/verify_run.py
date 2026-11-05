"""Verify the native r4.3 PMB run and compare its local standalone replay."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy


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
    for ext in ("json", "html", "png"):
        a,b = ({p.name:common["sha"](p) for p in folder.glob("*."+ext)} for folder in (src,replay/"absorption"))
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
