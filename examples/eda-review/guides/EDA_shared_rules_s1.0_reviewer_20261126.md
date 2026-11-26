# EDA shared rules s1.0 · Reviewer guide

**Plain-language edition · 26 November 2026.** Review guide for the shared EDA rules used in DBG01 and DBG03. See the [technical rule text](../../../tools/eda/rules/EDA_shared_rules_s1.0_consolidated_20261125.md) and the [machine rules](../../../tools/eda/rules/shared_rules_s1.0.machine.yaml) for exact criteria and implementation references.

These rules apply to Absorption, Distribution and Elimination. The shared rule takes precedence if a section's rule differs.

## The checks named here

- **Single-exponential check (T6):** does the IV decline follow one straight line on a semi-log plot?
- **Speeding-up check (T7):** after input has ended, does the decline ever get steeper? In a linear system with central input
  it can only slow down or stay the same.
- **Dose-proportional exposure (T3):** is AUC per dose over a common window the same at every dose?
- **Dose-proportional concentration (T3p):** is concentration per dose the same at matched times?
- **Filtration check (T10):** can filtration alone (filtration rate × unbound fraction) explain renal clearance?

Every formal check ends in one of three results: **cannot be judged** (a premise or needed data is missing), **not ruled
out**, or **ruled out under the stated assumptions** (only for the model and window tested).

## 1. When group averages are good enough for a firm conclusion

**Guards against:** ruling out a model from averages whose spread or make-up is unknown.

**Needed:** the kind of average, whether the same animals are followed over time, whether samples are independent (when the
check needs it), a real spread from the source (SD, SE or interval), and a test that covers every comparison looked at (rule 4).

**Result:** anything missing → cannot be judged (the curve and a sensitivity reading are still shown). All known and no
conflict → not ruled out. All known and a conflict → go on to rules 2 and 3.

Per check:

- Single-exponential: only geometric means of the same animals, with spread on the log scale. Arithmetic means never rule it
  out. A change in sample count alone does not stop the check if the source still supports the fixed-cohort comparison.
- Dose-proportional exposure: firm only if each time used different animals (not assumed when unstated). Use the
  small-sample t value instead of 1.96.
- Filtration: never firm on group averages.
- Only the project's default noise → cannot be judged; the number is a sensitivity reading.

*Example:* arithmetic means of 6 horses, no SD, curve looks bent → we say it looks bent; formally "cannot be judged".

## 2. Is the conflict carried by one point?

**Guards against:** ruling out a model because of one odd sample (wrong tube, misread, wrong time).

**How:** leave out one sample at a time and rerun the same check.

**Result:** conflict stays every time → it counts. Conflict disappears without one sample → not ruled out, naming that
sample. Nothing can be left out, or too few data remain → not ruled out, saying why. Keep the full-data result and every rerun.

Per check: the single-exponential rerun needs 3 time points; dose-proportional concentration with one matched time cannot be
rerun; dose-proportional exposure keeps its window; the filtration check leaves out a urine interval and a plasma sample
separately.

*Example:* 8 IV samples don't fit one exponential; without the 2-h sample they do → "not ruled out; rests on the 2-h sample".

## 3. Is the conflict a near miss, or caused by uncertain times?

**Guards against:** a conflict that only just crosses the line, or that depends on sampling times that are not exact.

**Near miss:** always report how far the conflict is from the line. No safety margin of our own; a wider margin only if the
study set and justified one in advance. Conflict gone with that margin → not ruled out, "borderline". The 5 % default of the
dose-proportional concentration check is description only.

**Uncertain times:** if the paper shows the times are uncertain and it could matter, rerun over the possible times, keeping
their order. Conflict stays → passed. Conflict gone or flips → not ruled out, "sensitive to timing" (stated-time result kept).
Check no longer makes sense → cannot be judged.

*Example:* conflict at "about 1 h (0.75–1.25 h)" disappears at 0.75 h → "not ruled out, sensitive to timing".

## 4. Many comparisons at once

**Guards against:** finding a "significant" result just because many things were tested.

- Fix in advance: scope, what is analysed, which tests belong together, how they combine, and the level (default 5 %
  two-sided for the whole family).
- The family covers everything that could trigger the published conclusion, including all units considered when one was
  picked after seeing the data. Count each underlying interval once.
- Dose-proportional concentration: family = dose pairs × matched times.
- A study-level "ruled out" needs a rule fixed in advance: "at least one animal" needs study-wide control; "all animals" needs
  every animal to reject in the same direction, none dropped; "at least k" needs its own calibration.

## 5. Ranking candidate models

**Guards against:** dropping or promoting a model on weak or one-sided evidence.

Each candidate (a full model: input, disposition, starting state, what was measured) goes in one group: **reference**,
**supported**, **indirect support only**, **not tested**, or **evidence against** (stays on the list).

- Sensitivity-level conflict only → stays in its group; order changes only if the same observation separates the pair.
- Formal conflict in some animals → "evidence against"; report required, assessed and conflicting counts.
- Formal conflict in every required animal, same direction → ruled out for the study. A ruled-out benchmark may still be shown
  as a comparison fit.
- Required animals are fixed in advance; one that cannot be assessed stays in the count; one the check does not apply to is not.
- Direction follows what each model predicts. A reliable fast-then-slow decline can put peripheral exchange first. A late
  steepening argues against both one-compartment and linear multi-compartment models. A failed single-exponential check alone
  does not favour two compartments.
- Within a group: more independent evidence first (one curve counts once), then the simpler model. Indistinguishable → tie.

*Example:* 3 of 4 animals formally conflict and 1 cannot be assessed → "evidence against", not ruled out.

## 6. How well each question is answered

The status says how far the data answer a question, not which way.

| Status | When |
|---|---|
| Answerable (可回答) | Every required unit reaches the needed evidence level. |
| Partly answerable (部分可回答) | Only some units or sub-questions, or only a conditional answer. |
| Insufficient evidence (证据不足) | The question applies but nothing answers it yet. |
| Not applicable (不适用) | The study design makes the question void. |

- Judge each result, then combine; row order does not matter.
- A limitation is attached to the conclusion it limits (unknown bioavailability limits oral clearance, not the window AUC).
- A fragile result (sensitivity only, one-point, removal check not possible, borderline, or conditional on an assumed label or
  cohort) is passed on with its reason and makes the question partly answerable at most.
- If a speeding-up conflict could not be checked for one-point dependence, nothing may assume "no speeding-up" (such as
  extrapolating the tail). Exception: if only assay-error information is missing, the curve's descriptive screen is clean and
  the other premises hold, a separately labelled sensitivity estimate is allowed.
- The page shows a short status, the finding and one sentence on the limit.

*Example:* urine recovery estimable but renal clearance not → partly answerable.

## 7. Checks that exist only in the code

**Guards against:** conclusions drawn from numbers no rule covers.

Numbers may be reported and described freely. A mechanism, ranking or formal result needs a named check. A registered
descriptive screen gives indirect support at most. Registered:

- **Renal sign test (Elimination):** description only (per-animal ratios, median, range, sources); never "tested" or
  "suggests secretion". The filtration check stays the formal one.
- **Re-comparing IV clearance reported by the paper (Elimination):** ratio, interval, pairing and source, corrected with the
  other dose comparisons (rule 4); partly answerable at most; always shown next to any dose-proportionality result.
- **Peak-per-dose screen (Absorption):** peak per dose below ½ or above 2× while AUC per dose is within 0.80–1.25; needs
  sampling around the peak; indirect support at most.
- **Dose patterns (Distribution):** described by shape only. If dose and animal are confounded: show the comparison, name no
  mechanism.
- **1.5-fold similar/different grading:** deleted.
- **Dose-proportional concentration on IV group means:** one shared result for all sections; check the means and spread
  (rule 1) and that dose groups are independent at each time.

## 8. Precision needed for a formal interval

**Guards against:** a "firm" interval built on an uncertainty we cannot trace.

Every uncertainty large enough to change the answer needs a source that fits this study. If a key one is missing → cannot be
judged (a sensitivity reading may be shown).

- **Data read from figures:** assay error, group spread and reading error are kept apart; reading error needs a basis in the
  figure. Only the default reading error → sensitivity only.
- **Assay CV:** must match method, analyte, matrix and range; a validation limit is not an observed CV; prodrug and active drug
  are separate; do not count assay noise twice.
- **Replicates:** record how many and whether precision is for one value or the mean.
- **Filtration rate and unbound fraction:** must match the animals and window; a single value, or an unbound fraction of 1, is
  not error-free.

## 9. Flip-flop reading

**Guards against:** mistaking slow absorption for slow elimination.

Compare the terminal half-life after extravascular dosing with IV, for every usable pair of windows:

| Ratio (extravascular / IV) | Reading |
|---|---|
| below 0.80 | Steeper: check windows and group comparability |
| 0.80 to below 1.25 | Approximately parallel: compatible with a common terminal process |
| 1.25 to below 2.0 | Moderately shallower: absorption-limited candidate |
| 2.0 or more | Markedly shallower: absorption-limited candidate |

- Unresolved only when window pairs disagree. No usable window on one side → cannot be assessed (say which side). A literature
  IV value or another oral curve is indirect support at most.
- Unresolved, unassessable or indirect is not evidence against flip-flop.
- Absorption owns this reading; every page and the modelling hand-off use the same one.

*Example:* ratios 1.20–1.30 span two readings → unresolved.

## 10. Order of the formal decision

Go in order; stop at the first step that decides.

1. **Premises** not met → cannot be judged (the filtration check stops here if the filtration rate does not fit the animals).
2. **Basis** for an interval or test missing (rules 1, 4, 8) → cannot be judged; sensitivity reading if possible.
3. **Full data:** no conflict → not ruled out.
4. **One point** (rule 2): carried by one point or not checkable → not ruled out.
5. **Near miss / timing** (rule 3) → not ruled out (borderline or timing-sensitive), or cannot be judged.
6. **All passed** → ruled out under the stated assumptions.

Formal and sensitivity results are kept apart.

**Concentration before the dose:** the single-exponential check → cannot be judged if the predose signal is unexplained
(sensitivity reading allowed). The speeding-up check still works if the residue is from earlier central input into the same
linear system and we still measure parent drug there. "Input has stopped" alone is not enough: after peripheral input ends, the
central decline can still be getting steeper.

## 11. Where facts come from

**Guards against:** a check silently using a wrong default.

Order: run settings, per-animal column, table, then paper text (labelled "source text (fallback)"). A missing fact is reported
and the formal result withheld. Facts: dose level, dose each animal received, IV input length (0 = bolus), and the clock of the
reported times (start of dosing or end of infusion). A stated duration beats the word "injection". Known input length but
unknown clock → results that depend on it are sensitivity only.

All sections read printed numbers with one reader that tidies minus signs, powers of ten, full-width digits and thin spaces.
Anything still not a complete number is not read.

## 12. Premises before comparing groups

**Guards against:** comparing groups that are not on the same footing.

Check every group, not only the first: same kind of summary (a geometric mean needs a log-scale spread), convertible units,
aligned times (or a stated timing bound), and stated sample dependence. Unknown or different → cannot be judged, sensitivity
only, premise named. A bound resting on an untestable assumption is an illustration only.

## 13. Figures and plain words

These change what is drawn and written, never what is calculated. Both drawing routes (R and Python) follow them.

1. **One clock.** Time axes read "Time after start of dosing (h)". Only if the clock cannot be fixed: "Reported time (h), input
   end unknown" or "Reported time during ongoing IV input (h)". One axis name per figure.
2. **IV input band.** A known-length infusion is a light band from 0 to its end, legend "IV infusion 0–X h"; different lengths
   share one band to the longest ("by animal"). No band for a bolus or unknown length.
3. **Every sample drawn alike**, used or not. Below-limit samples are open circles at the limit. Never split samples by count
   (no early/late halves).
4. **Notes about one sample** sit on that sample; panel corners are for whole-panel readings.
5. *(Withdrawn 2026-11-25.)* No sampling times printed by the points; the first sample after the input is named in the caption
   of the early close-up.
6. **Lines and axes say what they are**, e.g. "AUC window 0.25–31 h", "C / Dose (ug/mL per mg/kg)".
7. **Later doses are shown, not mixed in.** Dashed lines mark them ("later doses at 24, 48 h"). Group overviews: one line per
   animal over all doses, open symbols after the second dose, caption states the regimen. Single-animal figures and absorption
   readings use the first dosing interval only.
8. **PK words in figures.** No test names, margins, item numbers or status codes; a short code in brackets only where needed
   for tracing. Results better read as numbers go in a table. Times are after start of dosing ("0.05 h (end of infusion +
   1 min)").
9. **Title, question, reading.**
   - Title: "Horse · IV · I002 (12.3 mg/kg, 2-min infusion) — plasma concentration vs time, semi-log". No codes or questions.
   - Subtitle: the question, e.g. "Is there a dip followed by a second rise?".
   - Caption: the reading in at most two plain sentences.

   Only standard PK marks are drawn (points, infusion band, later-dose lines, Tmax/Cmax, last measured sample, below-limit
   samples, terminal fit). Test workings are not drawn, and a figure that would only show them is not made. A missing input
   reads "Not supplied in this package: ...".
10. **Plain words first.** Every first-read answer is two sentences: what the plot shows, then the modelling suggestion.
    Animal counts are fine; at most one other number, only if it changes a modelling choice. Codes, ratios and boilerplate go
    in a collapsed "Numbers behind this" block. Wording comes only from the tool's results, never from knowledge of the drug.
    No figures → one sentence why, never "0 figures". A one-point check is one sentence naming the animal. The recommended
    model comes first. Elimination shows each animal's terminal phase and the plasma profiles.

    *Example:* "All 6 horses show a fast early decline followed by a slower terminal phase. Start with a two-compartment model;
    a one-compartment model does not describe the early points."

## 14. Results shared between sections

Worked out once, used everywhere:

- **IV window after distribution:** found by Distribution, reused by Absorption; times counted from the end of dosing (no
  double shift). Keeps its samples, refitted slope and half-life, or the reason none was found (too few points, too little
  power, slowing in every window, no window passes, steepening, or screen not run).
- **Early mixing:** a sample within 5 minutes after the end of dosing (5 included).
- **Predose zero reported by the paper:** kept as reported, never a measured value; anchors an area only where the section
  justifies it.
- **Question numbering:** stable ids across sections, with guide and old engine numbers; guide questions without their own row
  are recorded.

## Open points

- The machine file marks rule 13.5 as replaced by the title rule; this text keeps the caption sentence. One must follow the code.
- To decide with George: the name of the timing-sensitive note (rule 3), and whether "insufficient evidence" keeps its code.
- The code does not yet do the filtration-check parts of rules 2, 3, 4 and 8; until then filtration results behave as in
  Elimination r1.1.
