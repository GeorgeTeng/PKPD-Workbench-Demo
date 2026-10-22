"""Sidecar metadata is emitted after normalization and bound to exact data bytes."""
import csv
import json
import io
from pathlib import Path
from .common import write_json, read_json, sha256


def write_changed(path,value):
    path=Path(path)
    try:
        if read_json(path)==value: return path
    except (OSError,ValueError): pass
    return write_json(path,value)


def reference(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': sha256(path)}


def metadata_sidecar(path, identifier, metadata, *, sources=None, summary=None, role=None):
    path = Path(path)
    sidecar = path.with_name(path.stem + '.metadata.json')
    write_changed(sidecar, {'schema_version': '1.0', 'dataset_id': identifier,
        'role': role or metadata.get('role', 'UNCLASSIFIED'), 'metadata': metadata,
        'data_file': reference(path), 'source_refs': sources or [], 'summary': summary or {},
        'review_status': 'PENDING', 'release_authority': 'SEPARATE_SIGNED_HANDOFF',
        'human_prediction_allowed': False})
    return reference(sidecar)


def export_dataset(folder, group, source_refs):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    path = write_changed(folder / (group['id'] + '.json'), {'records': group['records']})
    csvpath = path.with_suffix('.csv')
    keys = list(dict.fromkeys(k for row in group['records'] for k in row))
    stream=io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=keys); writer.writeheader()
    for row in group['records']:
        writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()})
    encoded=stream.getvalue().encode('utf-8-sig')
    if not csvpath.exists() or csvpath.read_bytes()!=encoded: csvpath.write_bytes(encoded)
    quarantine = write_changed(folder / (group['id'] + '.quarantine.json'), {'records': group['quarantine']})
    meta = metadata_sidecar(path, group['id'], group['metadata'], sources=source_refs,
        summary=group['summary'], role=group['metadata']['role'])
    return {'id': group['id'], 'role': group['metadata']['role'], 'data': reference(path),
            'csv': reference(csvpath), 'metadata_file': meta, 'quarantine': reference(quarantine),
            'readiness': group['readiness'], 'summary': group['summary']}
