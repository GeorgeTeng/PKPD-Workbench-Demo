# Translational PK/PD Workbench Demo

A local research workbench with two connected workspaces: **Research workflow** and **Knowledge & context**. The English interface reuses the existing pipeline, source contracts, ContextBuilder and knowledge library.

## EDA navigation correction

The [category correction](docs/eda_categories_20261026.md) removes the PK variability navigation category and places its PD endpoints and protein-binding panels in the appropriate sections. All 106 figures and their source data are retained; no scientific rerun occurred.

## EDA source update — 23 October revision, published 25 October 2026

The [EDA revision and remaining gaps](docs/eda_revision_20261023.md) updates 23 EDA-owned source, test and Rules files in `native_workflow/`. It adds DH-to-v6 intake, source-axis and role safeguards, review-state summaries and provider/R configuration. This is an offline-tested engineering revision; full Context → Data → EDA integration, fresh independent review and human approval remain pending. The demo still stops at Data. No new scientific run, figure regeneration or portable release build is included.

## Source update — 22 October 2026

The [native workflow snapshot](native_workflow/README.md) now includes the latest Compression/Data/EDA context assembly, Rules and two-level human review UI. It is separate from this demo executable. The [version decision](docs/version_selection_20261022.md) retains ContextBuilder 2.1 and RAG v2.0 as the baseline; [revision14 components](research/contextbuilder_v14/README.md) are an inactive research reference. No research images or detailed data are included in this update.

## Start on Windows

Download the complete Windows ZIP from [GitHub Releases](https://github.com/GeorgeTeng/PKPD-Workbench-Demo/releases/latest). GitHub's automatic source-code ZIP does not include the portable Python runtime.

1. Extract the complete Windows release ZIP under a short folder such as `C:\PKPD`, then open its `demo` folder. Keeping the path short avoids Windows path-length errors in scheduler dependencies.
2. Double-click `START_DEMO.cmd`.
3. Open `http://127.0.0.1:8772`. Use `STOP_DEMO.cmd` to stop this server.

The portable release includes Python 3.12 and the dependencies used by this demo. No Python installation is required for the portable release. Run from a writable local folder. Local state, imported files, run evidence and review notes are created under `state/`.

To stop an active scientific workflow, use **Pause** in its detailed workflow controls before stopping the server. The start and stop scripts manage the local web server process.

Browsing the library, RAG and ContextBuilder explanations, source inspection and recorded figures work locally without model calls. **Live Context and Data labelling require a configured model provider and network connectivity.** The default provider uses the Codex CLI on PATH with an authenticated account. Credentials and account configuration are not included.

The default execution configuration is **`gpt-6.1-sol` with `high` reasoning effort**. Requested identity is recorded in the invocation and stage-cache identity; it is not proof of the provider's served model identity. To start explicitly:

```powershell
.\start-demo.ps1 -Port 8772 -Provider codex -Model gpt-6.1-sol -ReasoningEffort high
```

Live Context, key-Rules and Data model calls have no default execution timeout. The acceptance runner also waits without a stage deadline. Use **Pause** to stop an active workflow; HTTP connection and process-cleanup timeouts remain separate from model execution.

## Demonstration sequence

1. Open **File intake** and import PMB, Meropenem, Voriconazole or Imidocarb. Each ZIP contains the exact files listed in `examples/inputs/manifest.json`. Imidocarb adds an unmodified cattle source workbook and attributed source notes.
2. Run **File intake**. Registration, extraction coverage and file hashes are deterministic local I/O. This step does not invoke ContextBuilder, RAG, a model or the scientific scheduler.
3. Open **Context & Project Rules**, run Context and inspect the source-bound results. Compression completes before one key-Rules extraction. This demo uses `DEMO_PROVISIONAL_RULES`: exact source quotes and hashes are checked, and automatic acceptance is explicitly recorded. Independent Rules review and content refinement are deferred; no independent PASS is fabricated. The main interface shows the Human checkpoint.
4. Approve the Context checkpoint to unlock **Data Assessment & Preparation**. Run the lightweight Data profile, review its scope, then run preparation and handoff. The Data scope and completed-Data checkpoints remain visible even when the acceptance script automatically approves them. Decisions remain bound to output signatures.
5. Stop at Data. EDA and PK figures are recorded previews; downstream execution is disabled in this demo.
6. In the separate **Knowledge & context** workspace, browse knowledge cards and read the RAG and ContextBuilder explanations. These two pages have no manual retrieval, assembly, parameter or result controls.

The API reports actual capabilities at `/workspace-api/capabilities`. Backend operations without a connected implementation are shown as planned, recorded or unavailable. Knowledge curation and card approval are inspectable workflow descriptions, not executable actions in this distribution.

## What Data requirements mean

Requirements describe the inputs needed by a proposed analysis: source identity, units, dosing and sampling information, concentration or response observations, experimental-unit definitions, use restrictions, and prerequisites for later translation or validation. They are derived from the current project's Context and Rules; they are not a fixed checklist copied between drugs.

The default **`SOURCE_PRESERVING_DEMO_1.0`** profile runs:

```text
File registration -> Context -> key Rules -> Context Human gate
  -> inventory + requirement definition -> access permissions -> source labels
  -> technical input checks -> Data scope Human gate
  -> source-preserving export -> program QC -> metadata validation
  -> inspection handoff -> completed-Data Human gate -> STOP
```

Inventory and requirement definition currently run in parallel, before the access plan and source labels. The label-first cards in the overview describe the intended design, not an additional execution route.

The model reads permitted sources and produces requirements/labels. Registered original names, file IDs and hashes are supplied together so explicit filename permissions in Rules can be resolved. The host then verifies source hashes, access and label accounting, exports original columns, retains raw cell values and locators, trims outer whitespace with a change log, and checks actual retained/quarantined records. Blank, numeric or duplicate headers are retained using unique positional field keys, with the original headers in the column map and a review finding; no column meaning is inferred. This raw demo performs no inferred joins, imputation, duplicate averaging or scientific unit normalization. Formula/error records remain explicit in quarantine.

When column-level unit or qualifier annotations are not copied from the cited source, this profile leaves them unresolved and records a Human-review finding. For example, a parameter table with different units on different rows has no assumed common column unit. Annotations that cannot be bound to the current table header remain unmapped review findings rather than being assigned to another column. Original rows, row-specific source wording and raw model responses remain available; these annotations and source-layout boundaries must be reviewed before analysis.

Full requirement coverage, method applicability, model readiness and predictive validity remain **`NOT_ASSESSED_IN_DEMO`**. Existing findings retain their original severity and required phase. No additional DC-review, per-table DP model planning or scientific handoff model calls run in this mode. `DEMO_TECHNICAL_DATA_READY` means source-preserving processing and mechanical QC completed; `fit_ready=false` and `scientific_release=false` remain. EDA/PK/index handoffs have `execution_authorized=false` and are available for inspection only.

Context still receives an independent source review. In this demo, a sole canonical-placement issue (such as repeated wording) can be deferred only when every record and source-unit completeness/faithfulness verdict and every other review check is preserved, with no critical errors or new-content fixes. The original `REVISE` and unchanged candidate remain bound to `demo_context_review.json`; both the receipt and original review appear in Context outputs, and their findings continue into Data and its unresolved ledger. This is technical continuation, not an independent review PASS. Full mode rejects this deferral, and missing content, changed meaning, uncertainty or conflicting conditions still block progression.

The full scientific assessment implementation remains in `backend/research_pipeline/research_pipeline/data_agents.py`; it is outside this technical-demo acceptance.

When a stated-value annotation combines a note with table-body evidence, fields supported only by the body remain unresolved in this technical profile. For example, a number may occur in a note while its unit occurs only in a table row. The note annotation does not adopt that unit automatically; the source table retains it, and `STATED_LOCATION_UNRESOLVED` records the proposed field for Human review before analysis. Invalid source citations still block processing.

## API locations and configuration

The browser and backend use the same local origin, normally **`http://127.0.0.1:8772`**. Open [interactive API documentation](http://127.0.0.1:8772/docs) or the [OpenAPI schema](http://127.0.0.1:8772/openapi.json) while the server is running. There are two separate interfaces:

| Interface | Where to adjust it | Purpose |
| --- | --- | --- |
| Frontend -> workbench HTTP API | `demo/connected.py`, `demo/handoffs.py`, `demo/api.py`; browser bindings in `workspace/live.js` | Import, run, inspect artifacts and record Human decisions |
| Workbench -> model provider | CLI flags in `app.py` / `start-demo.ps1`; transport in `backend/context_compression/ctxcomp/providers.py` and `openai_stream.py` | Change the provider, model and API base without changing workflow contracts |
| Workflow stages and gates | `backend/research_pipeline/research_pipeline/workflow_runtime.py`, `workflow_canvas.py`, `preparation_workflow.py` | Scheduling, frozen inputs, signatures and review boundaries |
| Lightweight Data behavior | `backend/research_pipeline/research_pipeline/demo_data.py` | Technical checks, retained-label recovery and source-preserving handoff |
| Context routing / request assembly | `backend/research_pipeline/research_pipeline/context_routes.py`, `context_gateway.py`, `context_builder.py` | Task-specific inputs, evidence binding and transport budget |
| Knowledge library | `knowledge/` and its pinned catalog | Source-backed reference cards; draft status remains explicit |

Stop the server before changing its launch configuration. An already-running server keeps its current settings. A new model configuration applies to new calls; saved results retain their original identity.

```powershell
.\stop-demo.ps1 -Port 8772
.\start-demo.ps1 -Port 8772 -Provider codex -Model gpt-6.1-sol -ReasoningEffort high
```

For a server implementing **OpenAI-compatible streaming Chat Completions**, set the credential locally if required, then use its exact model name and base URL:

```powershell
# If authentication is required, set this in the same PowerShell session.
$env:CTXCOMP_OPENAI_API_KEY = "replace-with-your-local-key"
.\stop-demo.ps1 -Port 8772
.\start-demo.ps1 -Port 8772 -Provider openai -Model "your-provider-model" -ApiBase "http://127.0.0.1:11434/v1"
```

The adapter appends `/chat/completions`; do not include that suffix in `-ApiBase`. It expects SSE `data:` events containing `choices[].delta.content` and a final `[DONE]`. This adapter is not a Responses-API adapter. Provider-specific optional request fields can be supplied as JSON in `CTXCOMP_OPENAI_EXTRA`; `CTXCOMP_OPENAI_RESPONSE_FORMAT=json_object` is available only when supported by the selected server. API keys are read from `CTXCOMP_OPENAI_API_KEY`, never from the frontend or committed configuration. Claude Code is also selectable with `-Provider claude -Model "your-claude-model"` when its CLI is installed/authenticated.

Check the effective settings at `/workspace-api/capabilities`. A replacement model must produce the same validated JSON contracts and exact source citations. Similar outcomes mean source preservation, comparable scoped labels/findings and matching workflow boundaries—not byte-identical prose. Schema, evidence, permissions and QC checks continue to apply after a provider change. An arbitrary new endpoint is not considered verified until fresh acceptance passes against it.

### Main endpoints

| Method and path | Use |
| --- | --- |
| `GET /demo-api/health` | Server health; this does not claim workflow completion |
| `GET /workspace-api/capabilities` | Effective provider/model and supported scope |
| `GET /workspace-api/examples` | Actual input ZIPs, checksums and download links |
| `POST /workspace-api/examples/{pmb|meropenem|voriconazole|imidocarb}/import` | Register an example and return its workflow ID |
| `POST /workspace-api/imports` | Upload one ZIP as multipart field `file` |
| `GET /ui-api/workflow/sessions/{id}` | Stage states, output signatures, artifacts and Human decisions |
| `POST /ui-api/workflow/sessions/{id}/nodes/{node}/start` | Start `intake`, `context`, `adequacy` or `prepare` when the native gate permits |
| `POST /ui-api/workflow/sessions/{id}/nodes/{node}/review` | Record a decision for the exact output signature |
| `POST /ui-api/workflow/sessions/{id}/pause` | Request cancellation of the active workflow |
| `GET /ui-api/workflow/sessions/{id}/nodes/{node}/artifacts/{name}` | Download a verified stage artifact |
| `GET /workspace-api/workflow/{id}/handoffs` | List read-only agent requests/responses and assembled context |
| `GET /workspace-api/workflow/{id}/handoffs/{call}/files/{name}` | Inspect one allowlisted artifact; response includes `X-Artifact-SHA256` |

Minimal PowerShell API example, from the same machine:

```powershell
$base = 'http://127.0.0.1:8772'
$run = Invoke-RestMethod "$base/workspace-api/examples/pmb/import" -Method Post -ContentType 'application/json' -Body '{}'
$flowId = $run.id
Invoke-RestMethod "$base/ui-api/workflow/sessions/$flowId/nodes/intake/start" -Method Post -ContentType 'application/json' -Body '{}'
Invoke-RestMethod "$base/ui-api/workflow/sessions/$flowId"
```

Poll the session until the stage completes. Start the next stage only when `can_run=true`. A review body contains `decision`, `reviewer`, `rationale`, `confirmed=true`, and the current `output_signature`; Context approval additionally requires `objective_decision="CONFIRMED"`. Use the UI or the explicit acceptance script to record these decisions. Changed outputs invalidate old approvals.

## Inspect agent-to-agent context

Open a Research stage -> **Context & references**. Select the current run, filter the agent stage, and expand a call. **Include earlier attempts** shows retained evidence from preceding jobs. The viewer is read-only and never assembles or sends a new request. The separate RAG and ContextBuilder pages remain explanation-only.

| Saved file | What it shows |
| --- | --- |
| `request.json` | Task, applicable Rules, source/data inputs, instructions and expected output contract |
| `assembled-model_input.json` / `assembled-model_prompt.txt` | The actual ContextBuilder model input and prompt, when recorded for this call |
| `assembled-context_manifest.json` / `assembled-projection_manifest.json` | Input sections, provenance, retained/omitted fields and request binding |
| `assembled-budget.json` | Measured application transport size; not a model tokenizer guarantee |
| `response.json` | Original model response; existence alone does not establish acceptance |
| `call.json` / provider receipt | Requested model, reasoning effort, duration, status and timeout setting |
| `replay.json` | Explicit reuse of an identical request/response with original source bindings |

Deterministic steps have stage artifacts rather than invented model-call records. Their program QC, cleaning log, metadata validation, unresolved ledger and inspection handoffs are downloadable from **Outputs**. Completed labels restored into a new technical-demo attempt carry `retained_inputs.json`, preserve their original model identity and do not count as new calls.

## Sources and evidence

| Content | Included scope |
| --- | --- |
| Example inputs | Four ZIPs with proposals, original source workbooks and `AGENT_README.md`; Imidocarb also includes attributed source notes. Package and member SHA-256 values are in `examples/inputs/manifest.json`. |
| Knowledge snapshot | `round12_general_reviewed_v1`: 255 cards, 80 source documents, 31 general/conditional method cards; scientific approval remains pending |
| Current Data review | Four source-bound technical runs from different code versions under `examples/acceptance/`; actual counts and timings appear below, with `fit_ready=false`. |
| Findings and Human gates | Every current run retains its own unresolved findings and three signature-bound automatic demo approvals. |
| EDA / PK previews | Three EDA subset-test figures and five PK diagnostic figures; no accepted PK model is implied |

Inventory, admission and preparation counts describe different steps. Restricted or unresolved sources remain in the inventory and review records; a prepared dataset count is not a scientific adequacy claim.

The release also includes the four verified technical runs under `examples/acceptance/`. Open [the acceptance review index](examples/acceptance/index.html) from the extracted folder, or `/examples/acceptance/` on the running server. It links each example's Context, Rules, requirements, labels, Data report, QC, cleaning log, unresolved issues and signature-bound checkpoint records. These snapshots retain their original file references and are read-only; import an input ZIP for a new live run.

Review notes in the Data page are stored locally in SQLite and tied to the recorded report hash. They do not change live workflow permissions. Live checkpoint decisions use the original workflow controls. Automatic Human-gate approval is available only in the explicit acceptance script described below; its decisions are technical test progression, not independent human scientific review or release.

## Verify

Run the integration checks:

```powershell
.\runtime\python.exe -I -B -X utf8 -m unittest discover -s tests -p "test_*.py" -v
```

Run the real model-backed acceptance through Data, with explicit authorization to pass its Human gates:

```powershell
.\runtime\python.exe -I -B -X utf8 tests\run_data_acceptance.py --approve-test-gates --max-context-repairs 0 --output state\acceptance\data_acceptance.json
```

This performs real Context, Rules and Data requirement/label calls and can consume account usage. It records failures and checkpoint decisions; the command above does not request Context revision loops. It never runs EDA or PK. An integration test pass alone does not establish a successful model-backed run. Only an acceptance report with `status=PASSED_THROUGH_DATA` establishes completion of this technical demonstration.

Run all four examples **from scratch**, with no response reuse, no resume and no manual repair:

```powershell
$round = Get-Date -Format 'yyyyMMdd-HHmmss'
$state = Join-Path $PWD "state\fresh-$round"
$report = Join-Path $PWD "state\acceptance\fresh-$round"
.\start-demo.ps1 -Port 8774 -NoBrowser -StateDirectory $state -Provider codex -Model gpt-6.1-sol -ReasoningEffort high
.\runtime\python.exe -I -B -X utf8 tests\run_fresh_examples.py --base http://127.0.0.1:8774 --state-root "$state" --output-dir "$report" --approve-test-gates
```

The server disables response reuse by default, even if an old Data replay path exists in the environment. The driver rejects old sessions, requires one start per stage, verifies fresh call receipts and all three visible Human gates per example, and checks actual source/data artifacts and the unchanged code/input snapshot. Success is `ALL_FOUR_PASSED_FRESH_THROUGH_DATA`. Failed rounds remain available; fix code and rerun all four in a new state directory. See [the fresh acceptance guide](docs/fresh-acceptance.md).

The accepted release includes [runtime_summary.csv](examples/acceptance/runtime_summary.csv) and [runtime_summary.json](examples/acceptance/runtime_summary.json). They record each example's total wall time, workflow stages, Context generation/review, Rules, requirements, access and parallel label calls, with UTC timestamps and source-receipt hashes. Model rows are nested inside workflow rows; cumulative parallel-call time must not be added to elapsed wall time. Totals include scheduling and final verification, and exclude earlier diagnostic rounds. These are observed client-side durations, not a guarantee of runtime with another provider.

After changing to an OpenAI-compatible or Claude provider, start a new server and new state directory using that provider's exact model name, then run the same fresh driver with `--expected-model "your-provider-model" --expected-effort none`. These transports do not record the Codex-specific effort field. A contract-compatible local transport test does not verify the quality of another external model.

Before editing backend code or Rules, finish or pause active jobs: plans freeze code and input hashes. Never overwrite historical outputs or edit success/failure receipts. The older `run_three_examples.py` remains a resumable diagnostic tool; it is not the fresh four-example acceptance. Historical response reuse is an explicit opt-in server mode (`--allow-response-reuse`), and the fresh driver rejects it.

## Current verified Data results

All four packaged examples have completed the technical workflow through Data. PMB, Meropenem and Voriconazole come from `fresh03`; Imidocarb comes from `fresh05`, after fixes for registered filename identity and preservation of blank/numeric source headers. **These results come from different code versions, not one unchanged-code four-case suite.** The user stopped the redundant full rerun. Each selected case had one attempt, no response reuse, no resume and no manual output repair. Requested model: `gpt-6.1-sol / high`; provider-served identity was not reported. The source records below cover admitted preparation scope; restricted or unresolved sources remain in the inventory and review records.

| Example | Prepared datasets | Source records | Retained records | Quarantined | Human gates recorded | Total wall time |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| PMB | 52 | 364 | 364 | 0 | 3/3 | 48 min 43 sec |
| Meropenem | 36 | 293 | 293 | 0 | 3/3 | 42 min 32 sec |
| Voriconazole | 12 | 75 | 75 | 0 | 3/3 | 32 min 03 sec |
| Imidocarb (cattle) | 4 | 56 | 56 | 0 | 3/3 | 8 min 43 sec |

Each duration includes scheduling and final verification; there is no combined suite wall time for this collection. Open [the current result index](examples/acceptance/index.html) for findings, prepared tables, original Human-gate records and agent-to-agent request details. The [runtime CSV](examples/acceptance/runtime_summary.csv) and [runtime JSON](examples/acceptance/runtime_summary.json) break down workflow and model-call time with source-receipt hashes. Failed diagnostic and user-stopped rounds are recorded separately in [diagnostic_timings.csv](validation/diagnostic_timings.csv); they are excluded from the selected-case durations.

The largest PMB cost was source labeling: 52 model calls with four concurrent workers took **24 min 22 sec** of its **48 min 43 sec** total. Context generation took 8 min 50 sec; Data preparation and handoff took 22 sec. Label calls must not be summed as elapsed wall time. See [runtime_profile.csv](validation/runtime_profile.csv) for the stage comparison. No new model runs were launched to prepare this release.

| Example | Context, review and Rules | Data requirements and labels | Preparation, QC and handoff | Total |
| --- | ---: | ---: | ---: | ---: |
| PMB | 13m 11s | 35m 00s | 22s | 48m 43s |
| Meropenem | 12m 06s | 29m 53s | 21s | 42m 32s |
| Voriconazole | 15m 22s | 16m 22s | 16s | 32m 03s |
| Imidocarb | 3m 21s | 5m 03s | 15s | 8m 43s |

Totals also include intake, scheduling and final verification. Model calls below are nested inside the workflow stages above; do not add both tables together.

| PMB step | Purpose | Wall time |
| --- | --- | ---: |
| Context generation | Compress the project sources | 8m 50s |
| Context review | Check meaning, omissions and conditions | 2m 38s |
| Rules extraction | Extract key project constraints | 1m 27s |
| Requirements | Identify the needed data | 5m 34s |
| Source access | Determine which sources may be reviewed | 4m 49s |
| Source labels | 52 model calls with four concurrent workers | **24m 22s** |
| Preparation, QC and handoff | Preserve source values and generate outputs | 22s |

The later duplicate PMB attempt was stopped by the user after 9m 10s; it is excluded from these completed-case times. Its earlier status message saying Context review was still running is no longer current.

The original Context review remains REVISE for canonical-placement findings in Meropenem. The existing technical-demo deferral preserves the unchanged candidate and every review finding; it is not an independent review PASS.

All 57 offline integration and local HTTP contract tests passed. The OpenAI-compatible transport was exercised against a local SSE test server; another external model service has not been accepted by these cases. Run the same fresh four-example suite after changing providers. EDA and PK were not executed; technical completion does not establish scientific adequacy or model readiness.

## Label optimization (20 October 2026)

The lightweight Data demo now sends source-focused Label requests and defers modeling/PTA adequacy and requirement matching. A PMB-only comparison reduced Label wall time from 24m 22s to 17m 32s (28.1%), with source coverage and all 161 previously explicit column units unchanged. One mixed-column unit issue was corrected and verified with one additional table call (54 seconds). The final prompt was not rerun across all examples. See the [comparison, review findings and retained evidence](validation/label_comparison_pmb/README.md). These changes are in the source checkout; the existing v0.1.1 portable archive has not been rebuilt.

## Source layout

- `workspace/`: the approved two-workspace interface and live API bindings.
- `frontend/`: the original detailed workflow controls, served at `/workbench`.
- `demo/`: thin API adapters, evidence catalog and persistent review-note store.
- `backend/`: original scientific workflow, ContextBuilder, model adapters and deterministic contracts.
- `knowledge/`: pinned knowledge snapshot and active retrieval adapter.
- `rag_candidate/`: archived candidate prototype; not the active retrieval implementation.
- `examples/`: actual input packages and separately labelled recorded evidence.
- `docs/`: the English weekly presentation.
- `upstream_docs/` and `pkpd_r/`: retained upstream documentation and scientific support code; their presence does not enable downstream execution.

For a source checkout, create a Python 3.12 virtual environment, install `requirements-demo.txt`, and install `backend/context_compression` and `backend/research_pipeline` in editable mode. Their imports must be available to isolated Python workers. Then run `python -I -B app.py` from this folder. `runtime_dependencies.json` records all versions in the Windows portable runtime.

The server binds only to `127.0.0.1`. Use a private repository for these project materials. Existing source-document and dependency licenses remain applicable; this package does not assign new rights to third-party literature. Portable dependencies retain their packaged license metadata.
