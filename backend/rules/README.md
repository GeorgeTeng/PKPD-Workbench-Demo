# Rules

Every rule file the backend agents load lives in this folder, grouped by workflow layer. The host sends these files to each agent as inline instructions. Editing one changes the rules for **new runs only**: every run freezes a copy of the rules it started with, and a changed rule never inherits an earlier approval.

Paths below are relative to `backend/`.

## What is where

| Folder | Rules | File | Version · status | Loaded by |
|---|---|---|---|---|
| `general/` | G001–G008, shared by every step and applied first | `workflow_governance.json` | 1.5.2 · active, user approved | `context_compression/ctxcomp/governance.py` |
| `intake/` | IN001–IN008, file intake before compression | `intake_rules.json` | 3.2.1 · active | `ctxcomp/rules.py` (`intake_agent_contract`) |
| `compression/` | 15 active CC rules (CC001–CC009, CC011, CC012, CC015–CC017, CC019) | `compression_rules.json` | 1.31.0 · active | `ctxcomp/rules.py` |
| | CC005 details: 13 preservation categories | `cc005_details.json` | 2.0.0 | `ctxcomp/rules.py`, `project_rule_agent.py` |
| | Contracts for the 11 internal compression agents | `compression_agents.json` | 1.13.0 | `ctxcomp/rules.py` |
| | Proposition and source-binding contract | `scientific_extraction.json` | 1.4.0 | `ctxcomp/rules.py`, `ctxcomp/bindings.py` |
| | PK terminology appendix for CC005 | `pk_binding_knowledge.json` | 2.0.0 | `ctxcomp/rules.py`, `project_rule_agent.py` |
| `project_rules/` | PRC001–PRC007, Project Rules Agent policy for new inputs | `extraction_policy.1.2.1.json` | 1.2.1 · active | `research_pipeline/project_rule_agent.py` |
| | Frozen policy for inputs prepared under 1.2.0 | `extraction_policy.1.2.json` | 1.2.0 · historical inputs only | `project_rule_agent.py` |
| | 1.2.0 → 1.2.1 numbering map | `numbering_migration.1.2.1.json` | not read; hashed as a plan input | `workflow_runtime.py` |
| `data/` | Agent DR · define data requirements: DR001–DR002 (DR alongside the inventory, DR-access joins them) | `dr_requirements.json` | 1.1.0 · split confirmed 2026-10-08, rule-by-rule review pending | `research_pipeline/data_agents.py` |
| | Agent DC · label data & check coverage: DC001–DC008, numbered in run order | `dc_coverage.json` | 2.5.0 · rule-by-rule reviewed 2026-10-09 | `research_pipeline/data_agents.py` |
| | Agent DP · prepare & QC: DP001 | `dp_preparation.json` | 1.0.0 · same | `research_pipeline/data_agents.py` |
| | Agent DH · validate metadata & hand off: DH001–DH004 | `dh_handoff.json` | 1.1.0 · same | `research_pipeline/data_agents.py` |
| | MP001–MP009, MP011 data requirements of PK/PD methods | `pkpd_method_profiles.json` | 1.0.0-draft.15 · scientific review pending | `research_pipeline/method_profiles.py` |
| | Data decisions the user confirmed, waiting to be published as project rules | `data_project_decisions.20261007.json` | 1.1.0 · not sent to agents | rule catalog only |
| `data/deferred/` | Earlier analysis guidance kept for later stages (PK, translation, human simulation, binding, IVIVE, PK/PD index, PTA) | `*_followup.json` (7 files) | 1.0.0 · not loaded into DR/DC | not loaded |
| `data/history/` | DA001–DA009 and agents D01–D05, replaced by the four agent files above | `data_agents.2.9.1.json` | 2.9.1 · historical runs only | not loaded |
| `eda/` | EDA001-EDA009; EP Planner, EC Calculator (R), EV Visualizer (R), EI Interpreter, ER Reviewer & Handoff | `eda_rules.json` | 2.0.0-draft.1; framework built, runtime pending | `eda_framework.py` checks only; runtime disabled |
| `drafts/` | Inactive drafts (`enabled: false`), never sent to agents | `general_pkpd_rules.json` (GEN-PKPD-001…012), `pk_modeling_rules_20260924.json` (PKMR-01…29) | 1.0 · pending user review | read-only draft view |

## Data agents (2026-10-08)

The Data part runs as four independent agents. The DC inventory and DR run side by side; DR-access joins them by giving every inventory item an access disposition; DC then labels and reviews; after human review DP → DH. Every model call carries G001–G008 from `general/` followed by the rules of its own agent file only. The DA001–DA009 text was redistributed sentence by sentence; three sentences already covered by G005 and G007 were dropped. Each rule's `derived_from` field names its DA source.

Method profiles (MP) are selected by DR from the objective only. Each profile also lists `data_roles` and one `condition_triggers` entry per conditional input and data check. After DC-label, host code maps each dataset's categorical labels onto the conditions of the profiles already selected for it and writes `adequacy/condition_checklist.json`; DC-review decides every row that applies or that labels cannot settle (DC006). Unmet conditions are follow-up gaps. Data never select a profile: a dataset no requirement uses is routed to human review.

Unresolved items follow G008 through a ledger. Open items from compression (`main.json` missing_information) and Data findings that a later phase depends on are recorded in `adequacy/unresolved_ledger.json`. DC-review records an outcome for items due before QC (DC007); DH-handoff does the same for items due before EDA and writes `data_preparation/unresolved_ledger.json`. Every eda, pk and index handoff carries all still-open items unchanged, plus the limitations accepted for its outputs (DH004).

DC splits worksheets alongside DR (DC001): a person's explicit range plan (`table_range_plan` in the workflow spec, bound to file hashes) wins, then Excel tables and source anchors; any other sheet goes to one DC-split call whose proposed tables, headers and note blocks host code verifies, and a sheet that fails stays unassigned for review. DC-label gives each item a primary role plus additional roles and, per column, the stated meaning and unit; pages that disagree leave the value MIXED or NOT_FOUND with a LABEL_CONFLICT finding (DC004). An oversized DC-review is split by task and merged with the strictest shared decision (DC008). Each DC call receives only the rules that name it, and `dc_coverage.json` holds the definitions of every label value (`label_vocabulary`). Labels copy each column's unit and qualifiers verbatim (checked by host code), and DC-label and DC-review read the CC005 terminology groups named in `dc_coverage.json` directly from `compression/pk_binding_knowledge.json`. DC rules are numbered in run order since 2.0.0; each rule keeps its `previous_id`. Data values written in text rather than a table body are listed by DC-label as stated values, copied verbatim; host code compares them with each other and with labelled tables, records matches as duplicates and differences as conflicts for human review before EDA, and preparation writes them to `stated_values.json` without merging them into any table (DC003).

## Rules that are not in this folder

- **Project rules R001…** are extracted per project by the Project Rules Agent and published into that run's `project_rules.json`. They are outputs, not configuration.
- **Rules still written in code:** `research_pipeline/data_rules.py` (older study-design checks, ruleset 2026-09-16.1, used by `data_preparation.py`), `research_pipeline/task_rules.py` (routes published project rules to steps) and `LEGACY_PROCESSING_RULES` in `project_rule_agent.py` (only for historical 1.0/1.1 inputs).
- **Generated views, do not edit:** `research_pipeline/docs/interfaces/` holds `workflow_governance.json`, `general_rules.review.json`, `file_intake.runtime.json`, `rule_layers.review.json`, `context_compression.runtime.json` and `context_compression.review.json`; `context_compression/docs/` holds `COMPRESSION_RULES_REVIEW.md` and `CC005_REVIEW.md`. They are rendered from the files here. After changing a general, intake or compression rule, run `python research_pipeline/scripts/export_compression_rules_review.py` (add `--check` to only detect stale copies).
- **Review records and superseded versions** stay in `research_pipeline/docs/review_drafts/` and its `history/` folder. The Project Rules Agent review record (`project_rules_agent_rules.review.json`, 2.0.0-draft.10) carries the same PRC001–PRC007 text as `project_rules/extraction_policy.1.2.1.json`; the policy file is the one agents load.

## Moved here on 2026-10-08

File contents did not change (same SHA-256), so rule versions, request hashes and existing runs are unaffected. Older documents and review records may still cite the old paths.

| Old path | New path |
|---|---|
| `context_compression/ctxcomp/resources/workflow_governance.json` | `rules/general/workflow_governance.json` |
| `context_compression/ctxcomp/resources/intake_rules.json` | `rules/intake/intake_rules.json` |
| `context_compression/ctxcomp/resources/compression_rules.json` | `rules/compression/compression_rules.json` |
| `context_compression/ctxcomp/resources/cc005_details.json` | `rules/compression/cc005_details.json` |
| `context_compression/ctxcomp/resources/compression_agents.json` | `rules/compression/compression_agents.json` |
| `context_compression/ctxcomp/resources/scientific_extraction.json` | `rules/compression/scientific_extraction.json` |
| `context_compression/ctxcomp/resources/pk_binding_knowledge.json` | `rules/compression/pk_binding_knowledge.json` |
| `research_pipeline/research_pipeline/resources/project_rules/extraction_policy.1.2.1.json` | `rules/project_rules/extraction_policy.1.2.1.json` |
| `research_pipeline/research_pipeline/resources/project_rules/extraction_policy.1.2.json` | `rules/project_rules/extraction_policy.1.2.json` |
| `research_pipeline/research_pipeline/resources/project_rules/numbering_migration.1.2.1.json` | `rules/project_rules/numbering_migration.1.2.1.json` |
| `research_pipeline/research_pipeline/resources/data_agents.json` | `rules/data/data_agents.json` (since 2026-10-08 `rules/data/history/data_agents.2.9.1.json`) |
| `research_pipeline/research_pipeline/resources/pkpd_method_profiles.json` | `rules/data/pkpd_method_profiles.json` |
| `research_pipeline/docs/review_drafts/data_project_decisions.20261007.json` | `rules/data/data_project_decisions.20261007.json` |
| `research_pipeline/research_pipeline/resources/*_followup.json` (7 files) | `rules/data/deferred/` (same names) |
| `research_pipeline/docs/review_drafts/general_pkpd_rules.json` | `rules/drafts/general_pkpd_rules.json` |
| `research_pipeline/docs/review_drafts/pk_modeling_rules_20260924.json` | `rules/drafts/pk_modeling_rules_20260924.json` |

`context_compression/ctxcomp/resources/` now holds only the compression prompt (`instructions.md`) and the planning method references (`literature.json`); `research_pipeline/research_pipeline/resources/` holds only the PK reference library (`pk_references/`).

## EDA framework (2026-10-13)

The five components are EP (EDA Planner), EC (EDA Calculator, R), EV (EDA Visualizer, R), EI (EDA Interpreter), and ER (EDA Reviewer & Handoff). Three model operations cover planning, findings and independent review; the host assembles the handoff. See [the framework guide](../research_pipeline/docs/EDA_FRAMEWORK.md) for contracts and entry points.

`eda/eda_rules.json` is the scaffold's single component/rule registry. `eda/eda_scientific_reference.txt` preserves the English review's drawing specifications, MP background and sources byte-for-byte. The new descriptive boundary excludes new AUC integration. It permits established descriptive formulas with complete supported inputs.

R interfaces and a read-only Python checker exist. Descriptive handlers, plot templates, response-schema enforcement and runtime/UI integration are pending; EDA start/retry/resume and related supplemental execution remain disabled. Earlier 0.3.0 runtime artifacts remain in `_claude_transfer/retired-eda-20261009/`; the superseded 1.0.0 draft and prompt assets are preserved in `outputs/EDA_Framework_20261013_213146/before/`.
