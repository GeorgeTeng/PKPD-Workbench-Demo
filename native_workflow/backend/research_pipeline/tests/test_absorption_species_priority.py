"""Case-independent species priorities, synthetic data only."""
import copy
import json
from pathlib import Path

import pytest

from research_pipeline.eda_absorption_species import build_species_priorities


POLICY = json.loads((Path(__file__).resolve().parents[2] / "rules" / "eda" /
                     "absorption_species_priority_rules.json").read_text(encoding="utf-8"))
EXCLUDED = "EXCLUDED_UNDER_STATED_ASSUMPTIONS"
MODELS = ("input_rate_limited","first_order","dose_proportional","separated_inputs","timing_sampling",
          "variable_lag","flip_flop","ongoing_input","multicompartment")


def dataset(sid, cid, species="rat", dose=1, rebound=False):
    card = {"study":sid,"species":species,"dataset_id":cid,"route_detail":"SC","record_level":"GROUP_MEAN",
            "unit":"mg/L","tests_allowed":True,"dose_series_allowed":True}
    series = {"series_id":"mean","dose":dose,"metrics":{"n_quantified":5,"n_before_peak":2,"tmax":1,
              "cmax_status":"OBSERVED_QUANTIFIED"}}
    if rebound:
        pts = [{"t":t,"c":v,"status":"QUANTIFIED"} for t,v in [(1,9),(2,5),(3,8)]]
        series["t2"]={"formal_status":"CANNOT_ASSESS","positive_count":3,"best":{"observations":pts},
                      "flags":["T2_NOT_APPLICABLE_TO_GROUP_MEANS","SENSITIVITY_ONLY"],"test_executed":False}
    return {"card":card,"series":[series]}


def study(sid, ds):
    ps = [{"dataset_id":d["card"]["dataset_id"],"series_id":"mean","series_label":"synthetic mean",
           "route_scope":"APPLICABLE","formal_status":"CANNOT_ASSESS","tests":[]} for d in ds]
    return {"study_id":sid,"species_group":"Rat","dataset_ids":[p["dataset_id"] for p in ps],
            "questions":[{"q":n,"link":f"species-rat.html#q-{sid}-{n}"} for n in range(1,10)],
            "candidate_assessments":[{"id":k,"status":"OPEN","profile_assessments":copy.deepcopy(ps),
                                      "contrast_assessments":[]} for k in MODELS]}


def doses(sid="A", species="rat", ratio=.4):
    ds = [dataset(sid,sid+"-low",species,1),dataset(sid,sid+"-high",species,4)]
    ids = [d["card"]["dataset_id"] for d in ds]
    r = {"status":"ASSESSED","cmax_label":"POINTS_TO_NONLINEARITY","R_window":.93,"cmax_d_ratio":ratio,
         "dataset_ids":ids,"doses":[1,4],"observed_window":{"start_h":.25,"end_h":3},
         "rows":[{"dataset_id":i,"series_id":"mean"} for i in ids]}
    return study(sid,ds),ds,r


def test_species_checks_follow_actual_sources_and_policy_order():
    a, rats, comparison = doses()
    rabbits = [dataset("B","rabbit-mean","rabbit",rebound=True)]
    b = study("B",rabbits)  # Deliberately stale study-level species grouping.
    x = {"datasets":rats+rabbits,"dose_series":[comparison]}
    out = {r["species"]:r for r in build_species_priorities([a,b],x,POLICY)}
    assert out["Rat"]["kind"]=="dose_peak_exposure" and out["Rat"]["study_ids"]==["A"]
    assert "peak per dose fell more" in out["Rat"]["summary"] and "Saturability remains unresolved" in out["Rat"]["summary"]
    assert "0.4" not in out["Rat"]["summary"] and out["Rat"]["source_scopes"][0]["measurements"]["peak_per_dose_ratio"] == .4
    assert out["Rabbit"]["kind"]=="group_rebound" and out["Rabbit"]["study_ids"]==["B"]
    assert "two-phase subcutaneous" in out["Rabbit"]["priority"] and "individual rabbits before" in out["Rabbit"]["summary"]
    assert all(20 <= len((z["priority"]+" "+z["summary"]).split()) <= 35 for z in out.values())
    assert out["Rat"]["evidence_link"].endswith("A-8") and out["Rabbit"]["evidence_link"].endswith("B-4")

    # Same source design but one species. Reordering policy tiers genuinely changes selection.
    rabbits[0]["card"]["species"]="rat"
    assert build_species_priorities([b,a],x,POLICY)[0]["kind"]=="dose_peak_exposure"
    change=copy.deepcopy(POLICY)
    rank=change["evidence_hierarchy"]
    rank[1],rank[2]=rank[2],rank[1]
    assert build_species_priorities([b,a],x,change)[0]["kind"]=="group_rebound"


def test_contrasting_studies_remain_separate_and_ties_abstain():
    a,ds,r = doses(); b,more,r2 = doses("B",ratio=2.5)
    x = {"datasets":ds+more,"dose_series":[r,r2]}
    first, = build_species_priorities([a,b],x,POLICY)
    assert first["kind"]=="no_unique_leader" and first["study_ids"]==["A","B"] and not first["candidate_ids"]
    assert len(first["source_scopes"])==2 and len(first["evidence_links"])==2
    assert "slower absorption at higher doses in A" in first["summary"] and "higher normalized peaks in B" in first["summary"]
    assert {(z["label"],z["evidence_link"]) for z in first["linked_checks"]} == {
        ("slower absorption at higher doses","species-rat.html#q-A-8"),("higher normalized peaks","species-rat.html#q-B-8")}
    assert {tuple(z["dataset_ids"]) for z in first["source_scopes"]}=={("A-high","A-low"),("B-high","B-low")}
    assert build_species_priorities([b,a],dict(x,dose_series=[r2,r]),POLICY)==[first]
    r2["cmax_d_ratio"]=.3
    stable, = build_species_priorities([b,a],x,POLICY)
    assert stable["kind"]=="dose_peak_exposure" and stable["study_ids"]==["A"]


def test_separate_dose_gate_and_excluded_control():
    a,ds,r=doses()
    for d in ds:
        d["card"].update(tests_allowed=False,dose_series_allowed=True,occasion="DAY_2")
    x={"datasets":ds,"dose_series":[r]}
    control=next(c for c in a["candidate_assessments"] if c["id"]=="first_order")
    control["profile_assessments"][0]["formal_status"]=EXCLUDED
    out,=build_species_priorities([a],x,POLICY)
    assert out["kind"]=="dose_peak_exposure" and "first_order" not in out["candidate_ids"]
    assert "first-order model" not in out["priority"]
    ds[0]["card"]["dose_series_allowed"]=False
    assert build_species_priorities([a],x,POLICY)[0]["kind"]=="insufficient_evidence"


def test_no_noncentral_rebound_or_cross_species_exposure():
    a,ds,r=doses()
    ds[0]["card"]["species"]="rabbit"
    ds[1]["card"].update(tests_allowed=False,dose_series_allowed=False)
    ds[1]["series"][0]["t2"]=dataset("A","extra",rebound=True)["series"][0]["t2"]
    out=build_species_priorities([a],{"datasets":ds,"dose_series":[r]},POLICY)
    assert {z["species"] for z in out}=={"Rat","Rabbit"}
    assert all(z["kind"]=="insufficient_evidence" for z in out)


def test_qualified_exclusion_is_not_recommended_as_a_model():
    d=dataset("B","animal",rebound=True)
    d["card"].update(record_level="INDIVIDUAL",identity_verified="yes")
    d["series"][0]["t2"].update(test_executed=True,formal_status=EXCLUDED,flags=[],missing_premises=[])
    b=study("B",[d])
    c=next(c for c in b["candidate_assessments"] if c["id"]=="first_order")
    p=c["profile_assessments"][0]
    p.update(formal_status=EXCLUDED,tests=[{"test":"T2","executed":True,"formal_status":EXCLUDED,"flags":[],"missing":[]}])
    out,=build_species_priorities([b],{"datasets":[d]},POLICY)
    assert out["kind"]=="verified_individual_rebound" and out["candidate_ids"]==["separated_inputs"]
    assert "verified within-animal" in out["priority"]
    d["series"][0]["t2"]={}
    scoped,=build_species_priorities([b],{"datasets":[d]},POLICY)
    assert scoped["kind"]=="scoped_formal_exclusion" and "first_order" not in scoped["candidate_ids"]
    assert "animal" in scoped["summary"]


def test_representative_requires_an_eligible_series_and_window():
    a,ds,r=doses()
    x={"datasets":ds,"dose_series":[r]}
    r["rows"][0]["series_id"]="missing"
    assert build_species_priorities([a],x,POLICY)[0]["kind"]=="insufficient_evidence"
    r["rows"][0]["series_id"]="mean"
    ds[0]["series"][0]["metrics"]["cmax_status"]="LOWER_BOUND_ONLY"
    assert build_species_priorities([a],x,POLICY)[0]["kind"]=="insufficient_evidence"
    ds[0]["series"][0]["metrics"]["cmax_status"]="OBSERVED_QUANTIFIED"
    r["observed_window"]["end_h"]=None
    assert build_species_priorities([a],x,POLICY)[0]["kind"]=="insufficient_evidence"


def test_wrong_version_and_incomplete_hierarchy_are_rejected():
    with pytest.raises(ValueError,match="policy version"):
        build_species_priorities([],{},dict(POLICY,version="old"))
    with pytest.raises(ValueError,match="requires the r4.3"):
        build_species_priorities([],{"rule_specification":{"version":"older"}},POLICY)
    with pytest.raises(ValueError,match="one tier"):
        build_species_priorities([],{},dict(POLICY,evidence_hierarchy=[["sparse_rise"]]))


def test_comparable_iv_requires_the_same_species_and_stable_window_grade():
    d=dataset("S","ev","ferret")
    s=study("S",[d])
    pair={"same_window":True,"ev_window_h":[1,6],"iv_window_h":[1,6],"ratio":2.2,"grade":"EV_SHALLOWER_MARKED"}
    terminal={"pairs":[pair],"window_sensitive":False}
    ref={"ev":"ev","iv":"iv","comparison_basis":"IV_SAME_STUDY","terminal_comparison":terminal}
    iv={"card":{"study":"S","dataset_id":"iv","species":"ferret"}}
    x={"datasets":[d],"iv_references":[iv],"ev_iv":[ref]}
    def kind():
        return build_species_priorities([s],x,POLICY)[0]["kind"]
    assert kind()=="matched_terminal_slow_input"
    iv["card"]["species"]="dog"
    assert kind()=="insufficient_evidence"
    iv["card"]["species"]="ferret"
    terminal["window_sensitive"]=True
    assert kind()=="reconcile_sampling"
    terminal["window_sensitive"]=False
    terminal["pairs"].append(dict(pair,grade="EV_SHALLOWER_MODERATE",ratio=1.4))
    assert kind()=="reconcile_sampling"

