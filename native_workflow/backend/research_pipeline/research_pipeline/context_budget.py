"""Final transport-size guard; application limits, never invented model token counts."""
from pathlib import Path
from ctxcomp.io import canonical, digest
from .common import read_json, sha256

POLICY=Path(__file__).parent/'resources/context_builder/transport_budget.v1.json'


def check(prompt, schema):
    policy=read_json(POLICY)
    schema_text=canonical(schema)
    chars=len(prompt)+len(schema_text)
    octets=len(prompt.encode('utf-8'))+len(schema_text.encode('utf-8'))
    report={'version':policy['version'],'prompt_characters':len(prompt),
        'prompt_utf8_bytes':len(prompt.encode('utf-8')),'transport_schema_characters':len(schema_text),
        'combined_input_characters':chars,'combined_input_utf8_bytes':octets,
        'reserved_output_characters':policy['reserved_output_characters'],
        'reserved_output_utf8_bytes':policy['reserved_output_utf8_bytes'],
        'token_count':None,'token_limit_verified':False,
        'limit_kind':'Application transport budget; not a provider tokenizer or model-window guarantee.',
        'prompt_sha256':digest(prompt),'transport_schema_sha256':digest(schema),
        'policy_ref':{'path':str(POLICY.resolve()),'sha256':sha256(POLICY)}}
    if chars+policy['reserved_output_characters']>policy['total_characters'] or octets+policy['reserved_output_utf8_bytes']>policy['total_utf8_bytes']:
        error=ValueError('Final model input exceeds the configured transport budget; nothing truncated or sent')
        error.budget_report={**report,'status':'REJECTED'}
        raise error
    return {**report,'status':'WITHIN_APPLICATION_BUDGET'}
