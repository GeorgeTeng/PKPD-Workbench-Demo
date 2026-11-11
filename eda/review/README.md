# Self-review of study conclusions

Run from the repository root with Python 3.10 or newer. Supply a local run containing the section JSON files, figures and `source_tables.json`. Supply the rule file used to generate each section. This command uses the bundled Codex CLI adapter with your installed, authenticated CLI.

```powershell
python -m eda.review D:/runs/MyDrug --out D:/reviews/MyDrug --resume --generate eda.review.codex_adapter:generate --rules absorption=D:/rules/absorption.md distribution=D:/rules/distribution.md elimination=D:/rules/elimination.md
```

The reviewer checks the status against endpoint evidence and labels each inventory source by study and arm. For a disputed row it returns search keywords. The writer uses matching source records and the original tables and figures to revise the conclusion. The reviewer then checks the revised board, including previously reported problems. This repeats until every row is confirmed and all omissions are resolved. The original measurements and figures stay available for comparison.

Open `index.html` to read the review. The revised wording, status, keywords and decisions are in `review.json` under `err[].self_review`. A passing self-review goes to the human reviewer. A repeated unsuccessful revision with the same evidence, a missing input, or an exhausted call budget stays pending. Use the same command to resume after supplying evidence. The adapter defaults to 22 model calls per invocation. Set `EDA_REVIEW_MAX_CALLS` to choose a different budget or `--max-rounds N` to limit correction rounds. A run with `--only` covers the selected requests. A run with `--inject` measures first-pass detection and skips correction.

Run `python -m pytest -q eda/review/tests` for the offline tests. See the [benchmark and targeted live verification](../../validation/eda_rereview/README.md).
