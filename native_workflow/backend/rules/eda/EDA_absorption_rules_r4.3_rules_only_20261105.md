# EDA absorption rules, items 16–23 (r4.3, 2026-11-05)

Revision of the supplied r4.2 rules-only text (SHA-256 `d620163e5a996af15c3201962163a3fcce5d4029945f618c37bde48fad9c4a28`). It incorporates the r4.2 review corrections and uses the nine-question presentation order in A0.11. Item numbers, test identifiers and figure panels are retained. Section A specifies the scientific rules; section B lists implementation requirements. Historical test results apply to their original version.

The input-model definitions in A0.9 apply to Q1–Q4. For terminal half-life versus the EV/IV concentration ratio, see item 18 (Q6). For dose proportionality versus scaling across conditions, see items 19 (Q8) and 23 (Q9).

## A. Rule text

### A0 | SHARED DEFINITIONS FOR ITEMS 16–23

Items 16–23 use the definitions below. An item states only what differs.

#### A0.1 Order of execution

0. Data card (A0.11) and gates (A0.2): route and administration, time origin and baseline (item 21), data status (A0.5), data support and uncertainty (A0.4).
1. Item 16, onset: did input start at the dose time?
2. Item 17, rising limb: description of the rise.
3. Item 20, multiphase: peaks, dips, shoulders, plateaus and the post-peak decline.
4. Item 18, terminal phase and flip-flop.
5. Item 19, dose dependence.
6. Item 22, extent (systemic F).
7. Item 23, comparison across conditions.
8. Hand-off (A0.9) and status board (A0.11).

Execution follows the dependencies above. The question numbers in A0.11 specify presentation order. Verify serial animal identity on the data card before T2. Item 22 consumes item 19 when dose dependence matters even though its question is presented first.

#### A0.2 Gates

1. Route and administration.
   - IV profiles are out of scope for absorption. Within EDA, IV data serve as references (items 18, 19, 20, 22 and 23). Item 17 also specifies how a suitable IV reference can support a subsequent modeling-stage reconstruction.
   - Known finite administration (pump, patch, injection or instillation over a stated time; A0.8): the shape during the administration period is not read as absorption (KNOWN_INPUT_PERIOD).
   - Inhaled or intratracheal routes: record the dose basis (A0.8) and set PULMONARY_AND_GI_UNRESOLVED unless A0.8 lifts it.
   - ROUTE_UNKNOWN (the source does not state the route of the PK data): items 16–23 are not run; values are background only.
2. Time origin and baseline: item 21.
3. Data status: A0.5. A profile with every sample BLQ is NOT_ASSESSABLE for items 16–23 and is never reported as "no absorption".
4. Data support and uncertainty: A0.4.

A gate failure gives the outcome stated in the item, with the reason.

#### A0.3 Exclusion principle and evidence labels

Principle

| Topic | Rule |
|---|---|
| Default | Start each candidate as an open hypothesis. Assign NOT_EXCLUDED only after an eligible test was actually performed. Missing or ineligible evidence gives CANNOT_ASSESS. |
| What is excluded | A complete model combination: input + disposition + initial state + observed signal. Mechanism names alone ("first-order absorption", "transit") are never excluded. |
| Basis | A proven necessary condition of that combination, with no compatible value inside the allowed data range. |
| Robustness | The contradiction must hold under the error combination most favourable to the candidate. |
| Data limits | When premises are unclear, or the error range has no source, no exclusion is made; the result is a sensitivity result. |
| Shape descriptions | Reported separately; never turned into a model selection. |
| Hand-off | Candidates not excluded, the evidence for each exclusion, the assumptions used and the missing information. Goodness of fit and complexity are compared in modeling. |

Main conclusions and attachable flags

| Situation | Main conclusion | Attachable flags |
|---|---|---|
| Formal assessment unavailable (missing premises, unknown relevant error, insufficient sampling or unsupported timing match) | CANNOT_ASSESS | SENSITIVITY_ONLY when a defined conditional calculation was possible. Retain its direction, margin and witness points. |
| Assessable, exclusion criterion not met | NOT_EXCLUDED | as applicable |
| Contradiction in the main analysis, but a pre-set robustness gate is not passed | NOT_EXCLUDED | BORDERLINE or SINGLE_POINT_SUPPORT, stated as "exclusion deferred" |
| Criterion and evidence gates both pass | EXCLUDED_UNDER_STATED_ASSUMPTIONS | none of the flags defined as blocking exclusion |

- BORDERLINE: a contradiction disappears in the prespecified, explicitly sized uncertainty-widening analysis. If the widening rule was not prespecified, report the exploratory margin without formal exclusion.
- SINGLE_POINT_SUPPORT: removing at least one prespecified unit leaves an assessable test without contradiction. Record the removed unit and rerun the full search. If removal leaves too few data, report that separate outcome under the removal procedure.
- SENSITIVITY_ONLY: the error range has no source (project-set), or the uncertainty of the comparison cannot be estimated.
- SENSITIVITY_ONLY blocks formal exclusion regardless of the sign of a margin. Report both the formal status and the conditional numerical result. Digitization bounds alone do not cover uncertainty of a group mean. Record which source of uncertainty is missing.

Removal (leave-one-out) procedure
1. Remove the specified unit.
2. Rerun the complete test on the remaining data.
3. Classify: contradiction remains / assessable without contradiction / not assessable.
- T1 and T2: rescan all allowed point pairs or triples of the remaining data, not only the original witness points.
- If removal leaves too few data, mark that check not assessable. The unit cannot be identified as the cause of loss of a contradiction. If independent support is required and cannot be evaluated, withhold formal exclusion and state why.
- T3 removing an animal: a CI that now includes 1 may only reflect the smaller sample; report the change in both the ratio estimate and the CI.
- T3 removing a window end point: the window is not shortened silently; if the original window can no longer be computed, that sensitivity run is not assessable.

Basis of judgement (reported with every test result)
- T1, T2, T4 and T5 evaluate necessary conditions. Deterministic exclusion requires justified bounds for all relevant observations and the analysis unit. With statistical intervals, account for all searched times, pairs or triples through simultaneous coverage or a prespecified calibrated global procedure; report its error level. Separate marginal 95% intervals, assay acceptance limits and leave-one-out checks do not provide simultaneous coverage.
- T3: a CI judgement with statistical error risk. T3p: a multiple-test judgement (Holm) with statistical error risk.
- Assumed-error analyses: sensitivity result.

#### A0.4 Uncertainty used for allowed intervals

- Each concentration gets an allowed interval [L, U] with its source, and each time an interval [t⁻, t⁺] when actual sampling times are uncertain.
- Three sources are recorded separately and never substituted for each other:
  - analytical error (from the source's validation or QC data when reported);
  - individual or between-group variability (SD, CV, CI and n when reported);
  - digitization error (reading tolerance, absolute or relative, stated).
- The 15 % used in r3 is the ICH M10 assay-validation acceptance limit, not a per-sample error. It is kept only as a project heuristic, labelled as such, with a sensitivity check; results that depend on it are SENSITIVITY_ONLY.
- Tolerances are applied in concentration units before dividing by Δt or forming ratios.
- BLQ samples use U = LLOQ and L = 0; they are never filled with 0 or LLOQ/2 for a test.

#### A0.5 Data status outcomes (shared by items 16–23)

Data assigns each record its status (data preparation rules 4 and 5, EDA item 03): BLQ, above ULOQ, measured zero, not sampled, sample lost, not reported, unreadable, duplicate or replicate. Absorption items do not re-classify records; they apply the outcomes below.

| Data status | Outcome in items 16–23 |
|---|---|
| All samples BLQ | NOT_ASSESSABLE for every item; never "no absorption" |
| Peak above ULOQ | Cmax is a lower bound (">x"); items 17, 19, 22, 23 treat Cmax-based values as bounds |
| LLOQ unknown, or different between batches | Item 16 onset test not run; only the observation interval is reported |
| Two values at the same time | Data first decides replicate or conflict; Δt = 0 is never divided by (item 17); conflicts block tests that use that time |
| Not sampled, lost, not reported | No value is imputed; tests use the remaining points; when a gate needs that point, CANNOT_ASSESS |
| BLQ between quantified points | Flagged (INTERIOR_BLQ) and kept as an interval [0, LLOQ]; never silently replaced |
| Denominator zero or near zero (AUC, slope, concentration) | Ratio UNDEFINED; never reported as infinity or zero |

#### A0.6 Observed-window AUC (option B, decided 2026-11-04)

- EDA may compute an observed-window AUC from observed points only.
- One method: linear trapezoid on rising or flat segments, log trapezoid on falling segments where both ends are > 0. Use a linear segment for a valid zero endpoint where the log formula is undefined. A numerical quadrature rule approximates the between-sample trajectory. Apply A0.6 censoring rules before integration.
- The integral ends at the last quantified point or at the common window end T. No extrapolation.
- Use a prespecified common start and end with actual sampling support in every profile (a defensible dose-time zero may anchor an EV start). Record actual times, start gaps, grid and integration method. For formal comparisons require comparable quadrature grids or quantified integration error; unequal interior sampling can change the numerical AUC even when the true profiles are proportional. Do not interpolate missing endpoints. A window chosen by a fixed coverage rule is labelled as such.
- A predose design zero or measured zero may anchor a calculation when item 21 permits. A postdose BLQ is censored in [0,LLOQ]. If the project uses zero for leading BLQs in a descriptive AUC, label this as an imputation, retain the original flags, and report sensitivity to admissible censored values. End at the last quantified observation before terminal BLQs. For interior BLQ, show the gaps and withhold a full-window scalar/CI unless a prespecified method covers censoring. Do not infer a formal contrast from an imputed point estimate.
- Group-mean data: only the mean curve is integrated (GROUP_MEAN); the result is a point estimate. Individual AUCs and their comparison follow item 19 (T3). AUCs of geometric-mean and arithmetic-mean curves are not compared with each other.
- The same window and method are used for every profile in a comparison. Items 19, 22 and 23 use this definition.

#### A0.7 Descriptive regressions and post-peak decline

Terminal slope (consumers: items 18, 19, 22, 23)
- Fit ln(C) against actual time on each eligible window. For fitted slope b < 0, report λz = −b (1/time) and apparent t½ = ln(2)/λz (time). Use the same logarithm and time units for EV and IV.
- Candidate windows are contiguous suffixes: from the last valid quantified point backwards, at least 3 quantified points after Tmax (Tmax excluded).
- Require a negative slope and a prespecified minimum span in apparent half-lives. Use consecutive eligible points; keep interior gaps, BLQs and omitted times visible. Freeze the span threshold in the run configuration and report it. Never add terminal BLQ as zero before log regression.
- Among qualified windows choose the longest with adjusted R² no more than 0.0001 below the maximum. A high R² alone cannot establish a terminal phase.
- No qualified window → TERMINAL_SLOPE_NOT_ASSESSABLE. This is not evidence of fast or slow absorption and does not switch off T4.
- The slope is descriptive: it is reported as an apparent terminal slope and is never passed downstream as k, a half-life or an extrapolation constant, except for the tail share in item 22 and the complete-AUC check in item 23, where it is labelled.
- Window sensitivity: the result for every qualified window is reported.

Post-peak decline description (shared by items 19, 20, 23)
- Split the quantified post-peak points into an early and a late half (sharing the middle point when the count is odd); fit a log-linear slope to each half.
- Calculate the late/early ratio of slope magnitudes only when both halves have at least two distinct quantified times, both slopes are negative and the early slope is distinguishable from zero under the prespecified tolerance. Otherwise report the signed slopes and mark the ratio unavailable. A ratio ≥1.25 flags steepening and ≤0.80 flags flattening; both cutoffs are descriptive.
- DECLINE_STEEPENS is a shape description. Ordinary first-order absorption with linear elimination produces it, because ongoing absorption slows the early decline (R3-02). Its explanations are listed unranked (item 20).

Allowed descriptive regressions (complete list for items 16–23)
- Terminal slope as above.
- The split-half slopes above.
- Item 19 power-model slope b1 of log AUC (or log Cmax, stated) on log dose, descriptive.
- Item 19 T3 ratio and CI, and the T3p per-time ratios (statistical comparisons, not model fits).
No other fitting, smoothing or back-extrapolation is done in EDA.

#### A0.8 Route, administration and analyte fields

Route detail
- route_detail values for absorption: SC, IM, IP, PO, INTRATRACHEAL, INHALED_NOSE_ONLY, INHALED_WHOLE_BODY, INTRATHECAL, OTHER_EV. "IT" is not used. ROUTE_UNKNOWN when the source does not state the route (A0.2).

Known finite administration
- Fields: administration_start, administration_end (or duration), administration_rate when given, dose_basis (labelled amount or delivered amount; a patch's labelled content is not the delivered amount).
- Three layers are kept apart: delivery to the administration site (known from the design), release from the formulation, and systemic absorption. EDA sees only their combined result and attributes nothing to a single layer.
- During finite administration the delivery input and the systemic input can differ. Withhold T1 unless its systemic-input assumptions are independently justified from dose time. Ending delivery does not reset time zero or establish zero initial amounts for a new T1.
- Items 17 and 18: the shape during the administration period is KNOWN_INPUT_PERIOD. After administration ends, release from the site may continue; "administration ended" does not show that absorption has ended.

Inhaled and intratracheal dosing
- Inhaled dose basis: NOMINAL, EMITTED, DEPOSITED or UNKNOWN; items 19, 22 and 23 state which one is used.
- Plasma after inhalation can include pulmonary absorption and absorption of swallowed drug (oropharyngeal deposition, mucociliary clearance, grooming in nose-only or whole-body exposure).
- Intratracheal dosing documents where the dose was delivered. Mucociliary transport can still move drug toward the gut. Retain PULMONARY_AND_GI_UNRESOLVED for inhaled and intratracheal profiles unless independent route-specific evidence bounds the GI contribution (e.g. effective charcoal blockade or documented negligible enteral uptake for this preparation).

Analyte
- analyte_role: PARENT, METABOLITE, ACTIVE_FROM_PRODRUG, SUM.
- iv_reference_compound: the compound given IV.
- For absolute parent F, compare parent exposure after EV dosing with exposure after IV administration of that parent. Following a prodrug, an active-drug IV reference on a stoichiometrically matched molar basis can estimate systemic availability of the active moiety, including formation, under shared linear active-drug clearance. Label this separately from parent F. A metabolite exposure ratio alone cannot identify parent F.

Origin and baseline (item 21)
- origin: EXOGENOUS, ENDOGENOUS (stated by the source, not inferred), MIXED (endogenous plus prior-dose residual).
- baseline_behavior: STABLE, VARYING (circadian, feeding, disease), UNKNOWN.
- assay_specificity: TOTAL_SIGNAL, EXOGENOUS_SPECIFIC (for example a labelled compound), UNKNOWN.
- When origin is ENDOGENOUS or MIXED and assay_specificity is not EXOGENOUS_SPECIFIC: raise ENDOGENOUS_REVIEW_REQUIRED. Items 16–20, 22 and 23 give no automatic conclusion on the total signal and run no test; only panels A1 and B1 are drawn and item 21 records the baseline fields (A0.11). The profile goes to human review. EDA never subtracts a baseline.

#### A0.9 Hand-off to modeling (every item)

- Open and tested candidates, each written as a complete combination. For a named Weibull model, record whether lag is present and the β range under discussion. Attach parameter values only if sourced, reconstructed or explicitly set for an illustration.
- Candidates excluded: the test (T1–T5), its margin or CI, the points or animals it rests on, the assumptions and the basis of judgement (A0.3).
- Deferred candidates (BORDERLINE, SINGLE_POINT_SUPPORT) and candidates that could not be assessed, with the reason.
- Shape descriptions, listed separately.
- For each candidate, whether the data are weakly informative or the candidates are structurally indistinguishable. Few points means weakly informative, not structurally unidentifiable.
- The data that would best discriminate the remaining candidates.
- Candidates that depend on later sections (saturable elimination, recirculation, disposition changes) are marked "pending DME" with the section named. After the distribution, metabolism and elimination sections report, their conclusions are added to the candidate's status; the absorption evidence is not rewritten.
- Candidates are not ranked and no model is selected.

**Input models used in the hand-off (items 16, 17 and 20)**

Define the modeled quantity before interpreting the shape. Let A∞ be the eventual amount of the measured parent drug entering systemic circulation (F × administered dose on a consistent basis), G(t) the fraction of A∞ that has entered by time t, and r(t) = A∞ dG/dt the systemic input rate. G is dimensionless and r has units of amount/time. Plasma C(t) also depends on distribution and clearance. An in vitro dissolution curve and a systemic input curve require separate evidence even when fitted with the same mathematical function.

| Single-dose input | Cumulative input and rate | Interpretation |
|---|---|---|
| Finite zero-order, duration T | G(t) = min(t/T, 1) for t ≥ 0. The constant rate A∞/T stops at T. | The **cumulative amount** rises linearly until input stops. Plasma concentration can curve during input. |
| Immediate first-order, rate constant kₐ | G(t) = 1 − exp(−kₐt). Rate = kₐA∞ exp(−kₐt). | A constant fraction of the remaining available amount enters per unit time. The amount entering during successive equal intervals falls. |
| Fixed lag L before a specified input | No systemic input before L. Apply the chosen input function to t − L after onset. | L specifies a period of exactly zero input. An early BLQ alone cannot establish such a period. |
| Serial transit compartments | Sequential transfers with specified rate constants delay the arrival of drug at the systemic input site. | Several stages can produce a gradually rising input rate. A fitted compartment count does not identify anatomical steps. Record whether a separate final absorption step was included. |
| Single Weibull, time scale τ > 0, shape β > 0 | With no lag, G(t) = 1 − exp[−(t/τ)^β]. For t > 0, r(t) = A∞(β/τ)(t/τ)^(β−1) exp[−(t/τ)^β]. | τ is the time to 63.2% of **eventual systemic input**. β controls how input is spread over time. A fixed lag is a separate parameter. |

Here τ denotes the Weibull time scale; in repeated-dose AUC₀–τ it denotes the dosing interval. For a single Weibull input, β = 1 recovers first-order input with kₐ = 1/τ. For β > 1, input begins continuously at dosing: the rate starts at zero, rises to one maximum, then declines. For 0 < β < 1 the rate decreases for every t > 0 and tends to infinity as t approaches zero from above. The cumulative amount remains finite and G(0) = 0. There is no instantaneous bolus in this parameterization.

For a teaching plot, fix τ and compare β = 1 and β = 2 on the same time axis. Plot G(t) as a fraction or percentage; use A∞ to show amount or amount/hour. A rate plot for β < 1 starts at positive time or shows mean input over the first interval. For a fair plasma illustration, use the same A∞, disposition, baseline and sampling times for both inputs. Label each curve as observed, reconstructed or simulated. A plot from an equation is an illustration unless the study data and estimation method support a reconstruction or fit.

Select candidates for modeling when the early observations or an independent formulation/route finding motivate them. A credible rise in C/t beyond uncertainty challenges M0 if its other premises hold. A hard lag, serial transit or Weibull β > 1 can remain open. T1 cannot rank them. With sparse early sampling, describe the observed feature once and retain the ambiguity. When the choice could affect a prediction such as Cmax or Tmax, item 17 describes how to compare candidates. Simulations, deconvolution and structural fits belong to the modeling hand-off and are outside the EDA regression allowlist in A0.7.

Sources: [Piotrovskii (1987), empirical Weibull absorption](https://doi.org/10.1007/BF01068420); [Savic et al. (2007), transit and fixed-lag models](https://doi.org/10.1007/s10928-007-9066-0). The T1 and T2 classifications below follow from the displayed rate and the project’s stated mathematical assumptions.

#### A0.10 Exclusion tests

T1–T5 are project identifiers. At first use, name the comparison and its units: T1, increase in plasma C/t (concentration/time); T2, a within-animal trough and re-rise (concentration); T3, high:low dose-normalized AUC ratio; T3p, dose-normalized concentration differences at matched times (log ratios); T4, decline in the matched EV/IV concentration ratio; T5, compatibility with one positive scale factor across conditions. Ratios and differences between ratios are dimensionless. Each test addresses its stated combination of input, disposition, initial state and observed signal. Record these premises and apply A0.3 to any numerical contradiction.

T1. Violation of "C/t non-increasing"
- Combination M0:
  - initial state: zero, single dose, time counted from this dose, no unmodelled prior dose or endogenous contribution;
  - input: r(t), the rate actually entering the central compartment, non-negative and non-increasing from the dose time (first-order without lag, finite zero-order starting at the dose time, or their sum). A fixed lag does not qualify: r jumps from 0 to a positive value at the lag time;
  - disposition: linear, time-invariant, reversible mammillary;
  - observation: central-compartment concentration.
- Result: under M0, C(t₂)/t₂ ≤ C(t₁)/t₁ for every t₂ > t₁ > 0, throughout the profile. For Q3, prespecify the full eligible single-dose observation window and scan every definitely ordered positive-time pair in it, including pairs after Tmax. Report the window, number of eligible pairs, largest margin and witness times. The onset pair (item 16) and the rising-limb view (item 17) are labelled subsets; a clean subset cannot clear the full profile. Apply joint uncertainty and leave-one-out checks to the full search used for the claim.
- Proof: C(t) = ∫₀ᵗ r(t−s)h(s)ds, so C(t)/t = ∫₀¹ r(t(1−v))·h(tv)dv. For a mammillary model with input into and observation of the central compartment, h(t) = Σ aⱼe^(−λⱼt) with aⱼ ≥ 0, λⱼ > 0 (symmetrization of the system matrix and spectral decomposition), so h is non-increasing. With r and h non-negative and non-increasing, the integrand does not increase with t.
- For definitely ordered positive times (tᵢ⁻ > 0, tⱼ⁻ > tᵢ⁺), M_T1 = Lⱼ/tⱼ⁺ − Uᵢ/tᵢ⁻. A positive margin is a numerical contradiction; A0.3 determines the formal conclusion. A true BLQ uses its assay upper bound. Widen for any justified reading error where relevant; pixel error cannot replace LLOQ. A dose-time zero is a baseline anchor and cannot enter C/t.
- With fixed animals and fixed weights, arithmetic means preserve this inequality; positive geometric means can also preserve it. Destructive or changing cohorts require comparable populations, weights, unbiased inclusion and intervals covering sampling uncertainty across the searched times. BLQ handling and changing sample composition can break the comparison. Otherwise show the group profile descriptively or as SENSITIVITY_ONLY.
- Wording: "violates the necessary condition C/t non-increasing", not "the rise is not concave".
- Under the other M0 premises, the no-lag Weibull with 0 < β ≤ 1 obeys the T1 inequality (for β < 1 its rate at the origin is understood as an integrable limit). A nonnegative sum of immediate, non-increasing inputs also obeys it. A Weibull with β > 1, a fixed lag or a transit input with an initial rate increase lies outside this guarantee. Such a model may still show no sampled increase in C/t.
- Do not transfer the central-input/central-observation prediction to peripheral, effect-site, metabolite or total-radioactivity observations, nonlinear or time-varying disposition, unaccounted predose input, or an unproven catenary structure. Handle a documented finite *administration* under A0.8. Finite zero-order *systemic absorption* starting at an instantaneous dosing event is a member of M0.

T2. Confirmed dip (excludes combinations that allow at most one peak region)
- "Unimodal" here means at most one peak region; plateaus are allowed.
- Input: a globally log-concave input rate r, with connected support. Standard single first-order input, finite constant input, either with a fixed lag, and standard serial first-order transit chains with positive fixed rates qualify. Two separated pulses do not qualify merely because each pulse is log-concave on its own.
- A single Weibull input with β ≥ 1 is globally log-concave on its support: for t > 0 the second derivative of log r is −(β−1)/t² − β(β−1)t^(β−2)/τ^β ≤ 0. A fixed time shift preserves this property. For 0 < β < 1 this log-concavity argument does not apply; that fact alone gives no evidence of a second peak. Mixtures require their own shape argument.
- One-compartment linear disposition: h is log-concave; the convolution of two non-negative log-concave functions is log-concave (Prékopa 1973, Theorem 7), so C is log-concave and unimodal.
- Linear mammillary multi-compartment disposition: h is non-increasing on t ≥ 0 (T1), so with h = 0 for t < 0 it is unimodal with its mode at 0 and integrable. The convolution of a log-concave function with any unimodal function is unimodal (Ibragimov 1956, strong unimodality). Concentration is unimodal, not necessarily log-concave.
- Premises: central input and observation, zero initial state, single dose, no prior-dose or endogenous contribution.
- For definitely ordered times a < b < c in one animal, M_drop = L_a − U_b, M_rise = L_c − U_b, and M_T2 = min(M_drop, M_rise) in concentration units. Both must be positive for a numerical contradiction. Report M_T2/U_b only for a strictly positive, adequately quantified denominator.
- M_T2 > 0 identifies a numerical re-rise under the supplied bounds; A0.3 determines whether it supports a formal contradiction, not the position, height or later decline of a second peak.
- Not applicable to group means or destructive sampling (averaging single-peaked curves can produce two peaks). Execution steps are in item 20.

T3. Dose-normalized superposition (item 19)
- Principle: for one linear time-invariant system at zero initial state, if the external dosing process scales with dose (u_D(t) = D·u₁(t)), then C_D(t)/D = C₁(t), and AUC_D(0,T)/D is dose-independent for any common window.
- Premises: external dosing scales proportionally (same time origin, comparable duration and rate profile, or a model correction from the dosing record; the unknown absorption input is not required to scale, because that is what is tested); comparable covariates, feeding, co-treatment and occasion; no untreated endogenous contribution (C_obs/D = B(t)/D + g(t) breaks superposition of the total signal); group data need the same-population assumption (individual parameter distributions do not differ systematically between dose groups).
- Main test: ratio R of dose-normalized AUC over a pre-set common window, with a pre-set CI.
  - Strict proportionality, H0: R = 1, two-sided 5 % → 95 % CI. A 90 % CI (as used in Smith et al. 2000's approximate-proportionality framework, which answers an equivalence question) excluding 1 is not a two-sided 5 % rejection. The common window and removal rules are project design, not Smith 2000.
  - Pre-specified: window; one primary dose pair or an overall contrast (for example the power-model slope); analyte and comparison range; CI level and method. A highest-versus-lowest comparison covers only that pair and does not exclude a non-monotone deviation at intermediate doses.
  - Data level: per-animal AUC → log(AUCᵢ/Dᵢ) → comparison by design (crossover: within-animal differences with period and occasion effects; parallel: between-group comparison with covariate imbalance considered) → R and CI. The AUC of the group-mean curve is not the geometric mean of individual AUCs; per-time means with SD or SE do not recover individual AUC variability (no cross-time covariance).
  - For destructive sampling, match the AUC variance estimator to the actual integration rule. Bailer’s original variance uses a linear combination with fixed time weights; log-down AUC is nonlinear in the means. Under A0.6 use a justified variance method for that hybrid estimator and study design, or report a descriptive ratio and CANNOT_ASSESS. Never attach ordinary linear-trapezoid Bailer variance to the hybrid AUC.
  - Baseline-corrected AUC ≤ 0, dose-dependent BLQ proportions and different sampling grids must be handled before a log-scale CI.
  - Without individual data and without interpretable SD, SE, CI and n: SENSITIVITY_ONLY. A standard error is not a CI; mean ± SE is not a hard bound.
- Main output: R, CI, CI level, window, dose pair, data level, basis of judgement.
- Per-time scanning without SD and n stays descriptive: M_T3(t) = max[L_H/D_H − U_L/D_L, L_L/D_L − U_H/D_H] per time (mg/L per dose unit or the applicable normalized concentration unit), reported in the description, not as the test result.
- Pointwise test T3p (supplement to the main test). Same principle and premises as T3: under them C_D(t)/D is the same at every time.
  - Data: at each tested time, individual values, or a mean with between-animal SD and n ≥ 2, for both doses; destructive sampling (one sample per animal) or individual serial sampling.
  - Pre-specified: one dose pair; the tested times (common nominal sampling times, chosen before the ratios are seen); two-sided family-wise level 5 %; Holm correction over the tested times.
  - Declare the estimand. For independent parallel individual groups compare mean log(C/D) with Welch or a design-appropriate model (geometric means). For crossover use within-animal log contrasts and account for period, sequence and carryover as appropriate. For independent groups of arithmetic summary means use d=ln(m_H/D_H)−ln(m_L/D_L) and approximate SE=√(CV_H²/n_H+CV_L²/n_L) with a justified small-sample CI. Paired summaries alone do not recover within-animal covariance. Record the estimand and design for each result.
  - Prespecify time strata from actual dosing/sampling records. A ±10% nominal-time tolerance alone does not bound the concentration change on a steep rise. If times differ materially, require a justified timing-error bound or label the result sensitivity only. Exclude ineligible BLQ or n<2 time strata under the prespecified missingness rule. If no eligible time remains, T3p is CANNOT_ASSESS.
  - With eligible data, at least one Holm-adjusted significant contrast challenges joint dose proportionality within the prespecified T3p family, subject to A0.3. Remove one tested time and repeat Holm for the project support check. No adjusted difference leaves the tested family NOT_EXCLUDED only if the design was assessable. Distinguish pointwise CIs from multiplicity-adjusted decisions.
  - Holm holds under any correlation between times, so serial individual data can be used.
  - Report T3 and T3p separately. If either test may trigger one overall confirmatory exclusion, prespecify an alpha allocation, hierarchical procedure or other joint control across both families and any tested dose pairs. Otherwise retain T3 as primary and T3p as a supplementary finding with its own stated error rate.
- A common truncated window does not by itself break proportionality under linearity; it limits whether a difference can be read as a change in F. When window coverage shares cannot be estimated: WINDOW_TRUNCATION_RISK.

T4. EV/IV ratio not decreasing under a shared one-compartment disposition (item 18)
- Combination: EV and IV arms share one-compartment linear disposition; IV bolus, or the period after an IV infusion has ended with no further IV input; central observation; zero initial state; reliable time origin, sampling times and their order.
- Proof: Ċ_IV = −k·C_IV, Ċ_EV = r(t)/V − k·C_EV. With Q = C_EV/C_IV, Q′(t) = r(t)/(V·C_IV(t)) ≥ 0 for any non-negative input (first-order, zero-order, lag, transit, multiphase).
- At each aligned time, form Qᵢ = C_EV,i/C_IV,i. For two ordered times, M_T4 = L_EV,i/U_IV,i − U_EV,j/L_IV,j: the earlier ratio’s lower bound minus the later ratio’s upper bound. A positive margin shows a numerical decline beyond those bounds. Apply A0.3 before assigning a formal conclusion. Report times, concentrations, route ratio bounds, the dimensionless margin, and the result after omitting each matched time pair across arms. Do not call this margin a fold change or a half-life ratio.
- Arithmetic illustration: observed ratios 2.0 and 1.0 with an **assumed** ±5% on each of four concentrations give an earlier lower bound 2.0 × 0.95/1.05 ≈ 1.81 and a later upper bound 1.0 × 1.05/0.95 ≈ 1.11. The margin is about 0.70. These bounds represent a sensitivity scenario; ±5% is not a default sampling uncertainty or confidence interval.
- Require positive, usable IV bounds at every included time. Include uncertainty in sampling-time alignment and all scanned ratios. A numerical slope or interval calculated with mismatched sampling times without a justified bound is sensitivity only. T4 tests shared one-compartment disposition under its IV-input and baseline assumptions; the ratio result alone cannot diagnose flip-flop.
- Different EV and IV doses do not invalidate T4 (under shared dose-independent disposition the dose ratio multiplies Q by a positive constant); DOSE_MISMATCH only prompts a check of comparability and links to T3.
- Group means: with animal-specific kᵢ the mean IV curve is a mixture of exponentials, so the mean EV/IV ratio can fall even when every animal satisfies the combination. T4 is applied to individual comparisons with a basis for shared disposition; group means need an added common-k assumption or a population model.
- Multi-compartment disposition: T4 does not hold. For h(t) = a·e^(−αt) + b·e^(−βt), h(t−s)/h(t) can decrease; a fully linear shared two-compartment system can show Q rising and then falling.

T5. Proportional family across conditions (item 23)
- Family: C_A(t) = c·C_B(t) for all t with one constant c > 0.
- Members: change of F only (F as an input amplitude factor with input time course and disposition unchanged); CL and V scaled by the same factor (one-compartment; multi-compartment needs every micro rate constant unchanged, that is all clearances and volumes scaled by the same factor); and their combinations. In one compartment with EV data only, "F × 1/a" and "CL and V × a" give identical curves and are structurally indistinguishable.
- Criterion: each time gives L_A,i/U_B,i ≤ c ≤ U_A,i/L_B,i. With positive denominators, max_i(L_A,i/U_B,i) > min_i(U_A,i/L_B,i) means no common c exists and the family is excluded. With BLQ or a lower bound at zero, the raw interval constraints are checked without division. With CIs per time, joint uncertainty is handled.
- In Q8, dose fixes the expected multiplier: for a dose ratio d, proportionality predicts raw concentrations and common-window AUCs in ratio d (dose-normalized ratio 1). T3 tests the specified AUC contrast; T3p tests matched-time concentrations. Q9 instead asks whether a single c, of any positive value, fits all matched concentration ratios across two conditions. Record the ratio direction, concentration basis and any dose normalization once. A change in the time course of absorption between formulations can violate T5 even when PK is linear within each formulation.
- For group means, state a common population and how the individual scale factor relates to individual profile shapes. Use actual common sampling times for formal T5, or a justified bound for the time mismatch. A nominal tolerance alone is sensitivity only. Never interpolate an unmatched time silently.

#### A0.11 Data card, figure set and answer status

Data card (one per EV dataset; a table, produced before any figure)
- Fields: route_detail (A0.8); record level (INDIVIDUAL / GROUP_MEAN / DESTRUCTIVE / DIGITIZED, combinations allowed); whether serial identity across times is verified; n per time; spread type (SD / SE / CI / none); mean_type (ARITHMETIC / GEOMETRIC / UNKNOWN); for digitized error bars, whether they were hidden by the symbols; LLOQ; dose_basis; analyte_role; baseline_status and time origin (item 21); first dose or later dose; origin (A0.8); curve or reported parameters only (A0.12).
- A missing field is shown as "not reported" and becomes the "missing" entry of the questions that need it.
- ROUTE_UNKNOWN or ENDOGENOUS_REVIEW_REQUIRED: only panels A1 and B1 with data-status marks are drawn (with the endogenous baseline level as a reference line when known) and no test is run.

Figure set (figures A–F)
- Six figures, each made of panels. A panel carries only the annotations listed for it below; a result of another item is not drawn on it. Panels open from the question rows (page structure below).
- Every panel shown as evidence has a four-line caption: (1) the question it answers; (2) the label with its margin or value; (3) the assumptions it depends on; (4) what it cannot show.
- A panel whose conditions are not met is not drawn empty; one line gives the reason.
- Tiers mark when a layer opens. Tier 2 layers (formal tests) are shown when the trigger seen in tier 1 and the data premise both hold. A test whose data premise holds is still run and reported in its question row when the trigger is absent; only its layer stays hidden, with the reason "no trigger in tier 1".

| Figure | Panel | Tier | Drawn when | Items | Annotations on this panel |
|---|---|---|---|---|---|
| A Early rise (per EV curve) | A1 linear concentration–time; default view the early window (last predose record or 0 to the first sample after Tmax), expandable to the whole profile | 1 | every EV curve | 16, 17, 21 | Tmax circled; BLQ as an open symbol at LLOQ; DESIGN_ZERO as an open diamond at 0 h; with a justified drug-free baseline, shade from dosing to the first quantifiable sample and label its time; earlier onset is unresolved; predose point at its actual time with value and % of Cmax; endogenous baseline as a reference line; observation interval and conditional hard-lag lower bound only when reported (item 16) |
| | A2 C/t intervals | 1 | at least one eligible strictly positive-time pair, independently of the rising-limb shape classification | 16, 17 | Each point's [L/t⁺, U/t⁻]; a contradicting pair joined and labelled with M_T1 |
| | A3 rising-limb increments ΔC/Δt, bars | 3 | at least two quantified pre-peak points | 17, 20 | Description only; values in the caption |
| | A4 individual metrics, Tmax and Cmax/D per animal, dot plot by dose | 3 | individual records | 17, 19 | Description; values in the caption |
| B Decline (per EV curve) | B1 semilog, whole profile | 1 | every EV curve | 18, 20 | Data-status marks as A1; with ≥ 3 quantified post-peak points: selected terminal window with its regression line (over the window only) and apparent t½, other qualified windows in the caption; split-half slopes dashed with ratio and DECLINE_STEEPENS / FLATTENS / NEITHER; dip or second-peak points circled, with SINGLE_POINT_SUPPORT when it applies |
| | B1, T2 layer | 2 | trigger: a second rise in A1 or B1; data: serial samples of one animal, single dose or confirmed washout | 20 | Per animal: [L, U] of the three points, M_drop, M_rise, M_T2, SINGLE_POINT_SUPPORT / EXCLUSION_APPLIED |
| | B2 terminal-window sensitivity: apparent t½ of every qualified window as points, selected window highlighted | 3 | at least two qualified windows | 18 | Description; values in the caption |
| C Dose series | C1 C/D overlay, linear (0 to about 1.5 × the latest Tmax) and semilog (whole profile) | 1 | two or more doses within item 19 scope | 19 | Common window shaded and labelled "common window 0–T h"; doses in one ordered single-hue ramp |
| | C2 metrics by log2 dose: Cmax/D, apparent t½, AUC/D | 1; T3 CI tier 2 | as C1 | 19 | t½ as the range over qualified windows plus the selected value; AUC/D on the common window (0–tlast dashed, labelled "different windows, not comparable"); sign reading per panel; T3 R with CI against 1 on the AUC/D panel when the T3 data exist. No dual axis |
| | C3 per-time ln(C/D) ratio, highest over lowest dose | 2 with T3p data; otherwise 3 | common sampling times | 19 | With SD and n (or individual values) per time: 95 % CI and the times significant after Holm, T3p label. Without them: point ratios, labelled "description, not a test" |
| D EV versus IV | D1 semilog, dose-normalized EV and IV (same hue, different line style) | 2 | trigger: a flat tail in B1, or the apparent t½ is to be read as disposition; data: same-species IV bolus (or after infusion end), common sampling times, individual data or a stated common-k assumption | 18 | Terminal windows; Q interval per common time with M_T4; flip_flop_reading, comparison_basis |
| | D2 linear, dose-normalized EV and IV | 2 | item 22 preconditions | 22 | Window area shaded; f_status, window, tail shares, IV early-area compensation, bias directions |
| E Conditions | E1 overlay, linear and semilog, one colour per condition, reference solid | 2 | item 23 scope | 23 | Every differing attribute listed |
| | E2 c intervals | 2 | as E1 | 23 | c interval per time with the common-c band (T5); rate-only check result |
| | E3 shape-normalized C/AUC_window | 3 | as E1 | 23 | Description; a remaining difference is not amplitude |
| F Reported parameters | one panel per parameter by dose; reported F | 1 when a dataset has parameters only (replaces A–C), otherwise 3 | reported parameters (A0.12) | 19, 22 | Each value with its definition, source and n; error bars when SD is reported; F > 1 flagged, IV and EV doses, same study or not |

- Individual layer: with individual records, A1 and B1 draw one thin line per animal and a bold mean; serial identity not verified → points only with a small time offset, no lines, legend "as labelled in the source". When the lines cannot be told apart (about 8 animals, project setting), A1 and B1 switch to small multiples, one animal per panel. Items 17 and 20 read shapes per animal from this layer.

Page structure and answer status
- Entry: species → study. Inside a study the main view is the nine questions below, nine rows per study. Each row's sentence names the datasets or comparisons it rests on; per-dataset values sit in the row's evidence table.
- Each row shows: the status; one conclusion sentence; beside it the single most explanatory evidence, one view or one data row; and what is missing. Other views and annotations open only when the reader expands the row.
- The conclusion sentence has three parts: what was observed; which points, animals or test result it rests on; how far it reaches given the record level (for example "group mean of different animals; individual profiles cannot be judged"). It uses the item's labels and never says more than they do.
- The primary evidence carries only that question's annotations, marks the points the conclusion rests on, and states the record level beneath it. Default choice: when a test excluded or deferred a combination, the test's view with its witness points; otherwise the view where the described pattern is seen. With NOT_ANSWERABLE_YET or NOT_APPLICABLE no figure is shown, only the sentence and what is missing.
- Tiers set what opens when: the conclusion and primary evidence are always shown; tier 1 views open with the row; tier 2 test views and margins open on request; tier 3 stays folded.

| Q | Question | Items | Primary evidence (default) | Other panels |
|---|---|---|---|---|
| 1 | Onset and delay | 16, 21 | A1 early window: first quantified sample, delay shading, predose point | A2 |
| 2 | What do the sampled rise and peak show? | 17 | A1 with Tmax; A3 increments | individual layer |
| 3 | Which complete input + disposition combinations are excluded | 16, 17 (T1), 20 (T2) | A2 with the witness pair, or the within-animal T2 layer of B1 when it provides the contradiction | A1 |
| 4 | Is there a within-animal trough and secondary rise? | 20 | B1 (or A1) with the dip and the points before and after it marked; the T2 layer per animal when T2 ran | A3, individual layer |
| 5 | Shared by individuals or produced by averaging | 17, 20, data card | The individual layer on A1 and B1; destructive sampling: the data card row | A4 |
| 6 | Long tail and flip-flop | 18 | D1 when IV exists; otherwise B1 with the terminal window | B2 |
| 7 | Can EV and IV exposure estimate systemic bioavailability? | 22, A0.12 | D2, or the reported F in F | — |
| 8 | Do Cmax and AUC increase in proportion to dose? | 19 | C3, or C2 with the T3 CI, when T3 or T3p excluded or deferred; otherwise C1 | C2, F |
| 9 | Can one concentration ratio describe both conditions at all matched times? | 23 | E1 with E2 | E3 |

- ANSWERABLE: a test reached EXCLUDED_UNDER_STATED_ASSUMPTIONS, or assessable NOT_EXCLUDED without a deferring flag. NOT_EXCLUDED is an answer ("not excluded"), not support.
- PARTLY_ANSWERABLE: only descriptions, a test with SENSITIVITY_ONLY, BORDERLINE or SINGLE_POINT_SUPPORT, or reported parameters only.
- NOT_ANSWERABLE_YET: CANNOT_ASSESS, NOT_ASSESSABLE or NOT_ESTIMABLE; the row names what is missing. With a usable conditional or descriptive result, the question can be partly answerable while its formal test remains CANNOT_ASSESS.
- NOT_APPLICABLE: the question does not arise for this dataset (for example a single condition for question 9). Never used for missing data.
- A row takes the highest status reached by any of its parts; the parts below it are listed under "missing".
- Questions 2 and 5 are descriptive. For Q2, a verified individual rising limb with adequate early sampling is answerable; group means or weak early sampling give at most PARTLY_ANSWERABLE. For Q5, verified serial identities and enough observations to see the feature in each animal determine answerability. A ka estimate is irrelevant to this decision.
- Q5 with one destructive observation per animal is NOT_ANSWERABLE_YET. Unverified cross-time identity gives at most PARTLY_ANSWERABLE; show source-labelled points without connecting them.
- Question 4 with group means only: PARTLY_ANSWERABLE when at least two post-peak samples exist; the dip search on the mean is a description and T2 does not apply.
- In Q6, give a status for the terminal half-life comparison and one for T4, each with its own evidence. A definitive result on T4 alone leaves the cause of the terminal decline unresolved.
- Q6 without comparable same-study IV can still describe the terminal window. Other-study IV, source-reported IV or an EV-route comparison may support an indirect absorption-influenced candidate under item 18. Mark its basis and at most PARTLY_ANSWERABLE; without usable slope or comparison evidence the cause is UNRESOLVED.
- Each study row names the applicable conditions and the condition supporting its summary. The highest status applies only to the named part. Where another relevant condition lacks data or conflicts, display its status beside the summary and avoid a study-wide unqualified conclusion.
- Panels of a gated curve (for example a non-plasma matrix) answer no question and are listed under "Other panels".
- A primary evidence drawn from reported parameters (A0.12) shows only the parameter of that question: Tmax for question 2, t½ for question 6, AUC for question 8.

#### A0.12 Reported-parameter path (EV data without a curve)

- Applies when an EV dataset gives source-reported parameters (Cmax, Tmax, AUC, t½, CL/F, F) and no concentration-time points; label REPORTED_PARAMETER. Each question it feeds is at most PARTLY_ANSWERABLE, except the T3 route below.
- Per value: definition (AUC interval, NCA or model, extrapolation), source location, n, spread type (SD / SE / CI) and whether an SD is between-animal or a model standard error, mean_type.
- Item 19: E5 description. Parallel groups with AUC mean, between-animal SD and n per dose: T3 on the ratio of arithmetic mean AUC/D, with an approximate CI of the log ratio: SE of each log mean ≈ CV/√n (delta method, CV = SD/mean), t quantile with Welch–Satterthwaite degrees of freedom (t3_data_level GROUP_SUMMARY_SD). Same pre-set rules as T3. A model standard error in place of an SD → SENSITIVITY_ONLY. AUCs of different definitions are not compared.
- Item 18: a source-reported IV terminal half-life can provide indirect evidence (REPORTED_IV_PARAMETER) when its definition, analyte, design and observation period support comparison. Check whether the reported value is a terminal λz half-life, ln(2)·Vcentral/CL or another model-derived quantity. A central elimination microconstant cannot stand in for terminal IV λz in a multicompartment model.
- Item 22: a source-reported F gets f_status SOURCE_REPORTED, with F_ABOVE_ONE, IV and EV doses (DOSE_MISMATCH; NONLINEAR_DOSE_MISMATCH when item 19 points to nonlinearity, otherwise LINEARITY_UNTESTED), same study or not, dose basis.
- Items 16, 17, 20, 21 and 23 need concentration points; reported parameters give a description only.

---
### 16 | EXTRAVASCULAR INPUT: ONSET OF INPUT

Scope
- route_class = EV profiles (route_detail as A0.8).
- First dose, or a later dose when a measured predose concentration is zero or BLQ, or WASHOUT_ZERO applies (item 21). A quantified or unknown predose gives NOT_ASSESSABLE.
- During and after known finite administration, apply A0.8. The end of delivery is not an automatic restart for the onset test.

Data and details
- Dose time and time origin of this dose, route_detail, formulation and vehicle, administration_start/end.
- Every sample from dose time to the observed peak with its Data status and the applicable LLOQ. BLQ is evidence of a concentration below LLOQ, never a missing value.
- Record level and observation source (A0.4), other doses by the same route in the same study.

Figures (A0.11)
- Figure A. With a justified drug-free baseline, shade the interval from dosing to the first quantifiable concentration and label it “first quantifiable sample at t₁; earlier onset unresolved.” With intervening BLQ samples, mark the last BLQ and first quantifiable sample separately. Draw a conditional hard-lag bound only when eligible, with its assumptions. Panel A2 shows the positive-time T1 witness pair, its bounds and margin. Compare onset across doses in figure C.
- Table: one row per profile with the Output fields.

Drawing specification (panel A1)
- X-axis: time after this dose, linear. Default view: the early window, from the last predose record (or 0) to the first sample after the observed Tmax; the whole profile opens on the same panel. State the window.
- Y-axis: linear concentration. Zero is drawn as zero. BLQ as an open circle at the LLOQ line with its value labelled; no line through BLQ points. DESIGN_ZERO as an open diamond at 0 h labelled "zero by design, not measured". Digitized points carry their reading tolerance in the caption.
- Vertical line at the dose time (and at administration_end when known). State when the dose-time concentration is unknown.
- Semilog views are not used alone to judge onset. No back-extrapolation, fitted curve or smoother.

Assessment (host code computes; the model describes)
1. Data support. NOT_ASSESSABLE when the dose-time concentration is unknown or nonzero, the time origin is not this dose, there is no post-dose sample, or ENDOGENOUS_REVIEW_REQUIRED applies.
   - DESIGN_ZERO and WASHOUT_ZERO follow item 21. A measured baseline takes precedence. A predose BLQ and a plausible depot or prior dose do not by themselves establish drug-free tissues.
2. First post-dose sample quantified → ONSET_NOT_OBSERVED. With a reliable dose time, drug-free baseline and specific assay, “systemic input had begun by the first quantifiable sample at t₁.” Its start within that interval is unresolved. Add LATE_FIRST_SAMPLE when the first sample is at or after one third of the observed Tmax (project choice).
3. For an early positive-time BLQ (or measured zero with a justified upper bound) and a later first quantified sample, test the T1 special case only if t₀⁻>0 and t₁⁻>t₀⁺.
   - M_T1 = L(t₁)/t₁⁺ − U(t₀)/t₀⁻. For BLQ, U(t₀) is the assay censoring limit including justified uncertainty. For a measured or digitized zero, use its documented upper bound; an unclassified point plotted at zero or an unknown LLOQ is insufficient. No test uses C(0)/0.
   - A positive margin contradicts M0 numerically. Use A0.3 before calling an exclusion. DELAYED_ONSET is a descriptive project flag for a delayed or accelerating early rise. A hard lag, gradual input and other violations of M0 remain open.
   - M_T1 ≤ 0 for an eligible BLQ pair → ONSET_BELOW_LLOQ: the pair is compatible with immediate input. For a bounded measured zero, retain the same legacy status but report the source status as “measured zero” in the observation sentence. Use A0.3 for the test status; missing bounds or invalid times are reasons for CANNOT_ASSESS, not zero margins.
4. Reporting (George, 2026-11-04). Observed onset evidence is reported separately from any model-conditional hard-lag bound.
   - `observation_interval_h` = [last BLQ time, first quantified time]. It is an observation interval, not a tlag interval.
   - Optional conditional hard-lag bound. Require zero baseline, a hard lag L followed by a concentration rise known to be concave throughout the relevant post-onset interval, definitely ordered times, C₁ lower bound >0 and 0≤r=U(t₀)/L(t₁)<1. Then L ≥ (t₀⁻−r·t₁⁺)/(1−r). Report a positive bound only, with its assumptions and units. The straight post-onset rise attains equality with closed concentration bounds. Never use this result to exclude gradual onset.
5. A positive T1 margin between early quantified points gives the descriptive finding C/t rose beyond the specified bounds. Use the legacy flag ONSET_NOT_CONCAVE for data compatibility only. Interpret formal exclusion through A0.3; a lag duration and a specific input model remain unresolved.
6. Sensitivity across doses. When two or more doses by the same route exist and DELAYED_ONSET appears only at the lower doses while higher doses are quantified at the same nominal time (±10 %), add LLOQ_LIMITED: the early BLQ may reflect the assay limit.
7. Consistency. For the same species, route_detail and formulation, compare onset status across doses and studies; record disagreement as a conflict for human review.

Output per profile
`onset_status` (DELAYED_ONSET / ONSET_BELOW_LLOQ / ONSET_NOT_OBSERVED / NOT_ASSESSABLE; precedence NOT_ASSESSABLE > DELAYED_ONSET > ONSET_BELOW_LLOQ > ONSET_NOT_OBSERVED), `t1_label` (A0.3), `t1_margin`, `observation_interval_h` or `first_sample_upper_bound_h`, `conditional_hard_lag_lower_bound_h` with `bound_assumptions`, `dose_time_basis` (MEASURED / DESIGN_ZERO / WASHOUT_ZERO), `evidence_rows`, `first_sample_h`, `observed_tmax_h`, `caveats` (LLOQ_LIMITED, LATE_FIRST_SAMPLE, ONSET_NOT_CONCAVE, GROUP_MEAN, DESTRUCTIVE_SAMPLING, DIGITIZED, KNOWN_INPUT_PERIOD, WASHOUT_ZERO, UNKNOWN_PREDOSE, TIME_ORIGIN_UNCLEAR), `not_assessable_reason`, `handoff_candidates`.

Hand-off
- DELAYED_ONSET: when the other M0 assumptions are supported, carry forward a fixed lag followed by first- or zero-order input, gradual input (e.g. an unshifted Weibull with β > 1 or serial transit), and any independently plausible delayed component. Fixed lag means zero input until a positive time. Gradual input can start immediately and still be below the assay limit at the first draws. A positive T1 does not distinguish these cases. Use the complete model definitions in A0.9–A0.10.
- State what could discriminate them: verified dose and sample times, serial samples around first appearance at a suitable LLOQ, a comparable IV disposition reference and any independent evidence of a release delay. If the earliest change lies between sparse samples, retain the alternatives and report the interval.
- ONSET_NOT_OBSERVED does not forbid a lag term in a model (Gabrielsson 2016 case 5: no visible delay, but a lag time removed systematic deviations around the peak).

Purpose, limits, and main-objective link
Reports when systemic drug was first quantifiable, which assumptions an eligible T1 challenged and how sampling limits a hard-lag estimate. Immediate but gradually accelerating input remains possible. Savic et al. (2007) compared transit and lag models in specific datasets; those fits do not rank candidates for a new dataset.

Keywords: onset; delayed onset; observation interval; conditional hard-lag bound; first quantified sample; BLQ before peak; LLOQ-limited; transit.
MP basis: MAIN.MP001 (time origin, input type), MAIN.MP003 (extravascular input, F); CPK01 absorption concept.
Sources: Gabrielsson, Meibohm & Weiner 2016 AAPS J 18:47, cases 3, 5, 16; Savic et al. 2007 J Pharmacokinet Pharmacodyn 34:711; WinNonlin 5.2 help Table B-3 (tlag definition).

---

### 17 | EXTRAVASCULAR INPUT: DESCRIPTION OF THE RISING LIMB

Scope
- Same scope and data support as item 16. Uses item 16: the rising limb is read from the first quantified sample; DELAYED_ONSET is carried into the hand-off.

Data and details
- As item 16, plus the rising-limb samples to the observed peak and the first two post-peak samples.

Figures (A0.11)
- Figure A (shared with item 16). For this item: Tmax circled on A1; A2 can open on the rising-limb subset, but its Q3 view includes the full search window and the full-window witness pair, even when either time is after Tmax. rise_shape and KA_NOT_IDENTIFIABLE go in the caption, not on the plot.
- Individual layer on A1 and B1 with individual data: shapes are read per animal. A4 (tier 3): individual Tmax and Cmax/D.
- A3 (tier 3): increments, when at least two quantified pre-peak points exist.
- Table: rising-limb samples with increments.

Drawing specification
- As item 16. Connect rising-limb points with thin straight segments only for verified serial units or source summary series; segments are visual guides, not fitted input functions.

Descriptive calculation (host code)
- Calculate the net plasma concentration slope ΔC/Δt between consecutive quantified observations at definitely ordered, distinct times. State its units (e.g. mg/L/h), record level and any intervening unsampled or BLQ interval. This is a slope of measured concentration, not the rate of systemic input (amount/time).
- For a descriptive increase or decrease, compare the concentration change with the prespecified project tolerance. If using individual bounds, report the change interval [L₂−U₁, U₂−L₁]; overlap with zero means the sign is unresolved. “Twice the tolerance” applies only to equal, symmetric absolute errors of the two measurements. Keep the observed change rather than replacing it with zero.

Assessment
Common conditions
- P1. route_class = EV; first dose, a later dose with predose zero or BLQ, or WASHOUT_ZERO. Not during KNOWN_INPUT_PERIOD. For formal M0 tests, require a justified zero initial state or bounds showing negligible carryover throughout the relevant window (item 21).
- P2. For the shape classification, require at least three quantified rising-limb samples including the peak, and an interpretable baseline and time origin. With exactly three, add SPARSE_RISING_LIMB. When this shape gate fails, report any observed Tmax or early bound separately. An eligible pair can still yield a numerical T1 margin; support and formal status follow A0.3.
- P3. Telling a corner from a rounded peak needs at least two rising-limb samples close to the peak and one just after it; otherwise UNCLEAR.
- P4. DESIGN_ZERO or WASHOUT_ZERO may anchor the first increment (mean rate over [0, t1]); caveat FIRST_INCREMENT_FROM_DESIGN_ZERO; when the description depends on it, `rise_shape_alt` holds the other reading.
- P5. The plasma profile reflects input, distribution and elimination together (DISPOSITION_CONFOUNDED). A sparsely sampled rapid EV input may resemble IV disposition. A suitable IV reference helps characterize disposition (Gabrielsson cases 4 and 5); an EV peak or post-peak slope alone cannot establish input order.
- P6. Peak above ULOQ: Cmax is a lower bound and the corner/rounded reading is NOT_ASSESSABLE.
- P7. Formulation, dose relative to solubility and route_detail are context, not evidence.

Exclusion (T1)
- Use the full-window Q3 T1 result (A0.10) for M0. In the item 17 view, separately identify any witness pair in the rising limb and label the subset. A positive margin is a numerical contradiction; call exclusion only if A0.3 passes.
- Keep every complete combination that T1 did not exclude. A formal T1 exclusion covers immediate first-order input at every positive constant kₐ, finite zero-order input from dose time, and any positive mixture of immediate nonincreasing rates, when the other M0 premises hold. Changing kₐ or mixing fast and slow immediate first-order depots preserves the prediction. State which premise differs for each retained candidate (e.g. hard lag, gradual input, or different disposition); see A0.9–A0.10.
- No test excludes a lag term or a transit-type input on its own: T1 concerns only M0, and T2 (item 20) only the log-concave input family, and only after a confirmed dip. T1 does not apply with peripheral, metabolite or total-radioactivity observation, or with nonlinear disposition (A0.10).

Description (`rise_shape`; does not exclude anything)
- FIRST_ORDER_LIKE (legacy code; display “slowing rise, rounded peak”): the largest slope occurs early and the last pre-peak slope is below half the first within the project tolerance. Input order remains unresolved.
- ZERO_ORDER_LIKE (legacy code; display “sustained rise, observed change of slope near peak”): report the slopes and time brackets. Constant systemic input means a linear cumulative input until its stop; concurrent elimination curves the plasma rise. Only with independently specified finite constant input, zero baseline, a central response that decreases after an IV bolus, and a well-sampled single-animal peak may the neighboring samples bracket tlag + duration. Report assumption-dependent duration only when lag is also bounded.
- SIGMOIDAL_DELAYED (legacy code; display “slow–fast–slow concentration rise”): the largest concentration slope is neither first nor last, with no sharp onset visible. A serial transit model and a Weibull with β > 1 can both give this pattern. The observed rise does not determine β, establish a hard lag, or identify physiological transit steps.
- MULTIPHASE: fast → slow → fast (shoulder), or two maxima; passed to item 20.
- UNCLEAR: none fits within tolerance.
- NOT_ASSESSABLE: P1 or P2 not met.
- Precedence for the single label: NOT_ASSESSABLE > MULTIPHASE > SIGMOIDAL_DELAYED > ZERO_ORDER_LIKE > FIRST_ORDER_LIKE > UNCLEAR.
- A plateau or a Tmax moving later with dose is not evidence of zero-order input (saturable absorption or elimination, Gabrielsson cases 9 and 10): PLATEAU_OR_PEAK_SHIFT, passed to item 19.
- KA_NOT_IDENTIFIABLE: fewer than two quantified samples before the observed peak, Tmax at the first sample, or FLAT_TOP_WITHIN_TOLERANCE (every sample up to the peak within twice the tolerance of the first). This is weak information from the sampling, not structural unidentifiability.

Individual and group data
- For verified individuals, describe shape per animal (e.g. 5 slowing rises, 3 slow starts and 1 shoulder). Report eligible per-animal T1 findings and how many animals were assessable. Use multiplicity control if claiming an overall statistical exclusion across animals.
- Group means only, evidence strength by whether averaging can create the feature:
  - An apparent corner or sudden onset in a sampled mean can reflect changing contributors, censoring, sparse draws or line segments between draws. Verify the same feature in serial animals before attributing it to an individual.
  - a plateau, rounded peak, sigmoidal rise, shoulder or double peak can be created by averaging (single-peaked animals with different Tmax can give a two-peaked mean): weak evidence, GROUP_MEAN with the direction stated (for example "rounded peak may come from averaging; zero-order not excluded").
  - Under M0 and fixed positive weights, an arithmetic mean preserves non-increasing C/t. A visual S-shape alone cannot identify delayed onset. Check baseline, sampling, censoring, group composition and the test premises.
- Before reading a mean: n per time point (unequal n flagged), arithmetic or geometric mean, spread of individual Cmax (a wide spread lets a few animals dominate an arithmetic mean), and how BLQ entered the mean (set to 0 lowers early means; dropped raises them).

Output per profile
`rise_shape`, `rise_shape_alt`, `rising_limb_n`, `increments`, `t1_label`, `t1_margin`, `excluded_combinations`, `retained_candidates`, `individual_distribution` (when individual data exist), `evidence_rows`, `caveats` (SPARSE_RISING_LIMB, PLATEAU_OR_PEAK_SHIFT, KA_NOT_IDENTIFIABLE, FLAT_TOP_WITHIN_TOLERANCE, FIRST_INCREMENT_FROM_DESIGN_ZERO, DISPOSITION_CONFOUNDED, GROUP_MEAN, UNEQUAL_N_PER_TIME, RESIDUAL_BASELINE, KNOWN_INPUT_PERIOD, CMAX_ABOVE_ULOQ, plus item 16 caveats), `not_assessable_reason` (including UNOBSERVED_START).

Purpose, limits, and main-objective link
Describe the sampled plasma rise, record the T1 status and hand off complete candidates through A0.9. Use the following comparisons in modeling when input order matters.

- **Finite zero-order versus first-order.** A zero-order input delivers a constant *amount* per unit time until it stops. A first-order depot delivers a constant *fraction of the remaining amount* per unit time. On a plot of cumulative systemic input, compare a constant slope up to a stop followed by a plateau with a progressively decreasing slope toward a plateau. Plasma concentration can curve under either input. If these data contain only a plasma profile and descriptive concentration slopes, report “input order unresolved.”
- **Reconstruct input when disposition is independently characterized.** For one-compartment linear disposition, known zero baseline and a justified elimination rate kₑ, Wagner–Nelson gives cumulative systemic input proportional to C(t) + kₑ AUC(0,t). To express the fraction of eventual systemic input, divide by kₑ AUC(0,∞) only if the total AUC is estimable. A suitable IV arm can supply kₑ; an unresolved EV terminal slope cannot. For more complex shared linear, time-invariant disposition, use numerical deconvolution with a suitable dose-normalized IV response and documented administration history. Plot reconstructed input with uncertainty and assess sensitivity to the IV fit, sampling and regularization. Call the reconstruction an estimate; distinguish it from the observed concentrations and from the fraction of administered dose reaching the circulation.
- **Compare plausible input models on the same data.** Fit the same observation units and times with the same disposition, error/BLQ handling and comparable lag assumptions. Inspect early, peak and immediately post-peak residuals; report model-comparison evidence together with uncertainty and sensitivity to removing a key peak observation. For gradual onset, compare Weibull and transit when both are plausible. If both predict the measured profile within uncertainty, report the alternatives and the next informative samples or independent input/disposition measurements. A source-reported preference is attributed to that analysis, not promoted to an EDA exclusion.

Keywords: input function; first-order; zero-order; Tabs; transit; sigmoidal rise; rising limb; increment rate; plateau; group-mean artefact.
MP basis: MAIN.MP003; CPK01 absorption concept.
Sources: [Gabrielsson et al., Case 16, Fig. 8](https://pmc.ncbi.nlm.nih.gov/articles/PMC4706292/), zero-order and first-order model fits with differing onset assumptions in one volunteer; [Wagner & Nelson (1964)](https://doi.org/10.1002/jps.2600531126), cumulative absorption; [Levitt (2003)](https://doi.org/10.1186/1472-6904-3-1), IV-referenced numerical deconvolution and its sensitivity to sampling and noise. For the single Weibull and serial transit models, see A0.9.

---

### 18 | EXTRAVASCULAR INPUT: TERMINAL PHASE AND FLIP-FLOP

Scope
- EV profiles with a post-peak decline. Flip-flop: absorption slower than the terminal disposition rate, so the EV terminal decline reflects absorption.
- Gates: ENDOGENOUS_REVIEW_REQUIRED → not assessed; prior-dose residual → MIXED_DOSE_TERMINAL; known finite administration → only the period after administration_end.

Identifiability
- One-compartment first-order absorption: C(t) = A·ka/(ka−k)·(e^(−kt) − e^(−ka·t)), A = F·D/V. The identical curve is given by ka′ = k, k′ = ka, A′ = A·ka/k. At ka = k use the continuous limit C(t) = A·k·t·exp(−kt). Swapping the rates without changing the amplitude does not give the same curve.
- Rule: for a single-condition EV curve with no independent constraint on amplitude or apparent volume, the curve alone cannot decide which rate belongs to absorption and which to elimination. Known V/F, independent absorption information or a suitable joint design can break this ambiguity.

Data and details
- The EV profile and IV profiles of the same drug, species (strain where stated), analyte, matrix and concentration basis, preferably the same study; other EV routes or formulations; a source-reported IV half-life labelled as reported.

Figures (A0.11)
- Panel B1: the selected terminal window with its regression line, drawn over the window only, and the apparent t½; other qualified windows in the caption. No fitted model curve is drawn.
- Panel D1 (tier 2) when same-species IV exists: dose-normalized semilog EV and IV with the same y-limits, terminal windows, Q intervals with M_T4, flip_flop_reading and comparison_basis.
- Panel B2 (tier 3): terminal-window sensitivity.
- Table: one row per EV profile with comparisons, windows, results.

Assessment: two separate procedures
1. T4 (A0.10) needs adequately aligned EV/IV sampling times, independently supported IV bolus or confirmed post-infusion status, and an assessable denominator. With unknown IV mode, withhold formal T4; a named bolus scenario may be shown as sensitivity only. T4 uses the observed concentration ratios and can run without a qualified terminal window. Report the two times and ratios, the bounds that define the margin, and the effect of omitting each time.
   - T4 addresses the shared linear one-compartment prediction for the ratio. A positive margin that passes all gates contradicts that prediction; shared two-compartment disposition can produce a decline. Every T4 outcome leaves the flip-flop assessment to the slope and independent-evidence comparison below.
   - Multi-compartment IV (visibly multi-exponential): T4 is CANNOT_ASSESS; an EV decline steeper than IV goes to EV_STEEPER_REVIEW with candidates multi-compartment disposition (EV still in a steeper distribution phase in the same window), different disposition between arms, nonlinearity, data issue.
2. Terminal slopes and apparent half-lives (A0.7 windows).
   - Report the EV/IV apparent half-life ratio for every pair of qualified windows. Identify both intervals and their comparability. If the grade changes across credible comparable windows, retain the grade range, mark WINDOW_SENSITIVE and leave the directional reading UNRESOLVED. The cut-offs 0.80, 1.25 and 2 describe the half-life difference in the chosen windows only (`terminal_difference_grade`: EV_STEEPER < 0.80 ≤ PARALLEL_IN_WINDOW < 1.25 ≤ EV_SHALLOWER_MODERATE < 2 ≤ EV_SHALLOWER_MARKED). They do not decide flip-flop and do not quantify the absorption contribution.
   - Reason: s_EV(t) = −k + (ka − k)/(e^((ka−k)t) − 1). At ka = k use s_EV(t) = 1/t − k for t > 0. In a finite window both ka > k and ka < k can make EV shallower than IV. Example: k = 0.1, ka = 0.2 /h (no flip-flop), secant over 8–12 h gives an EV/IV half-life ratio of 2.47. Byron & Notari 1976 also note that a straight semilog segment need not have the true absorption or terminal disposition slope.
   - No qualified window → TERMINAL_SLOPE_NOT_ASSESSABLE; this is not evidence of absence of slow absorption and does not switch off T4.
   - Without a suitable same-study IV curve, use a ≥ 1.25-fold difference between comparable EV terminal half-lives, or an EV terminal half-life ≥ 1.25 times a comparable source-reported IV terminal half-life, as indirect evidence only. Record the route, analyte, population, phase and estimation basis. A distribution half-life, a microconstant-derived half-life or a value with unspecified phase does not qualify as the IV terminal comparator. If comparability is unclear, retain the source value as context and withhold a numerical grade.
3. `flip_flop_reading`:
   - COMMON_TERMINAL_COMPATIBLE: parallel to a comparable IV in the window. Compatible with a common terminal process only; it does not prove that absorption has ended or that flip-flop is absent (ka close to k, finite noise).
   - ABSORPTION_INFLUENCED_CANDIDATE: EV shallower than IV (or indirect evidence). Candidates: flip-flop, ka only modestly above the terminal rate in an early window, nonlinearity at unequal doses.
   - EV_STEEPER_REVIEW: EV has the steeper apparent decline in comparable windows. Review window choice, distribution phase, differences between arms and data quality. Run T4 separately only when its own premises hold.
   - UNRESOLVED: no IV and no indirect evidence, or windows not assessable. UNRESOLVED is never negative evidence (item 23).
4. DISTRIBUTION_MASKED: IV multi-exponential while the EV post-peak decline looks mono-exponential. A candidate explanation (slow absorption hiding distribution), not a confirmed mechanism.
5. DOSE_MISMATCH: EV and IV doses differ; check comparability of disposition and link to item 19 (a slower terminal decline at a higher dose may come from saturable elimination).

Output per EV profile
`t4_label`, `t4_margin`, `t4_points`, `flip_flop_reading`, `terminal_difference_grade`, `grade_range`, `thalf_ratio_by_window_pair`, `comparison_basis` (IV_SAME_STUDY / IV_OTHER_STUDY / OTHER_EV_ROUTE / REPORTED_IV_PARAMETER / NONE), `profiles_compared`, `terminal_windows_h`, `evidence_rows`, `caveats` (DISTRIBUTION_MASKED, WINDOW_SENSITIVE, DOSE_MISMATCH, MIXED_DOSE_TERMINAL, UNEQUAL_TERMINAL_WINDOW, TERMINAL_SLOPE_NOT_ASSESSABLE, RESIDUAL_BASELINE, KNOWN_INPUT_PERIOD, DIGITIZED, GROUP_MEAN), `unresolved_reason`.

Hand-off (fixed wording)
"The EV half-life is reported as an apparent terminal half-life. Being parallel to a comparable IV curve only shows compatibility with a common terminal disposition process; it does not alone show that absorption has ended or that flip-flop is absent. The terminal λz of a multi-compartment IV profile is not the micro elimination constant k10. Joint EV + IV fitting is a reasonable next step, with parameter uncertainty and identifiability checked."
- EV dose/AUC∞ estimates CL/F under linear PK with reliable total exposure. Ongoing input and an uncertain extrapolated tail can materially bias a CL/F estimate obtained from incomplete observations.

Purpose, limits, and main-objective link
Reports the apparent terminal decline, its possible absorption contribution, and the separate test of shared one-compartment disposition. Assigning an EV slope to absorption or disposition requires independent information.

Keywords: flip-flop; apparent terminal half-life; EV/IV ratio; shared one-compartment test; parallel decline; masked distribution; identifiability.
MP basis: MAIN.MP003; CPK01 half-life check.
Sources: Gabrielsson et al. 2016 cases 3 and 4, Fig. 5; Kuan, Wright & Duffull 2023 CPT Pharmacometrics Syst Pharmacol (doi 10.1002/psp4.12909; parameter swap); Byron & Notari 1976 J Pharm Sci (doi 10.1002/jps.2600650804); Yáñez et al. 2011 Ther Deliv 2:643; Boxenbaum, J Pharm Pharm Sci 1(3):90; PKNCA half-life vignette; EMA CPMP/EWP/QWP/1401/98 Rev.1.

---

### 19 | EXTRAVASCULAR INPUT: DOSE DEPENDENCE

Scope
- Two or more doses of the same drug, species, route_detail, formulation, analyte, matrix and concentration basis; the same dosing occasion for each dose (item 21); preferably the same study.
- Gates: ENDOGENOUS_REVIEW_REQUIRED → T3 not run (BASELINE_CONFOUNDED); inhaled routes state the dose basis.
- Repeated-dose profiles from the same day of the same regimen that differ only in dose may be compared with each other (REPEATED_DOSE); they are not mixed with single-dose profiles. The zero initial state of T3 then refers to the start of the regimen, and the whole dosing history scales with dose (A0.10).
- Datasets with reported parameters only: A0.12.

Data and details
- Per dose: profile, observed Tmax and Cmax, observed-window AUC (A0.6) on the common window, source-reported AUC labelled with its definition.
- Per-animal data, or SD/SE/CI and n per time; design (crossover or parallel, destructive sampling).
- Same-species IV data at two or more doses when available.

Figures (A0.11)
- Figure C: C1 dose-normalized overlay and C2 descriptive metrics by dose, one set per study.
- Tier 2 on figure C: the T3 R and CI on the AUC/D panel of C2; C3 with T3p per-time ratios when SD and n exist per time.
- Tier 3: C3 as point ratios (description) when the T3p data are missing; A4 (individual metrics); figure F (reported parameters).
- Table: dose, Tmax, Cmax/D, AUC/D with basis and window, apparent terminal half-life (A0.7).

Assessment
1. T3 (A0.10) is the exclusion test: it can exclude "linear, dose-independent input and disposition" under the stated premises. It does not say whether the nonlinearity is in absorption or elimination. T3p (A0.10) is its pointwise supplement and excludes the same combination; both are reported.
2. IV at two or more doses: T3 on IV. IV incompatible (with actual IV dose and infusion process known, proportional or corrected) argues against a common dose-independent linear disposition; this does not locate it in saturable elimination (distribution, protein binding or the observation relation can also change). When EV fails superposition, an IV comparison precise enough to rule out a disposition change of the relevant size supports investigating dose-dependent systemic input or first pass. An inconclusive IV comparison leaves both input and disposition open. Compare over the same relevant concentration range, not only the same mg/kg.
3. Descriptive signs (POINTS_TO_NONLINEARITY / NO_SIGN / NOT_AVAILABLE, with INCONCLUSIVE as specified in E6). Label the figure with the metric, units and observed trend. These project flags do not establish proportionality or localize a mechanism:
   - E1. Whole-profile superposition of the dose-normalized overlay; per-time M_T3 (description; with SD and n per time, T3p).
   - E2. Apparent terminal half-life by dose, beyond window sensitivity.
   - E3. IV CL by dose.
   - E4. Under LTI PK and identical repeated input per dose, steady-state AUC₀–τ equals first-dose AUC₀–∞ at the same dose. Comparing two 0–τ windows addresses accumulation instead. Document steady state and complete single-dose exposure before using E4.
   - E5. Source-reported parameters by dose, labelled.
   - E6. Rdnm (AUC/D highest over lowest, common window), Cmax/D secondary. Without variability: point estimate, exploratory only (outside [0.50, 2.0] → POINTS_TO_NONLINEARITY; within [0.80, 1.25] → NO_SIGN; otherwise INCONCLUSIVE). The 0.50–2.0 range is Hummel et al. 2009's limit for a 90 % CI, used here on a point estimate as a project adaptation. Simulation (CV 30 %, n = 3 per dose, 200 000 runs, 2026-11-03): a point estimate against 0.80–1.25 flags a linear drug in 36 % of experiments (highest over lowest) and 63 % when every pair of three doses is tested.
   - E7. With three or more doses, power-model slope b1 (descriptive).
   - E8. Background knowledge (saturable pathways, Km): context only.
   - E9. Cross-route consistency, qualitative.
4. DECLINE_STEEPENS (A0.7) as a sign of saturable elimination counts only when it differs between doses after dose normalization: ordinary ongoing absorption produces the same steepening at every dose. A high-dose-only steepening strengthens suspicion but is not the only allowed sign; with different sampling ranges a low dose may have no observable early phase.
5. Saturable elimination signs: apparent half-life changing with dose is a sign. Identical terminal slopes do not exclude saturable elimination at high concentrations (one-compartment Michaelis–Menten: d log C/dt = −Vmax/[V(Km + C)]; once every dose falls to C ≪ Km, terminal slopes converge). Record ELIMINATION_NONLINEARITY_POSSIBLE "pending DME" (elimination section).
6. Candidates (premises: linear disposition, unchanged CL, complete exposure assessable; listed unranked):

| Candidate | Usual dose-normalized pattern | Limit of interpretation |
|---|---|---|
| 2a: input slowed and systemic availability unchanged | Cmax/D may fall and peak later; complete AUC/D unchanged under common linear clearance | Truncated AUC cannot establish unchanged extent |
| 2b: input limited and final systemic availability falls | Complete AUC/D falls; Cmax/D often falls | Direction alone does not locate the loss or its mechanism |
| 2c: saturable efflux or first pass, F rises | Complete AUC/D rises; Cmax/D direction also depends on rate | Saturable elimination can also give more-than-proportional exposure |

   - Interpret pattern 2a only with adequate total exposure and unchanged clearance. An unchanged fraction reaching systemic blood can coexist with slower absorption; a falling complete AUC/D requires a different explanation.
   - If Cmax/D falls more than common-window AUC/D, report both changes. Examine peak sampling and later exposure before proposing slower or more prolonged input. This contrast alone establishes neither saturation nor input order.
   - DECREASING_EXTENT_OR_INCREASING_CLEARANCE applies to falling **complete** AUC/D: evaluate F and clearance using comparable IV data across the relevant exposure range. A reduction confined to a partial window may reflect redistribution of input in time.
   - PO and IP: rising AUC/D can come from saturable first pass (FIRST_PASS_POSSIBLE).
   - Mechanism context (not evidence): saturable uptake transporter (gabapentin, Larsen et al. 2015 Pharm Res 32:898); saturable efflux (celiprolol; Bolger et al. simulation, citation note below); saturable presystemic metabolism (Ludden 1991 Clin Pharmacokinet 20:429); IP first pass in rodents (Lukas et al. 1971 JPET 178:562; Al Shoyaib et al. 2020 Pharm Res 37:12); solubility-limited absorption (Belubbi et al. 2023 Pharmaceutics 15:191); gastric emptying (Baruffol et al. 2014; Langeskov & Kristensen 2022; Flint et al. 2011); SC/IM site effects (Owens 2016; Turner et al. 2011; Bernards & Kopacz 1999). Mechanisms can combine (MIXED).
   - Citation note: "Bolger et al. 2013" could not be matched; the likely source is Bolger, Lukacova & Woltosz 2009 AAPS J 11:353 (doi 10.1208/s12248-009-9111-6), not re-checked for the quoted numbers.
7. Tmax: a shift within one sampling interval adds TMAX_WITHIN_SAMPLING_INTERVAL and makes the Tmax sign NOT_AVAILABLE. Tmax unchanged with dose is weak evidence only.
8. UNRESOLVED when doses are not comparable (studies, regimens, record levels, exposure definitions, occasions) or fewer than two doses qualify. Use separate strata in the primary dose comparison. The E4 diagnostic explicitly compares steady-state AUCτ to same-dose first-dose AUC∞ under its own assumptions.

Output per dose series
`t3_label` (A0.3), `t3_ratio`, `t3_ci`, `t3_ci_level`, `t3_window_h`, `t3_dose_pair_or_contrast`, `t3p_label`, `t3p_dose_pair`, `t3p_times`, `t3p_ln_ratio_ci` (per time), `t3p_p_holm` (per time), `t3p_data_level`, `t3_data_level` (INDIVIDUAL / SPARSE_ESTIMATOR / GROUP_SUMMARY_SD / GROUP_SUMMARY), `basis_of_judgement`, `iv_t3_label`, `descriptive_signs` (E1–E9 with values), `pattern_candidates[]` (2a / 2b / 2c / ELIMINATION_NONLINEARITY_POSSIBLE / DECREASING_EXTENT_OR_INCREASING_CLEARANCE, unranked), `mixed`, `doses`, `tmax_by_dose`, `cmax_per_dose`, `auc_per_dose` with basis, `evidence_rows`, `caveats` (NARROW_DOSE_RANGE, WINDOW_TRUNCATION_RISK, DIFFERENT_STUDIES, REPORTED_MODEL_AUC, REPEATED_DOSE, GROUP_MEAN, DIGITIZED, TMAX_WITHIN_SAMPLING_INTERVAL, FIRST_PASS_POSSIBLE, BASELINE_CONFOUNDED, CMAX_ABOVE_ULOQ).

Reporting wording
"Within the stated dose range, dosing conditions, population assumption and uncertainty handling, the data are incompatible / not yet shown incompatible / not assessable with a common, dose-independent linear model." Report R and CI, direction, dose pair, interval basis and sensitivity results. Rdnm and b1 are descriptive; with a suitable statistical model and CI they can support a formal proportionality assessment, but neither locates the mechanism.

Purpose, limits, and main-objective link
Identifies departures from dose-normalized superposition and the input or disposition alternatives to test before scaling exposure with dose. A highest/lowest dose ratio below 3 gives weak evidence (NARROW_DOSE_RANGE).

Keywords: dose proportionality; superposition; dose-normalized AUC; CI; saturable absorption; Michaelis–Menten elimination; first-pass saturation.
MP basis: MAIN.MP001/MP003; eda_scientific_reference item 05.
Sources: Gabrielsson et al. 2016 cases 7, 9, 10 and eq. 36/37; Smith et al. 2000 Pharm Res 17:1278 (doi 10.1023/A:1026451721686); Hummel et al. 2009 Pharm Stat 8:38; Bailer 1988 J Pharmacokinet Biopharm 16:303 (doi 10.1007/BF01062139); Zhou et al. SUGI 31 paper 182-31; simulation note 2026-11-03.

---
### 20 | EXTRAVASCULAR INPUT: MULTIPHASE PATTERNS (DIP AND SECOND RISE, SHOULDER, PLATEAU, DECLINE THAT STEEPENS)

Scope
- Describe the multiphase patterns specified by item 20 whenever visible. Independently run T2 on every eligible verified serial profile with enough ordered samples, including when tier 1 has no visible trough. The visual trigger controls the display of the T2 layer. Sparse rising-limb sampling alone does not block a post-peak check.

Data and details
- As item 17 over the whole profile; dosing record (every administration); same-species IV profiles; formulation and vehicle; feeding state; record level; inhaled dose basis.

Figures (A0.11)
- Panels A1 and B1 for the first view of a second rise, shoulder or plateau.
- Panel B1: split-half slopes with ratio and label; dip or second-peak points circled, with SINGLE_POINT_SUPPORT when it applies.
- Individual layer with individual data; the T2 layer of B1 (tier 2) only for serial samples of one animal after a single dose or confirmed washout.
- A3 (tier 3): the ΔC/Δt sequence used to judge shoulders. The EV/IV overlay is panel D1 (item 18) and is not repeated here.

Execution (in this order)
1. Raw description only, per animal: number of peak regions, apparent dips, shoulders (judged from ΔC/Δt, because sampling intervals may differ), plateaus, the post-peak description (A0.7). Patterns are recorded as suspected; T2 is not run in this step.
2. Analysis unit: same animal, analyte and matrix, known dosing history. Serial individual data → T2 can be run. Group means and destructive sampling → description only; no exclusion of individual-level models. Output: T2 runnable / description only / not yet assessable.
3. Record checks: actual sampling times, dosing events, series membership, duplicate records, units, assay flags. A mismatch between plotted points and nominal times is investigated, not automatically treated as an error. The next dose is a real additional input, not an artefact: set the analysis window from the dosing record; a dip that spans a later dose cannot exclude a single-dose model.
4. Verify positive-time order where needed and joint coverage of the concentration bounds across the searched data (A0.3–A0.4). Keep time and concentration uncertainty separate.
5. T2 (A0.10): search all time-ordered triples, keep raw point IDs; no smoothed curve is used as evidence. Report M_drop, M_rise, M_T2 and M_T2/U_b only when the denominator is usable.
6. Evidence strength, recorded as separate fields:
   - T2_NUMERIC_CONTRADICTION: whether the intervals form a contradiction.
   - SINGLE_POINT_SUPPORT: use the three distinct removal outcomes in A0.3. A missing or unverified critical observation is an evidence limitation; preserve it and withhold exclusion until verified.
   - EXCLUSION_APPLIED: require the complete model premises, justified bounds and the A0.3 evidence and robustness gates. Report CANNOT_ASSESS with SENSITIVITY_ONLY for a project-set error scenario; a number from this scenario alone does not establish a formal contradiction.
   - For statistical bounds, protect the full search across eligible samples/triples and any animals covered by the claim. Omitting a point evaluates fragility; it cannot control the false-positive rate of a search. Without joint uncertainty, keep the margin as sensitivity only.
7. Hand-off: animal and analysis window; raw point IDs, actual times and concentrations; intervals and their basis; M_drop, M_rise, M_T2; error sensitivity; sparsity and source issues; combinations formally excluded; explanations kept; the data that would best discriminate them. Fixed sentence: "Not excluded does not mean supported; a robust dip does not prove two absorption phases."

What a confirmed dip excludes
- With EXCLUSION_APPLIED, reject the complete combination of one log-concave input rate, a single dose and zero initial state, central input and observation, and linear, time-invariant one-compartment or reversible mammillary disposition. Covered inputs include finite zero-order or first-order input, ordered serial first-order transit compartments with fixed rates, and a single Weibull with β ≥ 1. A common fixed lag preserves this prediction. The Weibull β < 1 rate is outside the stated log-concavity proof; that fact alone does not predict a second peak (A0.10).
- Retain other complete explanations consistent with the dosing context: separated releases or input pathways with distinct timing, interrupted gastric emptying, site-specific uptake, recirculation, an independently plausible alternative disposition, or pulmonary and swallowed GI contributions after inhalation. Record which data could discriminate the remaining possibilities, for example verified redosing history, the same animal’s observations bracketing the dip, an IV profile or independent formulation/release data.
- A double peak after a single administration never establishes two inputs (Davies et al. 2010 Clin Pharmacokinet 49:351; Yousef et al. 2025 Clin Pharmacokinet, doi 10.1007/s40262-025-01559-4).

IV comparison wording
- After the dosing record and data source are checked, a reliable re-rise also after IV strengthens suspicion of recirculation or another disposition process; it does not alone diagnose enterohepatic recirculation.
- No second peak after IV does not exclude recirculation: compare sampling density, observation time, assay sensitivity, dose and feeding. Oral first pass can change the amount entering bile and being reabsorbed; biliary excretion and enterohepatic cycling also occur after IV; fasting does not mean no recirculation (Kim et al. 2015 AAPS J, fimasartan, doi 10.1208/s12248-015-9764-2: second peaks after IV and oral dosing).
- These questions go to joint absorption–disposition modeling and are marked "pending DME"; they are not removed from the absorption section.

Shape labels (limits)
- Shoulder, plateau and DECLINE_STEEPENS cannot exclude any combination by themselves or through T2; other proven tests (for example T1) still run independently.
- A plateau needs a pre-set change tolerance and minimum duration; "no significant slope detected" does not confirm a plateau.
- DECLINE_STEEPENS explanations, unranked: ordinary first-order absorption + linear elimination (retained unless an independent eligible test formally excludes that complete combination), burst plus sustained input, saturable elimination (pending DME), other disposition structures. Discriminating data: IV, dose comparison (item 19, step 4), formulation or dissolution information, denser sampling. An abrupt corner between two near-linear semilog segments is described as such; it does not exclude ordinary absorption by itself.
- A second maximum resting on one time point: SECOND_PEAK_CANDIDATE with SINGLE_POINT_SUPPORT; the point is kept. UPSTREAM_ISSUE only with evidence of a source, time or assay conflict.
- Repeated alternation (up, down, up, down) beyond tolerance: described as ALTERNATION; on group-mean or digitized data check plotted points against nominal times, mixing of series and digitization.
- Species context (not evidence): rats and horses have no gallbladder; coprophagy and caecotrophy in rodents and rabbits; rodents feed at night.

Output per profile
`pattern_description` (DIP_AND_RERISE / SHOULDER / PLATEAU / DECLINE_STEEPENS / ALTERNATION / NONE, more than one allowed), `analysis_unit_status`, `t2_label`, `t2_margins` (M_drop, M_rise, M_T2, M_T2/U_b), `t2_points`, `T2_NUMERIC_CONTRADICTION`, `SINGLE_POINT_SUPPORT`, `EXCLUSION_APPLIED`, `excluded_combinations`, `explanations_kept`, `pending_dme`, `peak_times_h`, `increment_sign_sequence`, `consistency` (across doses and studies), `evidence_rows`, `caveats` (SECOND_PEAK_CANDIDATE, DESTRUCTIVE_SAMPLING, GROUP_MEAN, UPSTREAM_ISSUE, DIGITIZED, PULMONARY_AND_GI_UNRESOLVED).

Purpose, limits, and main-objective link
Reports whether an individual trough and re-rise challenges the specified single-input, unimodal combinations, with the witness points, uncertainty and removal checks. A shoulder, flat peak or reread of a group mean may motivate targeted sampling or modeling; it cannot establish an individual trough. Compare surviving input and disposition hypotheses in modeling (A0.9).

Keywords: double peak; confirmed dip; shoulder; plateau; decline steepens; burst release; recirculation; unimodality.
MP basis: MAIN.MP003; CPK01 absorption concept.
Sources: Prékopa 1973 Acta Sci Math (Szeged) 34:335; Ibragimov 1956 Theory Probab Appl 1:255; Davies et al. 2010; Yousef et al. 2025; Kim et al. 2015; Ogungbenro et al. PAGE 2012; Chauvin et al. PAGE 2019; Ibarra et al. 2014 J Pharmacokinet Pharmacodyn 41:363.

---

### 21 | EXTRAVASCULAR INPUT: TIME ORIGIN AND PREDOSE BASELINE

Scope
- Every EV profile. Single documented first doses of an exogenous drug get DESIGN_ZERO directly; the item does real work when the predose of this dose is quantified, when the history implies drug on board, or when the compound is also endogenous.

Data and details
- Predose concentration of this dose with its status; full dosing history (doses, times, interval τ, day, washout); profile Cmax and LLOQ; origin, baseline_behavior, assay_specificity (A0.8).

Figures (A0.11)
- Panel A1. On it for this item: the predose point at its actual time with its value and percentage of Cmax; DESIGN_ZERO as an open diamond labelled "zero by design, not measured"; for endogenous compounds the baseline level as a reference line (also when ENDOGENOUS_REVIEW_REQUIRED limits the display to A1 and B1). No baseline-subtracted curve is drawn.
- Table row per profile: predose value, predose/Cmax, occasion, interval since the previous dose.

Recognition
1. `baseline_status`:
   - ZERO_OR_BLQ: predose measured zero or BLQ. Precedence: a measured predose > WASHOUT_ZERO > DESIGN_ZERO.
   - DESIGN_ZERO: documented single first dose of an exogenous drug with no predose sample; zero by design, not measured; drawn as an open diamond at 0 h.
   - WASHOUT_ZERO: a later period of a crossover, or a later dose after a documented washout of at least 5 terminal half-lives, with the predose not reported or BLQ. This is an assumption, not a measured zero: under mono-exponential decline 2⁻⁵ = 3.1 % remains after 5 half-lives, and more remains when the previous input was delayed, prolonged or multiphasic. Check the full dosing history first.
   - RESIDUAL_FROM_PRIOR_DOSE: repeated dosing, or a previous dose less than 5 terminal half-lives before this dose (any previous dose in the regimen when no half-life is known).
   - ENDOGENOUS / MIXED: origin stated by the source (A0.8). MIXED: endogenous plus prior-dose residual.
   - UNEXPLAINED: quantified predose on a documented first dose of an exogenous compound → UPSTREAM_ISSUE with candidates carry-over or contamination, assay interference, time-origin error, mislabelled group.
   - NOT_ASSESSABLE: predose not sampled or not reported and history unknown.
2. `baseline_size` (exogenous compounds): predose/Cmax for this profile.
   - ≤ 5 % → NEGLIGIBLE for Cmax- and AUC-type readings (items 17, 19, 22, 23). It does not lift item 16's NOT_ASSESSABLE for a quantified predose, and it does not cover the late profile: for items 18 and 22 compare the predose value with the terminal-window concentrations and C(T); add RESIDUAL_BASELINE when it exceeds 5 % of those.
   - > 5 % → RESIDUAL_BASELINE; data kept and flagged.
   - Basis (regulatory precedent, used here only to decide whether a caveat is needed): EMA CPMP/EWP/QWP/1401/98 Rev.1 (2010) §4.1.8 (exclusion above 5 % of Cmax; "does not apply to endogenous drugs"); FDA, Bioavailability Studies Submitted in NDAs or INDs (2022), Appendix A §C.
   - Detectability: EMA §4.1.7 asks for an LLOQ ≤ 1/20 of Cmax. Predose BLQ with LLOQ > 5 % of Cmax → BLQ_ABOVE_5PCT_CMAX, not NEGLIGIBLE.
3. Endogenous: apply ENDOGENOUS_REVIEW_REQUIRED only to endogenous or mixed total/unspecified signal. A verified exogenous-specific assay can proceed after residual and dosing-history checks.

Rules
- EDA never subtracts a baseline.
- Constant subtraction of the predose value: the error direction follows the residual's trajectory, which follows the previous input. A residual already declining is over-corrected, increasingly with time; a residual still rising (slow depot, flip-flop or multiphase input of the previous dose) is under-corrected at first. When the previous input is not known well enough, no direction is stated.
- Hand-off (G2016 point 4): model the full dosing history (preferred), or set the initial condition from the measured predose, which is exact only for one-compartment disposition with an empty depot. For an endogenous compound, a production (turnover) term is used instead of subtraction (G2016 case 11).

Consequences for the other items
- Item 16: NOT_ASSESSABLE when the predose is quantified or unknown.
- Item 17: RESIDUAL_BASELINE caveat; shape stays descriptive.
- Item 18: the terminal phase mixes doses: compare with IV only on the same occasion, or MIXED_DOSE_TERMINAL.
- Item 19: doses compared only on the same occasion; steady-state AUCτ and single-dose AUC are not mixed.
- Item 20: a rise caused by the next dose is a new dose, not a second peak.
- Zero-initial-state tests require a justified zero amount in all relevant compartments. A low or BLQ predose concentration alone cannot exclude residual drug in a depot or tissue. Use documented history, washout and residual bounds; otherwise describe the data and withhold zero-state exclusions. Dose-series T3/T3p can assess a scaled complete regimen from its zero start (item 19). Item 23's separate occasion comparison explicitly accounts for accumulation.

Output per profile
`baseline_status` (ZERO_OR_BLQ / DESIGN_ZERO / WASHOUT_ZERO / RESIDUAL_FROM_PRIOR_DOSE / ENDOGENOUS / MIXED / UNEXPLAINED / NOT_ASSESSABLE), `baseline_size` (NEGLIGIBLE / RESIDUAL_BASELINE / BLQ_ABOVE_5PCT_CMAX / NOT_APPLICABLE), `origin`, `baseline_behavior`, `assay_specificity`, `predose_value`, `predose_to_cmax`, `dosing_occasion`, `evidence_rows`, `caveats` (RESIDUAL_BASELINE, BLQ_ABOVE_5PCT_CMAX, MIXED_DOSE_TERMINAL, WASHOUT_ZERO, ENDOGENOUS_REVIEW_REQUIRED, UPSTREAM_ISSUE).

Purpose, limits, and main-objective link
Protects items 16–23 from reading a residual or endogenous signal as absorption, and tells modeling which profiles need the dosing history, a predose initial condition or a production term. Item 06 (repeated dosing and accumulation) owns accumulation itself.

Keywords: predose; baseline; residual; washout; endogenous; assay specificity; initial condition; dosing history.
MP basis: MAIN.MP003; reference item 06.

---

### 22 | EXTRAVASCULAR INPUT: EXTENT OF ABSORPTION (SYSTEMIC F)

Scope
- Use comparable IV exposure of the appropriate reference analyte for systemic F. With two EV profiles and no IV, complete dose-normalized exposures may support relative availability under shared linear clearance. A partial or unmatched exposure ratio remains descriptive.

What F means here
- Item 22 reports systemic F, labelled with the analyte. For oral dosing F = Fa·Fg·Fh; plasma AUC gives only the product (F = 0.3 can be poor absorption or complete absorption with 70 % first-pass loss).
- Route context for F < 1 (not a conclusion): PO, Fa, Fg and Fh all possible; IP, mainly portal uptake with hepatic first pass; SC and IM, no first pass, losses from site degradation or incomplete release; inhaled, pulmonary plus swallowed GI absorption (A0.8).
- Split Fa, Fg and Fh only when independent route and physiology evidence supports the split. For hepatic blood clearance, Fh=1−CL_hep,blood/Q_hep under the single-pass extraction model. If only total blood clearance is known, nonnegative extrahepatic clearance gives Fh ≥ max(0,1−CL_total,blood/Q_hep); equality requires exclusively hepatic clearance. Require compatible blood units and hepatic flow, and an appropriate linear extraction model. F_PO/F_IP is a route availability ratio. Interpreting it as Fa·Fg also requires independently justified complete IP uptake into portal blood, negligible bypass and shared hepatic extraction/clearance.
- Translation note: animal Fg and Fh do not transfer directly to human oral dosing.

Data and details
- Per profile: dose and dose_basis (salt or base, mg or IU, molar for prodrugs; inhaled dose basis), route_detail, iv_mode (BOLUS / INFUSION with duration), analyte_role, iv_reference_compound, record level, LLOQ, study and animal state.
- Item 19 T3 result for each route, item 18 result, item 21 baseline fields. Source-reported F or AUC, labelled with definitions.

Figures (A0.11)
- Figure D when the preconditions below hold: panel D2, dose-normalized IV and EV on linear axes, common window shaded (semilog: D1); f_status, window, tail shares, IV early-area compensation and bias directions. Otherwise one line with f_status and the reason.
- Source-reported F: figure F (A0.12).
- Table: one row per EV/IV pair with doses, window, AUCs, F_window, bias list and status.

Preconditions (failure → NOT_ESTIMABLE or a caveat, with the reason)
1. Dose basis identical, or converted with a factor stated by the source; otherwise NOT_ESTIMABLE (DOSE_BASIS_MISMATCH).
2. Match analyte, matrix and dose basis. For parent F use IV administration of the same parent. For active formed from a prodrug, follow the separate active-moiety convention in A0.8 (including stoichiometry and common active-drug clearance); a claim about parent absorption requires independent formation evidence.
3. An F interpretation requires shared, dose-independent systemic clearance. Matching study and animal state supports comparability without proving it. Report the source of independent support or the assumption, and record cross-study status separately.
4. Require defensible shared linear systemic clearance for an F interpretation. A T3/T3p contradiction identifies a joint input/disposition hypothesis, not its cause. Similar Cmax, including a difference below twofold, cannot establish common clearance in nonlinear PK. Without independent support, report a dose-normalized exposure ratio only. Retain dose-range flags and their direction only when independently supported.
5. Endogenous: ENDOGENOUS_REVIEW_REQUIRED → not computed on the total signal.
6. A mean curve gives a point estimate. Any CI must reflect the actual design, integration rule, sampling covariance and censoring. Crossover requires within-animal contrasts; destructive sampling requires an estimator compatible with A0.6 (see T3).

Calculation (host code, observed data only)
- F_window = (AUC_EV,window/D_EV)/(AUC_IV,window/D_IV) on [0, T], T = the last time quantified in both profiles, A0.6 method, no extrapolation. Also report F over a shorter common window when one exists.
- For a documented drug-free first dose of an exogenous drug, a zero EV baseline may anchor the first chord. It underestimates the area of a concave rise and overestimates an entirely convex rise. A sigmoid changes curvature; the net error has no predetermined sign without knowing which segment was missed.
- After a documented IV bolus with non-increasing central concentration, the missing early area is at least t₁·C(t₁). The observed denominator omits this area, raising the ratio relative to the same window with full IV coverage. Label an adjusted value minimum compensation only under those premises. With unknown IV mode, it is an optional bolus scenario, not a measured correction or guaranteed bound.
- IV early coverage is justified only by a source-reported back-extrapolated share or another independent upper bound on the missing share. Without a justified upper bound the size is unknown and a negligible contribution has not been established.
- IV infusion: the window ratio has no general bias direction (EV input can precede a long infusion; R3-05). The known infusion time course is stated and the truncation direction is UNKNOWN unless a model-based correction is supplied.
- Tails: with a qualified terminal slope (A0.7), conditional estimated tail share = C(T)/(λz·AUC₀–T + C(T)), dimensionless, per profile. The slope/window must end at T, or the later slope must be independently justified for T. A later terminal window does not prove terminal behavior at an earlier common endpoint. Without a qualified slope → TAIL_NOT_ASSESSABLE (no C(T)/AUC substitute: it has units of 1/time). Tail share > 5 % → EV_TRUNCATED / IV_TRUNCATED. For an IV bolus under shared linear disposition the EV retains an equal or larger fraction of total exposure after T than IV, so truncation alone biases the ratio downward or leaves it unchanged when early areas are complete; this direction holds only for an IV bolus.
- List each possible source of bias and its scope. Distinguish an incomplete numerator or denominator from the combined error versus total F. For unknown IV mode, uncertain early EV curvature or unsupported nonlinear clearance, state that direction is unresolved.

Status (`f_status`)
- ESTIMATED_WINDOW: same-study, shared linear clearance, compatible analyte and dose basis, justified IV early coverage and both estimated tail shares ≤5% under qualified windows. This status describes a window estimate; a fitted apparent tail is a sensitivity estimate, not a proven bound.
- UPPER_BOUND / LOWER_BOUND: every non-negligible bias has a known direction and all point the same way (for example the EV tail inside the window and only the IV early area missing → UPPER_BOUND).
- APPROXIMATE: opposing, bounded sources of bias with a defensible quantitative approximation. A nonlinear dose mismatch with uncertain clearance gives only an exposure ratio unless an independent correction is justified.
- INCOMPLETE_EXPOSURE_RATIO: any non-negligible bias of unknown direction or unknown size where size matters (TAIL_NOT_ASSESSABLE, infusion truncation UNKNOWN). The value is an incomplete exposure ratio, not F.
- INDIRECT labels the comparison basis when IV is from another study. Store this qualification independently of completeness. A reported IV half-life without IV exposure or comparable IV clearance cannot supply an F denominator.
- RELATIVE_ONLY requires comparable complete dose-normalized EV exposures and a defensible shared linear clearance. Otherwise report the observed-window exposure ratio and its assumptions without calling it relative F.
- SOURCE_REPORTED: F taken from the source, no curve-based F_window (A0.12); reported beside the curve-based statuses, not ranked with them.
- NOT_ESTIMABLE: absolute F lacks a valid analyte/dose basis, usable IV denominator, or defensible shared clearance; unresolved endogenous signal also blocks F.
- Record source-reported values separately. For calculated exposure, first check analyte, dose basis and denominator. Missing required prerequisites give NOT_ESTIMABLE for F; if a descriptive ratio is available, retain it separately. Unknown bias or incomplete exposure takes precedence over INDIRECT and RELATIVE_ONLY. Use a directional bound only when all material errors have justified signs. Report comparison_basis separately for every branch.
- F_ABOVE_ONE: log every estimate above 1 and its uncertainty. A digitization tolerance may qualify the size of the discrepancy only when derived from the actual measurements and integration method. Do not use a fixed 1.105 multiplier across datasets.
- No cut-off for low or high F is applied.

Output per EV profile
`f_status`, `f_window`, `f_window_min_iv_compensation`, `f_bias_list` (each bias with direction and size status), `window_h`, `iv_profile`, `iv_mode`, `infusion_duration_h`, `analyte_role`, `iv_reference_compound`, `dose_basis`, `comparison_basis`, `ev_tail_share`, `iv_tail_share`, `iv_early_lower_bound_share`, `fa_fg_fh_note`, `evidence_rows`, `caveats` (IV_EARLY_AREA_MISSING, EV_EARLY_CHORD, EV_TRUNCATED, IV_TRUNCATED, TAIL_NOT_ASSESSABLE, IV_OTHER_STUDY, DOSE_BASIS_MISMATCH, NONLINEAR_DOSE_MISMATCH, LINEARITY_UNTESTED, F_ABOVE_ONE, RESIDUAL_BASELINE, GROUP_MEAN, DIGITIZED, PULMONARY_AND_GI_UNRESOLVED, ENDOGENOUS_REVIEW_REQUIRED).

Purpose, limits, and main-objective link
State what the evidence supports about systemic availability and the basis for any modeling decision. An observed-window estimate alone does not justify fixing F; unresolved absorption and clearance remain explicit.

Keywords: systemic bioavailability; Fa Fg Fh; AUC ratio; common window; IV early area; tail share; IV infusion; analyte role; dose basis.
MP basis: MAIN.MP003 (F, CL/F).
Sources: Gabrielsson et al. 2016 eq. 37 and case 4; Bailer 1988; Al Shoyaib et al. 2020 (IP first pass).

---

### 23 | EXTRAVASCULAR INPUT: COMPARISON ACROSS CONDITIONS

Scope
- Two or more EV profiles of the same drug, species, analyte and matrix that differ in a stated condition: route, formulation or vehicle, injection site or volume, fed or fasted; animal state (infection, neutropenia, anaesthesia, strain, sex, age, weight); dosing occasion (first vs later dose).
- Dose comparisons are item 19; EV vs IV are items 18 and 22. This item asks which explanations of a difference between conditions the data exclude: change of input rate only, change of the amplitude only (F, or CL and V co-scaled), change of disposition, or combinations.

Data and details
- Per profile: condition labels, dose and dose_basis, route_detail, study, design (crossover, parallel, terminal sampling, randomization), sampling times, record level, LLOQ, occasion (item 21), items 16–22 results.
- Every attribute that differs between the profiles, not only the one of interest. One profile is the reference; ratios are test/reference.

Figures (A0.11)
- Figure E: E1 dose-normalized overlay, linear and semilog, one colour per condition, reference solid, differing attributes listed; E2 c intervals with the common-c band (T5) and the rate-only check result.
- Panel E3 (tier 3): shape panel, each profile divided by its own window AUC (C/AUC_window, 1/h); separation after normalization suggests a difference in the shapes over that window. Interpret alongside T5 and sampling coverage.
- Table: one row per pair with differing attributes, metrics, test results.

Preconditions
1. Same drug, analyte, matrix and concentration basis; dose basis identical or converted with a stated factor. Failure → NOT_COMPARABLE (direction-only metrics may be shown).
2. Common window [0, T] with at least 3 quantified points per profile. Failure → NOT_ASSESSABLE.
3. Same dose on the same basis; otherwise DOSE is listed as a differing attribute. A T3 result of NOT_EXCLUDED does not show linearity: a dose-normalized comparison across different doses then rests on an assumed linearity, stated in the output.
4. Same occasion (except in the occasion comparison); otherwise OCCASION_CONFOUNDED.
5. ENDOGENOUS_REVIEW_REQUIRED on either profile → tests not run on the total signal.

Tests
1. T5, proportional family (A0.10). EXCLUDED: no single amplitude factor explains the difference; "F only", "CL and V co-scaled" and their combination are excluded together. NOT_EXCLUDED: these members stay, and they cannot be separated from EV data alone. For a visible shape difference with adequate T5 evidence, compare input timing and disposition in modeling. If one scale factor is compatible with the observations, retain amplitude-related explanations and assess clearance independently. With sensitivity-only evidence, describe the observed ratios and the assumed bounds before drawing any inference about shape.
2. Rate-only check under shared linear disposition, the same effective systemic input site and unchanged total availability: AUC∞/D = (total systemic input / administered dose) × ∫h(t)dt = F/CL for central plasma parent concentration. The input time course can differ.
   - Test: ratio of complete dose-normalized AUC between conditions, with a pre-set CI (T3 conventions: data level, CI level, method). CI excluding 1 → "common LTI disposition + rate change only" EXCLUDED_UNDER_STATED_ASSUMPTIONS.
   - Use bounds on the unobserved area valid on both sides. An apparent terminal slope supplies a conditional estimate only unless supported independently. After a dose with nonnegative ongoing input in one compartment, C(T)/k_IV can give a lower bound on remaining exposure, not an upper bound. Use joint uncertainty in the AUC contrast.
   - CANNOT_ASSESS when complete exposure cannot be assessed reliably (EV_TRUNCATED without an independent two-sided tail bound, TAIL_NOT_ASSESSABLE).
   - Premise is common linear time-invariant disposition, not only "unchanged disposition parameters": with saturable elimination, a change of input speed can change the concentration range and complete AUC; then this test is CANNOT_ASSESS. A condition that itself changes disposition (for example food changing hepatic blood flow) is a disposition change.
   - Complete AUC is the preferred rate-invariance criterion, not the only one; with a specified rate model other necessary conditions can be tested in modeling.
   - A truncated-window AUC never judges extent alone. For the parent drug under linear PK, a changed complete dose-normalized AUC identifies a difference in F/CL. With supported common clearance the complete EV ratio estimates relative F. With suitable IV data in **both** conditions, compare each EV profile with its own IV reference (item 22) to separate relative F from the clearance change. EV-only data with clearance unresolved leave both explanations open.
3. Disposition: from EV curves under two conditions alone, input and disposition changes usually cannot be separated uniquely. "Disposition unchanged" is an explicit assumption or comes from independent data (IV under each condition, parameter constraints, mechanistic data, joint design); it is never inferred from an equal half-life (one compartment: CL′ = a·CL, V′ = a·V keeps k and the half-life).
4. Descriptive metrics (do not exclude anything): Tmax (counts only when |ΔTmax| exceeds the longer of the two bracketing sampling intervals and neither profile has FLAT_TOP_WITHIN_TOLERANCE, Tmax at the first sample or UPSTREAM_ISSUE); Cmax/AUC_window (Endrenyi, Fritsch & Yan 1991; Tozer et al. 1996); early-exposure share AUC(0, t_e)/AUC_window with t_e the earlier countable Tmax (Chen et al. 2011); window AUC/D ratio; apparent terminal half-life ratio. Band [0.80, 1.25] (digitized [0.72, 1.38]) is used for "difference seen in the description" only; without a CI it is not an equivalence test.
5. Flip-flop: when item 18 is UNRESOLVED or ABSORPTION_INFLUENCED_CANDIDATE for either profile, a terminal difference may come from input and is not labelled a clearance or elimination change.

Summary
- `explanations_excluded[]` and `explanations_not_excluded[]`, each with the test, label and basis of judgement. Possible entries: RATE_ONLY, AMPLITUDE_ONLY (F only, or CL and V co-scaled), DISPOSITION_CHANGE, combinations.
- No upgrading: "rate, or extent/disposition" is never merged into RATE_AND_EXTENT. A combined label is used only when each component is supported by its own test result and the others are excluded.
- Caveats (CONFOUNDED with every differing attribute, OCCASION_CONFOUNDED, LOCAL_ROUTE, PULMONARY_AND_GI_UNRESOLVED, EV_TRUNCATED) travel with every result.

Causal wording
- EDA reports the difference between conditions and the candidate explanations. It does not attribute cause or mechanism automatically; whether causal wording is allowed is decided by the study design and its assumptions.
- Two questions are kept apart: whether the condition changed exposure (a suitably designed, conducted and analysed randomized study can support this; crossover studies also need period and carry-over effects, ICH E9), and whether the exposure change came from absorption rate or F (usually needs mechanistic evidence).
- "The groups differ in one recorded condition" alone does not establish cause: occasion, covariates, selection and design are stated. A different study counts as a differing attribute unless the source states matched conditions. Group means need the same-population assumption.

Dosing occasion (time dependence)
- Compare the first dose with a later dose of the same regimen, same dose and formulation, over [0, τ] after each dose.
- Under linear time-invariant PK with non-negative inputs, the later profile is the first-dose profile plus the residual of earlier doses, so AUCτ,later ≥ AUCτ,first. AUCτ,later/D below AUCτ,first/D with a CI (or allowed intervals) excluding equality → "LTI with identical dose-by-dose input" EXCLUDED_UNDER_STATED_ASSUMPTIONS (TIME_DEPENDENCE_SUSPECTED, decrease). Needs no extrapolation.
- For equal doses under demonstrated steady state, compare interval exposure with complete first-dose AUC only under item 19 E4. For dose n given every τ with identical input and LTI PK, the predicted concentration at time t after dosing is Σ_{j=0}^{n−1} C₁(t+jτ). At steady state the sum extends over the full dosing history. Observed first-dose terms at matching times give a lower bound when unobserved terms are nonnegative. A later value above that partial sum alone cannot establish excess accumulation. An increase over the first interval alone is compatible with accumulation.
- Within TIME_DEPENDENCE_SUSPECTED, candidates (unranked): absorption side (changed rise or Tmax: injection-site change, induction of gut transporters or enzymes); disposition side (changed half-life: induction of clearance, disease progression). Pending DME.
- A day-2 or steady-state profile is never compared with another study's single-dose profile as the same occasion.

Other rules
- Animal state is a condition to compare, not evidence for a mechanism: infection, neutropenia and anaesthesia can change rate, extent and disposition.
- Following intratracheal or inhaled dosing, plasma may combine pulmonary and enteral uptake. A plasma difference compares systemic exposure; inference about availability needs shared clearance and adequate exposure coverage. Target-site delivery needs local measurements.

Translation note
- Absorption parameters (ka, tlag, F, MAT) are route-, formulation- and species-specific and are not scaled allometrically.
- For human IV prediction, animal EV data can inform jointly estimated disposition only to the extent supported by reference data and identifiability. Confounding or a condition effect can affect estimates of CL and V. Pass competing input and disposition explanations to the relevant modeling stages.
- Human route PO: animal F and absorption rate do not transfer directly; condition effects are context, not priors.
- A result where DISPOSITION_CHANGE is not excluded and supported by independent data (for example infection state changing clearance) is passed to the elimination section.

Output per compared pair
`condition_of_interest`, `reference_profile`, `differing_attributes`, `design`, `t5_label` with margins, `rate_only_label` with ratio, CI, CI level and tail basis, `disposition_assumption` (ASSUMED / SUPPORTED_BY with source / NOT_ASSUMED), `explanations_excluded[]`, `explanations_not_excluded[]`, `basis_of_judgement`, `tmax_pair`, `cmax_auc_ratio`, `early_share_ratio`, `window_auc_d_ratio`, `thalf_ratio`, `window_h`, `band_used`, `evidence_rows`, `caveats` (CONFOUNDED, DOSE_BASIS_MISMATCH, OCCASION_CONFOUNDED, LOCAL_ROUTE, PULMONARY_AND_GI_UNRESOLVED, GROUP_MEAN, DIGITIZED, EV_TRUNCATED, TAIL_NOT_ASSESSABLE, UPSTREAM_ISSUE, ENDOGENOUS_REVIEW_REQUIRED). Occasion comparisons add `time_dependence` (TIME_DEPENDENCE_SUSPECTED / NO_DECREASE_DETECTED / NOT_ASSESSABLE).

Keywords: condition comparison; proportional family; rate versus extent; complete exposure; F/CL; disposition change; causal wording; time-dependent absorption.
MP basis: MAIN.MP003; reference items 06 and 19.
Sources: Endrenyi, Fritsch & Yan 1991 Int J Clin Pharmacol Ther Toxicol, PMID 1748540; Tozer et al. 1996 Pharm Res, doi 10.1023/A:1016061013606; Chen et al. 2011 Pharm Res 28, doi 10.1007/s11095-011-0421-x; ICH E9 (statistical principles for clinical trials); FDA 2022 and EMA 2010 bioequivalence limits (scale only).

---
### Flag registry (items 16–23, r4)

Each flag is defined once; the item text gives the detail. Evidence labels (EXCLUDED_UNDER_STATED_ASSUMPTIONS, NOT_EXCLUDED, CANNOT_ASSESS, BORDERLINE, SINGLE_POINT_SUPPORT, SENSITIVITY_ONLY) are defined in A0.3. Values of a single output field (onset_status, rise_shape, flip_flop_reading, f_status, t3_data_level, time_dependence, answer status) are defined in their item or in A0.11–A0.12, not here.

| Flag | Item | Trigger |
|---|---|---|
| KNOWN_INPUT_PERIOD | A0.8; 16, 17, 18 | Time between administration_start and administration_end of a known finite administration |
| PULMONARY_AND_GI_UNRESOLVED | A0.8; 20, 22, 23 | Inhaled or intratracheal dosing with no independent evidence bounding the enteral contribution |
| ENDOGENOUS_REVIEW_REQUIRED | A0.8, A0.11, 21; 16–20, 22, 23 | origin ENDOGENOUS or MIXED and assay not EXOGENOUS_SPECIFIC |
| INTERIOR_BLQ | A0.5 | BLQ between quantified points |
| UNDEFINED (ratio) | A0.5 | Denominator zero or near zero |
| CMAX_ABOVE_ULOQ | A0.5; 17, 19, 22, 23 | Peak above ULOQ; Cmax is a lower bound |
| TERMINAL_SLOPE_NOT_ASSESSABLE | A0.7; 18, 19, 22, 23 | No qualified terminal window |
| DECLINE_STEEPENS / DECLINE_FLATTENS | A0.7; 19, 20, 23 | Split-half slope ratio ≥ 1.25 / ≤ 0.80 (description) |
| DESIGN_ZERO / WASHOUT_ZERO | 16, 21 | First documented dose without predose sample / washout ≥ 5 terminal t½ (assumption, 3.1 % may remain) |
| LATE_FIRST_SAMPLE | 16 | First sample ≥ observed Tmax/3 |
| LLOQ_LIMITED | 16 | DELAYED_ONSET only at lower doses; higher doses quantified at the same nominal time (±10 %) |
| ONSET_NOT_CONCAVE | 16 → 17 | Legacy code for “C/t increased beyond the specified bounds” between quantified early points before Tmax. Display the observation and formal status separately. |
| GROUP_MEAN, DESTRUCTIVE_SAMPLING, DIGITIZED | all | Record level and source |
| UNEQUAL_N_PER_TIME | 17 | Mean built from different n across time points |
| SPARSE_RISING_LIMB | 17 | Exactly three quantified rising points including the peak |
| KA_NOT_IDENTIFIABLE | 17 | < 2 quantified samples before the peak, Tmax at the first sample, or FLAT_TOP_WITHIN_TOLERANCE |
| FLAT_TOP_WITHIN_TOLERANCE | 17 (used in 23) | All samples up to the peak within twice the tolerance of the first |
| FIRST_INCREMENT_FROM_DESIGN_ZERO | 17 | First increment anchored on DESIGN_ZERO or WASHOUT_ZERO |
| PLATEAU_OR_PEAK_SHIFT | 17 → 19 | Plateau, or Tmax moving later with dose |
| DISPOSITION_CONFOUNDED | 17 | Post-peak shape would be needed to judge input order |
| UNKNOWN_PREDOSE, TIME_ORIGIN_UNCLEAR, UNOBSERVED_START | 16, 17 | Caveats; reasons for NOT_ASSESSABLE |
| T2_NUMERIC_CONTRADICTION, EXCLUSION_APPLIED | 20 | T2 evidence fields |
| SECOND_PEAK_CANDIDATE | 20 | Second maximum resting on one time point (with SINGLE_POINT_SUPPORT) |
| UPSTREAM_ISSUE | 20, 21, 23 | Evidence of a source, time or assay conflict; unexplained predose |
| WINDOW_SENSITIVE (+ grade_range) | 18 | Window-pair ratios cross a description cut-off |
| DOSE_MISMATCH | 18; A0.12 (22) | EV and IV doses differ (comparability check; links to T3) |
| UNEQUAL_TERMINAL_WINDOW | 18 | Terminal windows cover different time or concentration ranges |
| DISTRIBUTION_MASKED | 18 | IV multi-exponential, EV post-peak mono-exponential (candidate explanation) |
| MIXED_DOSE_TERMINAL | 18, 21 | Terminal phase contains earlier doses |
| WINDOW_TRUNCATION_RISK | 19 | Window coverage shares across doses cannot be estimated |
| NARROW_DOSE_RANGE | 19 | Highest/lowest dose < 3 |
| TMAX_WITHIN_SAMPLING_INTERVAL | 19 | Tmax difference not larger than the longer bracketing sampling interval |
| FIRST_PASS_POSSIBLE | 19 | PO or IP with AUC/D rising |
| BASELINE_CONFOUNDED | 19 | Endogenous signal in the AUC/D comparison |
| REPEATED_DOSE | 19 | Profiles from a repeated-dose occasion in the dose series |
| DIFFERENT_STUDIES, REPORTED_MODEL_AUC | 19 | Doses from different studies / AUC from a reported model |
| RESIDUAL_BASELINE | 21 (used in 17, 18, 22) | Predose > 5 % of Cmax; for 18 and 22, > 5 % of terminal-window concentrations or C(T) |
| BLQ_ABOVE_5PCT_CMAX | 21 | Predose BLQ with LLOQ > 5 % of Cmax |
| IV_EARLY_AREA_MISSING | 22 | IV bolus without C0; the t1·C(t1) compensation is a minimum |
| EV_EARLY_CHORD | 22 | EV area from the design-zero chord |
| EV_TRUNCATED / IV_TRUNCATED | 22, 23 | Tail share > 5 % |
| TAIL_NOT_ASSESSABLE | 22, 23 | No qualified terminal slope; no C(T)/AUC substitute |
| IV_OTHER_STUDY | 22 | IV from another study, strain or disease state |
| DOSE_BASIS_MISMATCH | 22, 23 | Dose basis different or unconfirmed |
| NONLINEAR_DOSE_MISMATCH | 22 | Descriptive project dose-range flag when T3 contradicts proportionality and Cmax differs at least twofold; the converse cannot establish shared clearance |
| LINEARITY_UNTESTED | 22 | EV and IV doses differ and linearity cannot be tested |
| F_ABOVE_ONE | 22 | Report any estimate above 1, with its measurement-specific uncertainty and possible causes |
| LOCAL_ROUTE | 23 | Intratracheal or inhaled |
| CONFOUNDED / OCCASION_CONFOUNDED | 23 | More than one differing attribute / different dosing occasions |
| ROUTE_UNKNOWN | A0.2, A0.8, A0.11 | Route of the PK data not stated; items 16–23 not run |
| REPORTED_PARAMETER | A0.12; 18, 19, 22 | EV dataset with source-reported parameters only |
| ELIMINATION_NONLINEARITY_POSSIBLE | 19 | Apparent half-life changing with dose; pending DME |
| DECREASING_EXTENT_OR_INCREASING_CLEARANCE | 19 | AUC/D falls with dose; not separable without IV |
| NOT_COMPARABLE | 23 | Drug, analyte, matrix, concentration basis or dose basis differ |
| TIME_DEPENDENCE_SUSPECTED | 23 | Later-dose AUCτ/D below first-dose AUCτ/D with the interval excluding equality |

---

## B. Changes to existing rules that these items need

1. **Allowed preparation (EDA004)**: add the rising-limb increment ΔC/Δt (item 17), a difference of observed values.
2. **Observed-window AUC (option B, decided 2026-11-04)**: allowed, one method only (linear up, log down; A0.6), no extrapolation. Required by items 19, 22 and 23.
3. **Descriptive regression allowlist**: the existing reference lists terminal-slope selection under deferred analysis. Allow exactly the regressions in A0.7: the terminal slope (items 18, 19, 22, 23), the split-half post-peak slopes (A0.7), the item 19 power-model slope b1, the item 19 T3 ratio and CI, and the T3p per-time ratios. All descriptive except the T3 and T3p statistical comparisons; none passed downstream as model parameters.
4. **Back-extrapolation** of the rising limb or of IV C0 stays forbidden.
5. **Data fields** to be proposed to the code thread:
   - route_detail values SC, IM, IP, PO, INTRATRACHEAL, INHALED_NOSE_ONLY, INHALED_WHOLE_BODY, INTRATHECAL, OTHER_EV ("IT" retired);
   - administration_start, administration_end (or duration), administration_rate, dose_basis, inhaled dose basis (NOMINAL / EMITTED / DEPOSITED / UNKNOWN);
   - iv_mode and infusion duration;
   - analyte_role, iv_reference_compound;
   - origin, baseline_behavior, assay_specificity;
   - data card fields (A0.11): mean_type, spread type, serial identity verified; route_detail value ROUTE_UNKNOWN.
6. **Data status labels**: absorption items read the record statuses assigned by data preparation rules 4 and 5 and EDA item 03; they do not re-classify records (A0.5).
7. **Hand-off record**: the candidate list format of A0.9 is shared with the distribution, metabolism and elimination sections, which back-fill "pending DME" entries.
8. **Front end**: entry species → study; inside a study the nine question rows are the main view, each with its conclusion sentence and primary evidence beside it; the data card sits above them; other views open from the rows by tier (A0.11).

---
