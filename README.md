# Translational PK/PD Workbench Demo

Use this repository to prepare source data, explore animal pharmacokinetics by study and species, and review the evidence before choosing a model. The browser workbench takes a project through **Data**. The standalone **EDA** tools calculate absorption, distribution, and elimination/metabolism from prepared study tables.

| What you have | Where to start |
| --- | --- |
| A case folder with `source_tables.json` | [Run the three EDA sections](tools/eda/README.md) |
| A completed three-section run | Open its `index.html` for the study report or [run independent self-review](eda/review/README.md) before human review. |
| A portable PMB absorption report or a released native Data handoff | [Open the report or use the absorption-only workflow](eda/README.md) |
| Project files or one of the packaged example ZIPs | [Start the browser workbench](#browser-workbench) for intake, Context, project Rules and Data preparation. |

## Exploratory data analysis (EDA)

### Run a case

Use a source checkout for the three-section runner. It requires Python with NumPy, SciPy and Matplotlib. For the R figures, install R with ggplot2, jsonlite and scales. Run the following in PowerShell from the repository root. Set the case, output and R paths for your machine and choose a fresh output folder.

```powershell
$caseDir = 'D:/cases/MyDrug'          # contains source_tables.json
$runDir = 'D:/runs/MyDrug'
$python = python -c "import sys; print(sys.executable)"
$rscript = 'D:/R/bin/Rscript.exe'
$rLibrary = 'D:/R/library'

& $python tools/eda/run_modules.py $caseDir $runDir --workspace . --python $python --rscript $rscript --r-lib $rLibrary
```

The runner applies absorption **r4.3**, distribution **r1.3** and elimination/metabolism **r1.1**. Each run records the source-table hash, section rules, calculation and plotting code, renderer and output hashes in `run_record.json`. A partial rerun checks the saved input and rules before writing. [Versioned rules](tools/eda/rules/rules_manifest.json) · [Partial rerun instructions](tools/eda/README.md)

### Read or share the result

| File in the run folder | What it answers |
| --- | --- |
| `index.html` | Where do I start? Browse the three sections and their study and species pages. |
| `report.html` and `figures/index.html` | Which observation supports this answer? Read the questions and inspect the linked plots. |
| `modeling_context.json` | What should modeling check next? Each species has one priority with the observed pattern, plausible alternatives, a distinguishing check, source IDs and links to available figures. If the curves cannot distinguish mechanisms, the entry identifies the evidence needed. |
| `coverage.json` and `run_record.json` | Which source tables contributed, which went unused, and which inputs and rules produced this run? |

To read a report on another computer, copy or zip **the entire run folder**, extract it, and open its `index.html` in a browser. For the separate PMB absorption-only package, open `Open_Report.html` from the extracted ZIP. Full study reports and their modeling JSON are generated locally. [PMB viewing instructions](eda/README.md)

### Review the conclusions

From the same checkout, run the independent reviewer against the completed calculation. The supplied adapter uses an installed, authenticated Codex CLI.

```powershell
$reviewDir = 'D:/reviews/MyDrug'
& $python -m eda.review $runDir --out $reviewDir --resume --generate eda.review.codex_adapter:generate
```

Open `index.html` in the **review folder** for the verdicts and `review.json` for revised wording. The reviewer checks each question against its rule passages, study, arm and supporting evidence. A disputed interpretation returns to the writer with search terms, then goes through review again. A disputed value or figure goes back for a calculation, data or display correction. A passing self-review is ready for a human decision. When handing findings to modeling, compare the original `modeling_context.json` with the corrections in `review.json`. [Review states and call limits](eda/review/README.md)

### Verify the installation

With pytest installed in the same Python environment, run the checks used by GitHub Actions from the repository root.

```powershell
& $python validation/eda_rereview/check_safeguards.py
& $python -m pytest -q eda/review/tests
```

The verification record reports the synthetic safeguards, reviewer tests, local paper comparisons and items with insufficient evidence. It also identifies which results require local study inputs. [Verification record](validation/eda_rereview/README.md) · [CI workflow](.github/workflows/eda-safeguards.yml)

## Browser workbench

For the Windows demo, extract the complete portable ZIP, open its `demo` folder and run `START_DEMO.cmd`. Browse to `http://127.0.0.1:8772` and use `STOP_DEMO.cmd` when finished. The portable release includes its own Python runtime. [Download the Windows demo](https://github.com/GeorgeTeng/PKPD-Workbench-Demo/releases/tag/v0.1.1)

The **Research workflow** runs file intake, Context, project Rules and source-preserving Data preparation with review checkpoints. Its EDA and PK screens show recorded previews. **Knowledge & context** lets you inspect source-backed cards and how context is assembled. Live Context and Data labeling require a configured model provider. The running server exposes its capabilities at `/workspace-api/capabilities`. [Packaged Data examples and results](examples/acceptance/index.html) · [Fresh acceptance guide](docs/fresh-acceptance.md)

## Repository map

| Path | Responsibility |
| --- | --- |
| [tools/eda/](tools/eda/) | Three scientific modules, R figure scripts, section rules, report publisher and species-level modeling handoff. |
| [eda/](eda/) · [eda/review/](eda/review/) | Native absorption commands and portable-report launcher. The `review` subdirectory contains the independent reviewer and revision loop for all three sections. |
| [app.py](app.py) · [demo/](demo/) · [workspace/](workspace/) · [frontend/](frontend/) | Local web server, API adapters, browser workspace and detailed workflow controls. |
| [backend/](backend/) · [knowledge/](knowledge/) | Workflow execution, ContextBuilder, provider adapters and the workbench knowledge library. |
| [native_workflow/](native_workflow/README.md) | Native workflow snapshot, including the released-Data-to-EDA adapter and absorption-only implementation. |
| [examples/](examples/) · [validation/](validation/) · [tests/](tests/) | Packaged workbench examples, verification records and browser-workbench integration tests. |
| [docs/](docs/) · [research/](research/) | Design and acceptance notes, historical EDA revisions and experimental ContextBuilder material. |

The earlier operator guide includes the detailed workbench API, provider configuration, and historical Data acceptance timings. [Versioned operator guide](https://github.com/GeorgeTeng/PKPD-Workbench-Demo/blob/63c04051d7921a7bf31f6dd83f68a2eaee1f05a7/README.md#api-locations-and-configuration)
