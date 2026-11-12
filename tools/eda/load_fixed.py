"""Register the modules in this folder as research_pipeline.eda_* so tests written against the pipeline package run here.

No other folder is needed. When a real research_pipeline package is already imported, the modules are attached to it;
otherwise an empty in-memory package is created (it never imports the pipeline repo).
"""
import importlib.util
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _package():
    package = sys.modules.get("research_pipeline")
    if package is None:
        package = types.ModuleType("research_pipeline")
        package.__path__ = []
        sys.modules["research_pipeline"] = package
    return package


def _register(package, name, path):
    qualified = f"research_pipeline.{name}"
    spec = importlib.util.spec_from_file_location(qualified, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    setattr(package, name, module)
    spec.loader.exec_module(module)
    return module


def load(path=None):
    package = _package()
    for name in ("eda_absorption", "eda_distribution"):
        _register(package, name, HERE / (name + ".py"))
    return _register(package, "eda_elimination", Path(path or HERE / "eda_elimination.py"))


if __name__ == "__main__":
    load().main()
