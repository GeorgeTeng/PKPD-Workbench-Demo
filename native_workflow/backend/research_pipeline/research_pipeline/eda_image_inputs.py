"""Explicit immutable image transport for EI/ER; no inferred image access."""
from pathlib import Path
from . import context_builder as cb
from .common import read_json

def transport_scope(manifest_ref, call_id):
    if call_id not in {'EI-findings','ER-review'}:
        raise ValueError('Image transport only supports EI/ER')
    cb.check_refs({'image_manifest':manifest_ref})
    manifest=read_json(manifest_ref['path'])
    if manifest.get('version')!='EDA_IMAGE_INPUTS_1' or not manifest.get('images'):
        raise ValueError('Invalid image manifest')
    ids=[]
    for image in manifest['images']:
        ids.append(image['figure_id'])
        cb.check_refs({'image':image['file']})
        if not Path(image['file']['path']).read_bytes().startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('EDA image must be an existing PNG')
    if len(ids)!=len(set(ids)):
        raise ValueError('Duplicate image identity')
    return {'mode':'JSON_WITH_ATTACHED_IMAGES','rendered_images_supplied':True,
        'manifest_ref':manifest_ref,'images':manifest['images'],
        'boundary':'Images are attached in this exact manifest order. Use pixels for visual patterns and exact supplied rows for numbers. Report unreadable or uninspected images; attachment does not prove inspection. All other paths are locators only. No file/tool access is permitted.',
        'image_token_budget_verified':False}

def attachment_paths(request, provider):
    payload=request.get('payload',{})
    scope=payload.get('transport_scope',{})
    if scope.get('mode')!='JSON_WITH_ATTACHED_IMAGES':
        return []
    if provider!='codex':
        raise ValueError('This provider has no implemented EDA image transport; refusing a text-only fallback')
    expected=transport_scope(scope['manifest_ref'],payload.get('stage'))
    if expected!=scope:
        raise ValueError('Image transport differs from bound manifest')
    return [item['file']['path'] for item in expected['images']]
