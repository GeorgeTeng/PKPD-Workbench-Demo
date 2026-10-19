"""IN001 source-content coverage: find objects a text reader leaves out.

Detection is deterministic and conservative. It reports where extracted text may be
incomplete; it never judges relevance and never claims that omitted content was read.
A detected gap blocks compression until a human records, per gap, that the omitted
object is irrelevant to this task, or until corrected files are supplied in a new run.
"""
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
import xml.etree.ElementTree as ET

from .io import digest, read_json, write_json

DETECTOR_VERSION = '1.0.0'
# Spacer pixels and bullet glyphs are not reported; every larger image is.
MIN_IMAGE_PIXELS = 2500
RESOLUTIONS = 'coverage_resolutions.json'
DECISIONS = ('IRRELEVANT_TO_TASK',)

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
M = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'
A = '{http://schemas.openxmlformats.org/drawingml/2006/main}'
C = '{http://schemas.openxmlformats.org/drawingml/2006/chart}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
PR = '{http://schemas.openxmlformats.org/package/2006/relationships}'
XDR = '{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}'
MC = '{http://schemas.openxmlformats.org/markup-compatibility/2006}'

LIMITATIONS = [
    'Detection finds known object types a text reader omits; it is not a relevance judgment.',
    'Vector drawings, text drawn as outlines and content inside images are not interpreted.',
    f'Images smaller than {MIN_IMAGE_PIXELS} pixels (for example spacer dots) are not reported.',
    'Word headers and footers are not inspected; spreadsheet cell values and comments are read by the parser.',
    'An IRRELEVANT_TO_TASK decision does not mean the omitted content was extracted.']

ACTIONS = {
    'PDF_PAGE_WITHOUT_TEXT': 'Supply a checked OCR or text version of these pages, or confirm they are irrelevant to this task.',
    'PDF_EMBEDDED_IMAGES': 'Check the images (figures, scanned tables, equations). Supply their content as text, or confirm they are irrelevant.',
    'DOCX_EQUATIONS': 'Word equations are not in the extracted text. Supply them as text, or confirm they are irrelevant.',
    'DOCX_TEXT_BOXES': 'Text boxes are not in the extracted text. Move their content into the body, or confirm it is irrelevant.',
    'DOCX_FOOTNOTES': 'Footnotes are not in the extracted text. Supply them in the body or as text, or confirm they are irrelevant.',
    'DOCX_ENDNOTES': 'Endnotes are not in the extracted text. Supply them in the body or as text, or confirm they are irrelevant.',
    'DOCX_COMMENTS': 'Review comments are not in the extracted text. Supply relevant comments as text, or confirm they are irrelevant.',
    'DOCX_IMAGES': 'Images (figures, pasted tables) are not in the extracted text. Supply their content, or confirm they are irrelevant.',
    'DOCX_CHARTS': 'Charts are not in the extracted text. Supply the underlying values, or confirm they are irrelevant.',
    'DOCX_EMBEDDED_OBJECTS': 'Embedded objects (for example OLE tables or equations) are not read. Supply their content, or confirm they are irrelevant.',
    'XLSX_IMAGES': 'Images placed on sheets are not read. Supply their content, or confirm they are irrelevant.',
    'XLSX_CHARTS': 'Charts are not read as data. Confirm the plotted values are in cells, supply them, or confirm the charts are irrelevant.',
    'XLSX_TEXT_SHAPES': 'Text in shapes or text boxes is not read. Move it into cells, or confirm it is irrelevant.',
    'COVERAGE_CHECK_FAILED': 'The coverage check could not inspect this file. Re-save or re-export it and start a new run, or confirm the file is irrelevant.'}
LABELS = {
    'PDF_PAGE_WITHOUT_TEXT': 'PDF pages without extractable text (possibly scanned)',
    'PDF_EMBEDDED_IMAGES': 'Images on PDF pages', 'DOCX_EQUATIONS': 'Word equations',
    'DOCX_TEXT_BOXES': 'Word text boxes', 'DOCX_FOOTNOTES': 'Word footnotes', 'DOCX_ENDNOTES': 'Word endnotes',
    'DOCX_COMMENTS': 'Word comments', 'DOCX_IMAGES': 'Images in Word body', 'DOCX_CHARTS': 'Charts in Word body',
    'DOCX_EMBEDDED_OBJECTS': 'Embedded objects in Word body', 'XLSX_IMAGES': 'Images on spreadsheet sheets',
    'XLSX_CHARTS': 'Charts on spreadsheet sheets', 'XLSX_TEXT_SHAPES': 'Text shapes on spreadsheet sheets',
    'COVERAGE_CHECK_FAILED': 'File structure could not be inspected for omitted content'}


class SourceIncompleteError(ValueError):
    code = 'SOURCE_INCOMPLETE'

    def __init__(self, unresolved):
        self.validation_details = {'rule_id': 'IN001', 'status': 'SOURCE_INCOMPLETE',
            'unresolved_gaps': [{k: g[k] for k in ('id', 'file_id', 'original_name', 'code', 'label', 'count', 'locations')}
                                for g in unresolved]}
        names = ', '.join(f"{g['original_name']} ({g['label']}: {g['count']})" for g in unresolved)
        super().__init__('IN001 SOURCE_INCOMPLETE: extracted text may omit content in ' + names + '. '
                         'Confirm each gap is irrelevant to this task, or supply corrected files in a new run.')


def _snippet(text, limit=60):
    text = ' '.join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + '…'


def _gap(code, count, locations, detail=''):
    return {'code': code, 'label': LABELS[code], 'count': count, 'locations': locations,
            'detail': detail, 'required_action': ACTIONS[code]}


def _image_pixels(xobject):
    try:
        return int(xobject.get('/Width', 0)) * int(xobject.get('/Height', 0))
    except (TypeError, ValueError):
        return 0


def _pdf_images(resources, seen=None, depth=0):
    """Count image XObjects, including those nested one form deep, without decoding them."""
    seen = seen if seen is not None else set()
    count = 0
    try:
        xobjects = resources.get('/XObject') if resources else None
        xobjects = xobjects.get_object() if xobjects is not None else {}
    except Exception:
        return 0
    for name in xobjects:
        try:
            ref = xobjects.raw_get(name)
            key = (ref.idnum, ref.generation) if hasattr(ref, 'idnum') else id(ref)
            obj = xobjects[name].get_object()
        except Exception:
            continue
        if key in seen:
            continue
        seen.add(key)
        subtype = obj.get('/Subtype')
        if subtype == '/Image' and _image_pixels(obj) >= MIN_IMAGE_PIXELS:
            count += 1
        elif subtype == '/Form' and depth < 2:
            count += _pdf_images(obj.get('/Resources'), seen, depth + 1)
    return count


def pdf_gaps(path):
    from pypdf import PdfReader
    empty, images = [], []
    for number, page in enumerate(PdfReader(path).pages, 1):
        text = (page.extract_text() or '').strip()
        if not text:
            empty.append(f'page {number}')
            continue
        found = _pdf_images(page.get('/Resources'))
        if found:
            images.append(f'page {number} ({found} image{"s" if found > 1 else ""})')
    gaps = []
    if empty:
        gaps.append(_gap('PDF_PAGE_WITHOUT_TEXT', len(empty), empty))
    if images:
        gaps.append(_gap('PDF_EMBEDDED_IMAGES', sum(int(re.search(r'\((\d+)', x).group(1)) for x in images), images))
    return gaps


def _xml(archive, name):
    try:
        return ET.fromstring(archive.read(name))
    except KeyError:
        return None


def _paragraph_text(p):
    return ''.join(t.text or '' for t in p.iter(W + 't'))


def _notes(root, tag):
    if root is None:
        return 0
    # Separator and continuation notes are layout, not author content.
    return sum(1 for note in root.iter(W + tag)
               if note.get(W + 'type') in (None, 'normal') and _paragraph_text(note).strip())


def _walk(element):
    """Document-order traversal that skips mc:Fallback, Word's duplicate legacy rendering."""
    yield element
    for child in element:
        if child.tag == MC + 'Fallback':
            continue
        yield from _walk(child)


def _own_text(p):
    """Paragraph text as the reader extracts it: no text-box or fallback content."""
    def visit(element):
        if element.tag in (MC + 'Fallback', W + 'txbxContent'):
            return
        if element.tag == W + 't':
            yield element.text or ''
        for child in element:
            yield from visit(child)
    return ''.join(visit(p))


def _count(element, test):
    return sum(1 for e in _walk(element) if test(e))


def docx_gaps(path):
    codes = ('DOCX_EQUATIONS', 'DOCX_TEXT_BOXES', 'DOCX_IMAGES', 'DOCX_CHARTS', 'DOCX_EMBEDDED_OBJECTS')
    found = {k: [] for k in codes}
    counts = dict.fromkeys(codes, 0)
    with zipfile.ZipFile(path) as archive:
        body = _xml(archive, 'word/document.xml')
        if body is not None:
            nested = {id(p) for box in _walk(body) if box.tag == W + 'txbxContent'
                      for p in _walk(box) if p.tag == W + 'p'}
            number, previous = 0, ''
            for p in (e for e in _walk(body) if e.tag == W + 'p' and id(e) not in nested):
                number += 1
                text = _own_text(p)
                near = text if text.strip() else previous
                where = f'paragraph {number}' + (f' near "{_snippet(near)}"' if near.strip() else '')
                objects = _count(p, lambda e: e.tag == W + 'object')
                ole_previews = sum(_count(o, lambda e: e.tag.endswith('}imagedata')) for o in _walk(p) if o.tag == W + 'object')
                boxes = _count(p, lambda e: e.tag == W + 'txbxContent')
                items = {'DOCX_EQUATIONS': _count(p, lambda e: e.tag == M + 'oMath'),
                         'DOCX_TEXT_BOXES': boxes,
                         'DOCX_IMAGES': _count(p, lambda e: e.tag == A + 'blip' or e.tag.endswith('}imagedata')) - ole_previews,
                         'DOCX_CHARTS': _count(p, lambda e: e.tag == C + 'chart'),
                         'DOCX_EMBEDDED_OBJECTS': objects}
                for code, value in items.items():
                    if value > 0:
                        counts[code] += value
                        found[code].append(where + (f' ({value})' if value > 1 else ''))
                if text.strip():
                    previous = text
        gaps = [_gap(code, counts[code], found[code]) for code in codes if counts[code]]
        for code, part, tag in (('DOCX_FOOTNOTES', 'word/footnotes.xml', 'footnote'),
                                ('DOCX_ENDNOTES', 'word/endnotes.xml', 'endnote')):
            n = _notes(_xml(archive, part), tag)
            if n:
                gaps.append(_gap(code, n, [f'{n} {tag}{"s" if n > 1 else ""} in {part}']))
        comments = _xml(archive, 'word/comments.xml')
        n = sum(1 for c in comments.iter(W + 'comment') if _paragraph_text(c).strip()) if comments is not None else 0
        if n:
            gaps.append(_gap('DOCX_COMMENTS', n, [f'{n} comment{"s" if n > 1 else ""} in word/comments.xml']))
    return gaps


def _rels(archive, part):
    folder, name = PurePosixPath(part).parent, PurePosixPath(part).name
    root = _xml(archive, str(folder / '_rels' / (name + '.rels')))
    result = {}
    if root is not None:
        for rel in root.iter(PR + 'Relationship'):
            if rel.get('TargetMode') == 'External':
                continue
            target = rel.get('Target', '')
            resolved = PurePosixPath(target.lstrip('/')) if target.startswith('/') else folder / target
            parts = []
            for piece in resolved.parts:
                if piece == '..':
                    if parts: parts.pop()
                elif piece != '.':
                    parts.append(piece)
            result[rel.get('Id')] = ('/'.join(parts), rel.get('Type', ''))
    return result


def xlsx_gaps(path):
    found = {'XLSX_IMAGES': [], 'XLSX_CHARTS': [], 'XLSX_TEXT_SHAPES': []}
    counts = dict.fromkeys(found, 0)
    with zipfile.ZipFile(path) as archive:
        workbook = _xml(archive, 'xl/workbook.xml')
        if workbook is None:
            return []
        book_rels = _rels(archive, 'xl/workbook.xml')
        for sheet in workbook.iter():
            if not sheet.tag.endswith('}sheet'):
                continue
            target = book_rels.get(sheet.get(R + 'id'))
            if not target:
                continue
            for drawing, kind in _rels(archive, target[0]).values():
                if not kind.endswith('/drawing'):
                    continue
                root = _xml(archive, drawing)
                if root is None:
                    continue
                items = {'XLSX_IMAGES': sum(1 for e in root.iter() if e.tag == XDR + 'pic'),
                         'XLSX_CHARTS': sum(1 for _ in root.iter(C + 'chart')),
                         'XLSX_TEXT_SHAPES': sum(1 for sp in root.iter(XDR + 'sp')
                                                 if ''.join(t.text or '' for t in sp.iter(A + 't')).strip())}
                for code, value in items.items():
                    if value:
                        counts[code] += value
                        found[code].append(f'sheet "{sheet.get("name")}"' + (f' ({value})' if value > 1 else ''))
    return [_gap(code, counts[code], found[code]) for code in found if counts[code]]


def detect(path):
    suffix = Path(path).suffix.lower()
    if suffix == '.pdf':
        return pdf_gaps(path)
    if suffix == '.docx':
        return docx_gaps(path)
    if suffix == '.xlsx':
        return xlsx_gaps(path)
    return []


def file_gaps(file_id, original_name, sha256, path):
    try:
        found = detect(path)
    except Exception as exc:  # An uninspectable structure is a coverage gap, never a silent pass.
        found = [_gap('COVERAGE_CHECK_FAILED', 1, ['whole file'], f'{type(exc).__name__}: {exc}')]
    return [{'id': f"{file_id}-{g['code']}", 'file_id': file_id, 'original_name': original_name,
             'file_sha256': sha256, **g} for g in found]


def report(gaps, assessed, not_assessed):
    return {'schema_version': '1.0', 'rule_id': 'IN001', 'detector_version': DETECTOR_VERSION,
            'status': 'SOURCE_INCOMPLETE' if gaps else 'NO_GAPS_DETECTED',
            'assessed_file_ids': assessed, 'not_assessed': not_assessed,
            'gaps': gaps, 'limitations': LIMITATIONS,
            'resolution': {'decisions': list(DECISIONS),
                           'alternative': 'Supply corrected or checked readable files in a new run; changed inputs require new intake checks.'}}


def _load_resolutions(path, manifest):
    if not Path(path).is_file():
        return {'schema_version': '1.0', 'rule_id': 'IN001', 'manifest_sha256': manifest['manifest_sha256'], 'resolutions': []}
    value = read_json(path)
    if value.get('manifest_sha256') != manifest['manifest_sha256']:
        raise ValueError('IN001 coverage resolutions belong to a different intake; changed inputs require reassessment')
    return value


def coverage_state(intake_dir, resolutions_path):
    """Current gaps and human resolutions; legacy intakes without detection report NOT_ASSESSED."""
    intake_dir = Path(intake_dir)
    manifest = read_json(intake_dir / 'manifest.json')
    coverage = manifest.get('coverage')
    if not coverage:
        return {'status': 'NOT_ASSESSED', 'gaps': [], 'unresolved': [], 'resolutions': [], 'legacy_intake': True}
    path = intake_dir / coverage['report_path']
    if digest(read_json(path)) != coverage['report_sha256']:
        raise ValueError('IN001 coverage report changed after intake')
    gaps = read_json(path)['gaps']
    resolutions = _load_resolutions(resolutions_path, manifest)['resolutions']
    by_gap = {}
    for item in resolutions:
        gap = next((g for g in gaps if g['id'] == item['gap_id']), None)
        if (gap is None or item['file_sha256'] != gap['file_sha256'] or item['locations'] != gap['locations']
                or item['decision'] not in DECISIONS):
            raise ValueError('IN001 coverage resolution does not match its detected gap: ' + item['gap_id'])
        by_gap[item['gap_id']] = item
    unresolved = [g for g in gaps if g['id'] not in by_gap]
    status = 'NO_GAPS_DETECTED' if not gaps else ('SOURCE_INCOMPLETE' if unresolved else 'GAPS_RESOLVED_BY_HUMAN')
    return {'status': status, 'gaps': gaps, 'unresolved': unresolved, 'resolutions': resolutions,
            'detector_version': coverage.get('detector_version'), 'limitations': read_json(path).get('limitations', [])}


def resolve(intake_dir, resolutions_path, gap_ids, reviewer, reason, decision='IRRELEVANT_TO_TASK', scope=None):
    """Record a human decision per gap. Append-only; a decision cannot be overwritten."""
    if decision not in DECISIONS:
        raise ValueError('Unsupported IN001 decision. Supply corrected files in a new run instead.')
    if not str(reviewer).strip():
        raise ValueError('IN001 resolution requires the reviewer identity')
    if len(str(reason).strip()) < 5:
        raise ValueError('IN001 resolution requires a reason of at least 5 characters')
    gap_ids = list(dict.fromkeys(gap_ids))
    if not gap_ids:
        raise ValueError('Select at least one coverage gap')
    intake_dir = Path(intake_dir)
    manifest = read_json(intake_dir / 'manifest.json')
    state = coverage_state(intake_dir, resolutions_path)
    known = {g['id']: g for g in state['gaps']}
    done = {r['gap_id'] for r in state['resolutions']}
    for gap_id in gap_ids:
        if gap_id not in known:
            raise ValueError('Unknown IN001 coverage gap: ' + gap_id)
        if gap_id in done:
            raise ValueError('IN001 coverage gap already resolved: ' + gap_id)
    record = _load_resolutions(resolutions_path, manifest)
    at = datetime.now(timezone.utc).isoformat()
    for gap_id in gap_ids:
        gap = known[gap_id]
        record['resolutions'].append({
            'gap_id': gap_id, 'decision': decision, 'reason': str(reason).strip(), 'reviewer': str(reviewer).strip(), 'at': at,
            'file_id': gap['file_id'], 'file_sha256': gap['file_sha256'], 'code': gap['code'],
            'locations': gap['locations'], 'scope': scope or {'stage': 'context_compression'},
            'meaning': 'The reviewer judged this omitted object irrelevant to the current task. Its content was not extracted.'})
    write_json(resolutions_path, record)
    return coverage_state(intake_dir, resolutions_path)


def require_resolved(intake_dir, resolutions_path):
    state = coverage_state(intake_dir, resolutions_path)
    if state['unresolved']:
        raise SourceIncompleteError(state['unresolved'])
    return state
