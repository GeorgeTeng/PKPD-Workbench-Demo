"""Complete the demo Rules step from a retained independently verified Context."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app
from ctxcomp.engine import verify_context
from research_pipeline.project_rule_agent import prepare, file_ref
from research_pipeline.demo_key_rules import extract

p = argparse.ArgumentParser()
p.add_argument('--run', required=True, type=Path)
p.add_argument('--model', default='gpt-6-sol')
p.add_argument('--approve-provisional-rules', action='store_true', required=True)
args = p.parse_args()
os.environ.update(PKPD_DEMO_PROVISIONAL_RULES='1', CTXCOMP_MODEL_PROVIDER='codex',
                  CTXCOMP_CODEX_MODEL=args.model, CTXCOMP_CODEX_REASONING_EFFORT='high')
run = args.run.resolve()
verify_context(run/'context_work')
input_path = run/'project_rules/input.json'
input_ref = file_ref(input_path) if input_path.exists() else prepare(run/'context_work', input_path)
print(extract(input_ref, run/'project_rules', model=args.model), flush=True)
