# EDA entry points

| Task | Entry point |
| --- | --- |
| Calculate absorption, distribution and elimination/metabolism from a study's prepared tables | [Three-section runner](../tools/eda/README.md) |
| Inspect a completed three-section run | Open `index.html` in the run folder. Its `modeling_context.json` gives one figure-led modeling priority per species. |
| Check the study conclusions and revise disputed interpretations before human review | [Independent self-review](review/README.md) |
| Open a saved PMB absorption report, rebuild absorption alone, or start from a native Data handoff | Use the absorption commands below. |

## Read the saved PMB report

Extract the portable PMB report ZIP into `eda/report/`. On Windows, double-click **Open_EDA.cmd**. On any computer, open `eda/report/absorption/index.html` in a browser. Keep the extracted folders together so the species pages, study sections and figures open offline. Each computer needs its own copy of the portable report.

If you already have an extracted report elsewhere, point the viewer at the directory containing `absorption/`. Run the following commands from the repository root.

```powershell
$reportDir = Read-Host 'Extracted report folder containing the absorption subfolder'
python eda open $reportDir
```

For the English PMB species edition, copy the private ZIP to the other computer, extract it, then open **Open_Report.html**. This opens the one-page species summary. Its canonical file is `absorption/mechanism_assessment.html`. A browser and the extracted files are sufficient for offline reading.

### Review candidate mechanisms

The report gives one modeling priority per species and links to the study evidence for that choice. When competing checks have equal support or the data are too sparse, the report says what evidence would distinguish them. The [promoted species-priority policy](../native_workflow/backend/rules/eda/absorption_species_priority_rules.json) governs that decision. Full explanations, alternatives and all nine answers per study are in the linked Markdown and JSON. The JSON includes `species_priorities` and the exact `priority_rule_specification`.

The standalone command below and the native EV workflow generate the following files from the same completed absorption result.

| File inside `absorption/` | What to use it for |
| --- | --- |
| `mechanism_assessment.html` | Read one concise modeling priority per species and open its supporting study evidence. |
| `mechanism_assessment.md` | Share the English handoff as text. |
| `mechanism_candidates.json` | Inspect every candidate, profile, comparison, constraint, rule reference and evidence link, including alternatives with unresolved route or sparse observations. |

The [versioned mechanism catalogue](../native_workflow/backend/rules/eda/absorption_mechanisms_r43.json) separates fixed lag from gradual onset and crosses Weibull shape (β < 1, β = 1, β > 1) with presence or absence of a fixed lag. β = 1 is equivalent to first-order input. Other entries cover zero-order, transit, inverse Gaussian and mixed inputs, recirculation, flip-flop, dose-dependent rate or extent, nonlinear disposition and route-specific alternatives. An observed feature can motivate a comparison even when its cause is unresolved. An exclusion applies to the specified combination, observations and assumptions. Source examples illustrate which comparisons can distinguish models.

## Rebuild absorption from existing EDA tables

Use the Python environment for the [native workflow](../native_workflow/README.md). On Windows its [setup script](../native_workflow/setup.ps1) creates `native_workflow/.venv-context/`. Run the following from the repository root and enter your own paths at the prompts.

```powershell
$py = ".\native_workflow\.venv-context\Scripts\python.exe"
$sourceDir = Read-Host 'Folder containing your source_tables.json'
$reportDir = Read-Host 'New folder for the rebuilt absorption report'
& $py eda run --source $sourceDir --out $reportDir
& $py eda open $reportDir
```

The source directory must contain the admitted `source_tables.json`. Supply its matching `dose_normalization_assessment.json` and EV plots when available. The portable viewing ZIP contains the rendered report. Recalculation requires the original table inputs. Choose a **new** output directory outside the source run. Set `PKPD_RSCRIPT` to your Rscript executable and `R_LIBS_USER` to the library containing ggplot2 and jsonlite to use the R renderer. The result records the renderer used.

## Start at a released Data handoff

Use `from-data` to call the repository’s native adapter with its input checks. This path requires the Data report and handoff plus the files they reference. Both commands below require the native Python environment. The second also requires a configured model provider and R runtime.

```powershell
$py = ".\native_workflow\.venv-context\Scripts\python.exe"
$handoff = Read-Host 'Full path to your eda_context.json'
$dataReport = Read-Host 'Full path to the matching data_report.json'
$intakeDir = Read-Host 'New folder for the intake check'
& $py eda from-data --prepare-only --handoff $handoff --report $dataReport --out $intakeDir

$edaDir = Read-Host 'New folder for the full EDA run'
& $py eda from-data --handoff $handoff --report $dataReport --out $edaDir
```

The first command validates and prepares intake locally. The second runs through EV and prints the path to the absorption report.

## Rule versions

The native absorption specification is **r4.3**, dated 5 November 2026. Its nine questions put individual-animal evidence at Q5, terminal decline at Q6, systemic availability at Q7 and dose dependence at Q8. See the source for the decision criteria and the implementation requirements. [Read the r4.3 rules for items 16–23](../native_workflow/backend/rules/eda/EDA_absorption_rules_r4.3_rules_only_20261105.md).

The executable supplied here uses **r4.3**. Each result identifies the rule document and its SHA-256. Run `python eda rules` to verify the document locally. The [historical retry 030 checks](../validation/pmb_absorption_retry030/README.md) apply to the archived **r4.2** output.

`python eda rules` also verifies both reporting resources: the candidate catalogue and the **r4.3-handoff.2** species priority policy. Each result records their versions and hashes and the hash of the exact `absorption.json` used. The species summary is generated locally without a model call.
