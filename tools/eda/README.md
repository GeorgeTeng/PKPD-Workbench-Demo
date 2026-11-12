# Calculate study-level PK EDA

Run the three descriptive modules from the repository root with Python, NumPy, Matplotlib and SciPy. The R renderer uses Rscript, ggplot2, jsonlite and scales. Supply a case directory with `source_tables.json`, an output directory and the paths to the installed runtimes.

```powershell
python tools/eda/run_modules.py D:/cases/MyDrug D:/runs/MyDrug --workspace . --python D:/pk/python.exe --rscript D:/R/bin/Rscript.exe --r-lib D:/R/library
python -m eda.review D:/runs/MyDrug --out D:/reviews/MyDrug --resume --generate eda.review.codex_adapter:generate
```

The run records the input, stage and rule digests in `run_record.json` and freezes them under `_engine`. To resume, add `--from distribution` or `--from elimination` to the first command. A partial rerun checks its historical rule bundle and source tables before writing. For a run without these bindings, use a fresh output directory. Open `index.html` to review the study results.

Distribution records systemic IV coverage by dataset, profile, matrix, occasion and number of distinct reported times before applying the first-dose and phase-analysis criteria. See the [reviewer](../../eda/review/README.md) for the independent review of the generated conclusions.
