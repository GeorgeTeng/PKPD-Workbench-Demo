"""Render compression review artifacts from the canonical rule files in backend/rules.

Run with --check to detect drift without changing files. No model calls or fits.
"""
import argparse
import json
from pathlib import Path

from ctxcomp.io import digest, read_json
from ctxcomp.rules import intake_agent_contract, load_rules


ROOT = Path(__file__).resolve().parents[2]
INTERFACES = ROOT / 'research_pipeline/docs/interfaces'
DOCS = ROOT / 'context_compression/docs'


def dumps(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + '\n'


def review_data(pack, intake):
    review = read_json(INTERFACES / 'context_compression.review.json')
    rules = {r['id']: r for r in pack['rules']}
    review['version'].update(shared_governance=pack['governance']['version'],
        compression_rules=pack['version'],
        scientific_extraction=pack['scientific_extraction']['version'],
        pk_terminology=pack['pk_binding_knowledge']['version'],
        cc005_details=rules['CC005']['details']['version'],
        compression_agents=pack['agent_contracts']['version'])
    review['output']['fields']['scientific_context'] = ('Main format 3.2: reviewed compact statements, roles, evidence statuses, '
        'method/adoption relationships and pending questions. Original-source bindings, quotes and locators remain '
        'in the private audit; required data-file and formal-rule references remain in main.json.')
    review['workflow'] = [
        'Verify intake, selected proposal and supplied source coverage',
        'Identify the overall scientific objective and targeted evidence gaps',
        'Search relevant permitted attachments',
        'Apply the shared access / retrieval / support checks; review eligible citation defects once before accepting evidence',
        'Extract propositions with separate role/status and source-bound PK relationships',
        'Independently review the inventory against source units',
        'Compress core context and attach the exact scientific_context projection',
        'Review faithfulness and completeness in parallel',
        'Check global conflicts against the same combined handoff',
        'Publish only the unchanged reviewed result after all required checks pass']
    review['rule_order'] = pack['logical_order']
    review['rules'] = {r['id']: r['instruction'] for r in pack['rules']}
    review['shared_rules'] = {r['id']: r['instruction'] for r in pack['governance']['rules']}
    review['general_rule_dependencies'] = {r['id']: r['general_rules'] for r in pack['rules']}
    review['CC005']['terminology_appendix'] = rules['CC005']['details']['terminology_appendix']
    review['CC005']['integrated_review'] = '../../../context_compression/docs/CC005_REVIEW.md'
    review['consolidation'] = pack['consolidation']
    review['proposition_contract'] = pack['scientific_extraction']['proposition_contract']
    review['qualification']['plan_status'] = (
        'Zero unblocked critical semantic errors in the agreed acceptance set is approved. '
        'Remaining evaluation design and thresholds require definition; the full live-model '
        'benchmark is deferred for insufficient labelled documents. No qualification is claimed.')
    review['qualification']['critical_error_gate'] = rules['CC012']['qualification_requirement']['acceptance_plan']
    review['implementation_status']['model_qualification']['status'] = (
        'CRITICAL_CRITERION_APPROVED_LIVE_EVALUATION_AND_HOST_GATE_PENDING')
    review['abc_implementation']['rule_owners'] = pack['consolidation']
    review['full_specifications']['canonical_resources'] = [
        '../../../rules/' + name + '.json'
        for name in ('compression/compression_rules', 'compression/cc005_details', 'compression/compression_agents',
                     'general/workflow_governance', 'compression/scientific_extraction', 'compression/pk_binding_knowledge')]
    review['source_snapshot'].update(
        governance_sha256=digest(pack['governance']),
        compression_runtime_sha256=digest(pack),
        intake_runtime_sha256=digest(intake))
    return review


def general_review(pack):
    governance = pack['governance']
    review = read_json(INTERFACES / 'general_rules.review.json')
    review['version'] = governance['version']
    review['rules'] = {r['id']: {k: r[k] for k in
        ('title', 'instruction', 'actions', 'priority') if k in r}
        for r in governance['rules']}
    review['objective_priority'] = next(
        r['priority_policy'] for r in governance['rules'] if r['id'] == 'G003')
    review['evidence_handling'] = governance['evidence_handling']
    return review


def layer_review(pack):
    review = read_json(INTERFACES / 'rule_layers.review.json')
    governance = pack['governance']
    review['current_state'].update(
        active_shared_rules=[r['id'] for r in governance['rules']],
        compression_rules_version=pack['version'],
        governance_version=governance['version'])
    review['migration_guardrails'][0] = (
        f"Shared governance {governance['version']} and compression {pack['version']} "
        'apply to new requests; historical inputs remain frozen.')
    return review


def shared_ids(pack):
    ids = [r['id'] for r in pack['governance']['rules']]
    return ids[0] + '-' + ids[-1]


def render_overview(pack):
    lines = ['# Compression rules - consolidated review', '',
        f"**CC pack {pack['version']} | 15 active CC rules | shared {shared_ids(pack)} | existing IDs preserved**", '',
        'The A/B/C changes extend existing rules. There is no second competing rule list. '
        'The host supplies complete applicable text and definition profiles to fresh agents.', '',
        '## What changed', '',
        '| Topic | Primary owner | Consolidated requirement |', '|---|---|---|',
        '| A: scientific classification | CC009 | Separate role, evidence status and retention bookkeeping; explicitly adopted assumptions differ from inferred pending questions. |',
        '| Proposition boundaries | CC009 | Split independent results, requirements, metadata, gaps and conflicts before labeling; keep qualifying conditions together. The scientific_extraction proposition contract owns the examples and boundary tests. |',
        '| B: extraction before compression | CC008, CC012 | Review propositions first; final reviewers inspect the core context and the exact typed projection that is published. |',
        '| C: PK binding | CC005 | Preserve all 13 categories; use the mapped terminology appendix and check relationships within the correct analysis. |',
        '| Missing information | CC006, CC019 | Search permitted sources; retain unresolved state, consuming stage, impact and targeted clarification. |',
        '| Source requirements | CC007 | Preserve obligations; only Project Rules Agent publishes formal project rules. |',
        '| Formal qualification | CC012 | Zero unblocked critical errors in the agreed acceptance set; live evaluation remains deferred, not satisfied by code tests. |', '',
        '## Rules in workflow order', '']
    rules = {r['id']: r for r in pack['rules']}
    for phase in pack['logical_order']['groups']:
        lines += ['### ' + phase['phase'], '', '| Rule | Requirement |', '|---|---|']
        for rid in phase['rules']:
            lines.append(f"| **{rid}** - {rules[rid]['title']} | {rules[rid]['instruction']} |")
        lines += ['']
    lines += ['## CC005: one checklist and its terminology appendix', '',
        '[Open the complete integrated CC005 review](CC005_REVIEW.md). It includes all 13 '
        'preservation categories and the eight English terminology tables. Original checklist '
        'clauses are unchanged; the term definitions are stored once and referenced by category.', '',
        '## Removed ambiguity and duplication', '',
        '- Inventory kind FACT/UNKNOWN is bookkeeping. Scientific role FACT/RESULT/etc. and '
        'evidence_status OBSERVED/ESTIMATED/PREDICTED/etc. are separate fields. Core-field '
        'EXPLICIT/PROPOSED/NOT_FOUND attribution is another separate contract.',
        '- The definition profile owns role meanings; CC009 owns their use. CC005 owns '
        'preservation; its appendix provides terms without creating extra requirements.',
        '- Source-rule ownership belongs to CC007. Output placement belongs to CC008. '
        'Citations belong to CC011. Review gates and the formal qualification criterion belong to CC012.',
        '- Generic governance remains ' + shared_ids(pack) + '. CC010 and CC013 retain their historical '
        'move records; CC014 and CC018 retain their merge records. No inherited IDs are renumbered.', '',
        '## Efficient correction and runtime policy', '',
        '- Keep concise outputs without dropping consequential content; no default hard '
        'output-length cap or model-call timeout. Preserve five-minute local-process heartbeats and event timing.',
        '- A/B/C reuse existing extraction/review calls. No new classification call is introduced.',
        '- G004/G007 separate access permission, retrieval coverage and claim support throughout the workflow. '
        'Automatic correction requires a stage-specific executable adapter; sharing the rule alone does not enable one.',
        '- Compression can send eligible defects to one fresh citation reviewer. Only supplied authorized evidence is used; '
        'the unchanged answer, source restrictions and later semantic gates remain binding. Original and corrected artifacts stay in the audit.',
        '- Stop on a failed mandatory check. An explicit same-run retry can reuse unchanged, '
        'validated branches with matching bindings. A changed candidate needs all final reviews again; '
        'changed sources or rules require a new run. Do not resample unchanged failed semantics for PASS.', '',
        '## Implementation limits', '',
        'Scoped rule delivery, typed extraction contracts, exact-projection publication and existing '
        'review gates are active for new runs. The broad source-completeness detector, dedicated '
        'objective gate, full structured missing-information migration and formal live-model '
        'qualification gate retain their documented pending status. This consolidation does not implement them.', '',
        'The approved zero-critical-error criterion is limited to an agreed acceptance set. '
        'There are insufficient labelled documents for the full benchmark; code tests establish '
        'contract behavior, not reliable semantic detection by a live model.', '',
        '## Editable and generated artifacts', '',
        '- Edit canonical rule files in `rules/general/`, `rules/intake/` and `rules/compression/`.',
        '- Regenerate with `research_pipeline/scripts/export_compression_rules_review.py`; '
        '`--check` detects stale exports without writing.',
        '- Human JSON: `research_pipeline/docs/interfaces/context_compression.review.json`.',
        '- Complete runtime JSON: `research_pipeline/docs/interfaces/context_compression.runtime.json`.',
        '- New runs snapshot the new pack. Historical runs and approvals are not rewritten.', '']
    return '\n'.join(lines)


def render_cc005(pack):
    rule = next(r for r in pack['rules'] if r['id'] == 'CC005')
    details = rule['details']
    profile = pack['pk_binding_knowledge']
    groups = {g['id']: g for g in profile['groups']}
    lines = ['# CC005 - Scientific preservation and PK terminology', '',
        f"**CC pack {pack['version']} | checklist {details['version']} | terminology {profile['version']}**", '',
        '## How the merged checklist works', '',
        'First check the applicable preservation categories below, then consult their mapped '
        'PK term groups. A term match cannot prove a scientific relationship. A missing term '
        'does not authorize dropping source content. An empty mapping does not remove a category.', '',
        'CC009 owns role/evidence classification; CC011 owns source citations; CC012 owns review '
        'and release. The glossary does not select a model, fill data, convert units or impose '
        'scientific acceptance thresholds.', '',
        '## 1. Mandatory preservation categories', '']
    for i, (category, clauses) in enumerate(details['preserve'].items(), 1):
        lines += [f"### {i}. {category.replace('_', ' ').capitalize()}", '']
        lines += ['- ' + clause for clause in clauses]
        linked = details['terminology_appendix']['categories'][category]
        lines += ['', 'PK appendix: ' + (', '.join(f"{ref} ({groups[ref]['topic']})" for ref in linked)
                  if linked else 'Use these source-preservation clauses and supporting metadata; no dedicated PK term group') + '.', '']
    lines += ['## 2. Compact supporting information', '', profile['supporting_metadata'], '']
    lines += ['- ' + item for item in profile['data_qualifiers']]
    lines += ['', '## 3. PK terminology appendix', '',
        'Terms in a row are related, not interchangeable. Only declared aliases map alternative '
        'names; source-defined symbols need the original definition. CORE means foundational '
        'terminology, not required fields in every proposal. CONDITIONAL groups apply when relevant.', '']
    references = {r['id']: r for r in profile['references']}
    for group in profile['groups']:
        lines += [f"### {group['id']}. {group['topic']} ({group['level']})", '',
                  '| Concept | Terms | Distinction / binding check |', '|---|---|---|']
        for concept in group['concepts']:
            terms = ', '.join(concept['terms'])
            if concept.get('aliases'):
                terms += '; aliases: ' + ', '.join(f'{a} = {b}' for a, b in concept['aliases'].items())
            if concept.get('symbols'):
                terms += '; source-defined symbols: ' + ', '.join(concept['symbols'])
            lines.append(f"| {concept['name']} | {terms} | {concept['check']} |")
        lines += ['', 'References: ' + ', '.join(f"[{ref}]({references[ref]['url']})" for ref in group['references']) + '.', '']
    lines += ['The [terminology reading record](PK_TERMINOLOGY_REVIEW.md#literature-reading-record) '
              'states which abstracts, sections and documentation were inspected. These references '
              'support terminology; they do not validate this compression algorithm.', '',
              '## 4. Boundaries and review criteria', '']
    lines += ['- ' + clause for clause in details['boundaries'] + details['review_criteria']]
    lines += ['', 'The canonical checklist is `cc005_details.json`; the canonical terminology '
              'is `pk_binding_knowledge.json`. The runtime sends one copy of the terminology profile '
              'to assigned agents. This combined review is generated from both.', '']
    return '\n'.join(lines)


def artifacts():
    pack = load_rules()
    intake = intake_agent_contract()
    if intake['governance'] != pack['governance']:
        raise ValueError('Governance changed while creating rule-review exports')
    return {
        INTERFACES / 'workflow_governance.json': dumps(pack['governance']),
        INTERFACES / 'general_rules.review.json': dumps(general_review(pack)),
        INTERFACES / 'file_intake.runtime.json': dumps(intake),
        INTERFACES / 'rule_layers.review.json': dumps(layer_review(pack)),
        INTERFACES / 'context_compression.runtime.json': dumps(pack),
        INTERFACES / 'context_compression.review.json': dumps(review_data(pack, intake)),
        DOCS / 'COMPRESSION_RULES_REVIEW.md': render_overview(pack),
        DOCS / 'CC005_REVIEW.md': render_cc005(pack),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    stale = []
    rendered = artifacts()
    for path, text in rendered.items():
        if args.check:
            if not path.exists() or path.read_text(encoding='utf-8') != text:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8', newline='\n')
    if stale:
        print('Stale rule-review exports:\n' + '\n'.join(stale))
        return 1
    print('Compression rule-review exports are current.' if args.check
          else f'Exported {len(rendered)} shared/compression rule-review artifacts.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
