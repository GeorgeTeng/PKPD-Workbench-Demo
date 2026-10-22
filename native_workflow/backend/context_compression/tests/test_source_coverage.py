"""IN001 source-content coverage: synthetic files only; detection is structural, never semantic."""
import json
import zipfile
import pytest
from docx import Document
from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.drawing.image import Image
from PIL import Image as PILImage
from pypdf import PdfWriter
from ctxcomp import coverage
from ctxcomp.cli import main
from ctxcomp.engine import init_run, prepare, resolve_coverage
from ctxcomp.io import read_json

EQUATION = ('<w:p><w:r><w:t>Clearance follows</w:t></w:r>'
            '<m:oMath><m:r><m:t>CL = Dose / AUC</m:t></m:r></m:oMath></w:p>')
TEXT_BOX = ('<w:p><w:r><w:t>After.</w:t></w:r></w:p><w:p><w:r><w:pict><v:shape><v:textbox><w:txbxContent>'
            '<w:p><w:r><w:t>Boxed dosing note</w:t></w:r></w:p></w:txbxContent></v:textbox></v:shape></w:pict></w:r></w:p>')
FOOTNOTES = ('<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
             '<w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/></w:r></w:p></w:footnote>'
             '<w:footnote w:id="1"><w:p><w:r><w:t>Doses were adjusted for salt form.</w:t></w:r></w:p></w:footnote>'
             '</w:footnotes>')


def docx_with_objects(path, extra=True):
    document = Document(); document.add_paragraph('Plain proposal paragraph.'); document.save(path)
    if not extra:
        return path
    with zipfile.ZipFile(path) as source:
        parts = {name: source.read(name) for name in source.namelist()}
    body = parts['word/document.xml'].decode('utf-8')
    parts['word/document.xml'] = body.replace('<w:sectPr', EQUATION + TEXT_BOX + '<w:sectPr', 1).encode('utf-8')
    parts['word/footnotes.xml'] = FOOTNOTES.encode('utf-8')
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as target:
        for name, content in parts.items():
            target.writestr(name, content)
    return path


def test_docx_detector_locates_equation_text_box_and_real_footnotes(tmp_path):
    gaps = {g['code']: g for g in coverage.docx_gaps(docx_with_objects(tmp_path / 'p.docx'))}
    assert set(gaps) == {'DOCX_EQUATIONS', 'DOCX_TEXT_BOXES', 'DOCX_FOOTNOTES'}
    assert gaps['DOCX_EQUATIONS']['locations'] == ['paragraph 2 near "Clearance follows"']
    # Text-box paragraphs are not numbered and their text is not used as the anchor.
    assert gaps['DOCX_TEXT_BOXES']['locations'] == ['paragraph 4 near "After."']
    assert gaps['DOCX_FOOTNOTES']['count'] == 1  # The separator note is layout, not content.
    assert all(g['required_action'] for g in gaps.values())
    assert coverage.docx_gaps(docx_with_objects(tmp_path / 'plain.docx', extra=False)) == []


def test_xlsx_detector_finds_image_and_chart_by_sheet(tmp_path):
    PILImage.new('RGB', (80, 80), 'red').save(tmp_path / 'img.png')
    book = Workbook(); sheet = book.active; sheet.title = 'PK data'
    for row in [('time', 'conc'), (1, 2.0), (2, 1.5)]:
        sheet.append(row)
    sheet.add_image(Image(str(tmp_path / 'img.png')), 'D2')
    chart = BarChart(); chart.add_data(Reference(sheet, min_col=2, min_row=1, max_row=3), titles_from_data=True)
    sheet.add_chart(chart, 'D10')
    book.save(tmp_path / 'data.xlsx')
    gaps = {g['code']: g for g in coverage.xlsx_gaps(tmp_path / 'data.xlsx')}
    assert set(gaps) == {'XLSX_IMAGES', 'XLSX_CHARTS'}
    assert all('PK data' in ' '.join(g['locations']) for g in gaps.values())


def test_pdf_page_without_text_and_unreadable_structure_are_gaps(tmp_path):
    writer = PdfWriter(); writer.add_blank_page(200, 200)
    with open(tmp_path / 'scan.pdf', 'wb') as f:
        writer.write(f)
    gaps = coverage.pdf_gaps(tmp_path / 'scan.pdf')
    assert [g['code'] for g in gaps] == ['PDF_PAGE_WITHOUT_TEXT'] and gaps[0]['locations'] == ['page 1']
    (tmp_path / 'broken.docx').write_bytes(b'not a zip')
    failed = coverage.file_gaps('F0009', 'broken.docx', 'x', tmp_path / 'broken.docx')
    assert [g['code'] for g in failed] == ['COVERAGE_CHECK_FAILED'] and failed[0]['id'] == 'F0009-COVERAGE_CHECK_FAILED'


def make_run(tmp_path, attachment):
    proposal = tmp_path / 'proposal.txt'
    proposal.write_text('Objective: estimate rat clearance from the attached study.', encoding='utf-8')
    run = tmp_path / 'run'
    init_run(run, attachments=[proposal, attachment], proposal_entry=proposal.name)
    return run


def test_intake_reports_gaps_and_compression_waits_for_human_resolution(tmp_path, capsys):
    run = make_run(tmp_path, docx_with_objects(tmp_path / 'study.docx'))
    manifest = read_json(run / 'intake/manifest.json')
    assert manifest['coverage']['status'] == 'SOURCE_INCOMPLETE' and len(manifest['coverage']['gap_ids']) == 3
    readability = read_json(run / 'intake/readability_report.json')
    assert readability['status'] == 'SOURCE_INCOMPLETE' and readability['coverage']['gap_count'] == 3
    with pytest.raises(coverage.SourceIncompleteError) as stopped:
        prepare(run, 'attachment_plan')
    assert stopped.value.code == 'SOURCE_INCOMPLETE'
    assert {g['code'] for g in stopped.value.validation_details['unresolved_gaps']} == {
        'DOCX_EQUATIONS', 'DOCX_TEXT_BOXES', 'DOCX_FOOTNOTES'}
    ids = manifest['coverage']['gap_ids']
    with pytest.raises(ValueError, match='reason'):
        resolve_coverage(run, ids[:1], 'Synthetic reviewer', 'no')
    with pytest.raises(ValueError):
        resolve_coverage(run, ['F0002-UNKNOWN'], 'Synthetic reviewer', 'Not relevant to clearance')
    resolve_coverage(run, ids[:1], 'Synthetic reviewer', 'Equation restates text already present')
    with pytest.raises(ValueError):
        resolve_coverage(run, ids[:1], 'Synthetic reviewer', 'Repeated decision for the same gap')
    with pytest.raises(coverage.SourceIncompleteError):
        prepare(run, 'attachment_plan')
    assert main(['resolve-coverage', '--run', str(run), '--gap', ids[1], '--gap', ids[2],
                 '--reviewer', 'Synthetic reviewer', '--reason', 'Box and footnote are layout notes only']) == 0
    capsys.readouterr()
    assert main(['coverage', '--run', str(run)]) == 0
    state = json.loads(capsys.readouterr().out)
    assert state['status'] == 'GAPS_RESOLVED_BY_HUMAN' and not state['unresolved']
    record = read_json(run / 'coverage_resolutions.json')['resolutions'][0]
    assert record['decision'] == 'IRRELEVANT_TO_TASK' and record['scope']['stage'] == 'context_compression'
    assert 'extract' in record['meaning'].lower()  # The decision never claims extraction.
    assert prepare(run, 'attachment_plan')['request_sha256']


def test_tampered_resolution_or_report_is_not_accepted(tmp_path):
    run = make_run(tmp_path, docx_with_objects(tmp_path / 'study.docx'))
    ids = read_json(run / 'intake/manifest.json')['coverage']['gap_ids']
    resolve_coverage(run, ids, 'Synthetic reviewer', 'All three objects are irrelevant')
    value = read_json(run / 'coverage_resolutions.json')
    value['resolutions'][0]['gap_id'] = 'F0002-DOCX_CHARTS'
    (run / 'coverage_resolutions.json').write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(ValueError):
        prepare(run, 'attachment_plan')


def test_clean_attachment_needs_no_resolution(tmp_path):
    run = make_run(tmp_path, docx_with_objects(tmp_path / 'study.docx', extra=False))
    assert read_json(run / 'intake/manifest.json')['coverage']['status'] == 'NO_GAPS_DETECTED'
    assert prepare(run, 'attachment_plan')['request_sha256']


def test_read_error_carries_a_specific_class(tmp_path):
    proposal = tmp_path / 'proposal.txt'; proposal.write_text('Objective text.', encoding='utf-8')
    (tmp_path / 'broken.docx').write_bytes(b'not a zip archive')
    with pytest.raises(ValueError, match='could not read broken.docx'):
        init_run(tmp_path / 'run', attachments=[proposal, tmp_path / 'broken.docx'], proposal_entry=proposal.name)
    error = read_json(tmp_path / 'run/intake/read_error.json')
    assert error['error_class'] == 'CORRUPT_OR_INVALID_FILE'
    assert error['corrective_action'].startswith('The file appears damaged')


def test_structured_warnings_follow_the_runs_frozen_cc019_contract():
    from ctxcomp.supporting import warning_contract, published_warnings
    historical = {'processing_rules': {'rules': [{'id': 'CC019', 'handoff_requirement': {'target': 'main.json'}}]}}
    assert warning_contract(historical) is None  # Older runs keep their original request and handoff shape.
    current = {'processing_rules': {'rules': [{'id': 'CC019', 'handoff_requirement': {'main_field': 'missing_information'}}]},
               'missing_information_warnings': [{'id': 'MI001', 'field': 'dose basis', 'status': 'AMBIGUOUS',
                   'needed_at': 'prepare', 'downstream_impact': 'Dose normalisation cannot be checked.',
                   'importance_reason': 'Salt and free-base doses differ.', 'requested_information': 'State the dose basis.',
                   'reason': 'Two statements disagree.', 'search': {'files': []}}]}
    assert warning_contract(current)
    assert published_warnings(current) == {'schema_version': '1.0', 'items': [{
        'id': 'MI001', 'field': 'dose basis', 'status': 'AMBIGUOUS', 'needed_at': 'prepare',
        'impact': 'Dose normalisation cannot be checked.', 'why_it_matters': 'Salt and free-base doses differ.',
        'clarification': 'State the dose basis.', 'resolution_status': 'OPEN'}]}
