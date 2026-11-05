"""Observed-window exposures and matched contrasts for absorption rules r4.3."""
from itertools import combinations
from math import exp, log, sqrt
from statistics import mean, variance


def known(value):
    return value is not None and str(value).strip().upper() not in {"", "NOT_FOUND", "UNKNOWN", "NOT REPORTED", "N/A", "SOURCE NOT ESTABLISHED","UNVERIFIED","NONE"}


def semantic(card, field):
    value=card.get(field)
    if field=="exposure_basis" and str(card.get("matrix","")).lower()=="plasma":
        if str(value).strip().lower() in {"total","plasma total","plasma total only","total plasma"}:
            return "total"
    return str(value).strip().casefold() if known(value) else None


def terminal_comparison(a,b):
    pairs=[]
    for x in a.get("terminal_windows",[]):
        for y in b.get("terminal_windows",[]):
            if not all(w.get("thalf") and (w.get("span_ratio") or 0)>=2 and w["slope"]<0 for w in (x,y)):
                continue
            ax=[x["start"],x.get("end",a["_t"][-1])]
            bx=[y["start"],y.get("end",b["_t"][-1])]
            ratio=x["thalf"]/y["thalf"]
            grade=("EV_STEEPER" if ratio<.8 else "PARALLEL_IN_WINDOW" if ratio<1.25 else
                   "EV_SHALLOWER_MODERATE" if ratio<2 else "EV_SHALLOWER_MARKED")
            pairs.append({"ev_window_h":ax,"iv_window_h":bx,"ratio":ratio,"grade":grade,"same_window":ax==bx})
    grades=sorted({p["grade"] for p in pairs if p["same_window"]})
    return {"pairs":pairs,"comparable_grades":grades,"window_sensitive":len(grades)>1,
            "flip_flop_reading":"UNRESOLVED","comparison_status":"COMPARABLE_WINDOW" if grades else
            "DIFFERENT_WINDOWS" if pairs else "QUALIFIED_WINDOW_MISSING"}


def grid(series, metrics):
    points = {}
    for p in series:
        t = p["t"]
        if t < 0:
            continue
        y = p.get("c")
        if t in points or p["status"] not in {"QUANTIFIED", "MEASURED_ZERO"} or y is None or y < 0:
            points[t] = None
        else:
            points[t] = float(y)
    if metrics.get("zero_anchor_allowed"):
        points.setdefault(0.0, 0.0)
    return points


def window(grids, start=None, end=None):
    """Use only common observed endpoints. Never bridge a censored or conflicting row."""
    common = sorted(set.intersection(*[{t for t, y in g.items() if y is not None} for g in grids]))
    result = {"status": "CANNOT_ASSESS", "common_times_h": common,
              "method": "linear-up/log-down", "areas": [], "same_grid": False}
    if len(common) < 2:
        return result | {"reason": "Fewer than two shared observed endpoints"}
    a, b = common[0] if start is None else start, common[-1] if end is None else end
    if a not in common or b not in common or a >= b:
        return result | {"reason": "The specified endpoints are unavailable"}
    times = [sorted(t for t in g if a <= t <= b) for g in grids]
    result.update(start_h=a, end_h=b, grids_h=times, same_grid=all(ts == times[0] for ts in times))
    if any(g[t] is None for g, ts in zip(grids, times) for t in ts):
        return result | {"reason": "A censored, missing or conflicting row interrupts the common window"}
    for g, ts in zip(grids, times):
        area = 0.0
        for s, t in zip(ts, ts[1:]):
            x, y = g[s], g[t]
            mean = (x - y) / log(x / y) if x > y > 0 else (x + y) / 2
            area += (t - s) * mean
        result["areas"].append(area)
    return result | {"status": "DESCRIPTIVE", "selection": "first and last shared usable time, coverage rule"}


def _match(a, b, *, near):
    """Reserve exact matches, then choose unique nearest partners for the sensitivity scan."""
    left = {t: i for i, t in enumerate(a["_t"])}
    right = {t: j for j, t in enumerate(b["_t"])}
    pairs = [(left[t], right[t]) for t in sorted(left.keys() & right.keys())]
    if not near:
        return pairs
    used_i, used_j = {i for i, _ in pairs}, {j for _, j in pairs}
    offsets = sorted((abs(s-t),i,j) for s,i in left.items() for t,j in right.items()
                     if i not in used_i and j not in used_j and abs(s-t) <= max(0.02,0.05*max(abs(s),abs(t)))+1e-12)
    for _,i,j in offsets:
        if i not in used_i and j not in used_j:
            pairs.append((i,j))
            used_i.add(i)
            used_j.add(j)
    return sorted(pairs)


def _bounded(point, c, card):
    lo, hi = point.get("lo"), point.get("hi")
    if lo is not None and hi is not None and 0 <= lo <= c <= hi:
        basis = str(point.get("bounds_basis", "")).upper()
        alpha=point.get("bounds_error_level")
        justified = basis=="DETERMINISTIC" or (basis in {"SIMULTANEOUS","CALIBRATED_GLOBAL"} and isinstance(alpha,(int,float))
                    and 0<alpha<1 and known(card.get("bounds_procedure")))
        return lo, hi, justified and known(point.get("bound_source"))
    return c * .95, c * 1.05, False


def ratio_rows(a, b, a_points, b_points, a_card, b_card, near=True):
    left = {p["t"]:p for p in a_points}
    right = {p["t"]:p for p in b_points}
    rows = []
    for i, j in _match(a, b, near=near):
        ta, tb, x, y = a["_t"][i], b["_t"][j], a["_c"][i], b["_c"][j]
        pa, pb = left.get(ta, {}), right.get(tb, {})
        if any(p.get("time_valid") is False or not all(isinstance(v,(float,int)) for v in
               (p.get("t_lo",t),p.get("t_hi",t))) for p,t in ((pa,ta),(pb,tb))):
            continue
        lo_a, hi_a, bound_a = _bounded(pa, x, a_card)
        lo_b, hi_b, bound_b = _bounded(pb, y, b_card)
        if y <= 0 or lo_b <= 0:
            continue
        # A source may supply prespecified widened simultaneous bounds for the
        # entire search. Record them separately from the primary intervals.
        wider = [pa.get("widened_lo"),pa.get("widened_hi"),pb.get("widened_lo"),pb.get("widened_hi")]
        use_wider = all(isinstance(v,(float,int)) for v in wider) and 0<=wider[0]<=lo_a<=hi_a<=wider[1] and 0<wider[2]<=lo_b<=hi_b<=wider[3]
        rows.append({"t": ta, "reference_t": tb, "delta_h": abs(ta-tb), "a_concentration": x,
                     "b_concentration": y, "records":[pa.get("record_id"),pb.get("record_id")],
                     "c": x/y, "q": x/y, "lo":lo_a/hi_b, "hi":hi_a/lo_b,
                     "bounds_justified":bound_a and bound_b,
                     "widened_bounds":[wider[0]/wider[3],wider[1]/wider[2]] if use_wider and
                     known(pa.get("widening_source")) and known(pb.get("widening_source")) else None,
                     "a_time_bounds":[pa.get("t_lo",ta),pa.get("t_hi",ta)],
                     "b_time_bounds":[pb.get("t_lo",tb),pb.get("t_hi",tb)]})
    return rows


def _margin(rows, test):
    if len(rows) < (2 if test == "T4" else 3):
        return None, []
    if test == "T4":
        eligible = [(a["lo"]-b["hi"], i,j) for (i,a),(j,b) in combinations(enumerate(rows),2)
                    if a["a_time_bounds"][1] < b["a_time_bounds"][0] and a["b_time_bounds"][1] < b["b_time_bounds"][0]]
        if not eligible:
            return None, []
        value, i, j = max(eligible)
    else:
        i = max(range(len(rows)), key=lambda idx:rows[idx]["lo"])
        j = min(range(len(rows)), key=lambda idx:rows[idx]["hi"])
        value = rows[i]["lo"] - rows[j]["hi"]
    return value, [rows[i]["records"],rows[j]["records"]]


def _decision(rows, test, reasons):
    margin, witness = _margin(rows,test)
    removal = []
    for i, r in enumerate(rows):
        m, _ = _margin(rows[:i]+rows[i+1:],test)
        removal.append({"removed_records":r["records"], "margin":m, "outcome":
                        "NOT_ASSESSABLE" if m is None else "CONTRADICTION" if m>0 else "NO_CONTRADICTION"})
    if any(r["delta_h"] > 0 or r["a_time_bounds"] != r["b_time_bounds"] or
           r["a_time_bounds"][0] != r["a_time_bounds"][1] for r in rows):
        reasons.append("Sampling-time mismatch or uncertainty has no justified concentration-change bound")
    if any(not r["bounds_justified"] for r in rows):
        reasons.append("Project tolerance or marginal uncertainty does not bound the complete search")
    flags = []
    if margin is None:
        reasons.append("Insufficient ordered, usable paired observations")
    widened=None
    if margin is not None and margin>0:
        if all(r["widened_bounds"] for r in rows):
            widened,_=_margin([r | {"lo":r["widened_bounds"][0],"hi":r["widened_bounds"][1]} for r in rows],test)
        else:
            reasons.append("No prespecified uncertainty-widening analysis")
        if any(x["outcome"]=="NOT_ASSESSABLE" for x in removal):
            reasons.append("Independent support after removal could not be assessed")
    if reasons:
        label = "CANNOT_ASSESS"
        if margin is not None:
            flags.append("SENSITIVITY_ONLY")
    elif margin > 0 and widened is not None and widened>0 and all(x["outcome"]=="CONTRADICTION" for x in removal):
        label = "EXCLUDED_UNDER_STATED_ASSUMPTIONS"
    else:
        label = "NOT_EXCLUDED"
    if margin is not None and margin > 0 and any(x["outcome"]=="NO_CONTRADICTION" for x in removal):
        flags.append("SINGLE_POINT_SUPPORT")
    if margin is not None and margin>0 and widened is not None and widened<=0:
        flags.append("BORDERLINE")
    return {"formal_status":label, "flags":flags, "margin":margin, "widened_margin":widened, "witness":witness, "removal":removal,
            "missing_premises":reasons, "conditional_direction":"NOT_ASSESSABLE" if margin is None else
            "CONTRADICTION" if margin>0 else "NO_CONTRADICTION"}


def _comparison_reasons(a, b):
    reasons=[]
    for key in ("matrix","unit","drug","analyte","exposure_basis","origin","occasion","species"):
        if semantic(a,key) is None or semantic(a,key)!=semantic(b,key):
            reasons.append(f"Common {key} is unverified")
    if any("endogenous" in str(c.get("origin","")).lower() and c.get("baseline_corrected") is not True for c in (a,b)):
        reasons.append("Endogenous contribution is unresolved")
    if any(c.get("record_level")=="GROUP_MEAN" for c in (a,b)):
        if not all(c.get("common_population_supported") is True and known(c.get("common_population_evidence")) for c in (a,b)):
            reasons.append("A common population and individual-level relationship have not been established")
    return reasons


def raw_scale_constraints(left, right):
    """Solve L_A <= c U_B and c L_B <= U_A at exact times for c>0."""
    def by_time(points):
        result={}
        for p in points:
            if p["t"]<0:
                continue
            result[p["t"]]=p if p["t"] not in result else {}
        return result
    lhs,rhs=by_time(left),by_time(right)
    constraints=[]
    for time in sorted(lhs.keys() & rhs.keys()):
        a,b=lhs[time],rhs[time]
        if any(p.get("time_valid") is False or p.get("status") not in {"QUANTIFIED","MEASURED_ZERO","BLQ","ABOVE_ULOQ"} for p in (a,b)):
            continue
        la,ua,lb,ub=a.get("lo"),a.get("hi"),b.get("lo"),b.get("hi")
        if la is None or lb is None:
            continue
        impossible=bool(ub==0 and la>0 or ua==0 and lb>0)
        lower=la/ub if ub is not None and ub>0 else 0.0
        upper=ua/lb if ua is not None and lb>0 else None
        constraints.append({"time_h":time,"record_ids":[a.get("record_id"),b.get("record_id")],
                            "lower":lower,"upper":upper,"incompatible_with_positive_scale":impossible})
    lo=max((r["lower"] for r in constraints),default=None)
    hi=min((r["upper"] for r in constraints if r["upper"] is not None),default=None)
    impossible=any(r["incompatible_with_positive_scale"] for r in constraints)
    return {"rows":constraints,"lower":lo,"upper":hi,"empty_intersection":(impossible or (hi is not None and lo>hi)) if constraints else None}


def individual_contrast(members):
    """Compare animal AUCs using independent groups or paired two-period AB/BA data."""
    from scipy.stats import t as student
    sources=sorted(members,key=lambda d:d["card"]["dose_mg_per_kg"])
    selected=(sources[0],sources[-1])
    ds=[x["card"]["dose_mg_per_kg"] for x in selected]
    result={"status":"INDIVIDUAL_CONTRAST","t3_label":"CANNOT_ASSESS","t3_flags":[],
            "doses":ds,"t3_data_level":"INDIVIDUAL","t3p":{"t3p_label":"CANNOT_ASSESS"}}
    arms=[[(s,grid(s["points"],s["metrics"])) for s in x["series"]] for x in selected]
    grids=[g for arm in arms for _,g in arm]
    if min(map(len,arms))<2:
        return result | {"t3_reason":"At least two verified serial animals are required in each group"}
    win=window(grids)
    result["observed_window"]=win
    if not win["areas"] or min(win["areas"])<=0:
        return result | {"t3_reason":win.get("reason","Positive AUCs required")}
    split=len(arms[0])
    logs=[[log(v/dose) for v in group] for dose,group in zip(ds,(win["areas"][:split],win["areas"][split:]))]
    result.update(R_window=exp(mean(logs[1])-mean(logs[0])),window_end_h=win["end_h"],window_start_h=win["start_h"])
    cards=[x["card"] for x in selected]
    design=str(cards[0].get("study_design","")).upper()
    view=[str(c.get("study_design","")).upper() for c in cards]
    gates=[]
    if view[0]!=view[1] or len(set(ds))!=2:
        gates.append("Incompatible design or dose contrast")
    if not win["same_grid"]:
        gates.append("Different quadrature grids")
    if not all(c.get("superposition_premises_supported") is True and
               known(c.get("superposition_evidence") or c.get("superposition_premises_evidence")) for c in cards):
        gates.append("Baseline, proportional administration and group comparability require source support")
    if design in {"CROSSOVER","PAIRED_CROSSOVER","TWO_PERIOD_CROSSOVER"}:
        # Verified animal keys and treatment periods must come from the record.
        periods=[c.get("period_by_subject",{}) for c in cards]
        subject_maps=[c.get("subject_by_series",{}) for c in cards]
        ids=[[sub.get(s["series_id"]) for s,_ in arm] for sub,arm in zip(subject_maps,arms)]
        if not all(isinstance(p,dict) and p for p in periods) or any(None in g or len(set(g))!=len(g) for g in ids) or set(ids[0])!=set(ids[1]):
            return result | {"t3_reason":"Verified subject pairing and AB/BA periods are required; marginal summaries cannot supply covariance"}
        if not all(c.get("carryover_controlled") is True for c in cards):
            gates.append("Washout and carryover checks are required")
        def estimate(values,drop=None):
            rows=[dict(zip(arm,vals)) for arm,vals in zip(ids,values)]
            strata=[[],[]]
            for animal in ids[0]:
                if animal==drop: continue
                order=(periods[0].get(animal),periods[1].get(animal))
                if order not in ((1,2),(2,1)):return None
                strata[order==(1,2)].append(rows[1][animal]-rows[0][animal])
            if min(map(len,strata))<2:return None
            return interval(strata,paired=True)
        units=ids[0]
    elif design in {"PARALLEL","INDEPENDENT_PARALLEL"}:
        def estimate(values,drop=None):
            samples=[[v for i,v in enumerate(vs) if (a,i)!=drop] for a,vs in enumerate(values)]
            if min(map(len,samples))<2:return None
            return interval(samples)
        units=[(a,i) for a,arm in enumerate(arms) for i in range(len(arm))]
    else:
        return result | {"t3_reason":"Independent parallel or qualified paired crossover design required"}
    def interval(samples,paired=False):
        n=[len(x) for x in samples]
        vs=[variance(x)/k for x,k in zip(samples,n)]
        if sum(vs)<=0:return None
        df=sum(vs)**2/sum(v*v/(k-1) for v,k in zip(vs,n))
        effect=(mean(samples[0])+mean(samples[1]))/2 if paired else mean(samples[1])-mean(samples[0])
        se=sqrt(sum(vs))/(2 if paired else 1)
        crit=student.ppf(.975,df)
        return {"R":exp(effect),"ci":[exp(effect-crit*se),exp(effect+crit*se)],"ci_level":.95,
                "df":df,"p":float(2*student.sf(abs(effect/se),df))}
    primary=estimate(logs)
    if primary is None:
        return result | {"t3_reason":"Insufficient residual variance or sequence support"}
    contradict=lambda v:v["ci"][0]>1 or v["ci"][1]<1
    removed=[{"animal":str(unit),"result":estimate(logs,unit)} for unit in units]
    if contradict(primary) and any(x["result"] is None for x in removed):gates.append("Removal leaves insufficient support")
    label="CANNOT_ASSESS" if gates else "EXCLUDED_UNDER_STATED_ASSUMPTIONS" if contradict(primary) and all(contradict(x["result"]) for x in removed) else "NOT_EXCLUDED"
    result.update(primary,t3_label=label,t3_reason="; ".join(gates) or "Predefined high-versus-low individual log AUC/D contrast",
                  removal=removed,dose_pair=ds,R_window=primary["R"],estimand="geometric mean ratio of individual AUC/dose",
                  method="Welch on independent log AUC/dose" if design in {"PARALLEL","INDEPENDENT_PARALLEL"} else "Average of the AB and BA within-subject contrasts, adjusted for period")
    timed=[]
    for t in win["common_times_h"]:
        if t<=0 or any(g[t] is None or g[t]<=0 for g in grids):continue
        values=[[log(g[t]/ds[a]) for _,g in arm] for a,arm in enumerate(arms)]
        x=estimate(values)
        if x: timed.append({"t":t,**x})
    if timed:
        from .eda_absorption import holm
        pv=[x["p"] for x in timed]; adjusted=holm(pv)
        for x,p_adj in zip(timed,adjusted): x["p_holm"]=p_adj
        significant=any(p<.05 for p in adjusted)
        stable=len(timed)>1 and all(any(p<.05 for p in holm(pv[:i]+pv[i+1:])) for i in range(len(timed)))
        result["t3p"]={"t3p_label":"CANNOT_ASSESS" if gates or (significant and len(timed)<2) else
                      "EXCLUDED_UNDER_STATED_ASSUMPTIONS" if significant and stable else "NOT_EXCLUDED",
                      "role":"Supplementary family, two-sided Holm 5%","t3p_times":[x["t"] for x in timed],"comparisons":timed}
    return result


def ev_iv(a_card, a, b_card, b, a_points=(), b_points=()):
    reasons = _comparison_reasons(a_card,b_card)
    mode = str(b_card.get("iv_mode") or b_card.get("route_detail","")).upper()
    if "BOLUS" not in mode and "INFUSION" not in mode:
        reasons.append("IV input mode is unreported")
    rows = ratio_rows(a,b,a_points,b_points,a_card,b_card)
    if "INFUSION" in mode:
        end = b_card.get("infusion_duration_h")
        if isinstance(end,(int,float)) and end>0:
            rows=[r for r in rows if r["reference_t"]>end]
        else:
            reasons.append("IV infusion end time is unavailable")
    if not all(c.get("shared_one_compartment_supported") is True and known(c.get("shared_one_compartment_evidence")) for c in (a_card,b_card)):
        reasons.append("A shared linear one-compartment disposition with common k is unverified")
    if not all(c.get("zero_state_supported") is True or (c.get("zero_initial_state_supported") is True and known(c.get("baseline_evidence"))) for c in (a_card,b_card)):
        reasons.append("A common zero initial state is unverified")
    exact = [r for r in rows if r["delta_h"]==0]
    t4 = _decision(exact,"T4",reasons.copy())
    scenario = _decision(rows,"T4",reasons.copy())
    result = {"ev":a_card["dataset_id"],"iv":b_card["dataset_id"],"comparison_basis":
              "IV_SAME_STUDY" if a_card["study"]==b_card["study"] else "IV_OTHER_STUDY",
              "dose_ev":a_card.get("dose_mg_per_kg"),"dose_iv":b_card.get("dose_mg_per_kg"),
              "q":rows,"t4":t4,"timing_sensitivity":scenario, "mt4":scenario["margin"],"mt4_pair":scenario["witness"],
              "t4_label":t4["formal_status"],"t4_flags":t4["flags"],"t4_reason":"; ".join(t4["missing_premises"]),
              "time_match":[a_card.get("sampling_time_basis","AS_RECORDED"),b_card.get("sampling_time_basis","AS_RECORDED")],
              "terminal_comparison":terminal_comparison(a,b), "f_status":"NOT_ESTIMABLE",
              "f_caveats":[],"f_window":None,"absolute_f":None,"absolute_f_status":"NOT_ESTIMABLE"}
    grids=[grid(a_points,a),grid(b_points,b)]
    exposure = window(grids)
    result["observed_window"] = exposure
    if exposure["status"]=="CANNOT_ASSESS":
        return result | {"f_reason":exposure["reason"]}
    if not known(a_card.get("dose_basis")) or a_card["dose_basis"]!=b_card.get("dose_basis"):
        return result | {"f_reason":"Dose bases are missing or differ"}
    if not all(isinstance(d,(int,float)) and d>0 for d in (result["dose_ev"],result["dose_iv"])):
        return result | {"f_reason":"Positive source-supported doses are required"}
    if a_card.get("unit")!=b_card.get("unit") or not known(a_card.get("unit")):
        return result | {"f_reason":"Concentration units are unverified or differ"}
    if known(a_card.get("analyte")) and known(b_card.get("analyte")) and a_card["analyte"]!=b_card["analyte"]:
        return result | {"f_reason":"EV and IV analytes differ"}
    for k in ("matrix_category","species","drug","exposure_basis","matrix","analyte_role"):
        if semantic(a_card,k) and semantic(b_card,k) and semantic(a_card,k)!=semantic(b_card,k):
            return result | {"f_reason":f"EV/IV {k} differs. An independent conversion or comparable reference is required."}
    if any(c.get("matrix_category")!="PLASMA_SERUM_BLOOD" for c in (a_card,b_card)):
        return result | {"f_reason":"A qualified central matrix is required"}
    ea, eb=exposure["areas"]
    if eb<=0:
        return result | {"f_reason":"IV window AUC is zero"}
    def normalized(x,y):
        return x/result["dose_ev"]/(y/result["dose_iv"]) if y>0 else None
    ratio=normalized(ea,eb)
    end=exposure["end_h"]
    caveats=[]
    if not exposure["same_grid"]:
        caveats.append("UNEQUAL_QUADRATURE_GRIDS")
    if exposure["start_h"]>0:
        caveats.append("IV_EARLY_AREA_MISSING")
    if mode not in {"BOLUS","IV_BOLUS","INFUSION","IV_INFUSION"}:
        caveats.append("IV_MODE_UNKNOWN")
    clearance=all(c.get("shared_linear_clearance_supported") is True and known(c.get("clearance_evidence")) for c in (a_card,b_card))
    if not clearance:
        caveats.append("CLEARANCE_UNVERIFIED")
    if not known(a_card.get("analyte")) or not known(b_card.get("analyte")):
        caveats.append("ANALYTE_UNVERIFIED")
    if any(c.get("endogenous_review_required") or (str(c.get("origin","")).upper() in {"ENDOGENOUS","MIXED"}
           and c.get("assay_specificity")!="EXOGENOUS_SPECIFIC") for c in (a_card,b_card)):
        return result | {"f_reason":"Unresolved endogenous contribution to total exposure"}
    short=None
    if len(exposure["common_times_h"])>=3:
        short=window(grids,start=exposure["start_h"],end=exposure["common_times_h"][-2])
        if short["areas"]:
            short["normalized_exposure_ratio"]=normalized(*short["areas"])
    def tail(m,area,last):
        chosen=m.get("terminal_selected")
        if not chosen or not m.get("_t") or m["_t"][-1]!=end or area<=0 or chosen["slope"]>=0:
            return None
        return last/(-chosen["slope"]*area+last)
    tails=[tail(m,area,g[end]) for m,g,area in zip((a,b),grids,(ea,eb))]
    adequate=all(x is not None and x<=0.05 for x in tails)
    if not adequate:
        caveats.append("TAIL_COVERAGE_UNRESOLVED")
    if ratio>1:
        caveats.append("WINDOW_RATIO_ABOVE_ONE")
    compatible=all(semantic(a_card,k) and semantic(a_card,k)==semantic(b_card,k) for k in ("drug","matrix","exposure_basis","analyte"))
    pres=exposure["start_h"]==0 and adequate and clearance and compatible and not any(k in caveats for k in
          ("ANALYTE_UNVERIFIED","UNEQUAL_QUADRATURE_GRIDS","IV_MODE_UNKNOWN")) and result["comparison_basis"]=="IV_SAME_STUDY"
    return result | {"f_status":"ESTIMATED_WINDOW" if pres else "INCOMPLETE_EXPOSURE_RATIO",
                     "f_reason":"Qualified observed window; tail shares rely on the terminal fits." if pres else
                     "Observed window ratio only; early coverage, terminal coverage or shared clearance remains unverified.",
                     "f_window":ratio, "window_h":end,"shorter_window":short,
                     "window_start_h":exposure["start_h"], "iv_early_area_direction":"UNKNOWN" if "BOLUS" not in mode else "MISSING_AREA_IF_NO_ZERO_SAMPLE",
                     "f_caveats":caveats,"ev_tail_share":tails[0],"iv_tail_share":tails[1]}


def condition_pair(a_card, a, b_card, b, a_points=(), b_points=()):
    diff = [k for k in ("route_detail","dose_mg_per_kg","matrix","species","study","record_level","dose_basis","occasion")
            if a_card.get(k)!=b_card.get(k)]
    rows=ratio_rows(a,b,a_points,b_points,a_card,b_card)
    exact=[r for r in rows if r["delta_h"]==0]
    reasons=_comparison_reasons(a_card,b_card)
    unresolved=[p.get("record_id") for p in [*a_points,*b_points] if p.get("status") in {"BLQ","ABOVE_ULOQ","DUPLICATE_CONFLICT","MEASURED_ZERO"} or p.get("c")==0]
    if unresolved:
        reasons.append("Censored/zero rows require raw interval constraints before formal exclusion: "+", ".join(str(x) for x in unresolved))
    if not known(a_card.get("dose_basis")) or a_card.get("dose_basis")!=b_card.get("dose_basis"):
        reasons.append("Dose bases across conditions are unverified or differ")
    decision=_decision(exact,"T5",reasons.copy())
    scenario=_decision(rows,"T5",reasons.copy())
    exposure=window([grid(a_points,a),grid(b_points,b)])
    result={"a":a_card["dataset_id"],"b":b_card["dataset_id"],"ratio_direction":"A / reference, raw concentrations",
            "differing_attributes":diff,"confounded":len(diff)>1,"intervals":rows,"exact_pairs":len(exact),
            "t5":decision,"timing_sensitivity":scenario,"t5_label":decision["formal_status"],
            "t5_flags":list(dict.fromkeys(decision["flags"]+scenario["flags"])),"observed_window":exposure,
            "raw_interval_constraints":raw_scale_constraints(a_points,b_points),
            "rate_only_label":"CANNOT_ASSESS","rate_only_reason":"Independent two-sided complete exposure bounds and shared clearance are required"}
    if rows:
        result.update(c_lower=max(x["lo"] for x in rows),c_upper=min(x["hi"] for x in rows))
    return result
