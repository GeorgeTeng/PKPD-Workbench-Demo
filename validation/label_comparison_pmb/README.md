# PMB Label optimization — 20 October 2026

The lightweight Data demo now limits Label to faithful source description. Original source units, selected project Rules, column vocabulary, literal-unit checks, exact citation checks and downstream label shape are retained. Requirement matching, method selection, modeling and PTA adequacy are deferred; the upstream requirements remain available. Full-mode behavior and the workflow/Human gates are unchanged.

## Observed comparison

| Metric | Historical baseline | Optimized Label | Reduction |
| --- | ---: | ---: | ---: |
| Label wall time | 24m 22s | 17m 32s | 28.1% |
| Mean model-call duration | 1m 49s | 1m 17s | 29.1% |
| Median prompt size | 77.8 KB | 45.8 KB | 41.2% |
| Median response-file size | 17.2 KB | 11.0 KB | 35.7% |
| Calls / concurrent workers | 52 / 4 | 52 / 4 | Unchanged |

Requested model: `gpt-6.1-sol`, high reasoning. Provider-served model identity was not reported. Response reuse was disabled. Frozen original Context, Rules, requirements and source inputs were used; no other example or upstream stage was rerun. The baseline is historical, not a simultaneous controlled experiment. These are Label timings, not complete Data workflow timings.

## Result review and correction

All 52 labels, 292 column positions and 161 previously explicit column units were retained. Existing host evidence checks passed. Seven category fields and six column meanings changed; the full differences are retained for inspection. Text-value records changed from 361 to 360 with different grouping, so this is not an independent scientific-equivalence claim.

The initial run added 20 source-supported pixel units and two inappropriate `mg/L` column-wide units in the mixed-content table `F0003:S1:T27`. A narrow prompt clarification now prohibits assigning one row's unit to an entire mixed-content column. Only that table was rerun: **one fresh call, 54.382 seconds**, with D/E units returned as `NOT_FOUND` and row-specific unit evidence retained. No model response was manually edited.

The 17m 32s experiment predates this final clarification. The final prompt was verified on the affected table only; it was not rerun across all 52 items. The original experiment and follow-up are separate records, not silently merged into a new acceptance result.

## Retained records

- [Machine-readable comparison](../label_comparison_pmb.json)
- Detailed labels, all field differences and result checks are retained locally under `validation/label_comparison_pmb/pmb_source_only_02/`.
- Corrected single-table labels and call receipts are retained locally under `validation/label_comparison_pmb/pmb_mixed_column_followup_01/`.
- Local preservation and cleanup records: `validation/label_comparison_pmb/retained_evidence_manifest.json` and `cache_cleanup.json`.

Detailed source-derived labels and call/audit records are intentionally local and ignored by Git; only code, test files and summary documentation are published in this update. Raw requests, responses, assembled prompts, source bindings and audit records remain in the original local `state/label_comparison/` directories, with hashes in the local manifest. Only 53 duplicate response-reuse files (605,308 bytes) under these runs' `data_agents/kept/` directories were removed after verifying identical audit responses. All 910 retained evidence-file hashes were unchanged. Existing acceptance results and Human-gate records were not changed.

The earlier offline suite passed 59 tests in 8.448 seconds (local log: `validation/label_comparison_pmb/offline_tests_original.txt`); the two Label-specific checks passed again after the final prompt clarification. Publishing and cleanup did not rerun tests, model calls or workflows. The `pmb_source_only_01` setup failure is retained separately; it made zero model calls.

This update changes the source checkout. It does not rebuild or replace the previously published v0.1.1 portable archive.
