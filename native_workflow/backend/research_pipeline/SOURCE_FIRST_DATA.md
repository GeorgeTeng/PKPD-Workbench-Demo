# Source-first Data test

This isolated workflow consumes a verified version-4 main. It does not approve Data for preparation, fitting or release.

The order is `import -> repair -> organize -> review`. Import replays the original host checks against unchanged source pages and retains the real historical Sol provenance. Old requirement IDs, reasons and finding targets remain historical explanations, not restrictions on the later DR. Every permitted original source unit and note remains available. Protected inputs are never opened by these stages.

Run from the repository with the installed Python environment:

```powershell
.venv-context/Scripts/python.exe -I -X utf8 -m research_pipeline.data_source_first_workflow --stage import --main outputs/Codex_Agent_Run_20261009/first_part_handoff_01/published/main.json --out outputs/Codex_Agent_Run_20261009/data_test_05_source_first/run --reuse-manifest outputs/Codex_Agent_Run_20261009/data_test_05_source_first/legacy_reuse_manifest.json --repair-spec outputs/Codex_Agent_Run_20261009/fixes/source-first-data/citation_repair_spec.json
.venv-context/Scripts/python.exe -I -X utf8 -m research_pipeline.data_source_first_workflow --stage repair --out outputs/Codex_Agent_Run_20261009/data_test_05_source_first/run
```

Import makes no model calls. Repair uses `gpt-6-luna` to supply exactly one source citation; the host applies that explicit operation to the fixed original response, preserves all facts and findings, and runs all original checks. The old run and its 59 cached pages remain unchanged. A replayable proof distinguishes the original Sol extraction, the Luna citation patch and host derivation.

`manifest.json` binds source, policy, code and output hashes. Each command holds `.stage.lock`; telemetry appends call-specific events to `events.jsonl` and exposes the latest state in `telemetry.json`. Stage receipts never grant scientific approval.

After repair, `--stage organize --out <run>` calls Luna once for post-source DR. It reads the complete permitted source units and notes, checked profiles, all retained findings and project-rule semantics. Duplicate stated-value arrays are omitted from this request because their exact original notes remain supplied; the saved labels and later coverage review retain every value. Descriptor note copies are deleted only when every line remains verbatim within the same item's source units. A request above 700,000 characters stops without truncation.

DR writes standard `requirements.json` and `labels.json`, with new `SFT` task and `SFQ` requirement IDs, exact evidence, objective coverage and an explicit association for every permitted item. These associations are potential relevance, not adequacy. The later `--stage review` is independently implemented and must be validated before execution; successful organization alone cannot open preparation.

A rejected DR response can be corrected using an explicitly prepared, source-bound target contract:

```powershell
.venv-context/Scripts/python.exe -I -X utf8 -m research_pipeline.data_source_first_organize_patch --out <run> --contract <approved-target-contract.json>
```

This call returns only authorized citation replacements, project-evidence additions and objective-row corrections, plus the specified coverage wording and per-task conditional method feasibility. The host locks all other original candidate fields, checks the complete derived candidate, and saves the raw patch and replayable provenance before publishing. Method feasibility is an unreviewed proposal, not an adopted requirement or proof of applicability. Original rejected responses remain unchanged. Missing-information coverage may cite the same record's exact field, clarification, impact or why-it-matters leaf; it cannot substitute another record or an administrative status field.
