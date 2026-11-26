# Calculate study-level PK EDA

The active standalone runner uses shared s1.0, absorption r4.4, distribution r1.6 and elimination/metabolism r1.2. The [rule manifest](rules/rules_manifest.json) binds the human-readable Markdown and the corresponding machine YAML by SHA-256. The [human review examples](../../examples/eda-review/README.md) include two completed reports and a review checklist.

Run the three descriptive modules from the repository root with Python, NumPy, Matplotlib and SciPy. The R renderer uses Rscript, ggplot2, jsonlite and scales. Start PowerShell in the repository root with your Python environment active. At the prompts, enter paths on your own computer without surrounding quotes. To find the R paths on Windows, run `file.path(R.home("bin"), "Rscript.exe")` and `dirname(find.package("ggplot2"))` in the R console.

```powershell
$caseDir = Read-Host 'Folder containing your source_tables.json'
$runDir = Read-Host 'New folder for your EDA results'
$python = python -c "import sys; print(sys.executable)"
$rscript = Read-Host 'Full path to your Rscript executable'
$rLibrary = Read-Host 'Your R package library folder'

& $python tools/eda/run_modules.py $caseDir $runDir --workspace . --python $python --rscript $rscript --r-lib $rLibrary
```

For self-review, supply the completed run folder, your preferred review directory and either your own model API or the Codex CLI. [Model and directory options](../../eda/review/README.md)

The run records the input, stage and rule digests in `run_record.json` and freezes them under `_engine`. To resume, add `--from distribution` or `--from elimination` to the runner command. A partial rerun checks its historical rule bundle and source tables before writing. For a run without these bindings, use a fresh output directory. Open `index.html` to review the study results.

`report.html` lists the questions, `figures/index.html` shows the gallery, and `coverage.json` records which input tables each section used. `modeling_context.json` records one prioritized check per species. `modeling_facts.json` and `modeling_facts.txt` retain study design, observed profiles and sampling constraints for downstream modeling. These files describe EDA evidence and proposed checks. Model fitting and human approval occur separately.

Distribution records systemic IV coverage by dataset, profile, matrix, occasion and number of distinct reported times before applying the first-dose and phase-analysis criteria. See the [reviewer](../../eda/review/README.md) for the independent review of the generated conclusions.
