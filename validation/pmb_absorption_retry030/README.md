# PMB absorption EDA · retry 030

On 4 November 2026 (America/Chicago), the native PMB workflow reached its requested EV checkpoint and produced the r4.2 absorption report. R/ggplot2 rendered **112 absorption figures** for **17 extravascular concentration datasets**. Three HTML pages cover mouse and rabbit data from four studies (S02, S05, S21, S22), each with nine questions. The main EV bundle contains 10 figures, counted separately.

| Stage | What ran |
| --- | --- |
| Inputs | The native launcher reverified the accepted Context and reused the published FirstPart handoff, which binds the Rules. Both recorded input-tree hashes remained unchanged. These upstream stages were not newly authored or independently reviewed in this run. |
| Data | The first pass admitted 53 datasets; the label-repair pass admitted 58. The final Data report, handoff and EDA source set agreed on all 58. The Data reuse ledgers recorded 43 reuse events, including 26 from retry 029 and 17 within retry 030. |
| EDA | Fresh EP and EP-finalize model calls (Codex, requested `gpt-6.1-terra`, high effort; served identity unknown), followed by EV and local absorption calculation/rendering. The main EV source-coordinate check passed. The mouse SC dose-normalized overlay reached `VERIFIED/RENDERED_AND_VERIFIED`. |
| Stop | `STOPPED_AFTER_EV` after 7 min 44 s. EI and ER were not run. Fit readiness, scientific release and human approval all remained false. |

**Output checks.** The [aggregate record](checks.json) includes input and result hashes. The [local verifier](verify_run.py) matched 121 artifacts to their manifest entries, decoded all 112 absorption PNGs and checked 532 local links/anchors across the absorption pages. All figures were reachable. These checks do not establish that every plotted observation or interpretation has been independently reviewed.

**Published code.** The analysis module is byte-identical to the one used for retry 030. The existing Demo native snapshot receives the absorption hooks at EV and in the review portal. The R script uses the configured library rather than a workstation-specific default. Exact run and published source hashes are in the [native manifest](../../native_workflow/native_source_manifest.json). Other November workflow changes are outside this backport.

The two targeted native test files passed **21 tests**. The published synthetic absorption test and existing review portal tests passed **11 tests**. Using the published module and renderer in a separate working directory on the frozen retry 030 inputs reproduced **112/112 PNGs, 3/3 absorption HTML pages and 2/2 result/spec JSONs** with identical SHA-256 hashes. This replay exercised the absorption stage only; the full native pipeline ran in the local PMB project.

**Review notes.** The native R process reported 14 warnings and emitted messages for line groups with one observation; it exited successfully and produced all specified images. The project reader-language checker flagged internal labels or identifiers on all three pages and in 36 figure specifications. This is an open presentation issue. The report describes available evidence and missing information; do not infer an absorption rate constant or absolute bioavailability from these outputs alone.

Run `python verify_run.py <local-PMB_run5w_retry_030-directory>` with Pillow installed to check the original artifacts. The run and bound Data files must remain at their original locations. This repository contains source, a synthetic test, and aggregate verification evidence; it does not distribute original observations, study graphics, model payloads or report HTML.
