# Open or run the absorption EDA

## Read the saved PMB report

Extract the portable PMB report ZIP into `eda/report/`. On Windows, double-click **Open_EDA.cmd**. On any computer, open `eda/report/absorption/index.html` in a browser. Keep the extracted folders together so the species pages, study sections and figures open offline. Each computer needs its own copy of the portable report.

If you already have an extracted report elsewhere, point the viewer at the directory containing `absorption/`. Run the following commands from the repository root.

```powershell
python eda open "D:/reports/PMB_retry030"
```

For the English PMB mechanism edition, copy the whole private ZIP to the other computer, extract it, then open **Open_Report.html**. From the overview choose **Absorption hypotheses for modeling**, or open `absorption/mechanism_assessment.html` directly. The Markdown handoff is beside it. A browser and the extracted files are sufficient for offline reading.

### Review candidate mechanisms

The standalone command below and the native EV workflow generate the following files from the same completed absorption result.

| File inside `absorption/` | What to use it for |
| --- | --- |
| `mechanism_assessment.html` | Read each study’s nine answers, observations that warrant a modeling check, and the evidence for each candidate. |
| `mechanism_assessment.md` | Share the English handoff as text. |
| `mechanism_candidates.json` | Inspect every candidate, profile, comparison, constraint, rule reference and evidence link, including alternatives with unresolved route or sparse observations. |

The [versioned mechanism catalogue](../native_workflow/backend/rules/eda/absorption_mechanisms_r43.json) separates fixed lag from gradual onset and crosses Weibull shape (β < 1, β = 1, β > 1) with presence or absence of a fixed lag. β = 1 is equivalent to first-order input. Other entries cover zero-order, transit, inverse Gaussian and mixed inputs, recirculation, flip-flop, dose-dependent rate or extent, nonlinear disposition and route-specific alternatives. An observed feature can motivate a comparison even when its cause is unresolved. An exclusion applies to the specified combination, observations and assumptions. Source examples illustrate which comparisons can distinguish models.

## Rebuild absorption from existing EDA tables

Use the Python environment for the [native workflow](../native_workflow/README.md). On Windows its [setup script](../native_workflow/setup.ps1) creates `native_workflow/.venv-context/`. Run the following from the repository root. Replace the example paths with your own.

```powershell
$py = ".\native_workflow\.venv-context\Scripts\python.exe"
& $py eda run --source "D:/PMB/eda/run" --out "D:/reports/PMB_rebuilt"
& $py eda open "D:/reports/PMB_rebuilt"
```

The source directory must contain the admitted `source_tables.json`. Supply its matching `dose_normalization_assessment.json` and EV plots when available. The portable viewing ZIP contains the rendered report. Recalculation requires the original table inputs. Choose a **new** output directory outside the source run. Set `PKPD_RSCRIPT` to your Rscript executable and `R_LIBS_USER` to the library containing ggplot2 and jsonlite to use the R renderer. The result records the renderer used.

## Start at a released Data handoff

Use `from-data` to call the repository’s native adapter with its input checks. This path requires the Data report and handoff plus the files they reference. Both commands below require the native Python environment. The second also requires a configured model provider and R runtime.

```powershell
& $py eda from-data --prepare-only --handoff "D:/Data/handoffs/eda_context.json" --report "D:/Data/data_report.json" --out "D:/reports/intake_check"
& $py eda from-data --handoff "D:/Data/handoffs/eda_context.json" --report "D:/Data/data_report.json" --out "D:/reports/fresh_eda"
```

The first command validates and prepares intake locally. The second runs through EV and prints the path to the absorption report.

## Rule versions

The current published absorption specification is **r4.3**, dated 5 November 2026. Its nine questions put individual-animal evidence at Q5, terminal decline at Q6, systemic availability at Q7 and dose dependence at Q8. See the source for the decision criteria and the implementation requirements. [Read the r4.3 rules for items 16–23](../native_workflow/backend/rules/eda/EDA_absorption_rules_r4.3_rules_only_20261105.md).

The executable supplied here uses **r4.3**. Each result identifies the rule document and its SHA-256. Run `python eda rules` to verify the document locally. The [historical retry 030 checks](../validation/pmb_absorption_retry030/README.md) apply to the archived **r4.2** output.

`python eda rules` also verifies the registered mechanism catalogue. The handoff records its hash and the hash of the exact `absorption.json` used to generate it.
