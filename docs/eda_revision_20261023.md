# EDA revision of 23 October 2026

Published on 25 October as an EDA-only update over commit `2b50eeb0db2f8c8930a236699c9d5a76427e290c`. The 23 source/test/configuration files are copied byte-for-byte from the final 23 October change manifest. This publication does not incorporate subsequent Context or Data changes from the working directory.

## Changes

- Preserve dosing-interval versus sampling-time axes, units, source time basis and explicitly supported time origins.
- Keep strict recipe matching and report missing or ambiguous dependencies. Carry Data roles through projections; context or unresolved roles cannot become observations.
- Add `eda_dh_adapter` to prepare inputs for the existing v6 pipeline from qualified DH and canonical Data reports. Preparation performs no model or R calls, cleaning, inferred joins or fitting.
- Derive review state and next steps from the exact packet and review evidence. Historical REVISE remains blocked before human approval; existing approval gates are unchanged.
- Bind Rules draft.9 to the new dated reference and catalog while retaining historical references and Rules.
- Respect provider-specific model configuration and `PKPD_R_LIB`; summarize existing stage, call, timing and budget records without inventing served-model evidence.

See the [interface documentation](../native_workflow/backend/research_pipeline/docs/interfaces/eda_first_batch_20261023.md), [file hashes](../validation/eda_release_20261023/change_manifest.json) and [publication checks](../validation/eda_release_20261023/checks.json).

## Verification boundary

The 23 October local regression recorded 162 passed and one real-R test deselected. Fresh publication verification runs against the isolated export, with networking and external child processes blocked during tests; only model/R transport stubs execute. Fresh counts and fixture requirements are recorded in the linked checks, separately from the historical result.

The full historical regression requires local fixtures that are intentionally not exported: `tests/fixtures/eda_quality_cases.json` and historical `outputs/` inputs. A checkout without these resources cannot reproduce the full suite. They are kept outside the staged publication, and no binding is rewritten to disguise this limitation.

## Remaining gaps

1. A complete current canonical Context → independently published Rules → Data DP/DH → native v6 replay remains unproven. The latest isolated Data fixture lacks published Rules authority and is correctly rejected with `EDA DH: published project Rules required`.
2. The conservative candidate catalog does not reproduce every historical manual recipe or guarantee the previous 106-figure display coverage. Ambiguous roles, units and axes remain explicit gaps or source tables.
3. The root demo still stops at Data; the revised native EDA is not integrated into that executable. This update does not rebuild the portable Windows release.
4. There is no fresh real model/R/rendering run, independent ER review, human approval, fit readiness or scientific release. The existing 106-figure package remains historical and unregenerated.

Only code, tests, configuration, hashes and aggregate summaries are published. Raw research data, original figures, detailed handoffs, model payloads and local fixture contents are excluded. The old source snapshot remains accessible in Git history; the local frozen review package is unchanged.
