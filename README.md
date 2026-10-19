# Translational PK/PD Workbench Demo

A local research workbench with two connected workspaces: **Research workflow** and **Knowledge & context**. The English interface reuses the existing pipeline, source contracts, ContextBuilder and knowledge library.

## Start on Windows

Download the complete Windows ZIP from [GitHub Releases](https://github.com/GeorgeTeng/PKPD-Workbench-Demo/releases/latest). GitHub's automatic source-code ZIP does not include the portable Python runtime.

1. Extract the complete Windows release ZIP under a short folder such as `C:\PKPD`, then open its `demo` folder. Keeping the path short avoids Windows path-length errors in scheduler dependencies.
2. Double-click `START_DEMO.cmd`.
3. Open `http://127.0.0.1:8772`. Use `STOP_DEMO.cmd` to stop this server.

The portable release includes Python 3.12 and the dependencies used by this demo. No Python installation is required for the portable release. Run from a writable local folder. Local state, imported files, run evidence and review notes are created under `state/`.

To stop an active scientific workflow, use **Pause** in its detailed workflow controls before stopping the server. The start and stop scripts manage the local web server process.

Browsing the library, RAG and ContextBuilder explanations, source inspection and recorded figures work locally without model calls. **Live Context and Data labelling require a configured model provider and network connectivity.** The default provider uses the Codex CLI on PATH with an authenticated account. Credentials and account configuration are not included.

The default execution configuration is **`gpt-6.1-sol` with `high` reasoning effort**. Requested identity is recorded in the invocation and stage-cache identity; it is not proof of the provider's served model identity. Historical PMB artifacts retain their original `gpt-6-sol` identity. To start explicitly:

```powershell
.\start-demo.ps1 -Port 8772 -Provider codex -Model gpt-6.1-sol -ReasoningEffort high
```

Live Context, key-Rules and Data model calls have no default execution timeout. The acceptance runner also waits without a stage deadline. Use **Pause** to stop an active workflow; HTTP connection and process-cleanup timeouts remain separate from model execution.

## Demonstration sequence

1. Open **File intake** and import the PMB, Meropenem or Voriconazole example. The ZIP download beside each example contains the exact three source files used in the original project demonstration.
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

The model reads permitted sources and produces requirements/labels. The host then verifies source hashes, access and label accounting, exports the original columns, retains raw cell values and locators, trims outer whitespace with a change log, and checks the actual retained/quarantined records. It performs no inferred joins, imputation, duplicate averaging or automatic scientific unit normalization in this profile. Ambiguous headers are held for review. Formula/error records remain explicit in quarantine.

When column-level unit or qualifier annotations are not copied from the cited source, this profile leaves them unresolved and records a Human-review finding. For example, a parameter table with different units on different rows has no assumed common column unit. Annotations that cannot be bound to the current table header remain unmapped review findings rather than being assigned to another column. Original rows, row-specific source wording and raw model responses remain available; these annotations and source-layout boundaries must be reviewed before analysis.

Full requirement coverage, method applicability, model readiness and predictive validity remain **`NOT_ASSESSED_IN_DEMO`**. Existing findings retain their original severity and required phase. No additional DC-review, per-table DP model planning or scientific handoff model calls run in this mode. `DEMO_TECHNICAL_DATA_READY` means source-preserving processing and mechanical QC completed; `fit_ready=false` and `scientific_release=false` remain. EDA/PK/index handoffs have `execution_authorized=false` and are available for inspection only.

Context still receives an independent source review. In this demo, a sole canonical-placement issue (such as repeated wording) can be deferred only when every record and source-unit completeness/faithfulness verdict and every other review check is preserved, with no critical errors or new-content fixes. The original `REVISE` and unchanged candidate remain bound to `demo_context_review.json`; both the receipt and original review appear in Context outputs, and their findings continue into Data and its unresolved ledger. This is technical continuation, not an independent review PASS. Full mode rejects this deferral, and missing content, changed meaning, uncertainty or conflicting conditions still block progression.

The full assessment implementation is retained separately in `backend/research_pipeline/research_pipeline/data_agents.py`; this release does not claim it passed the three-example acceptance. The oversized full-review request from the earlier PMB attempt is retained in local history, not recast as a successful scientific review.

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

Check the effective settings at `/workspace-api/capabilities`. A replacement model must produce the same validated JSON contracts and exact source citations. Similar outcomes mean source preservation, comparable scoped labels/findings and matching workflow boundaries—not byte-identical prose. Schema, evidence, permissions and QC checks continue to apply after a provider change. An arbitrary new endpoint is not considered verified until the three-example suite passes against it.

### Main endpoints

| Method and path | Use |
| --- | --- |
| `GET /demo-api/health` | Server health; this does not claim workflow completion |
| `GET /workspace-api/capabilities` | Effective provider/model and supported scope |
| `GET /workspace-api/examples` | Actual input ZIPs, checksums and download links |
| `POST /workspace-api/examples/{pmb|meropenem|voriconazole}/import` | Register an example and return its workflow ID |
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
| Example inputs | Three ZIPs, each with the proposal, source workbook and `AGENT_README.md`; package and member SHA-256 values in `examples/inputs/manifest.json` |
| Knowledge snapshot | `round12_general_reviewed_v1`: 255 cards, 80 source documents, 31 general/conditional method cards; scientific approval remains pending |
| Recorded Data review | 58 scoped tables, 499 retained source rows, no quarantined rows; descriptive EDA scope, `fit_ready=false` |
| Recorded findings | 20 findings: 12 human-review items and 8 follow-up items |
| EDA / PK previews | Three EDA subset-test figures and five PK diagnostic figures; no accepted PK model is implied |

The raw PMB workbook yields 63 source-table regions before scope review. This differs from the 58-table recorded preparation snapshot. Source organization is not scientific adequacy or readiness.

The release also includes the three newly accepted technical runs under `examples/acceptance/`. Open [the acceptance review index](examples/acceptance/index.html) from the extracted folder, or `/examples/acceptance/` on the running server. It links each example's Context, Rules, requirements, labels, Data report, QC, cleaning log, unresolved issues and signature-bound checkpoint records. These snapshots retain their original file references and are read-only; import an input ZIP for a new live run.

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

Run all three actual examples sequentially:

```powershell
.\runtime\python.exe -I -B -X utf8 tests\run_three_examples.py --approve-test-gates --output-dir state\acceptance\three_examples_sol61 --expected-model gpt-6.1-sol --expected-effort high
```

Use the same output directory to resume after a fix. Completed examples are re-verified, not automatically re-executed. The suite checks stage completion, all three signature-bound Human gates, source/artifact hashes, actual prepared records, retained findings, requested model identity, and the downstream execution boundary. Its success status is `ALL_THREE_PASSED_THROUGH_DATA`. Use the expected provider model name when testing a replacement endpoint; provider reasoning settings may differ.

For OpenAI-compatible or Claude providers, whose transport receipts do not record the Codex-specific reasoning field, use a fresh output directory and `--expected-effort none`:

```powershell
.\runtime\python.exe -I -B -X utf8 tests\run_three_examples.py --approve-test-gates --output-dir state\acceptance\replacement_api --expected-model "your-provider-model" --expected-effort none
```

Before editing backend code or rules, pause/finish active jobs: plans freeze code and input hashes. Explicitly retry a stopped stage after changes so it gets a new plan. Do not overwrite old artifacts or edit historical success/failure receipts.

An explicitly selected recovery run may reuse completed model responses with an identical request and executor identity. Each reuse retains source hashes and a receipt, and current stage validation runs again. Unsupported stated-value annotations remain `NOT_FOUND` with Human-review findings; source quotations and the original model response are preserved. Automatic checkpoint approval does not resolve those scientific findings.

## Verified release results

All three examples passed the technical workflow through Data on 2026-10-19. The source values below cover the admitted preparation scope; restricted or unresolved sources remain in their inventory and review records.

| Example | Prepared datasets | Source records | Retained records | Quarantined | Human gates recorded |
| --- | ---: | ---: | ---: | ---: | ---: |
| PMB | 49 | 417 | 417 | 0 | 3/3 |
| Meropenem | 35 | 286 | 286 | 0 | 3/3 |
| Voriconazole | 11 | 62 | 62 | 0 | 3/3 |

Open `http://127.0.0.1:8772/examples/acceptance/index.html` for the three-example overview, searchable findings, prepared-table downloads, and original checkpoint evidence. For offline review, open [examples/acceptance/index.html](examples/acceptance/index.html). The original model responses, source references and unresolved findings remain available in each run's records.

The acceptance reused PMB's retained model evidence and executed fresh Meropenem and Voriconazole model stages with requested `gpt-6.1-sol` / `high`. Debugging retries reused only responses matching the exact request and executor; the records distinguish those reuses. Provider-served model identity was not reported. Voriconazole retains the original Context `REVISE` for repeated wording through the explicit technical-demo deferral described above; the candidate and open review findings were not changed.

All 49 offline integration and local HTTP contract tests passed. The OpenAI-compatible transport was exercised against a local SSE test server; an alternative external model service has not been accepted by these runs. Run the same three-example suite after changing providers. EDA and PK were not executed, and these results do not establish scientific adequacy or model readiness.

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
