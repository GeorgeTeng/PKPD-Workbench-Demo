# Self-review of study conclusions

Run from the repository root with Python 3.10 or newer. Supply a local run containing the section JSON files, figures and `source_tables.json`. Without `--rules`, the reviewer uses the rule files the run was computed with (`<run>/_engine/rules`, written by `tools/eda/run_modules.py`). A supplied rule file whose SHA-256 differs from the run's `run_record.json` is refused. This command uses the bundled Codex CLI adapter with your installed, authenticated CLI.

```powershell
python -m eda.review D:/runs/MyDrug --out D:/reviews/MyDrug --resume --generate eda.review.codex_adapter:generate
```

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

Before dispatch or saved-answer reuse, each selected section needs a readable rule file with numbered passages. Its digest must match both binding records when present. The checked bytes are the ones sent for review. A partial review reports its selected scope.

Run `python validation/eda_rereview/check_safeguards.py` for the independent acceptance checks, or `python -m pytest -q eda/review/tests` for the full reviewer suite. See the [benchmark and targeted live verification](../../validation/eda_rereview/README.md).
