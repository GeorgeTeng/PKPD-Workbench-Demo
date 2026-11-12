from hashlib import sha256
import json
import shutil
from pathlib import Path

import pytest
import run_modules

from run_modules import snapshot_stage_config


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
