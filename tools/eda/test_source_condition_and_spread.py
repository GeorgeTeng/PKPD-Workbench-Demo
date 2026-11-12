import copy

import pytest
import eda_absorption as ab


def summary(meal, value, **overrides):
    card = dict(condition=meal, study="trial", species="species", drug="parent", matrix="plasma",
                reported_analyte="parent", route_class="EV", route_detail="PO", dosing_regimen="single",
                reported_dose_unit="mg/kg", dataset_id=meal)
    card.update(overrides)
    return {"card":card,"params":[dict(param="AUC", label="AUC(0-8 h)", unit="mg*h/L", dose=11,
                                       definition="0-8 h", value=value, record_id=meal+"-record")]}


@pytest.mark.parametrize("mismatch", ["study","species","reported_analyte","reported_dose_unit","route_detail",
                                       "reported_formulation","dosing_regimen","dose","unit","definition","duplicate"])
def test_printed_meal_contrast_needs_matched_source_endpoints(mismatch):
    fast, fed = summary("fasted", 5), summary("nonfasted", 2)
    row, = ab._meal_contrasts([fed, fast])
    assert row["ratio"] == 0.4 and row["records"] == ["nonfasted-record", "fasted-record"]
    tables = [fast, fed]
    if mismatch == "duplicate":
        tables.append(copy.deepcopy(fed))
    elif mismatch in ("dose","unit","definition"):
        fed["params"][0][mismatch] = 22 if mismatch == "dose" else "different"
    else:
        fed["card"][mismatch] = "different"
    assert ab._meal_contrasts(tables) == []


def test_repeat_individual_spread_uses_verified_animals_at_one_time_and_dose():
    card = dict(route_class="EV", matrix_category="PLASMA_SERUM_BLOOD", gates=["NOT_SINGLE_DOSE"],
                record_level="INDIVIDUAL", identity_verified="yes", series_kind="INDIVIDUALS", unit="mg/L", dataset_id="synthetic")
    def animal(label, dose, values):
        return dict(label=label, dose=dose, points=[dict(t=t, c=c, status=st, record_id=f"{label}-{t}") for t,c,st in values])
    data = [dict(card=card,series=[animal("a",3,[(1,0.7,"QUANTIFIED"),(2,0,"BLQ")]),
                                    animal("b",3,[(1,1.1,"QUANTIFIED"),(2,0.5,"QUANTIFIED")]),
                                    animal("c",9,[(1,4.2,"QUANTIFIED")])])]
    row, = ab._repeat_individual_ranges(data)
    assert (row["time_h"],row["n"],row["min"],row["max"],row["records"]) == (1,2,0.7,1.1,["a-1","b-1"])
    card["identity_verified"] = "no"
    assert ab._repeat_individual_ranges(data) == []
