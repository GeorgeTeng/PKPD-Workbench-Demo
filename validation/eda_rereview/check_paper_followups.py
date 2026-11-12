"""Verify four grepafloxacin follow-ups directly against a supplied local run and its source tables."""
import json
from math import isclose
from pathlib import Path
import sys


def check(root):
    def load(path):
        return json.loads((root / path).read_bytes())

    def require(ok, description):
        if not ok:
            raise ValueError(description)

    raw = load("source_tables.json")
    tables = {t["dataset_id"]: t for t in (raw if isinstance(raw, list) else raw["datasets"])}
    boards = {b["board_id"]: b for b in load("absorption/absorption.json")["status_boards"]}
    monkey = boards["gpfx-i/monkey/single"]
    q7 = next(q for q in monkey["questions"] if q["q"] == 7)
    require("inconclusive" in q7["observed"].lower() and
            any("variability" in x for x in monkey["hypothesis_v1"]["alternatives"]) and
            "F rising with dose" not in monkey["hypothesis"]["brief"]["suspected"], "A5: group variability or inference boundary lost")

    rat = boards["gpfx-i/rat/single"]
    q8 = next(q for q in rat["questions"] if q["q"] == 8)
    endpoints = q8["reported_condition_comparisons"]
    require(len(endpoints) == 2 and q8["status_code"] == "PARTLY_ANSWERABLE", "A6: incomplete group comparison")
    require({r["endpoint"] for r in endpoints} == {"Cmax", "AUC(0-12 h)"}, "A6: wrong endpoints")
    for r in endpoints:
        column = {"Cmax": "cmax", "AUC(0-12 h)": "auc"}[r["endpoint"]]
        source = []
        for did, rid, meal in zip(r["datasets"], r["records"], ("nonfasted", "fasted"), strict=True):
            t = tables[did]
            require(t["metadata"]["condition"] == meal, "A6: reversed condition")
            record, = [v for v in t["records"] if v["record_id"] == rid and v["dose"] == 40]
            source.append(record[column])
        require(r["dose"] == 40 and [r["fed"], r["fasted"]] == source and isclose(r["ratio"], source[0]/source[1]),
                "A6: reported values or ratio differ from source")
        require(f"{r['ratio']:.0%}" in q8["observed"], "A6: ratio absent in report")

    dog = boards["gpfx-dog99-po/dog/repeat"]
    q9 = next(q for q in dog["questions"] if q["q"] == 9)
    expected = {}
    for t in tables.values():
        if "GPFX_DOG99_PO" not in t["study_source_ids"]:
            continue
        cols = [c["id"] for c in t["columns"] if c["meaning"] == "CONCENTRATION"]
        for r in t["records"]:
            vals = [r[c] for c in cols if r["value_status"].get(c) == "QUANTIFIED"]
            if len(vals) >= 2:
                expected[(t["dataset_id"],r["time_h"])] = (len(vals),min(vals),max(vals),[r["record_id"]])
    actual = {(r["dataset"],r["time_h"]): (r["n"],r["min"],r["max"],r["records"]) for r in q9["observed_individual_ranges"]}
    require(len(actual) == len(q9["observed_individual_ranges"]) == 12 and actual == expected and
            q9["status_code"] == "PARTLY_ANSWERABLE", "A8: within-dose, same-time ranges differ from raw animal columns")

    elim = next(b for b in load("elimination/elimination.json")["boards"] if b["board_id"] == "gpfx-iii-tr-monkey/monkey/excreta")
    recovery = elim["recovery"][0]
    samples = {r["sample"]:r["value"] for r in tables[recovery["dataset_id"]]["records"]}
    require(recovery["route_split"]["CAGEWASH"] == [samples["cagewash (unallocated)"]] and
            recovery["route_split"]["URINE"] == [samples["urine"]] and recovery["route_split"]["FAECES"] == [samples["feces"]] and
            isclose(samples["urine + feces total"],samples["urine"]+samples["feces"]), "E10: cage wash reassigned or double counted")
    h = elim["hypothesis_v1"]
    require(any("separately" in s and "losses could" in s for s in h["alternatives"]) and "cage-wash" in h["next_test"],
            "E10: missing uncertainty or discriminating collection check")


if __name__ == "__main__":
    check(Path(sys.argv[1]))
    print("A5, A6, A8 and E10 verified against the local run.")
