"""Source-bound requirements, context and planning with fail-closed review gates."""
import copy
import os
from datetime import datetime, timezone
from pathlib import Path
from . import __version__
from .io import read_json, write_json, document, digest, atomic_text, canonical
from .schemas import SCHEMAS, validate_schema
from .validation import context_check, review_check, pipeline_check
from .retention import (WORKFLOW_VERSION, source_units, requirements_check,
                        requirements_review_check, context_coverage_check, source_unit_links)
from .rules import load_rules, attach_rules, require_rules
from . import supporting
from . import scientific
from . import review_records, model_view
from .bindings import options as binding_options

RESOURCE = Path(__file__).parent / "resources"
STAGES = (*supporting.STAGES, "requirements", "requirements_review", "context", "context_review", "pipeline", "pipeline_review")
# parallel_v2 also splits the faithfulness review into parts; parallel_v3 also runs the conflict review alongside.
PARALLEL_REVIEW_MODES = ('parallel_v1', 'parallel_v2', 'parallel_v3')
DEFAULT_REVIEW_MODE = 'parallel_v3'
SCHEMAS.update(supporting.SCHEMAS)
DEFAULT_POLICY = {"exclude_pbpk": True, "human_pk_validation_only": True,
                  "pd_requested": False, "cfr_requested": False,
                  "human_validation_available": False}
DEFAULT_BUDGET = {"content_words": None, "compact_characters": None}


def active_stages(bundle):
    from . import lean_compression
    return lean_compression.STAGES if lean_compression.enabled(bundle) else STAGES


def default_review_mode():
    """CTXCOMP_CONTEXT_REVIEW_MODE=parallel_v2 keeps the conflict review after both branches;
    parallel_v1 also gives new runs a single faithfulness review."""
    return os.getenv('CTXCOMP_CONTEXT_REVIEW_MODE', '').strip() or DEFAULT_REVIEW_MODE


def now():
    return datetime.now(timezone.utc).isoformat()


def init_run(run, proposal=None, clarifications=(), inventory_path=None, policy=None, literature_path=None, budget=None,
             package=None, attachments=(), reference_only=(), proposal_entry=None, opaque_references=False, revision=None,
             context_review_mode=None, context_output_profile='DATA_DEFERRED_1.0', compression_profile=None):
    run = Path(run); context_review_mode = context_review_mode or default_review_mode()
    if run.exists() and any(run.iterdir()):
        raise ValueError("Run directory is not empty; use a new run to preserve previous results")
    intake = None
    document_files = []
    from .handoff import proposal_scope, file_handoff
    if package or attachments:
        from .intake import intake_files
        if package and (proposal or clarifications or attachments):
            raise ValueError('Package mode reads the package itself; do not also provide separate files')
        supplied = ([proposal] if proposal else []) + list(clarifications) + list(attachments)
        intake = intake_files(run / 'intake', package=package, paths=supplied, reference_only=reference_only,
                              opaque_references=opaque_references)
        selector = proposal_entry
        if proposal:
            selector = next(f['id'] for f in intake['manifest']['files']
                            if f['origin'].get('path') == str(Path(proposal).resolve()))
        sources, registry, compression_scope = proposal_scope(run / 'intake', intake, selector)
    else:
        if not proposal:
            raise ValueError('Supply --proposal, --package, or explicit --attachment files')
        sources = [document(proposal, "S1", "PROPOSAL")]
        supporting = [document(p, f"S{i+2}", "CLARIFICATION") for i, p in enumerate(clarifications)]
        for source, path in zip(sources + supporting, [proposal] + list(clarifications)):
            document_files.append({'id': source['id'], 'original_name': source['name'],
                                   'source_role': source['role'],
                                   'raw_path': str(Path(path).resolve()), 'sha256': source['original_sha256']})
        registry = [{'id': s['id'], 'name': s['name'], 'role': 'FILE_REGISTRY',
                     'text': f"Supporting document read: {s['name']}; scientific QC NOT_RUN."} for s in supporting]
        compression_scope = {'mode': 'PROPOSAL_ONLY', 'proposal_file_id': 'S1', 'source_ids': ['S1']}
    inventory = read_json(inventory_path) if inventory_path else []
    if intake:
        if not isinstance(inventory, list):
            raise ValueError('Inventory must be a list')
        inventory = intake['inventory'] + inventory
    if not isinstance(inventory, list) or any(not isinstance(i, dict) or not i.get("id") or not i.get("description") for i in inventory):
        raise ValueError("Inventory must be a list of {id, description, ...}; provide descriptions, not observations")
    if len({i["id"] for i in inventory}) != len(inventory):
        raise ValueError("Duplicate inventory ID")
    from .intake import inventory_sources
    planning_sources = inventory_sources(sources + registry, inventory)
    # Preserve declarations as supplied; do not open data paths or infer QC success.
    chosen_policy = DEFAULT_POLICY | (policy or {})
    if set(chosen_policy) != set(DEFAULT_POLICY) or any(type(v) is not bool for v in chosen_policy.values()):
        raise ValueError("Policy keys must match the five documented boolean flags")
    chosen_budget = DEFAULT_BUDGET | (budget or {})
    if set(chosen_budget) != set(DEFAULT_BUDGET) or any(v is not None and (type(v) is not int or v <= 0) for v in chosen_budget.values()):
        raise ValueError("Budget requires positive integers or null (no limit) for content_words and compact_characters")
    literature = read_json(literature_path or RESOURCE / "literature.json")
    if not isinstance(literature, list) or len({r["id"] for r in literature}) != len(literature):
        raise ValueError("Literature must be a list with unique IDs")
    bundle = {"workflow_version": WORKFLOW_VERSION, "source_units": source_units(sources),
              "sources": sources, "inventory": inventory, "policy": chosen_policy,
              "planning_sources": planning_sources, "compression_scope": compression_scope,
              "document_files": document_files,
              "budget": chosen_budget, "literature": literature,
              "instructions": (RESOURCE / "instructions.md").read_text(encoding="utf-8"),
              "processing_rules": load_rules()}
    from .output_profile import load_profile
    profile = load_profile(context_output_profile)
    if profile:
        bundle['context_output_profile'] = profile
    if revision is not None:
        bundle['revision'] = revision
    if clarifications and intake:
        clarification_paths = {str(Path(p).resolve()) for p in clarifications}
        bundle['explicit_clarification_file_ids'] = [f['id'] for f in intake['manifest']['files']
            if f['origin'].get('path') in clarification_paths]
    from . import lean_compression
    lean_profile = lean_compression.profile(compression_profile)
    if lean_profile:
        bundle['compression_profile'] = lean_profile
        if intake:
            extra = set(bundle.get('explicit_clarification_file_ids', []))
            if any(f['id'] in extra and (f['kind'] != 'document' or f['role'] == 'REFERENCE_ONLY')
                   for f in intake['manifest']['files']):
                raise ValueError('Lean clarification must be an explicitly permitted text document')
            bundle['sources'] += [s for s in intake['sources'] if s.get('file_id') in extra and s['role'] != 'FILE_REGISTRY']
        else:
            bundle['sources'] += supporting
        bundle['source_units'] = source_units(bundle['sources'])
        bundle['compression_scope'] = {**bundle['compression_scope'],
            'mode':'PROPOSAL_AND_EXPLICIT_CLARIFICATIONS', 'source_ids':[s['id'] for s in bundle['sources']]}
        from . import lean_rules
        if lean_rules.enabled(bundle):bundle['lean_effective_rules']=lean_rules.freeze(bundle)
    if context_review_mode not in {'legacy', *PARALLEL_REVIEW_MODES}: raise ValueError('Unknown context review mode')
    if context_review_mode != 'legacy': bundle['context_review_mode'] = context_review_mode
    if intake:
        bundle['intake'] = {'manifest_path': 'intake/manifest.json',
                            'manifest_sha256': intake['manifest']['manifest_sha256']}
    run.mkdir(parents=True, exist_ok=True)
    write_json(run / "inputs.json", bundle)
    write_json(run / "audit/processing_rules.json", bundle['processing_rules'])
    if bundle.get('lean_effective_rules'):
        write_json(run / 'audit/lean_effective_rules.json',bundle['lean_effective_rules'])
    state = {"software_version": __version__, "created_at": now(), "inputs_sha256": digest(bundle), "accepted": {}}
    write_json(run / "state.json", state)
    write_json(run / "audit/file_registry.json", file_handoff(run, bundle, state))
    return {"run": str(run.resolve()), "status": "INITIALIZED", "input_sha256": digest(bundle)}


def load_run(run):
    run = Path(run)
    bundle = read_json(run / "inputs.json")
    state = read_json(run / "state.json")
    if digest(bundle) != state["inputs_sha256"]:
        raise ValueError("Run inputs changed; create a new run. Previous reviews are invalid")
    if bundle.get('processing_rules') and read_json(run / 'audit/processing_rules.json') != bundle['processing_rules']:
        raise ValueError('Frozen processing rules changed; create a new run for rule changes')
    from . import lean_rules
    if lean_rules.enabled(bundle):
        lean_rules.validate(bundle)
        if read_json(run / 'audit/lean_effective_rules.json')!=bundle['lean_effective_rules']:
            raise ValueError('Frozen lean effective rule projection changed')
    if bundle.get('intake'):
        from .intake import verify_intake
        intake_path = (run / bundle['intake']['manifest_path']).resolve(strict=True)
        if not intake_path.is_relative_to(run.resolve()):
            raise ValueError('Unsafe intake manifest path')
        if verify_intake(intake_path)['manifest_sha256'] != bundle['intake']['manifest_sha256']:
            raise ValueError('Intake no longer matches context input snapshot')
    for stage, record in state["accepted"].items():
        if digest(read_json(run / record["file"])) != record["sha256"]:
            raise ValueError(f"Accepted {stage} changed; previous review is invalid")
    if bundle.get("workflow_version") == WORKFLOW_VERSION:
        from .handoff import file_handoff
        if read_json(run / 'audit/file_registry.json') != file_handoff(run, bundle, state):
            raise ValueError('File handoff changed or no longer matches its source/context')
        for stage, alias, key in (("requirements", "critical_requirements.json", "requirements"),):
            if stage in state["accepted"]:
                expected = read_json(run / state["accepted"][stage]["file"])[key]
                if read_json(run / alias) != expected:
                    raise ValueError(f"{alias} changed; previous review is invalid")
    return bundle, state


def coverage_paths(run, bundle):
    """IN001 gaps live in the immutable intake; human resolutions are an append-only sidecar."""
    if not bundle.get('intake'):
        return None
    intake = (Path(run) / bundle['intake']['manifest_path']).parent
    return intake, Path(run) / 'coverage_resolutions.json'


def require_source_coverage(run, bundle):
    """No compression model call while a detected source-content gap is unresolved (IN001/IN008)."""
    paths = coverage_paths(run, bundle)
    if paths:
        from .coverage import require_resolved
        return require_resolved(*paths)


def resolve_coverage(run, gap_ids, reviewer, reason, decision='IRRELEVANT_TO_TASK'):
    run = Path(run)
    bundle, _ = load_run(run)
    paths = coverage_paths(run, bundle)
    if not paths:
        raise ValueError('This run has no file intake; there are no IN001 coverage gaps to resolve')
    from .coverage import resolve
    scope = {'stage': 'context_compression', 'proposal_file_id': bundle['compression_scope'].get('proposal_file_id'),
             'intake_manifest_sha256': bundle['intake']['manifest_sha256']}
    return resolve(*paths, gap_ids, reviewer, reason, decision=decision, scope=scope)


def accepted_response(run, state, stage):
    if stage not in state["accepted"]:
        raise ValueError(f"Stage {stage} must be accepted first")
    return read_json(Path(run) / state["accepted"][stage]["file"])


def make_request(run, stage):
    if stage not in STAGES:
        raise ValueError("Unknown stage")
    run = Path(run)
    bundle, state = load_run(run)
    from . import lean_compression
    if lean_compression.enabled(bundle):
        require_source_coverage(run, bundle)
        return lean_compression.request(run, bundle, state, stage)
    if bundle.get("workflow_version") != WORKFLOW_VERSION:
        raise ValueError("Legacy run uses a different compression scope. Create a new proposal-only run from original inputs; old results remain unchanged")
    require_source_coverage(run, bundle)
    if stage in supporting.STAGES:
        require_rules(bundle)
        if stage == 'attachment_evidence' and 'attachment_plan' not in state['accepted']:
            raise ValueError('Complete attachment_plan before attachment_evidence')
        payload = supporting.request_payload(run, bundle, state, stage)
        attach_rules(payload, bundle['processing_rules'])
        return {'request_sha256': digest(payload), 'payload': payload}
    bundle = supporting.view(run, bundle, state)
    planning = stage in {"pipeline", "pipeline_review"}
    payload = {"stage": stage, "instructions": bundle["instructions"],
               "sources": bundle["planning_sources"] if planning else bundle["sources"],
               "inventory": bundle["inventory"] if planning else [],
               "compression_scope": bundle['compression_scope'],
               "source_units": bundle["source_units"], "workflow_version": WORKFLOW_VERSION,
               "budget": bundle["budget"], "policy": bundle["policy"], "schema": SCHEMAS[stage]}
    if planning and bundle.get('processing_rules', {}).get('governance'):
        from .governance import attach_governance
        attach_governance(payload, bundle['processing_rules']['governance'])
    if bundle.get('processing_rules') and not planning:
        attach_rules(payload, bundle['processing_rules'])
        payload['source_registry'] = [{k:s[k] for k in ('id','name','role','file_id','locator','original_sha256') if k in s}
                                      for s in bundle['sources']]
        payload['missing_information_warnings'] = supporting.model_warnings(bundle)
        if model_view.enabled(payload):
            payload['instructions'] += model_view.INSTRUCTION
        # Stages with per-unit verdicts; the legacy single context review has none.
        unit_verdicts = stage == 'requirements_review' or (
            stage == 'context_review' and bundle.get('context_review_mode') in PARALLEL_REVIEW_MODES)
        if unit_verdicts and supporting.evidence_handling(bundle).get('unit_review'):
            payload['review_source_unit_ids'] = supporting.review_unit_ids(bundle)
        if supporting.evidence_handling(bundle).get('question_links') in supporting.QUESTION_LINKS:
            payload['supporting_questions'] = supporting.model_questions(bundle)
        if any(s.get('table_header_ids') for s in bundle['sources']):
            # Compression rules 1.27.0: cited spreadsheet rows come with their table's title and header rows.
            payload['instructions'] += ('\nA supporting spreadsheet row may list table_header_ids: the title and column-header '
                'rows of its table, also given in ' + ('source_units' if model_view.enabled(payload) else 'sources') + '. Read the row\'s values through those headers; a header row may be '
                'cited as evidence of what a column means.')
        if supporting.warning_contract(bundle):
            payload['instructions'] += ('\nFor every missing_information_warnings item, refer to its [MIxxx] ID in '
                'context.uncertainties or data.required with a short statement of what is missing. The host publishes the '
                'complete structured record (field, status, needed_at, impact, clarification) once in main.json.missing_information; '
                'do not repeat all of its wording. These are review warnings, not proof of absent experiments. '
                'A faithfully retained warning does not itself mean failed compression. Review their retention.')
        else:
            payload['instructions'] += ('\nFor every missing_information_warnings item, retain its [MIxxx] ID, '
                'what is missing, why it matters and needed_at in context.uncertainties or data.required. '
                'These are review warnings, not proof of absent experiments. They may be PROPOSED clarification '
                'checks. A faithfully retained warning does not itself mean failed compression. Review their retention.')
    if stage != "requirements":
        requirements = accepted_response(run, state, "requirements")["requirements"]
        payload["requirements"] = requirements
        payload["requirements_sha256"] = digest(requirements)
        payload["requirements_evidence_audit"] = requirements_check(requirements, bundle["source_units"], binding_options(bundle))
    if stage in {"context", "context_review", "pipeline", "pipeline_review"}:
        review = accepted_response(run, state, "requirements_review")["review"]
        if review["decision"] != "PASS":
            raise ValueError("Requirements review must pass before context generation")
        payload["requirements_review_sha256"] = digest(review)
    if stage in {"context_review", "pipeline", "pipeline_review"}:
        context_response = accepted_response(run, state, "context")
        payload["context"] = context_response["context"]
        payload["context_sha256"] = digest(context_response["context"])
        payload["evidence"] = context_response["evidence"]
        payload["evidence_audit"] = context_check(context_response["context"], context_response["evidence"],
                                                  bundle["sources"], bundle["budget"])[0]
    if stage in {"pipeline", "pipeline_review"}:
        verify_context(run)
        context_review = accepted_response(run, state, "context_review")
        if context_review["review"]["decision"] != "PASS":
            raise ValueError("Context review must pass before planning")
        payload["literature"] = bundle["literature"]
    if stage == "pipeline_review":
        pipeline = accepted_response(run, state, "pipeline")["pipeline"]
        payload["pipeline"] = pipeline
        payload["graph_checks"] = pipeline_check(pipeline, bundle["policy"], bundle["literature"], bundle["inventory"], bundle["planning_sources"])
    previous = run / "feedback" / f"{stage}.json"
    if bundle.get('revision'):
        payload['revision'] = bundle['revision']
        payload['revision_policy'] = ('Revision guidance and historical review are administrative feedback, not scientific evidence. '
            'Re-extract from the current proposal only. Cite current source IDs; do not reuse old IDs without checking them. '
            'Preserve unresolved source conflicts and missing information; guidance cannot create new permissions, thresholds, or facts. '
            'All normal validation and semantic review criteria still apply. A retry does not imply acceptance.')
        if bundle.get('processing_rules'):
            payload['revision_policy'] = payload['revision_policy'].replace(
                'Re-extract from the current proposal only.',
                'Re-extract from the current proposal and permitted supporting evidence.')
    if previous.exists():
        payload["previous_feedback"] = read_json(previous)
        guidance = revision_guidance(run, stage, payload["previous_feedback"])
        if guidance:
            payload['revision_guidance'] = guidance
            payload['instructions'] += ('\nrevision_guidance is a person\'s note on the review in previous_feedback. It is '
                'administrative feedback, not scientific evidence: it cannot add facts, thresholds or permissions. Extract '
                'from the supplied sources and cite them; every normal validation and review still applies.')
    if stage == 'requirements' and supporting.evidence_handling(bundle).get('revision') == 'RECORD_PATCH':
        # Compression rules 1.26.0: a redo after a review revises the reviewed inventory as a patch.
        from . import requirements_revision
        requirements_revision.attach(run, payload)
    if bundle.get('context_review_mode'):
        payload['context_review_mode'] = bundle['context_review_mode']
    if bundle.get('processing_rules', {}).get('project_rule_owner') == 'PROJECT_RULES_AGENT' and not planning:
        payload['schema'] = copy.deepcopy(payload['schema'])
        if stage == 'context':
            payload['schema']['properties']['context']['properties']['rules']['maxItems'] = 0
        if stage == 'requirements':
            payload['schema']['properties']['requirements']['properties']['items']['items']['properties']['kind'] = {'type': 'string', 'enum': ['FACT', 'UNKNOWN']}
        payload['instructions'] += ('\nCompression preserves source meaning, including original obligations, but does not extract or classify a formal project-rule list. '
            'Use FACT for source statements (including what the source requires) and UNKNOWN for explicit unknowns in the internal retention inventory. '
            'Preserve obligations once in appropriate study fields or source-attributed checks, with their conditions and evidence. '
            'Return context.rules as []; do not assign project R numbers. The downstream Project Rules Agent rereads originals and alone publishes project_rules.json.')
    proposition_contract = bundle.get('processing_rules', {}).get('scientific_extraction', {}).get('proposition_contract')
    payload['schema'] = scientific.response_schema(stage, payload['schema'], scientific.enabled(bundle), proposition_contract)
    if scientific.enabled(bundle) and stage in {'context', 'context_review'}:
        compact = bundle['processing_rules']['scientific_extraction'].get('handoff_projection') == 'COMPACT_2.0'
        scientific.attach(payload, requirements, bundle['source_units'], bundle['sources'], compact=compact)
    if stage == 'requirements_review' and 'review_source_unit_ids' in payload:
        # Each unit's links follow from the inventory; stating them lets the review list them exactly,
        # potential questions included.
        links = source_unit_links(requirements, payload['review_source_unit_ids'])
        payload['review_source_unit_links'] = {unit_id: sorted(ids) for unit_id, ids in links.items()}
        fields = payload['schema']['properties']['review']['properties']['source_units']['items']['properties']
        if supporting.evidence_handling(bundle).get('unit_links') == 'HOST_FILLED':
            # Compression rules 1.25.0: the host copies the links in; the model only judges each unit.
            payload['instructions'] += ('\nIn review.source_units, judge each unit against every ID given for it in '
                'review_source_unit_links: every inventory item and potential question whose evidence or source_refs cite '
                'that unit. Return requirement_ids as []; the host fills in exactly those links before validation.')
            fields['requirement_ids'] = {**fields['requirement_ids'],
                'description': 'Return []. The host fills in the IDs listed for this unit in review_source_unit_links.'}
        else:
            payload['instructions'] += ('\nIn review.source_units, requirement_ids for a unit lists exactly the IDs given for it in '
                'review_source_unit_links: every inventory item and potential question whose evidence or source_refs cite that unit, '
                'each once. Judge the unit against all of them.')
            fields['requirement_ids'] = {**fields['requirement_ids'],
                'description': 'Exactly the IDs listed for this unit in review_source_unit_links, inventory items and potential questions alike.'}
    if stage == 'requirements_review' and review_records.enabled(payload):
        payload['instructions'] += review_records.INSTRUCTION
    if stage in {'context', 'context_review'}:
        from .output_profile import attach
        attach(payload, bundle)
    request = {"request_sha256": digest(payload), "payload": payload}
    return request


def revision_guidance(run, stage, feedback):
    """A person's guidance for redoing this stage in the same run, only while it answers the current review."""
    path = Path(run) / 'feedback' / f'{stage}.guidance.json'
    if not path.is_file():
        return None
    record = read_json(path)
    if not record.get('guidance') or record.get('review_sha256') != digest(feedback):
        return None
    return {k: record[k] for k in ('guidance', 'submitted_by', 'at')}


def reopen_for_revision(run, guidance='', submitted_by=''):
    """Redo the stage whose review stopped this run (REVISE or NEEDS_REVIEW), keeping every other accepted stage.

    The candidate's acceptance is removed (REVISE already removed it), so the next run_model call generates it
    again with the review as previous_feedback and any guidance as revision_guidance, then reviews it again."""
    from uuid import uuid4
    run = Path(run)
    bundle, state = load_run(run)
    from . import lean_compression
    if lean_compression.enabled(bundle):
        raise ValueError('Lean revisions are limited to one recorded targeted patch; create a new run for new guidance')
    stopped = read_json(run / 'stopped.json')
    review_stage = stopped.get('stage', '')
    if stopped.get('status') not in {'REVISE', 'NEEDS_REVIEW'} or not review_stage.endswith('_review'):
        raise ValueError('Only a run stopped by a REVISE or NEEDS_REVIEW review can be revised in place')
    base = review_stage.removesuffix('_review')
    if base not in STAGES or review_stage in state['accepted']:
        raise ValueError('The stopped review does not belong to this run state')
    feedback = read_json(run / 'feedback' / f'{base}.json')
    if feedback != read_json(run / stopped['response']).get('review'):
        raise ValueError('Review feedback no longer matches the stopped review')
    record = {'at': now(), 'stage': base, 'review_stage': review_stage, 'decision': stopped['status'],
              'review_sha256': digest(feedback), 'guidance': guidance, 'submitted_by': submitted_by,
              'candidate_acceptance_removed': base in state['accepted'],
              'guidance_is_scientific_evidence': False, 'scientific_approval': False}
    write_json(run / 'audit/revisions' / f'{uuid4().hex}.json', record)
    write_json(run / 'feedback' / f'{base}.guidance.json', record)
    if base in state['accepted']:
        state['accepted'].pop(base)
        write_json(run / 'state.json', state)
    return record


AUTOMATIC_REVISION = 'host:automatic_revision'


def revise_automatically(run, bundle, stage, outcome):
    """Compression rules 1.29.0 (CC002 automatic_revisions): a requirements_review REVISE reopens the inventory for a
    patch revision without waiting for a person, up to the run's frozen limit. True when the run was reopened."""
    handling = supporting.evidence_handling(bundle)
    if outcome.get('status') != 'REVISE' or stage != 'requirements_review' or handling.get('revision') != 'RECORD_PATCH':
        return False
    done = sum(read_json(p).get('submitted_by') == AUTOMATIC_REVISION for p in (Path(run)/'audit/revisions').glob('*.json'))
    if done >= int(handling.get('automatic_revisions', 0)):
        return False
    reopen_for_revision(run, submitted_by=AUTOMATIC_REVISION)
    return True


def rerun_from(run, stage, requested_by=''):
    """Make `stage` and every later stage run again in this run, keeping every earlier accepted stage.

    Earlier answers, reviews and audits stay on disk as history; only their acceptance is removed."""
    from uuid import uuid4
    run = Path(run)
    if stage not in STAGES:
        raise ValueError('Unknown stage')
    bundle, state = load_run(run)
    from . import lean_compression
    if lean_compression.enabled(bundle):
        raise ValueError('Lean candidates cannot be resampled unchanged; create a new run with corrected inputs')
    later = active_stages(bundle)[active_stages(bundle).index(stage):]
    removed = [s for s in later if s in state['accepted']]
    record = {'at': now(), 'stage': stage, 'removed_acceptances': removed, 'requested_by': requested_by,
              'scientific_approval': False}
    write_json(run / 'audit/reruns' / f'{uuid4().hex}.json', record)
    if 'requirements' in later:
        from .requirements_revision import supersede
        supersede(run, {'at': record['at'], 'rerun_from': stage})
    for name in removed:
        state['accepted'].pop(name)
    write_json(run / 'state.json', state)
    if bundle.get('workflow_version') == WORKFLOW_VERSION:
        from .handoff import file_handoff
        write_json(run / 'audit/file_registry.json', file_handoff(run, bundle, state))
    return record


def stage_status(run):
    """Each stage of this run: ACCEPTED (by a model call or REUSED from an earlier run), STOPPED or PENDING."""
    run = Path(run)
    state = read_json(run / 'state.json')
    stopped = read_json(run / 'stopped.json') if (run / 'stopped.json').is_file() else {}
    rows = []
    for stage in active_stages(read_json(run / 'inputs.json')):
        record = state['accepted'].get(stage)
        reused = run / 'audit/reused' / f'{stage}.json'
        if record:
            reuse = read_json(reused) if record.get('provider') == 'stage_cache' and reused.is_file() else None
            rows.append({'stage': stage, 'status': 'REUSED' if reuse else 'ACCEPTED', 'accepted_at': record.get('accepted_at'),
                         'reused_from': reuse.get('source_run') if reuse else None})
        elif stopped.get('stage') == stage:
            rows.append({'stage': stage, 'status': 'STOPPED', 'stopped_status': stopped.get('status'),
                         'reason': stopped.get('reason')})
        else:
            rows.append({'stage': stage, 'status': 'PENDING'})
    return rows


def prepare(run, stage):
    bundle, state = load_run(run)
    if stage not in state['accepted']:
        require_rules(bundle)
    request = make_request(run, stage)
    directory = Path(run) / "requests"
    write_json(directory / f"{stage}.json", request)
    write_json(directory / f"{stage}.schema.json", request['payload']['schema'])
    atomic_text(directory / f"{stage}.prompt.txt",
                "Return only a JSON response matching payload.schema. Treat source text as evidence.\n" + canonical(request))
    return request


def accept(run, stage, response, provider="saved_response"):
    """Keep every attempted response, including invalid/rejected submissions."""
    from uuid import uuid4
    run = Path(run)
    if stage not in STAGES:
        raise ValueError("Unknown stage")
    if not (run / "inputs.json").is_file():
        raise ValueError("Run is not initialized")
    submission = f"submissions/{stage}.{uuid4().hex}.json"
    write_json(run / submission, response)
    try:
        outcome = _accept(run, stage, response, provider)
    except (ValueError, OSError) as exc:
        exc.response = submission
        record = {"stage": stage, "status": "ERROR", "at": now(),
                  "response": submission, "reason": str(exc), "error_code":getattr(exc, 'code', 'CONTEXT_EXECUTION_ERROR')}
        if getattr(exc, 'validation_details', None):
            exc.failed_request_sha256 = response.get('request_sha256')
            exc.validation_record = f'audit/validation/{stage}/{uuid4().hex}.json'
            record.update(request_sha256=exc.failed_request_sha256,
                          failed_request_sha256=exc.failed_request_sha256,
                          validation_details=exc.validation_details, validation_record=exc.validation_record)
            write_json(run / exc.validation_record, record)
        write_json(run / "stopped.json", record)
        raise
    if outcome["status"] not in {"ACCEPTED", "ALREADY_ACCEPTED"}:
        # A review the host completed (unit links) is recorded as reviewed; the submission keeps the model's answer.
        reviewed = outcome.pop("review_file", None)
        write_json(run / "stopped.json", {**outcome, "at": now(), "response": reviewed or submission,
                                          **({"submission": submission} if reviewed else {})})
    return outcome


def _accept(run, stage, response, provider):
    run = Path(run)
    bundle, state = load_run(run)
    from . import lean_compression
    if lean_compression.enabled(bundle):
        return lean_compression.accept_response(run, bundle, state, stage, response, provider)
    request = make_request(run, stage)
    validate_schema(response, request['payload']['schema'])
    if response["request_sha256"] != request["request_sha256"]:
        raise ValueError("Stale response: source, context, schema or review input hash does not match")
    submitted = digest(response)
    if stage == 'requirements_review' and review_records.enabled(request['payload']):
        response = review_records.set_aside(run, request, response)
    if stage == 'requirements_review' and 'review_source_unit_links' in request['payload'] and \
            supporting.evidence_handling(bundle).get('unit_links') == 'HOST_FILLED':
        response = fill_unit_links(run, request, response)
    if stage in state["accepted"]:
        old = accepted_response(run, state, stage)
        if digest(old) == digest(response):
            return {"status": "ALREADY_ACCEPTED", "stage": stage}
        raise ValueError("Accepted stage is immutable. Create a new run for changed inputs or candidates")
    require_rules(bundle)
    if stage not in supporting.STAGES:
        bundle = supporting.view(run, bundle, state)
    checks = {}
    if stage in supporting.STAGES:
        from .citation_repair import verify_proof
        grants = verify_proof(run/'audit/attachment_evidence_proof.json',request,response) if stage=='attachment_evidence' else []
        supporting.validate(request, response,scope_grants=grants)
        checks = {'status': 'VALIDATED', 'rule_pack_sha256': digest(bundle['processing_rules'])}
    elif stage == "requirements":
        from . import requirements_parts, requirements_revision
        if requirements_revision.enabled(request['payload']) and requirements_revision.produced_by_patch(run, request, response):
            # Recheck that the patch was built from this request and the reviewed inventory, and nothing changed since.
            requirements_revision.verify_proof(run, request, response)
        elif requirements_parts.enabled(request['payload']) and requirements_parts.produced_by_parts(run, request, response):
            # Recheck that every part was built from this request and validated, and nothing changed since.
            requirements_parts.verify_proof(run, request, response)
        checks = requirements_check(response["requirements"], bundle["source_units"], binding_options(bundle))
    elif stage == "context":
        supporting.check_warning_retention(response['context'], bundle.get('missing_information_warnings', []))
        audit, metrics = context_check(response["context"], response["evidence"], bundle["sources"], bundle["budget"])
        checks = {"evidence": audit, "length": metrics}
    elif stage == "pipeline":
        checks = pipeline_check(response["pipeline"], bundle["policy"], bundle["literature"], bundle["inventory"], bundle["planning_sources"])
    else:
        base = stage.removesuffix("_review")
        target = accepted_response(run, state, base)[base]
        if stage == "requirements_review":
            checks = requirements_review_check(response["review"], target, bundle["source_units"],
                                               supporting.review_unit_ids(bundle), binding_options(bundle))
            verdict = checks["decision"]
        else:
            verdict = review_check(response["review"], target,
                                   bundle["planning_sources"] if stage == 'pipeline_review' else bundle["sources"], stage)
        if stage == "context_review":
            if bundle.get('context_review_mode') in PARALLEL_REVIEW_MODES:
                from .split_review import verify_proof
                verify_proof(run, request, response)
            original = accepted_response(run, state, "context")
            checks = context_coverage_check(response["review"], request["payload"]["requirements"],
                                           target, original["evidence"], bundle["source_units"])
            write_json(run / "coverage_report.json", checks)
        write_json(run / "audit" / f"{stage}.json", checks)
        if verdict != "PASS":
            review_file = f"reviews/{stage}.{digest(response)[:12]}.json"
            write_json(run / review_file, response)
            write_json(run / "feedback" / f"{base}.json", response["review"])
            if stage == 'requirements_review' and supporting.evidence_handling(bundle).get('revision') == 'RECORD_PATCH':
                from .requirements_revision import keep_reviewed
                keep_reviewed(run, response['review'], accepted_response(run, state, base))
            # An unapproved candidate can be replaced after a semantic REVISE.
            # Keep the original response as history, and remove only its acceptance pointer.
            if verdict == "REVISE":
                state["accepted"].pop(base, None)
                write_json(run / "state.json", state)
            outcome = {"status": verdict, "stage": stage, "reason": "Semantic review requires attention; no handoff published"}
            if digest(response) != submitted:
                outcome["review_file"] = review_file  # reopen_for_revision compares feedback with this record.
            return outcome
    filename = f"accepted/{stage}.{digest(response)[:16]}.json"
    write_json(run / filename, response)
    write_json(run / "audit" / f"{stage}.json", checks)
    state["accepted"][stage] = {"file": filename, "sha256": digest(response), "provider": provider,
                                 "accepted_at": now(), "request_sha256": request["request_sha256"]}
    if stage=='attachment_evidence' and (run/'audit/attachment_evidence_proof.json').is_file():
        state['accepted'][stage]['citation_proof_sha256']=digest(read_json(run/'audit/attachment_evidence_proof.json'))
    if stage == 'context_review' and bundle.get('context_review_mode') in PARALLEL_REVIEW_MODES:
        state['accepted'][stage]['parallel_review_proof_sha256'] = digest(read_json(run/'parallel_review_proof.json'))
    if stage == "requirements":
        write_json(run / "critical_requirements.json", response["requirements"])
    write_json(run / "state.json", state)
    if stage == 'attachment_evidence':
        effective = supporting.view(run, bundle, state)
        for name, report in supporting.audit_reports(effective, request, response).items():
            write_json(run / 'audit' / name, report)
    if stage == "context_review":
        context = accepted_response(run, state, "context")["context"]
        write_json(run / "compressed_context.json", context)
        from .handoff import file_handoff, main_handoff
        write_json(run / "audit/file_registry.json", file_handoff(run, bundle, state))
        main = main_handoff(run, bundle, state)
        if main.get('version') == '3.2':
            reviewed = make_request(run, 'context_review')
            write_json(run / 'audit/scientific_context.json', scientific.audit_record(main, reviewed))
        write_json(run / "handoff/main.json", main)
    if stage == "pipeline_review":
        publish_candidate(run)
    return {"status": "ACCEPTED", "stage": stage}


def fill_unit_links(run, request, response):
    """Compression rules 1.25.0: copy each reviewed unit's links from the request into the review.

    The links follow from the inventory alone, so a model that drops or adds one no longer stops the run.
    Unit IDs and verdicts stay the model's; the submission keeps its original answer."""
    links = request['payload']['review_source_unit_links']
    filled = copy.deepcopy(response); changes = []
    for record in filled['review']['source_units']:
        if record['unit_id'] not in links:
            continue  # An unknown or extra unit still fails the exact source-unit check.
        expected = links[record['unit_id']]
        if record['requirement_ids'] != expected:
            changes.append({'unit_id': record['unit_id'], 'returned': record['requirement_ids'], 'filled': expected})
            record['requirement_ids'] = list(expected)
    write_json(Path(run) / 'audit' / 'requirements_review_links.json', {
        'request_sha256': request['request_sha256'], 'submitted_sha256': digest(response), 'filled_sha256': digest(filled),
        'changed_units': changes, 'scope': 'Bookkeeping links only; verdicts and reasons are unchanged.'})
    return filled


def verify_context(run):
    """Verify a completed B1 without requiring later scientific planning."""
    run = Path(run)
    bundle, state = load_run(run)
    from . import lean_compression
    if lean_compression.enabled(bundle):
        return lean_compression.verify(run, bundle, state)
    bundle = supporting.view(run, bundle, state)
    if bundle.get('processing_rules'):
        evidence_response = accepted_response(run, state, 'attachment_evidence')
        for name, report in supporting.audit_reports(bundle, make_request(run, 'attachment_evidence'), evidence_response).items():
            if read_json(run / 'audit' / name) != report:
                raise ValueError('Supporting evidence audit changed: ' + name)
    if bundle.get("workflow_version") != WORKFLOW_VERSION:
        raise ValueError("Legacy run uses a different compression scope; create a new proposal-only run")
    req = accepted_response(run, state, "requirements")["requirements"]
    reviewed = accepted_response(run, state, "requirements_review")["review"]
    if requirements_review_check(reviewed, req, bundle["source_units"], supporting.review_unit_ids(bundle),
                                 binding_options(bundle))["decision"] != "PASS":
        raise ValueError("Requirements review must pass")
    original = accepted_response(run, state, "context")
    supporting.check_warning_retention(original['context'], bundle.get('missing_information_warnings', []))
    context_check(original["context"], original["evidence"], bundle["sources"], bundle["budget"])
    review = accepted_response(run, state, "context_review")["review"]
    if bundle.get('context_review_mode') in PARALLEL_REVIEW_MODES:
        from .split_review import verify_proof
        proof_hash = verify_proof(run, make_request(run,'context_review'), accepted_response(run,state,'context_review'))
        if state['accepted']['context_review'].get('parallel_review_proof_sha256') != proof_hash:
            raise ValueError('Parallel review proof changed after acceptance')
    if review_check(review, original["context"], bundle["sources"], "context_review") != "PASS":
        raise ValueError("Context review must pass")
    report = context_coverage_check(review, req, original["context"], original["evidence"], bundle["source_units"])
    if read_json(run / "coverage_report.json") != report:
        raise ValueError("Coverage report changed after review")
    if read_json(run / "compressed_context.json") != original["context"]:
        raise ValueError("Compressed context no longer matches locked context")
    from .handoff import main_handoff, verify_main
    published = read_json(run / 'handoff/main.json')
    if published != main_handoff(run, bundle, state):
        raise ValueError('Main handoff changed after review')
    if published.get('version') == '3.2':
        expected_audit = scientific.audit_record(published, make_request(run, 'context_review'))
        if read_json(run/'audit/scientific_context.json') != expected_audit:
            raise ValueError('Scientific audit no longer matches reviewed sources and published main')
    verify_main(published)
    return {"status": "VALID", "context_sha256": digest(original["context"]),
            "handoff_file": str((run / 'handoff/main.json').resolve()),
            "critical_recall": report["critical_recall"], "independent_accuracy": None}


def candidate(run):
    bundle, state = load_run(run)
    if bundle.get("workflow_version") == WORKFLOW_VERSION:
        verify_context(run)
    context = accepted_response(run, state, "context")["context"]
    for s in ("context_review", "pipeline_review"):
        if accepted_response(run, state, s)["review"]["decision"] != "PASS":
            raise ValueError("Both semantic reviews must pass before candidate publication")
    pipeline = copy.deepcopy(accepted_response(run, state, "pipeline")["pipeline"])
    checks = pipeline_check(pipeline, bundle["policy"], bundle["literature"], bundle["inventory"], bundle.get("planning_sources", bundle["sources"]))
    pipeline["connections"] = checks["connections"]
    for block in pipeline["blocks"]:
        block["readiness"] = checks["readiness"][block["id"]]
        block["review"] = {"status": "PENDING_HUMAN_REVIEW"}
    return {"context": context, "pipeline": pipeline,
            "review": {"status": "PENDING_HUMAN_REVIEW", "decision": None, "reason": None}}


def publish_candidate(run):
    run = Path(run)
    result = candidate(run)
    write_json(run / "project_plan.candidate.json", result)
    atomic_text(run / "pipeline.mmd", render_mermaid(result["pipeline"]))
    write_json(run / "evaluation.json", {
        "structural_checks": "PASS", "context_review": "PASS", "pipeline_review": "PASS",
        "faithfulness": None, "retention": None, "preparation_fit": None,
        "score": None, "loss": None,
        "pilot_weights": {"faithfulness": 0.50, "retention": 0.35, "preparation_fit": 0.15},
        "reason": "No independent reference labels or calibrated semantic accuracy evaluation supplied",
        "human_review": "PENDING_HUMAN_REVIEW"})
    text = ["# Research workflow (candidate)", "", "Human review: Pending. No raw-data cleaning, PK fitting or human predictions have been executed.", "",
            "## Compressed context", "", "```json", __import__("json").dumps(result["context"], ensure_ascii=False, indent=2), "```", "",
            "## Workflow", "", "```mermaid", render_mermaid(result["pipeline"]), "```", ""]
    for block in result["pipeline"]["blocks"]:
        text.extend([f"## {block['id']} — {block['title']}", "", block["purpose"], "",
                     f"Method: {block['method']['name']} ({block['method']['origin']})", "",
                     f"Readiness: {block['readiness']['status']}", ""])
        text.extend(f"- {s}" for s in block["instructions"])
        text.extend(["", "Inputs: " + ", ".join(i["file_id"] for i in block["inputs"]),
                     "", "Outputs: " + ", ".join(block["outputs"]), ""])
    bundle, _ = load_run(run)
    text.extend(["## Method references", ""])
    used = {r for b in result["pipeline"]["blocks"] for r in b["method"]["reference_ids"]}
    text.extend(f"- [{r['title']}]({r['url']}) — {r['application']}; {r['limitation']}"
                for r in bundle["literature"] if r["id"] in used)
    atomic_text(run / "REPORT.md", "\n".join(text) + "\n")
    return result


def render_mermaid(pipeline):
    def label(value):
        return value.replace('"', "'").replace("\n", " ").replace("<", "").replace(">", "")
    lines = ["flowchart TD"]
    for b in pipeline["blocks"]:
        lines.append(f'  {b["id"]}["{b["id"]}: {label(b["title"])}"]')
    for e in pipeline["connections"]:
        arrow = "-->" if e["required"] else "-.->"
        lines.append(f'  {e["from"]} {arrow}|"{e["file_id"]}"| {e["to"]}')
    return "\n".join(lines) + "\n"


def verify(run):
    run = Path(run)
    expected = candidate(run)
    actual = read_json(run / "project_plan.candidate.json")
    if digest(expected) != digest(actual):
        raise ValueError("Candidate was modified after semantic review")
    if read_json(run / "compressed_context.json") != expected["context"]:
        raise ValueError("Compressed context no longer matches locked context")
    if (run / "pipeline.mmd").read_text(encoding="utf-8") != render_mermaid(expected["pipeline"]):
        raise ValueError("Flowchart no longer matches candidate; review invalid")
    gate = run / "human_review.json"
    if gate.exists() and read_json(gate)["candidate_sha256"] != digest(expected):
        raise ValueError("Human review is stale")
    if gate.exists():
        record = read_json(gate)
        reviewed = read_json(run / "project_plan.reviewed.json")
        reviewed_expected = copy.deepcopy(expected)
        reviewed_expected["review"] = record
        if reviewed != reviewed_expected:
            raise ValueError("Reviewed handoff no longer matches the human decision and candidate")
    return {"status": "VALID", "candidate_sha256": digest(expected),
            "human_review": read_json(gate)["decision"] if gate.exists() else "PENDING_HUMAN_REVIEW"}


def human_review(run, decision, reviewer, reason):
    if decision not in {"PASS", "FAIL"} or not reviewer.strip():
        raise ValueError("Human decision requires PASS/FAIL and reviewer")
    if decision == "FAIL" and not reason.strip():
        raise ValueError("FAIL requires a reason")
    check = verify(run)
    record = {"decision": decision, "reviewer": reviewer, "reason": reason,
              "candidate_sha256": check["candidate_sha256"], "at": now()}
    reviewed = candidate(run)
    reviewed["review"] = record
    write_json(Path(run) / "project_plan.reviewed.json", reviewed)
    write_json(Path(run) / "human_review.json", record)
    write_json(Path(run) / "reviews" / f"human.{digest(record)[:12]}.json", record)
    return record
