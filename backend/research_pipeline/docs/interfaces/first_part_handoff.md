# First-part main v4

`research_pipeline.first_part_handoff` integrates a verified historical PRC publication without rewriting it. The new main differs only in `version: "4.0"` and `rules`, which contains the complete structured published rules. Conditions, exceptions, scope, slots and evidence remain intact. The historical v3 compression validator is unchanged.

`prepare(pack_ref, new_directory)` writes the candidate main and a frozen unified review request. The request contains one main, one set of authorized source units, original source permissions and processing instructions. It does not load attachment bodies or include previous review verdicts. An independent `gpt-6-luna` call for new runs (historical Sol reviews remain valid) checks duplication, faithfulness and completeness, with exhaustive source-unit coverage, valid JSON pointers and exact quotations. Necessary evidence repetitions and distinct scientific versus operational uses are explicitly permitted. No missing information is converted into data or approval.

`review(directory, model='gpt-6-luna', timeout=1500)` preserves the raw response before host validation. A non-PASS blocks publication. `publish(directory, new_output)` copies the reviewed main bytes unchanged and writes `receipt.json` beside it. No circular self-hash is placed in main.

Data supplies only `main.json` to `verify_final_main(mainpath)`. The verifier reads fixed sibling `receipt.json`, verifies the old Rules pack and compression lineage, exact integration, all saved review bindings and source spans, and returns `{status: 'VALID', main, rules, main_ref, receipt_ref, review_ref, project_rules_ref, scientific_approval: false}`. Data must use embedded `rules` with existing scope routing, and must not claim that the old pack's main reference binds this new main. Necessary provenance and review files remain required for verification, but the scientific body and full rule content are contained in main alone.

This content-review receipt is neither user approval nor Data adequacy or permission to fit.

## Reusable standalone command

From the repository root in PowerShell:

```powershell
$env:PYTHONPATH='backend/context_compression;backend/research_pipeline'
$env:CTXCOMP_MODEL_PROVIDER='codex'
& ./.venv-context/Scripts/python.exe -X utf8 -m research_pipeline.first_part_cli run --rules-pack '<existing published/project_rules.json>' --out '<new first-part workflow directory>' --budget-seconds 1500
```

This explicit command starts only `prepare → first_part_review → publish`. It never continues a Canvas context node, re-extracts Rules, submits approval, starts Data or changes an existing runtime plan. New CLI runs use `gpt-6-luna`, as requested on 2026-10-10. Historical `gpt-6-sol` review receipts retain their actual model and remain verifiable; changing the default does not rerun or relabel them. A run writes `workflow_status.json`; only a validated PASS supplies `handoff_main_ref` and creates `published/main.json` with its receipt. Exit 0 means reviewed publication, exit 3 means REVISE/UNRESOLVED, and exit 2 means engineering error/interruption. Evidence is preserved and no automatic retry occurs. A candidate without a receipt is not a valid Data handoff. Do not rerun an unchanged semantic failure merely to obtain PASS.

The same module provides explicit stopped stages:

```text
prepare --rules-pack <published/project_rules.json> --out <new candidate directory>
review --prepared <candidate directory> --budget-seconds 1500
publish --prepared <already reviewed candidate directory> --out <new publication directory>
verify --main <published/main.json>
```

`prepare`, `publish` and `verify` do not call a model. `review` makes exactly one call and cannot silently overwrite an existing response. A saved PASS can therefore be published after an interruption without duplicating the review. The independent CLI is deliberately separate from historical `context`, `compress` and `project_rules` runtime targets; those targets and existing jobs keep their old semantics. This CLI does not imply that any running UI service has loaded new code.
