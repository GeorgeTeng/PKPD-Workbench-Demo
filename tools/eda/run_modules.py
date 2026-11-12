"""Run the native descriptive EDA modules on a verified case directory.

Locations come from arguments, then environment variables, then the defaults below,
so this file works from any folder depth:

  --workspace / EDA_WORKSPACE        project workspace (default: nearest parent with data/, deliverables/, outputs/)
  --python    / EDA_PYTHON           Python used to run the modules
  --rscript   / PKPD_RSCRIPT         Rscript executable
  --r-lib     / PKPD_R_LIB           R library folder
  --elimination-r / ELIMINATION_R_SCRIPT   elimination figure script (default: elimination_figures.R next to this file)

Rules: rules/rules_manifest.json names one rules file per section. The run stops if a file is missing or its SHA-256
differs, copies rules/ into _engine/ beside the module copies, and records the entries in run_record.json.

Resume: --from distribution reruns distribution and elimination on an existing run with the same source tables;
--from elimination (or the older --only elimination) reruns elimination only.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime,timezone
from pathlib import Path

local_engine=Path(__file__).resolve().parent
sys.path.insert(0,str(local_engine))
import eda_common  # noqa: E402

workspace=eda_common.WORKSPACE
repo=Path(os.environ.get("EDA_PKPD_REPO",Path.home()/"Documents/Codex/PMB-Translational-PKPD-code"))
science=Path(os.environ.get("EDA_SCIENCE_ENV",Path.home()/"Documents/Codex/ScienceEnv"))
DEFAULTS={
    "python":os.environ.get("EDA_PYTHON",str(repo/".venv-context/Scripts/python.exe")),
    "rscript":os.environ.get("PKPD_RSCRIPT",str(science/"R/bin/Rscript.exe")),
    "r_lib":os.environ.get("PKPD_R_LIB",str(science/"R-library")),
    "elimination_r":os.environ.get("ELIMINATION_R_SCRIPT",str(local_engine/"elimination_figures.R")),
}
py=Path(DEFAULTS["python"])
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def timestamp():return datetime.now(timezone.utc).isoformat()
def save(path,doc):path.write_text(json.dumps(doc,indent=2,ensure_ascii=False),encoding="utf8")

def snapshot_stage_config(data, out, name):
    """Run the statistical design specified by this input, including an absent design."""
    filename = name + "_config.json"
    source, target = data / filename, out / filename
    if source.is_file():
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)
        return sha(target)
    target.unlink(missing_ok=True)
    return None

def run(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument("case",type=Path)
    ap.add_argument("out",type=Path)
    ap.add_argument("--elimination",type=Path,default=local_engine/"eda_elimination.py")
    ap.add_argument("--absorption",type=Path,default=local_engine/"eda_absorption.py")
    ap.add_argument("--distribution",type=Path,default=local_engine/"eda_distribution.py")
    ap.add_argument("--from",dest="start",choices=("absorption","distribution","elimination"),default="absorption",
                    help="rerun this stage and the stages after it on an existing run")
    ap.add_argument("--only",choices=("elimination","all"),default="all",help="older spelling: --only elimination = --from elimination")
    ap.add_argument("--workspace",type=Path,default=workspace)
    ap.add_argument("--python",type=Path,default=Path(DEFAULTS["python"]))
    ap.add_argument("--rscript",type=Path,default=Path(DEFAULTS["rscript"]))
    ap.add_argument("--r-lib",type=Path,default=Path(DEFAULTS["r_lib"]))
    ap.add_argument("--elimination-r",type=Path,default=Path(DEFAULTS["elimination_r"]))
    cfg=ap.parse_args(argv)
    python=cfg.python
    if cfg.only=="elimination":cfg.start="elimination"
    problems=eda_common.check_rules(local_engine/"rules")
    if problems:raise SystemExit("rules folder does not match rules/rules_manifest.json: "+"; ".join(problems))
    data=cfg.case.resolve();out=cfg.out.resolve()
    engine=out/"_engine"
    scripts={"absorption":cfg.absorption.resolve(),"distribution":cfg.distribution.resolve(),"elimination":cfg.elimination.resolve()}
    r_scripts={"absorption":local_engine/"absorption_figures.R","distribution":local_engine/"distribution_figures.R","elimination":cfg.elimination_r.resolve()}
    manifest_path=out/"run_record.json"
    stages=list(scripts)
    if cfg.start!="absorption":
        if not manifest_path.is_file():raise SystemExit(f"--from {cfg.start} needs an existing run in {out}")
        manifest=json.loads(manifest_path.read_text(encoding="utf8"))
        if not (out/"source_tables.json").is_file() or not (data/"source_tables.json").is_file() or not (
                sha(out/"source_tables.json") == sha(data/"source_tables.json") == manifest.get("source_tables_sha256")):
            raise SystemExit("source_tables.json changed since this run; rerun all stages")
        if manifest.get("rules") != eda_common.rules_manifest(local_engine/"rules")["sections"]:
            raise SystemExit("the rules changed since this run; rerun all stages so every section uses one rules version")
        if eda_common.check_rules(engine/"rules") or eda_common.rules_manifest(engine/"rules")["sections"] != manifest["rules"]:
            raise SystemExit("the frozen rules do not match the run record; rerun all stages in a new directory")
        stages=stages[stages.index(cfg.start):]
        manifest.setdefault("resumed",[]).append({"from":cfg.start,"utc":timestamp()})
    # A rejected resume must have no filesystem side effects, including directory creation.
    if not (data/"source_tables.json").is_file():
        raise SystemExit("source_tables.json is missing from the input")
    out.mkdir(parents=True,exist_ok=True)
    engine.mkdir(exist_ok=True)
    for filename in ("modeling_handoff.py", "eda_modeling_rules.json", "eda_common.py"):
        shutil.copy2(local_engine / filename, engine / filename)
    if cfg.start=="absorption":
        shutil.copytree(local_engine/"rules", engine/"rules", dirs_exist_ok=True)
        for n in ("source_tables.json","dose_normalization_assessment.json","reported_parameter_context.json"):
            if (data/n).is_file():shutil.copy2(data/n,out/n)
        manifest={"input":str(data),"source_tables_sha256":sha(out/"source_tables.json"),"start_utc":timestamp(),"stages":{}}
    manifest["rules"]=eda_common.rules_manifest(local_engine/"rules")["sections"]
    manifest["locations"]={"workspace":str(cfg.workspace.resolve()),"python":str(python),"rscript":str(cfg.rscript),
                           "r_lib":str(cfg.r_lib),"elimination_r":str(r_scripts["elimination"])}
    snapshot_plots = {}
    for stage in stages:
        shutil.copy2(scripts[stage],engine/("eda_"+stage+".py"))
        render_dir = engine / (stage + "_r")
        render_dir.mkdir(exist_ok=True)
        snapshot_plots[stage] = Path(shutil.copy2(r_scripts[stage], render_dir))
        style = r_scripts[stage].with_name("plot_style.R")
        if style.is_file():
            shutil.copy2(style, render_dir)
        else:
            (render_dir / "plot_style.R").unlink(missing_ok=True)
    env=dict(os.environ,PYTHONUTF8="1",PYTHONIOENCODING="utf-8",PYTHONDONTWRITEBYTECODE="1",
             EDA_WORKSPACE=str(cfg.workspace.resolve()),
             PKPD_RSCRIPT=str(cfg.rscript),PKPD_R_LIB=str(cfg.r_lib),R_LIBS_USER=str(cfg.r_lib),
             **{name.upper()+"_R_SCRIPT":str(p) for name,p in snapshot_plots.items()})
    for name in stages:
        script=engine/("eda_"+name+".py")
        plot = snapshot_plots[name]
        entry={"program":str(scripts[name]),"sha256":sha(script),"plot_program":str(r_scripts[name]),"r_sha256":sha(plot),"plot_snapshot":plot.relative_to(out).as_posix(),"start_utc":timestamp()}
        entry["config_sha256"] = snapshot_stage_config(data, out, name)
        style = plot.with_name("plot_style.R")
        if style.is_file():
            entry["plot_style_sha256"] = sha(style)
        manifest["stages"][name]=entry;save(manifest_path,manifest)
        log_path=out/(name+".log")
        launcher=local_engine/"invoke_stage.py"
        entry["alias_registry_sha256"]=sha(launcher.with_name("species_aliases.json"))
        with log_path.open("w",encoding="utf8") as log:
            result=subprocess.run([str(python),str(launcher),str(engine),name,str(out)],env=env,cwd=cfg.workspace.resolve(),stdout=log,stderr=subprocess.STDOUT)
        entry.update(exit_code=result.returncode,end_utc=timestamp())
        if result.returncode:
            save(manifest_path,manifest)
            raise RuntimeError(f"{name} failed; see {log_path}")
        product=out/name/(name+".json")
        obj=json.loads(product.read_text(encoding="utf8"))
        entry.update(output_sha256=sha(product),version=obj.get("version"),render=obj.get("render"),figures=len(list((out/name).glob("*.png"))))
        save(manifest_path,manifest)
        print(name,entry["figures"],flush=True)
    coverage = eda_common.write_coverage(out)
    manifest["coverage"] = {"path": "coverage.json", "sha256": sha(out / "coverage.json"),
                            "unused_all_sections": coverage["summary"]["unused_all_sections"]}
    save(manifest_path, manifest)
    publisher = local_engine / "publish_portal.py"
    subprocess.run([str(python), str(publisher), str(out)], env=env, check=True)
    publication = json.loads((out/"portal_publication.json").read_text(encoding="utf8"))
    manifest["interface"] = {"publication": "portal_publication.json", "owner_sha256": publication["owner_sha256"],
                             "entry": "index.html", "question_report": "report.html", "figures": "figures/index.html"}
    manifest["modeling_input"] = publication["modeling_input"]
    save(manifest_path,manifest)
if __name__=="__main__":run()
