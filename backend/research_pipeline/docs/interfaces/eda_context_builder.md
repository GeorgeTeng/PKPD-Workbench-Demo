# EDA ContextBuilder integration

`research_pipeline.eda_context.prepare(call_id, inputs, schema)` prepares an
immutable bundle. It does not execute EDA, grant Data access, validate scientific
adequacy or approve a handoff. The existing EDA runtime and R workers remain
disabled/interface-only.

| Model entry | Supplied evidence | Result |
| --- | --- | --- |
| `EP-plan` | Data handoff, task context, bound scientific reference | `eda_plan` |
| `EI-findings` | Above plus plan, calculation bundle and figure bundle | `eda_findings` |
| `ER-review` | Above plus findings | `eda_review` |

The host loads the common EDA prompt plus only the selected operation. EDA rules
are selected by their existing explicit `calls` lists, without rewriting their
text. Canonical G001–G008 are attached once. Project-specific rules remain in
`task_context`; the upstream adapter is responsible for their applicability.
The existing bound scientific reference is included in full for now; there is no
new RAG query or automatic reference-pruning experiment.

`inputs` must contain exactly the input objects listed for the chosen operation,
except `scientific_reference`, which this adapter loads from its verified local
snapshot. `human_confirmation` is host-only and cannot be a model input.
EP requires `task_context.implemented_r_operations`; an empty registry means no
executable R operations, not permission to invent them. EC calculation, EV
plotting and final handoff assembly have no model route.

The caller must supply the stage's response JSON schema. Preparation verifies
its root artifact fields against the existing contract; this is not a complete
scientific response validator. A future runtime must still validate responses,
resolve review issues and enforce exact-version human confirmation.

The caller admits Data and materializes permitted result/plot evidence before
preparation. The builder does not follow paths or infer release from a `READY`
label. Bind source files with `input_bindings={name: context_builder.file_ref(path)}`
when preparing programmatically. The CLI binds its input/schema files itself.
Rules, prompts, the reference snapshot and supplied file bindings are rechecked
before and after transport. Full host requests and mechanical bindings stay in
the audit; model input retains the scoped evidence and semantic identifiers.

The current transport supplies JSON/text only. Rendered images are **not** sent.
Image references are locators, not inspected pixels; EI/ER must disclose missing
images and result/plot rows. This integration does not implement visual review.

All registered EDA requests use the existing provider gateway, final transport
size guard and durable no-repeat ledger. Oversize inputs stop without truncation.
Use a stable run `context_scope`; when orchestrating a linear pass, reuse
`LinearSession` so model operations cannot move backwards. There are no repair
loops, per-dataset/per-figure calls, or automatic downstream launches here.

To export a context without calling a model:

```powershell
.venv-context/Scripts/python.exe -I -X utf8 -m research_pipeline.eda_context --call EP-plan --inputs INPUTS.json --schema SCHEMA.json --out NEW_PREVIEW_DIRECTORY
```

The preview includes the host request, exact model input/prompt, projection audit,
bound sources and final size check. Character counts are not tokenizer counts.
