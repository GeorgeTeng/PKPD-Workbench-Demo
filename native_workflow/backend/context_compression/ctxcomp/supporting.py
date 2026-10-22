"""Question-led local evidence retrieval. No cleaning, fits, or early holdout access."""
import json
import re
from pathlib import Path
from .io import read_json, digest, leaves
from .intake import parse_file, file_hash
from .retention import source_units, exact_ids
from .schemas import obj, arr, S, enum, validate_schema
from .rules import frozen_rule, host_requirement
from . import matching

STAGES = ('attachment_plan', 'attachment_evidence')
QUESTION = obj(id=S, field=S, question=S, importance=enum('MATERIAL', 'OPTIONAL'),
               importance_reason=S, needed_at=enum('context','adequacy','prepare','eda','pk','index','human_pk','validation','clinical'),
               downstream_impact=S, requested_information=S, file_ids=arr(S), search_terms=arr(S,1))
CITATION = obj(passage_id=S, quote=S)
ANSWER = obj(question_id=S, status=enum('FOUND','NOT_FOUND','SEARCH_INCOMPLETE','CONFLICT','DEFERRED'),
             statement=S, reason=S, citations=arr(CITATION))
SCHEMAS = {'attachment_plan': obj(request_sha256=S, questions=arr(QUESTION)),
           'attachment_evidence': obj(request_sha256=S, answers=arr(ANSWER))}
# CC019 structured warnings (compression rules 1.19.0+): AMBIGUOUS is kept apart from conflict and absence.
WARNING_STATUSES = ('NOT_FOUND', 'SEARCH_INCOMPLETE', 'DEFERRED', 'AMBIGUOUS', 'CONFLICT')
ANSWER_V2 = obj(question_id=S, status=enum('FOUND', *WARNING_STATUSES), statement=S, reason=S, citations=arr(CITATION))
EVIDENCE_V2 = obj(request_sha256=S, answers=arr(ANSWER_V2))
NEEDED_AT = QUESTION['properties']['needed_at']['enum']


def warning_contract(bundle):
    """The run's frozen CC019 contract when it publishes main.json.missing_information; else None."""
    contract = frozen_rule(bundle, 'CC019').get('handoff_requirement', {})
    return contract if contract.get('main_field') == 'missing_information' else None


def evidence_handling(bundle):
    """The run's frozen CC002 host requirement for supporting passages; {} before compression rules 1.20.0."""
    return host_requirement(bundle, 'CC002')


QUESTION_LINKS = ('CITED_PASSAGES', 'SUPPORTING_PASSAGES')


def model_questions(bundle):
    """supporting_questions as sent to models. Under CC002 1.20.0-1.21.0 cited_passage_ids holds every citation;
    from 1.22.0 it holds supporting passages only and cited proposal passages are listed apart."""
    questions = bundle.get('supporting_questions', [])
    if evidence_handling(bundle).get('question_links') != 'SUPPORTING_PASSAGES':
        return questions
    supporting = {s['id'] for s in bundle['sources'] if s['role'] == 'SUPPORTING_EVIDENCE'}
    return [{**q, 'cited_passage_ids': [i for i in q['cited_passage_ids'] if i in supporting],
             'cited_proposal_ids': [i for i in q['cited_passage_ids'] if i not in supporting]} for q in questions]


def review_unit_ids(bundle):
    """Source units that need their own review verdict: all of them, or only the proposal's under CC002 1.20.0."""
    if evidence_handling(bundle).get('unit_review') == 'COMPRESSION_SCOPE':
        scope = set(bundle['compression_scope']['source_ids'])
        return [u['id'] for u in bundle['source_units'] if u['source_id'] in scope]
    return [u['id'] for u in bundle['source_units']]


def model_warnings(bundle):
    """Warnings as sent to models. Under CC002 1.20.0 a summary replaces each search log; the audit keeps the full log."""
    warnings = bundle.get('missing_information_warnings', [])
    if evidence_handling(bundle).get('warning_search_log') != 'SUMMARY':
        return warnings
    supplied = {s['id'] for s in bundle['sources']}
    summary = lambda s: {'question_id': s['question_id'], 'terms': s['terms'], 'method': s['method'],
        'files': [{**{k: v for k, v in f.items() if k != 'locations'}, 'matched_locations': len(f['locations'])}
                  for f in s['files']],
        'matched_passages': len(s['passage_ids']),
        'supplied_passage_ids': [p for p in s['passage_ids'] if p in supplied],
        'full_log': 'audit/missing_information_review.json'}
    return [{**w, 'search': summary(w['search'])} for w in warnings]


def published_warnings(bundle):
    """Deterministic projection of the reviewed warning records; no model rewrites these fields."""
    return {'schema_version': '1.0', 'items': [
        {'id': w['id'], 'field': w['field'], 'status': w['status'], 'needed_at': w['needed_at'],
         'impact': w['downstream_impact'], 'why_it_matters': w['importance_reason'],
         'clarification': w['requested_information'], 'resolution_status': 'OPEN'}
        for w in bundle.get('missing_information_warnings', [])]}


class EvidenceCitationError(ValueError):
    code = 'MODEL_CITATION_INVALID'

    def __init__(self, question_id, citation_id, source_type, reason):
        self.validation_details = {'question_id': question_id, 'citation_id': citation_id,
                                   'source_type': source_type, 'reason': reason}
        explanation = ('Citation is not in this question\'s searched evidence or supplied proposal' if reason == 'OUT_OF_SCOPE'
                       else 'Quote is empty or does not match the cited source text')
        super().__init__(f'{question_id}: {citation_id} ({source_type}): {explanation}.')


def citation_registry(payload):
    """One source resolver for prompts, validation, synthesis and audit; no ID guessing."""
    registry = {}
    for key, kind in [('proposal_sources', 'PROPOSAL'), ('passages', 'ATTACHMENT')]:
        for source in payload.get(key, []):
            if source['id'] in registry:
                raise ValueError('Ambiguous evidence source ID: '+source['id'])
            registry[source['id']] = {'source_type': kind, 'source': source}
    return registry


def citation_policy(payload):
    registry = citation_registry(payload)
    return {'proposal_source_ids': [key for key, value in registry.items() if value['source_type']=='PROPOSAL'],
            'attachment_scope': 'Only passage_ids in searches for this question_id.',
            'citation_id_field': 'passage_id accepts either an exact proposal source ID or an assigned attachment passage ID.',
            'quote_rule': 'Exact nonempty substring of that source. Do not invent IDs, change wording or join excerpts.',
            'evidence_boundary': 'A proposal objective or planned measurement does not establish that experimental observations exist.'}


def permitted_file(payload, question_id, file_id):
    """Hard access boundary, distinct from literal retrieval matches."""
    q = next(q for q in payload['questions'] if q['id']==question_id)
    search = next(s for s in payload['searches'] if s['question_id']==question_id)
    return file_id in q['file_ids'] and any(f['file_id']==file_id and
        f['status'] in {'MATCHED_PASSAGES','NO_LITERAL_MATCH'} for f in search['files'])


def files(run, bundle):
    result = []
    if bundle.get('intake'):
        root = (Path(run) / bundle['intake']['manifest_path']).parent
        for f in read_json(root / 'manifest.json')['files']:
            if f['id'] == bundle['compression_scope']['proposal_file_id']: continue
            snapshot_path = (root / f['snapshot_path']).resolve()
            if not snapshot_path.is_relative_to(root.resolve()): raise ValueError('Unsafe attachment snapshot')
            result.append({'id':f['id'], 'name':f['original_name'], 'kind':f['kind'],
                           'protected':f['role']=='REFERENCE_ONLY', 'snapshot':snapshot_path,
                           'sha256':f['sha256'], 'path':str((root/f['raw_path']).resolve())})
    else:
        for f in bundle.get('document_files', []):
            if f['id'] == bundle['compression_scope']['proposal_file_id']: continue
            result.append({'id':f['id'], 'name':f['original_name'], 'kind':'document',
                           'protected':False, 'snapshot':None, 'sha256':f['sha256'], 'path':f['raw_path']})
    return result


def metadata(run, bundle):
    return [{k:f[k] for k in ('id','name','kind','protected')} for f in files(run,bundle)]


def records(snapshot):
    """(locator, text, anchor) per record; the anchor names a spreadsheet or CSV row, else None."""
    kind=snapshot['kind']
    if kind=='document':
        for u in source_units([{'id':'text','text':snapshot['text']}]):
            yield f"characters {u['start_char']}:{u['end_char']}", u['text'], None
    elif kind=='csv':
        first=snapshot['rows'][0] if snapshot['rows'] else []
        for i,row in enumerate(snapshot['rows'],1):
            yield f'row {i}', json.dumps({'first_row_not_verified_header':first,'row_number':i,'values':row},ensure_ascii=False), f'R{i:06d}'
    elif kind=='xlsx':
        for si,sheet in enumerate(snapshot['sheets'],1):
            rows={}
            for cell in sheet['cells']: rows.setdefault(cell['row'],[]).append(cell)
            for n,cells in rows.items():
                yield (f"sheet {sheet['name']} row {n}", json.dumps({'sheet':sheet['name'],'cells':cells},ensure_ascii=False),
                       f'S{si:02d}R{n:06d}')
    elif kind=='json':
        for pointer,value in leaves(snapshot['value']):
            yield pointer, json.dumps({'pointer':pointer,'value':value},ensure_ascii=False), None


TABLE_CONTEXT = 'TITLE_AND_HEADER_ROWS'
MAX_HEAD_ROWS = 8
_NUMBER = re.compile(r'^[\s<>≤≥~≈±+\-−–.,:;/()%×*0-9eE]*[0-9][\s<>≤≥~≈±+\-−–.,:;/()%×*0-9eE]*$')


def table_context(bundle):
    """Compression rules 1.27.0 (CC002 table_context): a spreadsheet row travels with its table's title and
    column-header rows. On 2026-10-09 a citation review saw 'Mean ± SD | 24 ± 17' without the header naming the
    column '24-h AUC/MIC ratio Free drug' and could not confirm the free-drug basis."""
    return evidence_handling(bundle).get('table_context') == TABLE_CONTEXT


def _header_like(cells):
    values = [str(c.get('value')).strip() for c in cells if c.get('value') is not None and str(c.get('value')).strip()]
    return len(values) >= 2 and not any(_NUMBER.match(v) for v in values)


def table_heads(rows):
    """{record index: [record indexes of its title and header rows]} for spreadsheet records. A table is a run
    of consecutive rows of one sheet; its context is its first rows through the last header-like row (two or
    more cells, none numeric) above the record, or its first rows when no header is above it."""
    sheets = {}
    for i, (_, text, anchor) in enumerate(rows):
        if not anchor or 'R' not in anchor:
            continue
        sheets.setdefault(json.loads(text).get('sheet'), []).append((int(anchor.rsplit('R', 1)[1]), i))
    heads = {}
    for entries in sheets.values():
        entries.sort(); blocks = []
        for number, i in entries:
            if blocks and number == blocks[-1][-1][0] + 1: blocks[-1].append((number, i))
            else: blocks.append([(number, i)])
        for block in blocks:
            header = [k for k, (_, i) in enumerate(block) if _header_like(json.loads(rows[i][1]).get('cells', []))]
            for k, (_, i) in enumerate(block):
                above = [h for h in header if h < k]
                end = above[-1] if above else min(k - 1, 2)
                context = list(range(end + 1))
                if len(context) > MAX_HEAD_ROWS:
                    context = context[:2] + context[-(MAX_HEAD_ROWS - 2):]
                if context:
                    heads[i] = [block[c][1] for c in context]
    return heads


def row_passage_ids(bundle):
    """Compression rules 1.23.0: spreadsheet and CSV passage IDs carry the row they hold (F0004_S01R000209),
    because models citing 'row 209' wrote the record index as E000209. Earlier runs keep record-index IDs."""
    return (bundle.get('processing_rules') or {}).get('attachment_passage_ids',{}).get('format')=='SHEET_ROW'


def retrieve(run, bundle, questions):
    registered={f['id']:f for f in files(run,bundle)}
    cache={}; passages={}; searches=[]; by_row=row_passage_ids(bundle); heads={}
    with_heads=by_row and table_context(bundle)
    for question in questions:
        selected=[]; searched=[]
        for fid in question['file_ids']:
            f=registered[fid]
            if f['protected']:
                searched.append({'file_id':fid,'status':'PROTECTED_NOT_READ','locations':[]})
                continue
            if fid not in cache:
                # Integrity errors are engineering failures, never NOT_FOUND answers.
                if file_hash(f['path']) != f['sha256']: raise ValueError('Attachment changed: '+fid)
                snapshot=read_json(f['snapshot']) if f['snapshot'] else parse_file(Path(f['path']))
                cache[fid]=list(records(snapshot))
                if with_heads and snapshot['kind']=='xlsx': heads[fid]=table_heads(cache[fid])
            rows=cache[fid]; terms=[t.casefold() for t in question['search_terms']]
            hits={i for i,(_,text,_) in enumerate(rows) if any(term in text.casefold() for term in terms)}
            # Preserve neighboring context; no arbitrary output-length truncation.
            included={j for i in hits for j in (i-1,i,i+1) if 0<=j<len(rows)}
            table=heads.get(fid,{})
            included=sorted(included|{h for i in included for h in table.get(i,[])})
            pid_of=lambda i: f'{fid}_{rows[i][2]}' if by_row and rows[i][2] else f'{fid}_E{i+1:06d}'
            locations=[]
            for i in included:
                locator,text,anchor=rows[i]
                pid=pid_of(i)
                passages[pid]={'id':pid,'file_id':fid,'name':f['name'],'locator':locator,
                               'text':text,'file_sha256':f['sha256']}
                if table.get(i):
                    passages[pid]['table_header_ids']=[pid_of(h) for h in table[i]]
                selected.append(pid); locations.append(locator)
            searched.append({'file_id':fid,'status':'MATCHED_PASSAGES' if hits else 'NO_LITERAL_MATCH',
                             'locations':locations,'records_scanned':len(rows)})
        searches.append({'question_id':question['id'],'terms':question['search_terms'],
                         'files':searched,'passage_ids':list(dict.fromkeys(selected)),
                         'method':'Literal term search with neighboring records; not proof of semantic absence.'})
    return list(passages.values()),searches


def request_payload(run, bundle, state, stage):
    common={'stage':stage,'schema':SCHEMAS[stage],'proposal_sources':bundle['sources']}
    if stage=='attachment_plan':
        return {**common,'files':metadata(run,bundle),'instructions':'''Identify details not stated or unclear in the primary proposal that may affect its actual planned work.
Return questions MI001, MI002, ... and select relevant registered file IDs and literal search terms.
Materiality must name a specific downstream consequence, not a generic completeness preference.
No fixed checklist requiring every PK quantity. Read the proposal before declaring anything missing.
Do not create searches for details already explicit in the proposal unless a concrete ambiguity or conflict needs checking.
Select only relevant authorized files for each gap. File agents will independently receive their assigned evidence.
Use empty file_ids when no relevant files were provided. Protected files may be identified as deferred,
but will not be read. Information intentionally withheld until validation is needed at validation.
File names are retrieval hints, never scientific evidence. Do not read attachment contents yourself.
An empty questions list is allowed when no material or useful clarification is needed.'''}
    plan=read_json(Path(run)/state['accepted']['attachment_plan']['file'])
    passages,searches=retrieve(run,bundle,plan['questions'])
    if warning_contract(bundle):
        common['schema'] = EVIDENCE_V2
    payload = {**common,'questions':plan['questions'],'passages':passages,'searches':searches,
            'instructions':'''Answer every question exactly once using its permitted passages and the proposal.
FOUND requires an exact citation to a relevant passage; assess whether the evidence actually supports
this project, analyte, species and condition. Do not treat a catalog, filename or published parameter
as evidence that this project owns observations or has permission to reuse fitted values.
Use NOT_FOUND only for information not located in the supplied searched evidence. A literal search
is not exhaustive semantic proof; use SEARCH_INCOMPLETE if the retrieval is inadequate.
Use DEFERRED for protected or intentionally later-stage evidence and CONFLICT for unresolved statements.
Retain uncertainty, explain limits, and never invent values, joins or QC results.
Return one answer per question with its status, statement, reason and exact supporting citations.'''}
    if warning_contract(bundle):
        payload['instructions'] += ('\nUse AMBIGUOUS when located evidence is relevant but does not settle the question '
            '(for example undefined terms or a value without its basis). Keep CONFLICT for contradictory statements.')
    if any('table_header_ids' in x for x in passages):
        payload['instructions'] += ('\nA spreadsheet passage may list table_header_ids: the title and column-header rows of '
            'its table, which are supplied as passages too. Read a row\'s values through those headers. When a finding depends '
            'on what a column means (for example free versus total drug, units, species or study), cite the header row as '
            'well as the row with the value.')
    payload['citation_policy'] = citation_policy(payload)
    policy = bundle['processing_rules'].get('retry_policy', {}).get('citation_repair')
    if policy: payload['citation_repair_policy'] = policy
    return payload


class UnsupportedFindingError(ValueError):
    """A FOUND or CONFLICT answer without citations."""


def citation_defects(p, response, scope_grants=()):
    """Each answer or citation the host cannot verify, in answer order: (answer_index, citation_index or None, error)."""
    questions={q['id']:q for q in p['questions']}; registry=citation_registry(p)
    allowed={s['question_id']:s['passage_ids'] for s in p['searches']}
    grants={(g['question_id'],g['citation_id'],g['quote']) for g in scope_grants}
    # Compression rules 1.28.0 (retry_policy.citation_repair.approved_excerpts): a question synthesis may cite an
    # exact excerpt of a quote whose question assignment the review approved. On 2026-10-09 the PMB synthesis for
    # MI012 kept the first two sentences of an approved three-sentence quote and the run stopped.
    excerpts=p.get('citation_repair_policy',{}).get('approved_excerpts') is True
    approved=lambda qid,cid,quote: (qid,cid,quote) in grants or excerpts and bool(quote.strip()) and any(
        g[0]==qid and g[1]==cid and quote in g[2] for g in grants)
    loose=matching.loose(p)
    exact_ids([a['question_id'] for a in response['answers']], questions, 'Attachment question answers')
    for ai, answer in enumerate(response['answers']):
        if answer['status'] in ('FOUND','CONFLICT') and not answer['citations']:
            yield ai, None, UnsupportedFindingError('Found or conflicting attachment evidence needs exact citations')
        for ci, citation in enumerate(answer['citations']):
            cid=citation['passage_id']; entry=registry.get(cid); qid=answer['question_id']
            kind=entry['source_type'] if entry else 'UNKNOWN'
            scoped = entry is not None and kind=='ATTACHMENT' and permitted_file(p,qid,entry['source']['file_id'])
            reviewed = scoped and approved(qid,cid,citation['quote'])
            if entry is None or (kind=='ATTACHMENT' and cid not in allowed[qid] and not reviewed):
                yield ai, ci, EvidenceCitationError(qid,cid,kind,'OUT_OF_SCOPE')
            elif not matching.contains(entry['source']['text'], citation['quote'], loose):
                yield ai, ci, EvidenceCitationError(qid,cid,kind,'QUOTE_NOT_IN_SOURCE')


def validate(request, response, *, scope_grants=()):
    p=request['payload']; validate_schema(response,p['schema'])
    if response['request_sha256'] != request['request_sha256']: raise ValueError('Stale attachment evidence response')
    if p['stage']=='attachment_plan':
        questions=response['questions']; known={f['id'] for f in p['files']}
        if [q['id'] for q in questions] != [f'MI{i:03}' for i in range(1,len(questions)+1)]:
            raise ValueError('Attachment questions require consecutive MI001 IDs')
        for q in questions:
            if len(q['file_ids'])!=len(set(q['file_ids'])) or not set(q['file_ids'])<=known:
                raise ValueError('Unknown or duplicate selected attachment ID')
            if any(not x.strip() for x in q['search_terms']): raise ValueError('Empty attachment search term')
        return
    for _, _, error in citation_defects(p, response, scope_grants):
        raise error


def view(run, bundle, state):
    if not bundle.get('processing_rules'): return bundle
    if 'attachment_evidence' not in state['accepted']:
        raise ValueError('Complete attachment_plan and attachment_evidence before requirements extraction')
    p=request_payload(run,bundle,state,'attachment_evidence')
    result=read_json(Path(run)/state['accepted']['attachment_evidence']['file'])
    from .citation_repair import verify_proof
    from .engine import make_request
    frozen_request = make_request(run, 'attachment_evidence')
    if frozen_request['request_sha256'] != state['accepted']['attachment_evidence']['request_sha256']:
        raise ValueError('Accepted attachment evidence no longer matches its frozen request')
    proof_path = Path(run)/'audit/attachment_evidence_proof.json'
    expected_proof = state['accepted']['attachment_evidence'].get('citation_proof_sha256')
    if expected_proof and (not proof_path.is_file() or digest(read_json(proof_path))!=expected_proof):
        raise ValueError('Accepted attachment citation proof changed or is missing')
    grants = verify_proof(proof_path, frozen_request, result)
    validate(frozen_request, result, scope_grants=grants)
    selected={c['passage_id'] for a in result['answers'] for c in a['citations']}
    # Compression rules 1.27.0: a cited spreadsheet row brings its table's title and header rows along.
    header_ids={x['id']:x['table_header_ids'] for x in p['passages'] if x.get('table_header_ids')}
    selected|={h for i in list(selected) for h in header_ids.get(i,[])}
    sources=list(bundle['sources'])
    for passage in p['passages']:
        if passage['id'] in selected:
            sources.append({'id':passage['id'],'name':passage['name'],'role':'SUPPORTING_EVIDENCE',
                            'text':passage['text'],'locator':passage['locator'],'file_id':passage['file_id'],
                            'original_sha256':passage['file_sha256'],
                            **({'table_header_ids':[h for h in header_ids[passage['id']] if h in selected]}
                               if passage['id'] in header_ids else {})})
    answers={a['question_id']:a for a in result['answers']}
    searches={s['question_id']:s for s in p['searches']}
    warnings=[]
    for q in p['questions']:
        a=answers[q['id']]
        if q['importance']=='MATERIAL' and a['status']!='FOUND':
            warnings.append({'id':q['id'],'field':q['field'],'importance_reason':q['importance_reason'],
                             'needed_at':q['needed_at'],'downstream_impact':q['downstream_impact'],
                             'requested_information':q['requested_information'],'status':a['status'],
                             'reason':a['reason'],'search':searches[q['id']]})
    # Which proposal question each cited passage answers; sent to models under CC002 1.20.0.
    questions=[{'question_id':q['id'],'field':q['field'],'question':q['question'],'importance':q['importance'],
                'needed_at':q['needed_at'],'status':answers[q['id']]['status'],
                'cited_passage_ids':list(dict.fromkeys(c['passage_id'] for c in answers[q['id']]['citations']))}
               for q in p['questions']]
    return {**bundle,'sources':sources,'source_units':source_units(sources),
            'planning_sources':bundle['planning_sources']+[s for s in sources if s['role']=='SUPPORTING_EVIDENCE'],
            'missing_information_warnings':warnings,'supporting_questions':questions,'reviewed_citation_scope':grants}


def check_warning_retention(context, warnings):
    texts=context['uncertainties']+context['data']['required']
    missing=[w['id'] for w in warnings if not any(f"[{w['id']}]" in t for t in texts)]
    if missing:
        raise ValueError('CC019: Important missing-information warnings omitted from uncertainties/data.required: '+', '.join(missing))


def audit_reports(effective, request, response):
    warnings = effective['missing_information_warnings']
    registry=citation_registry(request['payload'])
    cited_ids=list(dict.fromkeys(c['passage_id'] for a in response['answers'] for c in a['citations']))
    return {
        'missing_information_review.json': {
            'status': 'REVIEW_WARNINGS' if warnings else 'NO_MATERIAL_WARNINGS_IDENTIFIED',
            'request_sha256': request['request_sha256'],
            'warnings': warnings,
            'limitations': ['Searches and model judgments do not prove data absence or scientific adequacy.']},
        'supporting_evidence.json': {
            'reviewed_citation_scope':effective.get('reviewed_citation_scope',[]),
            'sources': [s for s in effective['sources'] if s['role']=='SUPPORTING_EVIDENCE'],
            'citation_sources': [{'id':cid,'source_type':registry[cid]['source_type'],
                                 **{k:v for k,v in registry[cid]['source'].items()
                                    if k in {'name','locator','file_id','file_sha256','original_sha256'}}} for cid in cited_ids],
            'questions': request['payload']['questions'], 'answers': response['answers'],
            'searches': request['payload']['searches'], 'request_sha256': request['request_sha256']}
    }
