# Animal PK workflow planning

The main workflow retains its original canvas. PK model loops and the literature-assisted context review live in secondary workspaces, with return links to their parent module. JSON previews use expandable folders; folding changes presentation only.

## Entry and execution boundary

1. Clinical questions and routing produces the assigned `pk_context.json` and file references.
2. Opening Animal PK calls `POST /ui-api/workflow/sessions/{id}/animal-pk/planning/enter`.
3. The server verifies routing approval and input hashes, then constructs a draft for the species and datasets actually assigned. Re-entering the same version reuses its draft.
4. A LangGraph human-review interrupt binds the decision to that plan's signature. Review uses `POST .../planning/review`, with `plan_signature`, `decision`, `reviewer`, `confirmed` and optional `rationale` (required for revisions).
5. Agent and parallel-candidate execution endpoints reject requests until the workflow is approved. Existing scientific data qualification, model comparison and final selection gates still apply. Execution continues through LangGraph, Prefect and Snakemake.

`GET .../control` and `GET .../plan` no longer create a new plan. Opening an unprepared PK workspace cannot bypass routing approval. Changed candidate options create a new draft and require a new workflow review.

## Current adapter and reserved agent

The current planning adapter is `METADATA_DRAFT_BUILDER`. It generates a structural draft using the existing planner. **It makes zero LLM calls and zero fits.** It does not decide scientific pooling or claim that any candidate is identifiable.

`planning_agent_contract.json` reserves the `animal_pk_workflow_planner` role. Its input is the assigned PK branch context and verified file references; its intended outputs are the workflow, rationale and unresolved questions. The LLM adapter is explicitly `RESERVED_NOT_CONNECTED`. Connecting it later must preserve fresh scoped calls, validated outputs, review before execution and the existing scheduler stack.

Planning artifacts can be opened or downloaded through `GET .../planning/files/{name}`:

- `plan.json`
- `planning_agent_contract.json`
- `planning_report.json`
- `workflow_planning.json`

Legacy drafts are inspection records until explicitly initialized at PK entry and reviewed. None of these UI changes approves an existing plan or starts numerical fitting.
