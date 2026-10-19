# T0026 — 2023 fractionation scatter: K. pneumoniae 104; fAUC_MIC_h

Neutropenic mouse thigh; K. pneumoniae 104 · SC

| Record | Index coordinate (h) | Delta log10 CFU | X status |
|---|---|---|---|
| T0026_R530 | 1.0204 | 3.263 | AT_LEFT_LOG_AXIS_UNRESOLVED |
| T0026_R531 | 1.0204 | 2.895 | AT_LEFT_LOG_AXIS_UNRESOLVED |
| T0026_R532 | 6.5432 | 2.789 | DIGITIZED |
| T0026_R533 | 8.0077 | 2.737 | DIGITIZED |
| T0026_R534 | 8.0077 | 2.421 | DIGITIZED |
| T0026_R535 | 15.5949 | 2.684 | DIGITIZED |
| T0026_R536 | 15.5949 | 2.158 | DIGITIZED |
| T0026_R537 | 18.7038 | 3 | DIGITIZED |
| T0026_R538 | 18.7038 | 2.211 | DIGITIZED |
| T0026_R539 | 37.1685 | 2 | DIGITIZED |
| T0026_R540 | 37.1685 | 0.816 | DIGITIZED |
| T0026_R541 | 37.1685 | -0.921 | DIGITIZED |
| T0026_R542 | 45.4878 | -1.316 | DIGITIZED |
| T0026_R543 | 45.4878 | -1.632 | DIGITIZED |
| T0026_R544 | 86.8153 | -1.026 | OVERLAP_OR_AXIS_REVIEW |
| T0026_R545 | 86.8153 | -1.184 | OVERLAP_OR_AXIS_REVIEW |
| T0026_R546 | 106.2468 | -0.895 | DIGITIZED |
| T0026_R547 | 106.2468 | -1.395 | DIGITIZED |
| T0026_R548 | 248.1629 | -0.289 | DIGITIZED |
| T0026_R549 | 248.1629 | -0.895 | DIGITIZED |
| T0026_R550 | 309.9046 | -1.211 | OVERLAP_OR_AXIS_REVIEW |
| T0026_R551 | 309.9046 | -1.342 | OVERLAP_OR_AXIS_REVIEW |
| T0026_R552 | 723.8509 | -0.921 | DIGITIZED |
| T0026_R553 | 723.8509 | -1.553 | DIGITIZED |

**Notes / limits**

- Neutropenic mouse thigh; SC; same-study 0-24 h exposure vs change from pretreatment to 24 h; fu=0.20 already applied.
- These are visible single-thigh markers, NOT a complete individual dataset. Overlap hides counts; no invented duplicate dots.
- Exposure coordinates come from the published PK simulation, not an independently fitted current model. No extra fu multiplication.
- Only study/strain/window matching is established. Per-marker doses, animal IDs and cross-panel point IDs are NOT_FOUND.
- DO NOT join panels by rank, nearest response or assumed dose. Different recovered point sets cannot support AIC/BIC index ranking.
- Log-axis left-edge markers are unresolved display/censor locations, not verified positive exposure or established zero-dose controls.
- OVERLAP_OR_AXIS_REVIEW flags close/axis-obscured features; multiplicity uncertain. Exclude these from numerical diagnostics.
- Approximate digitization only; pixel tolerance +/-2. No fitted curve, R2 label or model-predicted response is extracted.
- Use for isolated descriptive Emax/Hill shape diagnostics, not primary independently selected best index; dose-range conflict remains.
- The fAUC/MIC panel also lacks verified common-record membership and has unresolved left log-axis markers. Affects: CROSS_TABLE_LINKAGE, DOSE_RESPONSE_LINKAGE.

Trace: [manifest](../../manifest.json) → T0026. Reading only; no analysis release.
