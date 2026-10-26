# EDA presentation category correction

The review navigation no longer presents a separate PK variability category. Figures with reported error bars retain their original analysis tags and evidence, but are displayed by subject:

- Rabbit pulmonary and thigh infection endpoints move to PD endpoints.
- Serum protein-binding experiments move to Supporting context, under Protein binding.
- The strain MIC panel moves from Exposure–response indices to Supporting context.

Both the figure-card generator and two-level portal use the same category function. Registered binding and MIC display families take precedence over cross-cutting analysis tags. The old category URL becomes a navigation-only page pointing to the new locations.

The existing local review now contains 74 PK profiles, 11 PD endpoints, 6 exposure–response panels, 5 time-kill panels and 10 supporting-context panels: 106 unique figures in five categories. All existing images and non-UI files remain byte-identical; all 118 packet bindings remain valid. The original evidence packet, analysis IDs, review findings and scientific approval state are unchanged. Three new preview thumbnails were derived from existing images; no scientific plot was regenerated.

Validation: 10 focused offline tests passed against the publication code and 10 against the active native code. Local verification checked 106 unique figure cards and 613 internal links. Browser automation could not access the local file URL; these are static/integrity checks, not a fresh visual-browser sign-off. No model, R, fitting or data-processing run occurred.

Only code, tests, source-manifest updates and aggregate verification are published. Local research images, raw data and detailed evidence remain local. The previous 23 October revision manifest remains historical; the current source manifest records this narrow presentation correction.
