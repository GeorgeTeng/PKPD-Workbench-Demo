# Opt-in PD target and PTA knowledge

`research_pipeline.method_profiles_next` loads
`backend/rules/data/pkpd_method_profiles.1.1.0-draft.1.json` explicitly. It is a
draft input-planning library. Importing it performs no analysis or model call.
The original `method_profiles.py`, original library, deferred PTA reference and
saved runs are unchanged. All original ten profiles retain their IDs and content.

The new DR integration entry is an independently frozen `next_method_context`:

```python
from research_pipeline import method_profiles_next as next_mp

next_method_context = next_mp.planning_context()
next_packet = next_mp.scoped_context(next_method_context, ['MP010', 'MP012'])
next_sources = {
    key: value for key, value in next_mp.evidence_sources(next_method_context).items()
    if key in {'method:MP010', 'method:MP012'}
}
# Persist the full next_method_context using existing artifact storage/hash APIs.
# Send next_packet and next_sources only to explicitly opted-in new DR calls.
```

Validate new requirements with
`next_mp.validate_requirements(requirements, next_method_context)`; ordinary
source-quote checking remains the caller's responsibility. The scoped packet is
prompt material, not a full context for `check_context`. Do not pass this new
library to legacy `method_profiles` APIs or silently replace a historical
`method_knowledge_ref`. Existing DR outputs need no rerun. Integrating this packet
into a future DR call is separate from this knowledge-library change.

To create a compact context for that entry without a provider call:

```powershell
.venv-context\Scripts\python.exe -m research_pipeline.method_profiles_next --profiles MP010 MP012 --out next_method_context.json
```

This saves a full, loadable context containing only the two selected profiles and
their sources, plus `full_library_sha256` for the originating menu. Its own
`library_sha256` binds the selected content. The CLI prints a file/hash manifest
and refuses to overwrite an existing path. The new DR caller uses
`next_mp.check_context(read_json(path))`, `next_mp.scoped_context(...)` and
`next_mp.evidence_sources(...)` on this saved context; it must explicitly provide
that packet to its new request. The CLI does not alter or rerun an existing DR.

MP009 remains the index entry point, including its existing conditional target
subtask. MP012 provides target-specific input knowledge: a paired panel may
support target estimation while cross-index comparison is unresolved. Stasis,
1-log and 2-log effects are project options. MP010 reuses the historical PTA topic
as a new data-only revision with family `PTA`; the old deferred analysis remains
untouched. Per-MIC PTA needs no MIC-frequency distribution; weighted attainment
needs population-specific weights and documented coverage.

Shared conventions distinguish design definitions, review of existing sources,
planned model outputs and genuinely new data. A target/model awaiting estimation
has a producer and phase, not an automatic missing-raw-data label. The same
definitions support project scope exclusions without a universal human-data ban.

Sources S07/S08 inform target definitions and context; S20 supplies a primary
example of MIC-frequency weighting. S07's working official URL and locators were
checked for this version. Bookkeeping, task boundaries and gap categories are
planning design inferences, not quoted regulatory requirements. No study-specific
drug parameters or probability cutoffs are imported.

Focused offline verification from repository root:

```powershell
.venv-context\Scripts\python.exe -m pytest backend\research_pipeline\tests\test_method_profiles_next.py backend\research_pipeline\tests\test_method_profiles.py -q
```

These tests verify knowledge/schema boundaries and version isolation, not
scientific adequacy, target qualification or simulation validity.
