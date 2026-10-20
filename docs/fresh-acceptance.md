# Fresh acceptance through Data

This command runs Imidocarb first, then PMB, Meropenem and Voriconazole from their packaged input ZIPs. Each example starts with a new file registration. It requests `gpt-6.1-sol` with `high` reasoning and stops at Data. It performs real model calls and consumes account usage.

From the extracted `demo` directory, in PowerShell:

```powershell
$round = Get-Date -Format 'yyyyMMdd-HHmmss'
$state = Join-Path $PWD "state\fresh-$round"
$report = Join-Path $PWD "state\acceptance\fresh-$round"
.\start-demo.ps1 -Port 8774 -NoBrowser -StateDirectory $state -Provider codex -Model gpt-6.1-sol -ReasoningEffort high
.\runtime\python.exe -I -B -X utf8 tests\run_fresh_examples.py --base http://127.0.0.1:8774 --state-root "$state" --output-dir "$report" --approve-test-gates
```

Use an available port and a new state/report directory. The driver refuses a state directory containing earlier sessions or calls, and refuses to overwrite an earlier report. Do not run the command twice against the same state directory.

## What is disabled

- Response reuse is disabled by default. The server reports `response_reuse_disabled=true` at `/workspace-api/capabilities`.
- Data ignores both same-request kept responses and `PKPD_DEMO_REUSE_DATA_RUN` when reuse is disabled.
- Context does not resume a previously accepted Context stage. Shared response cache lookups are disabled.
- The acceptance driver never retries a stage, edits a model response, requests a Context revision, or continues an old session.
- Model calls and the overall acceptance have no execution deadline. HTTP transport timeouts are separate.

Source parsing, file hashing, deterministic transformations, and the current run's upstream Context passed to Data remain part of normal execution. Disabling old model responses does not discard required agent-to-agent inputs.

## Human gates

`--approve-test-gates` records the user's authorization to approve the three visible checkpoints per example: Context, Data scope, and completed Data. Every decision includes its reviewer, rationale and output signature. These are automatic technical-demo approvals; they do not claim independent human review or resolve the scientific findings.

The single-example report saves progress events and the final session. The combined report verifies the actual saved gates, artifact hashes, prepared records, open findings, fresh model receipts and downstream nodes. Every stage must start exactly once. EDA and PK must remain unstarted.

Only `ALL_FOUR_PASSED_FRESH_THROUGH_DATA` is a successful fresh four-example result. A previous recorded result or a passed offline test suite does not meet this condition.

## After a failure

Keep the failed directory and inspect its driver log, stage artifacts and model request/response. Fix the owning code or contract, then stop the old server once its active call has ended:

```powershell
.\stop-demo.ps1 -Port 8774 -StateDirectory $state
```

Start a new round with a new timestamp and rerun **all four**. Do not repair historical JSON, copy a successful answer into the new run, or resume only the failed example and call that a one-pass acceptance. The verifier checks that code and inputs stayed unchanged during the final round.

## Fourth input

Imidocarb uses the original cattle workbook already present in the workspace, copied byte-for-byte from the supplementary data associated with Wang et al. (2022), DOI `10.1371/journal.pone.0270130`. The ZIP includes a new Data-only project proposal and attributed source excerpts. The workbook contains wide/multilingual headers, two formulation groups and source summary formulas. The source workbook is not rewritten to simplify the test. Its exact bytes and the ZIP members are bound in `examples/inputs/manifest.json`.

The success criterion is faithful source organization and technical QC. Formula/error or ambiguous records may require quarantine and review; a zero-quarantine count is not a universal acceptance requirement. Modeling sufficiency remains deferred. Successful repetition of these inputs cannot guarantee success for an arbitrary new dataset or model provider.
