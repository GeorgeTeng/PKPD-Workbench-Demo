"""Plain-English interpretations for the registered absorption candidates.

Comparison partners name nearby explanations. Their availability is resolved against
this study's actual per-profile and comparison decisions before they are displayed.
"""
from .eda_absorption_assessment import EXCLUDED


# ID -> meaning in systemic PK, followed by IDs of competing explanations to check.
READINGS = {
    "first_order": ("With immediate first-order input, drug starts to enter at dosing. The rate falls as the amount left to absorb decreases.",
                    "first_order_lag zero_order weibull_gt1_immediate"),
    "first_order_lag": ("With a fixed lag, input starts after a delay and then slows as the amount left to absorb decreases.",
                        "first_order zero_order_lag transit weibull_gt1_immediate"),
    "zero_order": ("A finite zero-order input delivers a constant amount per hour from dosing until a stop time.",
                   "first_order zero_order_lag burst_sustained"),
    "zero_order_lag": ("A fixed lag precedes a period of constant input that ends at a defined time.",
                       "zero_order first_order_lag transit"),
    "transit": ("Drug moves through successive stages before entering circulation. This can delay the peak even when transfer starts at dosing.",
                "weibull_gt1_immediate first_order_lag zero_order"),
    "transit_lag": ("A period of zero input precedes gradual transfer through successive stages.",
                    "transit weibull_gt1_lag first_order_lag"),
    "parallel_immediate": ("A fast and a slow fraction can both start to enter at dosing, with each input rate falling over time.",
                           "first_order burst_sustained separated_inputs"),
    "parallel_zero_first": ("Two fractions start at dosing. One enters at a constant rate for a finite period and the other at a declining rate.",
                            "first_order zero_order separated_inputs"),
    "separated_inputs": ("Separate portions of a dose can enter at different times and produce distinct rises.",
                         "burst_sustained enterohepatic timing_sampling"),
    "burst_sustained": ("A promptly released fraction can be followed by prolonged input from the same dose.",
                        "first_order parallel_immediate separated_inputs"),
    "inverse_gaussian": ("An inverse Gaussian input spreads arrival times around a delayed mode and allows a long tail.",
                         "transit weibull_gt1_immediate first_order_lag"),
    "input_rate_limited": ("Slower input at higher doses can depress the peak even if the same fraction eventually enters circulation.",
                           "uptake_extent_loss nonlinear_elimination timing_sampling"),
    "uptake_extent_loss": ("A smaller fraction of a higher dose may enter circulation if uptake capacity is limited or drug is lost at the site.",
                           "input_rate_limited changing_clearance solubility_limited"),
    "efflux_saturation": ("Saturation of transport back into the gut lumen could allow more drug from a higher enteral dose to enter the blood.",
                          "first_pass_saturation nonlinear_elimination f_change"),
    "first_pass_saturation": ("If presystemic extraction saturates, a larger fraction of a higher dose may reach systemic blood.",
                              "efflux_saturation nonlinear_elimination f_change"),
    "solubility_limited": ("Slow dissolution or precipitation can delay release or reduce how much drug becomes available for uptake.",
                           "input_rate_limited uptake_extent_loss depot_release"),
    "gastric_emptying": ("Delayed or interrupted stomach emptying can change when an enteral dose reaches the absorption site.",
                         "absorption_window separated_inputs timing_sampling"),
    "absorption_window": ("An enteral dose may be absorbed efficiently only while passing through a particular intestinal region.",
                          "gastric_emptying solubility_limited uptake_extent_loss"),
    "depot_release": ("Drug retained at a subcutaneous or intramuscular injection site may enter slowly or be lost locally.",
                      "first_order input_rate_limited changing_clearance"),
    "pulmonary_enteral": ("After airway dosing, systemic exposure can include uptake from the lung and from swallowed drug.",
                          "separated_inputs first_order changing_clearance"),
    "enterohepatic": ("Drug excreted into bile and then reabsorbed can reappear in blood after the original input.",
                      "separated_inputs timing_sampling multicompartment"),
    "flip_flop": ("In flip-flop kinetics, slow absorption determines the apparent terminal decline after extravascular dosing.",
                  "multicompartment ongoing_input changing_clearance"),
    "ongoing_input": ("Concentration can fall while drug is still entering the bloodstream if distribution and elimination remove it faster than it enters.",
                      "flip_flop multicompartment burst_sustained"),
    "multicompartment": ("Drug returning from tissues can prolong the decline. Slow input can obscure these distribution phases.",
                         "flip_flop ongoing_input binding_distribution"),
    "nonlinear_elimination": ("Saturable elimination can make exposure rise disproportionately as concentrations increase.",
                              "input_rate_limited first_pass_saturation parallel_linear_saturable_elimination"),
    "changing_clearance": ("A change in how quickly the body clears drug can change exposure across doses, occasions or conditions.",
                          "f_change input_rate_limited binding_distribution"),
    "binding_distribution": ("Changes in binding or tissue distribution can change measured plasma concentrations even with the same systemic input.",
                             "changing_clearance multicompartment ongoing_input"),
    "f_change": ("Changing only systemic availability scales concentrations up or down under otherwise shared linear disposition.",
                 "cl_v_coscaling rate_only changing_clearance"),
    "cl_v_coscaling": ("Changing clearance and volume by the same factor preserves their ratio and can mimic a difference in availability.",
                       "f_change rate_only changing_clearance"),
    "rate_only": ("Changing only the input rate can move the peak and redistribute exposure in time while preserving total exposure under common linear disposition.",
                  "f_change cl_v_coscaling mixed_rate_extent"),
    "mixed_rate_extent": ("Input timing, the fraction reaching blood and disposition may change together.",
                          "rate_only f_change changing_clearance"),
    "occasion_effect": ("Exposure on a later occasion can include residual drug from earlier doses or changes in input or clearance.",
                        "baseline_carryover changing_clearance rate_only"),
    "baseline_carryover": ("Residual drug or an endogenous signal can contribute to the concentration observed after dosing.",
                          "first_order first_order_lag occasion_effect"),
    "timing_sampling": ("Sparse or misaligned samples, assay limits and averaging can alter the apparent peak, trough or onset.",
                        "first_order_lag separated_inputs variable_lag"),
    "parallel_linear_saturable_input": ("A dose can enter through a linear pathway and a second pathway with limited capacity.",
                                       "first_order input_rate_limited parallel_linear_saturable_elimination"),
    "parallel_linear_saturable_elimination": ("Linear clearance can operate alongside a second elimination pathway that saturates at higher concentrations.",
                                             "nonlinear_elimination parallel_linear_saturable_input f_change"),
    "variable_lag": ("Subjects with different onset times or absorption rates can produce a gradual or irregular study mean.",
                     "first_order_lag transit timing_sampling"),
    "finite_administration": ("Delivering the dose over time can itself spread systemic input across the early sampling interval.",
                              "zero_order first_order_lag depot_release"),
    "dose_proportional": ("If the kinetics are dose-proportional, comparable dose-normalized profiles and exposures follow the same pattern.",
                          "input_rate_limited uptake_extent_loss nonlinear_elimination"),
    "shared_one_compartment": ("One shared central compartment would give both routes the same linear disposition once their different inputs are accounted for.",
                               "multicompartment ongoing_input nonlinear_elimination"),
}
for shape, meaning in {
    "lt1": "Input is fastest just after onset and then slows. The cumulative amount starts at zero.",
    "eq1": "Here Weibull input is exactly first-order input in a different parameterization.",
    "gt1": "The input rate starts at zero, rises smoothly, then declines.",
}.items():
    for lag in ("immediate", "lag"):
        onset = "Input starts at dosing." if lag == "immediate" else "A fixed period of zero input precedes onset."
        rivals = ("zero_order first_order_lag transit" if lag == "immediate" else "zero_order_lag first_order transit_lag")
        if shape != "eq1":
            rivals = ("first_order " if lag == "immediate" else "first_order_lag ") + rivals
        READINGS[f"weibull_{shape}_{lag}"] = (onset + " " + meaning, rivals)


CHECKS = {
    "first_order": "Fit immediate first-order, finite constant-rate and short-lag inputs to the same observations with the same disposition and assay assumptions. Check where each misses the rise, peak and early decline. Early serial samples between dosing and the first observed peak are especially informative.",
    "first_order_lag": "Compare first-order input with and without a fixed delay, and with gradual transit. Use verified dosing times, predose measurements and early serial samples to tell a period of zero input from concentrations below the assay limit.",
    "zero_order": "Compare a finite constant input with first-order input under the same disposition model. Samples bracketing the end of input can reveal where their predictions diverge. Repeat the comparison after omitting the peak sample.",
    "zero_order_lag": "Compare immediate and delayed constant-rate input with delayed first-order input. Sample both the start and end of the rise to separate duration from delay.",
    "inverse_gaussian": "Compare inverse Gaussian, Weibull and transit input on the same early samples. Use an IV reference to constrain disposition and check which predictions differ around the peak.",
    "parallel_zero_first": "Compare single constant-rate and first-order inputs before fitting their mixture. Check whether the data distinguish the fraction using each path and the duration of constant input.",
    "parallel_immediate": "Compare one immediate input with two fractions that start together and enter at different rates. Check whether early and late measurements constrain both rates and fractions when disposition is shared.",
    "shared_one_compartment": "Verify the IV administration history and match sample times. Fit EV and IV together, then compare the early distribution and late decline with a multicompartment fit.",
    "dose_proportional": "Compare dose-normalized concentrations at shared times, followed by exposure over the same interval and, if available, total exposure. Retain the uncertainty of each comparison.",
    "flip_flop": "Estimate the EV and IV slopes over comparable late windows and repeat after omitting the last sample. Fit both routes together to see whether slow input is needed once IV data constrain disposition.",
}


def modeling_check(candidate):
    key = candidate["id"]
    if key.startswith("weibull_"):
        if "_eq1_" in key:
            return ("Use the equivalent first-order model once. Compare freely estimated Weibull shape and serial transit "
                    "under comparable lag assumptions and inspect the rising limb and peak.")
        return ("Fit Weibull shape and time scale alongside first-order and serial transit alternatives under comparable lag assumptions. "
                "Check whether early serial samples distinguish the predicted rates, and how much the shape estimate changes when a peak sample is omitted.")
    return CHECKS.get(key, candidate["next_check"])


def alternatives(row, study_rows):
    key = row["id"]
    meaning, partners = READINGS[key]
    profiles = {(p["dataset_id"], p["series_id"]) for p in row["profile_assessments"] if p["route_scope"] == "APPLICABLE"}
    names = []
    for partner in partners.split():
        other = study_rows[partner]
        if other["status"] not in {"OPEN", "INSUFFICIENT_DATA"}:
            continue
        shared = [p for p in other["profile_assessments"] if p["route_scope"] == "APPLICABLE"
                  and (not profiles or (p["dataset_id"], p["series_id"]) in profiles)]
        if shared and all(p["formal_status"] != EXCLUDED for p in shared):
            names.append(other["label"])
    if row["status"] in {"OUTSIDE_ROUTE_SCOPE", "ROUTE_SCOPE_UNRESOLVED"}:
        status = "This pathway depends on the route of administration."
    elif row["status"].startswith("EXCLUDED_IN_"):
        status = "The evidence rules out the tested combination only for the profiles or comparison specified below."
    elif row["status"] == "INSUFFICIENT_DATA":
        status = "Its contribution remains unresolved with the available evidence."
    else:
        status = "This explanation remains open."
    if names:
        labels = [name[0].lower() + name[1:] if name[1:2].islower() else name for name in names]
        labels = [label.replace("single Weibull, ", "single Weibull input (", 1) + ")" if label.startswith("single Weibull, ") else label
                  for label in labels]
        status += " Other possibilities to compare include " + (
            ", ".join(labels[:-1]) + " and " + labels[-1] if len(labels) > 1 else labels[0]) + "."
    return meaning + " " + status
