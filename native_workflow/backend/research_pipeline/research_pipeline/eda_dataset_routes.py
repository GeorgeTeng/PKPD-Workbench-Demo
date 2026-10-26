"""Explicit dataset destinations for descriptive EDA; no release or fitting authority."""
import copy

ROLES = {'OBSERVATIONS', 'CONTEXT', 'SUPPLEMENTARY'}

INSTRUCTION = (
    'For every dataset_disposition add handoff: destinations (PK, PD, or both), '
    'role (OBSERVATIONS, CONTEXT or SUPPLEMENTARY), purpose and pending_checks. '
    'Use PK for animal concentration-time observations and their qualification context; '
    'PD for infection endpoints, index-response, time-kill, MIC and regimen context. '
    'Binding or genuinely shared study context may serve both with a specific purpose. '
    'Tissue/pathology views are supplementary unless a current modeling question needs them. '
    'Do not silently send unassigned datasets to both branches. A destination is an intake '
    'assignment, not evidence of fit readiness. Preserve source notes, permissions and '
    'unresolved relationships. No human/horse data admission or model launch. '
    'The host sets WAITING_FOR_NEXT_STAGE_PACKAGING and carries the original evidence once.'
)


def build(tables, dispositions, figures=()):
    """Require exactly one explicit, reviewable assignment for each admitted dataset."""
    by_id = {t['dataset_id']: t for t in tables}
    if len(by_id) != len(tables):
        raise ValueError('EDA routing: duplicate source dataset')
    if not isinstance(dispositions, list):
        raise ValueError('EDA routing: explicit dataset dispositions required')
    ids = [d['dataset_id'] for d in dispositions]
    if len(ids) != len(set(ids)) or set(ids) != set(by_id):
        raise ValueError('EDA routing: every admitted dataset must appear exactly once')
    result = []
    for d in sorted(dispositions, key=lambda x: x['dataset_id']):
        h = d.get('handoff', {})
        destinations = h.get('destinations')
        if (not isinstance(destinations, list) or not destinations or
                len(destinations) != len(set(destinations)) or
                not set(destinations) <= {'PK', 'PD'}):
            raise ValueError('EDA routing: explicit PK/PD destination required: ' + d['dataset_id'])
        if h.get('role') not in ROLES or not str(h.get('purpose', '')).strip():
            raise ValueError('EDA routing: role and purpose required: ' + d['dataset_id'])
        checks = h.get('pending_checks')
        if not isinstance(checks, list) or any(not isinstance(c, str) or not c.strip() for c in checks):
            raise ValueError('EDA routing: pending_checks must be explicit strings')
        did = d['dataset_id']; t = by_id[did]
        aid = t.get('analysis_id')
        metadata=t.get('metadata',{})
        if h['role']=='OBSERVATIONS' and (metadata.get('observation_role') is False or metadata.get('role_resolution')=='UNRESOLVED'):
            raise ValueError('EDA routing: contextual or unresolved Data role cannot become model observations: '+did)
        data_destination=metadata.get('role') if metadata.get('observation_role') is True else None
        if data_destination in {'PK','PD'} and data_destination not in destinations:
            raise ValueError('EDA routing: destination contradicts verified Data role: '+did)
        expected = ('PK' if aid in {'A_PK_SOURCE_CURVES', 'A_DIGITIZED_PK_CURVES'} else
                    'PD' if aid in {'A_PD_ENDPOINTS', 'A_INDEX_RESPONSE_PANELS',
                    'A_IN_VITRO_TIME_KILL', 'A_IN_VITRO_REPORTED_SUMMARY'} else None)
        if expected and expected not in destinations:
            raise ValueError('EDA routing: destination contradicts admitted analysis type: ' + did)
        if aid == 'A_CONTEXT_TABLES' and h['role'] == 'OBSERVATIONS':
            raise ValueError('EDA routing: contextual evidence cannot become model observations: ' + did)
        fids = [f['figure_id'] for f in figures
                if did in f.get('dataset_ids', []) or
                any(r.get('dataset_id') == did for r in f.get('plotted_rows', []))]
        result.append(dict(dataset_id=did, title=t.get('title', did),
            destinations=sorted(destinations), role=h['role'], purpose=h['purpose'],
            pending_checks=copy.deepcopy(checks), figure_ids=sorted(set(fids)),
            source_notes_locator={'dataset_id':did, 'field':'notes', 'binding':'source_tables'},
            experimental_unit=t.get('experimental_unit', ''),
            packaging_status='WAITING_FOR_NEXT_STAGE_PACKAGING',
            qualification_status='NOT_ASSESSED_BY_ROUTING', fit_ready=False))
    return dict(version='EDA_DATASET_ROUTING_1', datasets=result,
                human_approval=False, model_execution_started=False,
                source_data_modified=False)


def branch(ledger, name):
    rows = [copy.deepcopy(r) for r in ledger['datasets'] if name in r['destinations']]
    return dict(dataset_ids=[r['dataset_id'] for r in rows if r['role'] == 'OBSERVATIONS'],
        shared_context_dataset_ids=[r['dataset_id'] for r in rows if r['role'] != 'OBSERVATIONS'],
        dataset_routing=rows)


def validate_figure_review(required_ids, decision):
    """Exact current image set; global checkbox alone cannot stand in for per-figure review."""
    rows = decision.get('figure_reviews', [])
    ids = [r.get('figure_id') for r in rows]
    if len(ids) != len(set(ids)) or set(ids) != set(required_ids):
        raise ValueError('EDA handoff: record human review of every current figure')
    if any(r.get('decision') != 'ACCEPT' for r in rows):
        raise ValueError('EDA handoff: unresolved per-figure human review')
