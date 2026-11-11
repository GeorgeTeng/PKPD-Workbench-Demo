# EDA review verification, 11 November 2026

The previous live benchmark covered 15 grepafloxacin requests and 25 PMB requests. On grepafloxacin the reviewer flagged at least one row with an expected issue type in all six fully visible known-error groups and one partially visible group. It did not recover the full scientific explanation of every error.

| PMB, 30 planted errors | Previous live reviewer | Same saved responses plus new status checks |
|---|---:|---:|
| Planted rows flagged | 29/30 | 30/30 |
| Planted error type identified | 21/30 | 24/30 |
| Overstated statuses correctly typed | 2/6 | 5/6 |
| Untouched rows flagged | 75/128 | 75/128 |

The four endpoint checks alone flagged four of six planted status errors and zero rows on the original 158-row PMB input. The replay uses the original model answers. It does not measure a change in the false-positive rate with the new study and arm information.

A separate live test used the S07 rat elimination Q7 row with its status deliberately raised to ANSWERABLE. The reviewer identified the inconsistency and returned keywords for excreta components and in vitro assays. The writer searched the supplied study tables, restored NOT_ANSWERABLE_YET and identified the missing measurements. Independent re-review confirmed that limited conclusion. The test took three model calls and one correction round.

The A1 paper comparison uses the historical different-support EV/IV exposure ratio with a tolerance of 0.10 against the published F for each of five species. It also checks two source-attributed statements. The common-window exposure ratio is a different measure. Run `python validation/eda_rereview/check_a1.py PATH/TO/absorption.json` against the local grepafloxacin result. The original in-place suite reported 341 passed, eight skipped and five expected failures.
