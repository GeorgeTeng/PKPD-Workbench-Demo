# C - PK terminology review

**Version 2.0.0 | English | 8 groups | 41 concept families**

**Reading order:** dose input -> exposure -> disposition -> exposure basis -> modeling. Evaluation, translation and PK/PD are conditional extensions.

Each concept has one home. Terms in a row are related, not necessarily synonyms; aliases are explicitly identified. Symbols require the source definition. The glossary helps bind evidence and does not select models, add project requirements or exclude unfamiliar terms. English terminology does not restrict the language of source documents.

## Supporting metadata

Bind to drug/analyte, study/analysis, species and subject/group; retain other descriptors only when consequential. Never infer a match from species alone.

## Core PK terms

### 1. Dose input and absorption

| Concept | Terms | Binding check |
|---|---|---|
| Dose amount | dose per administration, total daily dose, loading dose, maintenance dose | Retain amount, units, formulation and absolute versus body-weight-normalized basis; one administration is not one day. |
| Dosing schedule | dosing interval, number of doses, single dose, multiple dose; aliases: tau = dosing interval | Keep route and schedule with the dose; do not infer either from a concentration curve. |
| Administration input | IV bolus, IV infusion, infusion rate, infusion duration, extravascular administration | Bolus and infusion have different inputs; retain rate and duration separately. Preserve any named extravascular route. |
| Absorption rate and delay | ka, absorption lag time, mean transit time, depot; aliases: Tlag = absorption lag time, MTT = mean transit time | ka is an absorption rate constant; lag and transit times are distinct delay representations, not elimination half-lives. |
| Extent of systemic availability | absolute bioavailability, relative bioavailability; source-defined symbols: F, Frel | Confirm the source definition and reference route/formulation; do not assign an absolute F from a relative comparison. |

Terminology references: [S07](https://pubmed.ncbi.nlm.nih.gov/33150591/), [S08](https://pubmed.ncbi.nlm.nih.gov/36718051/), [D02](https://humanpred.github.io/pknca/articles/v09-secondary-parameters.html).

### 2. Concentration and exposure

| Concept | Terms | Binding check |
|---|---|---|
| Concentration summaries | Cmax, Tmax, Cmin, Ctrough, Cavg, C0 | Retain sampled versus model-derived values and the time window. Cmin is the interval minimum; Ctrough is tied to predose timing. C0 may be extrapolated. |
| Concentration-time integral | AUC, AUC0-t, AUC0-inf, AUC0-24, AUCtau, partial AUC | Preserve integration limits, time units, sampling origin and first-dose versus steady-state status. Extrapolated and observed-window exposure differ. |
| Time-weighted exposure and residence | AUMC, MRT | AUMC is the first moment of the concentration-time curve; MRT is mean residence time. Preserve route, integration window and input-duration correction; MRT is not MTT or half-life. |
| Repeated-dose exposure | steady state, accumulation ratio, peak-to-trough ratio; aliases: Rac = accumulation ratio | Specify which metric is ratioed and its reference dose/window; a simulated steady-state profile is not an observed one. |
| Dose-exposure relationship | dose-normalized concentration, dose-normalized AUC, dose proportionality, dose-exposure power model; aliases: C/Dose = dose-normalized concentration | Retain the normalization denominator and fitted slope/interval. Nonproportional exposure alone does not identify its mechanism. |

Terminology references: [S02](https://pubmed.ncbi.nlm.nih.gov/23007438/), [D01](https://humanpred.github.io/pknca/articles/v05-auc-calculation-with-PKNCA.html), [D02](https://humanpred.github.io/pknca/articles/v09-secondary-parameters.html), [D03](https://humanpred.github.io/pknca/articles/v06-half-life-calculation.html), [D04](https://humanpred.github.io/pknca/articles/v03-selection-of-calculation-intervals.html).

### 3. Distribution and elimination

| Concept | Terms | Binding check |
|---|---|---|
| Clearance measures | CL, CL/F, CLu, CLR, CLH, CLint | Separate systemic, apparent, unbound, renal, hepatic and intrinsic clearance. Bind each to its concentration basis, units and organ/system definition; do not cancel an unknown F. |
| Distribution volumes | Vc, Vp, Vss, Vz, V/F | Central, peripheral, steady-state, terminal-phase and apparent volumes differ. V1/V2 labels need the source compartment mapping; Vss alone is not Vc. |
| Intercompartmental exchange | intercompartmental clearance, k12, k21; source-defined symbols: Q | Confirm the source meaning of Q; organ blood flow may use the same symbol. Exchange clearance and first-order transfer constants have different units. |
| Elimination and curve slopes | k10, kel, alpha, beta, lambda_z | Distinguish model micro-rate constants from hybrid exponential slopes and the estimated terminal slope; compartment assumptions govern any equality. |
| Half-life | terminal half-life, distribution half-life, absorption half-life | Retain the phase and estimation window. After extravascular dosing, a terminal slope can reflect absorption rather than elimination. |
| Urinary recovery | amount excreted unchanged, fraction excreted unchanged; aliases: Ae = amount excreted unchanged, fe = fraction excreted unchanged | Keep collection window and dose denominator; link renal clearance to the matching plasma exposure interval. |

Terminology references: [S01](https://link.springer.com/article/10.1007/BF01059626), [S05](https://pmc.ncbi.nlm.nih.gov/articles/PMC6765694/), [S07](https://pubmed.ncbi.nlm.nih.gov/33150591/), [D02](https://humanpred.github.io/pknca/articles/v09-secondary-parameters.html), [D03](https://humanpred.github.io/pknca/articles/v06-half-life-calculation.html).

### 4. Free, total and tissue exposure

| Concept | Terms | Binding check |
|---|---|---|
| Concentration basis | total concentration, unbound concentration, bound fraction, unbound fraction, fAUC, fCmax; aliases: free concentration = unbound concentration, fu = unbound fraction | Bound and unbound fractions differ; do not apply an unbound conversion twice or treat nonspecific assay adsorption as protein binding. For fAUC/fCmax, retain the source's free-exposure definition and window. |
| Binding measurement | fu,p, fu,b, concentration-dependent binding, equilibrium dialysis, ultrafiltration, nonspecific binding; aliases: fup = fu,p, fub = fu,b, NSB = nonspecific binding | Retain matrix, species, method, concentration range and measured versus assumed status; animal binding does not establish human binding. |
| Site-specific exposure | blood-to-plasma ratio, tissue-to-plasma ratio, Kp, Kp,uu, epithelial lining fluid, lung homogenate, microdialysis; aliases: ELF = epithelial lining fluid | Keep ratio numerator/denominator, free/total basis and concentration versus AUC basis. Plasma, serum, blood, ELF and homogenate are distinct; retain sampling/dilution corrections. |

Terminology references: [S07](https://pubmed.ncbi.nlm.nih.gov/33150591/), [S08](https://pubmed.ncbi.nlm.nih.gov/36718051/), [S09](https://doi.org/10.3390/antibiotics13010072), [S12](https://pubmed.ncbi.nlm.nih.gov/15932954/).

### 5. Model structure and estimation

| Concept | Terms | Binding check |
|---|---|---|
| Noncompartmental analysis | noncompartmental analysis, linear trapezoidal integration, linear-up/log-down integration, AUC extrapolated fraction; aliases: NCA = noncompartmental analysis | NCA is an analysis approach, not a compartment count; keep the integration and terminal extrapolation methods. |
| Compartment structure | one-compartment model, two-compartment model, three-compartment model; aliases: 1C = one-compartment model, 2C = two-compartment model, 3C = three-compartment model | Keep input, elimination and parameterization with compartment count; a curved plot alone does not choose a structure. |
| Kinetic assumptions | first-order kinetics, zero-order kinetics, Michaelis-Menten elimination, Vmax, Km, flip-flop kinetics | Separate rate law from compartment count. A saturable model is not evidence that saturation occurred; preserve which process is nonlinear. |
| Fitting level | nonlinear least squares, group-mean curve fit, nonlinear mixed-effects model; aliases: NLS = nonlinear least squares, NLME = nonlinear mixed-effects model, NLMEM = nonlinear mixed-effects model | Do not equate pooled/mean fits with individual mixed-effects fits or reconstruct animal identities from summary curves. |
| Variability components | interindividual variability, interoccasion variability, residual unexplained variability, random-effects covariance, eta, epsilon; aliases: IIV = interindividual variability, IOV = interoccasion variability, RUV = residual unexplained variability | Variability and parameter-estimation uncertainty differ; retain covariance/correlation and the experimental unit. Do not invent IIV from mean data. |
| Observation model | additive error, proportional error, combined error, log-normal error, censored likelihood, M3 | Keep response scale, error assumptions and BLQ handling. A censoring method name does not supply a missing quantification limit. |
| Estimation algorithms | FOCEI, SAEM, maximum likelihood, Bayesian estimation | FOCEI and SAEM are estimation algorithms, not compartment models. Retain objective, approximation, priors and convergence information where stated. |
| Execution software | nlmixr, nlmixr2, NONMEM, Monolix | Software/version is distinct from the model and algorithm; naming a tool neither selects a method nor proves it was run. |

Terminology references: [S02](https://pubmed.ncbi.nlm.nih.gov/23007438/), [S03](https://pmc.ncbi.nlm.nih.gov/articles/PMC2691472/), [S05](https://pmc.ncbi.nlm.nih.gov/articles/PMC6765694/), [S06](https://ascpt.onlinelibrary.wiley.com/doi/10.1002/psp4.12471).

## Conditional extensions

Use these concepts only when relevant to the proposal or evidence. They are not mandatory analyses for every PK model.

### 6. Evaluation and uncertainty

| Concept | Terms | Binding check |
|---|---|---|
| Fit and comparison criteria | log likelihood, OFV, AIC, AICc, BIC, R-squared; aliases: R2 = R-squared | Retain observation set, likelihood/response scale, parameter count and comparison scope; a best score alone does not validate prediction. |
| Residual diagnostics | observed versus predicted, residual versus time, residual versus prediction, WRES, CWRES, IWRES | Keep residual definition and conditioning; an image path or scalar summary is not evidence that a residual plot was visually reviewed. |
| Simulation-based checks | VPC, pcVPC, NPC, NPDE | Use the named diagnostic only with its data/design and predictive distribution; mixed-effects diagnostics are not blanket obligations for every PK model. |
| Uncertainty summaries | confidence interval, prediction interval, credible interval, relative standard error, bootstrap, sensitivity analysis; aliases: CI = confidence interval, RSE = relative standard error | Retain interval level, target and resampling unit; parameter uncertainty, future observations and assumed population variability differ. |
| Estimation reliability | convergence, identifiability, parameter correlation, condition number, shrinkage | Optimizer success is not identifiability. Distinguish parameter-estimate correlation from random-effects correlation; preserve failed or unavailable checks. |

Terminology references: [S04](https://pubmed.ncbi.nlm.nih.gov/21302010/), [S05](https://pmc.ncbi.nlm.nih.gov/articles/PMC6765694/), [S11](https://pubmed.ncbi.nlm.nih.gov/18215437/).

### 7. Animal-to-human translation

| Concept | Terms | Binding check |
|---|---|---|
| Interspecies scaling | allometric scaling, allometric coefficient, allometric exponent, reference body weight, unbound-clearance scaling | Retain predicted parameter, weight basis, species set and estimated versus fixed exponent; no exponent or binding correction is universally supplied by this glossary. |
| In vitro to in vivo extrapolation | in vitro to in vivo extrapolation, in vitro intrinsic clearance, unbound fraction in incubation, organ blood flow, extraction ratio; aliases: IVIVE = in vitro to in vivo extrapolation, fu,inc = unbound fraction in incubation | Preserve system, units, physiological scaling factors and equations. Incubation, plasma and blood binding are not interchangeable. |
| Human concentration-time prediction | predicted human clearance, predicted human distribution volume, human IV simulation, prospective prediction | Keep compatible parameter sets, compartment structure and dosing input. CL and Vss do not uniquely identify an arbitrary multicompartment curve. |
| Prediction evaluation | held-out species, independent validation, fold prediction error, prediction bias, prediction precision | Retain validation target and error definition. Animal holdout performance is not target-drug human validation; no human data means human outputs remain prospective. |

Terminology references: [S01](https://link.springer.com/article/10.1007/BF01059626), [S07](https://pubmed.ncbi.nlm.nih.gov/33150591/), [S10](https://pure.eur.nl/en/publications/the-magnitude-of-the-pharmacodynamic-index-for-noso-502-pathogen-/), [S12](https://pubmed.ncbi.nlm.nih.gov/15932954/).

### 8. PK/PD handoff

| Concept | Terms | Binding check |
|---|---|---|
| Susceptibility measurement | MIC, MIC50, MIC90, broth microdilution | Retain isolate, method and conditions. A population MIC90 is not a matched isolate MIC; MIC is not EC50. |
| Exposure indices | fAUC/MIC, fCmax/MIC, fT>MIC, %fT>MIC, dose fractionation | Retain free exposure, MIC pairing and exposure window. Explicitly distinguish duration, fraction and percentage for time above MIC; an index is not its effect target. |
| Exposure-response models | Emax, EC50, Hill coefficient, effect compartment, ke0 | Keep response definition, sign, units and source parameterization; maximum effect, half-maximal exposure and slope are separate parameters. |
| Effect target | change in log10 CFU, stasis, 1-log kill, 2-log kill, resistance suppression, regrowth | Retain baseline/comparator and endpoint time; growth inhibition, bacterial killing and resistance suppression are different objectives. |
| Target attainment | PK/PD target magnitude, PTA, CFR, MIC distribution, Monte Carlo simulation, virtual population | Bind target, regimen, MIC and population assumptions. MIC-specific attainment and MIC-weighted summaries differ; PTA is not cure probability and assumed human IIV remains a scenario. |

Terminology references: [S07](https://pubmed.ncbi.nlm.nih.gov/33150591/), [S08](https://pubmed.ncbi.nlm.nih.gov/36718051/), [S09](https://doi.org/10.3390/antibiotics13010072), [S10](https://pure.eur.nl/en/publications/the-magnitude-of-the-pharmacodynamic-index-for-noso-502-pathogen-/).

## Data qualifiers

- Preserve units, time origin/window, raw versus digitized and individual versus summary data, sampling unit and n; mean/median and SD/SEM/CV are distinct. Do not infer serial identity from destructive sampling.
- Keep BLQ/BQL, LLOQ/ULOQ, LOD, missing and zero distinct; preserve assay limits and missingness reasons. Never invent a limit or treatment policy.

Use scientific_extraction.json for role/evidence status and CC005 for all 13 preservation categories, including negation, conditions and exceptions; these are not duplicated as PK keyword lists.

## Deduplication and changes

| Previous issue | Revision |
|---|---|
| Species and other generic descriptors dominated the first groups | One 20-word metadata line; no animal-name or demographic lists |
| Parameters, structures, estimators and software mixed together | Distinct concept families; model structure is separate from SAEM/FOCEI and software |
| EC50 repeated under endpoints and MIC | Stored once under exposure-response; MIC retains a distinction check |
| F/bioavailability and Q repeated or ambiguous | One concept home each; ambiguous symbols require the source definition |
| Generic status/logic words repeated as PK terms | Refer to scientific_extraction.json and CC005; no duplicate keyword group |
| Related quantities risked being merged | CL versus CL/F, Vc/Vss/Vz, AUC windows and time-above-MIC representations remain distinct |
| Flat bilingual list | English, ordered groups; source text and unknown terminology remain preserved |

New additions include AUMC/MRT, accumulation, urinary recovery, kinetic rate distinctions, observation models and IVIVE binding. Normalized duplicate checks retain mathematical punctuation: CL/F and CL, or fT>MIC and %fT>MIC, must not collapse.

CPK identifiers belong to this version; they do not reuse the meanings of the old PKB identifiers. Review by source plus version, not by number alone.

## Literature reading record

Twelve scientific publications were consulted, including a methods chapter and a perspective/review, plus four author-documentation pages. Access varied as stated below; this is a focused terminology review, not twelve full-paper appraisals or validation of the extraction algorithm. Group links support terminology families; binding safeguards also reflect approved project requirements and our synthesis.

| Source | Material inspected | Contribution and boundary |
|---|---|---|
| [S01: Rowland et al. (1973). Clearance concepts in pharmacokinetics.](https://link.springer.com/article/10.1007/BF01059626) | Publisher abstract | Clearance versus time constants; blood flow context. No parameter values imported. |
| [S02: Gabrielsson and Weiner (2012). Non-compartmental analysis.](https://pubmed.ncbi.nlm.nih.gov/23007438/) | PubMed abstract; methods chapter | NCA versus model fitting; exposure summaries and integration. |
| [S03: Bergstrand and Karlsson (2009). Handling Data Below the Limit of Quantification in Mixed Effect Models.](https://pmc.ncbi.nlm.nih.gov/articles/PMC2691472/) | Full-text Introduction, Methods and model-evaluation sections | BLQ/censoring terminology and observation models; no automatic M3 policy. |
| [S04: Bergstrand et al. (2011). Prediction-corrected visual predictive checks for diagnosing nonlinear mixed-effects models.](https://pubmed.ncbi.nlm.nih.gov/21302010/) | PubMed abstract | VPC and prediction correction; conditional on a suitable simulation model. |
| [S05: Fidler et al. (2019). Nonlinear Mixed-Effects Model Development and Simulation Using nlmixr and Related R Open-Source Packages.](https://pmc.ncbi.nlm.nih.gov/articles/PMC6765694/) | Author-hosted full-text case study, estimation and comparison sections | Compartment structure versus estimator/software; diagnostic and fit-summary labels. |
| [S06: Schoemaker et al. (2019). Performance of the SAEM and FOCEI Algorithms in the Open-Source, Nonlinear Mixed Effect Modeling Tool nlmixr.](https://ascpt.onlinelibrary.wiley.com/doi/10.1002/psp4.12471) | Publisher abstract | SAEM and FOCEI as algorithms; no claim about current software performance. |
| [S07: Sou et al. (2021). Model-Informed Drug Development for Antimicrobials: Translational PK and PK/PD Modeling to Predict an Efficacious Human Dose for Apramycin.](https://pubmed.ncbi.nlm.nih.gov/33150591/) | PubMed abstract and indexed Methods/Results passages | Allometry, unbound clearance, input kinetics and PK/PD linkage; no apramycin parameters reused. |
| [S08: van der Meijden et al. (2023). Pharmacokinetic and pharmacodynamic properties of polymyxin B in Escherichia coli and Klebsiella pneumoniae murine infection models.](https://pubmed.ncbi.nlm.nih.gov/36718051/) | PubMed abstract and indexed Results passages | Dose per administration, dose-dependent kinetics, free exposure and nonspecific binding. |
| [S09: Bissantz et al. (2024). Translational PK/PD for the Development of Novel Antibiotics-A Drug Developer's Perspective.](https://doi.org/10.3390/antibiotics13010072) | Full-text sections 2.1, 3.1.2 and 3.1.4; perspective/review | Index versus target; full concentration-time profiles and tissue exposure. Not a compression method. |
| [S10: van den Berg et al. (2026). The magnitude of the pharmacodynamic index for NOSO-502: pathogen clearance, emergence of resistance and human dose predictions.](https://pure.eur.nl/en/publications/the-magnitude-of-the-pharmacodynamic-index-for-noso-502-pathogen-/) | Institutional publication abstract | Human prediction, effect-specific targets and regimen/window dependence. Full methods not verified. |
| [S11: Comets et al. (2008). Computing normalised prediction distribution errors to evaluate nonlinear mixed-effect models: the npde add-on package for R.](https://pubmed.ncbi.nlm.nih.gov/18215437/) | PubMed abstract | NPDE as a predictive-distribution diagnostic, with within-subject structure. |
| [S12: Riley et al. (2005). A unified model for predicting human hepatic, metabolic clearance from in vitro intrinsic clearance data in hepatocytes and microsomes.](https://pubmed.ncbi.nlm.nih.gov/15932954/) | PubMed abstract and publisher abbreviation list | Intrinsic versus hepatic clearance and incubation versus blood binding in IVIVE; no scaling factors imported. |
| [D01: PKNCA authors. AUC calculation and integration methods.](https://humanpred.github.io/pknca/articles/v05-auc-calculation-with-PKNCA.html) | Author documentation: AUC calculation and integration methods | Integration, interpolation and extrapolation terminology. |
| [D02: PKNCA authors. Secondary parameters: renal clearance, bioavailability and ratios.](https://humanpred.github.io/pknca/articles/v09-secondary-parameters.html) | Author documentation: secondary parameters | Cross-profile pairing for renal clearance, bioavailability and ratios. |
| [D03: PKNCA authors. Half-life calculation.](https://humanpred.github.io/pknca/articles/v06-half-life-calculation.html) | Author documentation: half-life calculation | Terminal slope and explicit terminal-phase selection. |
| [D04: PKNCA authors. Calculation intervals and residence-time corrections.](https://humanpred.github.io/pknca/articles/v03-selection-of-calculation-intervals.html) | Author documentation: calculation intervals | Residence-time conventions, multiple-dose and infusion corrections. |

Accessible full-text copies used:

- [Fidler et al.: author-hosted PDF](https://www.occams.com/assets/pdf/Fidler_et_al-2019-CPT__Pharmacometrics_%26_Systems_Pharmacology.pdf).
- [Bissantz et al.: publisher PDF](https://mdpi-res.com/d_attachment/antibiotics/antibiotics-13-00072/article_deploy/antibiotics-13-00072.pdf).

## Runtime use

New compression runs receive this profile under CC pack 1.14.0 in extraction and the assigned review calls. Existing runs keep their frozen profiles. CC005 links its 13 preservation categories to this single terminology appendix; see [the integrated CC005 review](CC005_REVIEW.md). No additional model call, fitting job or downstream simulation is started by this terminology update.

The machine-readable source is ../../rules/compression/pk_binding_knowledge.json. The resolved portable pack is research_pipeline/docs/interfaces/context_compression.runtime.json. Formal project rules remain a separate Project Rules Agent output.
