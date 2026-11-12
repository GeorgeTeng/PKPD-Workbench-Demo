"""Make `python -m pytest tools/eda` self-contained: tests import research_pipeline.eda_*, mapped to this folder."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_fixed import load  # noqa: E402

if "research_pipeline.eda_elimination" not in sys.modules:
    load()
