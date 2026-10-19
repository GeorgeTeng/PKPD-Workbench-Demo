import copy
import subprocess
from unittest.mock import patch

import pytest

from ctxcomp.handoff import verify_main
from ctxcomp.io import read_json
from ctxcomp.providers import codex_generate


def minimal_main():
    return {'version': '3.0', 'objective': 'Assess PMB animal-to-human PK.',
            'study': {key: 'NOT_FOUND' for key in ('drug','regimen','population','system','measurements','methods')},
            'data': {'available': [], 'required': [], 'files': []},
            'rules': ['R001: Keep benchmark data separate.'], 'checks': [], 'uncertainties': []}


def test_nonconsecutive_rule_ids_rejected():
    value = minimal_main()
    verify_main(value)
    value['rules'] = ['R002: Keep benchmark data separate.']
    with pytest.raises(ValueError, match='consecutive'):
        verify_main(value)


def test_reference_file_cannot_be_routed_to_pk_or_changed(tmp_path):
    import hashlib
    value = minimal_main()
    path = tmp_path/'reference.json'; path.write_text('{}', encoding='utf-8')
    value['data']['files'] = [{'id':'F1', 'name':path.name, 'path':str(path),
        'sha256':hashlib.sha256(path.read_bytes()).hexdigest(), 'kind':'json', 'role':'REFERENCE_ONLY',
        'receivers':['pk_longitudinal'], 'read_status':'READ_COMPLETE', 'qc_status':'NOT_RUN', 'fit_ready':False}]
    with pytest.raises(ValueError, match='routing contradicts'):
        verify_main(value)
    value['data']['files'][0]['receivers'] = ['validation']
    verify_main(value)
    path.write_text('{"changed":true}', encoding='utf-8')
    with pytest.raises(ValueError, match='missing or changed'):
        verify_main(value)


def test_timeout_diagnostics_survive_without_accepting_output(tmp_path):
    request = {'request_sha256':'test-request', 'payload':{'schema':{'type':'object'}}}
    failure = subprocess.TimeoutExpired(['mock'],600,output=b'{"type":"turn.started"}\n',
                                         stderr=b'Authorization: Bearer TOKEN_VALUE\nnetwork interrupted')
    with patch('ctxcomp.providers.shutil.which',return_value='mock'), \
         patch('ctxcomp.providers.monitored_run',side_effect=failure):
        with pytest.raises(ValueError,match='exceeded 600 seconds'):
            codex_generate(request,timeout=600,diagnostics_dir=tmp_path)
    assert read_json(tmp_path/'call.json')['status']=='TIMEOUT'
    assert 'turn.started' in (tmp_path/'events.jsonl').read_text(encoding='utf-8')
    stderr=(tmp_path/'stderr.log').read_text(encoding='utf-8')
    assert 'TOKEN_VALUE' not in stderr and 'network interrupted' in stderr


def test_main_carries_intake_snapshot_for_data(tmp_path):
    import hashlib, json
    from ctxcomp.handoff import main_handoff
    from ctxcomp.intake import intake_files
    proposal = tmp_path/'proposal.md'; proposal.write_text('# Proposal\nAssess exposure.\n', encoding='utf-8')
    table = tmp_path/'data.csv'; table.write_text('Time (h),Concentration (mg/L)\n0,4\n', encoding='utf-8')
    run = tmp_path/'run'; intake = intake_files(run/'intake', paths=[proposal, table])
    proposal_id = next(f['id'] for f in intake['manifest']['files'] if f['original_name'] == 'proposal.md')
    context = minimal_main(); del context['data']['files']
    (run/'context.json').write_text(json.dumps({'context': context}), encoding='utf-8')
    bundle = {'intake': {'manifest_path': 'intake/manifest.json'},
              'compression_scope': {'proposal_file_id': proposal_id}, 'inventory': []}
    state = {'accepted': {'context_review': {}, 'context': {'file': 'context.json'}}}
    value = main_handoff(run, bundle, state)
    files = value['data']['files']
    assert sorted(f['role'] for f in files) == ['DATA_CANDIDATE', 'PROPOSAL']
    for f in files:
        assert hashlib.sha256(open(f['snapshot_path'], 'rb').read()).hexdigest() == f['snapshot_sha256']
    verify_main(value)
    files[0]['snapshot_sha256'] = 'not-a-hash'
    with pytest.raises(ValueError):
        verify_main(value)
