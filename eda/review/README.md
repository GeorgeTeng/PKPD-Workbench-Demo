# Self-review of study conclusions

Run from the repository root with Python 3.10 or newer. The first argument is your completed EDA run folder, containing the section JSON files, figures and `source_tables.json`. Use `--out` to choose the review folder on any drive. The default is `<run>/review`. The reviewer checks the frozen rules in `<run>/_engine/rules` against the run record. You can supply the matching files with `--rules`.

### Use your own model API

Install `jsonschema` in the Python environment you will use for review. Enter the model ID and API base URL provided by your local server or hosted provider. The adapter sends non-streaming Chat Completions requests with the review schema, study evidence and any cited PNGs. The model must return a JSON object and accept image input when a request contains figures. The host checks the response against the schema and the study-specific review rules.

```powershell
python -m pip install jsonschema
$runDir = Read-Host 'Completed EDA run folder'
$reviewDir = Read-Host 'Folder for review results'
$apiBase = Read-Host 'Model API base URL (for example, http://localhost:8000/v1)'
$model = Read-Host 'Model ID'
python -m eda.review $runDir --out $reviewDir --api-base $apiBase --model $model --resume
```

For a server that requires a bearer token, set `EDA_REVIEW_API_KEY` in the same session before running the command. PowerShell can read the key without displaying it.

```powershell
$key = Read-Host 'API key' -AsSecureString
$env:EDA_REVIEW_API_KEY = [System.Net.NetworkCredential]::new('', $key).Password
```

The endpoint and requested model ID appear in `review.json`. Cached board reviews, rewrites and rechecks are scoped to the endpoint and model. To keep two reports side by side, give each its own output folder.

### Use Codex CLI or a Python adapter

With an installed, authenticated Codex CLI, run the following using the same folder variables.

```powershell
python -m eda.review $runDir --out $reviewDir --generate eda.review.codex_adapter:generate --resume
```

Set `EDA_REVIEW_CALL_LOG` to choose a path for the Codex CLI call log. For another API protocol, pass `--generate your_module:generate` with an importable Python callable taking `(prompt, schema, image_paths)` and returning a dictionary. If that callable can select different models, set its `identity` attribute to a non-secret JSON value identifying its configuration, or use a separate output folder per model.

### Follow up on a review

The reviewer checks the status against endpoint evidence and labels each inventory source by study and arm. For a disputed row it returns search keywords. The writer uses matching source records and the original tables and figures to revise the conclusion. The reviewer then checks the revised board, including previously reported problems. This repeats until every row is confirmed and all omissions are resolved. The original measurements and figures stay available for comparison.

Open `index.html` to read the review. The revised wording, status, keywords and decisions are in `review.json` under `err[].self_review`. A passing self-review goes to the human reviewer. A repeated unsuccessful revision with the same evidence, a missing input, or an exhausted call budget stays pending. Use the same command to resume after supplying evidence. The adapter defaults to 22 model calls per invocation. Set `EDA_REVIEW_MAX_CALLS` to choose a different budget or `--max-rounds N` to limit correction rounds. A run with `--only` covers the selected requests. A run with `--inject` measures first-pass detection and skips correction.

Changes of 2026-11-12:

- Rule passages are sent whole. The shared answer-status, exclusion and figure passages (X0.11, X0.3, X0.6) always travel with a row, together with any shared passage the item text cites.
- All boards get their first review before any rewrite starts; corrections then run with the current rows of every board.
- Issues are routed. VALUE_ERROR and DISPLAY need a code or data change and are not sent to the writer; the board ends as NEEDS_CODE_OR_DATA (exit code 2) and the page lists them. A display note on a confirmed row is shown but starts no rewrite.
- Quantitative statements belong to the calculation that produced the row. The writer retains each such statement in its original field. It can add a separate qualitative limitation. A change of value, unit, direction, population or removal of that statement is returned for source or code review. Reviewer comments and search hits can point to a source, but cannot authorize a new measurement. Summary statements with quantities must quote a cited row.
- A re-review that fails the host checks is retried once (`--retries`) with the reasons.
- Species are matched with one vocabulary that covers every module group.
- Saved answers from earlier runs are not reused, because prompts and payloads changed; the next run makes new model calls.

Before dispatch or saved-answer reuse, each selected question needs a mapping, the nonempty text of every mapped rule item, and the required shared passages. This also covers questions cited by a hypothesis sent in a separate request. Each rule file's digest must match the binding records when present. A confirmed question must list its mapped items in `checked_rules`. The host rejects missing passages and missing rule citations separately.

Run `python validation/eda_rereview/check_safeguards.py` for the independent acceptance checks, or `python -m pytest -q eda/review/tests` for the full reviewer suite. See the [benchmark and targeted live verification](../../validation/eda_rereview/README.md).
