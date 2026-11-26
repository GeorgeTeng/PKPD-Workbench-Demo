# EDA shared rules s1.0 (Absorption, Distribution, Elimination)

Version: s1.0 · Edition: consolidated, 2026-11-25 (wording only; no rule changed) · Status: current (wording confirmed by George 2026-11-26)

Applies to: Absorption r4.4 (items 16–23), Distribution r1.6 (items 24–28), Elimination r1.2 (items 29–36).
Machine form: `shared_rules_s1.0.machine.yaml` (unchanged). Code: `tools/eda/eda_common.py`.

Where a module rules file and this file differ, this file wins. A module file states only its item-specific premises,
minimum data and removal units. Rules S1 to S10 are George's rule decisions R1 to R10 of 2026-11-24; their discussion and
the probes behind them stay in `rule_decisions.md` (eda_logic_review_20261124, sha256
5b6267a4f5111e8b3a0f6d5343ddd359f2f31f5aa42d053096e8c2b2e0a03924). S11 and S12 come from the third review round of
2026-11-24, S13 from the figure review of 2026-11-25. Worked examples are in Appendix A; open points and parts not yet
implemented are in Appendix B.

## S1. Formal conclusions from group-level data

A formal exclusion requires that the analysis unit, the estimation target and the sampling design agree, and that a valid
joint interval or a calibrated test covers the whole range actually searched. Group-level data may use sampling uncertainty
with a stated source and a matching scale, once the mean type, the population each time point represents and the dependence
requirements of the method have been checked. When only the default tolerance is available, the group composition cannot be
identified, or the dependence information the check needs is missing, keep the observation and the sensitivity reading and
record the formal status as CANNOT_ASSESS. When the check is eligible and finds no contradiction, record NOT_EXCLUDED.

One evidence threshold applies across the modules; each check keeps its own conditions.

- T6: the fixed-cohort geometric-mean path only with an SD or SE on the ln C scale (or a convertible interval). No
  single-line exclusion from arithmetic means, also for destructive cohorts. A changing n alone is not a veto.
- T3: formal only for independent destructive sampling. Missing metadata is not independence. A small-sample t quantile
  (Satterthwaite df) replaces the normal 1.96. The conclusion is worded as unequal dose-normalised exposure over the window.
- T10: group-level data are not formal.
- The formal interval basis is recorded separately from the noise tier. Tier 3 (project default) gives CANNOT_ASSESS with
  SENSITIVITY_ONLY.

## S2. Removal rerun

After the full-data check finds a contradiction, remove each predefined unit in turn and recalculate. Each rerun keeps the
original estimation target and eligibility conditions. If the contradiction disappears in a valid rerun, record NOT_EXCLUDED
with SINGLE_POINT_SUPPORT, naming the unit. If there is no removable unit, or a required rerun cannot be assessed (below the
check's minimum), record NOT_EXCLUDED with LOO_NOT_ASSESSABLE and the reason. Both may be recorded together. Keep the
full-data direction, margin and decisive observations, and the result of every rerun. The removal gate is passed only when
every required rerun is assessable and keeps the contradiction.

| Check | Removal minimum or unit |
|---|---|
| T6 | a rerun needs three qualified distinct time points |
| T3p | removing the only matched time gives LOO_NOT_ASSESSABLE |
| T3 | reruns keep the original window |
| T10 | units "remove urine collection interval" and "remove plasma sample inside the interval", named separately; the number of valid reruns is recorded |

## S3. Widening, BORDERLINE and timing

A formal exclusion rests on a joint interval or a calibrated test that covers the range actually searched. Report the
direction of the contradiction, the margin to the decision boundary and the decisive observations. A generic fixed widening
is not part of the formal decision in any module; the margin is always reported. Run an extra widening check only when the
study prespecified a justified widening scheme, and record its size and what it is applied to; if that recheck removes the
contradiction, record NOT_EXCLUDED with BORDERLINE. The T3p default 5 % tolerance is not on the formal path.

When source-supported timing uncertainty could change the eligibility or the conclusion of a check, recheck it while keeping
the dependence between times. Outcomes: gate passed; NOT_EXCLUDED, timing-sensitive, nominal result kept; or CANNOT_ASSESS,
with SENSITIVITY_ONLY when a conditional calculation is possible. The timing gate is passed only when the original check stays
valid over the supported time range and keeps a contradiction in the same direction.

## S4. Test family and significance level

A formal conclusion declares in advance its scope, analysis unit, test family, combination rule and significance level. The
default family-wise level is 0.05 two-sided. The family follows the conclusion that is published. Where any single
observation, window, contrast or unit could trigger the conclusion, the joint interval or calibrated procedure covers all of
those opportunities; a unit picked after seeing the results covers every unit that took part in the selection.

- Each formal result records scope, analysis unit, family members, correction method and m. m counts the distinct underlying
  intervals covered together: T7 by concentration interval; a reused plasma observation once; fu and GFR included when they
  carry statistical intervals.
- The T3p Holm family is the dose pairs actually included times the matched time contrasts.
- A unit may have its own family; a board may summarise unit results as a count, stating the denominator and the correction
  scope.
- A board-level formal exclusion follows a combination rule fixed before the results: "at least one unit" needs study-level
  control (Holm over valid unit tests, or a study-wide joint interval); "all required units" may use an intersection-union
  test, same direction, with no shrinking of the denominator; "at least k" needs its own calibration.

## S5. Rank groups and board-level combination

Each candidate is a complete model combination and is placed in one group:

| Group | Meaning |
|---|---|
| REFERENCE | the benchmark role |
| SUPPORTED | direct positive support |
| INDIRECT_SUPPORT | indirect support only |
| UNTESTED | no evidence usable for ranking (state "not assessed" or "assessed but undecided") |
| CONTRARY_EVIDENCE | a formal unit-level contradiction; the combination stays on the board |

| Evidence | Board handling |
|---|---|
| Sensitivity-level contradiction only | The candidate stays in its group. The order of two candidates changes only when the same observation distinguishes that pair and supports the other candidate of the same group. Otherwise keep the order or tie them, and mark the contradiction. |
| Formal unit-level exclusion, board threshold not met | CONTRARY_EVIDENCE. Report required n, assessable m and formal contradictions k, with direction and unit-level correction. k = n with mixed directions also stays here. Supporting evidence stays visible in the same record. |
| Every required unit formally excluded, same direction | Board-level exclusion by the intersection-union rule of S4, within the declared conditions and window, recorded separately. An excluded benchmark model may still be shown as a fit comparator. |

- The required units for each candidate and check are fixed before the results. A planned unit that cannot be assessed stays
  in the denominator; a unit outside the scope of the check (for example an oral-only curve for the IV T6) is not counted.
  Combination uses stable candidate and unit ids.
- Direction follows what each candidate predicts. Reliable early steepness followed by slowing, with input ended and baseline
  and observation conditions met, can support listing peripheral exchange first. Reliable late steepening challenges both the
  linear one-compartment model and linear reversible multi-compartment models that meet the T7 premises. A T6 failure alone
  does not put two compartments ahead of one. Without an alternative supported by the same observation, mark the shared
  contradiction on both.
- Within a group, order by the number of independent evidence sources traced to the original observations (figure, slope, AUC
  and reused results from one curve count once), then by model simplicity. Tie candidates the data cannot distinguish.
- When Absorption shows a single component such as a fixed lag, it shows the contradiction with the complete combination it
  depends on. Elimination with one actual candidate shows its evidence level, contradictions and the next distinguishing check.

## S6. Answer statuses and flagged upstream results

A question status says how far the data answer the question, not which way the answer goes.

| Display (zh) | Display (en) | Code | Condition |
|---|---|---|---|
| 可回答 | Answerable | ANSWERABLE | Every prespecified required unit reaches the evidence level the question asks for. |
| 部分可回答 | Partly answerable | PARTLY_ANSWERABLE | A usable result exists but covers only some required units or sub-questions, or supports only a conditional conclusion. |
| 证据不足 | Insufficient evidence | NOT_ANSWERABLE_YET | The question applies and no usable result answers it yet. |
| 不适用 | Not applicable | NOT_APPLICABLE | The known study design makes the question void. |

- Judge each result first, then combine the results into the question status; the outcome does not depend on row order. A
  hand-off such as the urine recovery estimate has its own evidence level.
- A limitation attaches to the specific conclusion it limits (unknown bioavailability limits the reading of systemic
  clearance after extravascular dosing; the window AUC is still reported).
- A result with a limiting flag (SENSITIVITY_ONLY, BORDERLINE, SINGLE_POINT_SUPPORT, LOO_NOT_ASSESSABLE,
  CONDITIONAL_ON_LABEL_IDENTITY, CONDITIONAL_ON_FIXED_COHORT) is passed on with its direction, the reason and its scope,
  supports sensitivity-level use only, and makes the question PARTLY_ANSWERABLE at most.
- A T7 result with a full-data contradiction whose removal rerun cannot be assessed defers the formal exclusion and cannot
  open a tail calculation that depends on "no contradiction found in the observed window". If the only gap is assay-error
  information, the descriptive screen of the same curve shows no contradiction and the other extrapolation premises hold, a
  separately listed assumption-based sensitivity estimate is allowed.
- The board shows a short label, the finding and one sentence on the limit; codes and flags stay in the structured result and
  the audit detail.

## S7. Checks and thresholds that exist only in code

Report numbers as they are; an inference needs a rule. A number may carry its unit, comparator, window and source, and may
describe what was observed. A mechanism reading, a candidate ranking or a formal test result traces to a check that the rules
name, with its conditions of use and outcome table. A registered descriptive screen gives INDIRECT_SUPPORT at most. A
reliable number answers a question completely when the question only asks for that number (for example a window AUC).

| Check | Rule |
|---|---|
| Renal filtration sign test (Elimination) | A description (DESCRIBED): per-animal ratios, median, range, paired window and the sources of GFR and fu. No "tested" or "suggests net secretion"; the p-value stays in the audit detail. The p-value reflects agreement of direction between animals and cannot correct a common GFR bias. T10 stays the formal filtration check. |
| Source-reported individual IV clearance (Elimination) | Registered as "re-comparison of source-reported individual IV CL": ratio, interval, pairing design and source table, beside T3/T3p, with family correction over all preset contrasts on the board that can trigger the same conclusion (S4). A cited author test keeps its own correction scope. Alone it gives at most PARTLY_ANSWERABLE for the dose and repeat-dose questions, and it is shown together with any upstream exclusion of dose proportionality. |
| Cmax/D screen (Absorption) | Cmax/D below 0.5 or above 2.0 with common-window AUC/D within 0.80–1.25 is a registered descriptive screen. It needs sampling that brackets the peak and comparable exposure windows. Passing it gives INDIRECT_SUPPORT at most, also when T3/T3p has a formal result: T3 answers window exposure, T3p concentration at matched times, and separating absorption from disposition needs evidence that distinguishes the two. |
| Dose patterns (Distribution) | Labels name observable shapes (for example "the ratio of dose-normalised concentrations, high over low dose, rises in the late part"). When dose and animal are confounded, show the contrast and the reason only; no candidate, no `dose_nonlinear`, no mechanism nomination in Elimination. |
| 1.5-fold grading (Distribution) | Deleted (no SIMILAR/DIFFERENT). Keep the comparable window and the paired numbers, with numerator and denominator stated. EV against IV is read by Absorption (half-life ratio EV over IV). |
| T3p reused on IV group means (Distribution) | One shared result for the three modules with dose pair, matched times, family, status and limits. Check mean and SD scale (S1) and that the dose groups at one time point are independent, or use a valid paired method. Repeated sampling over time within a group does not prevent the Holm correction. The conclusion is limited to dose-normalised concentration at matched times. |

## S8. Precision evidence for a formal interval

Every uncertainty component large enough to change the conclusion has a traceable source, a scope that matches this analysis,
and a stated coverage or justified bounds. When a key component is missing, the formal status is CANNOT_ASSESS; where an
interpretable estimate exists, a sensitivity result may be reported beside it. The machine result keeps the precision source,
matched scope, degrees of freedom or coverage, and the components that entered the joint interval; the board uses the S6
short labels.

| Evidence | Requirement for a formal interval |
|---|---|
| Digitized data | Record assay error, sampling error of the group summary and figure-reading error separately. The reading range needs a figure-level basis (axis ticks, resolution, point overlap or a check against the source table). Keep the common shift from the calibration of one panel. A bounded reading error may be combined with the statistical interval. With only the project default of 5 % the result stays a sensitivity analysis. |
| Matched assay CV | Check source, method, analyte, matrix, concentration or QC level covered, within or between run, and the unit and meaning of the CV. A validation acceptance limit is not an observed CV. A prodrug and the active moiety formed from it are checked separately. When a group SD already contains assay variation, the same component is not counted twice. |
| Replicates | Record the number of independent replicates or the effective degrees of freedom, and whether the value is the precision of one measurement or of the replicate mean. The family-wise factor is applied to the standard error that matches the target. The quantile function must be checked for extreme tails. |
| GFR and fu in T10 | Source and physiological condition match the animals, dosing state and window. A single value, limits that are equal after rounding and a nominal fu of 1 are not zero error. Use justified physiological bounds, or include the statistical intervals in the joint coverage (S4). |

## S9. Flip-flop reading

Grade every qualified EV/IV window pair, then map each grade to a reading. Each cut includes its lower bound.

| EV/IV apparent terminal half-life ratio r | Grade | Reading |
|---|---|---|
| r < 0.80 | EV steeper | Review the windows and the comparability of the groups |
| 0.80 ≤ r < 1.25 | Approximately parallel | Compatible with a common terminal process |
| 1.25 ≤ r < 2.0 | Moderately shallower | Absorption-influenced candidate |
| r ≥ 2.0 | Markedly shallower | Absorption-influenced candidate |

- Record UNRESOLVED only when qualified window pairs give different readings. Report the ratio range and the number of
  qualified window pairs.
- NOT_ASSESSABLE: either route lacks a qualified window, or no reference is available; say which side is missing.
- INDIRECT_COMPARATOR: a comparable other EV curve or a literature IV terminal value, listed with its source and limits;
  indirect support at most. When the direct comparison lacks a window, its NOT_ASSESSABLE is kept as well.
- UNRESOLVED, NOT_ASSESSABLE and INDIRECT_COMPARATOR are not evidence against flip-flop.
- Board, candidate ranking and the Modeling hand-off read the same reading. Absorption owns this reading.

## S10. Order of the formal decision

Apply the steps in order and stop at the first that decides. Each check declares its own premises, minimum data and removal
unit; the module files and YAMLs refer to this one table (`decision_order`).

| Step | Formal decision |
|---|---|
| 1. Premises | Fail: CANNOT_ASSESS, with the reason (T10 with an unmatched GFR stops here even when the numeric ranges overlap). |
| 2. Interval or test basis | The basis required by S1, S4 and S8 is missing: CANNOT_ASSESS; SENSITIVITY_ONLY when a defined conditional calculation is possible. |
| 3. Full data | No contradiction on eligible data: NOT_EXCLUDED. With a contradiction, keep direction, margin and decisive observations. |
| 4. Removal check | As S2: SINGLE_POINT_SUPPORT or LOO_NOT_ASSESSABLE with NOT_EXCLUDED; both defer the formal exclusion and may be recorded together. |
| 5. Timing and widening | As S3. Assessable over the time range but contradiction or direction unstable: NOT_EXCLUDED, timing-sensitive. The time range makes the check invalid: CANNOT_ASSESS. A justified, prespecified widening removes the contradiction: NOT_EXCLUDED with BORDERLINE. |
| 6. All applicable steps passed | EXCLUDED_UNDER_STATED_ASSUMPTIONS, limited to the tested model combination and window. |

The formal result and any sensitivity calculation are recorded separately (`<test>_flags` and `<test>_sensitivity_flags`;
a reader that checks a flag reads both). A formal result that stops at step 1 or 2 carries only the reason for that step; the
assumptions, direction and removal results of a sensitivity calculation stay in its own record.

Quantified predose concentration:

- T6 tests the single-exponential decline after this dose. With an unexplained predose signal the formal result is
  CANNOT_ASSESS; a sensitivity reading may be kept under an explicitly stated, reasonable residue assumption.
- T7 can still be assessed when the residue is attributable to completed input into the central compartment of the same
  linear time-invariant system and the observation is still parent drug in that central compartment (superposed inputs then
  give a sum of exponentials with positive coefficients, so the slope of log C does not become more negative with time).
  "Input has stopped" alone does not guarantee this: after input into a peripheral compartment ends, the central concentration
  can already be falling while its rate of decline still increases. With residue of unknown source, ongoing input or an
  unconfirmed premise, the formal T7 is CANNOT_ASSESS.

## S11. Input contract and one reader

Facts that a check depends on are read from structured fields first; prose is a fallback and is labelled as such ("source text
(fallback)"). A missing field never takes a permissive default silently: the check that needs it reports it, and its formal
result is withheld (S12).

| Fact | Table metadata | Concentration column |
|---|---|---|
| Dose level (groups dose series) | `dose_mg_kg` | `dose_level_mg_kg` when one table holds several levels |
| Administered dose (divides: Vc and CL bounds, C/D, AUC/D) | the dose level | `dose_mg_kg` on a column that has `subject_id` |
| IV input duration (h; 0 = bolus) | `infusion_h` | `infusion_h` on a column that has `subject_id` |
| Clock of the source times | `time_origin` (START_OF_DOSING or END_OF_INFUSION) | — |

Order: run configuration, column, table metadata, then prose. A stated duration is not overridden by the word "injection".
With an input of known length and no stated clock, a result that depends on which samples follow the end of input is
sensitivity only (TIME_ORIGIN_NOT_STATED). The input contract record lists what is missing, conflicting or only in prose
(IV_INPUT_FROM_TEXT, IV_INPUT_DURATION_NOT_STATED, TIME_ORIGIN_NOT_STATED, TIME_ORIGIN_CONFLICT, TIME_ORIGIN_FROM_TEXT,
SUBJECT_DOSES_ONLY_IN_TEXT, SUBJECT_DURATIONS_ONLY_IN_TEXT, SUBJECT_DOSE_PARTIAL, DOSE_LEVEL_NOT_STATED). Every printed number
in every section is read by one reader after one normalisation of typographic minus signs, superscript powers of ten,
full-width digits and thin spaces. Text that is still not a complete number is not read; a printed limit with a number left
over after it is not read.

## S12. Premise gate for formal comparisons

A formal comparison between groups (dose groups, routes, matrices) checks its premises on every compared group, never on the
first one only, and fails closed: a premise that is unknown or differs between the groups makes the comparison CANNOT_ASSESS +
SENSITIVITY_ONLY, with the premise named. Premises: the same summary type (arithmetic means, geometric means or individual
values; a geometric mean needs an SD on the ln scale; an unstated type is one convention only within one source), a
convertible and common concentration unit, aligned times or a timing-error bound stated in the input with its source
(Absorption item 19), and stated sampling dependence (S1). Codes: SUMMARY_TYPE_CONFLICT, SUMMARY_TYPE_MIXED,
GEOMETRIC_MEAN_LINEAR_SD, SUMMARY_TYPE_NOT_STATED_ACROSS_SOURCES, UNIT_NOT_CONVERTIBLE, UNIT_MISMATCH, TIME_NOT_ALIGNED,
SAMPLING_DEPENDENCE_UNRESOLVED. A bound that rests on an assumption the samples cannot test is not a premise check; it may be
shown as an illustration only.

## S13. Plot and plain-word rules

These rules change what is drawn and written, never what is computed. They apply to the three modules and to both renderers
(R/ggplot2 and the matplotlib fallback), which draw the same plot specs.

1. **One clock.** Every time-course panel uses the time after the start of dosing, axis name "Time after start of dosing (h)".
   A section that computes on another clock (Distribution item 24 uses the time after the end of the input) converts back
   for display. Only two other axis names are allowed, and only when the clock cannot be fixed: "Reported time (h), input end
   unknown" and "Reported time during ongoing IV input (h)". All time panels of one figure have the same axis name.
2. **The IV input is drawn.** An IV input of known length is a light shaded band from 0 to its end, under the data, with a
   legend entry "IV infusion 0–X h". Profiles with different input lengths in one panel share one band to the longest, labelled
   with the range ("by animal"). A bolus or an input of unknown length gets no band. No free text such as "infusion stop".
3. **Every observation is drawn, alike.** Each quantified sample is drawn at its own time with the same symbol, whether or not a
   check uses it; samples inside the input are recognised by the band. Below-limit samples keep their own mark (open circle
   at the limit). No colouring or line that splits the samples into halves by count (early/late halves, split-half lines):
   the halves are a device of the screen, not phases.
4. **Point facts are marked on the data.** A note about one sample (last quantified sample, last sample, a later sample that is
   below the limit) is written next to that sample, and the sample is marked; corners are for readings of the whole panel.
5. *(Withdrawn 2026-11-25.)* Sample times are not printed next to the points; the first sample after the input is stated in
   the caption of the early close-up.
6. **Lines and axes say what they are.** A vertical line that bounds a calculation window has a legend entry naming the window
   (for example "AUC window 0.25–31 h"). A dose-normalised axis names its unit ("C / Dose (ug/mL per mg/kg)").
7. **Later doses are shown, not mixed in.** In a multiple-dose profile whose columns list their doses (`dose_events`), each later
   dose time is a dashed vertical line ("later doses at 24, 48 h"). In a group overview each animal's whole course (all doses) is
   one connected line in that animal's own colour, the samples after the second dose as open symbols of the same colour, and
   the caption states the regimen ("3 doses at 0, 24, 48 h; absorption readings use the first dosing interval only").
   Per-animal figures show only the first dosing interval. This is a dosing fact, not a count split (rule 3).
   Absorption reads only the first dose interval (up to and including a sample at the second-dose time).
8. **Plain PK words in figures.** Figure titles, legend entries and text inside a panel say in PK words what is drawn and what it
   shows (for example "A single exponential does not fit (beyond ±5 % and beyond assay noise)"). Internal codes (test names such
   as T1, T2, T6, T7; margins such as M_T2, U_b; item, table or question numbers; status enums such as CANNOT_ASSESS) do not
   appear in figure text; a short code may follow the plain words in brackets only where it is needed for traceability. A
   result that is better read as numbers is a table, not a figure (the Vc bounds of item 25 are a table). Every time in text
   and tables is after the start of dosing; for an infusion the time after its end may follow in brackets ("0.05 h (end of
   infusion + 1 min)").
9. **Standard title, question, reading.** Every figure carries three levels of text:
   - Title, standard and descriptive: "<Species> · <route> · <profile or group> (<dose>[, <input>]) — <plotted quantity> vs time,
     <linear | semi-log>", for example "Horse · IV · I002 (12.3 mg/kg, 2-min infusion) — plasma concentration vs time, semi-log".
     A plot that is not against time names both quantities ("Horse · IM · 6 animals (8.74–10 mg/kg) — Tmax by animal"). No
     panel codes, no test names and no questions in the title.
   - Subtitle: the question the figure is there to answer ("Is there a dip followed by a second rise?").
   - Caption below the plot: the reading, in at most two short plain sentences; a symbol is defined there or not used. The
     reading of a screen is a caption sentence.
   Markers are only standard PK marks: observed points, the infusion band, later-dose lines, Tmax/Cmax, the last quantified
   sample, BLQ, the terminal-fit line. Test constructions (error-limit chords and intervals, decisive triplets, binding points,
   delay bands, colouring by a screening reading) are not drawn; a figure that exists only to show such a construction (the
   single-exponential / speeding-up check, the C/t interval check) is not made, and its reading is a caption sentence of the
   standard profile figure. A missing input is reported as "Not supplied in this package: ...", not as a tool error.
10. **Plain words first.** Every reading a person or a downstream model reads first (the answer of each question and of the
   working hypothesis in the report pages, the overview paragraphs, the "in plain words" lines of model_context.txt and
   modeling_facts.txt) is two plain sentences: (1) what the plot shows; (2) the PK modelling suggestion. Example: "All 6 horses
   show a fast early decline followed by a slower terminal phase on the semi-log plot. Start with a two-compartment model
   (central + one peripheral); a one-compartment model does not describe the early points." Animal counts are allowed; beyond
   them the pair carries at most one number, and only when it changes a modelling choice (for example the starting value of the
   central volume). No codes, test names, ratios, z, tolerances, noise settings or "not a formal test" boilerplate in the pair;
   these stay in a collapsed "Numbers behind this" block under the pair and in the JSON. The wording comes only from the tool's
   own results, never from knowledge of a compound.
   - Scope: every reader-facing text of the three sections, the report sections and the portal cards. No rule ids, item
     numbers, internal codes or method boilerplate in the visible text (they stay in collapsed blocks, the JSON and the rules).
   - A section without figures says in one plain sentence why ("this study has IV dosing only, so there is no absorption phase
     to show"), never "0 figures".
   - Single-point removal checks are one plain sentence that names any animal whose shape depends on one point, not a table.
   - The working hypothesis names the recommended model first; a simpler model is mentioned only as the baseline it is
     compared with.
   - Elimination shows the terminal phase of each animal (the samples used, the fitted line, the half-life in the subtitle)
     and repeats the plasma profiles.

## Shared records

These records are written once and read by every section that needs them (machine form keys in brackets).

- **IV post-distribution window** (`iv_window`, name `iv_post_distribution_window`). One record for Distribution and
  Absorption, on the clock "time after the end of dosing" (no second shift when the source clock starts at the end of input).
  It keeps name, time basis, shift applied, precision basis, status (DETERMINED or NOT_DETERMINED), start and end time, sample
  times and ids, n, slope, rate, half-life and the reason when not determined (TOO_FEW_POINTS, LOW_POWER,
  SLOWING_IN_EVERY_SUFFIX, NO_NULL_SUFFIX, PROFILE_STEEPENING, SCREEN_NOT_ASSESSABLE). The slope is refitted on the samples the
  record lists.
- **Early mixing** (`early_mixing`). EARLY_MIXING_POSSIBLE means a sample within 5 minutes after the end of dosing, the bound
  included.
- **Source-reported predose zero** (`predose_zero`). Keeps its own status, REPORTED_ZERO_PREDOSE. It is never a quantified
  concentration and may anchor an area only where the section justifies it.
- **Question ids** (`question_ids`). Every row carries `qid` (stable), `guide_q`, `also_guide_q`, `legacy_q`,
  `display_number` and `display_ref`. Cross-module references use `section:qid` or `section:board_id:qid`; the working
  hypothesis names its rows that way. Each board records guide questions without a row of their own in `guide_coverage`
  (ROW, SHOWN_IN_ROW, NO_ENGINE_ROW). Upstream tests are cited with their own meaning: `absorption:T3`, `absorption:T3p`,
  `absorption:T5` (can one multiplier map one occasion's profile onto the other over the common window) and
  `distribution:T9` (are later-dose concentrations no lower than first-dose concentrations at matched times).

## Appendix A. Worked examples (not rules)

- S6, Elimination. Q1 with extravascular data only and an estimable window AUC is Answerable. Q3 with some required units
  assessed is Partly answerable, reporting units assessed, their results and the gap. Urine recovery estimable and paired renal
  clearance insufficient is Partly answerable, with clearance and the filtration reading reported per matched animal and
  interval. A reliable urine plus faeces sum of 30 % is Answerable for the window. A reported sum of 135 % is Partly answerable
  when the parts can still be interpreted; keep the raw values and note that denominator, window and double counting need
  checking.
- S5. Three of four required units with a formal contradiction plus one not assessable gives CONTRARY_EVIDENCE.
- S6. A formal "filtration alone not excluded" answers "can these data exclude filtration alone"; whether renal excretion is
  explained by filtration alone stays open.
- S7, sign test. With fewer than six non-tied animals the smallest two-sided p is 0.0625 or more; six in one direction give
  0.03125.
- S7, source-reported IV CL. A p of 0.61 is shown together with an upstream exclusion of dose proportionality.
- S8, replicates. At family-wise two-sided 95 % and m = 10 the factor is 2.813 for a known sigma (as the code computes it, t
  with df 1000; normal quantile 2.807) and 127.321 for one degree of freedom, applied to s/√2 for the mean of two independent
  log measurements. The quantile function truncates for larger families.
- S8, T10 probe. A renal clearance lower limit of 0.1544 excludes against a fixed filtration limit of 0.1500 and does not against
  a justified upper limit of 0.1800.
- S9. A ratio range of 1.90 to 2.10 is shown as "absorption-influenced candidate, half-life ratio 1.90 to 2.10, degree of
  shallowing varies with the window". A range of 1.20 to 1.30 spans two readings and stays UNRESOLVED. The short-IV case (all 12
  window pairs "markedly shallower", ratio 4.74, no qualified post-distribution IV window in Distribution) is handled by the
  shared IV window record.

## Appendix B. Open points and parts not yet implemented

- The machine form records S13.5 as `replaced_by: figure_titles`, while this text keeps the caption sentence of the early
  close-up; one of the two needs to follow the code.
- Open with George: the name of the timing flag in S3 (proposed TIMING_SENSITIVE; no module emits a timing flag yet) and
  whether the code NOT_ANSWERABLE_YET stays (assumed yes).
- The T10 parts of S2, S3, S4 and S8 are deferred in the code; Elimination r1.2 lists them. Until the code follows, T10 results
  carry the r1.1 behaviour named there.
- Code that implements these rules: `eda_common` (constants and functions named in the machine form; `std_title`,
  `title_problems`, `input_text`, `plain_absorption`, `plain_distribution`, `plain_elimination`, `plain_problems`,
  `reader_text`); `eda_absorption` (`TIME_AXIS`, `input_band`, `card_input_h`, `later_doses`, `_std`, `Q_SUB`, `attach_plain`,
  `_plain_html`, `_mc_plain`, `section_card`, `_render_mpl`); `eda_distribution` (`_band`, `_dstd`, `D_SUB`, `shape_caption`,
  `yes_no`, `_overview_paras`, `_model_steps_html`); `eda_elimination` (`terminal_phase`, `pEMT`, `_figures_html`);
  `modeling_facts.plain_summary`; renderers `absorption_figures.R`, `distribution_figures.R`, `elimination_figures.R`. Tests:
  `test_plot_rules_20261125.py`, `test_walkthrough_20261125.py`, `test_plain_words_20261125.py`.
