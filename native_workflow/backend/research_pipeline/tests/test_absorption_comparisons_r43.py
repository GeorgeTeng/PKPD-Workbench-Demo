"""Scientific counterexamples for the r4.3 comparison and intake paths."""
from math import exp, log

import pytest

from research_pipeline import eda_absorption as ab, eda_absorption_comparisons as comparison


def points(times, values):
    return [{"t":t,"c":y,"record_id":f"r{i}","status":"QUANTIFIED","lo":y*.95,"hi":y*1.05,
             "bounds_basis":"PROJECT_SET","bound_source":"project sensitivity"} for i,(t,y) in enumerate(zip(times,values))]


def card(name="A",route="SC"):
    return {"dataset_id":name,"study":"S","species":"mouse","matrix":"plasma","unit":"mg/L",
            "record_level":"GROUP_MEAN","route_detail":route,"matrix_category":"PLASMA_SERUM_BLOOD",
            "dose_mg_per_kg":1,"dose_basis":"parent","origin":"EXOGENOUS","analyte":"parent",
            "drug":"X","exposure_basis":"total","occasion":"first"}


def metrics(p):
    return {"_t":[x["t"] for x in p],"_c":[x["c"] for x in p],"terminal_selected":None}


def test_auc_hybrid_common_endpoints_and_censoring():
    win=comparison.window([{1:8,2:2},{.5:10,1:8,1.5:4,2:2}])
    assert win["start_h"]==1 and win["same_grid"] is False
    assert win["areas"]==pytest.approx([6/log(4)]*2)
    assert comparison.window([{1:8,1.5:None,2:2},{1:8,2:2}])["status"]=="CANNOT_ASSESS"
    assert comparison.window([{1:8,2:2},{1.05:8,1.95:2}])["areas"]==[]


def test_timing_can_create_apparent_shape_difference():
    a=points([1,2,3,4],[exp(-4*x) for x in [1,2,3,4]])
    b=points([1.05,1.95,3.05,3.95],[exp(-4*x) for x in [1.05,1.95,3.05,3.95]])
    res=comparison.condition_pair(card(),metrics(a),card("B","PO"),metrics(b),a,b)
    assert res["exact_pairs"]==0 and res["t5_label"]=="CANNOT_ASSESS"
    assert len(res["intervals"])==4 and res["timing_sensitivity"]["margin"]>0
    assert "SENSITIVITY_ONLY" in res["timing_sensitivity"]["flags"]


def test_ev_iv_missing_mode_and_incompatible_signals():
    a,b=points([1,2,3,4],[4,4,1,1]),points([1,2,3,4],[1,1,1,1])
    res=comparison.ev_iv(card(),metrics(a),card("B","NOT_FOUND"),metrics(b),a,b)
    assert res["t4"]["margin"]>0 and res["t4_label"]=="CANNOT_ASSESS"
    assert res["f_status"]=="INCOMPLETE_EXPOSURE_RATIO" and res["absolute_f"] is None
    assert res["shorter_window"]["end_h"]==3
    incompatible=comparison.ev_iv(card()|{"matrix":"ELF"},metrics(a),card("B","IV_BOLUS"),metrics(b),a,b)
    assert incompatible["f_status"]=="NOT_ESTIMABLE" and incompatible["f_window"] is None


def test_zero_denominator_and_blq_stay_as_raw_inequalities():
    left=points([1,2],[2,4])
    right=points([1,2],[1,2])
    right[0].update(c=None,status="BLQ",lo=0,hi=1)
    raw=comparison.raw_scale_constraints(left,right)
    assert raw["rows"][0]["upper"] is None and raw["rows"][0]["lower"]==pytest.approx(1.9)
    right[0].update(status="MEASURED_ZERO",c=0,lo=0,hi=0)
    assert comparison.raw_scale_constraints(left,right)["empty_intersection"]


def test_exactly_proportional_summary_means_have_unit_p_value():
    stat=ab._tp_summary({"c":20,"sd":1,"n":5},{"c":10,"sd":1,"n":5},2,1)
    assert stat["p"]==pytest.approx(1)


def test_truncated_area_cannot_substitute_for_complete_exposure_contrast():
    a,b=points([1,2,3],[2,3,4]),points([1,2,3],[1,2,3])
    left,right=card(),card("B","PO")
    source={"comparison_dataset_id":"A","reference_dataset_id":"B","estimand":"COMPLETE_DOSE_NORMALIZED_AUC_RATIO",
            "ci_level":.95,"ratio_ci":[1.5,2.1],"design_appropriate":True,"positive_two_sided_coverage":True,
            "shared_lti_disposition":True,"same_systemic_site":True,"source":"synthetic comparison",
            "coverage_evidence":"independent upper and lower bounds on both omitted areas"}
    def run(spec):
        return comparison.condition_pair(left|{"complete_exposure_comparison":spec},metrics(a),right,metrics(b),a,b)
    assert run(source)["rate_only_label"]=="EXCLUDED_UNDER_STATED_ASSUMPTIONS"
    assert run(source|{"positive_two_sided_coverage":False})["rate_only_label"]=="CANNOT_ASSESS"


def test_mixed_concentration_units_and_different_analytes_block_dose_comparisons():
    left=card()
    for change in ({"unit":"µg/L"},{"analyte":"metabolite"},{"dose_basis":"unknown"},
                   {"drug":"other compound"},{"matrix":"serum"}):
        right=left | change | {"dose_mg_per_kg":2}
        assert ab.dose_series([(left,{},{"dose":1}),(right,{},{"dose":2})],None)["status"]=="NOT_ASSESSABLE"


def test_parallel_animal_aucs_are_kept_separate_from_summary_aucs():
    def cohort(name,dose,scales):
        c=card(name)|{"dose_mg_per_kg":dose,"study_design":"PARALLEL","formulation":"same solution","superposition_premises_supported":True,
                      "superposition_evidence":"qualified design","record_level":"INDIVIDUAL"}
        series=[]
        for i,scale in enumerate(scales):
            pt=points([1,2,3],[scale*dose*v for v in [1,2,1]])
            series.append({"series_id":str(i),"points":pt,"metrics":metrics(pt)})
        return {"card":c,"series":series}
    result=comparison.individual_contrast([cohort("A",1,[1,1.1,1.2,1.3]),cohort("B",2,[1,1.1,1.2,1.3])])
    assert result["R"]==pytest.approx(1) and result["t3_label"]=="NOT_EXCLUDED"
    assert len(result["removal"])==8
    assert result["t3p"]["t3p_label"]=="NOT_EXCLUDED"
    arms=[cohort("A",1,[1,1.1,1.2,1.3]),cohort("B",2,[1,1.1,1.2,1.3])]
    del arms[0]["card"]["formulation"]
    restricted=comparison.individual_contrast(arms)
    assert restricted["R_window"]==pytest.approx(1) and restricted["t3_label"]=="CANNOT_ASSESS"
