# Calculate study-level PK EDA

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

Distribution records systemic IV coverage by dataset, profile, matrix, occasion and number of distinct reported times before applying the first-dose and phase-analysis criteria. See the [reviewer](../../eda/review/README.md) for the independent review of the generated conclusions.
