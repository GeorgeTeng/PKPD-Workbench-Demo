from hashlib import sha256
import json
import shutil
from pathlib import Path

import pytest
import run_modules

from run_modules import snapshot_stage_config


def test_refresh_of_readonly_frozen_rule(tmp_path):
    source, frozen = tmp_path / "rule", tmp_path / "frozen"
    source.write_bytes(b"new")
    frozen.write_bytes(b"old")
    frozen.chmod(0o444)
    run_modules.copy_rule(source, frozen)
    assert frozen.read_bytes() == b"new"
    frozen.chmod(0o444)
    run_modules.copy_rule(source, frozen)
    assert frozen.read_bytes() == source.read_bytes()


def test_removed_input_plan_cannot_reappear_on_rerun(tmp_path):
    case = tmp_path / "case"
    output = tmp_path / "output"
    case.mkdir()
    output.mkdir()
    plan = case / "distribution_config.json"
    plan.write_text('{"tissue_ratio_comparisons": {}}', encoding="utf8")
    assert snapshot_stage_config(case, output, "distribution") == sha256(plan.read_bytes()).hexdigest()
    assert (output / plan.name).read_bytes() == plan.read_bytes()
    plan.unlink()
    assert snapshot_stage_config(case, output, "distribution") is None
    assert not (output / plan.name).exists()


@pytest.mark.parametrize("fault", ["source", "rules", "frozen_rule", "no_manifest", "no_directory"])
def test_rejected_resume_preserves_every_file(tmp_path, fault):
    case, output = tmp_path / "case", tmp_path / "run"
    case.mkdir()
    source = case / "source_tables.json"
    source.write_bytes(b"[]")
    if fault != "no_directory":
        engine = output / "_engine"
        shutil.copytree(Path(run_modules.__file__).parent / "rules", engine/"rules")
        (engine/"eda_common.py").write_bytes(b"historical code")
        (output/"source_tables.json").write_bytes(b"[{}]" if fault == "source" else source.read_bytes())
        rules = json.loads((engine/"rules/rules_manifest.json").read_bytes())["sections"]
        if fault == "rules":
            rules["elimination"]["version"] = "historical"
        if fault == "frozen_rule":
            target = engine/"rules"/rules["elimination"]["file"]
            target.chmod(0o600)  # the temporary copy inherits the frozen source's read-only bit on Windows
            target.write_bytes(b"historical rule")
        if fault != "no_manifest":
            (output/"run_record.json").write_text(json.dumps({"rules": rules, "source_tables_sha256": sha256(b"[]").hexdigest()}))
    def inventory():
        return {p.relative_to(tmp_path).as_posix(): sha256(p.read_bytes()).hexdigest() if p.is_file() else None
                for p in tmp_path.rglob("*")}
    before = inventory()
    with pytest.raises(SystemExit):
        run_modules.run([str(case), str(output), "--from", "elimination"])
    assert inventory() == before


@pytest.mark.parametrize("fault", ["upstream_json", "shared_helper", "upstream_config", "working_input"])
def test_partial_rerun_validates_inputs_before_writing(tmp_path, monkeypatch, fault):
    engine = Path(run_modules.__file__).parent
    case, out = tmp_path / "case", tmp_path / "run"
    case.mkdir()
    frozen = out / "_engine"
    shutil.copytree(engine / "rules", frozen / "rules")
    shutil.copy2(engine / "eda_common.py", frozen)
    shutil.copy2(engine / "eda_absorption.py", frozen)
    (case / "source_tables.json").write_text("[]")
    shutil.copy2(case / "source_tables.json", out)
    (out / "absorption").mkdir()
    product = out / "absorption" / "absorption.json"
    product.write_text("{}")
    sha = run_modules.sha
    manifest = {"source_tables_sha256": sha(case / "source_tables.json"),
                "rules": run_modules.eda_common.rules_manifest(frozen / "rules")["sections"],
                "stages": {"absorption": {"exit_code": 0, "sha256": sha(frozen / "eda_absorption.py"),
                                          "output_sha256": sha(product), "config_sha256": None}}}
    (out / "run_record.json").write_text(json.dumps(manifest))
    if fault == "upstream_json":
        product.write_text('{"edited":true}')
    elif fault == "shared_helper":
        (frozen / "eda_common.py").write_text("# different calculations")
    elif fault == "upstream_config":
        (case / "absorption_config.json").write_text("{}")
    else:
        (out / "dose_normalization_assessment.json").write_text("{}")
    before = {p: sha(p) for p in out.rglob("*") if p.is_file()}
    monkeypatch.setattr(run_modules.subprocess, "run", lambda *a, **kw: pytest.fail("dispatched with stale evidence"))
    with pytest.raises(SystemExit):
        run_modules.run([str(case), str(out), "--from", "distribution"])
    assert {p: sha(p) for p in out.rglob("*") if p.is_file()} == before
