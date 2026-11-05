"""Direct access to a saved report and the repository's native EDA."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import webbrowser


HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent / "native_workflow" / "backend"
RULES = BACKEND / "rules" / "eda"
sys.path[:0] = [str(BACKEND / "research_pipeline"), str(BACKEND / "context_compression")]


def rule_spec():
    pack = json.loads((RULES / "eda_rules.json").read_bytes())
    spec = pack["source"]["absorption_rule_specification"]
    path = RULES / spec["file"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != spec["sha256"]:
        raise ValueError(f"Rule file differs from its registered SHA-256: {path}")
    return spec, path


def open_report(folder, show_path):
    page = folder.resolve() / "absorption" / "index.html"
    if not page.is_file():
        raise FileNotFoundError(f"Missing {page}. Extract the portable report ZIP into {folder}, or pass an EDA run directory.")
    print(page)
    if not show_path and not webbrowser.open(page.as_uri()):
        raise RuntimeError("Open the printed HTML path in your browser.")


def run_absorption(source, out):
    from research_pipeline import eda_absorption

    source, out = source.resolve(), out.resolve()
    tables = source / "source_tables.json"
    if not tables.is_file():
        raise FileNotFoundError(f"Expected admitted EDA tables at {tables}")
    if out.is_relative_to(source):
        raise ValueError("Choose a new output directory outside the source run.")
    spec, _ = rule_spec()
    print(f"Executing {eda_absorption.VERSION}. Published rule text: {spec['version']}.", flush=True)
    assessment = source / "dose_normalization_assessment.json"
    inputs = [tables, *([assessment] if assessment.is_file() else []), *sorted((source / "EV").glob("*.png"))]
    manifest_path = source / "outputs.json"
    manifest = {k.replace(chr(92), "/"):v for k,v in json.loads(manifest_path.read_bytes()).items()} if manifest_path.is_file() else None
    out.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for path in inputs:
        relative = path.relative_to(source).as_posix()
        dest = out / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, dest)
        hashes[relative] = hashlib.sha256(dest.read_bytes()).hexdigest()
        if manifest is not None and hashes[relative] != manifest.get(relative, {}).get("sha256"):
            raise ValueError(f"Input differs from the source EV manifest: {relative}")
    provenance = {"source_manifest": "verified" if manifest is not None else "not supplied",
                  "input_sha256": hashes, "rule_sha256": spec["sha256"], "engine": eda_absorption.VERSION}
    (out / "replay_inputs.json").write_text(json.dumps(provenance, indent=2),encoding="utf-8")
    folder = eda_absorption.attach(out)
    if (folder / "error.json").exists():
        raise ValueError(f"Absorption failed. See {folder / 'error.json'}")
    open_report(out, show_path=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="command", required=True)
    viewer = actions.add_parser("open", help="open a saved absorption report locally")
    viewer.add_argument("folder", nargs="?", type=Path, default=HERE / "report")
    viewer.add_argument("--print-path", action="store_true", help="resolve the HTML file without opening a browser")
    actions.add_parser("rules", help="verify and locate the published absorption rule text")
    absorption = actions.add_parser("run", help="rebuild absorption from existing admitted EDA tables")
    absorption.add_argument("--source", required=True, type=Path, help="EDA directory containing source_tables.json")
    absorption.add_argument("--out", required=True, type=Path, help="new working directory")
    handoff = actions.add_parser("from-data", help="start native EDA at a released Data handoff")
    handoff.add_argument("--handoff", required=True, type=Path)
    handoff.add_argument("--report", required=True, type=Path, help="bound data_report.json")
    handoff.add_argument("--out", required=True, type=Path, help="new output directory")
    handoff.add_argument("--model", help="model for the configured provider")
    handoff.add_argument("--prepare-only", action="store_true", help="validate and materialize intake only")
    args = parser.parse_args()
    if args.command == "open":
        open_report(args.folder, args.print_path)
    elif args.command == "rules":
        spec, path = rule_spec()
        print(f"{spec['version']}\n{path}\nSHA-256 {spec['sha256']}")
    elif args.command == "run":
        run_absorption(args.source, args.out)
    else:
        from research_pipeline import eda_dh_adapter

        out = args.out.resolve()
        if args.prepare_only:
            eda_dh_adapter.build(args.handoff.resolve(), args.report.resolve(), out)
            print(out / "snapshot_receipt.json")
        else:
            eda_dh_adapter.run(args.handoff.resolve(), args.report.resolve(), out, model=args.model, until="EV")
            error = out / "run" / "absorption" / "error.json"
            if error.exists():
                raise ValueError(f"EV returned an absorption error. See {error}")
            open_report(out / "run", show_path=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, ImportError) as exc:
        sys.exit(str(exc))
