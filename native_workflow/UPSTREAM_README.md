# PMB Translational PK/PD

Research workbench for source-bound context extraction, data preparation, EDA,
animal PK modeling and PK/PD index analysis. The current project studies polymyxin B.
Scientific model acceptance remains a human decision.

## Repository map

| Directory | Contents |
| --- | --- |
| `frontend/` | Workbench web interface (HTML, JavaScript, CSS), served by the backend at `/assets` |
| `backend/research_pipeline/research_pipeline/` | Workflow state, APIs, evidence routing, QC, EDA and modeling adapters |
| `backend/research_pipeline/research_pipeline/resources/` | EDA rules and reference resources |
| `backend/research_pipeline/workflow/` | Snakemake file dependencies and execution rules |
| `backend/research_pipeline/docs/` | Contracts, design notes and proposed scientific rules (some JSON here is read at runtime) |
| `backend/research_pipeline/scripts/`, `tests/` | Pipeline utilities (the workbench launches `run_workbench_job.py`) and tests |
| `backend/context_compression/` | Proposal extraction, structured context, independent reviews and provider adapters |
| `pkpd_r/` | R PK, PK/PD index, Emax/Hill, mean-curve and nlmixr2 computation |
| `tools/diagnostics/` | Project-specific input audit utilities |
| `tools/work/` | Earlier literature retrieval and review utilities |
| `reports/` | Static one-off review pages (rat and mouse PK, 2026-09-23); not part of the workbench |
| `.vscode/` | Local editor tasks and debugging configuration |
| `outputs/` | Created on first run; run state, logs and results (not versioned) |

Module READMEs describe their interfaces and tests:
[context compression](backend/context_compression/README.md),
[research pipeline](backend/research_pipeline/README.md),
[R computations](pkpd_r/README.md).

## Workflow

LangGraph manages task state and review boundaries. Prefect coordinates execution;
Snakemake resolves file dependencies and launches computational stages. R and
Python compute scientific results; independent model calls review scoped input
contracts and evidence. A successful process or low AIC does not by itself release
a model for human prediction.

Main stages: intake -> context compression and evidence review -> adequacy ->
preparation/QC -> EDA -> task routing -> animal PK and PK/PD index branches ->
diagnostics and human review.

## Local setup

The workbench was developed on Windows with Python 3.12. From the repository root,
`setup.ps1` creates `.venv-context` and installs both editable packages with the test
and orchestration dependencies:

```powershell
.\setup.ps1
```

Equivalent manual steps:

```powershell
python -m venv .venv-context
.\.venv-context\Scripts\python.exe -m pip install -e ".\backend\context_compression[documents,test]"
.\.venv-context\Scripts\python.exe -m pip install -e ".\backend\research_pipeline[test,workflow]"
```

Install R and the packages needed by the selected adapter as described in
`pkpd_r/README.md`. Point `PKPD_RSCRIPT` to Rscript and `R_LIBS_USER` to the intended
R package library. The optional nlmixr2 adapter requires its scientific runtime in
addition to the basic R modules.

Start the workbench:

```powershell
.\start-workbench.cmd
```

Then open <http://127.0.0.1:8767/>. This launcher selects Codex with `gpt-6-sol`,
using the existing Codex CLI login. Model calls use `CTXCOMP_CODEX_MODEL` or
`gpt-6-sol` by default; an explicit task model takes precedence. To select another
provider or model, set its environment variables and launch
`.\.venv-context\Scripts\python.exe -I -X utf8 -m research_pipeline.workbench --port 8767`
directly. Credentials are not included in this repository.

## Portability and retained research state

This is a source snapshot of an evolving research application, not a claim that
every scientific adapter is complete or qualified. Some project utilities, editor
tasks and historical audit references contain absolute paths for the original
computer. Configure or replace those paths when moving to another machine.
External R libraries and original research packages must be supplied separately.

Installed environments and local CLI tools are excluded from Git. Historical run
data, checkpoints and logs are distributed separately in the private repository's
[2026-10-07 workspace snapshot](https://github.com/GeorgeTeng/PMB-Translational-PKPD/releases/tag/workspace-2026-10-07).
The snapshot includes a file manifest, SHA-256 checksums and consistent SQLite
backups, excluding credentials, installed dependencies and transient caches.
Its standard `.tar.gz` archive stores identical files as hard links while
preserving every path. Extract it with `tar -xzf <archive>.tar.gz` on Windows,
macOS or Linux, or with a compatible archive utility.
Files referenced outside this workspace must still be supplied separately.
The regulatory evidence review remains versioned in Git, with suggested rule
amendments still subject to their recorded review status.

The snapshot preserves successful, failed and exploratory runs as recorded; it
does not turn retained candidates or old approvals into released scientific
results. The latest scoped compression correction is under
`outputs/Compression_Atomicity_Fix_20261007/` inside the snapshot.

## Evidence review

The regulatory evidence review (`outputs/PK_Regulatory_Rules_Audit_20260924/`) is a
research result, not code, and is not part of this code-only copy. It remains in the
original workspace and in the private GitHub repository.

## Verification status

Repository preparation checks file selection, common credential patterns and Git
integrity. It does not constitute a fresh model fit, a full software test run,
scientific validation or approval of a model for clinical use. Existing tests and
the source audit records are retained for reproducible follow-up.
