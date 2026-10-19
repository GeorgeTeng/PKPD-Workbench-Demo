"""Read-only, allowlisted rule resources for the workbench file browser."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .common import RULES, read_json, sha256


def rule_sources():
    from .project_rule_compact import POLICY_PATH, WORKFLOW_REFERENCE_PATH
    # The Project Rules Agent review record (docs/review_drafts) repeats the runtime PRC text word for word,
    # so only the runtime policy is listed.
    return [
        ('general', 'general', 'General rules', 'Policy', RULES / 'general/workflow_governance.json'),
        ('intake', 'intake', 'File intake', 'Policy', RULES / 'intake/intake_rules.json'),
        ('compression', 'compression', 'Compression', 'Policy', RULES / 'compression/compression_rules.json'),
        ('cc005', 'compression', 'Semantic preservation details', 'Policy', RULES / 'compression/cc005_details.json'),
        ('pk-binding', 'compression', 'PK terminology & bindings', 'Reference', RULES / 'compression/pk_binding_knowledge.json'),
        ('prc-policy', 'prc', 'Project Rules Agent', 'Runtime policy', POLICY_PATH),
        ('prc-workflow', 'prc', 'Module responsibilities & workflow', 'Reference only', WORKFLOW_REFERENCE_PATH),
        ('data-dr', 'data', 'DR · Define data requirements', 'Agent rules', RULES / 'data/dr_requirements.json'),
        ('data-dc', 'data', 'DC · Label data & check coverage', 'Agent rules', RULES / 'data/dc_coverage.json'),
        ('data-dp', 'data', 'DP · Prepare & QC', 'Agent rules', RULES / 'data/dp_preparation.json'),
        ('data-dh', 'data', 'DH · Validate metadata & hand off', 'Agent rules', RULES / 'data/dh_handoff.json'),
        ('method-profiles', 'data', 'PK/PD method profiles', 'Candidate knowledge; review pending', RULES / 'data/pkpd_method_profiles.json'),
        ('data-project-decisions', 'data', 'Confirmed project decisions', 'Awaiting project-rule publication', RULES / 'data/data_project_decisions.20261007.json'),
        ('scientific', 'scientific', 'Earlier PK/PD criteria', 'Inactive review draft', RULES / 'drafts/general_pkpd_rules.json'),
    ]


router = APIRouter()


@router.get('/rule-catalog')
def rule_catalog():
    files = []
    for identifier, group, label, status, path in rule_sources():
        value = read_json(path)
        files.append({'id': identifier, 'group': group, 'label': label, 'status': status,
                      'name': path.name, 'version': value.get('version', value.get('schema_version', 'UNVERSIONED')),
                      'sha256': sha256(path), 'url': '/ui-api/workflow/rule-files/' + identifier})
    return {'files': files, 'read_only': True}


@router.get('/rule-files/{identifier}')
def rule_file(identifier: str):
    source = next((s for s in rule_sources() if s[0] == identifier), None)
    if source is None:
        raise HTTPException(404, 'Unknown rule file')
    path = source[4]
    if not path.is_file():
        raise HTTPException(404, 'Rule file is unavailable')
    return FileResponse(path, media_type='application/json', filename=path.name,
                        headers={'Cache-Control': 'no-store'})
