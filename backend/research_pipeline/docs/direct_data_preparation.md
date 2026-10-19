# Direct Data preparation

The approved DirectDataReview checkpoint can enter the existing DP, host QC,
metadata validation and independent DH workflow without rerunning Coverage or
Necessity. The adapter retains the original assessment and its limitations; it
does not manufacture a legacy scientific PASS.

Use the authoritative `review.json` under `workbench_state/direct_data_reviews`.
The batch-local `human_gate.json` is a historical snapshot and may predate the
human decision. The reviewer, confirmation, timestamp, signature and all input
bindings must remain current. No command below creates human approval.

```powershell
$env:CTXCOMP_MODEL_PROVIDER = 'codex'
.\.venv-context\Scripts\python.exe -I -X utf8 -m research_pipeline.direct_preparation `
  --review <approved-review.json> --output <run-directory> --model gpt-6-astra
```

Preparation uses deterministic host planning, with zero DP model calls.
`--previous-plan <preparation_plan.json>` reuses source-bound reviewed mappings
and findings after checking the same approval and inventory. Otherwise only
unique reviewed meanings with explicitly supported header units are mapped.
`--host-only` prepares and self-checks outputs without calling the reviewer.

The run produces the preparation plan, source-preserving JSON/CSV datasets,
quarantine, metadata, transformation log, program QC and independent handoff
report. A failure retains its evidence and valid cached plans. Reuse the same
run directory to retry unchanged inputs; use a new directory for another reviewed
checkpoint.

DH uses one independent package call, with no elapsed-time limit and no
automatic retry. Large inputs supply first/last rows plus every marked exception
and quarantined row, all table metadata/notes, requirements and open findings.
The report states the exact supplied and unchecked model record scope; host QC
checks all records. Repeated values and provenance are sent once, with complete
original artifacts bound by the execution manifest. A model review is never
described as exhaustive when selected records were supplied.
The package response must pass check-ID, ledger and evidence validation before
cache reuse. Input bindings are checked before/after calls and publication.
Each fresh call retains one request, response and compact timing/identity record;
cache reuse appends one short JSONL entry without copying the request again.
The transport schema constrains fixed request hashes and permitted DP citation
identifiers, and limits scalar mappings to the current adapter's supported
header/target pairs. Units documented only in notes remain preserved metadata;
this adapter does not convert them into new scalar fields. Host validation still
rejects invalid replies without editing them.

`technical_processing_complete` records host processing and metadata checks.
`handoff_review_complete` records completion of the independent review.
`status` and `cleaning_complete` retain the existing handoff eligibility meaning;
they can remain pending when scientific definitions or unsupported mappings are
unresolved. On rerun, persisted outputs are checked; damaged derivatives are
rebuilt once from unchanged approved sources. Source drift blocks repair.
DP009 planning-time execution checks remain in the original plan and close in
host QC with explicit resolutions; legacy model plans retain DH ledger handling.
Scientific identity and mapping gaps remain separate. No EDA, fitting, index
selection, human prediction or scientific release is executed by this command.

After host QC and metadata validation, `data_preparation/reading_package.zip`
contains one independent `tables/<ID>/table.md` per table, a short index and
`manifest.json` (format 2.2). It is refreshed after a
completed handoff review. No model call is used to create it.

The default downstream input is the selected table view. There is no duplicated
rule/context dump or separate `scope.md`. Each view has a title, condition line,
data and scientific notes/limits. Unflagged pixel coordinates and digitization
point labels stay in full JSON; biological IDs and interpretation flags remain.
Exact identity-derived columns and repeated sentences are shown only once.
Units appear in headers; empty strings, nulls and censoring remain distinct.
Repeated missing placeholders use one table-local legend only when their status
is uniform across all displayed cells, including quarantine. Ambiguous statuses
and censored zeros remain explicit. A constant X-unit column is omitted only
when every value matches the coordinate header unit and no annotation is lost.
Non-applicable metadata placeholders are omitted; source data values are not.
Exact repeated statements are merged across context and notes; the duplicate
host mapping/gate notices become one statement. Distinct scientific limits remain.
Values, units, censoring, missingness, experimental-unit definitions and use
restrictions remain visible. Citation payloads, source locations and audit
history stay in the full JSON files outside the reading package. The manifest
records their paths relative to `source_root` and SHA-256 for on-demand retrieval.
Resolve the path and verify its hash before reading; calculations continue to
use the full original CSV/JSON. Moving the reading ZIP alone does not move those
underlying files or grant scientific release.

To split or regroup existing tables without recomputing data:

```powershell
.\.venv-context\Scripts\python.exe -I -X utf8 -m research_pipeline.reading_package `
  --execution <data_preparation/preparation_execution.json> `
  --output <selected_tables.zip> --tables T0028 T0054
```

Omit `--tables` for every table. Selection preserves table boundaries, not a
biological join; duplicate or unknown IDs are rejected. Keep the regenerated
manifest with selected table folders. These are reading views, not a complete
analysis context: load applicable project rules and the referenced review before
analysis. Packaging does not approve pending scientific or mapping gates.


Operation-scoped handoff uses `OPERATION_SCOPED_V1` in new direct runs. The
existing independent call returns `affected_operations` on each finding. A
rejected dataset must have a matching scoped finding; a PASS cannot contradict
a blocking finding for descriptive EDA. These checks run before caching.

The host scopes each restriction to its named use rather than letting a table
status veto every action. `required_by` still records the decision deadline and
is preserved in the ledger. Legacy current-phase items without a typed scope
remain conservative blockers. Integrity, permissions and global checks keep
their existing gates. Unknown scope is never silently interpreted as approval.

Only separate-source descriptive display can be handed off by this workflow.
It preserves units, series, matrices, time alternatives, missingness, censoring
and source conflicts. Longitudinal joins, time-axis selection, dose-response or
cross-table linkage, matrix conversion, uncertainty weighting, censored-value
calculations, MIC-weighted PTA, NCA and fitting receive no execution authority.
The report, scoped EDA handoff and ZIP manifest carry operation restrictions;
the existing workbench renders them. One independent call remains the default.

Scientific row identity and time coordinates remain explicit in compact model
inputs rather than inherited from modal defaults. This changes presentation
only; exact round-trip reconstruction and all source values are preserved.
