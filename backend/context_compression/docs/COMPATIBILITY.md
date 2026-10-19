# Recovered rules and migration boundaries

Source: `outputs/context_compression_chat_complete.md` in this workspace, a saved conversation covering 68 historical turns. Historical attachments and executable code were not copied into that transcript. The old Mac paths are references, not local files on this Windows computer.

## Recovered decisions

| Historical turn / line | Decision retained |
|---|---|
| Turn 17, lines 1404–1443 | Compact handoff; no question–fact links or evidence quotations in downstream context; missing information is explicit |
| Turn 32–34, lines 2230–2453 | Add rules; preserve known values, negation, scope and provenance; evidence/review remain sidecars |
| Turn 34, lines 2368–2419 | Context keys objective, study, data.available, data.required, rules, checks, uncertainties; schema version 3.0; default 220 words / 2,400 characters |
| Turn 41, lines 2829–2868 | Pipeline contains blocks, connections and data_files; file requirements recorded once |
| Turn 47, lines 3166–3288 | Backward planning, input–output contracts, conditional branches and missing-input visibility |
| Turn 48–50, lines 3296–3445 | Separate context and pipeline generation; lock context; use Pass/Fail human review, Fail needs reason |

## What was reconstructed

- Current 3.11.0 export: one `handoff/main.json` containing the 3.0 scientific fields directly, rules numbered R001…, and an explicit `data.files` attachment extension. Internal evidence, registry hashes and execution logs are not downstream inputs. Consumers using the strict old context schema must use `main.schema.json` for this extension. See `SINGLE_JSON_HANDOFF.md`.

- The Windows reconstruction started at 3.8.0; version 3.9.0 adds a reviewed requirements inventory and complete bidirectional coverage. The compact context remains 3.0. New generation requires a new run with workflow `source-coverage-v1`; existing outputs are not silently upgraded.
- Compact context keeps the explicitly documented top-level schema and version 3.0. The nested study fields are newly formalized as drug, regimen, population, system, measurements and methods; historical source files were unavailable to verify exact subfield compatibility.
- The final wrapper uses `context`, `pipeline`, `review`, as described in the later two-stage design. An earlier version called the final gate `gate`; we follow the later design.
- Every scalar context field is covered by a source/absence/proposal audit record. This is an explicit check, not proof of semantic support.
- Model-based reviews are separated from generation and bound to their requests. No statistical performance score is inferred from a reviewer saying PASS.
- F/R/A and the uncalibrated historical 0.50/0.35/0.15 weights are recorded; without an independently defined reference and judgments, scores remain null. The old full semantic scoring engine has not been recovered or claimed as reproduced.
- B1 reads explicitly submitted attachments/ZIP contents, registers original names and hashes, and preserves source content; it does not follow undeclared paths from a document. Reading a file does not establish QC or analysis readiness. B2 owns table splitting, cleaning and release.
- The historical 220-word/2,400-character limits shown above are no longer defaults. Both output limits are null unless explicitly supplied.
- The current project excludes PBPK. Historical PBPK and phage examples in the transcript are not templates for the current example.

## Reuse of old outputs

This software rejects unknown fields rather than silently dropping them. An actual old JSON file can be imported only after explicitly mapping and checking its nested fields. Keeping the top-level layout is not a promise of byte-for-byte or binary compatibility.

## Operational boundary

The program produces a scientific plan, not a fitted PK/PD model. Planned analysis files are contracts, not artifacts already created. Human review remains pending until a real reviewer records a decision. No remote messages, deployments or clinical recommendations are performed.
