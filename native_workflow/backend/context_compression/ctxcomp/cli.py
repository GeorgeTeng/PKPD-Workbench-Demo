import argparse
import json
import shutil
import sys
from pathlib import Path
from . import __version__
from .engine import (STAGES, init_run, prepare, accept, verify, verify_context, human_review, load_run,
                     coverage_paths, resolve_coverage)
from .io import read_json
from .providers import run_model


def parser():
    p = argparse.ArgumentParser(description="Research context extraction + scientific workflow planning")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check runtime without opening credentials or calling a model")
    create = sub.add_parser("init", help="Read a proposal or all explicit package/attachment contents; preserve raw copies")
    create.add_argument("--proposal")
    create.add_argument("--package", help="ZIP containing all input files")
    create.add_argument("--proposal-entry", help="Exact proposal entry/name or file ID inside supplied attachments; required when ambiguous")
    create.add_argument("--attachment", action="append", default=[])
    create.add_argument("--reference-only", action="append", default=[], help="Read locally but withhold numerical reference content from the context model")
    create.add_argument("--clarification", action="append", default=[])
    create.add_argument("--inventory")
    create.add_argument("--policy")
    create.add_argument("--literature")
    create.add_argument("--budget")
    create.add_argument("--out", required=True)
    for name in ("prepare", "accept"):
        stage = sub.add_parser(name)
        stage.add_argument("--run", required=True)
        stage.add_argument("--stage", choices=STAGES, required=True)
        if name == "accept":
            stage.add_argument("--response", required=True)
    model = sub.add_parser("run", help="Explicitly send supplied documents to the selected model provider")
    model.add_argument("--run", required=True)
    model.add_argument("--provider", choices=["codex"], required=True)
    model.add_argument("--model", help="Explicit model override; otherwise provider setting (Codex: CTXCOMP_CODEX_MODEL or gpt-6-sol)")
    model.add_argument("--attempts", type=int, choices=[1], default=1, help="One attempt; errors stop execution")
    model.add_argument("--stop-after", choices=["context_review", "pipeline_review"], default="context_review")
    for name in ("verify", "verify-context", "status"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--run", required=True)
    coverage = sub.add_parser("coverage", help="Show IN001 source-content gaps and their human resolutions")
    coverage.add_argument("--run", required=True)
    resolve = sub.add_parser("resolve-coverage",
                             help="Record that detected omitted objects are irrelevant to this task (IN001); never claims extraction")
    resolve.add_argument("--run", required=True)
    resolve.add_argument("--gap", action="append", required=True, help="Gap ID from the coverage report; repeat for several")
    resolve.add_argument("--reviewer", required=True)
    resolve.add_argument("--reason", required=True)
    gate = sub.add_parser("review", help="Record a real human decision, bound to the candidate hash")
    gate.add_argument("--run", required=True)
    gate.add_argument("--decision", choices=["PASS", "FAIL"], required=True)
    gate.add_argument("--reviewer", required=True)
    gate.add_argument("--reason", default="")
    search = sub.add_parser("search", help="Search Europe PMC with explicitly supplied public terms")
    search.add_argument("--query", required=True)
    search.add_argument("--out", required=True)
    search.add_argument("--page-size", type=int, default=10)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        if args.command == "doctor":
            import importlib.util
            result = {"version": __version__, "python": sys.executable,
                      "codex_cli": shutil.which("codex"), "model_login": "NOT_CHECKED",
                      "jsonschema": bool(importlib.util.find_spec("jsonschema")),
                      "pypdf": bool(importlib.util.find_spec("pypdf")),
                      "docx": bool(importlib.util.find_spec("docx"))}
        elif args.command == "init":
            result = init_run(args.out, args.proposal, args.clarification, args.inventory,
                              read_json(args.policy) if args.policy else None, args.literature,
                              read_json(args.budget) if args.budget else None,
                              package=args.package, attachments=args.attachment, reference_only=args.reference_only,
                              proposal_entry=args.proposal_entry)
        elif args.command == "prepare":
            request = prepare(args.run, args.stage)
            result = {"status": "PREPARED", "request_sha256": request["request_sha256"],
                      "request_file": str(Path(args.run).resolve() / "requests" / f"{args.stage}.json")}
        elif args.command == "accept":
            result = accept(args.run, args.stage, read_json(args.response))
        elif args.command == "run":
            result = run_model(args.run, args.model, args.attempts, stop_after=args.stop_after)
        elif args.command == "verify":
            result = verify(args.run)
        elif args.command == "verify-context":
            result = verify_context(args.run)
        elif args.command == "status":
            _, state = load_run(args.run)
            result = {"accepted_stages": list(state["accepted"]),
                      "main_handoff_exists": (Path(args.run) / "handoff/main.json").is_file(),
                      "candidate_exists": (Path(args.run) / "project_plan.candidate.json").exists()}
        elif args.command == "coverage":
            from .coverage import coverage_state
            bundle, _ = load_run(args.run)
            paths = coverage_paths(args.run, bundle)
            result = coverage_state(*paths) if paths else {"status": "NOT_ASSESSED", "reason": "No file intake in this run"}
        elif args.command == "resolve-coverage":
            result = resolve_coverage(args.run, args.gap, args.reviewer, args.reason)
        elif args.command == "review":
            result = human_review(args.run, args.decision, args.reviewer, args.reason)
        elif args.command == "search":
            from .literature import search
            result = search(args.query, args.out, args.page_size)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get("status") in {"REVISE", "NEEDS_REVIEW", "ERROR"}:
            return 2
        return 0
    except (ValueError, OSError, ImportError) as exc:
        print(json.dumps({"status": "ERROR", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)


if __name__ == "__main__":
    raise SystemExit(main())
