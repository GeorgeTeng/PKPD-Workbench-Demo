# CC005 - Scientific preservation and PK terminology

**CC pack 1.31.0 | checklist 2.0.0 | terminology 2.0.0**

## How the merged checklist works

First check the applicable preservation categories below, then consult their mapped PK term groups. A term match cannot prove a scientific relationship. A missing term does not authorize dropping source content. An empty mapping does not remove a category.

CC009 owns role/evidence classification; CC011 owns source citations; CC012 owns review and release. The glossary does not select a model, fill data, convert units or impose scientific acceptance thresholds.

## 1. Mandatory preservation categories

### 1. Quantities and units

- Numerical values, ranges, precision and uncertainty as reported.
- Units, denominators and normalization bases, including mg versus mg/kg and absolute versus body-weight-normalized parameters.
- Thresholds and comparison operators, including >, >=, <, <= and equality.

PK appendix: CPK01 (Dose input and absorption), CPK02 (Concentration and exposure), CPK03 (Distribution and elimination), CPK04 (Free, total and tissue exposure).

### 2. Drug and analyte identity

- Drug, formulation and measured analyte identities.
- Distinctions among active drug, prodrug, metabolites and measured components.
- Whether doses or concentrations refer to salt mass, active-moiety mass or another stated basis.

PK appendix: Use these source-preservation clauses and supporting metadata; no dedicated PK term group.

### 3. Biological context

- Species, population, experimental condition and relevant physiological or disease state.
- Sample matrix and sampling site, including plasma, serum, whole blood, tissue and ELF.
- Free, total or bound concentration basis.

PK appendix: CPK04 (Free, total and tissue exposure).

### 4. Dosing definitions

- Administration route, dose, frequency and dosing interval.
- Bolus versus infusion, infusion duration and administration rate.
- Single versus repeated dosing, loading versus maintenance dosing, and steady-state status when stated.

PK appendix: CPK01 (Dose input and absorption).

### 5. Time definitions

- Time units, time origin and relationship to dose administration.
- Sampling times, dose occasions and observation windows.
- Exposure integration windows, including AUC0-24, AUC0-infinity and AUC over a dosing interval.

PK appendix: CPK01 (Dose input and absorption), CPK02 (Concentration and exposure), CPK03 (Distribution and elimination).

### 6. Endpoints and comparators

- Endpoint definition, calculation, assessment time and direction of effect.
- Absolute outcomes versus changes from baseline or differences from a control.
- Comparator identity and reference values, including the stated MIC definition and its associated strain or experiment.

PK appendix: CPK08 (PK/PD handoff).

### 7. Experimental units and data levels

- Individual observations versus group summaries or pooled samples.
- Independent animals, subjects or biological replicates versus repeated measurements or technical replicates.
- Sample-size meaning: animals, groups, samples, time points or observations.

PK appendix: CPK05 (Model structure and estimation).

### 8. Statistical summaries

- Mean, median, geometric mean and other reported summary definitions.
- SD, SEM, CV, confidence intervals, credible intervals and prediction intervals as distinct quantities.
- Reported interval levels and uncertainty methods when stated.

PK appendix: CPK06 (Evaluation and uncertainty).

### 9. Variable and parameter definitions

- Variable meanings, parameterization and estimands.
- Distinctions such as CL versus CL/F and Vc versus Vss or terminal volume.
- Equations and operational definitions needed to interpret or reproduce the stated method.

PK appendix: CPK03 (Distribution and elimination), CPK05 (Model structure and estimation), CPK07 (Animal-to-human translation), CPK08 (PK/PD handoff).

### 10. Transformations and normalization

- Original versus transformed values, including logarithm base when stated.
- Absolute versus dose-normalized, weight-normalized or baseline-normalized quantities.
- Absolute bacterial counts versus logarithmic counts or changes in bacterial counts.

PK appendix: CPK02 (Concentration and exposure), CPK08 (PK/PD handoff).

### 11. Information status

- Observed, estimated, predicted, assumed and planned quantities.
- Reported findings versus hypotheses or proposed analyses.
- BLQ, other censoring, missing, zero and not-measured values as distinct states.
- Applicable quantification limits and censoring conventions when stated.

PK appendix: CPK04 (Free, total and tissue exposure), CPK05 (Model structure and estimation).

### 12. Relationships and matching

- Links among study, species, subject or group, treatment, dose, occasion, sampling time and outcome.
- Exposure-to-response, strain-to-MIC and specimen-to-analyte matching when explicitly established.
- Restrictions on pooling, pairing, joining or comparing records across studies or groups.
- Uncertain relationships must remain uncertain; matching must not be invented.

PK appendix: CPK04 (Free, total and tissue exposure), CPK07 (Animal-to-human translation), CPK08 (PK/PD handoff).

### 13. Logic scope and exceptions

- AND versus OR, conditional clauses, prerequisites and triggers.
- Negation, permissions, prohibitions, exceptions and qualifiers such as only, before and after.
- Which population, dataset, method, stage or circumstance each statement applies to.
- Development, model-selection and validation restrictions, including holdout and sensitivity-only use.

PK appendix: Use these source-preservation clauses and supporting metadata; no dedicated PK term group.

## 2. Compact supporting information

Bind to drug/analyte, study/analysis, species and subject/group; retain other descriptors only when consequential. Never infer a match from species alone.

- Preserve units, time origin/window, raw versus digitized and individual versus summary data, sampling unit and n; mean/median and SD/SEM/CV are distinct. Do not infer serial identity from destructive sampling.
- Keep BLQ/BQL, LLOQ/ULOQ, LOD, missing and zero distinct; preserve assay limits and missingness reasons. Never invent a limit or treatment policy.

## 3. PK terminology appendix

Terms in a row are related, not interchangeable. Only declared aliases map alternative names; source-defined symbols need the original definition. CORE means foundational terminology, not required fields in every proposal. CONDITIONAL groups apply when relevant.

### CPK01. Dose input and absorption (CORE)

| Concept | Terms | Distinction / binding check |
|---|---|---|
| Dose amount | dose per administration, total daily dose, loading dose, maintenance dose | Retain amount, units, formulation and absolute versus body-weight-normalized basis; one administration is not one day. |
| Dosing schedule | dosing interval, number of doses, single dose, multiple dose; aliases: tau = dosing interval | Keep route and schedule with the dose; do not infer either from a concentration curve. |
| Administration input | IV bolus, IV infusion, infusion rate, infusion duration, extravascular administration | Bolus and infusion have different inputs; retain rate and duration separately. Preserve any named extravascular route. |
| Absorption rate and delay | ka, absorption lag time, mean transit time, depot; aliases: Tlag = absorption lag time, MTT = mean transit time | ka is an absorption rate constant; lag and transit times are distinct delay representations, not elimination half-lives. |
| Extent of systemic availability | absolute bioavailability, relative bioavailability; source-defined symbols: F, Frel | Confirm the source definition and reference route/formulation; do not assign an absolute F from a relative comparison. |

References: [S07](https://pubmed.ncbi.nlm.nih.gov/33150591/), [S08](https://pubmed.ncbi.nlm.nih.gov/36718051/), [D02](https://humanpred.github.io/pknca/articles/v09-secondary-parameters.html).

### CPK02. Concentration and exposure (CORE)

| Concept | Terms | Distinction / binding check |
|---|---|---|
| Concentration summaries | Cmax, Tmax, Cmin, Ctrough, Cavg, C0 | Retain sampled versus model-derived values and the time window. Cmin is the interval minimum; Ctrough is tied to predose timing. C0 may be extrapolated. |
| Concentration-time integral | AUC, AUC0-t, AUC0-inf, AUC0-24, AUCtau, partial AUC | Preserve integration limits, time units, sampling origin and first-dose versus steady-state status. Extrapolated and observed-window exposure differ. |
| Time-weighted exposure and residence | AUMC, MRT | AUMC is the first moment of the concentration-time curve; MRT is mean residence time. Preserve route, integration window and input-duration correction; MRT is not MTT or half-life. |
| Repeated-dose exposure | steady state, accumulation ratio, peak-to-trough ratio; aliases: Rac = accumulation ratio | Specify which metric is ratioed and its reference dose/window; a simulated steady-state profile is not an observed one. |
| Dose-exposure relationship | dose-normalized concentration, dose-normalized AUC, dose proportionality, dose-exposure power model; aliases: C/Dose = dose-normalized concentration | Retain the normalization denominator and fitted slope/interval. Nonproportional exposure alone does not identify its mechanism. |

References: [S02](https://pubmed.ncbi.nlm.nih.gov/23007438/), [D01](https://humanpred.github.io/pknca/articles/v05-auc-calculation-with-PKNCA.html), [D02](https://humanpred.github.io/pknca/articles/v09-secondary-parameters.html), [D03](https://humanpred.github.io/pknca/articles/v06-half-life-calculation.html), [D04](https://humanpred.github.io/pknca/articles/v03-selection-of-calculation-intervals.html).

### CPK03. Distribution and elimination (CORE)

| Concept | Terms | Distinction / binding check |
|---|---|---|
| Clearance measures | CL, CL/F, CLu, CLR, CLH, CLint | Separate systemic, apparent, unbound, renal, hepatic and intrinsic clearance. Bind each to its concentration basis, units and organ/system definition; do not cancel an unknown F. |
| Distribution volumes | Vc, Vp, Vss, Vz, V/F | Central, peripheral, steady-state, terminal-phase and apparent volumes differ. V1/V2 labels need the source compartment mapping; Vss alone is not Vc. |
| Intercompartmental exchange | intercompartmental clearance, k12, k21; source-defined symbols: Q | Confirm the source meaning of Q; organ blood flow may use the same symbol. Exchange clearance and first-order transfer constants have different units. |
| Elimination and curve slopes | k10, kel, alpha, beta, lambda_z | Distinguish model micro-rate constants from hybrid exponential slopes and the estimated terminal slope; compartment assumptions govern any equality. |
| Half-life | terminal half-life, distribution half-life, absorption half-life | Retain the phase and estimation window. After extravascular dosing, a terminal slope can reflect absorption rather than elimination. |
| Urinary recovery | amount excreted unchanged, fraction excreted unchanged; aliases: Ae = amount excreted unchanged, fe = fraction excreted unchanged | Keep collection window and dose denominator; link renal clearance to the matching plasma exposure interval. |

References: [S01](https://link.springer.com/article/10.1007/BF01059626), [S05](https://pmc.ncbi.nlm.nih.gov/articles/PMC6765694/), [S07](https://pubmed.ncbi.nlm.nih.gov/33150591/), [D02](https://humanpred.github.io/pknca/articles/v09-secondary-parameters.html), [D03](https://humanpred.github.io/pknca/articles/v06-half-life-calculation.html).

### CPK04. Free, total and tissue exposure (CORE)

| Concept | Terms | Distinction / binding check |
|---|---|---|
| Concentration basis | total concentration, unbound concentration, bound fraction, unbound fraction, fAUC, fCmax; aliases: free concentration = unbound concentration, fu = unbound fraction | Bound and unbound fractions differ; do not apply an unbound conversion twice or treat nonspecific assay adsorption as protein binding. For fAUC/fCmax, retain the source's free-exposure definition and window. |
| Binding measurement | fu,p, fu,b, concentration-dependent binding, equilibrium dialysis, ultrafiltration, nonspecific binding; aliases: fup = fu,p, fub = fu,b, NSB = nonspecific binding | Retain matrix, species, method, concentration range and measured versus assumed status; animal binding does not establish human binding. |
| Site-specific exposure | blood-to-plasma ratio, tissue-to-plasma ratio, Kp, Kp,uu, epithelial lining fluid, lung homogenate, microdialysis; aliases: ELF = epithelial lining fluid | Keep ratio numerator/denominator, free/total basis and concentration versus AUC basis. Plasma, serum, blood, ELF and homogenate are distinct; retain sampling/dilution corrections. |

References: [S07](https://pubmed.ncbi.nlm.nih.gov/33150591/), [S08](https://pubmed.ncbi.nlm.nih.gov/36718051/), [S09](https://doi.org/10.3390/antibiotics13010072), [S12](https://pubmed.ncbi.nlm.nih.gov/15932954/).

### CPK05. Model structure and estimation (CORE)

| Concept | Terms | Distinction / binding check |
|---|---|---|
| Noncompartmental analysis | noncompartmental analysis, linear trapezoidal integration, linear-up/log-down integration, AUC extrapolated fraction; aliases: NCA = noncompartmental analysis | NCA is an analysis approach, not a compartment count; keep the integration and terminal extrapolation methods. |
| Compartment structure | one-compartment model, two-compartment model, three-compartment model; aliases: 1C = one-compartment model, 2C = two-compartment model, 3C = three-compartment model | Keep input, elimination and parameterization with compartment count; a curved plot alone does not choose a structure. |
| Kinetic assumptions | first-order kinetics, zero-order kinetics, Michaelis-Menten elimination, Vmax, Km, flip-flop kinetics | Separate rate law from compartment count. A saturable model is not evidence that saturation occurred; preserve which process is nonlinear. |
| Fitting level | nonlinear least squares, group-mean curve fit, nonlinear mixed-effects model; aliases: NLS = nonlinear least squares, NLME = nonlinear mixed-effects model, NLMEM = nonlinear mixed-effects model | Do not equate pooled/mean fits with individual mixed-effects fits or reconstruct animal identities from summary curves. |
| Variability components | interindividual variability, interoccasion variability, residual unexplained variability, random-effects covariance, eta, epsilon; aliases: IIV = interindividual variability, IOV = interoccasion variability, RUV = residual unexplained variability | Variability and parameter-estimation uncertainty differ; retain covariance/correlation and the experimental unit. Do not invent IIV from mean data. |
| Observation model | additive error, proportional error, combined error, log-normal error, censored likelihood, M3 | Keep response scale, error assumptions and BLQ handling. A censoring method name does not supply a missing quantification limit. |
| Estimation algorithms | FOCEI, SAEM, maximum likelihood, Bayesian estimation | FOCEI and SAEM are estimation algorithms, not compartment models. Retain objective, approximation, priors and convergence information where stated. |
| Execution software | nlmixr, nlmixr2, NONMEM, Monolix | Software/version is distinct from the model and algorithm; naming a tool neither selects a method nor proves it was run. |

References: [S02](https://pubmed.ncbi.nlm.nih.gov/23007438/), [S03](https://pmc.ncbi.nlm.nih.gov/articles/PMC2691472/), [S05](https://pmc.ncbi.nlm.nih.gov/articles/PMC6765694/), [S06](https://ascpt.onlinelibrary.wiley.com/doi/10.1002/psp4.12471).

### CPK06. Evaluation and uncertainty (CONDITIONAL)

| Concept | Terms | Distinction / binding check |
|---|---|---|
| Fit and comparison criteria | log likelihood, OFV, AIC, AICc, BIC, R-squared; aliases: R2 = R-squared | Retain observation set, likelihood/response scale, parameter count and comparison scope; a best score alone does not validate prediction. |
| Residual diagnostics | observed versus predicted, residual versus time, residual versus prediction, WRES, CWRES, IWRES | Keep residual definition and conditioning; an image path or scalar summary is not evidence that a residual plot was visually reviewed. |
| Simulation-based checks | VPC, pcVPC, NPC, NPDE | Use the named diagnostic only with its data/design and predictive distribution; mixed-effects diagnostics are not blanket obligations for every PK model. |
| Uncertainty summaries | confidence interval, prediction interval, credible interval, relative standard error, bootstrap, sensitivity analysis; aliases: CI = confidence interval, RSE = relative standard error | Retain interval level, target and resampling unit; parameter uncertainty, future observations and assumed population variability differ. |
| Estimation reliability | convergence, identifiability, parameter correlation, condition number, shrinkage | Optimizer success is not identifiability. Distinguish parameter-estimate correlation from random-effects correlation; preserve failed or unavailable checks. |

References: [S04](https://pubmed.ncbi.nlm.nih.gov/21302010/), [S05](https://pmc.ncbi.nlm.nih.gov/articles/PMC6765694/), [S11](https://pubmed.ncbi.nlm.nih.gov/18215437/).

### CPK07. Animal-to-human translation (CONDITIONAL)

| Concept | Terms | Distinction / binding check |
|---|---|---|
| Interspecies scaling | allometric scaling, allometric coefficient, allometric exponent, reference body weight, unbound-clearance scaling | Retain predicted parameter, weight basis, species set and estimated versus fixed exponent; no exponent or binding correction is universally supplied by this glossary. |
| In vitro to in vivo extrapolation | in vitro to in vivo extrapolation, in vitro intrinsic clearance, unbound fraction in incubation, organ blood flow, extraction ratio; aliases: IVIVE = in vitro to in vivo extrapolation, fu,inc = unbound fraction in incubation | Preserve system, units, physiological scaling factors and equations. Incubation, plasma and blood binding are not interchangeable. |
| Human concentration-time prediction | predicted human clearance, predicted human distribution volume, human IV simulation, prospective prediction | Keep compatible parameter sets, compartment structure and dosing input. CL and Vss do not uniquely identify an arbitrary multicompartment curve. |
| Prediction evaluation | held-out species, independent validation, fold prediction error, prediction bias, prediction precision | Retain validation target and error definition. Animal holdout performance is not target-drug human validation; no human data means human outputs remain prospective. |

References: [S01](https://link.springer.com/article/10.1007/BF01059626), [S07](https://pubmed.ncbi.nlm.nih.gov/33150591/), [S10](https://pure.eur.nl/en/publications/the-magnitude-of-the-pharmacodynamic-index-for-noso-502-pathogen-/), [S12](https://pubmed.ncbi.nlm.nih.gov/15932954/).

### CPK08. PK/PD handoff (CONDITIONAL)

| Concept | Terms | Distinction / binding check |
|---|---|---|
| Susceptibility measurement | MIC, MIC50, MIC90, broth microdilution | Retain isolate, method and conditions. A population MIC90 is not a matched isolate MIC; MIC is not EC50. |
| Exposure indices | fAUC/MIC, fCmax/MIC, fT>MIC, %fT>MIC, dose fractionation | Retain free exposure, MIC pairing and exposure window. Explicitly distinguish duration, fraction and percentage for time above MIC; an index is not its effect target. |
| Exposure-response models | Emax, EC50, Hill coefficient, effect compartment, ke0 | Keep response definition, sign, units and source parameterization; maximum effect, half-maximal exposure and slope are separate parameters. |
| Effect target | change in log10 CFU, stasis, 1-log kill, 2-log kill, resistance suppression, regrowth | Retain baseline/comparator and endpoint time; growth inhibition, bacterial killing and resistance suppression are different objectives. |
| Target attainment | PK/PD target magnitude, PTA, CFR, MIC distribution, Monte Carlo simulation, virtual population | Bind target, regimen, MIC and population assumptions. MIC-specific attainment and MIC-weighted summaries differ; PTA is not cure probability and assumed human IIV remains a scenario. |

References: [S07](https://pubmed.ncbi.nlm.nih.gov/33150591/), [S08](https://pubmed.ncbi.nlm.nih.gov/36718051/), [S09](https://doi.org/10.3390/antibiotics13010072), [S10](https://pure.eur.nl/en/publications/the-magnitude-of-the-pharmacodynamic-index-for-noso-502-pathogen-/).

The [terminology reading record](PK_TERMINOLOGY_REVIEW.md#literature-reading-record) states which abstracts, sections and documentation were inspected. These references support terminology; they do not validate this compression algorithm.

## 4. Boundaries and review criteria

- Preserve these details when stated and relevant; this is not a requirement that every proposal contain every listed item.
- Do not infer absent definitions, silently reconcile conflicts or create unsupported relationships.
- Do not silently convert units, transform values, normalize data or replace reported quantities during compression.
- Use CC006 for unspecified information and CC002/CC011 for evidence provenance.
- The compressed content supports the same scientific interpretation and permitted downstream actions as the source.
- Consequential definitions, conditions and relationships remain explicit or unambiguous.
- Any consequential omission, alteration or unsupported inference requires revision.
- Faithfully retained source uncertainty is not an extraction error; it must remain visible for downstream resolution.

The canonical checklist is `cc005_details.json`; the canonical terminology is `pk_binding_knowledge.json`. The runtime sends one copy of the terminology profile to assigned agents. This combined review is generated from both.
