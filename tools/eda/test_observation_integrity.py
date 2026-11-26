import pytest

from research_pipeline import eda_absorption as ab, eda_distribution as dist, eda_elimination as elim
from modeling_handoff import dose_pattern


def curve(times, values, *, unit="h", dose=1, identity="", statuses=None):
    statuses = statuses or ["QUANTIFIED"] * len(times)
    entry = {"dataset_id": str(dose), "experimental_unit": identity,
             "metadata": {"record_category": "INDIVIDUAL", "dose_mg_kg": dose},
             "columns": [{"id": "t", "meaning": "TIME", "unit": unit},
                         {"id": "c", "meaning": "CONCENTRATION", "unit": "mg/L"}],
             "records": [{"t": t, "c": c, "value_status": {"c": status}}
                         for t, c, status in zip(times, values, statuses)]}
    card, (series,) = ab.extract(entry)
    return card, ab.curve_metrics(series["points"], card["record_level"]), series


def test_units_leave_metrics_invariant():
    t, c = [0.5, 1, 2, 3, 4], [1, 4, 2, 1, 0.5]
    hours = curve(t, c)[1]
    minutes = curve([x * 60 for x in t], c, unit="min")[1]
    for key in ("tmax", "auc_0_tlast", "terminal_selected"):
        assert minutes[key] == hours[key]
    assert not curve(t, c, unit="unknown")[2]["points"]


def test_common_window_includes_matched_but_later_endpoint():
    low = curve([1, 2, 3], [2, 2, 2])
    high = curve([1, 2, 3.0005], [4, 4, 4], dose=2)
    result = ab.dose_series([low, high], False)
    assert result["window_end_h"] == 3
    assert result["R_window"] == pytest.approx(1)
    assert result["e6_label"] == "NO_SIGN"


def test_design_zero_reaches_modeling_summary():
    low = curve([1, 2, 3], [2, 4, 2])
    high = curve([1, 2, 3], [8, 16, 8], dose=2)
    comparison = ab.dose_series([low, high], False)
    comparison["dataset_ids"] = ["1", "2"]
    datasets = {card["dataset_id"]: {"card": card} for card in (low[0], high[0])}
    _, result = dose_pattern({"species": "rat", "study": "example"}, comparison, datasets, [])
    assert "assum" in result["supports"].lower() and "zero" in result["supports"].lower()


def test_ambiguous_serial_identity_stays_unverified():
    for desc in ("", "Serial identity unknown.", "Identity not verified."):
        assert curve([1, 2, 3], [3, 2, 1], identity=desc)[0]["record_level"] == "INDIVIDUAL_IDENTITY_UNVERIFIED"
    assert curve([1, 2, 3], [3, 2, 1], identity="One concentration column per identified animal.")[0]["identity_verified"] == "yes"


def test_subject_identity_has_to_be_documented_in_this_table():
    verify = ab.COMMON.serial_identity_verified
    assert verify({"metadata": {"subject_id": "R1"}})
    assert not verify({"metadata": {"subject_id": "unknown"}})
    assert not verify({"metadata": {"subject_id": "R1", "serial_identity_verified": False}})
    assert not verify({"metadata": {"cross_route_identity_verified": True}})


@pytest.mark.parametrize("later_low", [True, False])
def test_common_window_with_staggered_times_never_extrapolates(later_low):
    low_t, high_t = (3.0005, 3) if later_low else (3, 3.0005)
    low = curve([1, 2, low_t], [2, 2, 2])
    high = curve([1, 2, high_t], [4, 4, 4], dose=2)
    result = ab.dose_series([low, high], False)
    assert result["window_end_h"] == 3
    assert result["R_window"] == pytest.approx(1)
    assert result["t3_label"] == "CANNOT_ASSESS"


def test_observed_baseline_enters_area_and_requires_no_zero_assumption():
    low = curve([0, 1, 2, 3], [2, 2, 2, 2])
    high = curve([0, 1, 2, 3], [4, 4, 4, 4], dose=2)
    assert low[1]["auc_0_tlast"] == 6
    result = ab.dose_series([low, high], False)
    assert result["rows"][0]["aucW_d"] == 6 and result["assumed_zero_doses"] == []


def test_duplicate_times_withhold_metrics_and_keep_observations():
    for values in ([4, 1, 4, 2, 0.5], [4, 4, 1, 2, 0.5]):
        _, metrics, series = curve([0.5, 1, 1, 2, 4], values)
        assert len(series["points"]) == 5
        assert "auc_0_tlast" not in metrics
        assert "duplicate" in metrics["not_assessable_reason"].lower()


def test_nd_sampling_reaches_profile_without_value_or_limit():
    card, metrics, series = curve([1, 2, 8, 24], [4, 2, 1, "ND"], statuses=["QUANTIFIED"] * 3 + ["ND"])
    assert series["points"][-1]["status"] == "NOT_DETECTED"
    assert series["points"][-1]["c"] is None
    assert metrics["last_sample_h"] == 24 and metrics["tlast"] == 8 and metrics["n_blq"] == 0
    panel = ab.pA1(card, metrics, series, whole=True).d
    assert panel["xlim"][1] >= 24
    assert "Not detected at 24 h" in panel["xlab"]
    assert dist.parse_value("ND", "ND") == (None, None, None, "NOT_DETECTED")
    for printed in ("Not detected (a)", "below detection limit"):
        assert dist.parse_value(printed) == (None, None, None, "NOT_DETECTED")


def test_assay_flags_override_numeric_placeholders():
    for raw in (0.5, "0.5"):
        assert dist.parse_value(raw, "BELOW_LLOQ") == (None, None, None, "BLQ")
        assert dist.parse_value(raw, "QUARANTINED")[-1] == "MISSING"
        assert elim.parse_cell(raw, "ABOVE_ULOQ")["value"] is None
        assert elim.parse_cell(raw, "BLQ")["state"] == "BLQ"
        assert elim.parse_cell(raw, "ND")["state"] == "NOT_DETECTED"


@pytest.mark.parametrize("printed,relation,limit", [
    ("<0.2", "<", .2), (">2", ">", 2), ("≤0.2", "≤", .2), (">=1e-2 mg/L", ">=", .01)])
def test_printed_inequality_survives_a_numeric_working_column(printed, relation, limit):
    entry = {"dataset_id": "bounded", "metadata": {"species": "Rat", "matrix": "plasma"},
             "columns": [{"id": "time_h", "meaning": "TIME", "unit": "h"},
                         {"id": "c", "meaning": "CONCENTRATION", "header": "Plasma", "unit": "mg/L"}],
             "records": [{"record_id": "r", "time_h": 1, "c": .2, "source_raw_values": {"c": printed},
                          "value_status": {"c": "QUANTIFIED"}}]}
    for series in (ab.extract(entry)[1], dist.extract(entry, {})[1]):
        point, = series[0]["points"]
        assert point["status"] == "CENSORED" and point["c"] is None
        assert (point["censoring"]["relation"], point["censoring"]["threshold"]) == (relation, limit)
    assert elim.parse_cell(printed, "QUANTIFIED")["censoring"]["threshold"] == limit


@pytest.mark.parametrize("baseline", ["REPORTED_ZERO_PREDOSE", "ND"])
def test_predose_sample_and_dip_plot_cannot_be_labeled_unsampled(baseline):
    c = 0 if baseline == "REPORTED_ZERO_PREDOSE" else "ND"
    card, metrics, series = curve([0, 1, 2, 3], [c, 4, 2, 4], statuses=[baseline] + ["QUANTIFIED"] * 3)
    for panel in [ab.pA1(card, metrics, series).d, ab.pA1_dip(card, metrics, series, (0, 1, 2)).d]:
        labels = [l.get("label") for l in panel["layers"]]
        assert "design zero (not measured)" not in labels
        if baseline == "ND":
            assert "Not detected at 0 h" in panel["xlab"]
        else:
            assert any(label and "predose" in label.lower() for label in labels)


def test_internal_censor_blocks_only_the_auc_windows_that_cross_it():
    low = curve([1, 2, 3, 4, 5], [2, 2, 2, "BLQ", 2], statuses=["QUANTIFIED"] * 3 + ["BLQ", "QUANTIFIED"])
    high = curve([1, 2, 3, 4, 5], [4] * 5, dose=2)
    assert low[1]["auc_0_tlast"] is None and low[1]["tail_share"] is None
    assert ab.dose_series([low, high], False)["status"] == "NOT_ASSESSABLE"
    short = curve([1, 2, 3], [4] * 3, dose=2)
    comparison = ab.dose_series([low, short], False)
    assert comparison["R_window"] == pytest.approx(1) and comparison["R_own_tlast"] is None
    assert ab.pC2(comparison)
    for card, _, _ in (low, high, short):
        # A12/G4: a pairing needs a reported study and species and the same matrix
        card.update(record_level="GROUP_MEAN", dose_basis="active moiety", study="S1", species="Rat",
                    matrix="plasma", matrix_category="PLASMA_SERUM_BLOOD")
    low[0].update(route_class="EV", route_detail="ORAL")
    for iv_card in (high[0], short[0]):
        iv_card.update(route_class="IV", route_detail="IV_BOLUS")
    spanning = ab.ev_iv(low[0], low[1], high[0], high[1])
    assert spanning["f_status"] == "NOT_ESTIMABLE" and "censored" in spanning["f_status_reason"]
    assert ab.ev_iv(low[0], low[1], short[0], short[1])["window_auc_ratio"] == pytest.approx(1)


def test_assumed_error_retains_numerical_evidence_without_excluding_models():
    times = [1, 2, 3, 4, 5, 6]
    reference = curve(times, [1] * 6)
    rising = curve(times, [1, 3, 8, 18, 40, 90])
    falling = curve(times, [16, 8, 4, 2, 1, .5])
    for card, _, _ in (reference, rising, falling):
        # A12/G4: a pairing needs a reported study and species and the same matrix
        card.update(record_level="GROUP_MEAN", dose_basis="active moiety", study="S1", species="Rat",
                    matrix="plasma", matrix_category="PLASMA_SERUM_BLOOD")
    assert rising[1]["mt1"] > 0 and rising[1]["t1_label"] == "CANNOT_ASSESS"
    pair = ab.ev_iv(falling[0], falling[1], reference[0], reference[1])
    assert pair["mt4"] > 0 and pair["t4_label"] == "CANNOT_ASSESS"
    scale = ab.condition_pair(rising[0], rising[1], reference[0], reference[1])
    assert scale["c_lower"] > scale["c_upper"] and scale["t5_label"] == "CANNOT_ASSESS"
    _, _, profile = curve(times, [9, 8, 1, .8, 7, 8])
    valley = ab.t2_curve(profile["points"])
    assert valley["robust"] and ab.t2_label(valley, "INDIVIDUAL")[0] == "CANNOT_ASSESS"

