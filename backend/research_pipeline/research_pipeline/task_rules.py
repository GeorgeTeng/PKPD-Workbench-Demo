"""Source-traceable rule projection. Rule numbers never determine routing.

This is a conservative, deterministic scope classifier, not scientific approval.
Unknown clauses are exposed for review rather than broadcast to every agent.
The approved source stays immutable; audit records retain excluded clauses too.
"""
import copy
import re
from ctxcomp.io import digest

VERSION = '1.2'
STAGES = {'animal_pk', 'human_pk', 'index', 'clinical', 'prepare', 'eda'}
BRANCH_STAGES = {'pk': {'animal_pk', 'human_pk'}, 'index': {'index'},
                 'clinical': {'clinical'}, 'pk_longitudinal': {'animal_pk'},
                 'pkpd_index': {'index'}, 'pk_translation': {'human_pk'}}


def hit(pattern, text):
    return bool(re.search(pattern, text, re.I))


def drug_context(main):
    value = main.get('study', {}).get('drug', main.get('drug', 'NOT_FOUND'))
    if isinstance(value, dict):
        value = value.get('name') or value.get('active_moiety') or 'NOT_FOUND'
    return str(value)


def drug_label(main):
    return re.split(r'\s+is\s+|;|\n', drug_context(main), maxsplit=1)[0].strip()


def entries(main):
    for i, value in enumerate(main.get('rules', [])):
        item = value if isinstance(value, dict) else {'text': str(value)}
        text = str(item.get('text', item.get('requirement', '')))
        match = re.match(r'^(R\d+):\s*', text)
        if match and item.get('id') and item['id'] != match[1]:
            raise ValueError('G001: Structured rule ID conflicts with its text prefix')
        yield {'id': item.get('id') or (match[1] if match else 'rule_' + str(i)),
               'context_path': item.get('context_path', f'/rules/{i}'),
               'source_text': item.get('source_text', text),
               'body': text[match.end():] if match else text,
               'explicit_stages': item.get('stages') if not item.get('projection_version') else None, 'original': item}


def owner(text):
    """Whole-rule scopes keep an index's generic AIC/CI sentences with index."""
    if hit(r'PD qualification|all three PD indices|qualify an index|current PK/PD index comparison|dose-feasibility endpoint', text):
        return {'index', 'clinical'}
    if hit(r'^Human PK validation|^Report all eligible human patients|^Validation must replay|^Failed validation|^After PK validation|^For PTA|^Preserve MIC bins|virtual subjects', text):
        return {'clinical'}
    if hit(r'^No automatic dose escalation|^Analyze first .*steady.state', text):
        return {'human_pk', 'clinical'}
    if hit(r'^Admit only converged|^Cross.validation may leave out an animal', text):
        return {'animal_pk', 'human_pk'}
    return None


def clause_scope(text, parent):
    if parent is not None:
        return parent, 'Explicit task of the source rule'
    if hit(r'cannot tune animal models|fitted human parameters.*(?:tune|animal)', text):
        return {'animal_pk', 'human_pk'}, 'Protect animal fitting and translation from human outcome leakage'
    if hit(r'freeze models and predictions', text):
        return {'human_pk', 'clinical'}, 'Prediction freeze and validation boundary'
    if hit(r'validation failure|human PK agreement|population PTA|MIC distribution|PD targets.*PTA', text):
        return {'clinical'}, 'Human validation, PD target or PTA work'
    if hit(r'prespecified feasibility|not universal regulatory|project choices', text):
        return STAGES, 'Project thresholds must not be presented as universal standards'
    if hit(r'benchmark|published fitted|references support|primary.analysis inputs|primary starting values', text):
        return STAGES, 'Source permissions constrain every dependent analysis'
    if hit(r'published experimental|model library|model.*parameters|translational objective|matching the drug|model and parameter.source permissions', text):
        return STAGES, 'Use only project-qualified evidence and methods'
    if hit(r'preserve|do not invent|not individual animals|source boundar|keep original units|separate routes|every conversion|record.level data dictionary|each block must declare|source units|whole.lung.*ELF|activity converts|unknown fields|binding|bioavailability|BLQ|assay.limit|interindividual|successful fit|human review before fitting|supersedes earlier', text):
        return STAGES, 'Data integrity, applicable input definitions or execution control'
    if hit(r'convergen|identifiab|\bCL/F\b|\bV/F\b|compartment|animal.*PK|\bPK fits?\b', text):
        return {'animal_pk', 'human_pk'}, 'PK model estimation and diagnostics'
    if hit(r'\bEmax\b|\bHill\b|PD indices|index discrimination|matched.*MIC|exposure.response', text):
        return {'index'}, 'Exposure-response/index analysis'
    return set(), 'Unclassified: explicit task scope is required before execution'


def project_rules(main, target, datasets=None):
    reviewed_pack = main.get('project_rules_ref') or main.get('rule_projection', {}).get('project_rules_ref')
    if reviewed_pack:
        from .project_rule_agent import project
        source_ids = None
        if datasets is not None:
            source_ids = set()
            for dataset in datasets:
                metadata = dataset.get('metadata', dataset)
                if not isinstance(metadata, dict): continue
                for item in [metadata, metadata.get('source_table', {})]:
                    for key in ['source_id', 'study_id', 'id']:
                        if item.get(key): source_ids.add(str(item[key]))
        task_ids = [t['id'] for t in main['tasks']] if 'tasks' in main else None
        result = project(reviewed_pack, target, task_ids=task_ids, source_ids=source_ids)
        result['drug'] = drug_context(main)
        return result
    if main.get('rule_publication') == 'PROJECT_RULES_AGENT':
        raise ValueError('Project Rules Agent publication is required; compression is not a rule source')
    requested = BRANCH_STAGES.get(target, {target})
    if not requested <= STAGES:
        raise ValueError('Unknown rule destination: ' + target)
    selected, audit = [], []
    unresolved = copy.deepcopy(main.get('rule_projection', {}).get('unresolved', []))
    drug = drug_label(main)
    source_rules = list(entries(main))
    ids = [r['id'] for r in source_rules]
    if len(ids) != len(set(ids)):
        raise ValueError('G001: Duplicate inherited rule IDs; inspect the source artifact instead of renumbering')
    for rule in source_rules:
        body = rule['body']
        # Resolve an example-study prohibition without treating its drug as the
        # current medicine. This does not relax any independent permission rule.
        example = re.search(r'without importing the (.+?) model or its parameters', body, re.I)
        normalized = body
        change = None
        if example:
            normalized = (f'Use the current proposal\'s translational objective and project-qualified model library for {drug}. '
                'Reference-study models and parameters require drug, analyte, route, study-design and data compatibility review; '
                'matching the drug alone does not authorize transfer. Apply the current project\'s model and parameter-source permissions.')
            change = {'type': 'REFERENCE_EXAMPLE_TO_PROJECT_CONTEXT', 'reference_drug': example[1],
                      'target_drug': drug, 'permissions_relaxed': False}
        parent = owner(body)
        clauses = [normalized] if change else re.split(r'(?<=[.!?])\s+(?=[A-Z])', body)
        keep, decisions = [], []
        for number, clause in enumerate(clauses):
            scopes, reason = (STAGES, 'Drug-aware reference applicability; all source permissions retained') if change else clause_scope(clause, parent)
            effective = clause
            if requested == {'animal_pk'}:
                if 'Human baseline covariates may define the target population;' in clause:
                    effective = 'Human concentrations and fitted human parameters cannot tune animal models or scaling.'
                if 'A successful fit is not predictive validation;' in clause:
                    scopes = STAGES
                    effective = clause.split(';')[0] + '.'
                if '; measurement error is not interindividual PK variability' in clause:
                    scopes = STAGES
                    effective = 'Measurement error is not interindividual PK variability.'
                if 'Each block must declare' in clause:
                    effective = clause.replace('response window, matched MIC, ', '')
                if 'Guideline doses and published validation methods inform design;' in clause:
                    effective = 'Model-selection thresholds are project choices, not universal regulatory criteria.'
                if 'The prespecified feasibility rules are not universal regulatory thresholds.' == clause:
                    effective = ''  # The following task-specific sentence carries this constraint.
                if 'Published experimental observations' in clause:
                    effective = effective.replace('measured binding, guideline dose ranges and', 'measured binding and')
                if 'References support design and data provenance only;' in clause:
                    effective = effective.replace('their fitted results and preferred indices', 'their fitted results')
            if rule['explicit_stages'] is not None:
                scopes = set(rule['explicit_stages'])
                if not scopes <= STAGES:
                    scopes = set()
                reason = 'Explicit structured rule scope'
            applicable = bool(scopes & requested)
            # A named source qualification belongs only to its actual source.
            source_ids = re.findall(r'\bS\d{2,}\b', clause)
            if applicable and datasets is not None and source_ids:
                def source_metadata(d):
                    embedded = d.get('metadata')
                    d = embedded if isinstance(embedded, dict) and not embedded.get('path') else d
                    if not isinstance(d, dict):
                        return ''
                    table = d.get('source_table', {})
                    return ' '.join(str(d.get(k, '')) for k in ['source_id','study_id','source_title']) + ' ' + ' '.join(
                        str(table.get(k, '')) for k in ['id','source_id','study_id','title'])
                evidence = ' '.join(source_metadata(d) for d in datasets)
                if not any(re.search(r'\b'+re.escape(s)+r'\b', evidence, re.I) for s in source_ids):
                    applicable = False
                    reason = 'Named source is not among this task\'s assigned metadata'
            # Activity/potency factors are drug-specific facts, never templates.
            conversion = re.match(r'(.+?) activity converts', clause, re.I)
            if applicable and conversion and not hit(r'\b'+re.escape(conversion[1])+r'\b', drug_context(main)):
                applicable = False
                reason = 'Drug-specific conversion does not match the current drug declaration'
            decisions.append({'clause': number, 'source_quote': clause if not change else body,
                'effective_text': effective, 'stages': sorted(scopes), 'included': applicable, 'reason': reason})
            if not scopes:
                unresolved.append({'id': rule['id'], 'context_path': rule['context_path'], 'quote': clause,
                                   'reason': reason})
            if applicable and effective:
                keep.append(effective)
        if keep:
            selected.append({'id': rule['id'], 'context_path': rule['context_path'],
                'text': rule['id'] + ': ' + ' '.join(keep), 'stages': sorted(requested),
                'projection_version': VERSION})
        audit.append({'id': rule['id'], 'context_path': rule['context_path'],
            'source_text': rule['source_text'], 'normalization': change,
            'clauses': decisions, 'included': bool(keep)})
    return {'version': VERSION, 'target': target, 'drug': drug_context(main), 'rules': selected,
            'source_context_sha256': digest(main),
            'audit': audit, 'unresolved': unresolved, 'scientific_approval': False,
            'method': 'SOURCE_CLAUSE_SCOPE_WITH_EXPLICIT_UNKNOWN_REVIEW',
            'source_rule_count': len(audit), 'selected_rule_count': len(selected)}


def scoped_context(context, target):
    """Materializable view over an immutable routed context, not a new approval."""
    result = copy.deepcopy(context)
    projection = project_rules(context, target, context.get('data_files'))
    result['rules'] = projection['rules']
    result['rule_projection'] = {k: v for k, v in projection.items() if k not in {'audit', 'rules'}}
    if target == 'animal_pk':
        def human_prediction_task(t):
            if hit(r'^\s*human\b', str(t.get('species', ''))):
                return True
            if t.get('species'):
                return False
            return hit(r'^(?:Can .* be translated|Translate|Predict|Simulate|Scale).*\bhuman\b', str(t.get('question', '')))
        result['tasks'] = [t for t in context.get('tasks', []) if not human_prediction_task(t)]
        ids = {t['id'] for t in result['tasks']}
        result['task_requirements'] = [r for r in context.get('task_requirements', []) if r.get('task_id') in ids]
        result['clinical_questions'] = {k: v for k, v in context.get('clinical_questions', {}).items()
            if k not in {'target_population', 'translation_assumptions', 'regimen_constraints'}}
    return result, projection
