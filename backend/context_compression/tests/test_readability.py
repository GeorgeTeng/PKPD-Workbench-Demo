"""CC013: actual parsing, explicit failures and honest deferred-read status."""
import pytest

from ctxcomp.engine import init_run
from ctxcomp.handoff import verify_main
from ctxcomp.io import read_json
from ctxcomp import intake
from test_main_handoff import minimal_main


@pytest.mark.parametrize('name,content', [
    ('broken.json', b'{unfinished'),
    ('broken.csv', b'\xff\xfeinvalid UTF-8'),
    ('broken.xlsx', b'not a workbook'),
    ('broken.docx', b'not a document archive'),
    ('broken.pdf', b'not a PDF'),
])
def test_unreadable_input_stops_with_actionable_diagnosis(tmp_path, name, content):
    proposal = tmp_path / 'proposal.md'
    proposal.write_text('Assess animal PK.', encoding='utf-8')
    attachment = tmp_path / name
    attachment.write_bytes(content)
    run = tmp_path / 'run'
    with pytest.raises(ValueError, match='CC013.*' + name):
        init_run(run, proposal, attachments=[attachment])
    diagnosis = read_json(run / 'intake/read_error.json')
    assert diagnosis['status'] == 'READ_FAILED'
    assert diagnosis['original_name'] == name
    assert diagnosis['reason'] and diagnosis['corrective_action']
    assert diagnosis['qc_status'] == 'NOT_RUN' and diagnosis['fit_ready'] is False
    assert not (run / 'intake/manifest.json').exists()
    assert not (run / 'handoff/main.json').exists()


def test_held_out_file_is_byte_read_without_claiming_content_parsing(tmp_path, monkeypatch):
    proposal = tmp_path / 'proposal.md'
    proposal.write_text('Assess animal PK.', encoding='utf-8')
    held_out = tmp_path / 'holdout.json'
    held_out.write_bytes(b'Protected content, deliberately not valid JSON.')
    original_parser = intake.parse_file
    parsed_suffixes = []

    def parse(path):
        parsed_suffixes.append(path.suffix)
        return original_parser(path)

    monkeypatch.setattr(intake, 'parse_file', parse)
    run = tmp_path / 'run'
    init_run(run, proposal, attachments=[held_out], opaque_references=True)
    manifest = read_json(run / 'intake/manifest.json')
    assert manifest['status'] == 'REGISTERED_WITH_DEFERRED_READS'
    reference = next(f for f in manifest['files'] if f['role'] == 'REFERENCE_ONLY')
    assert parsed_suffixes == ['.md']
    assert reference['read_status'] == 'BYTES_READ_ONLY'
    assert reference['qc_status'] == 'NOT_RUN'
    assert not reference['content_sent_to_context']
    assert (run / 'intake' / reference['raw_path']).read_bytes() == held_out.read_bytes()
    registry = read_json(run / 'audit/file_registry.json')
    routed = next(f for f in registry['files'] if f['purpose'] == 'REFERENCE_ONLY')
    assert routed['read_status'] == 'BYTES_READ_ONLY'
    assert routed['receivers'] == ['validation'] and routed['fit_ready'] is False
    assert intake.verify_intake(run / 'intake/manifest.json') == manifest


def test_portable_handoff_allows_deferred_reads_only_for_reference_files():
    value = minimal_main()
    entry = {'id': 'F1', 'name': 'reference.json', 'path': 'unused', 'sha256': 'a' * 64,
             'kind': 'json', 'role': 'REFERENCE_ONLY', 'receivers': ['validation'],
             'read_status': 'BYTES_READ_ONLY', 'qc_status': 'NOT_RUN', 'fit_ready': False}
    value['data']['files'] = [entry]
    verify_main(value, check_files=False)
    entry.update(role='DATA_CANDIDATE', receivers=['data_preparation'])
    with pytest.raises(ValueError):
        verify_main(value, check_files=False)
