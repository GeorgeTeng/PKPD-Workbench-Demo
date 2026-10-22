# Parallel context review and live diagnostics

## Execution contract

New runs (Workbench intake, the CLI and the Python `init_run` default) bind
`context_review_mode: parallel_v3` in their immutable input bundle. To run the
global conflict review after both branches instead, set
`CTXCOMP_CONTEXT_REVIEW_MODE=parallel_v2` before starting the Workbench;
`parallel_v1` also uses one faithfulness review. Existing runs keep the mode they
were created with (`legacy`, `parallel_v1`, `parallel_v2` or `parallel_v3`), so their
reviewed artifacts can still be verified. The mode cannot be changed in place. New retries use the current
Workbench intake contract.

The first three stages remain requirements extraction, requirements review, and
context generation. The final review now executes:

```text
                         ┌─ faithfulness ──┐
source + candidate ──────┤                ├─ global conflicts ─ validation ─ main.json
                         └─ completeness ─┘
```

Both branches receive the full proposal as ordered, lossless source units. Each
receives its own schema and task instructions. Completeness also receives the
reviewed requirement inventory. The global reviewer receives the full proposal,
candidate, inventory and both branch reviews. There is no new content limit.

Faithfulness must cover every scalar field and its atomic claims. Completeness
must cover every inventoried requirement/component and every source unit, and
independently inspect inventory omissions. From compression rules 1.20.0 (CC002) the
per-unit verdicts cover the proposal's own units, listed in `review_source_unit_ids`;
cited supporting passages are checked wherever they are cited. Earlier runs keep
one verdict for every unit. Global review covers source permissions,
cross-field consistency, cross-section conditions, phase boundaries, and exposure,
units and endpoints. It cannot override a branch rejection.

Two workers write separate artifacts. Only the parent thread changes acceptance
state. A malformed response or failed call stops execution and cancels the other
active branch. A valid REVISE/NEEDS_REVIEW still reaches global reconciliation,
but cannot publish. All branch requests, responses and aggregate hashes must
verify before acceptance. An old single-review response cannot bypass this gate.

Downstream handoff remains a single version 3.0 `main.json`. Internal branch
responses, schemas, proof, timing logs and evidence stay in the audit directory.
Human scientific acceptance remains separate from these model checks.

## Split faithfulness review (`parallel_v2`)

Faithfulness is the slowest branch because it writes one claim per context field
plus its atomic claims. `parallel_v2` splits it into `FAITH_PARTS` (3) parts that
run alongside completeness:

```text
                         ┌─ faithfulness part 1 ─┐
                         ├─ faithfulness part 2 ─┤
source + candidate ──────┼─ faithfulness part 3 ─┼─ combine ─ global conflicts ─ validation ─ main.json
                         └─ completeness ────────┘
```

- `faithfulness_parts` cuts the context fields, in document order, into contiguous
  groups of similar text length, and the scientific item IDs into contiguous groups.
- Every part still receives the full proposal, candidate context and any
  scientific_context. It reports claims, decomposition and atomic claims only for
  its `review_part.paths`, and scientific checks only for its IDs.
- Each part is validated alone (its fields exactly once). The combined review must
  then pass the ordinary whole-context faithfulness checks. Atomic claim IDs are
  prefixed with their part (`P2-…`).
- The global reviewer receives the combined faithfulness review, so cross-field
  conflicts are still checked over the whole context.
- The proof records `faithfulness_parts` and each part's request and response;
  verification rebuilds the parts from the context and rejects any change.
- On retry, parts and branches that already validated in this run are reused;
  only the others are called again. A failed part or branch does not stop the
  others in its group: they finish so that a retry can reuse them, and the first
  failure in plan order is reported.

Compare both modes on the synthetic suite with
`.venv-context/Scripts/python.exe -I -X utf8 -m ctxcomp.review_benchmark --out outputs/review_benchmark_v2 --live --modes parallel_v1 parallel_v2`.

## Concurrent conflict review (`parallel_v3`)

`parallel_v3` keeps the split faithfulness review and also starts the global
conflict review together with the faithfulness parts and completeness:

```text
                         ┌─ faithfulness parts 1-3 ─┐
source + candidate ──────┼─ completeness ───────────┼─ combine ─ validation ─ main.json
                         └─ global conflicts ───────┘
```

- The global reviewer receives the full proposal, candidate, inventory, warnings
  and any scientific_context, but no branch reviews. It still completes all five
  global checks; it no longer reconciles disagreements between the branch reviews.
- The release rule is unchanged: the aggregate takes the worst of the three
  decisions and keeps every branch and global finding, so a global PASS cannot
  override a branch REVISE or NEEDS_REVIEW.
- The proof lists the global review with the first group of requests;
  verification rebuilds its request without branch findings.
- The conflict review no longer waits for the slowest branch, which removes one
  model round from the critical path.
- Runs frozen with compression rules 1.22.0 or later also give every
  faithfulness part, the completeness review and the conflict review
  `supporting_questions`: each attachment question, its answer status, the
  supporting passages cited for it and, listed apart as `cited_proposal_ids`,
  any proposal passages the answer also cites. Faithfulness parts are told that
  the conflict review runs at the same time without their findings. Runs frozen
  with 1.20.0 or 1.21.0 rebuild their original requests unchanged.

## Concurrency, silent calls and rate limits

- `CTXCOMP_REVIEW_WORKERS` caps how many requests of the first review group run
  at once. The default runs them all (up to five in `parallel_v3`: three
  faithfulness parts, completeness and the conflict review); the value must be a
  whole number of at least 1.
- `CTXCOMP_MODEL_SILENCE_SECONDS` stops a model call whose CLI has sent no output
  for that many seconds (at least 60). It is unset by default, and then no call is
  stopped for silence. The step stops with `MODEL_SILENT` and can be retried. The
  Codex CLI usually sends nothing between `turn.started` and its final message, so
  the silent gap is nearly the whole call: in the October 2026 workbench runs the
  longest call (requirements) took about 11 minutes. A value such as 1800 stops a
  hung call without stopping normal ones; check `event_timeline.jsonl` first.
- A rate or usage limit reported by the model service stops the step with
  `MODEL_RATE_LIMITED` rather than `MODEL_RESPONSE_UNAVAILABLE`. Wait, then retry;
  if it recurs, lower `CTXCOMP_EVIDENCE_WORKERS` or `CTXCOMP_REVIEW_WORKERS`.
- In the workbench, Retry context continues the same run when its code and inputs
  are unchanged (`research_pipeline/docs/CONTEXT_REVISIONS.md`), so accepted
  stages and validated calls are reused.

## Real-time files

Each call writes under `context_work/audit/model_calls/<invocation>/<stage>/`:

| File | Meaning |
|---|---|
| `events.jsonl` | CLI stdout lines, saved as they arrive; secrets redacted |
| `stderr.log` | CLI stderr, saved as it arrives; secrets redacted |
| `event_timeline.jsonl` | Event type, item type, client receive time, elapsed seconds, usage/errors when provided |
| `progress.json` | Latest phase, first event/assistant response, output completion, turn completion and CLI exit |
| `heartbeats.jsonl` | Five-minute local liveness reports |
| `call.json` | Request digest, input size, selected/default model and terminal call status |
| `progress_write_failures.json` | Diagnostic copies that could not be written, for example while another program held the file open; the call continued |

`thread.started` and `turn.started` are not assistant responses. An error/reconnect
event is logged as an error event. When `turn.completed` arrives while the process
is alive, the UI says it is waiting for CLI exit. Timestamps are client receive
times, not server first-token measurements; a CLI that emits only completed
messages can make first response and output completion identical. A heartbeat
proves local liveness only. No default model-call deadline was reintroduced.

## Validation and performance evaluation

`test_split_review.py` exercises concurrency, exhaustive coverage, proof tampering,
missing branches, global failure, legacy bypass and rejection precedence. The six
authored defect verdicts test the release gate; they do not measure LLM accuracy.
`test_model_progress.py` uses a real synthetic subprocess and reads its files
before exit to check live timing, error events, redaction and cancellation.

For actual model comparison:

```powershell
.venv-context/Scripts/python.exe -I -X utf8 -m ctxcomp.review_benchmark --out outputs/review_benchmark_new --live
```

Omit `--live` to materialize fixtures without calling a model. Use a new output
directory each time. The suite contains a clean control plus six individual
mutations: MIC freeze omission, literature/benchmark permission conflict,
free/total substitution, units change, conditional loss and negation loss.

Both implementations review the same source and candidate. Order alternates by
case. Defect labels stay outside model requests. Report valid reviews, affected
requirement detection, false releases, clean false rejections, engineering errors
and elapsed time separately. Stop on an engineering failure. Raw model outputs
remain available for manual scoring; a wrong verdict elsewhere is not counted
as detection of the injected defect. These small English fixtures and a single
repetition cannot establish production accuracy, statistical non-inferiority or
a reliable speedup. Repeat matched real-proposal trials before those claims.

## Existing workflow connection gap

The historical Data adequacy canvas node has `target: null` and
`AWAITING_APPROVED_DATA_ADAPTER`. Context approval is saved, but that node has no
registered scientific executor. The UI now states this explicitly. Connecting
the adequacy runner and its output/status contracts is separate from the review
parallelization change; enabling its button alone would not execute an assessment.
