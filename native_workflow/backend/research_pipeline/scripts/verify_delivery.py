"""Rebuild reviewable local examples; no online calls and no acceptance of references."""
import importlib.metadata
import json
import platform
from pathlib import Path
from research_pipeline.api import create_app
from research_pipeline.common import BACKEND, PROJECT, read_json, write_json, sha256, utcnow
from research_pipeline.engine import run_pipeline
from research_pipeline.literature import LocalLibrary

output = PROJECT/'outputs/Research_Pipeline_2026-09-16'
state = output/'verified_state'
examples = BACKEND/'research_pipeline/examples'
report = {'checked_at':utcnow(), 'python':platform.python_version(), 'runs':[]}
for filename, identifier in [('parallel.request.json','parallel_verified_001'), ('roberts_pmb.request.json','roberts_pmb_verified_001')]:
    request = read_json(examples/filename)
    request['request_id'] = identifier
    existing = state/'runs'/identifier/'output.json'
    if existing.exists():
        raise SystemExit('Use a new verification state; immutable run exists: '+str(existing))
    result = run_pipeline(request,state,examples)
    assert result['status'] == 'SUCCEEDED', result
    report['runs'].append({'request_id':identifier,'status':result['status'],'output':str(existing),'sha256':sha256(existing)})
library = LocalLibrary(state/'library.sqlite3')
report['indexing'] = [library.index_file(examples/'roberts_reference_inventory.json'),
                     library.index_file(PROJECT/'outputs/Roberts_2022_Fig4b_2026-09-16/references/article.pdf')]
found = library.search('pharmacokinetics',drug='polymyxin b')
assert found['results'] and not found['network_used']
write_json(output/'local_pmb_search.json',found)
write_json(BACKEND/'research_pipeline/docs/openapi.json',create_app(state).openapi())
dependencies = ['pkpd-research-pipeline','jsonschema','fastapi','uvicorn','python-multipart','openpyxl','pypdf','pytest','httpx','starlette']
report['dependencies'] = {name:importlib.metadata.version(name) for name in dependencies}
write_json(output/'verification.json',report)
(BACKEND/'research_pipeline/requirements-tested.txt').write_text(
    '# Observed environment, 2026-09-16. Install project using setup.ps1.\n'+
    '\n'.join(f'{k}=={v}' for k,v in report['dependencies'].items() if k!='pkpd-research-pipeline')+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
