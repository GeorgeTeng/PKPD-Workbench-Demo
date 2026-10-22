# Context revision interface

A semantic `REVISE` / `NEEDS_REVIEW` stops compression without publishing `B1/main.json` or a successful compression receipt. It is displayed as **Revision required**, with reasons, suggested changes, original proposal excerpts, and the complete review JSON. Technical logs remain available in a collapsed section. Engineering failures remain separate.

## Two explicit actions

- **Repair extraction from review feedback** keeps the proposal and all attachments. The reviewed stage is generated again: its request receives the prior review as `previous_feedback` and any extraction guidance as `revision_guidance`, then it is reviewed again. Guidance is administrative feedback; it cannot create scientific facts or permissions, and it lapses once a new review decision replaces the one it answered. Source conflicts must stay explicit and may still require a revised proposal.
- **Upload a revised proposal** replaces only the identified proposal. Use this when changing scientific scope, permissions or requirements. Other attachments, including opaque held-out references, are retained with their registered hashes.

Repairing extraction continues the stopped run when its code and input files are unchanged: accepted stages, including attachment evidence, are reused and only the reviewed stage and the stages after it run again. When the run cannot continue (for example because the code changed since it started), the submission starts a new canvas session, job, file-dependency plan and model attempt instead, and records why in `same_run_unavailable`. Uploading a revised proposal always starts a new run. Either way, previous inputs, failed submissions, logs and review evidence are retained, no scientific approval is inherited and no downstream scientific result is reused. Model token/content limits are unchanged. Model calls have **no forced deadline** by default.

## API

`GET /ui-api/workflow/sessions/{session_id}/context-feedback`

Returns `signature`, `stage`, `decision`, `issues`, exact `source_evidence`, affected `source_units`, `raw_review` and evidence hashes. Review evidence must match the recorded stop and belong to the current attempt.

`POST /ui-api/workflow/sessions/{session_id}/context-revisions`

```json
{
  "feedback_signature": "from the feedback response",
  "mode": "REPAIR_EXTRACTION",
  "proposal_upload_id": null,
  "guidance": "Restore the omitted requirement and retain source ambiguity explicitly.",
  "submitted_by": "Researcher",
  "confirmed": true
}
```

For `REPLACE_PROPOSAL`, first upload one DOCX, PDF, Markdown or text proposal through `POST /pipeline/v1/attachments` (multipart `file`). Send its `upload_id` as `proposal_upload_id`. A successful submission returns HTTP 202 and a session view: the same session when the run continues, otherwise the new one. Follow its `session_id` to observe execution and pause it if necessary. Once a new run exists, further submissions against the same parent are rejected; the parent links to the child attempt.

A continuation is recorded at `state/workbench_jobs/{job}/context_attempts/{id}.json`; an extraction repair is also recorded in the run's `context_work/audit/revisions/` and `context_work/feedback/{stage}.guidance.json`. A new run's submission is recorded at `state/canvas_sessions/{child}/context_revision.json`, in the new job request and in hashed context inputs. The runtime propagates feedback into the model's request payload. New source citations must use the current intake IDs, even when replacement changes file ordering.

## Execution failures and retries

Execution failures have a separate `failure` object in job and node state: `code`, `stage_label`, `summary`, `known_facts`, `uncertainty`, `suggested_actions`, `materials_note`, `retry_supported`, and an evidence-bound `signature`. A timeout does not establish a problem with the proposal or scientific data. Unknown errors remain explicitly undiagnosed. Full technical details stay in the audit and a collapsed UI section.

For eligible failures, **Retry context** calls:

`POST /ui-api/workflow/sessions/{session_id}/context-retries`

```json
{"failure_signature": "from node.state.failure.signature", "confirmed": true}
```

When the run's code and input files are unchanged, the retry continues the same run: accepted stages and validated model calls (attachment evidence calls and review branches) are reused and the stopped stage runs again. Otherwise the original proposal and attachments are hash-verified and copied into a new run. Old approvals and successful compression receipts are not fabricated or inherited. Failure signatures, duplicate submissions and source changes are checked before launch.

Retry is offered for model-call failures such as `MODEL_TIMEOUT`, `MODEL_RATE_LIMITED` (the service reported a rate or usage limit), `MODEL_SILENT` (a call stopped by the opt-in `CTXCOMP_MODEL_SILENCE_SECONDS` limit) and `MODEL_RESPONSE_UNAVAILABLE`, and for `WORKER_EXITED`. The workbench reports `WORKER_EXITED` when the process running a step has ended without recording an outcome, for example after the workbench was closed or restarted. It records each worker's process ID and start time in `workbench_jobs/{job}/worker.json`; a retry is refused while that process is still running.

## Five-minute status messages

While a model subprocess runs, the provider writes `audit/model_calls/{invocation}/{stage}/progress.json` with the last local liveness check, elapsed time, process ID, event count and time of the last received model event. Every 300 seconds it also appends a message to `heartbeats.jsonl`. The browser displays each new message and shows the most recent one in the step panel. Messages remain on disk when the browser is closed.

Local process liveness is **not proof of remote model progress**. A stale monitor is labeled as stale rather than alive. The existing Pause control stops the active process tree through the executor. Content budgets and automatic retries are unchanged. Explicit timeout arguments remain available for isolated tests; production calls use `timeout=None`.

## Validation scope

Tests use isolated synthetic proposals and mocked model responses or launchers. They exercise source preservation/replacement, evidence hashes, feedback propagation, engineering-versus-semantic routing, attachment restrictions and downstream gating. Passing these tests establishes interface behavior; it does not establish that a real revised proposal will pass semantic review or produce valid scientific predictions.
