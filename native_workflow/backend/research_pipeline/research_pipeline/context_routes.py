"""Explicit model-stage routes; legacy adapters preserve their complete payloads."""
COMPRESSION = {'attachment_plan','attachment_evidence','requirements','requirements_review',
               'context','context_review','pipeline','pipeline_review',
               'context_faithfulness','context_completeness','context_conflicts'}
DATA = {'DR','DR-access','DC-split','DC-label','DC-review','DP','DH-handoff',
        'REQUIREMENT_PLANNING_ONLY','DIRECT_DR_COVERAGE','NECESSITY_IMPACT_AND_ADVICE_ONLY',
        'NECESSITY_SCOPED_ASSESSMENT','HUMAN_REVIEW_SUMMARY_ONLY'}
REPAIRS = {'schema_repair','binding_repair','attachment_citation_repair'}
EDA = {'EP-plan': 'plan', 'EP-finalize': 'finalize', 'EI-findings': 'findings', 'ER-review': 'review'}
EDA_AGENTS = {'EP', 'EC', 'EV', 'EI', 'ER'}
DIRECT = {'DIRECT_DR_COVERAGE':'coverage','NECESSITY_IMPACT_AND_ADVICE_ONLY':'necessity',
          'NECESSITY_SCOPED_ASSESSMENT':'necessity','HUMAN_REVIEW_SUMMARY_ONLY':'human_summary'}

# These are adapter control envelopes, not words to search in source evidence.
REPAIR_FIELDS = {'original_draft','base_candidate_sha256','schema_errors','repair_tasks',
                 'revision_patch','reviewed_inventory','previous_feedback',
                 'contract_correction','prior_rejected_response','failed_request_ref',
                 'failed_response_ref','repair_context','correction_context'}
CONTROL_ENVELOPES = ('control','execution','task','request','payload')


def reject_repairs(payload):
    """Inspect only known instruction envelopes; never interpret evidence as code."""
    if not isinstance(payload, dict):
        return
    operation = str(payload.get('operation', '')).upper()
    if payload.get('stage') in REPAIRS or REPAIR_FIELDS.intersection(payload) or any(
            word in operation for word in ('PATCH','REPAIR','REVISION','CORRECTION')):
        raise ValueError('Automatic correction/repair calls are disabled at the unified gateway')
    for key in CONTROL_ENVELOPES:
        if isinstance(payload.get(key), dict):
            reject_repairs(payload[key])


def managed(request):
    p=request.get('payload',{}) if isinstance(request,dict) else {}
    pack=p.get('processing_rules')
    compression=isinstance(pack,dict) and pack.get('scope',{}).get('module')=='context_compression'
    return (compression or p.get('stage') == 'RAG-sufficiency' or p.get('stage') in COMPRESSION|DATA|REPAIRS
            or p.get('stage') in EDA or str(p.get('stage', '')).upper().startswith('EDA')
            or str(p.get('stage', '')).split('-', 1)[0] in EDA_AGENTS
            or p.get('stage') in EDA_AGENTS or p.get('agent') in {'DR','DC','DP','DH'}|EDA_AGENTS)


def select(payload):
    reject_repairs(payload)
    stage=payload.get('stage')
    if stage == 'RAG-sufficiency':
        return 'context', 'sufficiency'
    if payload.get('agent') in EDA_AGENTS and stage not in EDA:
        raise ValueError('Unsupported EDA model call: ' + str(stage))
    if stage in EDA:
        return 'eda', EDA[stage]
    if stage == 'HUMAN_REVIEW_SUMMARY_ONLY' and 'analyses' in payload and 'action_decisions' not in payload:
        return 'data', 'human_summary_legacy'
    if stage in DIRECT:
        return 'data',DIRECT[stage]
    if stage=='DR' and payload.get('operation') in {'REQUIREMENT_PLAN_4.0','REQUIREMENT_PLAN_5.0','REQUIREMENT_PLAN_5.1', 'REQUIREMENT_PLAN_6.0'}:
        return 'data','requirements'
    if stage in {'context','context_review'} and payload.get('compression_profile',{}).get('id')=='LEAN_1.0':
        return 'compression','extract' if stage=='context' else 'review'
    if stage in COMPRESSION:
        return 'compression','adapter_'+stage
    if stage in DATA:
        return 'data','adapter_'+stage
    raise ValueError('No ContextBuilder route for stage: '+str(stage))
