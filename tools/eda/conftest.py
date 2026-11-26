"""Make `python -m pytest tools/eda` self-contained: tests import research_pipeline.eda_*, mapped to this folder."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_fixed import load  # noqa: E402

# Backup copies of modules and tests (backups/) are not part of the suite: a second test file with the same name stops collection.
collect_ignore = ["backups"]

if "research_pipeline.eda_elimination" not in sys.modules:
    load()
