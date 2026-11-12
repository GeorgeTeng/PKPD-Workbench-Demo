"""Load a case's frozen module copies and the two explicit study species names."""
import importlib
import json
import sys
from pathlib import Path

engine, stage, run = sys.argv[1:]
sys.path.insert(0,str(Path(engine).resolve()))
ab=importlib.import_module("eda_absorption")
dist=importlib.import_module("eda_distribution")
aliases=json.loads((Path(__file__).with_name("species_aliases.json")).read_text(encoding="utf8"))
for registry in [ab._SPECIES,dist._SP_HEAD]:
    for name,pattern in aliases:
        if all(row[0]!=name for row in registry):
            registry.append((name,pattern))
module=importlib.import_module("eda_"+stage)
module.main([str(Path(run).resolve())])
