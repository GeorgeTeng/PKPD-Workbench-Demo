# Conditional additions for the current PK/PD workflow

The existing 77-source library already includes GEN001–GEN003 and EDA001. This isolated packet adds three **full-text** sources only for a relevant branch; it changes no card or project policy. Original files retain their prior SHA-256 hashes. `chunks.jsonl` contains 40 hash-bound, source-located excerpts, and `verified_equations.jsonl` contains two simple expressions checked against original MathML. Other formulas are omitted from flattened text and require the original source.

| Source | Use in the existing flow | Trigger and boundary |
| --- | --- | --- |
| EXTA001, Yau et al. 2017, DOI 10.1002/bdd.2068 | Translation of **oral** exposure: distinguish Fa, Fg, Fh and apparent CL/F; expose deconvolution assumptions and rat-to-human Fg uncertainty. | Use only if an oral scenario is requested. The paper's human drug data and performance rankings are not target-drug validation or default parameters. |
| EXTA003, Kerbusch et al. 2004, DOI 10.1046/j.1365-2125.2003.01988.x | PK/PD method example for parent plus active-metabolite exposure, delay-model alternatives and potency/formation confounding. | Use only if an active metabolite and matched PK/PD evidence are relevant. Darifenacin potency and clinical effect are source-case metadata. |
| EXTB003, EMA Rev. 1 (2017), pp. 10–11 | **Optional reference** when explaining why a prospective human exposure scenario does not establish clinical starting-dose suitability. | Does not add a first-in-human calculation, NOAEL/HED/MRSD requirement, or target-drug safety evidence. |

EXTB004 (FDA MRSD) remains an intact candidate because it would introduce a separate clinical starting-dose algorithm. EXTB001–002 (TMDD) remain candidates for a triggered target-mediated disposition branch. EXTA002 was not selected because the retained page was verified only to abstract level. The already registered GEN/EDA originals were not duplicated.

The packet is ready for **bounded, conditional Qwen source review**. Selection is not scientific approval of a method or a decision to broaden the core workflow.
