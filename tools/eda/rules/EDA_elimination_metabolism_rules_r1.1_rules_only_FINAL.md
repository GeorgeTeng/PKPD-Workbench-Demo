# EDA elimination and metabolism rules, items 29–36 | r1.1 final

**Final rule text.** This edition follows the Q1–Q7 decisions in the supplied r1.0 (source edition dated 2026-11-10, SHA-256 797bd8dc9ad3cecfe64761107c9b7eabb8f5f78b4a4e618f23860afd74e42909). The primary-source review covers the sixteen tutorial cases of Gabrielsson, Meibohm & Weiner and the authors’ discussion. Section C records the scope and changes.

Built from George's scientific review draft `EDA_elimination_metabolism_rules_r0.2_20261109.md` (SHA-256 `6052dede747a8eb0c42de614ad83e7536fd468422cacf29d67c4b4b49ee9b4aa`) in the layout of the absorption rules r4 (`EDA_absorption_rules_r4_rules_only_20261104.md`, SHA-256 `d620163e5a996af15c3201962163a3fcce5d4029945f618c37bde48fad9c4a28`) and the distribution rules r1.2 (`EDA_distribution_rules_r1.2_rules_only_20261109.md`, SHA-256 `872532b9bede3eae4c99cdde948ff7152f5ca17396c5065d3981bda640261b09`). The scientific content follows the review draft. r1.0 (George, 2026-11-10) is the version after the question-by-question walkthrough of Q1 to Q7; the decisions are in the text and are listed in section C. The module covers metabolism and excretion only. Whatever absorption or distribution already computes or draws is read from their records and is not repeated. The module is ordered by data layer: systemic parent plasma, when available, comes first; urine, recovery, excreta components and in vitro data follow when they were measured. Q4 is reserved. The new figures are EM-5a, EM-5c, EM-6a, EM-7a and EM-7b. The late-area share that an earlier draft held in item 29 is now in distribution item 24 (distribution rules r1.3). Section A gives the scientific rules. Section B lists what the code, the settings and the shared rules need. Project data and worked examples are kept out of section A; they belong in the test record.

The rule text applies EDA004. It starts with systemic parent plasma and adds unchanged drug in urine, total recovery, excreta components and in vitro evidence only when they were measured. A study may answer one part of a question while another part stays open. These are rules for reading data and handing an identifiable question to modeling. They do not fit a model and do not release a scientific conclusion.

Scope. Item 32 (plasma metabolites and total radioactivity) and test T11 are reserved and inactive. Outside this release: hepatic-flow extraction bounds, dedicated endogenous modeling, attribution of induction to a co-medication, attribution to target-mediated disposition, and classification of absorption from oral-only data. Upstream endogenous and target-binding gates are respected, and a question that belongs to another module is routed to it.

## A. Rule text

### E0 | SHARED DEFINITIONS FOR ITEMS 29–36

Items 29–36 use the absorption definitions A0.3–A0.6, A0.9 and A0.11 and the distribution definitions D0.2–D0.10 unchanged unless E0 states a difference. Each item states only what differs from E0.

#### E0.1 Order of execution

The module is ordered by data layer. Start with the systemic parent plasma series when available. Urine-only, recovery-only and in vitro studies enter at their first measured layer. A later layer is run only when its data were measured, and it never blocks an earlier one.

| Layer | Data needed | Items | Questions | Evidence |
|---|---|---|---|---|
| 1. Plasma | Systemic parent concentrations after a known dose; two or more doses or occasions for Q2 and Q3 | 29, 30, 31 (32 reserved) | Q1, Q2, Q3 | The existing concentration–time, dose and occasion panels of absorption and distribution, with the EM-1a value row. No new figure |
| 2. Urine | Unchanged parent in urine as amounts or concentration with volume; matched plasma for renal clearance | 33 | Q5 | EM-5a; EM-5c |
| 3. Recovery | Administered radiolabel or a defined parent-equivalent total in excreta, with or without carcass | 34 | Q6 | EM-6a |
| 4. Excreta components and in vitro | Component profiles in excreta; matched in vitro loss or kinetic assays | 35 | Q7 | EM-7a; EM-7b |
| Project level | The outputs of layers 1 to 4 for every species | 36 | Q7 | EM-8a columns of the project species table |

0. Data card (E0.11) and gates (E0.2). Resolve source identities and record which version of each upstream rule and result is used. Reuse eligible results from absorption items 18, 19, 21 and 23 and distribution items 24–28 by ID. An absent dependency blocks only the conclusion that needs it. Its test is not recreated from a plot.
1. Plasma layer, within study, group and occasion. Item 29 gives the window clearance from the plasma window (EM-1a value row). Items 30 and 31 read the upstream dose and occasion results. For an eligible uncovered plasma occasion contrast, item 31 requests T9 from its upstream owner. Both items use the existing panels.
2. Item 32 is reserved. A plasma metabolite or total-radioactivity series is inventoried and flagged for scope review. It is not interpreted indirectly under item 35.
3. Urine layer, item 33 (EM-5a, EM-5c). A urine-only study can answer how much parent was collected even when renal clearance cannot be calculated. Urine by dose and by occasion is passed back to items 30 and 31 as supporting evidence.
4. Recovery layer, item 34 (EM-6a), and the layer of excreta components and in vitro assays, item 35 (EM-7a, EM-7b). Each runs independently of the others.
5. Item 36 once at project level (EM-8a columns of the project species table).
6. Hand-off (E0.9) and status board (E0.11).

Execution follows these dependencies. Presentation follows the question order in E0.11. For each question the output gives the observed result, the strongest permitted interpretation, what remains unknown, and the most informative next measurement or comparison. An alternative explanation is always tied to a particular observation.

#### E0.2 Gates

Each gate lists what the relevant calculation needs and what follows when it is absent, incompatible or unresolved.

1. Dose and occasion.
   - Needed: actual dose and time; dose as parent-equivalent mass or amount of substance; route and mode; formulation; infusion start and end; regimen, prior doses and predose state. Per-kg quantities use the matched body weight or consistently normalized inputs.
   - If not met: no dose, F, baseline or infusion end is invented. Concentrations from a local site do not support systemic CL (LOCAL_ROUTE, D0.2). Unknown input timing blocks the shape tests (INFUSION_TIMING_UNKNOWN, D0.2).
2. Time origin and baseline: absorption item 21. An unresolved endogenous baseline (ENDOGENOUS_REVIEW_REQUIRED, A0.8) blocks every dose-attributed plasma result.
3. Signal.
   - Needed: study, subject or cohort, matrix, parent or component identity, total or unbound parent, assay, units, LLOQ, actual times and the location in the source. Parent, a named component, an unresolved component and total radioactivity (TR) are kept apart.
   - If not met: a sum of components is not an individual component. For a dosed mixture, use the dose of the assayed component; no component is allocated from an unspecified mixture. TR is neither unchanged parent nor metabolite-specific exposure (TR_NOT_PARENT).
   - Assay type. A specific assay measures the named analyte. A microbiological assay measures antimicrobial activity, that is the parent together with any active components or products. Its values are named "active material" (ACTIVE_MATERIAL_ASSAY). They are shown as a separate trace and are not a numerator for unchanged-parent recovery, fe, interval renal clearance or T10.
4. Collection.
   - Needed: animal or animals; route of collection; start and end; completeness and bladder emptying; gaps and overlaps; interval, cumulative or total basis; concentration and volume, or amount; denominator; cagewash allocation; bile cannulation; pooling; footnotes.
   - If not met: a missing value or "—" is not zero. No amount is formed from a concentration alone. No subtraction across mismatched animals, windows or cumulative bases. A disputed header or footnote stays a source conflict (SOURCE_CONFLICT) until resolved.
5. Handling.
   - Needed: matrix-specific stability over the actual residence, collection, processing and storage conditions; the stabilizer and when it was added, if used. Residence in the bladder or collection vessel is kept apart from stability after freezing.
   - If not met: documented instability under the relevant conditions flags the affected parent and product values (SAMPLE_STABILITY_RISK). An unreported method is unknown. It is not evidence of loss and not evidence of stability. If a plausible loss or formation could reverse the conclusion and is unbounded, the conclusion is withheld.
   - Loss to container surfaces. For a compound with sourced adsorption to container materials, a low-protein matrix (urine, bile, buffer, lavage or dialysis fluid) at low concentration can read too low (SAMPLE_ADSORPTION_RISK). Adsorption alone lowers the recovered amount. Evaluate other analytical errors separately. A lower limit on a collected amount stays a lower limit, "not detected" becomes weaker evidence of absence, and any conclusion that needs an upper limit on the amount is withheld unless the loss is bounded. A quantitative loss or correction requires evidence for the same analyte, matrix, material, concentrations and handling period. A related compound in culture medium can motivate a handling check.
6. Analysis unit and error: E0.4.
7. Supporting measurements: E0.8. Only the quantities needed for the result in hand are used. An unmatched literature GFR or fu,p is sensitivity context. No physiological default is applied silently. A missing kidney comparison does not suppress an observed recovery.
8. Upstream gates: the endogenous gate (absorption item 21), the D0.8 matrix and basis fields and `target_binding_declared` (D0.8) are respected. With NOT_STATED, target-mediated disposition is not read from the curves and is not listed as a candidate. LOCAL_ROUTE and INFUSION_TIMING_UNKNOWN keep their D0.2 definitions.

A gate failure gives the outcome stated in the item, with the reason. Every value carries a source pointer down to the table, row, figure or time series, together with any upstream restriction.

#### E0.3 Exclusion principle and evidence labels

A0.3 applies unchanged: the default, what is excluded (a complete named combination), the basis, robustness, data limits, the labels CANNOT_ASSESS, NOT_EXCLUDED and EXCLUDED_UNDER_STATED_ASSUMPTIONS, the flags SENSITIVITY_ONLY, BORDERLINE and SINGLE_POINT_SUPPORT, and the removal and widening checks. Elimination uses four kinds of output.

| Output kind | Meaning and display rule |
|---|---|
| Observed or descriptive | Name what was measured, in whom, on which basis and over which window. An approximation is shown as an approximation |
| Directional bound | Name the target, the direction, the window and the assumptions. `bound_kind` is JUSTIFIED_BOUND (supported bounds on the data), STATISTICAL_BOUND (one-sided coverage and method stated) or SENSITIVITY_ONLY (an explicit conditional calculation). When only a point proxy exists, show the proxy with its formula (WINDOW_PROXY). No unqualified ≤ or ≥ is printed for a population quantity |
| Formal test | CANNOT_ASSESS when premises or error coverage are missing. NOT_EXCLUDED only after an eligible test. EXCLUDED_UNDER_STATED_ASSUMPTIONS only for the named combination. State the witness, margin, robustness and error basis. A project band, a plot, or the lack of a contradiction is not a mechanism test |
| Data check | A conflict blocks the calculations that depend on it. Source values stay visible and independent results are preserved. T12 is a data check and cannot exclude a biological model |

Elimination adds the following.
- When no difference is detected, write "did not clearly differ over [range and window]", never "linear" or "absent".
- Formal exclusions in items 29–36 come only from T10 and from the reused tests T3, T3p, T7 and T9, each with its premises.
- When several intervals or windows are searched for an exclusion, the window is prespecified or the procedure has simultaneous coverage or a calibrated global error rate.

#### E0.4 Uncertainty used for allowed intervals

A0.4 applies unchanged. Elimination adds the following.
- Analysis unit. Record whether a value comes from an individual serial profile, destructive cohorts, a fixed group mean, a pool or a reported parameter, with the mean type (arithmetic or geometric), SD, SE or CI, and n. Analytical, digitization, sampling and collection uncertainties are recorded separately.
- SD = SE × √n only when n and the SE are both identified.
- An individual ratio, a ratio of means (RATIO_OF_MEANS) and a mean of ratios (MEAN_OF_RATIOS) are different quantities (D0.5). A mean curve is not evidence about each animal. A missing SD is not zero error.
- Ratio endpoints. For a positive ratio N/A the conservative endpoints are N_low/A_high and N_high/A_low. Either joint bounds are established or the statistical coverage of the combination is stated. If the relevant denominator can be zero, no finite upper bound follows. Pairing and shared inputs are preserved. Independent pointwise CIs are not a simultaneous band.
- Concentration error bars alone do not bound the curve between samples (E0.6).

#### E0.5 Data status outcomes

A0.5 applies unchanged. Elimination adds the following outcomes.

| Data status | Outcome in items 29–36 |
|---|---|
| Excreta value missing or printed as "—" | Not zero. The interval is missing; a known recovered amount in other intervals is kept |
| Excreta concentration without interval volume | No amount is formed. The concentration is displayed only |
| Interval concentration below the assay limit | For a representative, well-mixed collection with known volume, retain the censoring interval on the assay basis. Its nominal amount threshold is LLOQ × volume, with dilution and units reconciled. A bound on the original excreted amount also requires supported measurement error, recovery and stability in that direction. With missing volume retain the censored concentration. An unquantified interval supplies no upper limit on ultimate recovery |
| Predose value of zero before an IV bolus | Not a post-dose C₀. It is not used as the start of an area |
| Interior BLQ, unsupported endpoint or unexplained gap in plasma | Not bridged for a formal result |
| Cumulative means from cohorts that change between times | Interval amounts are not formed by differencing. A decline is not read as an individual decreasing series |
| Cumulative total and its increments both reported | Use one of them and reconcile the two. They are never added |
| Total radioactivity series | Kept on its own trace and basis. Not converted to unchanged parent |
| Printed values in conflict (header, footnote, subtotal, parameter against its inputs) | SOURCE_CONFLICT. All values are kept as reported and only the affected derivatives are quarantined |
| Route in which the analyte was detected with no amount reported | ROUTE_DETECTED_NOT_QUANTIFIED. The route is named. It enters neither a split nor a total |

#### E0.6 Observed-window AUC

A0.6 applies unchanged: linear-up/log-down from supported points; the actual first and last time, the grid and the censoring are recorded; no extrapolation to zero or to infinity. Elimination adds the following.
- A late first sample leaves a valid partial window. Write AUC(a,b), not AUC(0,b) (PARTIAL_WINDOW).
- A common-window contrast needs sampling support at both ends in every group and a comparable integration error.
- A true partial area and a numerical approximation are different. For a non-negative concentration, true AUC(a,b) ≤ true AUC(0,∞). A sampled trapezoid, written ÂUC(a,b), can overestimate even the full area on a sparse profile.
- A clearance upper bound therefore uses a justified positive lower limit L on the true area, or a stated one-sided statistical limit that includes integration error. Without one, D/ÂUC(a,b) is a window proxy (WINDOW_PROXY) and not a strict clearance ceiling.
- Under a stated assumption that the curve does not increase over the window, the lower concentration at the right end of each supported interval times the interval length gives a conservative area, conditional on that shape. The assumption is never imposed silently.

#### E0.7 Descriptive calculations allowed (complete list for items 29–36)

- Observed-window AUC(a,b) (E0.6); D/ÂUC(a,b) as a window proxy; D_high/L when L is justified; the conditional right-end area of E0.6 and D_high/L_cond (item 29).
- The last-chord tail inequality of item 29 and its truncated form in item 33. This is the only tail calculation allowed.
- Division of a plasma clearance limit by a supported lower limit of fu,p or of the blood/plasma concentration ratio (item 29).
- Reused from upstream by ID and not computed again here: the window AUC (A0.6), dose-normalized exposure with T3 and T3p (absorption item 19; DIS-2), chord slopes and T7 (item 24), and the occasion comparison with T9 (absorption item 23; D0.10).
- Sums of excreted amounts over collected intervals; r_U = Ae/D and Ae_low/D_high; the late increment share; interval rates ΔAe/Δt and interval-average plasma concentration ÂUC/Δt as table values; interval renal clearance with its limits; the filtration reference fu,p × GFR or GFR × AUCu; the nonrenal clearance limit U × (1 − L_f) (item 33).
- Route and total recoveries on their stated denominators (item 34).
- Component share as % of dose; identified, unidentified and unprofiled shares; sum checks (item 35).
- Comparison of reported in vitro readouts on one basis, and the check of a printed ratio against its printed inputs (item 35).
- Unit conversions, each with its basis.

Not computed in EDA: a fitted terminal slope or half-life, AUC to infinity, a fitted excretion asymptote, the amount-remaining-to-be-excreted (sigma-minus) plot (it needs the total amount excreted at infinite time, and an error or a missed interval is carried into every point), a formation or elimination rate constant of a product, IVIVE, allometry, model selection, a plasma metabolite/parent ratio, metabolite superposition, and a parent clearance derived from TR. A reported estimate stays reported.

#### E0.8 Excreta, in vitro and supporting-quantity fields

Excreta fields (on the data card, one per series)
- `excretum`: URINE, FAECES, BILE, CAGEWASH, EXPIRED_AIR, CARCASS, TISSUE_RESIDUE, OTHER.
- `analyte`: PARENT, NAMED_COMPONENT, UNRESOLVED_COMPONENT, TOTAL_RADIOACTIVITY, ACTIVE_MATERIAL.
- `assay`: SPECIFIC (method named), MICROBIOLOGICAL, RADIOACTIVITY, NOT_REPORTED; with LLOQ.
- `amount_basis`: INTERVAL, CUMULATIVE, TOTAL; `value_form`: AMOUNT, CONCENTRATION_AND_VOLUME, PERCENT_OF_DOSE, PERCENT_OF_EXCRETUM, PERCENT_OF_CHROMATOGRAM.
- `denominator`: administered dose, administered radioactivity, radioactivity recovered in the excretum, that day's dose.
- `interval_start`, `interval_end`, `gaps`, `overlaps`, `bladder_emptying`, `collection_complete`.
- `cagewash`: ALLOCATED (to which excretum), SEPARATE, NOT_REPORTED.
- `animals`: INTACT, BILE_CANNULATED; `pooling`; `pairing` with plasma (SAME_ANIMAL, PARALLEL_COHORT_SAME_STUDY, OTHER_STUDY, NOT_REPORTED).
- `label_position` and retained-radiolabel basis for a radiolabel study.
- `stability`: conditions documented for residence, processing and storage; stabilizer and timing; `sample_loss_to_container`: ADDRESSED, RISK_SOURCED, NOT_REPORTED.

In vitro fields
- System, species, tissue and dilution; substrate and starting concentration; incubation time and temperature; protein or cell normalization; cofactors; controls (no enzyme, inactivated, inhibitor); readout (parent remaining, half-life, Vmax, Km, Vmax/Km); units; source.

Supporting quantities
- fu,p matched to the study, with concentration range and method, taken from the item 27 record.
- The blood/plasma concentration ratio with its convention (blood over plasma), taken from the D0.8 record.
- GFR with species, method, kidney function of the study animals, and normalization. `gfr_ml_min_kg` is kept distinct from an absolute GFR and from a GFR indexed to body surface area. Values in different units are not compared directly; conversions state their basis (for example 1 mL/min/kg = 0.06 L/h/kg).
- Molecular weights of parent and product, and stoichiometry where a mass comparison between molecules needs it.
- Body weight.
- Each supporting quantity needs a source specific to the comparison it enters.

#### E0.9 Hand-off to modeling

A0.9 applies unchanged. The candidate list is shared across absorption, distribution, metabolism and elimination. Elimination adds the following.
- Status of the candidates that absorption and distribution marked "pending DME" (saturable elimination, nonlinear binding, time dependence, recycling). The elimination result is added to the candidate's status with the observation it rests on. The upstream evidence is not rewritten.
- Minimum result record, one per quantity: `item_id`, `question_id`, `analysis_unit`, `analyte`, `matrix`, `route`, `dose_basis`, `time_window`, `quantity`, `value_or_limits`, `units`, `estimate_or_bound`, `evidence_kind`, `answer_status`, `test_id_and_status`, `source_refs`, `caveats`, `missing`, `next_step`. Nulls are kept with their reasons. The direction of a limit (upper, lower, both, none) is encoded separately from the numeric value.
- Working hypothesis H of a study. Each hypothesis is linked to its observation, to one alternative that is still consistent with that observation, and to one next test. For a joint plasma/urine modeling question, hand over source IDs for the plasma observations, urinary interval amounts or cumulative series, input record and animal pairing. Note any shared observations behind derived CLR, fe and cumulative totals so modeling can account for their dependence. A source fact, an assumption and a proposed experiment stay distinguishable. The form is: "Plasma was sampled for only the first part of the urine collection. Matched plasma samples through the end of the collection would allow interval renal clearance to be estimated."
- Bounds are handed over as bounds with their direction, window, basis and bound kind. A window proxy is handed over as a proxy.

#### E0.10 Exclusion tests T10–T12

T10–T12 continue the distribution numbering. T10 compares interval renal clearance with the prediction from total plasma in clearance units, or urinary amount with the prediction from unbound plasma in amount units. T11 is reserved. T12 is a data check on recovery tables. Apply A0.3 to any numerical contradiction.

T10. Filtration alone
- Combination: unbound parent is freely filtered; no secretion, no reabsorption and no loss of parent within the kidney; negligible urinary delay; constant GFR over the interval and, for the total-plasma clearance comparison, constant fu,p; a measured CLR limit that is valid in the direction tested (item 33).
- Result: CLR,I = fu,p × GFR. With a supported directly measured unbound plasma area over I, compare unchanged urinary amount ΔAe(I) with GFR × AUCu(I), both in amount units. Apply the same directional comparisons below to amount limits on both sides. This branch needs GFR and uncertainty for AUCu(I) and the amount. Time-varying fu,p is already reflected in AUCu(I).
- Criterion: with measured limits [CLR_L, CLR_U] from item 33 and filtration limits [F_L, F_U] from the supported joint uncertainty of fu,p and GFR, read the table below.
- Requires: matched study physiology including kidney function; compatible units and body-size basis; matched time and collection; a supported joint error. A single fu,p × GFR requires stable binding and GFR over the interval. The direct unbound-area branch requires a supported constant GFR and matched unbound exposure. A literature range is sensitivity context. A measured urinary recovery percentage by itself cannot run T10.

| Comparison under the allowed uncertainty | Test result and reading |
|---|---|
| CLR_L > F_U | If the A0.3 gates pass, the filtration-only combination is excluded above its prediction. Additional net appearance of parent in urine is compatible with secretion. No transporter is identified |
| CLR_U < F_L | If the gates pass, the combination is excluded below its prediction. Less unchanged parent reached urine than predicted. Reabsorption, loss within the kidney, and collection or handling alternatives each need distinct evidence |
| Two-sided ranges overlap | Eligible test: NOT_EXCLUDED. Filtration alone is compatible. Counterbalancing processes can give the same result |
| A one-sided limit on the wrong side, unavailable GFR or exposure on the applicable total/unbound basis, unresolved loss, or uncertainty based only on a project band | CANNOT_ASSESS for that direction. A conditional comparison may be kept. No mechanism label |

- Analysis unit: same-animal urine and plasma pairs. Matched parallel cohorts in one study give a ratio of group quantities, not an individual CLR; a T10 result on it concerns that group ratio and needs the supported joint error. Unrelated studies do not qualify.
- Several intervals: state which were tested, the uncertainty and search procedure, and the leave-one-interval-out result.
- Not covered: a transporter, a site of reabsorption, the size of a secreted fraction.

T11. Reserved with item 32. Not run.

T12. Recovery data integrity (data check only)
- Applies to comparable cumulative measurements on one basis (item 34).
- Flags for reconciliation: a decline in a cumulative series, a negative amount, overlapping bins, recovery above the dose, or incompatible subtotals.
- The 100 % ceiling applies to a conserved, dose-attributable quantity. A later interval expressed as % of that day's dose can include carryover, so the ceiling is not applied to it automatically.
- Three levels are distinguished: a point discrepancy (including ordinary rounding), a discrepancy above a tolerance, and one that persists beyond the supported measurement uncertainty. A source tolerance is used when justified. A project tolerance is a review trigger. It is not measurement error and gives no permission to cap a value at 100 %.
- An individual anomaly is not erased by a valid mean. A decreasing individual series is not inferred from changing cohorts. Printed values are preserved and only the affected derivatives are quarantined.
- T12 cannot exclude a biological model.

Reused tests
- T3 and T3p (absorption A0.10) for dose-normalized exposure and matched-time contrasts in item 30, through DIS-2 and absorption item 19. The parent test's actual premises, power limits and result are retained.
- T7 (D0.10) as the premise of the optional conditional tail in items 29 and 33. Only an eligible result of NOT_EXCLUDED opens the tail.
- T9 (D0.10) and absorption item 23 for repeated dosing in item 31.

#### E0.11 Data card, figure set and answer status

Data card (one per dataset, before any figure)
- The A0.11 and D0.11 fields. Also the E0.8 excreta, in vitro and supporting-quantity fields, the analysis unit (E0.4) and the upstream results reused with their versions.
- A missing field is shown as "not reported" and becomes the "missing" entry of the questions that need it.

Figure set (EM-5a, EM-5c, EM-6a, EM-7a, EM-7b; the EM-1a value row; the EM-8a columns; EM-R)
- Every panel shown as evidence has the four-line caption of A0.11. A panel whose conditions are not met is not drawn empty and is never shown as a finding; one sentence gives the missing data. Tiers follow A0.11.
- Figures and reports use natural English. Codes, input references and excluded combinations stay in structured output.
- A downward arrow is used only for a supported upper limit and an upward arrow only for a supported lower limit. A window proxy, a conditional tail limit and a source estimate have distinct markers.
- Clearance limits of different groups are not drawn side by side on one axis: two upper limits cannot order the clearances (item 29), and a side-by-side plot invites that comparison. They are given as value rows with the kind written out.
- Reuse rule. A panel that absorption or distribution already drew for the same dataset, quantity and window is not drawn again. The elimination question row links to the existing panel, reads its values from the upstream result record by ID and version, and states its own conclusion sentence under it. The plotting call is not repeated. A value is not recomputed when the upstream record holds it for the same profile, window and method. A new EM panel is drawn only for a quantity that no upstream panel shows. For a missing or mismatched upstream panel, record the mismatch and show any eligible upstream result as a value row. New plots are limited to the five EM panels listed below.

| Figure | Panel | Tier | Drawn when | Items | Annotations on this panel | Source of the panel |
|---|---|---|---|---|---|---|
| EM-1 Plasma window and clearance | EM-1a value row: the window clearance D/ÂUC (CL or CL/F); optional sensitivity rows folded | 1 | item 29 eligible | 29 | Quantity name, value, units, actual window, kind written out (window proxy, justified upper limit, conditional upper limit with its assumption, conditional tail limit, source-reported); "/F" for EV; group-curve or individual | No plot. The row sits under the existing DIS-1a (IV) or B1 (EV), which already marks the first and last quantified points. The window AUC comes from the upstream record (A0.6) when profile, window and method match. Across species the values are columns of DIS-6b |
| EM-5 Urine | EM-5a cumulative unchanged parent at the observed collection ends | 1 | parent amounts in urine | 33 | Gaps marked; "0–t" or "sum over collected intervals"; TR and active material on separate traces; late increment share | New |
| | EM-5c interval CLR against the sourced filtration range | 2 | item 33 CLR eligible | 33 | One CLR value per interval with the coverage of urine and plasma, expected sampling effect and any supported limit; one-sided arrows for CLR_UPPER_ONLY and CLR_LOWER_ONLY; the filtration range with its source, drawn only when fu,p and GFR are sourced; "sensitivity context" when GFR is from the literature; T10 result and direction. No other band | New. fu,p comes from the item 27 record |
| EM-6 Recovery | EM-6a non-overlapping route-specific % of dose, with clearly labelled totals and time windows | 1 | a recovery design | 34 | Conserved quantity and denominator; intact or cannulated; T12 findings | New. Kept apart from DIS-4d, which shows tissue amounts at one time on another basis; the two are never stacked |
| EM-7 Components and in vitro | EM-7a measured component shares by excretum | 1 | component profile | 35 | Reported basis and denominator; unassigned peaks; unprofiled fraction; sum check | New |
| | EM-7b comparable in vitro readouts | 1 | at least two comparable rows in one matched system; otherwise a table row | 35 | System, units, controls; rows left out of a ranking with the reason | New |
| EM-8 Species and conditions | EM-8a elimination columns of the project species table | 1 | project level | 36 | One column per quantity; missing cells visible; comparability of each contrast | No separate table. The columns are added to the project species table DIS-6b |
| EM-R Reported parameters | one panel per reported value | 1 when a dataset has parameters only; otherwise 3 | E0.12 | 29, 33, 34 | Definition, units, method, window, source. Never substituted silently for EM-1 or EM-5 | Same panel form as F and DIS-R. A value already shown there (CL/F, t½ and AUC in F; volumes in DIS-R) is not shown again |

Plasma questions answered from existing panels (no EM panel is drawn)

| Question | Existing panel used | What elimination adds |
|---|---|---|
| Q2, dose | EV: C2 with the T3 CI, and C3. IV: DIS-2a and DIS-2b with the T3 and T3p results | The reading table of item 30: which candidates remain and which measurement separates them; urine by dose from EM-5a |
| Q3, repeated dosing | EV: E1 and E2 with the item 23 occasion result. Plasma in a tissue repeat-dose study: the reference accumulation ratio of DIS-4c with T9 | Item 31: the measured change kept apart from its cause; urine by occasion from EM-5a |

- Panel IDs of the review draft that are no longer used: EM-1b (moved to distribution item 24), EM-2a, EM-2b, EM-3a, EM-3b, EM-4, EM-5b, EM-6b, EM-7c. The IDs are not reused. Reasons are in section C.

- Without plasma, EM-5a is still drawn for recovery.
- Individual layer: as A0.11.

Reading map: what each panel is for. "Look at" is what the reviewer checks on the panel; "reading" is the descriptive or test result; "hypothesis handed over" is what goes to E0.9. Readings without a test stay descriptions (E0.3). For a reused panel, the row is applied to the existing panel named in the figure table.

| Panel | Look at | Reading | Hypothesis handed over |
|---|---|---|---|
| EM-1a (value row) | The window clearance, its window and analysis unit; for a folded sensitivity row, which kind it is | "D/ÂUC(a,b) = X (window clearance, no extrapolated tail)"; in a sensitivity row "CL (or CL/F) ≤ X on the stated basis" | A window-specific starting value. Missing exposure tends to raise the ratio if the numerical area is accurate. Check quadrature and definitions when a source-reported clearance lies above it |
| C2, C3 (EV); DIS-2a, DIS-2b (IV), reused for Q2 | Does common-window AUC/D stay level, rise or fall with dose | "Did not clearly differ over [range, window]", or direction and size with the T3/T3p result | No departure seen in this range; or proportional disposition under the tested input is challenged, with saturable elimination as one candidate when AUC/D rises, beside timing, distribution, concentration-dependent binding and analytical issues |
| E1, E2 (EV); DIS-4c reference ratio, reused for Q3 | First against later occasion at matched times since dose, on the same window and dose; whether a decrease is robust | Rise, no clear change or decrease; T9 and item 23 result | A rise is compatible with ordinary accumulation. A robust decrease challenges the linear, time-invariant, identical-input combination; increased clearance and reduced input or F are both to be tested |
| EM-5a | Cumulative unchanged parent at each collection end, by dose and occasion where measured; gaps; the last increment | r_U with its lower limit; "small last increment" when configured | Report observed recovery on its source basis. Use “at least” for a supported lower limit. A conclusion about a minor route requires an upper limit on ultimate recovery |
| EM-5c | The CLR value of each interval and the coverage of urine and plasma; once the filtration range is sourced, the CLR limits against it and the direction each limit can test | Interval estimate or labelled partial-window proxy; T10: excluded above, excluded below, not excluded, cannot assess | Net appearance beyond filtration (compatible with secretion); less parent in urine than filtration predicts (reabsorption, loss within the kidney, collection or handling); filtration alone compatible |
| EM-6a | Route amounts and the three totals on their denominators; T12 findings | Recovery by route and total, as numbers; no completeness class | Routes by which drug-related material left; what the unaccounted part could reflect, without apportioning it |
| EM-7a | Largest measured component in each excretum and window; unassigned and unprofiled parts | Component share of dose; identified share | A product was observed. Its origin (enzymatic, chemical in vivo, after collection) stays open until controls and stability separate them |
| EM-7b | Ranking within matched systems only; controls | More or less loss on one assay basis | A species or system difference in loss on that basis. Not a pathway and not a scaled clearance |
| EM-8a | Which cells are filled and which contrasts are comparable | comparable / descriptive_only / incompatible, each with the reason | Per species: one observation, its principal unresolved alternative and one feasible discriminator |
| EM-R | Definition and method of the reported value | Reported value on its own basis | Source context; at most a partial answer |

Page structure and answer status
- Entry: species → study → question → H, as A0.11. The question is the unit of output. Questions follow the data layers of E0.1, plasma first.
- The plasma questions Q2 and Q3 read the results of absorption and distribution and add the elimination reading; they repeat no figure and no test.
- Each row shows the status, one conclusion sentence, the single most explanatory evidence, and what is missing.
- Required rows in the study view: Q1, Q2, Q5 and Q7. Q3 is shown for repeated dosing and Q6 for a recovery design, even when the expected evidence is missing. Q4 is reserved with item 32 and has no row. Q7 shows the study's contribution and links to item 36 at project level. A required row without evidence shows a missing-data sentence.

| Q | Layer | Question | Items | Primary evidence (default) | Other panels |
|---|---|---|---|---|---|
| 1 | Plasma | What does the plasma window tell us about clearance? | 29 | DIS-1a (IV) or B1 (EV) with the EM-1a value row | EM-R |
| 2 | Plasma | Does exposure scale with dose? | 30 | The upstream panel: C2 (EV) or DIS-2b (IV), with the T3/T3p result when eligible | C3, DIS-2a, DIS-5a; EM-5a by dose |
| 3 | Plasma | What changes on repeat dosing? | 31 | The upstream panel: E1 with E2 (EV) or the DIS-4c reference ratio, with the T9 or item 23 result | EM-5a by occasion |
| 5 | Urine | How much parent is in urine, and is CLR consistent with filtration? | 33 | EM-5a | EM-5c with the T10 result |
| 6 | Recovery | Where did the dose go? | 34 | EM-6a | — |
| 7 | Components, in vitro, species | What products, systems and species can be compared? | 35, 36 | EM-7a and EM-7b in the study; DIS-6b with the EM-8a columns at project level | In vivo comparison table |

- Each subquestion is ANSWERABLE, PARTLY_ANSWERABLE, NOT_ANSWERABLE_YET or NOT_APPLICABLE (A0.11). ANSWERABLE is relative to the question actually asked, for example the recovery observed by the last collection end. It does not mean that a mechanism is established.
- A compound question shows its component results and is PARTLY_ANSWERABLE when only some parts can be answered.
- A single-dose design makes Q3 NOT_APPLICABLE. One dose does not test proportionality (Q2). Absent urine makes urinary recovery unknown (Q5 NOT_ANSWERABLE_YET). EV-only plasma cannot fully answer Q1.
- Q2 and Q3 take their test status from the upstream record. Elimination does not upgrade it.
- Report-only, conditional or exploratory evidence is at most PARTLY_ANSWERABLE for a mechanistic question.

#### E0.12 Reported-parameter path

- Applies when a source reports CL, CL/F, CLR, fe, urinary or total recovery, a half-life or an in vitro constant without a usable curve or table of amounts. Label REPORTED_PARAMETER.
- Per value: the original definition, value, units, method, matrix, window, route, n and uncertainty are kept as reported.
- A reported number is not turned into a reconstructed observation or into a successful test. It is shown in EM-R and is never substituted silently for EM-1 or EM-5.
- A parameter-only answer to a module question is at most PARTLY_ANSWERABLE.

---

### 29 | PLASMA: OBSERVED-WINDOW EXPOSURE AND THE WINDOW CLEARANCE

Scope
- One systemic parent profile after an isolated, known dose with no prior contribution, at least 3 quantified post-dose points, a positive supported area, and dose and matrix units that match.
- For an infusion, the dose is the amount actually delivered. The area within the infusion can contribute to the window. Points within the infusion cannot define a post-input chord.
- The item reports what the sampled window says about clearance. It does not estimate a terminal slope, a half-life or AUC to infinity.

Principle
- Target. After a single IV dose the target is D/AUC(0,∞). After a systemic EV dose it is D/AUC(0,∞), conventionally called CL/F under the usual constant-CL/F interpretation. If disposition is nonlinear or time-varying, the quantity is a dose-specific dose/exposure ratio and a single constant physiological CL is not identified.
- Partial area. For a non-negative concentration, true AUC(a,b) ≤ true AUC(0,∞). A justified positive lower limit L on the true area therefore gives target ≤ D_high/L. A sampled trapezoid is not such a limit by itself (E0.6).
- Tail. For a central parent after completed central IV input and zero initial state, a positive exponential sum has a convex ln C (T7). If ln C stays convex after the last sample, the last chord extended forward lies below the curve, so the area after the last sample is at least C_last/(−s), with s the strictly negative slope of the last log-chord.
- Group mean. For equal doses, D divided by the area of a group-mean curve targets a group-curve ratio. It is not the arithmetic mean of the individual clearances.

Data and details
- Dose amount, basis and units; route and mode; infusion start and end; times after dose; concentrations with data status, LLOQ and allowed intervals; record level, n, SD and mean type; predose value and dosing history.
- The T7 result for the profile (item 24), with its version.
- fu,p or the blood/plasma concentration ratio with source and concentration range, when an unbound or blood clearance limit is wanted.
- Source-reported CL to infinity (E0.12), displayed separately.

Figures (E0.11)
- No new figure. The EM-1a value row sits under the existing DIS-1a or B1. Source-reported values in EM-R.

Assessment
1. Set the target before dividing (Principle). An arbitrary later dosing interval is never used as a single-dose area.
2. Window clearance, the one value shown by default. CL_window = D/ÂUC(a,b), or CL/F after EV dosing. The EV display is labelled a window proxy for CL/F. ÂUC(a,b) is the observed-window AUC that absorption and distribution already compute under A0.6; when the upstream record holds none for this profile, the same A0.6 routine is applied. Report the value with its window, units and analysis unit. Because the area before a and after b is left out, this value lies on the high side of D/AUC(0,∞) when the trapezoid is accurate. Record WINDOW_PROXY. If integration error is unknown, the net direction for this profile is unknown (E0.6).
3. What cannot be ordered. Two window values, two upper limits or two different terminal slopes cannot order the true clearances. A matched AUC/D difference is evidence about exposure in that window. When terminal slopes are similar across conditions, read them with the common-window exposure and the item 24 late-area share, if available. Similar terminal slopes can accompany very different exposures.
4. Optional sensitivity rows, folded by default. They are shown only on request and never replace the window value.
   - Justified limit. If a lower area limit L is justified and positive: target ≤ D_high/L on the stated basis, with `bound_kind` JUSTIFIED_BOUND or STATISTICAL_BOUND.
   - Conditional area limit. For IV data after the input has ended, under the stated assumption that the concentration does not rise over the window, L_cond = Σ C_low(right end) × interval length over the supported intervals, and target ≤ D_high/L_cond. Labelled SENSITIVITY_ONLY (CONDITIONAL_AREA) with the assumption printed. Not formed for EV profiles, for points within an infusion, or when a later point lies above an earlier one beyond their allowed intervals.
   - Conditional tail. All of the following are required: an eligible upstream T7 result of NOT_EXCLUDED; the stated positive exponential sum for a central parent after completed central IV input and zero initial state; a last positive quantified pair with a strictly negative, supported log-chord s.
   - Omit the tail when T7 is missing, uninformative or blocked; when input is ongoing or EV; when a rebound is inconsistent with the premise; or when the sign of the slope is unresolved.
   - Tail area ≥ C_last/(−s). Use the lowest admissible C_last and the most negative admissible s, or their joint extrema, together with the supported area lower limit L: target ≤ D_high/[L + tail_low].
   - Label SENSITIVITY_ONLY (CONDITIONAL_TAIL). This is not an estimated tail and not evidence that the model is correct.
5. Source check. Show a source-reported full-exposure CL or CL/F separately. For a comparable dose, analyte, matrix, animals and summary method, flag a reported value above the proxy for reconciliation (REPORTED_CL_ABOVE_WINDOW). Check integration grid and method, coverage near the peak, exposure outside the sampled window, dose units and individual versus group summaries. The sign relative to a numerical proxy is a review trigger. A discrepancy with a justified ceiling can be assessed separately with joint uncertainty.
6. Unbound or blood clearance. Divide a plasma clearance limit of step 4 only by a positive, supported lower limit of a constant fu,p (unbound) or of the blood/plasma concentration ratio (blood) over the relevant exposure. Constancy documented only inside the sampled window supports, at most, a stated conditional conversion. A separately justified lower area of the converted signal can be used directly instead. The EV "/F" qualifier is kept. The window value divided in the same way stays a window value.

Output per profile
`dose_exposure_target`, `auc_window`, `auc_method`, `auc_source` (upstream record ID or computed here), `window_proxy` (the window clearance), `cl_upper_window`, `cl_upper_tail`, `bound_kind` (JUSTIFIED_BOUND / STATISTICAL_BOUND / SENSITIVITY_ONLY / none), `cl_u_upper`, `cl_blood_upper`, `cl_upper_conditional_area`, `reported_cl_check`, `caveats` (WINDOW_PROXY, PARTIAL_WINDOW, CONDITIONAL_AREA, CONDITIONAL_TAIL, REPORTED_CL_ABOVE_WINDOW, DOSE_SPECIFIC_RATIO, GROUP_CURVE_RATIO, EV_OVER_F, INFUSION_TIMING_UNKNOWN, GROUP_MEAN, DESTRUCTIVE_SAMPLING, DIGITIZED), `not_assessable_reason`. An omitted bound is null with a reason.

Hand-off
- "Over [a,b], dose divided by the sampled plasma area is X [units]." When the integration error is unknown, state that the direction relative to full-exposure clearance is unresolved. A defensible direction is reported with its premise or bound.
- With a sensitivity row: the limit, its kind and its premise.
- EDA does not estimate the tail.

Purpose, limits, and main-objective link
Gives modeling one dose/exposure ratio per profile on the sampled window, and the conditions that support a directional clearance limit.

Keywords: clearance; dose/exposure ratio; partial area; window proxy; upper bound; log-convex tail; group-mean curve; unbound clearance; blood clearance.
MP basis: EDA004; figure list B1.
Sources: Gabrielsson, Meibohm & Weiner 2016, [AAPS J 18:47–63](https://doi.org/10.1208/s12248-015-9817-6), cases 1 and 2 (read; the cases motivate the panel and the alternatives, and a curve resemblance does not transfer a case's fitted mechanism to another drug). Clearance definitions as in Rowland & Tozer, Clinical Pharmacokinetics and Pharmacodynamics, 4th ed., and Gibaldi & Perrier, Pharmacokinetics, 2nd ed. (standard definitions). The partial-area inequality and the convex-tail inequality are derived (log-sum-exp convexity as in D0.10 T7).

---

### 30 | PLASMA: DOSE DEPENDENCE, READ FROM UPSTREAM RESULTS

Scope
- Two or more comparable doses within one route, occasion, analyte, matrix and design. With one dose, dose dependence cannot be assessed (SINGLE_DOSE_ONLY).
- Item 30 computes nothing and draws nothing of its own. The dose-normalized profiles, the common-window AUC/D and the T3 and T3p tests are those of absorption item 19 (EV: C1 to C3) and distribution item 24 (IV: DIS-2a, DIS-2b). Item 30 adds the elimination reading: which candidates remain and which measurement separates them.

Principle
- Under dose-proportional disposition and input, dose-normalized profiles superimpose and common-window AUC/D does not change with dose. A supported departure challenges that combination under the tested input. It does not name the process that departs.

Data and details
- From the upstream record, by ID and version: dose range, concentration range, common window, direction of the departure, the T3 and T3p results with their actual premises and power limits, and the T7 result.
- Paired total and unbound profiles or binding over the actual concentration range (item 27); input and formulation records; unchanged urinary recovery by dose (item 33) when measured.

Figures (E0.11)
- No new figure. EV: the existing C2 and C3. IV: the existing DIS-2a and DIS-2b. Link to DIS-5a.

Assessment
1. Take the dose range, the concentration range, the common window and the test results from the upstream record. The parent test's premises, power limits and result are retained as they are.
2. Record the dose allocation (same subjects across doses, replicated comparable parallel groups, or a different unreplicated subject/condition at each dose). For the last design, label the dose contrast CONFOUNDED and describe the profiles by subject and dose. A within-profile shape result retains its own eligibility. In crossover data check period, carryover and formulation. Read the eligible evidence with the table below.

| Evidence | Permitted reading | What would distinguish the candidates |
|---|---|---|
| One dose, with or without T7 | Dose dependence cannot be assessed. A robust T7 contradiction concerns the shape combination at that dose only | A second matched dose; verify timing, matrix and concentration basis |
| Comparable doses, no supported departure | "Dose-normalized exposure did not clearly differ over [range and window]." If uncertainty is missing, describe the points only | A wider dose range or better precision, if the distinction matters |
| IV AUC/D rises or falls, or profiles separate at matched times | Name the direction, size, window and T3/T3p result. A supported departure challenges proportional disposition under the tested input. Saturable elimination is one candidate when normalized exposure rises. Timing, distribution, concentration-dependent binding and analytical issues can also produce a departure | Paired total and unbound profiles or binding over the actual range; input records; unchanged urinary recovery |
| EV AUC/D or peak time changes | Report the observations together. A change in F, in absorption rate, in disposition, or a combination can explain them. A late peak with a higher AUC/D does not identify saturated elimination | Matched IV doses and the formulation and input record |

3. For a completed IV infusion, mark the actual end of input and read the early and later post-infusion chords separately on DIS-1b. Record whether log concentration flattens or steepens as concentration falls, with the corresponding times and concentration ranges. Early distribution and later concentration-dependent elimination can coexist. A late straight segment at low concentrations is compatible with a capacity-limited pathway behaving approximately linearly there. Use existing chords and T7 for their stated tests. If the only informative range is low relative to an independently sourced, comparable Km, Michaelis–Menten elimination behaves approximately as (Vmax/Km) × C. H can request matched doses or samples spanning the suspected change in slope to help distinguish capacity from affinity. Record where the data lie on the measured concentration scale when no comparable Km exists. A change of the late decline with dose (the apparent half-life panel of C2, the chord slopes of DIS-1b) is a window description. Convergence at low concentrations, a late separation, or a longer apparent half-life cannot by themselves select a mechanism.
4. Binding alternative. It is not closed merely because some unbound samples exist. Ask whether the same departure persists in comparable unbound profiles, or whether fu,p is stable across the relevant concentrations.
5. Excretion evidence by dose, as candidates only. It needs unchanged parent in urine over the same collection interval at two or more doses (item 33); two lower recovery bounds from different intervals are not ordered.
   - For a renal trend, require comparable, supported CLR estimates on matched plasma/urine intervals. Opposite directions for the two true values can be compatible with ordered one-sided bounds. Check fu,p over the actual range, kidney function and urine collection across doses before interpreting the trend.
   - Interval CLR falls as supported interval-average plasma concentration rises: saturable renal secretion is a candidate.
   - Interval CLR rises as supported interval-average plasma concentration rises: saturable tubular reabsorption is a candidate.
   - If recovered parent per administered dose rises while supported interval CLR is similar, inspect same-window plasma AUC/D. Under constant CLR, r_U(I) = CLR × AUCp(I)/D, so the two observations share the same exposure information. Assess altered time course, EV input/F and sampling coverage before proposing saturation of a competing pathway.
   - None of these names a transporter, an enzyme or a site. Each is listed with its observation and the alternative still consistent with it (E0.9).

Output per dose set
`dose_range`, `concentration_range`, `common_window`, `exposure_direction`, `t3_ref`, `t3p_ref`, `t7_ref`, `alternatives`, `next_discriminator`, `caveats` (SINGLE_DOSE_ONLY, EV_INPUT_CONFOUNDED, NO_UNCERTAINTY, CONFOUNDED, GROUP_MEAN, DIGITIZED), `not_assessable_reason`.

Hand-off
- The status of the "pending DME" candidates saturable elimination and nonlinear binding is updated with the observation, its window and the test it rests on.
- "No supported departure" is handed over with the dose and concentration range it covers. It is not handed over as linear elimination.
- A direction seen in the urine evidence (step 5) is handed over as a candidate with the matched intervals it rests on.

Purpose, limits, and main-objective link
Closes the dose-dependence candidates that absorption and distribution left "pending DME": it states which alternatives remain when exposure does not scale with dose, and which measurement separates them. It repeats no upstream figure or test, does not select a mechanism and does not estimate Vmax or Km.

Keywords: dose proportionality; superposition; saturable elimination; concentration-dependent binding; EV input; reuse of upstream results.
MP basis: EDA004; figure list B2, B3.
Sources: Gabrielsson et al. 2016, Fig. 6 cases 7–8 and Fig. 7 cases 9–10, Eqs. 14, 16, 18 and 36; absorption item 19 and its sources; distribution item 24 (DIS-2).

---

### 31 | REPEATED DOSING: DEPARTURE FROM SIMPLE ACCUMULATION, READ FROM UPSTREAM RESULTS

Scope
- Known dose history, the same regimen, matched times since dose, and comparable input, formulation, matrices and animals or cohorts.
- A changed regimen, co-medication, a different sampling phase or uncertain dose timing: the occasions are described separately and auto-induction is not tested (REGIMEN_CHANGED). Attribution to a co-administered drug is out of scope.
- Item 31 draws nothing of its own. The plasma occasion contrast is that of absorption item 23 (EV: E1, E2) and of T9 (D0.10; the reference accumulation ratio of DIS-4c). Item 31 adds the reading and the rule for urine by occasion.

Principle
- With linear, time-invariant disposition, zero initial state and an identical non-negative input at each dose, a later profile is the first-dose profile plus the residual of earlier doses. Matched later concentrations and same-window AUC cannot be below the first occasion (T9, absorption item 23).
- A rising trough or AUC after initiation is compatible with ordinary accumulation. Five apparent half-lives do not demonstrate steady state.

Data and details
- From the upstream record, by ID and version: dose times, interval and number of doses; matched times since dose, predose or post-dose; first and later AUC over the same supported interval and dose; the T9 and absorption item 23 results.
- An independent, supported accumulation prediction with provenance and uncertainty, when one exists.
- Occasion-specific urine amounts per administered interval dose (item 33).

Figures (E0.11)
- No new figure. EV: the existing E1 and E2. Plasma in a tissue repeat-dose study: the existing DIS-4c. Urine by occasion: EM-5a.

Assessment
1. Separate the measured change from its cause. Check the Scope conditions first.
2. Take the matched contrast and the T9 or item 23 result from the upstream record. For matched plasma occasions that upstream did not cover, use the upstream T9 procedure once under its D0.10 premises, store its result with the source version and report the result as a value row under the existing concentration–time panels.
3. Two occasions allow a paired or group contrast, not a drift trajectory (TWO_OCCASIONS_ONLY). With three or more occasions the matched values are listed by occasion in the evidence table.
4. First and later AUC are compared over the same supported interval and dose. AUCτ is used only for a full interval.
5. A robust decrease challenges the combination in Principle. It does not challenge clearance specifically. State which test and which observation support it.
6. A rise alone is not the reverse exclusion. A rise is compared with an accumulation prediction only when an independent, supported prediction is available. For a sustained exposure above that prediction, retain reduced elimination (including inhibition) and altered binding or distribution as alternatives alongside any supported input change. For a documented pre-, during- and post-treatment sequence, link troughs at the same time after dosing to the period dates and describe any return toward earlier values. A changed co-medication remains a descriptive contrast.
7. Urine by occasion. The collected amount per administered interval dose can be compared between occasions. With carryover, the recovered material is not all attributed to that dose (CARRYOVER_POSSIBLE). Without plasma, the urine contrast is reported under items 33 and 35 and the clearance question stays open.

Output per regimen
`occasions`, `matched_times`, `interval_basis`, `direction`, `t9_ref`, `abs23_ref`, `accumulation_context`, `alternatives`, `caveats` (TWO_OCCASIONS_ONLY, REGIMEN_CHANGED, CARRYOVER_POSSIBLE, TIME_DEPENDENCE_SUSPECTED, OCCASION_CONFOUNDED, GROUP_MEAN, DESTRUCTIVE_SAMPLING), `not_assessable_reason`.

Hand-off
- A reduced exposure can motivate testing increased clearance, or reduced input or F. It does not prove induction.
- The status of the "pending DME" candidate time dependence (absorption item 23, distribution T9) is updated with the observation and test.

Purpose, limits, and main-objective link
Closes the time-dependence candidate that absorption and distribution left "pending DME", and keeps the measured change apart from its cause. It repeats no upstream figure, does not test steady state and does not attribute a change to induction or to a co-medication.

Keywords: repeated dosing; accumulation; superposition; time dependence; auto-induction; carryover; reuse of upstream results.
MP basis: EDA004; figure list B1.
Sources: Gabrielsson et al. 2016, Fig. 8 case 14 and Eq. 28 (periods, exposure changes and alternatives in the repeated-dose discussion); absorption item 23; distribution D0.10 T9.

---

### 32 | PLASMA METABOLITES AND TOTAL RADIOACTIVITY (RESERVED)

Scope
- Item 32 and T11 are inactive in this release. No panel and no question row is defined.

Assessment
1. If a source contains a plasma metabolite or TR series, inventory its analyte, matrix, method, units and source, and flag it for scope review (SCOPE_REVIEW).
2. No plasma metabolite/parent ratio, no metabolite superposition and no TR-derived parent CL is computed.
3. A future policy revision activates the item. The presence of one series does not.

Output
`inventory_rows`, `caveats` (SCOPE_REVIEW).

MP basis: EDA004.

---

### 33 | URINE: UNCHANGED DRUG, INTERVAL RENAL CLEARANCE AND FILTRATION

Scope
- Unchanged parent measured in urine, as amounts or as concentration with the actual interval volume. A urine-only study is in scope for the recovered amount.
- Interval renal clearance and T10 also need matched plasma.

Principle
- Fraction. For a single dose, r_U = Ae_parent,collected/D_admin. After IV, the target is the systemic unchanged urinary fraction fe for that dose. After EV, r_U is a fraction of the administered dose; in conventional linear PK the ultimate recovery over D equals F × fe.
- Collection is one-sided. A collected amount bounds ultimate recovery from below. It gives no upper limit on future excretion.
- Interval renal clearance. For an interval I = [u,v], CLR,I = ΔAe(I)/AUCp(I), from intact parent in urine and total parent in plasma. It measures clearance to unchanged urine over I. For a non-constant CLR it is an exposure-weighted interval summary. F is not needed for a properly matched interval CLR after EV dosing.
- Filtration. The intact parent expected to enter urine by filtration alone is the filtered load, fu,p × GFR × AUCp(I) (T10).
- Additivity. For a matched single-dose IV parent with an appropriate additive clearance interpretation, CLnr = CL × (1 − fe).

Data and details
- The E0.8 excreta fields; dose on a compatible basis; assay (E0.2, gate 3); stability and container handling (gate 5).
- Plasma over the collection intervals, from the same animals where available; pairing recorded.
- fu,p, GFR and their sources (E0.8) for T10.
- The item 29 outputs for the nonrenal limit, on the same target and analysis unit.

Figures (E0.11)
- EM-5a; EM-5c when CLR is eligible.

Assessment

Numerator (EM-5a)
1. Confirm unchanged parent, a compatible administered-dose basis, valid amounts or concentration × actual interval volume, and non-overlapping bins. A value from a microbiological assay is active material and does not enter this numerator (E0.2).
2. A source-reported % of dose may be shown without an absolute dose. It cannot supply an amount for CLR unless the dose and units are known.
3. Use either the reported cumulative total or its constituent increments. Reconcile the two when both exist; never add both. Unassigned cagewash is kept separate (CAGEWASH_UNASSIGNED).
4. A continuous series may be labelled "0–t". With gaps, label "sum over collected intervals" and list them (COLLECTION_GAP). Missing intervals do not erase a known recovered amount. Interval amounts are not inferred by differencing cumulative means from changing cohorts.
5. A missing collection elsewhere allows a rate calculation for an independently complete interval with known voiding at both boundaries. CLR also requires matching plasma support. A missed boundary void can affect the next bin, so check its allocation.

Name the fraction
6. Report the observed percentage r_U, the last collection time, the recovery uncertainty and the collection conditions. A justified Ae_low/D_high bounds the ultimate unchanged urinary recovery, as a fraction of the administered dose, from below.
7. After EV dosing, systemic fe and CLnr stay unresolved without an independently supported F and a compatible comparison (ADMIN_DOSE_FRACTION). After repeated doses, the occasion rule of item 31 applies.
8. Late increment. With at least 2 contiguous intervals, a positive cumulative amount, a last interval at least as long as the previous one, and an explicitly configured `late_increment_share`, compare the last increment over the cumulative amount with that cut-off. Print the actual amount, duration and fraction. A single bin, a gap or an unresolved BLQ gives no flattening decision. A small increment is descriptive (LATE_INCREMENT_SMALL). Even a small increment, a visually flat curve, or 24 h of collection supplies no upper limit on future excretion.
9. Wording.
   - A credible lower limit of at least 50 % supports "at least half the administered dose was recovered unchanged in urine". Above 50 % supports "a majority".
   - A low lower bound cannot establish a minor renal route, and cannot establish that at least (1 − r_U) was eliminated nonrenally. A "minor" statement requires a credible upper limit on ultimate unchanged urinary recovery, for example an independent, compatible mass balance that limits the unaccounted dose.
   - High kidney/plasma concentrations (item 26) warrant investigating tissue uptake or retention. They do not establish tubular reabsorption.

Interval renal clearance (EM-5c)
10. Requirements: known bladder emptying and collection alignment, and no unbounded transit or loss affecting the direction being tested. Same-animal pairs are preferred. Matched parallel cohorts in one study give a ratio of group quantities (RATIO_OF_MEANS), not an individual CLR. No primary calculation is made from unrelated studies. Units are stated, for example mL/min/kg.
11. For complete matched I, report ΔAe(I)/ÂUCp(I) as the interval estimate. For complete urine and partial plasma J inside I, label ΔAe(I)/ÂUCp(J) as a window proxy and print both windows. Omitting plasma area alone pushes the ratio upward if the sampled area is accurate. Missing urine alone pushes it downward if plasma area is accurate. The net direction can be unknown because of numerical integration and assay error. Print arrows only when the corresponding limits in the table are supported. If both inputs are incomplete or there is no usable overlap, display the two observations separately and leave interval CLR empty.

| What is supported | Calculation and permitted use |
|---|---|
| Complete I, quantified urine, and plasma supported at both ends | Report ΔAe/ÂUC as an interval estimate. With numerator limits [N_L, N_U] and true interval-area limits [A_L, A_U], use [N_L/A_U, N_U/A_L] when defined |
| Complete urine, plasma covering only a subset J of I, with a positive area lower limit L_J | CLR_UPPER_ONLY: CLR,I ≤ N_U/L_J. Useful when plasma stops before the last urine collection. A point trapezoid without integration support gives a conditional proxy, not a formal upper limit. An upper limit can challenge filtration only in the below direction |
| Incomplete urine, full plasma window | A trustworthy lower limit of the recovered amount and a finite upper limit of the full area can give CLR_LOWER_ONLY: CLR,I ≥ N_collected,L/A_U. It can challenge filtration only in the above direction. No low-clearance inference is made from an unbounded urine loss |
| Incomplete urine and partial plasma, no other bounds, or disjoint windows | Numerator and denominator may both be too small and the ratio has no known direction (CLR_NO_DIRECTION). The two observations are reported separately |

12. Optional refinement of the partial-plasma upper limit. Only under the central-IV tail premises of item 29: if J ends at the last plasma observation p < v inside I, the area from p to v is at least C_p[1 − exp(s(v − p))]/(−s). A conservative lower limit for that non-overlapping segment is added to L_J. Label SENSITIVITY_ONLY. It is never used to manufacture a two-sided CLR estimate.
13. For the same fully covered I, list mean excretion rate ΔAe(I)/duration(I) and average plasma concentration ÂUCp(I)/duration(I). Under constant CLR, their ratio equals CLR, by integration of Eq. 39. Agreement across comparable intervals supports that model as a candidate. For partial coverage J, a plasma average refers only to J and uses duration(J). Display its own endpoints and keep the same-window rate comparison unavailable. A midpoint locates the collection bin.

T10 (EM-5c)
14. Run T10 (E0.10) on each eligible interval, in the direction the available limit can test. Report the status and the direction separately. With unmatched GFR or, for a total-plasma comparison, unmatched fu,p, label the comparison as sensitivity context (FILTRATION_REFERENCE_UNMATCHED). If only a matched-species literature GFR range is available, mark it as sensitivity context. With direct AUCu use the amount comparison in E0.10 and display its result in amount units in a value row. No descriptive band is drawn around the filtration range.

Nonrenal clearance
15. A supported upper limit U on CL and a lower limit L_f on fe, on the same target and analysis unit, give CLnr ≤ U × (1 − L_f) for 0 ≤ L_f ≤ 1. The weaker evidence status and the joint uncertainty are propagated.
16. A mean-curve proxy is never combined with a different cohort's mean fe to bound a mean individual CLnr. EV CL/F is never inserted. CLnr is never labelled "hepatic" or "metabolic". It covers every path other than unchanged parent into urine and can include loss of parent within the kidney. If these conditions fail, each input is reported separately.

Output per urine series
`admin_urine_fraction`, `fe_lower`, `collection_intervals`, `gaps`, `late_increment_share`, `clr_interval` (estimate for the full matched interval), `clr_window_proxy` (partial overlap, with urine/plasma windows and coverage for each), `clr_bound_direction` (BOTH / CLR_UPPER_ONLY / CLR_LOWER_ONLY / CLR_NO_DIRECTION / none), `filtration_reference`, `t10_status`, `t10_direction`, `clnr_upper`, `caveats` (COLLECTION_GAP, CAGEWASH_UNASSIGNED, ADMIN_DOSE_FRACTION, LATE_INCREMENT_SMALL, ACTIVE_MATERIAL_ASSAY, BELOW_LLOQ_UPPER_LIMIT, SAMPLE_STABILITY_RISK, SAMPLE_ADSORPTION_RISK, TR_NOT_PARENT, RATIO_OF_MEANS, FILTRATION_REFERENCE_UNMATCHED, CARRYOVER_POSSIBLE, WINDOW_PROXY, GROUP_MEAN), `not_assessable_reason`. Each quantity carries its units, basis and evidence kind.

Hand-off
- "By t, the source reports X % of the administered dose recovered unchanged in urine." Use “at least” with a supported lower limit and name its analysis unit. Whether the route is minor stays open unless an upper limit exists.
- The matched interval CLR, or the partial-window proxy with both windows and any separately supported direction; the T10 status and direction; the measurement that would make a one-sided limit two-sided (plasma through the end of the collection, or complete urine).
- A T10 exclusion above filtration: net secretion as a candidate, no transporter named. Below: reabsorption, loss within the kidney, and collection or handling alternatives, each needing distinct evidence.

Purpose, limits, and main-objective link
Reports how much unchanged drug was collected in urine, what the interval data support about renal clearance, and whether filtration alone is excluded in a stated direction. It does not estimate fe to infinity and does not identify a transporter or a site of reabsorption.

Keywords: urinary recovery; fraction excreted unchanged; interval renal clearance; one-sided bound; glomerular filtration; unbound fraction; secretion; reabsorption; nonrenal clearance; collection completeness.
MP basis: EDA004.
Sources: Gabrielsson et al. 2016, Fig. 6 case 6, Eq. 12 and discussion Eq. 39 (plasma and urinary measurements with shared clearance). Renal clearance and urinary recovery as in Rowland & Tozer, 4th ed., and Gibaldi & Perrier, 2nd ed. (standard definitions). Bourne DWA, Pharmacokinetics course, chapter 5, Analysis of urine data, https://www.boomer.org/c/p4/c05/c0503.php and c0505.php (read 2026-11-10: rate points are independent and tolerate a missed sample; the amount-remaining plot carries every error into the total). Scotcher et al. 2016 Eur J Pharm Sci 94:59, §2.2, https://pmc.ncbi.nlm.nih.gov/articles/PMC5074076/ (read in the part quoted: a ratio above 1.5 was used to exclude likely net secretion from a human reabsorption analysis). Chapron et al. 2017 Clin Transl Sci 10:395, doi 10.1111/cts.12481 (read in the part quoted: 0.74 was an inclusion cut-off in a human kidney-function analysis, not a diagnostic cut-off for animal reabsorption). Davies & Morris 1993 Pharm Res 10:1093, doi 10.1023/A:1018943613122 (source context for compiled physiology; DOI and title checked, values not copied; a species-table value does not substitute for matched study physiology in T10). Assay type and loss to container surfaces: Abdelraouf et al. 2012 Antimicrob Agents Chemother 56:5724 (read: urinary recovery by a specific assay against much higher earlier values from non-specific microbiological assays) and Karvanen et al. 2017, [colistin adsorption study](https://doi.org/10.1128/AAC.00857-17), abstract and Fig. 2–4 captions (colistin in protein-free in vitro medium, with concentration and container dependence). Sharafi & Ardebili 2019, Infect Drug Resist 12:2649, provide review context. The interval limits, the truncated tail and the nonrenal limit are derived.

---

### 34 | RECOVERY: WHERE DRUG-RELATED MATERIAL WAS RECOVERED

Scope
- A recovery design: administered radiolabel, or a source-defined non-overlapping parent-equivalent total, collected in excreta with or without carcass and tissues.
- Parent alone cannot close a total drug-related mass balance.

Principle
- A mass balance needs a conserved quantity: the administered radiolabel (including the label position), or a source-defined non-overlapping parent-equivalent total.
- Percent of dose, percent of recovered material and percent of the radioactivity in one excretum are different denominators.
- "Unaccounted" has several possible origins: later excretion, retained material, unmeasured routes, loss of label, and collection or analytical losses. The remainder is not apportioned among them.

Data and details
- Route of administration, cohort, collection window, and whether animals were intact or bile-cannulated.
- Per excretum and interval: amount or % of dose, denominator, cagewash allocation; carcass, tissues and unallocated washes.
- Source tolerance for recovery, when stated.

Figures (E0.11)
- EM-6a.

Assessment
1. Identify the conserved quantity and record the design (Scope, Data and details).
2. Report three totals separately: urine + faeces; all measured excreta; all material accounted for. Residual carcass, tissues and unallocated washes enter only the total they belong to.
   - A source-reported total with disputed route labels can be displayed as reported. The split is not invented.
   - Do not add a subtotal twice, count a wash that is already allocated, sum tissues that are already inside a whole-carcass total, or combine bile and faeces across different designs. Overlapping totals are never stacked.
   - A route in which the analyte was detected with no amount reported is named and enters neither the split nor a total (ROUTE_DETECTED_NOT_QUANTIFIED).
3. T12 (E0.10) on comparable cumulative measurements. Findings are data-check results.
4. Recovery is reported as numbers: each route and each total with its denominator and collection end. No completeness class is assigned and no reference threshold is applied. Keep each printed value above 100 % and record the point discrepancy. Escalate its severity using a justified source tolerance or an explicitly configured project tolerance. If neither is available, retain the point discrepancy with the tolerance marked unknown.
5. Reading of routes.
   - After IV dosing, faecal TR supports transfer of drug-related material into the gut. It does not identify a unique route.
   - Drug-related material in faeces or bile, or a secondary plasma peak, does not establish enterohepatic recycling.
6. Record what "unaccounted" could reflect (Principle).

Output per recovery dataset
`recovery_urine_faeces`, `recovery_all_excreta`, `recovery_accounted`, `route_split`, `collection_ends`, `t12_findings`, `unaccounted_candidates`, `caveats` (TR_NOT_PARENT, OVERLAPPING_TOTALS, SOURCE_CONFLICT, ROUTE_DETECTED_NOT_QUANTIFIED, CARRYOVER_POSSIBLE, CAGEWASH_UNASSIGNED, SAMPLE_ADSORPTION_RISK), `not_assessable_reason`.

Hand-off
- Routes by which drug-related material was recovered, each with its amount, window and denominator.
- Recycling stays a "pending DME" candidate without support from this item; a matched intact and bile-cannulated design would be the test.
- An independent, compatible mass balance that limits the unaccounted dose is the evidence item 33 needs for a "minor route" statement.

Purpose, limits, and main-objective link
Shows where drug-related material was recovered and how much of the dose is accounted for on each denominator, and catches recovery tables that do not reconcile. It does not assign a unique route and does not establish recycling.

Keywords: mass balance; total radioactivity; recovery; urine and faeces; cagewash; carcass; data integrity.
MP basis: EDA004.
Sources: FDA, Clinical Pharmacology Considerations for Human Radiolabeled Mass Balance Studies, guidance for industry, July 2024, §§V.G–I, https://www.fda.gov/media/158178/download (read in full; used for the separation of denominators only; it addresses humans and its thresholds are not applied). Roffey et al. 2007 Drug Metab Rev 39:17, doi 10.1080/03602530600952172 (abstract read: origins of incomplete recovery in animal and human studies). Gabrielsson et al. 2016, discussion (read).

---

### 35 | EXCRETA COMPONENTS AND IN VITRO TRANSFORMATIONS

Scope
- Component profiles in urine, faeces or bile, and in vitro loss or kinetic assays.
- Plasma metabolite series are not read here (item 32, reserved).

Principle
- A component share becomes a share of dose only through the recovery of the same excretum on the same basis: component % of dose = (component % of excretum TR × excretum TR % of dose)/100.
- A measured product is not an enzyme, a site of formation or a total fraction metabolized. A named urinary product can reflect enzymatic metabolism, chemical conversion in vivo, or degradation after collection.
- In vitro readouts are comparable only within matched systems. They are not scaled.

Data and details
- Per component: identity (named or unresolved), excretum, cohort or pool, interval, label, reported basis, extraction and profiling coverage.
- The matching excretum recovery (item 34) from the same cohort or pool, interval, label and accounting basis.
- Sourced MW and stoichiometry where molecules are compared by mass.
- Stability conditions (E0.2, gate 5), product identity, source statements, and matched active, inactive or no-enzyme controls.
- In vitro: the E0.8 in vitro fields.
- In vivo quantities for a comparison (items 29 and 33), each with its evidence kind.

Figures (E0.11)
- EM-7a; EM-7b.

Assessment

Excreta components (EM-7a)
1. Convert a component's share into % of administered radiolabel only with the corresponding excretum's recovery from the same cohort or pool, interval, label and accounting basis. State the extraction and profiling coverage: % of chromatogram area is not automatically % of all excretum TR. A missing denominator leaves the value on its reported basis. TR is not converted to unchanged parent without identity and quantitative support.
2. Name the largest measured component in this excretum and window, with its dose share, and any unassigned peaks or amount outside the profiled fraction (UNPROFILED_FRACTION). Reconcile the component sum against that excretum's total.
3. Identified, unidentified and unprofiled shares are reported as numbers on the radioactivity recovered in the excretum assessed. No threshold is applied. A single urine profile gives a urine-specific result only. Aggregate by amounts (recovery-weighted), not by an unweighted average of percentages. Unknown identity stays unknown.
4. Product origin (PRODUCT_ORIGIN_OPEN). Link the documented stability conditions, the product identity, source statements and the matched controls, and keep the evidence from each distinct. A rising product share on later occasions can also reflect parent recovery, collection timing and carryover.

In vitro (EM-7b)
5. Compare only matched systems, substrate, starting concentration, incubation time (for residual %), protein or cell normalization, cofactors, units and controls. With fewer than two comparable rows in a matched system the readout is a table row and EM-7b is not drawn.
6. Direction of each readout on one basis: at equal incubation time, less parent remaining denotes more loss; a shorter reported half-life denotes faster loss; a higher Vmax/Km denotes a higher reported low-concentration efficiency.
7. Enzyme kinetics, depletion and chemical stability are distinguished. No ranking across systems.
8. If a printed Vmax/Km conflicts with compatible printed inputs beyond rounding, all values are kept as reported, the row is flagged SOURCE_CONFLICT and it is left out of the affected ranking.

In vivo comparison (table, no panel)
9. List eligible in vitro rankings beside comparably defined in vivo evidence in one table.
10. Same-direction upper bounds on CLnr cannot rank the actual CLnr, even across three or more species. In that case the bounds are displayed as bounds and rank agreement is omitted (RANK_NOT_ELIGIBLE).
11. With independently supported, comparable in vivo estimates, or non-overlapping two-sided ranges, describe agreement or discordance with its uncertainty. An association does not assign a pathway and does not validate IVIVE.

Output per component profile or assay
`component_identity`, `excretum`, `reported_basis`, `dose_share`, `identified_share`, `unidentified_share`, `unprofiled_share`, `sum_check`, `in_vitro_readout`, `rank_eligibility`, `in_vivo_comparison`, `caveats` (UNPROFILED_FRACTION, PRODUCT_ORIGIN_OPEN, SOURCE_CONFLICT, RANK_NOT_ELIGIBLE, SAMPLE_STABILITY_RISK, SAMPLE_ADSORPTION_RISK, TR_NOT_PARENT, CARRYOVER_POSSIBLE), `not_assessable_reason`.

Hand-off
- The products observed, each with excretum, window, basis and share, and whether its origin is separated by controls and stability data.
- In vitro differences as assay-basis observations, with the matched system they hold for.
- No fraction metabolized, no enzyme assignment and no scaled clearance.

Purpose, limits, and main-objective link
Reports which components were measured in excreta and what in vitro assays show on their own basis, and keeps product identity, origin and amount apart. It does not estimate a fraction metabolized and does not scale in vitro data.

Keywords: metabolite profile; component share; identified share; product origin; chemical degradation; in vitro stability; Vmax/Km; species ranking; no IVIVE.
MP basis: EDA004.
Sources: FDA 2024, §§V.G–I (as item 34; denominator of the identified share). The component conversion and the aggregation rule are arithmetic. EDA004 for the no-scaling limit.

---

### 36 | CONDITIONS AND THE PROJECT SPECIES TABLE

Scope
- Run once per project. One row per species × study × comparable condition. Every species gets a row, including a species with one study or reported parameters only.

Data and details
- Per row: body weight (or "not reported"), route and dose, analyte and matrix basis, sampling and collection windows, analysis unit, source, and the outputs of items 29–35 with their evidence kinds.

Figures (E0.11)
- EM-8a: elimination columns added to the project species table DIS-6b. No second table.

Assessment
1. Columns. One column per quantity, each with its evidence kind: the window clearance (CL or CL/F, item 29); a source-reported clearance; urinary recovery of unchanged parent with its collection end; interval CLR or window proxy, with coverage and any supported direction and, once the filtration range is sourced, the T10 result; recovery by route; the largest measured product; in vitro readouts on their own assay basis. Quantities that the species table already shows are not repeated. Missing cells stay visible. Different quantities are never put on a common clearance axis.
2. Contrasts. For each proposed contrast record `comparable`, `descriptive_only` or `incompatible`, with the specific reason.
3. Different collection ends cannot be rescaled by time. Two lower recovery bounds cannot order the ultimate fe, even with equal end times. Observed recovery is compared over matched intervals when eligible.
4. Each species summary ends with one observation, its principal unresolved alternative and one feasible discriminator.
5. No allometric exponent, no human prediction and no inferred species mechanism.

Output
`species_rows`, `contrast_rows` (pair, quantity, comparability, reason), `species_summaries` (observation, alternative, discriminator), `missing_by_species`.

Hand-off
- Species and condition differences as covariate candidates, each with the comparison that supports it and its comparability status. No scaling or prediction is made in EDA.

Purpose, limits, and main-objective link
Shows what can already be compared across species and conditions on a common basis, and what is missing for each species.

Keywords: species comparison; comparability; collection window; fe; renal clearance; recovery; in vitro basis; covariate candidate.
MP basis: EDA004; figure list C1, C2.
Sources: Gabrielsson et al. 2016 (read); Davies & Morris 1993 (source context for compiled physiology; values not copied).

---

### Flag registry (items 29–36, r1.1)

Each flag is defined once; the item text gives the detail. Evidence labels are defined in A0.3 and E0.3. Flags reused from absorption and distribution (GROUP_MEAN, DESTRUCTIVE_SAMPLING, DIGITIZED, ENDOGENOUS_REVIEW_REQUIRED, CONFOUNDED, OCCASION_CONFOUNDED, TIME_DEPENDENCE_SUSPECTED, INFUSION_TIMING_UNKNOWN, LOCAL_ROUTE, RATIO_OF_MEANS, MEAN_OF_RATIOS, REPORTED_PARAMETER) keep their definitions. The review draft uses few codes; the names below marked "new" are proposed in r0.3 for structured output only.

| Flag | Item | Trigger |
|---|---|---|
| JUSTIFIED_BOUND / STATISTICAL_BOUND / SENSITIVITY_ONLY | E0.3 | Kind of a directional bound |
| WINDOW_PROXY (new) | E0.6; 29, 33 | D/ÂUC or ΔAe/ÂUC from a point trapezoid without a justified area limit |
| PARTIAL_WINDOW (new) | E0.6; 29 | First sample late; area written AUC(a,b) |
| CONDITIONAL_AREA (new) | E0.6; 29 | Right-end area under the stated non-rising assumption; IV after input has ended; sensitivity only |
| REPORTED_CL_ABOVE_WINDOW (new) | 29 | Source-reported CL above the window value D/ÂUC from the same data; data check |
| CONDITIONAL_TAIL (new) | 29, 33 | Last-chord tail inequality used; sensitivity only |
| DOSE_SPECIFIC_RATIO (new) | 29 | Nonlinear or time-varying disposition; no single constant CL |
| GROUP_CURVE_RATIO (new) | 29 | D over the area of a group-mean curve |
| EV_OVER_F (new) | 29 | EV target; the "/F" qualifier is kept |
| SINGLE_DOSE_ONLY (new) | 30 | One dose; dose dependence cannot be assessed |
| EV_INPUT_CONFOUNDED (new) | 30 | EV AUC/D or peak time changes; F, absorption rate and disposition not separable |
| NO_UNCERTAINTY (new) | 30 | Comparable doses without supported uncertainty; points described only |
| TWO_OCCASIONS_ONLY (new) | 31 | Two occasions; contrast, no trajectory |
| REGIMEN_CHANGED (new) | 31 | Regimen, co-medication, sampling phase or dose timing differs; occasions described separately |
| CARRYOVER_POSSIBLE (new) | 31, 33, 34, 35 | Recovered material may include earlier doses |
| SCOPE_REVIEW (new) | 32 | Plasma metabolite or TR series inventoried; item reserved |
| TR_NOT_PARENT (new) | E0.2 | Total radioactivity; not unchanged parent and not metabolite-specific |
| ACTIVE_MATERIAL_ASSAY (new) | E0.2; 33 | Microbiological assay; active material, not unchanged parent |
| BELOW_LLOQ_UPPER_LIMIT (new) | E0.5; 33 | Nominal censored amount for a representative collection with known volume. Limits on original excreted amount also need supported assay and recovery bounds |
| SAMPLE_STABILITY_RISK (new) | E0.2; 33–35 | Documented instability under the relevant conditions |
| SAMPLE_ADSORPTION_RISK (new) | E0.2; 33–35 | Sourced loss to container surfaces in a low-protein matrix, handling not stated |
| SOURCE_CONFLICT | E0.2, E0.5; 34, 35 | Printed values, headers or footnotes in conflict |
| COLLECTION_GAP (new) | 33 | Non-contiguous collection; "sum over collected intervals" |
| CAGEWASH_UNASSIGNED (new) | 33, 34 | Cagewash not allocated to an excretum; kept separate |
| ADMIN_DOSE_FRACTION (new) | 33 | EV dosing: r_U is a fraction of the administered dose (F × fe) |
| LATE_INCREMENT_SMALL (new) | 33 | Last increment below `late_increment_share`; descriptive |
| CLR_UPPER_ONLY / CLR_LOWER_ONLY | 33 | One-sided interval renal clearance |
| CLR_NO_DIRECTION (new) | 33 | Incomplete urine and partial plasma, or disjoint windows |
| FILTRATION_REFERENCE_UNMATCHED (new) | 33; T10 | fu,p or GFR not matched to the study; sensitivity context |
| OVERLAPPING_TOTALS (new) | 34 | Totals that share material; not stacked |
| ROUTE_DETECTED_NOT_QUANTIFIED (new) | E0.5; 34 | Analyte detected in an excretum, no amount reported |
| UNPROFILED_FRACTION (new) | 35 | Part of the excretum TR outside the profiled fraction |
| PRODUCT_ORIGIN_OPEN (new) | 35 | Product origin not separated by controls and stability data |
| RANK_NOT_ELIGIBLE (new) | 35 | In vivo side is bounds only, or systems not matched |

---

## B. Changes to existing rules that these items need

These are integration requirements. The rule revision itself does not change software, run configuration or historical findings.

1. **EDA004 allowlist**: add the E0.7 list for items 29–36. The last-chord tail inequality (item 29, and its truncated form in item 33) is the only tail calculation allowed. No fitted terminal slope, fitted half-life, AUC to infinity, fitted excretion asymptote, sigma-minus plot, formation constant, IVIVE, allometry or model selection.
2. **A0.10 test list**: register T10 with its premises and its two directions (E0.10). Register T12 as a data check that cannot exclude a model. Reserve T11 with item 32.
3. **Distribution item 24** (applied in the distribution rules r1.3, 2026-11-10): the late-area share moves there from item 29. Add the output `late_area_share` = observed AUC(cut,b)/AUC(a,b) as a percentage, with cut = `post_distribution_from_h` and the window stated; add it to the D0.7 allowlist; show it as a value row under DIS-1b, without a plot and without a threshold. It is reported only when `phases_visible` is TWO_OR_MORE or TWO_OR_MORE_TENTATIVE: with ONE_APPARENT the cut equals the first sample and the share is 100 % by construction. Reading: "most of the window area lies before (or after) the cut" means exactly that; it does not establish how much of total lifetime exposure is terminal. Basis: Gabrielsson et al. 2016, case 2 (similar terminal slopes with very different AUC).
4. **Upstream contract**: bind absorption A0.3–A0.6, items 18, 19, 21 and 23, and distribution D0.2–D0.10, DIS-2 and items 24–28 at their actual run versions. The review draft checked its definitions against the local distribution r1.1 and absorption r4.3 texts; r0.1 named distribution r1.2; this restructure was compared with the absorption r4.2 and distribution r1.2 files named in the header; distribution r1.3 differs from r1.2 only by the late-area share. Confirm the bound run's version and premises before formal reuse. An ID alone does not establish equivalence.
5. **Data card and intake fields** to propose to the code thread: the E0.8 excreta, in vitro and supporting-quantity fields. Intake must preserve urine interval headers, footnotes, concentration against amount, cohort and denominator.
6. **Hand-off record**: the minimum result record of E0.9; elimination back-fills the "pending DME" entries of A0.9 and D0.9; H links each hypothesis to an observation, an alternative and one next test.
7. **Run configuration**: no setting is silently active. Store the value, comparison operator, denominator, intended population, provenance and version. If a setting is absent, only the threshold classification is omitted and the continuous measurement is still shown. The values below are proposals. None is a validated animal decision boundary. The human radiolabel reference thresholds (recovery above 90 %, daily excretion below 1 %, identified share above 80 %) are not settings of this module.

| Setting | Proposed use | Boundary |
|---|---|---|
| `late_increment_share` | Below 5 % of the cumulative unchanged urinary amount, with the last bin at least as long as the previous one (adopted 2026-11-10) | Display "small last increment". No remaining-tail estimate and no conclusion |
| `clr_band` | Retired (2026-11-10). The former descriptive band [0.75, 1.50] on CLR/(fu,p × GFR) is not drawn and not reported | Only the sourced filtration range and the T10 result are shown (Scotcher 2016 and Chapron 2017 used such cut-offs for selecting human data, for other purposes) |
| `recovery_review_tolerance_pp` | 5 percentage points of administered dose beyond 100 %, when no source-based tolerance exists | Project data-review trigger only. A printed 103 % stays 103 %. No biological inference and no automatic correction |
| Supporting quantities | fu,p, GFR, blood/plasma ratio, MW, body weight, collection and stability limits, each with a source specific to the comparison | `gfr_ml_min_kg` is kept distinct from absolute GFR and from GFR indexed to surface area. No value is filled from memory |

8. **Front end**: reader view species → study → question → H; question rows of E0.11 as the main view, ordered by data layer with plasma first: Q1, Q2, Q5 and Q7 always shown, Q3 for repeated dosing, Q6 for a recovery design, Q4 reserved without a row; natural English on figures, codes in structured output.
9. **Figure reuse**: the code for items 29–36 calls no plotting function for a reused panel. It reads the upstream plot and result record and writes its own conclusion sentence. Needed from the code thread: the absorption record (window AUC, the C2 metrics, T3 and T3p, the item 23 occasion result) and the distribution record (DIS-1b chords, `post_distribution_from_h`, T7, DIS-2, the DIS-4c reference ratio, the DIS-6b rows) addressable by ID and version, and a DIS-6b table that accepts added columns.
10. **Test record (outside the rules)**: project examples, the Gabrielsson case examples and the check cases for T10 and T12 go to a separate test file. They are not part of section A.

## C. Decision record and implementation dependencies

1. Additions kept from the thread draft, listed here with their place in the text: assay type and active material (E0.2 gate 3); loss to container surfaces (E0.2 gate 5); interval below the assay limit (E0.5); route detected but not quantified (E0.5, item 34); sigma-minus plot not used (E0.7); interval rate and interval CLR usable when another interval is missing (item 33, step 5); CLnr can include loss of parent within the kidney (item 33, step 16). The context note on long persistence of plasma TR and the optional animal adaptation of the recovery reference were removed with the Q6 decision (point 3).
2. Dropped from the thread draft because the review draft is stricter: the trapezoid D/AUC(window) as a strict upper bound; the "very low fe means a minor route" reading and its 1 % setting; the reading of a late plateau as near-complete excretion; the renaming of CLnr to CL_other; species ranking from bounds; the CLR band as a reading of secretion or reabsorption; the flag for intervals long against the half-life.
3. Walkthrough decisions (George, 2026-11-10; Q1 to Q7 complete). Q1: item 29 computes one window clearance D/ÂUC from the AUC that upstream already holds and shows it by default (step 2). The justified limit, the conditional area limit and the conditional tail are folded sensitivity rows (step 4). A source-reported CL above the window value is flagged for review (step 5). Proposed and not adopted: comparing a justified clearance limit with fu,p × GFR when only plasma exists. Q2: item 30 gains the direction readings of the urine evidence by dose, as candidates only (step 5). Q3: item 31 confirmed as written. Q5, amount in urine (EM-5a), confirmed: the row is shown in every study and reads "urinary recovery unknown" without urine data; `late_increment_share` 5 % is adopted as a descriptive label only; microbiological-assay values are "active material" on a separate trace; an interval below the assay limit retains its assay-based censoring threshold and the collection conditions of E0.5; total radioactivity, when measured, is a separate trace on EM-5a and is not converted to parent. Q5, renal clearance (EM-5c): one CLR value per interval from the existing plasma AUC is shown by default with its sampling coverage and the expected effect of missing area or amount, with conditional or supported limits in folded rows; a literature GFR range gives sensitivity context only; the descriptive band `clr_band` is retired; the filtration range is drawn only once fu,p and GFR are sourced. Q6, recovery (EM-6a): the animal-study text is shortened. Recovery is reported as numbers on stated denominators with no completeness class; the human reference thresholds, their settings and the flag RECOVERY_REFERENCE_HUMAN are removed, and so are the time to 90 % of the final observed recovery and the note on persistence of plasma TR; a value above 100 % stays as printed and is a review finding beyond the tolerance; T12 remains a data check; the identified share in item 35 is a number without a threshold. Q7 (EM-7a, EM-7b, species columns): EM-7b is drawn only with at least two comparable rows in one matched system, otherwise the readout is a table row; the species columns of item 36 are reduced to the quantities the module now reports by default.
4. Removed or moved in r0.5 to r0.7 (George, 2026-11-10). Each can be restored when a dataset needs it.
   - Question order. r0.7 had re-ordered the questions with urine before dose and repeated dosing. r0.8 restores the review draft's numbers and orders the module by data layer, plasma first (E0.1).
   - EM-1a: a value row instead of a plot. Side-by-side limits invite a comparison that item 29 forbids.
   - EM-1b, late-area share: moved to distribution item 24 (section B, item 3). It describes the disposition phases, not elimination.
   - EM-2a, EM-2b and the calculations of item 30: duplicates of absorption item 19 (C1 to C3, T3, T3p) and distribution item 24 (DIS-2a, DIS-2b, DIS-1b chords). Item 30 keeps the reading table only.
   - EM-3a, EM-3b and the plots of item 31: the two-occasion contrast duplicates absorption item 23 (E1, E2) and DIS-4c with T9. The trough-by-occasion panel had no dataset in the current projects. Item 31 keeps the reading and the urine-by-occasion rule.
   - EM-4 and the reserved question row: nothing to draw while item 32 is reserved.
   - EM-5b, rates against interval-average plasma concentration: the same ratio as EM-5c shown a second way, and not readable when plasma ends before the urine interval. The two quantities stay as table values.
   - EM-6b, intact against bile-cannulated, and the faecal reading after oral dosing: no such design and no oral dosing in the current scope. The cannulation field stays on the data card.
   - EM-7c, in vitro against in vivo: with upper bounds only on the in vivo side no ranking is allowed, so the panel could not be drawn. The comparison stays as a table.
   - EM-8a: columns of the project species table DIS-6b instead of a second table. EM-R: no repeat of values already in F or DIS-R.
5. Proposed in r0.3 and not in the review draft: the tiers in the figure table, the flag names marked "new", the reading map, and the caveat lists in the output lines. They restate the review draft's conditions and add no new reading.
6. The hand-off example in E0.9 is written without numbers so that section A carries no data example.
7. Implementation dependencies. (a) GFR values are not filled in: the Davies & Morris table could not be read as text and no value is written from memory; until a sourced value exists EM-5c shows CLR only. (b) Of the settings in section B, item 7, `late_increment_share` is adopted and `recovery_review_tolerance_pp` is a proposal. The optional descriptive aids (dose-range flag, fold band) were removed from the settings because items 30 and 31 compute nothing. (c) Case-specific H and software integration are downstream work. E0.9 defines the hand-off for this rule edition.
8. MP basis lines use EDA004 and the figure list only. No elimination-specific MP ID has been assigned.
9. Reference status. Read in full: Gabrielsson et al. 2016, FDA 2024, Abdelraouf 2012. Read in the relevant parts: Karvanen 2017 (primary article abstract and Fig. 2–4 captions), Scotcher 2016, Chapron 2017, Bourne chapter 5, Sharafi & Ardebili 2019. Abstract only: Roffey 2007. DOI and title only: Davies & Morris 1993. Textbooks (Rowland & Tozer; Gibaldi & Perrier) are cited for standard definitions.

10. Final source review (r1.1). Cases 1–2 distinguish terminal slope from whole-profile exposure. Cases 7–10 refine the dose-design and phase readings in item 30. Case 14 informs the descriptive interpretation of treatment periods. Case 6 and Eqs. 12 and 39 motivate a joint plasma/urine hand-off and the matched-window calculation in item 33. The in vitro primary adsorption source was checked for the conditions it actually studied. Modeling, software integration, and study-specific data review have separate deliverables.
