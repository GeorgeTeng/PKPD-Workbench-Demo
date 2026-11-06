"""Choose a species-level modeling check from separately scoped r4.3 studies."""
from collections import defaultdict
from math import isfinite

from .eda_absorption import species_group
from .eda_absorption_assessment import EXCLUDED, firm
from .eda_absorption_reader_evidence import number, route_name, time, time_window


VERSION = "r4.3-handoff.2"
RULE_VERSION = "r4.3"
KINDS = {"verified_individual_rebound","scoped_formal_exclusion","dose_peak_exposure","increased_peak_exposure",
         "matched_terminal_slow_input","matched_terminal_steeper_ev","group_rebound","verify_identity",
         "reconcile_sampling","sparse_rise"}
UNASSIGNED = {"","NOT_FOUND","UNKNOWN","NOT REPORTED","SPECIES NOT STATED","N/A"}


def validate(policy, result):
    if (policy.get("version"), policy.get("rule_version")) != (VERSION, RULE_VERSION):
        raise ValueError("Unsupported absorption species-priority policy version")
    if (result.get("rule_specification") or {}).get("version", RULE_VERSION) != RULE_VERSION:
        raise ValueError("Species priority requires the r4.3 study evidence")
    tiers = policy["evidence_hierarchy"]
    kinds = [k for tier in tiers for k in tier]
    if not all(tiers) or set(kinds) != KINDS or len(kinds) != len(KINDS):
        raise ValueError("Every species-priority evidence kind must have exactly one tier")
    if policy["tie_handling"] != {"different_kinds":"no_unique_leader","same_kind":"one_lexically_stable_example","pool_studies":False}:
        raise ValueError("Unknown species-priority tie or pooling policy")
    if (policy["dose_criterion"]["required_direction"] != "normalized_peak_changes_more_than_partial_exposure"
            or policy["rebound_criterion"]["observations"] != "three_quantified_ordered_samples_with_middle_below_both_neighbors"
            or policy["rebound_criterion"]["group_mean_action"] != "verify_within_animal_first"
            or not policy["terminal_criterion"]["require_same_study_iv"] or not policy["terminal_criterion"]["require_same_window"]
            or policy["report_requirements"]["excluded_candidate_policy"] != "omit_in_selected_scope"):
        raise ValueError("Unsupported scope or evidence requirements in species-priority policy")
    return {k:n for n,tier in enumerate(tiers) for k in tier}


def taxon(card):
    raw = str(card.get("species") or "").strip()
    if raw.upper() in UNASSIGNED:
        return "Species not stated"
    group = species_group(raw)
    # Keep a source-named species such as Ferret when the portal lacks a grouping alias.
    return raw if group == "Species not stated" else group


def real(value):
    return isinstance(value, (int,float)) and not isinstance(value,bool) and isfinite(value)


def scoped_candidates(study, names, ev_sources, all_ids, *, dose=False):
    """A candidate excluded elsewhere can survive here; an exclusion here always wins."""
    selected = []
    for c in study.get("candidate_assessments", []):
        if c["id"] not in names or c.get("status") in {"OUTSIDE_ROUTE_SCOPE","ROUTE_SCOPE_UNRESOLVED"}:
            continue
        checks = c.get("contrast_assessments", [])
        if any(z.get("formal_status") == EXCLUDED and firm(z) and
               set(z.get("dataset_ids", [])) == set(all_ids) for z in checks):
            continue
        assessments = c.get("profile_assessments", [])
        valid = True
        for cid, series_id in ev_sources:
            hits = [p for p in assessments if p["dataset_id"] == cid and
                    (series_id is None or p.get("series_id") == series_id)]
            unusable = {EXCLUDED,"NO_QUANTIFIED_PROFILE","GATED_PROFILE"}
            # Dose-series permission is checked on every source card separately.
            if dose:
                unusable.discard("GATED_PROFILE")
            if not hits or any(p.get("route_scope") != "APPLICABLE" or p.get("formal_status") in unusable for p in hits):
                valid = False
                break
        if valid:
            selected.append(c["id"])
    return [k for k in names if k in selected]


def link(study, n):
    return next((q["link"] for q in study.get("questions", []) if q.get("q") == n and q.get("link")), "")


def entry(study, kind, n, ids, candidates, priority, summary):
    return {"kind":kind,"question":n,"study_id":study["study_id"],"dataset_ids":sorted(set(ids)),
            "candidate_ids":list(candidates),"priority":priority,"summary":summary,"evidence_link":link(study,n)}


def route_word(route):
    return {"SC":"subcutaneous","IM":"intramuscular","IP":"intraperitoneal"}.get(route,route)


def dose_signals(study, ds, doses, rules):
    cards = {d["card"]["dataset_id"]:d for d in ds}
    for r in doses:
        ids = set(r.get("dataset_ids", []))
        if not ids or not ids <= cards.keys() or r.get("status") not in rules["allowed_comparison_status"]:
            continue
        if not all(cards[i]["card"].get("dose_series_allowed", cards[i]["card"].get("tests_allowed")) for i in ids):
            continue
        if r.get("cmax_label") != rules["peak_flag"]:
            continue
        peak, area = r.get("cmax_d_ratio"), r.get("R_window")
        w = r.get("observed_window") or {}
        a,b = w.get("start_h"),w.get("end_h")
        dp = r.get("dose_pair") or r.get("t3_primary_pair") or r.get("doses") or []
        if not (all(real(v) for v in (peak,area,a,b)) and peak > 0 and area > 0 and 0 <= a < b and
                len(dp) >= 2 and all(real(z) and z > 0 for z in dp) and max(dp)>min(dp)):
            continue
        # Use the series actually compared, including multi-dose columns in one source.
        rows = r.get("rows", [])
        selected = []
        for i in sorted(ids):
            source = cards[i]
            records = [z for z in rows if z.get("dataset_id") == i]
            keys = {z["series_id"] for z in records if z.get("series_id")}
            series = [s for s in source.get("series", []) if not keys or s.get("series_id") in keys]
            if not series or (keys and {s.get("series_id") for s in series} != keys) or any(
                    not s.get("metrics",{}).get("n_quantified") or s["metrics"].get("cmax_status") == "LOWER_BOUND_ONLY" for s in series):
                break
            selected.extend((i,s.get("series_id")) for s in series)
        else:
            slower = peak < min(1,area)
            higher = peak > max(1,area)
            if not (slower or higher):
                continue
            keys = ("input_rate_limited","first_order","dose_proportional") if slower else ("dose_proportional","timing_sampling")
            open_ids = scoped_candidates(study,keys,selected,ids,dose=True)
            if slower and "input_rate_limited" not in open_ids:
                continue
            routes = set(route_name(cards[i]["card"]) for i in ids)
            route = route_word(routes.pop()) if len(routes) == 1 else "extravascular"
            if slower:
                control = "a dose-independent first-order model" if {"first_order","dose_proportional"} <= set(open_ids) else "other retained input models"
                priority = f"Test slower {route} absorption at higher doses against {control}."
                reading = f"In {study['study_id']}, peak per dose fell more than partial exposure per dose. Saturability remains unresolved."
            else:
                priority = f"Check peak sampling before assigning the higher {route} peak per dose to faster absorption."
                reading = f"In {study['study_id']}, peak per dose rose more than partial exposure per dose."
            proposal = entry(study,"dose_peak_exposure" if slower else "increased_peak_exposure",8,ids,open_ids,priority,reading)
            yield dict(proposal,measurements={"low_high_doses_mg_kg":[min(dp),max(dp)],"peak_per_dose_ratio":peak,
                                             "exposure_per_dose_ratio":area,"window_h":[a,b]})


def profile_signals(study, ds, rules):
    for d in ds:
        c = d["card"]
        if not c.get("tests_allowed"):
            continue
        cid, route = c["dataset_id"],route_name(c)
        for s in d.get("series", []):
            m = s.get("metrics") or {}
            if not m.get("n_quantified"):
                continue
            unit = c.get("record_level")
            sources = [(cid,s.get("series_id"))]
            if unit == "INDIVIDUAL_IDENTITY_UNVERIFIED":
                keys = scoped_candidates(study,("timing_sampling","variable_lag"),sources,[cid])
                yield entry(study,"verify_identity",5,[cid],keys,
                            "Verify animal identifiers and collection times before fitting individual absorption.",
                            f"{study['study_id']} ({cid}, {route}) reports values under source labels whose cross-time animal identity is unverified.")
                continue
            t = s.get("t2") or {}
            best = t.get("best") or {}
            z = best.get("observations") or []
            quantified = len(z) == 3 and all(real(p.get("c")) and real(p.get("t")) and p.get("status") == "QUANTIFIED" for p in z)
            if (t.get("positive_count",0) >= rules["minimum_positive_triples"] and quantified and
                    z[0]["t"] < z[1]["t"] < z[2]["t"] and z[1]["c"] < min(z[0]["c"],z[2]["c"])):
                verified = (unit == "INDIVIDUAL" and c.get("identity_verified") == "yes" and not c.get("destructive_sampling")
                            and t.get("test_executed") and t.get("formal_status") == EXCLUDED
                            and firm({"flags":t.get("flags",[]),"missing":t.get("missing_premises",[])}))
                group = unit == "GROUP_MEAN"
                keys = scoped_candidates(study,("separated_inputs","first_order"),sources,[cid])
                if (verified or group) and "separated_inputs" in keys:
                    action = (f"Compare two-phase {route_word(route)} absorption with other explanations for the verified within-animal rebound." if verified else
                              f"Check for two-phase {route_word(route)} absorption.")
                    animal = {"Mouse":"mice","Rabbit":"rabbits","Rat":"rats","Dog":"dogs","Human":"participants"}.get(taxon(c),"animals")
                    summary = (f"In {study['study_id']}, the same animal showed a qualified trough and secondary rise. Its cause remains unresolved." if verified else
                               f"The {study['study_id']} group mean dipped and rose again. Verify the rebound in individual {animal} before fitting a second input.")
                    yield dict(entry(study,"verified_individual_rebound" if verified else "group_rebound",4,[cid],keys,action,summary),
                               series_id=s.get("series_id"),measurements={"times_h":[v["t"] for v in z],
                               "concentrations":[v["c"] for v in z],"unit":c.get("unit")})
            n = m.get("n_before_peak")
            if n in (0,1) and m.get("cmax_status") != "LOWER_BOUND_ONLY" and real(m.get("tmax")):
                keys = scoped_candidates(study,("timing_sampling",),sources,[cid])
                yield entry(study,"sparse_rise",2,[cid],keys,"Collect earlier samples before choosing an input shape.",
                            f"In {study['study_id']} ({cid}, {route}), {n} quantified samples preceded the sampled maximum at {time(m['tmax'])}.")


def comparison_signals(study, ds, result, ivs):
    single = {d["card"]["dataset_id"]:d for d in ds if d["card"].get("tests_allowed") and len(d.get("series",[])) == 1
              and d["series"][0].get("metrics",{}).get("n_quantified")}
    for r in result.get("ev_iv", []):
        ev,iv = r["ev"],r["iv"]
        if ev not in single or iv not in ivs or r.get("comparison_basis") != "IV_SAME_STUDY":
            continue
        ev_series = single[ev]["series"][0]
        pairs = [p for p in (r.get("terminal_comparison") or {}).get("pairs", []) if p.get("same_window") and
                 len(p.get("ev_window_h") or []) == 2 and p["ev_window_h"] == p.get("iv_window_h") and real(p.get("ratio"))]
        grades = {p.get("grade") for p in pairs}
        if pairs and ((r.get("terminal_comparison") or {}).get("window_sensitive") or len(grades)>1):
            proposal = entry(study,"reconcile_sampling",6,[ev,iv],[],"Reconcile the terminal windows before interpreting the apparent half-life.",
                             f"In {study['study_id']}, the extravascular-to-IV comparison is sensitive to the selected window.")
            yield dict(proposal,request_key="review_terminal_windows")
            continue
        directions = {("slow" if str(p.get("grade","")).startswith("EV_SHALLOWER") else
                       "steep" if p.get("grade") == "EV_STEEPER" else "parallel") for p in pairs}
        for direction in sorted(directions - {"parallel"}):
            if "parallel" in directions:
                continue  # Window sensitivity precludes a unique direction.
            p = next(v for v in pairs if (str(v.get("grade","")).startswith("EV_SHALLOWER") if direction=="slow" else v.get("grade")=="EV_STEEPER"))
            keys = ("flip_flop","ongoing_input") if direction == "slow" else ("multicompartment","timing_sampling")
            open_ids = scoped_candidates(study,keys,[(ev,ev_series.get("series_id"))],[ev,iv])
            if keys[0] not in open_ids:
                continue
            priority = ("Check whether slow input accounts for the shallower extravascular terminal slope." if direction == "slow"
                        else "Check disposition and sampling behind the steeper extravascular terminal slope.")
            summary = f"{study['study_id']} shows the difference over matched extravascular and IV windows, but its cause remains unresolved."
            yield dict(entry(study,"matched_terminal_slow_input" if direction == "slow" else "matched_terminal_steeper_ev",6,
                             [ev,iv],open_ids,priority,summary),measurements={"ratio":p["ratio"],"window_h":p["ev_window_h"]})
    for r in result.get("conditions", []):
        a,b = r["a"],r["b"]
        n = len(r.get("intervals") or [])
        if a not in single or b not in single or not n or r.get("exact_pairs") != 0:
            continue
        keys = scoped_candidates(study,("timing_sampling",),[(i,single[i]["series"][0].get("series_id")) for i in (a,b)],[a,b])
        yield entry(study,"reconcile_sampling",9,[a,b],keys,"Reconcile actual sampling times before interpreting the condition difference.",
                    f"{study['study_id']} ({a} versus {b}) has {n} nearby pairs and no exact time matches.")


FORMAL = {
    "T1": (3, "the central concentration divided by time increased", "Compare inputs that relax the non-increasing rate assumption under the stated disposition."),
    "T2": (4, "a verified trajectory contradicted the single-peak prediction", "Compare explanations that permit a within-animal trough and secondary rise."),
    "T3": (8, "the dose-normalized exposure contrast excluded equality", "Compare dose-dependent input and disposition explanations against the formal exposure contrast."),
    "T3p": (8, "the matched dose-normalized concentrations excluded proportionality", "Compare dose-dependent input and disposition explanations against the formal concentration contrast."),
    "T4": (6, "the matched extravascular-to-IV ratio declined", "Investigate the shared one-compartment assumption using the qualified IV reference."),
    "T5": (9, "one positive concentration multiplier could not describe all matched times", "Compare condition effects that change shape as well as amplitude."),
    "RATE_ONLY": (9, "complete dose-normalized exposure differed under shared linear disposition", "Evaluate an extent or disposition change within the qualified condition contrast."),
}


def formal_signals(study, ds, parameters, ivs, individual_rebounds):
    source = {d["card"]["dataset_id"]:d for d in ds}
    param_ids = {d["card"]["dataset_id"] for d in parameters}
    ev_ids = source.keys() | param_ids
    found = set()
    for c in study.get("candidate_assessments", []):
        for p in c.get("profile_assessments", []):
            cid = p["dataset_id"]
            if cid not in source or p.get("route_scope") != "APPLICABLE" or p.get("formal_status") != EXCLUDED:
                continue
            d = source[cid]
            if not d["card"].get("tests_allowed") or not any(s.get("series_id") == p.get("series_id") for s in d.get("series", [])):
                continue
            for t in p.get("tests", []):
                code = t.get("test")
                if code not in {"T1","T2"} or not firm(t) or not t.get("executed") or t.get("formal_status") != EXCLUDED:
                    continue
                if code == "T2" and (cid,p.get("series_id")) in individual_rebounds:
                    continue
                key = (code,cid,p.get("series_id"))
                if key in found:
                    continue
                found.add(key)
                n,why,priority = FORMAL[code]
                scope = f"{cid}, {p.get('series_label') or 'specified series'}"
                v = entry(study,"scoped_formal_exclusion",n,[cid],[],priority,
                          f"In {study['study_id']} ({scope}), {why} under the documented observation and model assumptions.")
                yield dict(v,request_key=code)
        for z in c.get("contrast_assessments", []):
            code,ids = z.get("test"),set(z.get("dataset_ids", []))
            if code not in FORMAL or code in {"T1","T2"} or not ids or z.get("formal_status") != EXCLUDED or not firm(z):
                continue
            if code == "T4":
                if len(ids & ivs) != 1 or len(ids & source.keys()) != 1 or len(ids) != 2:
                    continue
            elif not ids <= ev_ids:
                continue
            # Keep the caller's valid dose gate distinct from the gate for a single-dose shape.
            gate = "dose_series_allowed" if code in {"T3","T3p"} else "tests_allowed"
            if any(not source[i]["card"].get(gate,source[i]["card"].get("tests_allowed")) for i in ids & source.keys()):
                continue
            key = (code,tuple(sorted(ids)))
            if key in found:
                continue
            found.add(key)
            n,why,priority = FORMAL[code]
            v = entry(study,"scoped_formal_exclusion",n,ids,[],priority,
                      f"In {study['study_id']} ({', '.join(sorted(ids))}), {why} for the specified comparison.")
            yield dict(v,request_key=code if code != "T3p" else "T3")


def insufficient(study, ds, params):
    captured = sorted({d["card"]["dataset_id"] for d in ds+params})
    scope = f"{study['study_id']} ({', '.join(captured[:2])})" if captured else study["study_id"]
    if params and not ds:
        return entry(study,"insufficient_evidence",2,captured,[],"Verify parameter definitions and obtain timed concentration measurements.",
                     f"{scope} supplies reported parameters without an eligible observed curve to distinguish absorption mechanisms.")
    if ds and all(not d["card"].get("tests_allowed") for d in ds):
        return entry(study,"insufficient_evidence",1,captured,[],"Resolve the route, matrix or dosing gate before choosing an absorption model.",
                     f"{scope} has no eligible single-dose systemic curve or qualifying dose contrast.")
    if ds and all(not s.get("metrics",{}).get("n_quantified") for d in ds for s in d.get("series", [])):
        return entry(study,"insufficient_evidence",2,captured,[],"Recover quantified timed observations and retain the assay limits.",
                     f"{scope} has no quantified postdose series to distinguish absorption mechanisms.")
    return entry(study,"insufficient_evidence",3,captured,[],"Obtain a discriminating input or disposition measurement before preferring a model.",
                 f"{scope} supplies no eligible pattern that separates the proposed absorption mechanisms.")


def select(species, offers, fallback, tiers, policy):
    # Stable sorting selects an example for the same check; it never ranks different mechanisms at equal priority.
    order = lambda e:(e.get("request_key",e["kind"]),e["study_id"],tuple(e["dataset_ids"]),e["summary"])
    offers = sorted(offers,key=order)
    if offers:
        tier = min(tiers[v["kind"]] for v in offers)
        leaders = [v for v in offers if tiers[v["kind"]] == tier]
        representatives = {}
        for v in leaders:
            representatives.setdefault(v.get("request_key",v["kind"]),v)
        selected = list(representatives.values())
    else:
        selected = [min(fallback,key=order)]
    first = selected[0]
    labels = {"dose_peak_exposure":"slower absorption at higher doses","increased_peak_exposure":"higher normalized peaks",
              "group_rebound":"individual confirmation of a mean rebound","verified_individual_rebound":"two-phase input",
              "matched_terminal_slow_input":"slow input","matched_terminal_steeper_ev":"a steeper extravascular decline",
              "verify_identity":"animal identity","reconcile_sampling":"sampling-time alignment",
              "review_terminal_windows":"terminal-window sensitivity","sparse_rise":"early sampling",
              "T1":"the early-input assumption","T2":"the single-peak prediction","T3":"dose proportionality",
              "T4":"shared disposition","T5":"constant scaling","RATE_ONLY":"a rate-only change"}
    if len(selected) == 1:
        kind,priority,summary = first["kind"],first["priority"],first["summary"]
        candidate_ids = first["candidate_ids"]
    else:
        kind = "no_unique_leader"
        priority = "No single modeling check takes precedence across the scoped findings."
        scope = [f"{labels[z.get('request_key',z['kind'])]} in {z['study_id']}" for z in selected]
        summary = "Check " + " and ".join(scope[:2]) + " separately." + (" Further tied checks are linked." if len(scope)>2 else "")
        candidate_ids = []
    links = list(dict.fromkeys(z["evidence_link"] for z in selected if z["evidence_link"]))
    report = {"species":species,"kind":kind,"priority":priority,"summary":summary,
              "study_ids":sorted({v["study_id"] for v in selected}),"candidate_ids":candidate_ids,
              "dataset_ids":sorted({i for z in selected for i in z["dataset_ids"]}),
              "evidence_link":links[0] if links else "","evidence_links":links,"source_scopes":selected,
              "scope":" / ".join(v["study_id"] + " (" + ", ".join(v["dataset_ids"]) + ")" for v in selected),
              "linked_checks":[{"label":labels.get(v.get("request_key",v["kind"]),"source evidence"),
                                "study_id":v["study_id"],"evidence_link":v["evidence_link"]} for v in selected],
              "policy_version":policy["version"]}
    for field in policy["report_requirements"]["scope"]:
        if field not in report:
            raise ValueError(f"Unknown required species-priority field: {field}")
    return report


def build_species_priorities(studies, result, policy):
    """Return one next modeling check per species; all numerical evidence remains study-local."""
    tiers = validate(policy,result)
    offers, fallback = defaultdict(list),defaultdict(list)
    for study in studies:
        sid = study["study_id"]
        ids = set(study.get("dataset_ids", []))
        local = [d for d in result.get("datasets", []) if d["card"].get("study") == sid and d["card"]["dataset_id"] in ids]
        reported = [d for d in result.get("reported_parameters", []) if d["card"].get("study") == sid and d["card"]["dataset_id"] in ids]
        species = {taxon(d["card"]) for d in local+reported}
        if not species:
            species = {study.get("species_group") or "Species not stated"}
        for sp in species:
            ds = [d for d in local if taxon(d["card"]) == sp]
            params = [d for d in reported if taxon(d["card"]) == sp]
            fallback[sp].append(insufficient(study,ds,params))
            if sp == "Species not stated" or " / " in sp:
                continue  # A mixed or unknown source cannot establish a species-specific priority.
            ivs = {d["card"]["dataset_id"] for d in result.get("iv_references", []) if
                   d["card"].get("study") == sid and taxon(d["card"]) == sp}
            profile_offers = list(profile_signals(study,ds,policy["rebound_criterion"]))
            rebounds = {(z["dataset_ids"][0],z["series_id"]) for z in profile_offers if z["kind"] == "verified_individual_rebound"}
            offers[sp].extend(profile_offers)
            offers[sp].extend(dose_signals(study,ds,result.get("dose_series",[]),policy["dose_criterion"]))
            offers[sp].extend(comparison_signals(study,ds,result,ivs))
            offers[sp].extend(formal_signals(study,ds,params,ivs,rebounds))
    return [select(sp,offers[sp],fallback[sp],tiers,policy) for sp in sorted(fallback)]


