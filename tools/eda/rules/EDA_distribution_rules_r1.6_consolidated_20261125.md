# EDA distribution rules, items 24–28 (r1.6)

Version: r1.6 · Edition: consolidated, 2026-11-25 (wording only; no rule changed) · Status: current (wording confirmed by George 2026-11-26)

Shared rules: `EDA_shared_rules_s1.0_consolidated_20261125.md` (s1.0); where this file and s1.0 differ, s1.0 wins.
Machine form: `distribution_rules_r1.6.machine.yaml` (unchanged). Question numbers: the reviewed guide
`EDA_distribution_rules_r1.5b_reviewed_20261124.md` (nine questions).
History: this edition merges three layers into one text: the r1.3 rules (2026-11-10), the r1.5 revision (2026-11-21) with the
r1.5b decisions A–D (2026-11-24), and the r1.6 amendments (2026-11-24). The superseded r1.3 file
(`EDA_distribution_rules_r1.3_rules_only_20261110.md`, SHA-256 5cb7ae001125093caf8b4fe6fd0fccfe6b33049675b825de9f6be6dd5d4ab106)
stays in the rules folder; the r1.5 text is quoted whole in the r1.6 file of 2026-11-24 (SHA-256 of the r1.5 text
8e828b9aadb1e1c432f90a7bfb1c5c718e7197a6c3dea06c7b4baa03b0672009). Appendix A lists what r1.5 and r1.6 changed; Appendix B
lists the checks that the tests cover.

## Main question and scope

> **What is the simplest disposition model supported by the observed parent concentration–time data?**
> Can linear one-compartment disposition explain the observations? Which time window and measurements support testing
> peripheral exchange or another mechanism? Formal T6/T7 readings use IV data; EV profiles receive the descriptive reading
> of item 24 (EV profiles).

Give one study-level conclusion supported by the observed window, the observations that carry it and the main limitation.
Use the observed phases to order candidate models for testing; the model comparison and any choice of additional
compartments belong to Modeling.

| Analysis | Where it belongs |
| --- | --- |
| IV shape, evidence strength and alternative explanations | item 24 |
| Initial central-volume upper bound | item 25, supporting evidence |
| Measured tissue distribution and tissue–blood comparison | item 26, optional |
| Binding data and unbound observations | item 27; shown when binding can change the PK interpretation; effect-relevant exposure goes to PK/PD |
| IV/EV comparison, masked distribution and flip-flop | Absorption item 18; Distribution supplies the IV reference window |
| EV post-peak shape and the Vc/F bound | item 24 (EV profiles), item 25; formal T6/T7 are not assessable |
| Candidate ordering for model search (APOD) | D0.9; only formal exclusions remove a candidate |
| Cross-species comparability and transfer | item 28; at the start of Translation or before shared constraints in a joint fit |

The rule text applies EDA004. It uses observations, justified bounds and summaries within the observed window. Curve fitting, extrapolation to time zero or infinity, and parameter estimation are left to modeling. Published parameter estimates are reported with their source, method and uncertainty.

## A. Rule text

### D0 | SHARED DEFINITIONS FOR ITEMS 24–28

Items 24–28 use the absorption definitions A0.3–A0.6 and A0.9 unless D0 states a difference. The formal decision, removal, widening and timing checks, test families, precision admission, rank groups and question statuses are those of the shared rules s1.0. Each item states only what differs from D0.

#### D0.1 Order of execution

0. Data card (D0.11) and gates (D0.2). This includes route and administration, time origin and baseline (absorption item 21), data status (A0.5), matrix and basis (D0.8), and uncertainty (D0.4).
1. Mass-balance pre-check D3 (item 26) on every tissue dataset. Rows failing D3 do not enter any later step.
2. Item 24, IV plasma disposition shape (DIS-1, DIS-2, the EV/IV link).
3. Item 25, initial central-volume bound (DIS-3).
4. Item 26, tissue concentrations, tissue/reference ratios and repeat dosing (DIS-4a, DIS-4b, DIS-4c).
5. Item 27, plasma protein binding, unbound exposure and Kpuu (DIS-5).
6. Item 28, conditions within a species, then the project-level species table.
7. Hand-off (D0.9) and status board (D0.11).

Execution follows these dependencies. Presentation follows the question order in D0.11. Item 26 uses `post_distribution_from_h` from item 24 and the binding record from item 27. Item 28 is run once per project, after every species and study has been read.

#### D0.2 Gates

1. Route and administration.
   - Items 24 and 25 need IV data: a central bolus, or the period after a central infusion has ended. Points during an infusion are not read as disposition shape. Times are counted from the end of the infusion. If the infusion duration is not reported, set INFUSION_TIMING_UNKNOWN. The data are still displayed, but T6 and T7 are not run and item 25 is not computed.
   - EV-only data: item 24 gives a description of the post-peak decline only and links to absorption item 18. Item 25 is NOT_APPLICABLE. EV data give V/F only, as a reported parameter.
   - Local dosing to the sampled site (intratracheal or inhaled dosing with ELF or lung sampling, intrathecal dosing with CSF sampling): the site/plasma direction is reversed. Item 26 reports the observations and sets LOCAL_ROUTE. The readings of DIS-4b do not apply.
   - ROUTE_UNKNOWN: items 24–28 are not run. Values are background only.
2. Time origin and baseline: absorption item 21. ENDOGENOUS_REVIEW_REQUIRED (A0.8) stops T6–T9, D3, item 25 and the item 26 ratio readings. Only DIS-1 and DIS-4a are drawn, with the baseline as a reference line.
3. Data status: A0.5. A profile with every sample BLQ is NOT_ASSESSABLE and is never reported as "no distribution".
4. Matrix and basis: D0.8. MATRIX_UNKNOWN stops every quantitative reading of that series.
5. Uncertainty: D0.4.

A gate failure gives the outcome stated in the item, with the reason.

#### D0.3 Exclusion principle and evidence labels

The formal decision follows s1.0 S10: premises, interval or test basis, full data, removal (S2), timing and prespecified widening (S3), exclusion. The labels are CANNOT_ASSESS, NOT_EXCLUDED and EXCLUDED_UNDER_STATED_ASSUMPTIONS; what is excluded is a complete combination of input, disposition, initial state and observed signal (A0.3). The project tolerance and the noise gate are descriptive only.

Distribution adds the following.
- Descriptive readings (the split-half curvature reading in item 24, the dose pattern in DIS-2, the four readings of DIS-4b) are shape descriptions. They use project noise settings and project bands. They are never turned into an exclusion. Formal exclusions in items 24–28 come only from T6, T7, T8, T9 and the reused absorption tests T3, T3p and T5, each with its premises.
- A data check is not a model exclusion. D3 and the plasma-volume check in item 25 can mark rows as DATA_ISSUE. They exclude data from later steps, not a model.
- When no difference is detected, write "not seen in this window", never "absent".

#### D0.4 Uncertainty used for allowed intervals

A0.4 applies unchanged: each concentration has an interval [L, U] with its source, each uncertain time an interval [t⁻, t⁺], and analytical, between-animal and digitization error are recorded separately. Distribution adds sources specific to tissue data. Each is recorded separately and never replaces another.
- Homogenate dilution factor and the basis of the reported value (per g tissue, per mL homogenate, per organ).
- Residual blood: correction status and the V_r value with its source (item 26).
- Organ weight: same-study value, or a literature range matched on species, strain, age and body weight, with its source (D3).
- Recovery: microdialysis recovery calibration and method; ELF urea-dilution correction and lavage dwell time.
- Binding: fu,p and fu,T with method, temperature, concentration tested and nonspecific binding where reported (item 27).

Noise settings. Set the per-point noise σ on ln C for each dataset before running T6, T7 or the split-half screen, and do not change it after seeing their results. The shared precision admission (s1.0 S8) sets the tier:
1. tier 1, SOURCE_ASSAY: the assay precision reported by the source, converted as σ ≈ √ln(1 + CV²), at the concentration range of the profile where given;
2. tier 2, SOURCE_REPLICATES: replicate or duplicate measurements in the source;
3. tier 3, DEFAULT: the project default, 0.15 for individual data and the item 24 step 3 formula for group means.

Record the value, `noise_tier`, `tier_label`, the admitted components and the source locator in the evidence table. A formal T6/T7 result needs tier 1 (converted to joint bounds over every searched point) or tier 2 (stated coverage); tier 3, pointwise or unconverted precision gives CANNOT_ASSESS with SENSITIVITY_ONLY (decision A). Project tolerances for T6/T7 follow the same order. A per-dataset override is set in `distribution_config.json` (`noise_by_dataset`). Statistics built from reported SDs with small n use t quantiles with Welch–Satterthwaite degrees of freedom, not a fixed z of 2 (item 26, step 10).

#### D0.5 Data status outcomes

A0.5 applies unchanged. Distribution adds the following outcomes.

| Data status | Outcome in items 24–28 |
|---|---|
| Reference (plasma, serum or blood) BLQ at a time when the tissue is quantified | The tissue value is kept. The ratio at that time is UNDEFINED. The time is not used in DIS-4b, Kpuu or D3 denominators |
| Tissue BLQ | The tissue is reported as [0, LLOQ_T] in its own units. Ratios use the interval only in formal tests; no point ratio is formed |
| Tissue and reference from different animals at one time | The ratio is a ratio of group means (RATIO_OF_MEANS). It is not a mean of individual ratios. Its uncertainty treats the groups as independent |
| Source reports a mean of individual ratios | It is kept as reported (MEAN_OF_RATIOS) and is not recomputed from group means. The two estimators are never mixed in one trend |
| Homogenate value with unknown dilution or unknown basis | MATRIX_UNKNOWN; display only |

#### D0.6 Observed-window AUC

A0.6 applies unchanged: observed points only, linear-up/log-down, no extrapolation, a prespecified common window. Distribution adds the following.
- A tissue/reference AUC ratio uses the same window, the same integration rule and actual sampling support at both window ends in both matrices.
- For destructive sampling, a CI for the AUC ratio needs a variance method matched to the hybrid estimator (A0.10, T3) and an interval suited to a ratio: Fieller-type with a moderate to large number of sampling times, bootstrap-t with few (item 26, step 8). Otherwise the ratio is descriptive.
- An unbound AUC is the integral of a measured or derived unbound profile (item 27). It is not total AUC × fu unless fu is supported as constant over the window.

#### D0.7 Descriptive calculations allowed (complete list for items 24–28)

- The A0.7 terminal slope, for item 18 only. Its window starts at or after `post_distribution_from_h` (item 24).
- Chord slopes between consecutive quantified points, [ln C₂ − ln C₁]/(t₂ − t₁). These are differences of observed values, not fits.
- The item 24 split-half slopes of ln C on time, with their ratio R and statistic z (item 24, step 3). For IV data this replaces the A0.7 split-half cut-offs 1.25/0.80 with R ≥ 1.5 and |z| ≥ 2. EV post-peak descriptions use A0.7 without the z threshold.
- Dose-normalized concentration ratios at matched times (DIS-2) and the reused T3/T3p statistics.
- Ratios of tissue to reference at matched times, and the DIS-4b and DIS-4c log differences d with their z (item 26).
- Observed-window AUC ratios (D0.6), including the late-area share AUC(cut,b)/AUC(a,b) of item 24.
- D/C(t) bounds (item 25) and tissue amounts L·W (D3).
- Residual-blood corrected values (item 26), as sensitivity only.

No other fitting, smoothing, back-extrapolation to C0, AUMC, MRT, Vss, Vz or Kp at infinity is computed in EDA.

#### D0.8 Matrix, basis and supporting-quantity fields

Matrix fields (on the data card, one per series)
- `matrix`: PLASMA, SERUM, WHOLE_BLOOD, TISSUE_HOMOGENATE, ISF_MICRODIALYSIS, ELF, CELLS (for example alveolar macrophages), CSF, OTHER_FLUID, UNKNOWN.
- `basis`: TOTAL, UNBOUND, UNKNOWN. A series with basis UNKNOWN is displayed only.
- `perfused`: YES, NO, NOT_REPORTED (homogenates).
- `residual_blood_corrected`: YES (with method), NO, NOT_REPORTED.
- `homogenate_dilution` and `value_basis` (per g tissue, per mL homogenate, per organ).
- `recovery_calibrated` (microdialysis): YES (method), NO.
- `elf_correction` (ELF): UREA (with dwell time), NONE, NOT_REPORTED.
- `pairing`: SAME_ANIMAL, DIFFERENT_ANIMALS, NOT_REPORTED. `cross_time_identity`: SERIAL, DESTRUCTIVE, UNKNOWN.
- `sampling_site` (systemic series): ARTERIAL, VENOUS (with vessel), CARDIAC, MIXED, NOT_REPORTED; whether the site is the injection site or the same limb. SAMPLING_SITE_EARLY is set on items 24 and 25 when the site is venous, mixed, unreported or near the injection site and the reading or bound depends on samples in the first minutes.

Supporting quantities
- Blood-to-plasma ratio B:P with source; haematocrit with source.
- fu,p and fu,T with species, method, concentration tested and source (item 27).
- Organ weights with source (D3).

Flags
- MATRIX_UNKNOWN: matrix or basis cannot be determined. Display only.
- ELF_DILUTION_UNCORRECTED: ELF concentrations without urea correction. No ratio or Kpuu conclusion.
- MICRODIALYSIS_UNCALIBRATED: microdialysate without recovery calibration. Not used quantitatively.
- Macrophage lysis and long lavage dwell time are recorded as known biases of ELF values. Lysis releases cell-associated drug and raises the apparent ELF concentration. Urea diffuses into the lavage fluid during dwell, so the urea-derived ELF volume rises and the derived ELF drug concentration falls (Marcy et al. 1987; the direction is inferred from the abstract). Short-dwell microlavage gives smaller ELF volumes than conventional lavage (Baldwin et al. 1991). Neither bias is corrected in EDA. Single-time ELF/plasma ratios follow the same timing caution as item 26.

Matrix-specific reading limits
- A tissue/plasma ratio in µg/g over µg/mL has units mL/g. Treating it as dimensionless assumes a tissue density of 1 g/mL; state this when ratios from different value bases are compared.
- CSF is not brain interstitial fluid. A CSF/plasma ratio describes CSF; it is reported as such and not as brain exposure.
- Cell-associated concentrations (for example alveolar macrophages) depend on the method used to estimate cell volume; record it with the value.

Analyte
- Parent, metabolite and total radioactivity are read separately. Total radioactivity is never read as parent distribution.

Target binding (r1.2)
- `target_binding_declared`: YES (with the source quote that states high-affinity binding to a pharmacological target) or NOT_STATED (default). With NOT_STATED, target-mediated disposition is not read from the curves, is not listed as a candidate, and TARGET_BINDING_PATTERN is not reported. Curve shape alone never sets YES.

#### D0.9 Hand-off to modeling

A0.9 applies unchanged. The candidate list is shared across absorption, distribution, metabolism and elimination. Distribution adds the following fields.
- Excluded combinations from T6, T7, T8 and T9, written in full, with margin, witness points and basis of judgement.
- Bounds and ratios: the initial-volume bound with its time and population meaning (item 25); the plateau ratio with the statement "steady-state Kp ≤ plateau ratio" and, for a non-eliminating tissue after a first dose, the bracket "window AUC ratio ≤ Kp ≤ plateau ratio" (item 26); observed-window AUC ratios; Kpuu where eligible (item 27).
- Information content: whether the first IV sample is early enough to inform Vc; whether both fast and slow phases have enough points to inform Q and Vp; whether sampling and LLOQ cover the slowest phase seen. Weak information and structural non-identifiability are written separately.
- `post_distribution_from_h` for item 18 and for modeling's initial estimates.
- Candidates that depend on later sections (saturable elimination, nonlinear binding, enterohepatic recycling, and target-mediated disposition only when `target_binding_declared` = YES) are marked "pending DME".
- APOD model search. The board orders candidate structures; it does not choose one. Candidates use the rank groups of s1.0 S5 with fixed required units. Only a formal result removes a candidate: a T6 exclusion removes linear one-compartment disposition for that unit and window; a formal T7 contradiction removes "add linear reversible compartments" as the explanation of the steepening, which is passed on as a candidate for nonlinear elimination or binding. Every other reading (split-half, interval rates, dose overlays, SENSITIVITY_ONLY, LOW_POWER, EV descriptions) changes only the order and the evidence shown. A sensitivity-level contradiction keeps the candidate in its group; the order of two candidates changes only when the same observation distinguishes them and supports the other one (decision D, s1.0 S5). A T6 failure alone does not put two compartments ahead of one. Each removal records test, unit, window and margin. When group-mean bends are reported, give the number of animals showing the bend among the individually sampled animals.
- Conclusion for Modeling: the simplest plausible structure, the source series and times behind it, the main limitation and the observation or comparison that could change it. Compare compartment candidates on the same eligible records, dose histories and error and censoring models; inspect residuals in the time region that motivated a more complex model. Compare species before imposing shared parameters in a joint model.

#### D0.10 Exclusion tests T6–T9

T6–T9 continue the absorption numbering. At first use, name the comparison and its units. T6 is a single-line feasibility test on ln C, T7 a log-convexity witness on ln C, T8 a constant tissue/reference ratio in a window (dimensionless), and T9 a non-decreasing concentration at a later dose (concentration units). Apply s1.0 S10 to any numerical contradiction.

T6. One-compartment single line
- Combination: linear, time-invariant one-compartment disposition; central IV bolus, or the period after a completed central infusion; zero initial state; central parent observation.
- Result: ln C(t) = a − λt for one a and one λ > 0 over the whole post-dose window.
- Criterion: no line with λ > 0 passes through every interval [ln Lᵢ, ln Uᵢ] at admissible times [tᵢ⁻, tᵢ⁺]. This is a linear feasibility problem. Report the smallest common widening on the log scale that would restore feasibility as the margin, with the witness points. For three definitely ordered times a < b < c and w = (c − b)/(c − a), the witness is either ln L_b > w ln U_a + (1 − w) ln U_c (the middle point lies above every admissible line) or ln U_b < w ln L_a + (1 − w) ln L_c (below every line).
- Analysis unit: serial individual profiles. A geometric mean of a fixed cohort qualifies only with an SD or SE on the ln C scale (or a convertible interval) (s1.0 S1): for one-compartment animals, mean ln C is a − λ̄t, a straight line. An arithmetic or unstated mean, of fixed or destructive cohorts, gives no single-line exclusion, because a mixture of single exponentials is curved; it is read descriptively. Destructive cohorts qualify only with a common population and intervals that cover the sampling error of mean ln C at every searched time. A changing n alone is not a veto.

T7. Log-convexity of a positive exponential sum
- Combination: linear, time-invariant, reversible mammillary disposition; central input that has ended (bolus, or any completed non-negative central infusion); zero initial state; central parent observation.
- Result: C(t) = Σ aⱼ e^(−λⱼ t′) with aⱼ > 0, λⱼ > 0 and t′ the time after input ends. ln C is convex: on a semilog plot the decline never becomes steeper.
- Criterion: for definitely ordered times a < b < c, M_T7 = ln L_b − [w ln U_a + (1 − w) ln U_c], with w = (c − b)/(c − a). M_T7 > 0 is a numerical contradiction. When times are uncertain, take the smallest margin over all admissible ordered times [tᵢ⁻, tᵢ⁺]. Scan every eligible ordered triple in the prespecified window. Report the window, the number of triples, the largest margin and the witness times. Apply A0.3 for joint uncertainty and leave-one-out.
- Analysis unit: serial individual profiles; arithmetic means of a fixed set of animals (a mixture of positive exponential sums is again one); geometric means of a fixed set of animals (a mean of convex functions is convex); destructive cohorts with a common population and intervals covering sampling error.
- Proof sketch: the A0.10 T1 proof gives central impulse response h(t) = Σ aⱼ e^(−λⱼ t) with aⱼ ≥ 0 for a reversible mammillary model. After any non-negative input u that ends at T, C(T + t′) = Σ [∫ u(s) aⱼ e^(−λⱼ (T − s)) ds] e^(−λⱼ t′), and each bracket is non-negative. The log of a sum of exponentials with positive weights is convex (log-sum-exp).
- Not covered: a non-reversible structure (enterohepatic recycling, reabsorption loops), nonlinear or time-varying disposition, a nonzero baseline, peripheral or metabolite observation, or points taken during input.

T8. Constant tissue/reference ratio in a window
- Combination: linear, time-invariant disposition; no input during the window; tissue and reference both in the terminal phase of the same slowest exponential throughout the window. Under this combination r(t) = C_T(t)/C_ref(t) is constant in the window.
- This is the formal version of the statement "the observed plasma terminal phase is the true terminal phase" for that tissue. It does not test a compartment structure.
- Criterion (item 26, DIS-4b): a prespecified pair of times, normally the last and the third-last common quantified times. d = ln r(t_late) − ln r(t_early), with its standard error and degrees of freedom (item 26, step 10). Contradiction: |z| ≥ z_crit (item 26, step 10) and e^d outside the band [0.80, 1.25] ([0.72, 1.38] for digitized data). This is a statistical judgement with an error rate of about 2 % per direction (1.5–2.7 % in the r1.1 check of group summaries with n 3–6 and CV 0.15–0.5). Report d, its SE, df, z, z_crit, the band and the times.
- Requires a supported uncertainty. Without SD and n, or individual values, T8 is CANNOT_ASSESS and the reading is descriptive (SENSITIVITY_ONLY).

T9. Later dose not below first dose
- Combination: linear, time-invariant disposition; identical, non-negative dose-by-dose input; zero initial state before the first dose.
- Result: at the same time after dose, C_later(t) ≥ C_first(t) in every matrix, because the later profile is the first-dose profile plus the residual of earlier doses. This is the matched-time form of the absorption item 23 AUCτ check.
- Criterion: M_T9 = L_first − U_later > 0 at a matched post-dose time. For statistical intervals, the accumulation ratio AR = C_later/C_first has its CI below 1. Apply A0.3.
- A contradiction in plasma routes to absorption item 23 (TIME_DEPENDENCE_SUSPECTED). A contradiction in tissue alone is reported in item 26 with candidates (time-dependent uptake, tissue injury, data issue).

Reused absorption tests
- T3 and T3p (dose-normalized superposition) for two or more IV doses in DIS-2. The premises of A0.10 apply, with the IV dosing record replacing the EV input. T3p on IV group means at exact shared post-input times is one shared result with dose pair, matched times, family, status and limits (s1.0 S7).
- T5 (one positive scale factor across conditions) for condition overlays in item 28.

#### D0.11 Data card, figure set and answer status

Data card (one per dataset, before any figure)
- The A0.11 fields. Also the D0.8 matrix fields, IV mode (bolus, infusion with start and end, unknown), sampling site, and whether tissue and reference come from the same animal.
- A missing field is shown as "not reported" and becomes the "missing" entry of the questions that need it.

Figure set (DIS-1 to DIS-6)
- Every figure follows s1.0 S13: standard title, the question as subtitle, the reading as a caption of at most two plain sentences. Early/late halves, T6/T7 witness triples and their bounds are not drawn (S13.3, S13.9); those readings are caption sentences and table rows. The Vc bounds are a table (S13.8). Pages use the figure labels of the r1.5b guide; the panel names below are the code keys:

| Guide label | Code key | Content |
|---|---|---|
| DIS-1a | DIS1a | observed concentration–time, linear and semilog |
| DIS-1b | DIS1a | semilog view of the same observations; dose series as raw overlay (key DIS2) |
| DIS-1c | DIS1a | interval decline rate between adjacent quantified samples |
| Table 2 support | DIS1b | profile shape, decisive samples, interval rates, omission results, IV reference window |
| DIS-2a | DIS2, DIS6a | log C/D by dose or matched conditions |
| DIS-2b | DIS2 | log (C/D) high over reference at common times |
| DIS-3a / 3b / 3c | DIS4a / DIS4b / DIS4c | tissue and reference; tissue/reference ratio; later/first ratio |
| DIS-4a / 4b | DIS5a / DIS5b | fu,p against total concentration; unbound tissue/plasma ratio |
| DIS-5 | DIS6b | one reported parameter per panel |
| Table 3 | DIS3 | Vc bounds and reported volumes (optional figure off by default) |
| optional | DIS4d, DIS4e | organ contributions to recovered parent; tissue against reference inset |
| supplementary | DIS1animal, DIS1ind | per-subject figures | A panel whose conditions are not met is not drawn empty; one line gives the reason. Tiers follow A0.11: a test whose data premise holds is run and reported in its question row even when its layer is hidden.

| Figure | Panel | Tier | Drawn when | Items | Annotations on this panel |
|---|---|---|---|---|---|
| DIS-1 IV disposition (keys) | DIS-1a linear and semilog concentration–time with an early close-up | 1 | every IV curve; EV post-peak as description | 24 | Dose time and infusion end; first and last quantified points; LLOQ line; BLQ as open symbols at LLOQ; record level; low-confidence digitized points as open markers; early and late halves marked; no fitted line |
| | DIS-1b chord-slope table and split-half reading | 1 | ≥ 5 quantified post-dose points | 24 | Chord slopes; R, z, σ used; reading; robustness rows; `post_distribution_from_h` as a vertical line; the late-area share as a value row when two or more phases are visible |
| | DIS-1c T6/T7 layer | 2 | trigger: curvature visible in DIS-1a; data: T6 or T7 premises hold | 24 | Witness triple with [L, U], margin, analysis unit, label |
| DIS-2 IV doses | DIS-2a dose-normalized overlay, semilog | 1 | two or more IV doses in item 24 scope | 24 | Doses in one ordered single-hue ramp; common times marked |
| | DIS-2b ratio of dose-normalized concentrations (higher/lower) by time | 1; T3p tier 2 | common sampling times | 24 | Band [0.80, 1.25] shaded; T3p CIs and Holm results when the data exist; otherwise "description, not a test" |
| DIS-3 Volume bound | per group: D/C(t) as a downward arrow, L/kg | 1 | item 25 eligible | 25, 28 | Time of the sample; population meaning (individual / harmonic-mean bound); sourced plasma, extracellular and total-water reference lines; source-reported Vss, Vc, Vz, V/F with distinct markers labelled "source-reported" |
| DIS-4 Tissue | DIS-4a tissue and reference, semilog, native units | 1 | measured tissue | 26 | Matrix and basis in the legend; same-animal pairs marked; BLQ marks; D3 status |
| | DIS-4b ratio by time | 1; T8 layer tier 2 | ≥ 3 common quantified times with a usable reference | 26 | Estimator (MEAN_OF_RATIOS / RATIO_OF_MEANS); last three points bold; band shaded; d, SE, df, z, z_crit and reading; residual-blood sensitivity range when unperfused |
| | DIS-4c accumulation, first versus later dose | 1; T9 layer tier 2 | repeat-dose tissue and reference at matched post-dose times | 26 | AR for tissue and reference on a log axis with a line at 1; d, df, z and z_crit |
| | DIS-4d D3 stacked bar, % of dose | 1 | every tissue dataset with organ weights | 26 | Lower-bound amount per organ; line at 100 %; DATA_ISSUE label |
| | DIS-4e phase plot, tissue against reference, joined in time order | 3 | ≥ 3 common times; serial animals or a common population | 26 | Arrows in time order; loop direction stated; description only |
| DIS-5 Binding | DIS-5a fu,p against total concentration | 1 when ≥ 2 comparable concentrations; otherwise a table row | binding records | 27 | Species, method, matrix as separate series; observed PK concentration range shaded |
| | DIS-5b unbound ratio (Kpuu) | 2 | item 27 eligibility | 27 | Window; estimator; band [0.5, 2] |
| DIS-6 Conditions and species | DIS-6a condition overlay, dose-normalized, semilog | 2 | item 28 scope | 28 | Every differing attribute listed; T5 c intervals (absorption E2) |
| | DIS-6b species table and DIS-3 across species | 1 | project level | 28 | Vss/fu,p where eligible; missing cells named |
| DIS-R Reported parameters | one panel per reported distribution parameter | 1 when a dataset has parameters only; otherwise 3 | D0.12 | 25, 27, 28 | Definition, method, source, n, uncertainty |

- Individual layer: as A0.11. With individual records, DIS-1a and DIS-4a draw one thin line per animal and a bold mean. Without verified serial identity, points only.

Reading map (r1.2): what each panel is for. "Look at" is what the reviewer checks on the panel; "reading" is the descriptive or test result; "hypothesis handed over" is what goes to D0.9. Readings without a test stay descriptions (D0.3).

| Panel | Look at | Reading | Hypothesis handed over |
|---|---|---|---|
| DIS-1a | Does the semilog decline flatten, stay straight or steepen; time of the first sample; last point against LLOQ | FLATTENING / NONE_DETECTED / STEEPENING | Two or more phases (multi-compartment candidate); one phase after the first sample (earlier sampling decides); nonlinear elimination or recycling candidate (only after T7) |
| DIS-1b | R, z and whether the reading survives dropping the first, last or low-confidence points | ROBUST or the point it depends on; `post_distribution_from_h`; the late-area share of the window | Where item 18's IV terminal window may start; whether a compartment rests on one point; how the window area divides between the parts before and after the cut |
| DIS-1c | Witness triple: middle point above every admissible line (T6) or above the chord (T7) | EXCLUDED_UNDER_STATED_ASSUMPTIONS / NOT_EXCLUDED / CANNOT_ASSESS | One compartment excluded; linear mammillary disposition with completed input excluded |
| DIS-2a, DIS-2b | Do dose-normalized curves superimpose; how the higher/lower ratio moves with time | RATIO_WITHIN_BAND / RATIO_CONSTANT_OUTSIDE_BAND / RATIO_RISES_LATE_ABOVE_BAND / RATIO_BELOW_BAND / RATIO_ABOVE_BAND_EARLY_THEN_FALLS / RATIO_MIXED / DESCRIPTIVE_CONFOUNDED | No candidate is generated from the label (s1.0 S7); what to check is listed in item 24 step 10 |
| DIS-3 | Arrow D/C(t) against plasma, extracellular and total-water lines | Vc ≤ X; VOLUME_BELOW_PLASMA; LOOSE_BOUND | Upper limit for the initial Vc; initial confinement hint; dose, unit or timing error |
| DIS-4a | Tissue peak later than plasma; late declines parallel | Sampled peak, persistence | Slow equilibration; tissue moving with plasma |
| DIS-4b | Ratio flat, rising or falling over the last three common times | NO_DIFFERENCE_SEEN / RISING / TISSUE_NOT_FALLING / FALLING | Kp ≤ plateau ratio (and window AUC ratio ≤ Kp); slow tissue, plasma terminal phase not the true one (T8); uptake or binding; tissue elimination or efflux |
| DIS-4c | Tissue accumulation ratio against plasma at the same post-dose time | TISSUE_ACCUMULATES_MORE / NO_DIFFERENCE_SEEN / LESS; T9 | Slow tissue; time dependence in plasma (absorption item 23) or tissue |
| DIS-4d | Lower-bound tissue amounts against the dose | PASS / DATA_ISSUE / SENSITIVITY_ONLY | Dilution, value basis, units or dose basis error |
| DIS-4e | Loop direction when tissue is plotted against plasma in time order | Counter-clockwise loop / no loop | Delayed tissue equilibration (description) |
| DIS-5a | fu,p across total concentration, by method | STABLE / CHANGING / NOT_ASSESSABLE | Constant-fraction unbound conversion; nonlinear binding |
| DIS-5b | Unbound ratio against [0.5, 2] | INSIDE / ABOVE / BELOW / UNRESOLVED | Passive equilibrium; uptake (or pH partitioning, lysosomal trapping); efflux or tissue elimination |
| DIS-6a | Can one scale factor carry one condition onto the other (T5) | NOT_EXCLUDED / EXCLUDED | Shape change with the condition: covariate candidate |
| DIS-6b | Vss and Vss/fu,p across species | Contrast shrinks / remains | Plasma binding explains the contrast; tissue binding or transport hypothesis |

Page structure and answer status
- Pages print the r1.5b guide numbers. Engine rows map to guide questions: row 1 → Q1; row 4 → Q2 (also shows Q4); row 5 → Q6 (also shows Q5 and Q7); row 6 → Q8; rows 2, 3 and 7 are unnumbered ("Vc bound", "IV and EV routes", "Across species", the last also showing Q4 and Q9). Guide Q3 has no row: its answer is the `iv_reference_window` record. Each board records this in `guide_coverage`. Rows carry `qid`, `guide_q`, `also_guide_q`, `legacy_q`, `display_ref` and `legacy_display_number`; `q` stays the engine row id. Page order: rows 1, 4, 5, 6, 2, 3, 7.
- The engine rows are the r1.3 rows below (`q`); the status rules below refer to them.
- Entry: species → study, as A0.11. Inside a study the main view is the question rows. Engine row 7 is one project-level row.
- Each row shows the status, one conclusion sentence, the single most explanatory evidence, and what is missing. The conclusion sentence follows A0.11: what was observed, which points or test it rests on, and how far it reaches given the record level.
- Required rows come first and are always shown: Q1, Q4, Q6 and Q7. Q2, Q3 and Q5 are shown when they apply. A skipped row takes its status in structured output and needs no empty panel.

| Engine row (q) | Question | Items | Primary evidence (default) | Other panels |
|---|---|---|---|---|
| 1 | Which decline phases can be seen after IV dosing? | 24 | DIS-1a with the halves marked; DIS-1c when T6 or T7 excluded or deferred a combination | DIS-1b |
| 2 | What bounds the initial central volume? | 25 | DIS-3 | DIS-R |
| 3 | Could input hide a fast phase? | 24, absorption 18 | Absorption D1 with DISTRIBUTION_MASKED | DIS-1a |
| 4 | Which measurements support the shape, and could dose, baseline, analyte or averaging explain it? | 24 | DIS-2b when two doses exist; otherwise DIS-1b robustness rows | DIS-2a, individual layer |
| 5 | Which tissue was sampled, when, and does the measured amount fit the dose? | 26 | DIS-4a; DIS-4d when D3 flags | — |
| 6 | What unbound and relative exposure can be established? | 26, 27 | Plasma: the binding row or DIS-5a. Tissue: DIS-4b, or DIS-4c for repeat dosing | DIS-5b |
| 7 | What differences are supported across conditions and across the project's species? | 28 | DIS-6b; DIS-6a for within-species conditions | DIS-3 |

- ANSWERABLE, PARTLY_ANSWERABLE, NOT_ANSWERABLE_YET (shown as "Insufficient evidence") and NOT_APPLICABLE follow s1.0 S6 and A0.11. A directly reported measured concentration can fully answer a descriptive question (Q5).
- Q1 with group means only and no T7: at most PARTLY_ANSWERABLE. Q1 with ONE_APPARENT is answerable only together with the time of the first sample.
- Q6 is required in every study. When no binding or unbound measurement exists, the row is NOT_ANSWERABLE_YET with "plasma unbound exposure unknown" and the total-concentration result is kept.
- Q7 is always returned at project level. PARTLY_ANSWERABLE when a comparable subset exists; NOT_ANSWERABLE_YET when no comparable species pair exists yet.

#### D0.12 Reported-parameter path

- Applies when a source reports Vc, V1, Vss, Vz, Vβ, V/F, Q, Kp, fu or a tissue/plasma ratio without usable concentration points. Label REPORTED_PARAMETER. Each question it feeds is at most PARTLY_ANSWERABLE.
- Per value: definition (which volume, which model, NCA or compartmental, extrapolation), analyte, matrix, basis, dose route and mode, source location, n, uncertainty type (between-animal SD or model standard error), mean type.
- Volumes of different definitions are never pooled or averaged. Vz depends on λz and is not a distribution volume of any tissue. A V/F from EV data is not compared with an IV volume without F.
- A reported Kp states its time basis (single time, AUC ratio over a window, extrapolated). Only a ratio over a stated window is compared with DIS-4b; an extrapolated Kp is source context.

---

### 24 | IV DISPOSITION: DECLINE PHASES, DOSE AND ROUTE

Scope
- IV profiles with quantified points after the end of dosing (D0.2), plasma, serum or whole blood, parent analyte. EV profiles, including studies without an IV arm, are read as described under "EV profiles".
- Repeated occasions in one animal. When the source links animals across occasions (for example IV and EV periods of a crossover), the animal × occasion profile is the plotting and testing unit: each occasion is drawn and tested separately (T6, T7, split-half screen, volume bound), and the occasions of one animal are read together (a common panel or overlay per animal, and a table of each animal's per-occasion readings). State whether the readings agree within animals and whether a disagreement follows the occasion order, the dose or the washout. Pass the animal–occasion linkage to Modeling. Where the source does not establish the linkage, treat occasions as separate units and say so.
- The item describes the shape of the post-dose decline on the semilog plot and runs T6 and T7 when their premises hold. It does not count compartments and does not estimate C0, Vss, Vz or any rate constant.

Principle
- Linear disposition. After an IV bolus, or after any completed central infusion, plasma concentration in a linear reversible mammillary model is a sum of exponentials with positive coefficients. Its semilog decline is steepest first and flattens, never the reverse (T7). A straight decline is consistent with one phase over the sampled window; it does not show that only one compartment exists.
- Saturable elimination. For one compartment with Michaelis–Menten elimination, d ln C/dt = −Vmax/[V(Km + C)]. The log slope becomes steeper as concentration falls: flat first, then steep. When target binding is declared (D0.8), target-mediated disposition gives the same direction at low concentrations. Distribution plus saturable elimination can give steep, then flat, then steep.
- Group means. Averaging animals whose individual declines are straight produces an apparent flattening when elimination rate varies between animals. Identical clearance with different volumes also gives different individual rates (k = CL/V).
- What sampling can show. A distribution phase is visible only if it is still a large part of C(t₁) at the first sample. A slow late phase appears only if concentrations stay above the LLOQ long enough. A terminal slope is "the slowest phase seen above this LLOQ", not the elimination phase by default.
- Earliest samples. Incomplete mixing or timing error at the first sample can create an apparent fast phase. Arterial and venous concentrations can differ markedly early after an IV dose, and a sample drawn near the injection site reads high; record the sampling site.
- Target binding, only when `target_binding_declared` = YES (D0.8); otherwise this paragraph is not applied. For a drug with a high-affinity, limited-capacity target, the profile after an IV bolus has a rapid initial drop (binding to target), an apparently linear phase, a transition and a linear terminal phase. The initial drop is relatively larger at lower doses, the linear phase shifts upward with dose while its slope stays the same, and the transition moves later with higher dose (Peletier & Gabrielsson 2012). A single profile can therefore show FLATTENING that is not distribution. With two or more doses, an early drop whose dose-normalized size changes with dose separates target binding from linear distribution, which superimposes after dose normalization.

Data and details
- Time after the end of dosing (displayed after the start of dosing, s1.0 S13.1); dose, dose basis and units, the administered dose per animal when the input states it (s1.0 S11); IV mode and infusion duration; concentrations with data status and LLOQ; record level, n per time, SD and mean type; sampling site; digitization status and low-confidence points; predose value and dosing history; analyte.
- Two or more IV doses of the same drug, species, analyte and matrix for DIS-2.

Figures (D0.11)
- DIS-1a, DIS-1b and DIS-1c (guide labels, D0.11). DIS-2a and DIS-2b for two or more doses. No fitted lines on any panel. Split-half results, exclusions and deletion checks go in the Table 2 support table.

Assessment (host code computes; the model describes)
1. Points. Use quantified points after the end of dosing. At least 5 are needed for the split-half reading; otherwise `curvature` NOT_ASSESSABLE (TOO_FEW_POINTS). BLQ points are not used in the reading. T6 and T7 can run with 3 or more points.
2. Halves. Order the n points by time. Early half: the first ⌈n/2⌉ points. Late half: the last ⌈n/2⌉ points; they share the middle point when n is odd. For each half compute the descriptive least-squares slope of ln C on time, as positive decline rates b_e and b_l. If either is ≤ 0, `curvature` NOT_ASSESSABLE (NON_DECLINING_HALF).
3. Reading. R = b_e/b_l. Per-point noise σ on ln C is set per dataset before any test (D0.4); the tier-3 default is 0.15 for individual data and, for group means, √(0.05² + (SD/mean)²/n) when SD and n are reported (drop the 0.05 digitization term for tabulated values), otherwise 0.158. z = (b_e − b_l)/(σ√(u_e² + u_l²)), with u = 1/√Σ(t − t̄)² within each half. The shared middle point makes the halves weakly dependent; a z near the threshold with odd n is read as borderline.
   - R ≥ 1.5 and z ≥ 2 → FLATTENING.
   - R ≤ 1/1.5 and z ≤ −2 → STEEPENING.
   - Otherwise NONE_DETECTED.
4. Robustness. Repeat the reading without the first point, without the last point, and without all low-confidence digitized points. `curvature_support` = ROBUST when the reading holds in every repeat that still has 5 or more points. Otherwise list what it depends on: FIRST_POINT, LAST_POINT, LOW_CONFIDENCE_POINTS.
5. Descriptive output `phases_visible`.
   - FLATTENING and ROBUST → TWO_OR_MORE.
   - FLATTENING, not robust → TWO_OR_MORE_TENTATIVE.
   - NONE_DETECTED → ONE_APPARENT, always reported with `earliest_sample_h`. ONE_APPARENT is never written as "one compartment".
   - STEEPENING → NOT_LOG_CONVEX_DESCRIPTIVE. Run T7 (step 6) before any exclusion is stated.
   - Caveats on FLATTENING: GROUP_MEAN_CURVATURE_POSSIBLE (group means with R < 1.6); LLOQ_PROXIMAL (the reading depends on the last point and that point is below 3 × LLOQ, or LLOQ not reported); EARLY_MIXING_POSSIBLE (the reading depends on the first point and that point is within 5 minutes after the end of dosing, the bound included).
   - Precedence: NOT_ASSESSABLE > NOT_LOG_CONVEX_DESCRIPTIVE > TWO_OR_MORE > TWO_OR_MORE_TENTATIVE > ONE_APPARENT.
6. Formal tests (D0.10), run whenever their premises hold, independently of the reading.
   - T7 on the full post-dose window. A contradiction that passes A0.3 → "linear reversible mammillary disposition + completed central input + zero baseline + central observation" EXCLUDED_UNDER_STATED_ASSUMPTIONS. Candidates, unranked and pending DME: saturable elimination, nonlinear binding, target-mediated disposition (only when declared), enterohepatic recycling (with a rebound), mistimed infusion end, unrecorded input, data issue.
   - T6 when the analysis unit qualifies. A contradiction that passes A0.3 → "linear one-compartment + completed central input + zero baseline + central observation" EXCLUDED_UNDER_STATED_ASSUMPTIONS. For an arithmetic or unstated group mean T6 gives no single-line exclusion (D0.10); record "T6 not applicable to arithmetic means".
   - Order of the formal decision: s1.0 S10. Removal set: every eligible observation is removed in turn; the full T6 calculation is repeated, and all T7 triples are rescanned, on the rest (decision C). A rerun needs three qualified distinct time points; otherwise LOO_NOT_ASSESSABLE. A formal CANNOT_ASSESS keeps the removal flags in `t6_sensitivity_flags` / `t7_sensitivity_flags`.
   - Prior-dose residue. When a predose value is quantified, or a prior dose is not followed by a documented washout, a T6 exclusion is SENSITIVITY_ONLY unless the residue is explicitly accounted for (s1.0 S10); T7 is unaffected because a positive sum of decaying exponentials stays log-convex. Carry the baseline or dosing history into Modeling.
   - If a decisive time is uncertain, the formal conclusion stands only if the contradiction survives the supported timing range (s1.0 S3).
   - Report each test's window, number of searched triples or the feasibility margin, witness points and leave-one-out result.
7. Start of the post-distribution part. After an observed slowing, the candidate start (`post_distribution_from_h`) is the earliest remaining sampled time for which at least five remaining points read NONE_DETECTED. A suffix counts only if the screen could have detected the threshold change: with b_l the later-half decline rate, require 2σ√(u_e² + u_l²) ≤ 0.5 b_l (the change that corresponds to R = 1.5 at z = 2). A suffix that fails this check is LOW_POWER and is not a candidate start. If no eligible suffix exists, record NOT_DETERMINED with the reason (TOO_FEW_POINTS, LOW_POWER, SLOWING_IN_EVERY_SUFFIX). When one phase is apparent throughout, the earliest measured time is a candidate subject to early coverage and the same power check. The window is written once as the shared record `iv_post_distribution_window` (s1.0 shared records): quantified samples after the end of input, on the clock "time after the end of dosing", with start and end time, sample ids, the slope refitted on those samples, and the reason when it cannot be determined. Absorption reads the same record and owns the final IV terminal window, the IV/EV comparison and the flip-flop reading.
   - Late-area share (r1.3). `late_area_share` = observed AUC(cut,b)/AUC(a,b) as a percentage, with cut = `post_distribution_from_h`, both areas by D0.6 on the same points, and the window [a,b] stated. It is reported only when `phases_visible` is TWO_OR_MORE or TWO_OR_MORE_TENTATIVE: with ONE_APPARENT the cut equals the first sample and the share is 100 % by construction. It is a value row under DIS-1b, without a plot and without a threshold.
   - Reading: "X % of the window area lies after the cut" means exactly that. It does not establish how much of the total exposure is terminal, and it is not compared between profiles with different windows.
8. Checks before reading a bend as distribution. Before naming peripheral exchange, record each as checked, not applicable or not possible, and name a remaining alternative beside the candidate: concentrations near the LLOQ where assay bias or selective censoring flattens the tail; enterohepatic recirculation or secondary peaks; a metabolite or nonspecific assay signal; a change of matrix or sampling site late in the profile; early mixing and sampling site; change of cohort composition across times; predose signal and prior dose; endogenous baseline (gate D0.2); parent and metabolite read separately; when target binding is declared, free ligand, target and complex where measured.

DIS-2: two or more IV doses
9. Comparability: at least two source-defined IV dose levels with matching route, input mode and duration, analyte, matrix, dose basis, assay and population. Record each group's planned level and normalise by the actual delivered dose on a consistent basis where available; differences in recorded mg/kg within one planned group are individual dosing variation. If dose and study or individual are confounded, the pattern is DESCRIPTIVE_CONFOUNDED: the contrast and the reason only, no `dose_nonlinear` and no Elimination mechanism nomination (s1.0 S7). Reuse the Absorption dose comparison and its figures for the same IV contrast when available.
10. At each common time, ratio = dose-normalized concentration at the higher dose over the reference dose. Band [0.80, 1.25] ([0.72, 1.38] for digitized data), a project setting for a dimensionless fold comparison. The label names the observable shape of the ratio (s1.0 S7): RATIO_WITHIN_BAND, RATIO_CONSTANT_OUTSIDE_BAND, RATIO_RISES_LATE_ABOVE_BAND, RATIO_BELOW_BAND, RATIO_ABOVE_BAND_EARLY_THEN_FALLS, RATIO_MIXED. No candidate is generated from a label. What to check:
    - Overlap of the normalized profiles is compatible with linear disposition in that window, even if each profile has visible curvature.
    - Late separation or a time-varying ratio prompts review of dose-dependent disposition, including saturation where applicable; one dose rarely shows saturable elimination, so this overrides a single-profile NONE_DETECTED as a prompt for review.
    - An early separation or a nearly constant offset needs review of dose basis, units, assay, input and sampling before attributing it to binding or distribution. A ratio below the band prompts a check of plasma binding when total concentration is measured (DIS-5a).
    - Target-mediated disposition is considered only when `target_binding_declared` = YES (D0.8).
11. Formal proportionality: T3 (observed-window AUC) and T3p (matched times) under their A0.10 premises, including T3p on IV group means at exact shared post-input times (D0.10). Report them separately from the descriptive pattern.

EV/IV link
12. When IV is multi-exponential and the EV post-peak decline looks mono-exponential, absorption item 18 sets DISTRIBUTION_MASKED. Item 24 adds one sentence: with EV data only, the fast phase and Vc cannot be assessed. A long infusion can also mask the fast phase.
13. EV profiles. Input continues throughout an EV profile, so the completed-input premise of T6 and T7 does not hold and both are CANNOT_ASSESS. Show DIS-1a and, when useful, DIS-1c for the post-peak decline. The post-peak shape follows Absorption A0.7: a slope ratio only when both segments decline and the early slope differs from zero; the z threshold of the IV screen is not used. Label every reading "absorption and distribution not separable". When the post-peak decline rate is close to an absorption-rate estimate or slower than an available IV terminal rate, flag possible flip-flop and link to Absorption item 18. The Vc/F bound follows item 25 (table only). With an IV arm, the IV reading carries the disposition conclusion; the EV reading is supporting description. Distribution passes the same subject's IV window as `iv_reference_window` {iv_sid, from_h, to_h, b_late_iv_per_h} and carries no flip-flop reading or flag; Absorption owns the thresholds (decision B, s1.0 S9).

Output per IV profile
`curvature` (FLATTENING / STEEPENING / NONE_DETECTED / NOT_ASSESSABLE), `curvature_support`, `phases_visible`, `slope_ratio`, `z`, `sigma_used`, `robustness_rows`, `chord_slopes`, `earliest_sample_h`, `post_distribution_from_h`, `post_distribution_reason`, `iv_post_distribution_window`, `noise_tier`, `tier_label`, `late_area_share`, `last_quantified_over_lloq`, `t6_label`, `t6_margin`, `t6_points`, `t7_label`, `t7_margin`, `t7_points`, `analysis_unit` (INDIVIDUAL / GEOMETRIC_MEAN_FIXED / ARITHMETIC_MEAN_FIXED / DESTRUCTIVE), `dose_pattern` (DOSE_PARALLEL / SATURABLE_ELIMINATION_SUSPECTED / TARGET_BINDING_PATTERN (declared only) / HIGHER_DOSE_LOWER / DOSE_OFFSET_CONSTANT / MIXED_DOSE_PATTERN / NOT_APPLICABLE), `t3_result`, `t3p_result`, `checks_done`, `candidates`, `caveats` (GROUP_MEAN_CURVATURE_POSSIBLE, LLOQ_PROXIMAL, EARLY_MIXING_POSSIBLE, SAMPLING_SITE_EARLY, INFUSION_TIMING_UNKNOWN, CONFOUNDED, DIGITIZED, GROUP_MEAN, DESTRUCTIVE_SAMPLING), `not_assessable_reason`.

Hand-off
- TWO_OR_MORE: a multi-compartment candidate is supported by the shape; the T6 result says whether one compartment was formally excluded. TWO_OR_MORE_TENTATIVE: modeling should not add a compartment on these data alone. ONE_APPARENT: one phase within the window after `earliest_sample_h`; earlier sampling is the discriminating data.
- A T7 exclusion moves the nonlinear and recycling candidates to the front of the "pending DME" list without ranking them.
- NONE_DETECTED from one dose does not show linear elimination; DIS-2 or T3 needs two or more doses.

Purpose, limits, and main-objective link
Tells modeling how many disposition phases the data can support, which simple combinations are formally excluded, and from which time an IV terminal slope may be read. A FLATTENING reading is consistent with multi-compartment distribution; it does not prove it.

Keywords: multi-exponential decline; distribution phase; log-convexity; single-line feasibility; semilog curvature; saturable elimination; group-mean artefact; LLOQ and terminal phase; incomplete mixing; dose-normalized overlay.
MP basis: EDA004; T05 (does sampling cover the distribution phase); figure list B1.
Sources: Gabrielsson, Meibohm & Weiner 2016 AAPS J 18:47, Fig. 4 and 6–8; Chiou 1979 J Pharmacokinet Biopharm 7:527 (doi 10.1007/BF01062393; abstract read); Wagner 1973 J Pharmacokinet Biopharm 1:103 (doi 10.1007/BF01059625; abstract read); Schentag & Jusko 1977 Clin Pharmacol Ther 22:364 (doi 10.1002/cpt1977223364; abstract read); Mager & Jusko 2001 J Pharmacokinet Pharmacodyn 28:507 (title and venue only); Peletier & Gabrielsson 2012 J Pharmacokinet Pharmacodyn 39:429, doi 10.1007/s10928-012-9260-6 (TMDD phases; read in part); arterial–venous sampling-site differences early after IV dosing (verapamil in rats and later reviews; titles only). Log-convexity of positive exponential sums, the geometric-mean argument for T6 and the Michaelis–Menten log slope are derived, not cited.

---

### 25 | IV DISPOSITION: INITIAL CENTRAL-VOLUME BOUND

Scope
- Known central IV bolus, or a completed infusion with a qualified end-of-infusion sample. Zero initial drug in the body. Adequate mixing at the sample time. A representative central parent sample. EV data: NOT_APPLICABLE.

Principle
- Under these premises the drug amount in the central compartment at a post-dose time t cannot exceed the amount delivered by t. So Vc × C(t) ≤ D(t) and Vc ≤ D(t)/C(t) for every valid sample. The tightest bound comes from the highest valid concentration, normally the first sample after a bolus.
- Lower check. Drug in the body includes at least the drug in plasma, so D(t) ≥ C(t) × V_plasma whenever mixing is complete and the sample is plasma or serum (for whole blood, use blood volume). A bound D/C(t) below a sourced lower value for the species' plasma volume contradicts the premises: dose, units, timing, mixing or sampling site.
- Group means. With a group arithmetic mean C̄(t) of animals given the same dose per kg, D/C̄(t) bounds the harmonic mean of the individual Vc, not each animal's Vc. The harmonic mean is never larger than the arithmetic mean.

Data and details
- Dose amount and basis (labelled or delivered), body weight and units; bolus time or infusion start and end; time of each sample after the end of dosing; concentration with data status and allowed interval; sampling site; record level.
- Sourced species reference volumes for plasma, extracellular fluid and total body water, with source (display only, except the plasma lower check).
- Source-reported Vc, Vss, Vz and V/F (D0.12), displayed separately.

Figures (D0.11)
- Table 3: value in L/kg, sample time, data level, reference volumes and source-reported volumes (s1.0 S13.8); the DIS3 figure is optional and off by default (`optional_figures.DIS3`).

Assessment
1. Eligibility: IV mode known; zero baseline (absorption item 21) or a residue flagged as in step 2a; sample after the end of dosing; matrix plasma, serum or whole blood stated. Otherwise NOT_ASSESSABLE with the reason. Infusion: use the amount actually delivered and label the bound "end of infusion".
2. Point bound: Vc ≤ D/C over every quantified sample after input ends; `vc_upper_bound_l_per_kg` uses the highest of them, with its time. When the earliest sample is not the highest, the earliest-sample bound is reported beside it (`earliest_sample_bound_l_per_kg`, `earliest_sample_time_h`); a later highest point is checked for source timing, input, mixing and sampling before it is qualified. EV profiles give a Vc/F bound on the same rule (Vc/F ≤ D/C(t)), table only.
2a. Modeling constraint (`modeling_constraint`): Vc ≤ D_upper / max_i L_i, with L_i the lower concentration limits of the candidate samples covered together (family m = number of candidate samples, s1.0 S4) at the precision admitted by s1.0 S8, and D_upper the supported upper delivered dose (source field `dose_upper_mg_per_kg`, at least the nominal dose). Status FORMAL needs source precision, a supported upper dose, no unresolved residue and a limiting sample outside the mixing window; otherwise SENSITIVITY_ONLY with the reasons. Unresolved mixing or predose residue does not withhold the bound: the limit is kept with RESIDUE_UNRESOLVED or EARLY_MIXING_POSSIBLE and the constraint is SENSITIVITY_ONLY. An endogenous compound gives no bound.
3. Plasma-volume check: if D_upper/C_lower(t) is below the sourced lower value of plasma volume → VOLUME_BELOW_PLASMA, a data check (D0.3). Rows go to human review for dose, units, timing, mixing and sampling site. The bound is not reported as a volume.
4. Reading.
   - Report "Vc ≤ X L/kg at t = … h". There is no lower bound on Vc from this calculation.
   - A bound near plasma or extracellular volume is consistent with initial distribution confined to that space. This is a hint, not proof.
   - A first sample late relative to the decline (`earliest_sample_h` after a visible distribution phase in item 24, or ONE_APPARENT with a sparse early grid) → LOOSE_BOUND; the number is reported without interpretation.
   - Two overlapping upper bounds do not show equal Vc, comparable exchange rates or confinement to an organ.
5. Caveats: EARLY_MIXING_POSSIBLE (sample within 5 minutes after the end of dosing, the bound included, or sampling near the injection site), RESIDUE_UNRESOLVED, SAMPLING_SITE_EARLY, DIGITIZED, GROUP_MEAN, INFUSION_TIMING_UNKNOWN, RESIDUAL_BASELINE, WHOLE_BLOOD_BASIS (the bound refers to blood concentration).

Output per IV group
`vc_upper_bound_l_per_kg`, `sample_time_h`, `earliest_sample_bound_l_per_kg`, `earliest_sample_time_h`, `modeling_constraint`, `bound_basis` (POINT / CONSERVATIVE), `population_meaning` (INDIVIDUAL / HARMONIC_MEAN), `reference_volumes` with source, `nearest_reference`, `reported_volumes` (D0.12), `data_check` (PASS / VOLUME_BELOW_PLASMA / NOT_ASSESSABLE), `caveats` (LOOSE_BOUND, EARLY_MIXING_POSSIBLE, SAMPLING_SITE_EARLY, INFUSION_TIMING_UNKNOWN, RESIDUAL_BASELINE, WHOLE_BLOOD_BASIS, DIGITIZED, GROUP_MEAN), `not_assessable_reason`.

Hand-off
- "Vc ≤ X L/kg (sample at t h). An initial estimate for Vc should not exceed this bound unless the premises are rejected." The bound is most informative when t is early relative to the distribution phase.
- EDA does not back-extrapolate C0 and does not estimate Q from slopes.

Purpose, limits, and main-objective link
Gives modeling a hard upper limit for the initial volume from one observation, and a data check that catches dose or unit errors early. It cannot give Vss, which needs extrapolation.

Keywords: initial volume; central volume; D/C(t₁); upper bound; plasma volume; harmonic mean; mixing.
MP basis: EDA004; figure list C1.
Sources: derived from mass balance. Reference volumes from a sourced physiology table per species (to be named in the run configuration). Toutain & Bousquet-Mélou 2004 (volume definitions; not yet verified).

---

### 26 | TISSUE CONCENTRATIONS, TISSUE/REFERENCE RATIO AND REPEAT DOSING

Scope
- Any measured tissue, fluid or cell concentration (D0.8 matrices other than plasma, serum and whole blood). The reference is plasma, serum or whole blood from the same study.
- Gates: D0.2 (local dosing → LOCAL_ROUTE; endogenous → display only); D0.8 flags.

Principle
- Linear exchange. For a tissue with linear uptake k_in and loss k_out, dC_T/dt = k_in C_p − k_out C_T. While plasma declines with rate λz < k_out, the ratio approaches a plateau r∞ = Kp × k_out/(k_out − λz), with Kp = k_in/k_out. The plateau is an apparent ratio. For a non-eliminating tissue, steady-state Kp ≤ r∞, with equality only when k_out ≫ λz.
- Window AUC ratio. Integrating the same equation from 0 to T with zero initial tissue gives AUC_T(0–T)/AUC_P(0–T) = Kp − C_T(T)/[k_out × AUC_P(0–T)]. For a non-eliminating tissue after a first dose, the observed-window AUC ratio is therefore never above Kp, and approaches Kp only as the window lengthens (the area method of Gallo et al. 1987 uses the 0–∞ limit, which EDA does not compute). Together with the plateau: window AUC ratio ≤ Kp ≤ plateau ratio. At steady state over one dosing interval the AUCτ ratio equals Kp. A single-time ratio can lie on either side of Kp. These bounds were checked numerically in the r1.1 review for four parameter sets.
- Timing. Because tissues equilibrate at different rates, a single-time ratio depends on the sampling time and on the dosing mode (bolus, infusion, fast or slow absorption). Single-time ratios from studies with different dosing modes or sampling times are not compared as if they were Kp (Lu et al. 2023; Mouton et al. 2008).
- A ratio that is still rising late in the window means the tissue is slower than plasma. Under linear exchange, the plasma decline in that window is not yet the true terminal phase (T8).
- Residual blood. In an unperfused homogenate, measured C = (1 − V_r) C_T + V_r × C_blood. The measured tissue/plasma ratio ≈ (1 − V_r) × true ratio + V_r × B:P. The effect is largest when the true ratio is below 1.
- Repeat dosing. In a linear system, a tissue moving in step with plasma has the same accumulation ratio as plasma at the same post-dose time. A slower tissue accumulates more.
- Homogenates mix interstitial, cellular and residual-blood drug. A homogenate ratio describes distribution; it is not target-site exposure. For a drug confined to extracellular water, homogenization dilutes the drug and underestimates the interstitial concentration. For a drug that accumulates in cells, the homogenate overestimates the extracellular concentration (Mouton et al. 2008). Homogenate concentrations are not compared with MIC or other PD targets.
- Residual blood matters most when the blood fraction of the tissue is large and the drug is taken up little by the tissue (Khor & Mayersohn 1991, abstract). B:P measured in vitro at equilibrium may not hold early after dosing when red-cell uptake is slow.

Data and details
- Per series: matrix and D0.8 fields; organ; time after dose; concentration with data status, n, SD/SE and mean type; units and value basis; same-animal pairing; the matched reference values.
- Organ weights with source; V_r with source; B:P and haematocrit with source.
- Dose history: dose, interval, number of doses, predose values, matched post-dose times.

Figures (D0.11)
- Keys DIS-4a, DIS-4b, DIS-4c (guide labels DIS-3a, 3b, 3c); DIS-4d and DIS-4e optional (D0.11).

Assessment

D3 mass-balance pre-check (runs first, on every tissue dataset)
1. At each time, for disjoint organs, amount_i = L_i × W_i. L_i is the lower allowed concentration, uncorrected for residual blood. W_i is the same-study organ weight, or the lower end of a literature range matched on species, strain, age and body weight. Do not add blood or plasma: the residual blood in each organ is already part of the body total. For paired organs (kidneys, lungs), use the weight that matches the measured tissue and do not count the pair twice.
2. Compare Σ amount_i with the upper bound on the dose delivered by that time (cumulative over prior doses). Use the same analyte and dose basis. Not applicable to endogenous compounds or to MIXED origin without a specific assay.
3. Σ amount_i > dose upper bound → DATA_ISSUE on the rows involved. Those rows do not enter later steps and go to human review. Common causes: homogenate dilution factor, value basis (per g versus per organ), units, dose basis, digitized axis scale.
4. Organ weights from an unmatched literature range, or group means whose lower bound has no supported uncertainty → the comparison is SENSITIVITY_ONLY and cannot set DATA_ISSUE.
5. Pass → "measured tissues show no mass-balance contradiction". This does not show that the data are correct, or that a large share of dose was recovered.

DIS-4a tissue measurements
6. Report each tissue, time, concentration, native units, n and dispersion. One time point is a complete descriptive answer for that sampling. With several times, report the sampled peak, the last quantified time and observed persistence. Destructive cohorts are drawn as separate points, not lines.
7. With a contemporaneous reference, show both on one semilog plot. Look for a tissue peak later than the plasma peak (slow equilibration) and for parallel late declines. Rank tissues only within comparable measurements at one time.
8. Observed-window tissue AUC and tissue/reference AUC ratio follow D0.6. A homogenate AUC ratio is labelled "homogenate, total". For a non-eliminating tissue after a first dose, report it as a lower bound on Kp (see Principle); for an eliminating or unknown tissue, report it as a window ratio only. For destructive sampling, the CI of the AUC ratio uses a Fieller-type interval when the number of sampling times is moderate to large, or a bootstrap-t interval when it is small; percentile bootstrap intervals undercover with 3 animals per time (Jaki, Wolfsegger & Ploner 2008).
8a. Phase plot (DIS-4e, tier 3, optional). Plot tissue against reference concentration, points joined in time order with arrows. A counter-clockwise loop is consistent with delayed equilibration of the tissue; a straight line through the origin with no loop is consistent with rapid equilibration in the sampled window. Description only; destructive cohorts need a common population.

DIS-4b ratio over time
9. Eligibility: at least 3 common quantified times with a usable reference (D0.5). State the estimator: MEAN_OF_RATIOS (source-reported or individual pairs) or RATIO_OF_MEANS. A missing or BLQ reference leaves the tissue point usable and the ratio UNDEFINED at that time.
10. d = ln r(last) − ln r(third-last). SE(d) from the four concentration CVs and n: Var(ln r(t)) ≈ CV_T²/n_T + CV_ref²/n_ref, adding a covariance term only when same-animal pairing and the within-animal correlation are reported. With pairing but no correlation reported, use zero covariance and state it (conservative when the correlation is positive). z = d/SE(d).
    - Critical value z_crit. When SE(d) is estimated from group SDs, use the 0.977 quantile of the t distribution with Welch–Satterthwaite degrees of freedom, df = [Σ vᵢ]²/Σ[vᵢ²/(nᵢ − 1)] with vᵢ = CVᵢ²/nᵢ over the four groups. With individual data and a known or well-estimated SE, z_crit = 2. Reason: with n = 3 per group a fixed z_crit = 2 gave 3.5–4.9 % false RISING or FALLING per direction in the r1.1 check (lognormal data, CV 0.15–0.5), and the t quantile gave 1.5–2.0 %.
11. Reading, applied only when e^d is outside the band [0.80, 1.25] ([0.72, 1.38] for digitized data) and |z| ≥ z_crit. Otherwise the reading is NO_DIFFERENCE_SEEN.
    - NO_DIFFERENCE_SEEN (plateau): tissue and reference may move in step; this is not proven. Report the plateau ratio with "steady-state Kp ≤ plateau ratio". Not read as accumulation.
    - RISING: the tissue declines more slowly than the reference in this window. T8 contradiction when its premises hold: "the observed reference decline is the terminal phase for this tissue" EXCLUDED_UNDER_STATED_ASSUMPTIONS. Candidates: a slow tissue compartment; specific binding; active uptake.
    - TISSUE_NOT_FALLING: the tissue concentration itself does not fall, or rises, in the window. Candidates: active uptake, specific binding, accumulation.
    - FALLING: the tissue declines faster than the reference. Candidates: elimination in the tissue, efflux, redistribution. After local dosing the direction is reversed anyway (LOCAL_ROUTE).
    - One ratio at one time describes only that time. A rising ratio can come from a falling reference; always show numerator and denominator.
12. Residual-blood sensitivity, for unperfused homogenates. C_corr = (C_homog − V_r × C_blood)/(1 − V_r), with C_blood = B:P × C_plasma. V_r is a sourced value. When B:P is missing, run both ends of a range: the lower end 1 − Hct (drug confined to plasma) and an upper end set in the run configuration with its basis. If the reading changes between uncorrected and corrected values → SENSITIVITY_ONLY on the reading. Correction is never applied silently and never to perfused tissue.
13. ELF: no ratio reading with ELF_DILUTION_UNCORRECTED. Record dwell time and macrophage lysis risk (D0.8). Microdialysis: no quantitative reading with MICRODIALYSIS_UNCALIBRATED.
14. Formal trend tests over more than one pair of times, or over a whole window, need a prespecified family and multiplicity control (A0.3). A window-wide "stable" statement also needs joint support at the middle time.

DIS-4c repeat dosing
15. Match post-dose time, dose, interval, matrix and assay between the first and the later dose. Record dosing history, predose values and whether steady state is claimed by the source.
16. AR_T = T_later/T_first and AR_ref = ref_later/ref_first at the same post-dose time. d = ln(AR_T/AR_ref), with SE, df and z_crit from the four concentration CVs as in step 10. Reading as step 11: TISSUE_ACCUMULATES_MORE (same hand-off as RISING), NO_DIFFERENCE_SEEN, TISSUE_ACCUMULATES_LESS.
17. T9 on each matrix. A contradiction in the reference routes to absorption item 23 (TIME_DEPENDENCE_SUSPECTED) and the tissue reading is reported with PLASMA_TIME_DEPENDENCE; it is not attributed to tissue. A contradiction in tissue only → TISSUE_TIME_DEPENDENCE with candidates (time-dependent uptake, tissue injury, data issue).
18. Relative accumulation applies only to the compared occasions.

Output per tissue series
`d3_status` (PASS / DATA_ISSUE / SENSITIVITY_ONLY / NOT_APPLICABLE) with `d3_sum_pct_dose_lower` and organ-weight source, `tissue_rows`, `sampled_peak_h`, `last_quantified_h`, `ratio_estimator`, `ratio_rows` (time, numerator, denominator, ratio or UNDEFINED), `window_auc_ratio` with window, `d`, `se_d`, `z`, `band_used`, `df`, `z_crit`, `ratio_reading` (NO_DIFFERENCE_SEEN / RISING / TISSUE_NOT_FALLING / FALLING / NOT_ASSESSABLE), `plateau_ratio` with "steady-state Kp ≤ plateau", `kp_bracket` (lower from the window AUC ratio, upper from the plateau, with premises), `t8_label`, `residual_blood_sensitivity` (unchanged / SENSITIVITY_ONLY / not applicable), `repeat_dose_reading`, `ar_tissue`, `ar_reference`, `t9_labels`, `candidates`, `caveats` (LOCAL_ROUTE, ELF_DILUTION_UNCORRECTED, MICRODIALYSIS_UNCALIBRATED, MATRIX_UNKNOWN, RATIO_OF_MEANS, MEAN_OF_RATIOS, RESIDUAL_BLOOD_UNCORRECTED, PLASMA_TIME_DEPENDENCE, TISSUE_TIME_DEPENDENCE, DIGITIZED, DESTRUCTIVE_SAMPLING), `not_assessable_reason`.

Hand-off
- RISING or TISSUE_ACCUMULATES_MORE: this tissue as a slow-compartment candidate. The plasma λz in this window may overestimate the true terminal rate, and a Vss estimated from it may be too small. Estimating uptake needs earlier tissue points; estimating loss needs later tissue and plasma points.
- NO_DIFFERENCE_SEEN: steady-state Kp ≤ plateau ratio; a candidate equilibrium ratio only if the tissue is fast relative to λz. With a first-dose window AUC ratio and no tissue elimination, hand over the bracket "window AUC ratio ≤ Kp ≤ plateau ratio".
- Homogenate ratios are handed over as distribution evidence, not as target-site exposure.

Purpose, limits, and main-objective link
Reports which tissue was measured when, whether the amounts are compatible with the dose, and what the tissue/reference ratio and its change say about equilibration and the terminal phase. It does not estimate Kp at infinity or tissue rate constants.

Keywords: tissue/plasma ratio; plateau ratio; apparent Kp; terminal phase; residual blood; mass balance; homogenate; ELF; microdialysis; accumulation ratio.
MP basis: EDA004; T10 (matrix and local-site concentrations); figure list B4.
Sources: Schentag & Jusko 1977 Clin Pharmacol Ther 22:364 (tissue accumulation with multiple dosing; abstract read); Khor & Mayersohn 1991 Drug Metab Dispos 19:486 (residual blood; abstract read, organ values not obtained); Mouton et al. 2008 J Antimicrob Chemother 61:235 (homogenate bias and timing; full text read); Gallo, Lam & Perrier 1987 J Pharmacokinet Biopharm 15:271, doi 10.1007/BF01066322 (area method; abstract read); Lu et al. 2023 Int J Mol Sci 24:16224, doi 10.3390/ijms242216224 (time dependence of Kp; read in part); Jaki, Wolfsegger & Ploner 2008 Pharm Stat (CIs for AUC ratios with destructive sampling; preprint read); Jusko, Molins & Ayyar 2020 Drug Metab Dispos 48:894, doi 10.1124/dmd.120.000118 (tissue dilution and trapped blood in fu,T; read in part); Marcy et al. 1987 Am Rev Respir Dis 135:1276 and Baldwin et al. 1991 Thorax 46:658 (ELF urea method; abstracts read); Rennard et al. 1986 (urea dilution; title only); Rodvold, George & Yoo 2011 and Drwiega & Rodvold 2021 Clin Pharmacokinet (ELF penetration reviews; title and venue). The plateau formula, the residual-blood mixing equation and the accumulation-ratio argument are derived.

---

### 27 | PLASMA PROTEIN BINDING, UNBOUND EXPOSURE AND KPUU

Scope
- Every study (Q6 is required). Binding records may come from the same study, another study or a source-reported value.

Principle
- Unbound concentration drives diffusion and many effects. Total concentration differs from unbound by fu,p, which may change with concentration, species, disease state and method.
- Kpuu = unbound tissue concentration / unbound plasma concentration. With binding removed, a value near 1 is consistent with passive equilibrium. Departures need transport or trapping explanations.

Data and details
- Measured unbound plasma concentration; fu,p with species, matrix, method (equilibrium dialysis, ultrafiltration, ultracentrifugation), temperature, concentration tested, nonspecific binding and source.
- Tissue unbound data: calibrated microdialysate, or homogenate concentration × fu,T with the fu,T method, the homogenate dilution correction (Kalvass & Maurer 2002) and any trapped-blood correction. The dilution correction is most reliable when drug concentration is low, binding is weak and dilution is small (Jusko, Molins & Ayyar 2020).

Figures (D0.11)
- DIS-5a when two or more comparable binding concentrations exist; otherwise a table row. DIS-5b when Kpuu is eligible.

Assessment

Plasma unbound exposure (every study)
1. Evidence order.
   - Measured unbound plasma concentration: report the value or profile; compare with total at matched times.
   - Applicable fu,p and total concentration: Cu,p = fu,p × C_total,p, labelled DERIVED. A single fu,p describes its assay condition; applying it across a PK profile needs support that binding is constant over the observed concentration range.
   - Neither: "plasma unbound exposure unknown" with the missing input; the total-concentration result is kept.
2. Binding by concentration (DIS-5a). Plot fu,p against total concentration by species, method and matrix, not averaged, and shade the observed PK range. Stable fu,p across the range supports a constant-fraction conversion. Changing fu,p → NONLINEAR_BINDING candidate, pending DME, cross-checked with DIS-2 HIGHER_DOSE_LOWER. A tested range that does not cover the PK range is stated and not extrapolated (FU_RANGE_NOT_COVERED).
3. Unbound AUC over an observed window: integrate the unbound profile (D0.6). Total AUC × fu,p only when fu,p is supported as constant over the window.

Kpuu (DIS-5b)
4. Eligibility: unbound concentrations on both sides (calibrated microdialysis, or homogenate × fu,T with fu,p for plasma); not computed from total concentrations only. Use the unbound AUC ratio over a common observed window during a period that DIS-4b reads as NO_DIFFERENCE_SEEN, or at a documented steady state. A single-time unbound ratio is an apparent Kpuu (KPUU_APPARENT) and is not compared with the band.
    - One-sided use of the item 26 bracket on the unbound scale, when the tissue is not known to eliminate drug and exchange is linear: a first-dose window unbound AUC ratio whose lower interval bound exceeds 2 places Kpuu above the band; a plateau unbound ratio whose upper interval bound is below 0.5 places Kpuu below it. Other positions need the period or steady-state estimate above.
5. Band [0.5, 2], a project setting for a defined unbound ratio. A position (inside, above, below) is assigned only when the ratio's interval lies entirely on one side; otherwise UNRESOLVED. Without a sourced uncertainty for fu,p and fu,T → SENSITIVITY_ONLY.
   - Inside → no departure from passive equilibrium seen.
   - Above 2 → active uptake candidate. When derived from homogenate × fu,T, also list pH partitioning and lysosomal trapping.
   - Below 0.5 → efflux or tissue elimination candidate; incomplete equilibration if the ratio period was not established.
6. Specific transporters or mechanisms need independent evidence.

Output per study
`plasma_unbound_status` (MEASURED / DERIVED / UNKNOWN), `fu_table` (species, matrix, method, temperature, concentration range, value, uncertainty, source), `fu_concentration_dependence` (STABLE / CHANGING / NOT_ASSESSABLE), `pk_range_covered`, `unbound_auc_window`, `kpuu` with estimator, window, interval and position (INSIDE / ABOVE / BELOW / UNRESOLVED), `caveats` (KPUU_APPARENT, FU_RANGE_NOT_COVERED, FU_OTHER_STUDY, FU_OTHER_SPECIES, NONLINEAR_BINDING, MICRODIALYSIS_UNCALIBRATED, SENSITIVITY_ONLY), `not_assessable_reason`.

Hand-off
- The fu table is an input for modeling. Nonlinear binding is a candidate pending DME. Kpuu is handed over only with its window and estimator.

Purpose, limits, and main-objective link
Establishes what unbound plasma exposure each study supports and, where possible, whether tissue entry departs from passive equilibrium. It does not estimate tissue binding from total concentrations.

Keywords: protein binding; fraction unbound; unbound concentration; nonlinear binding; Kpuu; microdialysis; homogenate fu,T; lysosomal trapping.
MP basis: T11 (unbound drug and protein binding); figure list C3.
Sources: Øie & Tozer 1979 (binding and volume; not yet verified); Kalvass & Maurer 2002 (homogenate dilution correction; cited through Jusko et al. 2020); Jusko, Molins & Ayyar 2020 Drug Metab Dispos 48:894 (read in part). Kpuu concept in the brain, liver-transporter and anti-infective microdialysis literature (papers checked by title only).

---

### 28 | CONDITIONS WITHIN A SPECIES AND THE PROJECT SPECIES TABLE

Scope
- Within a species: two or more conditions (disease, infection, co-medication, body weight, age, strain) with IV or comparable profiles.
- Across species: always run once per project, using the project species inventory. Every species gets a row, including species with one study or reported parameters only.

Data and details
- Per row: species, study, arm, route, dose basis, IV mode, matrix, basis, measured window, item 24 to 27 outputs, source-reported volumes (D0.12), fu,p.

Figures (D0.11)
- DIS-6a condition overlay with T5 c intervals; DIS-6b species table; DIS-3 across species.

Assessment

Conditions within a species
1. Match route, dose basis, IV mode, matrix, sampling basis and time window. List every differing attribute. More than one differing attribute → CONFOUNDED. Different studies or occasions → description only.
2. T5 (A0.10) on dose-normalized concentrations at matched times. Contradiction → the profiles are not one scaled family: a shape difference (distribution or elimination) is supported for the window; the condition becomes a covariate candidate. No contradiction → NOT_EXCLUDED: a proportional shift is compatible; shape change not seen.
3. Report the affected window and study confounders before attributing a difference to the condition.

Species table (project level)
4. One row per species/study/arm with the columns: route, dose basis, matrix and window; item 24 reading and T6/T7 labels; item 25 bound with time (L/kg); source-reported Vss, Vc, Vz as separate entries (L/kg); fu,p or measured Cu,p; primary evidence locator; missing evidence.
5. Compare only matching parent, matrix, basis, dose basis and parameter definition. Keep original values with any unit conversion and its basis. A species with only V/F or a loose bound contributes that evidence in its own category.
6. Source-reported Vss per kg with source uncertainty. When concentration-independent, species-matched fu,p applies, also Vss/fu,p, the apparent volume referred to unbound plasma. A smaller species contrast after this step is consistent with a plasma-binding contribution. A remaining contrast can motivate tissue binding or transport hypotheses.
7. Optional, sensitivity only: a tissue unbound fraction from the Øie–Tozer relation, with sourced physiological volumes and ratios, labelled MODEL_DERIVED with its sensitivity range.
8. A feature seen in one species (for example a fast phase) can motivate a candidate in another; label it TRANSFERRED_HYPOTHESIS and state what the receiving species' own data show.
9. Status: PARTLY_ANSWERABLE when a comparable subset exists; NOT_ANSWERABLE_YET when no comparable species pair exists yet.

Output
Within species: `condition_of_interest`, `reference_condition`, `differing_attributes`, `t5_label` with margins, `affected_window`, `caveats` (CONFOUNDED, OCCASION_CONFOUNDED, DIFFERENT_STUDIES, DOSE_BASIS_MISMATCH). Project: `species_rows`, `comparable_pairs`, `vss_fu_rows`, `model_derived_rows`, `transferred_hypotheses`, `missing_by_species`.

Hand-off
- Condition and species effects as covariate candidates, each with the comparison that supports it and its confounders. No allometric scaling or prediction is made in EDA.

Purpose, limits, and main-objective link
Shows what can already be compared across conditions and species on a common basis, and what is missing for each species.

Keywords: species comparison; Vss per kg; Vss/fu; Øie–Tozer; condition effect; covariate candidate; confounding.
MP basis: figure list C1, C3.
Sources: Gabrielsson et al. 2016; Øie & Tozer 1979 (not yet verified); Davies & Morris 1993 (physiological parameters; not yet verified).

---

### Flag registry (items 24–28)

Each flag is defined once; the item text gives the detail. Evidence labels are defined in A0.3. Absorption flags reused here (GROUP_MEAN, DESTRUCTIVE_SAMPLING, DIGITIZED, ENDOGENOUS_REVIEW_REQUIRED, ROUTE_UNKNOWN, RESIDUAL_BASELINE, CONFOUNDED, OCCASION_CONFOUNDED, DOSE_BASIS_MISMATCH, TIME_DEPENDENCE_SUSPECTED, DISTRIBUTION_MASKED, UNDEFINED) keep their absorption definitions.

| Flag | Item | Trigger |
|---|---|---|
| INFUSION_TIMING_UNKNOWN | D0.2; 24, 25 | IV infusion with unreported duration or end |
| LOCAL_ROUTE | D0.2; 26 | Dose given to the sampled site |
| MATRIX_UNKNOWN | D0.8 | Matrix, basis or homogenate value basis cannot be determined |
| ELF_DILUTION_UNCORRECTED | D0.8; 26, 27 | ELF without urea correction |
| MICRODIALYSIS_UNCALIBRATED | D0.8; 26, 27 | Microdialysate without recovery calibration |
| RATIO_OF_MEANS / MEAN_OF_RATIOS | D0.5; 26 | Ratio estimator |
| DATA_ISSUE | D3 (26); 25 | Mass-balance contradiction, or VOLUME_BELOW_PLASMA; rows leave later steps |
| VOLUME_BELOW_PLASMA | 25 | D_upper/C_lower below the sourced plasma-volume lower value |
| LOOSE_BOUND | 25 | First valid sample late relative to the decline |
| WHOLE_BLOOD_BASIS | 25 | Bound computed from whole-blood concentration |
| TOO_FEW_POINTS / NON_DECLINING_HALF | 24 | Reasons for curvature NOT_ASSESSABLE |
| GROUP_MEAN_CURVATURE_POSSIBLE | 24 | Group-mean FLATTENING with R < 1.6 |
| LLOQ_PROXIMAL | 24 | Reading depends on the last point and it is < 3 × LLOQ, or LLOQ not reported |
| EARLY_MIXING_POSSIBLE | 24, 25 | Reading or bound depends on a sample within 5 min of dosing or near the injection site |
| NOT_LOG_CONVEX_DESCRIPTIVE | 24 | STEEPENING reading; T7 decides any exclusion |
| RATIO_WITHIN_BAND / RATIO_CONSTANT_OUTSIDE_BAND / RATIO_RISES_LATE_ABOVE_BAND / RATIO_BELOW_BAND / RATIO_ABOVE_BAND_EARLY_THEN_FALLS / RATIO_MIXED / DESCRIPTIVE_CONFOUNDED | 24 | DIS-2 dose pattern by observable shape (replaces DOSE_PARALLEL, SATURABLE_ELIMINATION_SUSPECTED, HIGHER_DOSE_LOWER, DOSE_OFFSET_CONSTANT, MIXED_DOSE_PATTERN) |
| LOW_POWER / NOT_DETERMINED / SLOWING_IN_EVERY_SUFFIX | 24 | Window-start screen reasons |
| SOURCE_ASSAY / SOURCE_REPLICATES / DEFAULT | D0.4 | Noise tier labels |
| RESIDUE_UNRESOLVED | 24, 25 | Quantified predose or prior dose without verified washout |
| FORMAL / SENSITIVITY_ONLY (constraint) | 25 | Status of the Vc modeling constraint |
| RESIDUAL_BLOOD_UNCORRECTED | 26 | Unperfused homogenate without correction |
| PLASMA_TIME_DEPENDENCE / TISSUE_TIME_DEPENDENCE | 26 | T9 contradiction in reference / in tissue only |
| KPUU_APPARENT | 27 | Single-time unbound ratio |
| FU_RANGE_NOT_COVERED | 27 | Binding concentrations do not cover the PK range |
| FU_OTHER_STUDY / FU_OTHER_SPECIES | 27 | fu,p taken from another study or species |
| NONLINEAR_BINDING | 27; 24 | fu,p changes with concentration |
| MODEL_DERIVED | 28 | Øie–Tozer or other model-implied estimate |
| TRANSFERRED_HYPOTHESIS | 28 | Candidate motivated by another species |
| REPORTED_PARAMETER | D0.12 | Parameters only, no concentration points |
| SAMPLING_SITE_EARLY | D0.8; 24, 25 | Reading or bound depends on early samples from a venous, mixed, unreported or injection-adjacent site |
| TARGET_BINDING_PATTERN | 24 | Retired as a dose label in r1.6 (labels name shapes only); target-mediated disposition is considered only with `target_binding_declared` = YES |

---

## B. Run settings

name the physiology source for reference volumes and plasma-volume lower values per species, the V_r source, the B:P upper end when unreported, confirm the z_crit rule of item 26 step 10 (t quantile with Welch–Satterthwaite df for group summaries), and confirm the project settings (σ, R ≥ 1.5, bands [0.80, 1.25], [0.72, 1.38], [0.5, 2]). Since r1.6 the noise tiers and the precision admission of D0.4 set σ; the 1.5-fold SIMILAR/DIFFERENT grading is deleted (s1.0 S7).

## Appendix A. What r1.5 and r1.6 changed

| Change | Where | Reason |
|---|---|---|
| r1.5: analysis unit for repeated occasions; EV profiles read in Distribution; dataset-specific noise; APOD hand-off; prior-dose residue; alternative causes of slowing; power of the window-start screen | item 24, D0.4, D0.9 | r1.5 (2026-11-21) |
| r1.5b decisions A–D: formal threshold tiers; flip-flop owned by Absorption; removal set; sensitivity demotion (now s1.0 S5) | D0.4, item 24, D0.9 | George, 2026-11-24 |
| T6/T7 decision order, removal outcomes and the separate sensitivity record follow s1.0 | D0.3, item 24 | R2, R3, R10 |
| T6 on group data: geometric-mean path only with SD or SE on ln C; no single-line exclusion from arithmetic means | D0.10 | R1 |
| T6 and T7 reruns need three qualified distinct time points | item 24 | R2 |
| Two-sided family-wise 0.05; the family follows the published conclusion | item 24, item 26 | R4 |
| APOD ordering uses the shared rank groups | D0.9 | R5 |
| Dose patterns named by observable shape; confounded doses give the contrast only; 1.5-fold grading deleted; T3p reuse registered | item 24, D0.10, B | R7 items 4–6 |
| Noise tiers come from the shared precision admission | D0.4 | R8, M4 |
| The IV post-distribution window is one shared record read by Absorption | item 24 step 7 | M1 |
| Pages use the guide numbers; stable question ids; recorded gaps | D0.11 | M5 (with L3) |
| Vc upper bound uses the highest eligible concentration; a separate modeling constraint | item 25 | M6 |
| Source-reported predose zero, EV post-peak shape from Absorption A0.7, mixing within 5 minutes inclusive | items 24, 25 | L1, L5, L6 |
| Consolidated edition: guide labels mapped to code keys; captions and drawing limits of s1.0 S13; Vc bounds as a table | D0.11, 24, 25, 26 | s1.0 wins where it differs (2026-11-25) |

## Appendix B. Checks covered by the tests

1. T6 excludes the arithmetic-mean path for destructive cohorts (a mixture of linear one-compartment individuals whose arithmetic mean bends).
2. A single planned dose level with individual dose variation gives an individual layer; genuine dose levels trigger DIS-2.
3. The Vc bound uses the highest qualified concentration.
4. Absorption receives a valid IV candidate window or an explicit unresolved status; a weak IV reference stays identifiable.
5. Prior-dose residue: a linear one-compartment IV occasion after an earlier dose without washout gives no formal T6 exclusion, and T7 stays compatible.
6. Repeated occasions: each animal × occasion is drawn and tested separately; the per-animal summary shows the occasions together; the linkage reaches Modeling.
7. Window-start power: a sparse IV profile with one late sample returns LOW_POWER or NOT_DETERMINED rather than the earliest time.
8. EV: T6/T7 report CANNOT_ASSESS, the post-peak description carries the non-separability label, and the Vc/F bound is produced.
9. Noise: σ is recorded with its tier and source before the tests run; a tier-3 value gives SENSITIVITY_ONLY in a formal test.
10. APOD: only formal T6/T7 results remove candidates, each with test, unit, window and margin.
