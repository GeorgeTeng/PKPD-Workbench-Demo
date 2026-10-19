# Clinical questions and scoped downstream contracts

The dispatch adapter reads the reviewed effective context, the independently reviewed data-adequacy tasks, approved QC metadata and completed EDA. It assembles editable question drafts and source-bound branch contracts deterministically. It does not run another LLM call or estimate scientific parameters.

## Workflow

### Proposal-dependent defaults (generator 2.0)

The 12 field names are stable; their contents are retrieved from each project's reviewed `main.json`, tasks and requirements. Task-specific endpoint windows, units and exposure basis stay labeled by task. Each definition or related statement has an exact quote and JSON pointer in an evidence catalog, also inspectable from the question form. Missing definitions stay UNKNOWN; related statements do not certify a complete or consistent answer. Human edits are separately identified from generated defaults.

Binding policies, safety endpoints and acceptance criteria are no longer supplied by the PMB example. Index candidates are recognized from current declarations; absent, excluded or ambiguous candidates are not filled from a default list. This is bounded deterministic retrieval of already model-reviewed context, not another semantic LLM interpretation. New terminology or unresolved task classification requires review. Fixed branch slots and adapter capabilities do not imply that every project requests every branch. Tasks without a reviewed branch allocation remain visible as unresolved.

Completed or confirmed historical outputs are retained. Upgrading the generator does not rewrite a scientific decision or inherit approval into new answers.

1. Prepare the draft after EDA completes. Earlier context, assessment and QC must be approved. Drafting never releases data for modeling.
2. Review the 12 question fields. Keep unresolved definitions as `UNKNOWN: reason`. Confirm whether index calculations need this PK model's predictions or separately qualified matched exposure data.
3. Confirm the question definitions against the current draft and upstream signatures.
4. After EDA approval, run Clinical questions. LangGraph reads the reviewed references, invokes Prefect, and Snakemake executes `clinical_dispatch` with hashed inputs and a receipt.
5. Review the generated routing artifacts through the existing LangGraph interrupt. The downstream consumer verifies the exact artifact signature, data references and any supplemental-input approvals.

The PK/index scientific execution adapters remain a separate implementation. Dispatch approval authorizes the scoped routing; it does not certify model-ready data, predictive validity or clinical efficacy.

## Branch outputs

| File | Contents |
|---|---|
| `pk_context.json` | Animal PK and human-exposure translation tasks, source-separated concentration/dosing/binding references, applicable rules, EDA findings, missing model qualifications and expected diagnostics |
| `index_context.json` | Permitted indices, endpoint/window/free-basis definitions, MIC/PD/dosing/binding candidates, exposure dependencies, separate calculation and matched-PD fitting gates |
| `clinical_context.json` | Validation, MIC distribution, PTA readiness, feasibility/safety and study-wide revision tasks; human holdout data stay reserved |
| `clinical_questions.json` | Question definitions, explicit unknowns, original draft defaults and source provenance |
| `routing_plan.json` | Per-file destinations and reasons, unassigned sources, parallel tasks and dependencies |
| `dispatch_report.json` | Branch counts, unresolved definitions and reasons scientific calculation cannot yet pass |

Each data reference includes a SHA-256 checksum. No datasets are combined or rewritten at dispatch. Metadata and quarantine references accompany the data. Unclassified source tables require QC role qualification; nonmatching pathogen sources remain outside the current index scope. Model libraries containing mixed permissions or published fitted parameters require a separately qualified structure/code subset.

## API

Prefix: `/ui-api/workflow/sessions/{session_id}`.

- `POST /clinical-questions/draft`: generate a versioned, nonreleased draft from the current inputs.
- `GET /clinical-questions/draft/files/{name}`: inspect a verified draft JSON.
- `POST /clinical-questions`: submit all question `values`, `reviewer`, `confirmed: true`, `index_exposure_source` and current `draft_signature`.
- `POST /nodes/dispatch/start`: execute a new dispatch job, or retry a failed job with corrected definitions. Earlier compression/QC/EDA are not rerun.
- `POST /nodes/dispatch/review`: approve or return the exact generated artifacts using the standard review contract.
- `GET /nodes/{pk|index|clinical}/assigned-context`: consume the approved scoped contract plus separately approved supplemental handoff references. Returns HTTP 409 until the routing review and upstream requirements are met. `model_release` stays false.

Failed execution records a structured reason and correction action. Definitions are versioned; changes after a completed dispatch require a new study cycle. This adapter does not implement selective downstream reruns.

## Validation

Synthetic tests cover metadata routing independent of filenames, retained source boundaries, held-out/human input rejection, changed-file detection, pending-review blocking, signature-bound question confirmation and branch-specific requirements. A separate synthetic command-line run exercises LangGraph → Prefect → Snakemake without granting approval to actual research data.
