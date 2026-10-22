# Version selection — 22 October 2026

## Decision

Publish the current native workflow and EDA review code, retain **ContextBuilder 2.1 + RAG v2.0** as the existing runtime baseline, and archive the verified standalone **revision14** ContextBuilder components as an opt-in research reference. No evaluated successor has demonstrated sufficient evidence to replace the baseline automatically. This is a conservative release decision, not a claim that the baseline is scientifically optimal or that dynamic RAG is validated.

| Candidate | Evidence checked locally | Publication decision |
| --- | --- | --- |
| Runtime ContextBuilder 2.1 | Active deterministic assembly, versioned stage routes, input bindings, exact evidence and final-budget checks; current EDA review uses it | Publish latest native source and existing demo branch adapter; preserve caller boundaries |
| RAG v2.0 baseline | Existing `rag_candidate/` matches all 11 files of the local v2.0 snapshot | Retain baseline; optional background and source/applicability restrictions remain |
| Retrieval revision13 | Positive group coverage improved, but hybrid returned false matches on 4/4 negative controls; assessment explicitly says `DO_NOT_ADOPT_HYBRID` | Do not replace baseline |
| Reranker/admission round001 | Independent local report says investment rule not met and scientific acceptance inconclusive; no automatic adoption | Do not activate |
| ContextBuilder revision14 | Final local verification: 54/54 real-input arms checked, no prior method-unit loss, exact inline preservation; 38 tests run with one skipped; improvement in evidence use not established | Publish standalone deterministic components and synthetic tests under `research/contextbuilder_v14/`; keep inactive |
| Evidence-unit round001 | `NOT_ACCEPTED_FOR_PROMOTION`: two B-arm budget failures and a confirmed C-arm condition-use regression | Do not promote |
| Evidence-budget round002 | Latest receipt says `PAUSED_BY_USER`, 0/48 model calls returned, scientific assessment pending; local preflight/code checks are not outcome evidence | Do not resume or adopt |

The revision14 source selection is tied to `background_code_freeze006`: the final evidence-pointer closure correction passed its bounded independent code review. Historical whole-card delivery and pointer/hash integrity do not establish scientific entailment, adequacy or model compliance.

## Release boundaries

- Root demo: retain its existing technical Data profile and explicit downstream execution restrictions.
- `native_workflow/`: latest source snapshot for native Compression/Data/EDA and handoff, separate from the demo-specific implementation.
- `research/contextbuilder_v14/`: a testable reference, not a new production entry point. The experimental retriever, model weights, source corpus and original evaluation payloads are not bundled.
- Detailed research inputs, plots and responses remain local under the user's publication choice. Only code, tests, configurations and aggregate summaries are published.
- No scientific model run, knowledge repair, broad experiment or automatic optimization was started for this release.

See [the release validation summary](../validation/release_20261022/README.md) for fresh checks and their limits.
