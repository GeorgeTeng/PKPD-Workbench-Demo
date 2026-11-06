# PMB absorption EDA r4.3

**PMB retry 032 reached `STOPPED_AFTER_EV` on 5 November 2026.** The native run took 7 min 51 s. The Data repair pass admitted 58 tables and the main EV bundle passed its technical check with 8 figures. The absorption section covers 17 extravascular concentration datasets in four studies of mice and rabbits. R/ggplot2 generated 89 absorption PNGs. A separate run through the published standalone entry reproduced all 89 PNGs, 3 HTML pages and 2 JSON files byte for byte.

The [standalone EDA entry](../../eda/README.md) opens an extracted report or runs absorption from an existing EDA directory. The [r4.3 specification](../../native_workflow/backend/rules/eda/EDA_absorption_rules_r4.3_rules_only_20261105.md) covers items 16–23. The [machine-readable verification record](checks.json) gives the final checkpoint, source hashes and replay counts.

## What changed in the calculations

| Question | Rule applied in r4.3 | Consequence for the PMB report |
| --- | --- | --- |
| Q1–Q4, onset, rise, model exclusions and second rise | Test definitely ordered times, preserve censoring and time uncertainty, retain witnesses, then repeat the full search after each removal. Distinguish a conditional numerical contradiction from formal exclusion. | The group-mean shapes and their error scenarios remain visible with their evidence limits. |
| Q5, individual animals | A longitudinal analysis requires supporting animal identity across sampling times. | The S21 labels permit within-time comparisons. Per-animal AUC and terminal fits are withheld. |
| Q6, terminal decline | Compare qualified EV and IV terminal windows separately from the T4 ratio test. Record the time basis and the omission checks for each result. | S05 EV windows end at 12 h and the IV window at 6 h. The S05 T4 numerical declines depend on sample times and uncertainty. IV input mode and common disposition remain unresolved. |
| Q7, systemic availability | Integrate the supported common window, report a shorter-window comparison when available, and check concentration units, analyte, dose basis, exposure coverage and shared clearance. | S05 supplies descriptive window ratios. The partial exposures and available disposition evidence leave absolute F unresolved. |
| Q8, dose proportionality | Preserve each dose’s interior sampling grid, compare with the exact shared grid, and match a CI to the actual integration rule and sampling design. | S02’s observed-window point estimate changes with the interior grid. Formal T3 and T3p are withheld on these digitized means. |
| Q9, condition comparison | Record exact-time pairs separately from the nearest-time sensitivity calculation. Preserve both sample times, ratio direction and uncertainty basis. | S22 has zero exact-time pairs and six near pairs in the IT-labelled / SC plasma comparison. The sensitivity result does not support formal T5 exclusion. |

## Execution and verification

The local native project reused the accepted Context and FirstPart and rechecked the Data handoff before running EDA through EV. Fresh EP and EP-finalize calls requested Codex `gpt-6.1-terra` with high effort. The workflow stops before EI, ER and human review. The standalone replay starts from the final run’s admitted tables and dose assessment. Its inputs are checked against the EV manifest, and its output hashes are compared with the completed native run.

The first r4.3 integration run, retry 031, reached EV and rendered 89 absorption PNGs. Cross-review then identified an input-unit comparison issue and an inaccurate T2 omission message. The final run uses the corrected source. The native runtime source hashes are recorded in the [source manifest](../../native_workflow/native_source_manifest.json). The earlier [retry 030 archive](../pmb_absorption_retry030/README.md) records r4.2.

The final native installation passed 45 targeted tests, including the migrated private regression suite and dose-overlay cases. The publication checkout passed 34 absorption and review-portal tests with synthetic inputs. The two suites overlap. Separate entry-point checks exercised manifest omissions and tampering, mismatched handoff membership, valid local intake, rule-hash verification and resolution of the offline report path.

To repeat the verification locally, supply the native run folder and a separately generated replay folder.

The additional English mechanism edition (`r4.3-handoff.1`) was generated from the admitted retry 032 tables through `python eda run`. It contains 36 study-level question answers and 184 candidate assessments (46 per study). The two original numerical JSON files, two species pages and all 89 absorption figures matched the frozen run byte for byte. The overview gained one local link to the handoff. The verifier checks that link, the catalogue and source-result hashes, complete per-study coverage, the question anchors and the scope of formal exclusions. It also accepts the original replay. The English ZIP and study evidence are distributed privately.

The edition passed 41 synthetic absorption and review-portal tests. These cover missing Weibull variants, per-profile T1/T2 scope, ambiguous routes, conditional fixed-lag bounds and the distinction between matched and unequal terminal windows.

```powershell
python validation/pmb_absorption_r43/verify_run.py "D:/runs/PMB_run5w_retry_032" "D:/reports/PMB_rebuilt"
```

The verifier checks the native checkpoint, Data membership, rule hash, output manifest, all absorption PNGs, local HTML links, the scope of the PMB comparisons and replay equality. Run artifacts, plots, model payloads and private source-derived test fixtures stay on the research workstation.

All 89 absorption PNGs decoded successfully and were reachable through 536 local references in the three absorption pages. The portable package was extracted into a fresh directory and all 553 local links across the complete offline report were checked. Independent checks against the admitted observations agreed on the S02 native-grid and shared-grid AUC ratios, both S05 exposure windows and T4 margins, and the six-pair rabbit timing sensitivity result. The reader-language check flagged technical labels in three HTML pages and 27 figure specifications. R reported 14 warnings and emitted messages about line groups with a single observation. Scientific and human review remain pending.
