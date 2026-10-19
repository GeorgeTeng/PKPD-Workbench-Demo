# Main → Data entry

This small workflow passes the complete immutable `main.json` to the existing Data input function. It does not extract regimen fields, adopt facts as project requirements, or run Data agents, adequacy, preparation or fitting.

```powershell
.venv-context\Scripts\python.exe -I -X utf8 -m research_pipeline.main_data_handoff --main <final-main.json> --out <new-output-directory>
```

Without published Project Rules and an existing Context approval, this writes `handoff_receipt.json` with `status: PENDING`, exact source references and the missing prerequisites. It does not produce an approved Data input or invent approval.

Once the existing workflow has produced the real approval artifact:

```powershell
.venv-context\Scripts\python.exe -I -X utf8 -m research_pipeline.main_data_handoff --main <final-main.json> --approval <existing-context-approval.json> --out <another-new-output-directory>
```

The command checks the original main, attachment/snapshot hashes, approval signature and published rule pack, then calls `research_pipeline.adequacy.import_reviewed_context`. It verifies the complete imported object against the published main and records `B1/main.json`, its hash and `B1/context_provenance.json`. The receipt status is `IMPORTED_AT_DATA_ENTRY`; `data_started` and `data_adequacy_assessed` remain false. The CLI stops here and does not start or schedule a Data job.

The consumer is the same function used by the existing `reviewed_context` workflow step. A new adapter or Data agent input format is not introduced. Protected file contents are not interpreted; only referenced bytes are hashed. Existing access roles, scientific context, missing-information records, regimen facts and Project Rules references are retained. Pending scope amendments must be resolved in the original review workflow first. Changed references fail verification, and an existing nonempty output directory is never overwritten.
