"""Rule definitions shared by every backend step live in backend/rules (indexed in its README)."""
from pathlib import Path

RULES = Path(__file__).resolve().parents[2] / 'rules'
