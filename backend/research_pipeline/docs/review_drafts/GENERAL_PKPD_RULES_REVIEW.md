# General PK/PD audit criteria — review draft

All 12 criteria remain disabled. This draft does not activate project thresholds or authorize scientific release.

Rules are additional scientific audit criteria, selected, adjusted, and versioned for each project. They are not a fixed execution workflow or regulatory certification.

## GEN-PKPD-001 — Define intended use and estimands

State whether the goal is description, index screening, or human extrapolation, with evidence requirements for each.

- Scope: All PK/PD projects
- Proposed action: HUMAN_REVIEW
- If unknown: NOT_CALCULABLE; define the objective first
- Avoid: Treating successful fitting as validated human prediction
- Numerical threshold: unset; define for the project after review.

[FDA Population Pharmacokinetics (2022)](https://www.fda.gov/media/128793/download). V.C: validation for the intended use.

## GEN-PKPD-002 — Identify experimental units and replicates

Record animals/subjects, strains, wells, repeated samples, and group summaries separately to avoid pseudoreplication.

- Scope: Animal studies; define in vitro experimental units separately
- Proposed action: WARN_AND_REVIEW
- If unknown: Report gaps; defer inference pending confirmation
- Avoid: Counting each blood sample as an independent animal or reconstructing individuals from means
- Numerical threshold: unset; define for the project after review.

[ARRIVE 2.0 — experimental unit](https://arriveguidelines.org/arrive-guidelines/study-design/1b/explanation). Essential 10, 1b; applying this to in vitro work is a project-specific extension.

## GEN-PKPD-003 — Assess data amount and coverage for the task

Use parameter precision, identifiability, and time/dose coverage to assess adequacy; no fixed species count.

- Scope: Tasks requiring parameter estimation or prediction
- Proposed action: HUMAN_REVIEW
- If unknown: NOT_CALCULABLE without project-specific criteria
- Avoid: Automatically declaring three species or a fixed N adequate
- Numerical threshold: unset; define for the project after review.

[FDA Population Pharmacokinetics (2022)](https://www.fda.gov/media/128793/download). V.C.1: parameter precision and data support.

## GEN-PKPD-004 — Trace assay quality, LLOQ, and BLQ

Record quantification method, matrix, and LLOQ; distinguish missing values, BLQ, and true zeros.

- Scope: Quantitative concentrations; record gaps in public-source documentation
- Proposed action: WARN_AND_REVIEW
- If unknown: Preserve the original state; follow the project analysis plan
- Avoid: Declaring data invalid solely because assay-validation documentation is unavailable
- Numerical threshold: unset; define for the project after review.

[ICH M10 Bioanalytical Method Validation (2022)](https://www.ema.europa.eu/en/documents/scientific-guideline/ich-guideline-m10-bioanalytical-method-validation-step-5_en.pdf). Assay fitness-for-purpose principles; state encoding is a proposed software implementation.

## GEN-PKPD-005 — Establish biological plausibility and parameter meaning

Support structures, covariates, and parameter definitions pharmacologically; distinguish apparent and absolute parameters.

- Scope: PK structural models and cross-species comparisons
- Proposed action: HUMAN_REVIEW
- If unknown: Check units, model conventions, and applicability
- Avoid: Applying the same parameter range or fixed allometric exponent to every drug
- Numerical threshold: unset; define for the project after review.

[FDA Population Pharmacokinetics (2022)](https://www.fda.gov/media/128793/download). V.B; CL/F checks are implementation proposals based on model definitions.

## GEN-PKPD-006 — Match free/total exposure, MIC, and infection site

Prioritize free exposure; justify total concentrations and match binding, MIC, and tissue matrix.

- Scope: Antimicrobial PK/PD; not automatically applicable to other drug classes
- Proposed action: WARN_AND_REVIEW
- If unknown: Do not calculate indices when critical conversion evidence is missing
- Avoid: Uncritically using another species' binding or treating lung homogenate as ELF
- Numerical threshold: unset; define for the project after review.

[EMA Antimicrobial PK/PD guideline (2016; effective 2017)](https://www.ema.europa.eu/en/documents/scientific-guideline/guideline-use-pharmacokinetics-and-pharmacodynamics-development-antimicrobial-medicinal-products_en.pdf). 4.2.3、4.3.3.

## GEN-PKPD-007 — Confirm PD endpoints and observation windows in advance

Define effect scale, baseline, time window, and strain; retain non-estimability when target effects are not reached.

- Scope: Antimicrobial infection or time-kill models
- Proposed action: HUMAN_REVIEW
- If unknown: Do not pool different times/endpoints as one comparison
- Avoid: Requiring the same bacterial kill magnitude for every drug
- Numerical threshold: unset; define for the project after review.

[EMA Antimicrobial PK/PD guideline (2016; effective 2017)](https://www.ema.europa.eu/en/documents/scientific-guideline/guideline-use-pharmacokinetics-and-pharmacodynamics-development-antimicrobial-medicinal-products_en.pdf). 4.2.1–4.2.3.

## GEN-PKPD-008 — Use comparable conditions for information criteria

Check observation sets, response scales, and likelihood comparability before ranking by AIC/BIC.

- Scope: Model selection using AIC/BIC
- Proposed action: BLOCK_INVALID_COMPARISON
- If unknown: Stop that ranking; retain individual fit results where appropriate
- Avoid: Directly ranking AIC values from different datasets
- Numerical threshold: unset; define for the project after review.

[R stats — AIC](https://stat.ethz.ch/R-manual/R-devel/library/stats/html/AIC.html). Details: likelihood and data conditions across fits.

## GEN-PKPD-009 — Assess uncertainty, convergence, and shrinkage together

Report estimation uncertainty and diagnostics; review the reliability of individual exposure estimates separately.

- Scope: Parameter estimation; shrinkage only for applicable population models
- Proposed action: WARN_AND_REVIEW
- If unknown: Flag non-identifiability or limits of use; configure thresholds per project
- Avoid: Using RSE<30% or a convergence flag as a universal acceptance threshold
- Numerical threshold: unset; define for the project after review.

[FDA Population Pharmacokinetics (2022)](https://www.fda.gov/media/128793/download). V.C.1: the consequences of shrinkage depend on intended use.

## GEN-PKPD-010 — Separate predictive checks from goodness of fit

Choose diagnostics, predictive checks, and independent validation for the intended use; describe the validation scope.

- Scope: Models used for prediction or translation
- Proposed action: HUMAN_REVIEW
- If unknown: Limit conclusions when evidence does not support the intended use
- Avoid: Treating the highest R² or lowest AIC as proof of clinical reliability
- Numerical threshold: unset; define for the project after review.

[FDA Population Pharmacokinetics (2022)](https://www.fda.gov/media/128793/download). V.C: complementary validation methods selected for intended use.

## GEN-PKPD-011 — Define the animal/in vitro-to-human bridge

Record species, infection-state, and population differences; label predictions without human PK as awaiting validation.

- Scope: Preclinical-to-human translation
- Proposed action: HUMAN_REVIEW
- If unknown: Retain translational research; do not claim validated human dosing recommendations
- Avoid: Treating animal targets or scenario PTA as a validated human regimen
- Numerical threshold: unset; define for the project after review.

[EMA Antimicrobial PK/PD guideline (2016; effective 2017)](https://www.ema.europa.eu/en/documents/scientific-guideline/guideline-use-pharmacokinetics-and-pharmacodynamics-development-antimicrobial-medicinal-products_en.pdf). 4.3–4.4: preclinical exploratory work can still proceed.

## GEN-PKPD-012 — Review regimen feasibility and safety separately

Assess effects, practical dosing constraints, and safety endpoints; unsupported thresholds remain unassessable.

- Scope: Clinical interpretation and regimen scenarios
- Proposed action: HUMAN_REVIEW
- If unknown: Record limitations; gather evidence or open another cycle
- Avoid: Automatically declaring a regimen safe because target attainment is high
- Numerical threshold: unset; define for the project after review.

[FDA Exposure–Response Relationships (2003)](https://www.fda.gov/media/71277/download). Clinical use and exposure–benefit/adverse-effect relationships; feasibility checklists are project proposals.
