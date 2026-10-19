"""Frozen, explicit applicability of the authoritative compression rules to LEAN.

The full source pack stays immutable. No library rule is edited or silently inherited
by a historical run, and a single-run PASS is not workflow qualification.
"""
import copy
from pathlib import Path
from .io import digest,read_json
from .rules import require_rules, _check_general_dependencies, _check_terminology_appendix
from .governance import attach_governance

BINDING = 'FROZEN_SCOPED_PROJECTION_1.0'
RULE_IDS = {'CC001','CC002','CC003','CC004','CC005','CC006','CC007','CC008',
            'CC009','CC011','CC012','CC015','CC016','CC017','CC019'}
RULE_FIELDS = ('id','title','instruction','actions','evidence','on_failure','general_rules',
               'details','source_coverage_requirement','qualification_requirement',
               'pass_meaning','handoff_requirement','human_objective_decision','priority')
REVIEW_CHECKS = ['CC004_objective_fidelity_and_resolution','CC005_all_13_preservation_categories',
                 'CC009_proposition_role_and_evidence_status','CC011_record_and_relation_support',
                 'G004_CC006_CC019_unresolved_information_scope']
AUTHORIZATION = ('User-authorized compression simplification: one joint extraction, one independent full-source '
                 'review, at most one targeted patch and full recheck; data attachment inspection and data '
                 'organization deferred to the downstream Data task; preserve main.json structure; '
                 'explicit 20–30 minute target implemented as a 1500-second execution budget. '
                 'No authorization to weaken source fidelity, permissions, scientific classification or release gates.')

# Paths address original clauses; their exact text and hashes are resolved at freeze time.
OVERRIDES = [
 ('CC002',['/instruction','/actions/0','/actions/1','/actions/2','/actions/3','/actions/4','/evidence','/on_failure','/host_requirement'],
  'Read all proposal and explicit clarification source_units. Do not run attachment_plan, attachment_evidence, '
  'inventory parts or their separate reviews. Attachments are registered only and NOT_SEARCHED. Preserve '
  'questions, limitations, contradictions and consequential proposal facts in canonical records; the independent '
  'review covers every source unit. No data access or interpretation is inferred from file registration.'),
 ('CC004',['/actions/2'],
  'If the overall objective is unclear in the authorized proposal/clarifications, preserve the unresolved status '
  'and request targeted clarification. Attachment search is deferred; do not invent an objective. The unresolved '
  'objective blocks ready publication even if other records pass.'),
 ('CC006',['/instruction','/actions/0','/evidence'],
  'Attachment search is NOT_SEARCHED in this profile. NOT_FOUND refers only to omission from the supplied '
  'proposal/clarifications or source-explicit missingness, never proof of searched or absent attachment data. '
  'Carry deferred data assessment and protected evidence with their honest status; do not fabricate search logs.'),
 ('CC007',['/actions/1'],
  'Keep context.rules empty. Preserve detailed source requirements once in scientific_context items, with their '
  'role, scope, conditions and exact evidence. This is source classification, not formal Project Rules publication.'),
 ('CC008',['/actions/0','/actions/1','/actions/2'],
  'The one joint response creates the short objective/study overview and canonical scientific items directly. '
  'There is no separate inventory to summarize. Detailed facts and requirements live once in scientific_context; '
  'full gaps live once in missing_information with short uncertainty references. data.available/required are empty; '
  'the host registers data.files. All unique meaning and provenance survives this representation change.'),
 ('CC009',['/actions/2','/actions/5'],
  'Canonical scientific items replace inventory retention bookkeeping only. Apply the complete scientific '
  'role, evidence-status and proposition definitions unchanged. Core evidence attribution and scientific '
  'evidence_status are distinct. Inferred questions use potential_questions, not invented source facts or data lists.'),
 ('CC011',['/instruction','/actions/1','/actions/4'],
  'The compact canonical representation has no components, bindings or character-offset arrays. Instead every '
  'scientific item and overview scalar has exact source_id/unit_id/quote evidence in the private sidecar. '
  'Each entire proposition and each method/adoption/relation association must be supported by its cited source '
  'context; co-occurrence is insufficient. Every consequential value, unit, condition and association stays in '
  'published prose and typed relationships. Exact-span validation and independent semantic support review both remain mandatory.'),
 ('CC019',['/instruction','/actions/0','/handoff_requirement/model_response_boundary'],
  'Identify unresolved material questions from proposal/clarifications without inspecting attachments. Preserve '
  'honest NOT_SEARCHED/deferred search scope in gap descriptions; no fabricated searched-file list. Return '
  'structured missing_information once and short MI references in uncertainties. Later scientific gaps do not '
  'block unrelated stages, but unresolved objective/source coverage does block the compression handoff.'),
 ('CC012',['/instruction','/actions/0','/actions/1','/actions/2','/actions/3','/actions/5','/evidence','/host_requirement'],
  'One independent fresh context_review reviews the exact combined candidate against all original source_units. '
  'It jointly performs output-to-source faithfulness, source-to-output completeness, global conflicts, all '
  'CC005 categories, CC009 propositions/roles/statuses and every relationship. No inventory review, branch '
  'receipts or additional review calls are fabricated. Any required failed or unresolved verdict blocks PASS. '
  'After one permitted patch, a fresh full review checks every record and every source unit again.'),
 ('CC015',['/instruction','/actions/1','/actions/2','/actions/5','/on_failure'],
  'Only an explicit REVISE allows at most one targeted patch within this frozen run, followed by a fresh full '
  'independent review. Preserve unchanged records and all prior failures. Strict deterministic protocol '
  'normalization may canonicalize unambiguous evidence pointers or exact failed-target sets with full audit; '
  'it cannot change scientific content or verdicts. No binding dropping, attachment citation repair, repeated '
  'unchanged sampling or automatic extra attempts are enabled. Exhausted or unresolved failures stop.'),
 ('CC017',['/actions/1','/actions/4'],
  'The user explicitly configured a 20–30 minute compression goal. This profile freezes a 1500-second cumulative '
  'execution budget, not a default deadline or content truncation. Joint extraction performs classification; '
  'one independent review checks the complete candidate. No extra classification call is introduced.'),
 ('scientific_extraction',['/instructions/0','/instructions/2','/instructions/4','/instructions/6',
                           '/binding_contract','/proposition_contract/procedure/5'],
  'Interpret inventory item as canonical scientific item and preserve all role/status/proposition semantics. '
  'No mechanical binding/component arrays are generated. The binding contract exact-source, same-analysis, '
  'qualification and no-invented-join principles apply to each record sidecar quote and all values/relationships '
  'in its compact statement. Preserve the full source meaning across any split children and repair incoming '
  'and outgoing scientific IDs; never use a schema shortcut to retain mixed incompatible propositions.')
]


def enabled(bundle):
    return bundle.get('compression_profile',{}).get('effective_rule_binding') == BINDING


def pointer(value,path):
    for key in path.strip('/').split('/'):
        value=value[int(key)] if isinstance(value,list) else value[key]
    return value


def checked_pack(bundle):
    require_rules(bundle);pack=bundle['processing_rules'];rules=pack.get('rules',[])
    ids=[r['id'] for r in rules]
    if len(ids)!=len(set(ids)) or set(ids)!=RULE_IDS:
        raise ValueError('Lean effective rules require every reviewed active CC rule exactly once')
    governance=pack.get('governance',{})
    if {r['id'] for r in governance.get('rules',[])}!={f'G{i:03}' for i in range(1,9)}:
        raise ValueError('Lean effective rules require complete G001-G008 governance')
    _check_general_dependencies(rules,governance)
    cc005=next(r for r in rules if r['id']=='CC005')
    if len(cc005.get('details',{}).get('preserve',{}))!=13:
        raise ValueError('Lean effective rules require all 13 CC005 preservation categories')
    _check_terminology_appendix(cc005['details'],pack['pk_binding_knowledge'])
    science=pack['scientific_extraction']
    for key in ('role_definitions','evidence_status_definitions','proposition_contract','binding_contract','qualification'):
        if not science.get(key):raise ValueError('Missing scientific extraction companion: '+key)
    return pack


def freeze(bundle):
    pack=checked_pack(bundle);sources={r['id']:r for r in pack['rules']}
    sources['scientific_extraction']=pack['scientific_extraction'];overrides=[]
    for source_id,paths,directive in OVERRIDES:
        overrides.append({'source_id':source_id,'clause_paths':paths,
            'source_clause_hashes':{path:digest(pointer(sources[source_id],path)) for path in paths},
            'effective_instruction':directive,'authorization':AUTHORIZATION})
    projected={k:copy.deepcopy(pack[k]) for k in ('version','authority')}
    projected.update(projection='LEAN_SCOPED_PROJECTION',scope={'module':'context_compression','stages':['context','context_review']},
        rules=[{k:copy.deepcopy(r[k]) for k in RULE_FIELDS if k in r} for r in pack['rules']],
        scientific_extraction=copy.deepcopy(pack['scientific_extraction']),
        pk_binding_knowledge=copy.deepcopy(pack['pk_binding_knowledge']))
    return {'id':BINDING,'source_pack_version':pack['version'],'source_pack_sha256':digest(pack),
        'source_rule_sha256':{r['id']:digest(r) for r in pack['rules']},
        'source_companion_sha256':{k:digest(pack[k]) for k in ('governance','scientific_extraction','pk_binding_knowledge')},
        'included_rule_fields':list(RULE_FIELDS),'processing_rules':projected,
        'governance':copy.deepcopy(pack['governance']),'execution_overrides':overrides,
        'source_scope':{'mode':'PROPOSAL_AND_EXPLICIT_CLARIFICATIONS','attachment_search':'NOT_SEARCHED',
                        'attachment_data_organization':'DEFERRED_TO_DATA'},
        'precedence':'Read G first. Original substantive CC clauses remain mandatory. The explicitly mapped '
                     'user-authorized execution_overrides replace only their cited procedural/representation clauses; '
                     'they never override fidelity, scientific meaning, access limits or unresolved-objective gates.',
        'audit_source':'audit/processing_rules.json','qualification':'DEFERRED_INSUFFICIENT_LABELLED_DOCUMENTS'}


def validate(bundle):
    if not enabled(bundle):return
    pack=checked_pack(bundle);binding=bundle.get('lean_effective_rules')
    if not binding or binding['source_pack_sha256']!=digest(pack):
        raise ValueError('Lean effective rule source pack binding mismatch')
    source={r['id']:r for r in pack['rules']};source['scientific_extraction']=pack['scientific_extraction']
    if binding['source_rule_sha256']!={r['id']:digest(r) for r in pack['rules']}:
        raise ValueError('Lean effective rule lineage changed')
    for k in ('governance','scientific_extraction','pk_binding_knowledge'):
        actual=binding['governance'] if k=='governance' else binding['processing_rules'][k]
        if actual!=pack[k] or binding['source_companion_sha256'][k]!=digest(pack[k]):
            raise ValueError('Lean rule companion changed: '+k)
    expected=[{k:copy.deepcopy(r[k]) for k in binding['included_rule_fields'] if k in r} for r in pack['rules']]
    if binding['processing_rules']['rules']!=expected:raise ValueError('Lean inherited rule wording changed')
    for override in binding['execution_overrides']:
        for path in override['clause_paths']:
            if override['source_clause_hashes'][path]!=digest(pointer(source[override['source_id']],path)):
                raise ValueError('Lean procedural override lost its source clause')


def host_input_checks(run,bundle):
    from .engine import require_source_coverage
    if run is None:raise ValueError('Lean rule-bound requests require the run for host coverage provenance')
    state=require_source_coverage(run,bundle)
    intake=bundle.get('intake');reference=None
    if intake:
        manifest=read_json(Path(run)/intake['manifest_path'])
        coverage=manifest.get('coverage',{})
        reference={'manifest_path':intake['manifest_path'],'manifest_sha256':intake['manifest_sha256'],
                   'report_path':coverage.get('report_path'),'report_sha256':coverage.get('report_sha256')}
    return {'selected_proposal_file_id':bundle['compression_scope'].get('proposal_file_id'),
            'authorized_source_ids':bundle['compression_scope']['source_ids'],
            'source_units_sha256':digest(bundle['source_units']),
            'coverage_status':state['status'] if state else 'NOT_ASSESSED',
            'coverage_gate':('NO_INTAKE_COVERAGE_RECORD' if state is None else
                             'NO_DETECTED_UNRESOLVED_GAPS' if state['status'] in
                             {'NO_GAPS_DETECTED','GAPS_RESOLVED_BY_HUMAN'} else 'NOT_ASSESSED'),
            'coverage_state_sha256':digest(state) if state else None,
            'coverage_reference':reference,
            'resolved_gap_ids':[r['gap_id'] for r in state.get('resolutions',[])] if state else [],
            'limitations':(state.get('limitations',[]) if state else [])+[
                'Detector/readability status is not proof of semantic or extraction completeness. '
                'No missing or unassessed objects are certified complete; the model must not claim to have inspected unseen content.']}


def attach(payload,bundle,run=None):
    if not enabled(bundle):return
    validate(bundle);binding=bundle['lean_effective_rules']
    payload['processing_rules']=copy.deepcopy(binding['processing_rules'])
    payload['processing_rules_sha256']=digest(payload['processing_rules'])
    payload['effective_rule_binding']={k:copy.deepcopy(v) for k,v in binding.items() if k not in ('processing_rules','governance')}
    payload['effective_rule_binding_sha256']=digest(binding)
    payload['compression_scope']=copy.deepcopy(bundle['compression_scope'])
    payload['host_input_checks']=host_input_checks(run,bundle)
    payload['instructions']=('Apply the inline processing_rules, complete scientific and PK companions, and all 13 '
        'CC005 preservation categories. Read effective_rule_binding.precedence and its explicit clause overrides: '
        'these rules are processing authority, never source facts or scientific project R rules. '
        'An unresolved overall objective blocks ready publication. A PASS is candidate review only; formal '
        'qualification remains DEFERRED_INSUFFICIENT_LABELLED_DOCUMENTS.\n'+payload['instructions'])
    attach_governance(payload,binding['governance'])


def objective_release_gate(candidate,bundle):
    if not enabled(bundle):return
    objective=candidate['context']['objective'].strip()
    evidence=next(e for e in candidate['evidence'] if e['id']=='/objective')
    if not objective or objective=='NOT_FOUND' or evidence['status']!='EXPLICIT' or not evidence['citations']:
        raise ValueError('CC004: unresolved or unsupported overall objective cannot be published as a ready handoff')
