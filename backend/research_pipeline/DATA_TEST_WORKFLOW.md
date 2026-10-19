# Main to Data test

This isolated entry runs the existing Data inventory, DR definition/access, DC labeling and adequacy functions with either verified published Project Rules or an explicitly unapproved no-rules test. It never edits the original main, fabricates Canvas approval, prepares measurements, fits models or releases production artifacts.

Run in a dedicated process with the project environment:

```powershell
.\.venv-context\Scripts\python.exe -I -X utf8 -m research_pipeline.data_test_workflow --main <absolute-published-main.json> --out <new-test-directory> --stage inventory --model gpt-6-sol --rules-mode published
```

Run stages `inventory`, `define`, `access`, `label`, `assess` in that order, using the same main and output directory. Inventory and definition are independent. Completed stages are hash-checked and reused; failed stages retain requests, responses and timing for an explicit retry. Existing per-call checks and cache behavior remain in force.

`--rules-mode published` requires a real `project_rules_ref`, verifies its publication and exact effective-main binding, and keeps the original Data `rules_for` implementation. Stage projections preserve full rule text, conditions and provenance. Requests carry `PROJECT_RULES_PROVIDED`, the exact main and rule-pack references, and `UNAPPROVED_TEST_ONLY`. DR/access output rule IDs are constrained to the IDs actually supplied in their projected rules. Processing/governance IDs are a separate namespace.

The default `auto` mode uses published rules whenever main references them; a missing or invalid referenced pack fails rather than falling back to an empty list. For historical no-rules tests, `none` rejects any existing rule reference. Only that mode's private module replaces `rules_for` with an empty list and marks `Rules_NOT_PROVIDED_FOR_TEST`; this does not mean an approved empty rule pack. The production module is never monkeypatched. Both modes retain all DR/DC/shared processing rules, source checks, holdout restrictions, schemas and evidence validation.

For a version `4.0` first-part main, supply that one main path. The adapter calls `first_part_handoff.verify_final_main`, which verifies the fixed sibling receipt, complete source lineage and source-bound unified review PASS. Rule bodies come from `main.rules`; the old `project_rules_ref` is provenance, not a claim that the old publication approved the new main bytes. The private adapter uses the same explicit stage selection and full-record projection as the existing Rules projector. Test requests and receipts bind the final-main receipt and review. A missing, changed or non-PASS first-part proof fails before Data calls. This remains an unapproved Data test, not Canvas approval.

Use a new directory when changing main or connecting Rules. Old outputs, cache keys and page-correction manifests remain bound to their original main. A correction from a different main fails binding checks; it is not silently reused as new evidence. The published-rules mode includes general existing DC004 header-position guidance without carrying an old page-specific correction.

The final test export retains technical adequacy as `technical_can_enter_qc` but sets `can_enter_qc=false`, keeps human review required and updates all affected output references. Original technical files are retained under `audit/unapproved_technical_assessment` solely as audit evidence, with no production approval. `prepared_input` rejects the test QC export. The test receipt and reports do not establish scientific adequacy or production readiness.

For published-rule test requests only, context_sources omits a rule string when it is exactly the JSON serialization of the full rule already present in project_rules. All full rule fields remain there once; rule IDs still name evidence sources. Nonidentical strings and sources outside that request's projection remain unchanged. The original host source map and verbatim evidence validator are unchanged. No alias or extra mapping object is sent.

For embedded rules, matching `main:/rules/index/...` leaves are also omitted only when that same complete rule is in the request's projection and the leaf equals its original value. Nonmatching leaves, nonprojected rules and scientific context remain. The existing 700000-character budget and DC008 task-level split/stop behavior are unchanged; a still-oversized task stops for an explicit engineering decision rather than dropping evidence.

An explicit `definition_correction.json` may authorize one source-bound corrective DR call after a rejected definition. It binds main and the saved request/response hashes, schema, governance, full rule projection, method snapshot and source context. The old candidate and feedback are NON-EVIDENCE. Only listed requirement IDs may change or be omitted with a finding; other task/requirement records and prior findings must remain, and authority cannot be promoted. The response uses its new request hash and still passes all original schema, literal evidence and method-applicability checks. This manifest never auto-fixes source spans or approves a rejected response.
