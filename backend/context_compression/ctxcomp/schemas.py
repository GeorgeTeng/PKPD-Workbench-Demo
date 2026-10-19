"""Explicit schemas; audit/provenance stay outside the compact handoff."""
import copy
from jsonschema import Draft202012Validator
from .bindings import CONTRACT as BINDING_CONTRACT


def obj(**properties):
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


S = {"type": "string", "minLength": 1}
TEXT = {"type": "string"}
BOOL = {"type": "boolean"}


def enum(*values):
    return {"type": "string", "enum": list(values)}


def arr(items=S, minimum=0):
    return {"type": "array", "items": items, "minItems": minimum}


CONTEXT = obj(
    version={"const": "3.0", "type": "string"}, objective=S,
    study=obj(drug=S, regimen=S, population=S, system=S, measurements=S, methods=S),
    data=obj(available=arr(), required=arr()),
    rules=arr(), checks=arr(), uncertainties=arr())

# One downstream document: unchanged 3.0 scientific fields, plus attachment
# contracts in data.files. Evidence, request hashes and model logs stay internal.
ATTACHMENT = obj(id=S, name=S, path=S, sha256={"type": "string", "pattern": "^[0-9a-f]{64}$"},
                 kind=enum('document', 'csv', 'xlsx', 'json'),
                 role=enum('PROPOSAL', 'DATA_CANDIDATE', 'MODEL_CATALOG', 'REFERENCE_ONLY', 'SUPPORTING_DOCUMENT'),
                 receivers=arr(S, 1), read_status=enum('READ_COMPLETE', 'BYTES_READ_ONLY'), qc_status=enum('NOT_RUN'),
                 fit_ready={"const": False, "type": "boolean"})
ATTACHMENT['allOf'] = [{
    'if': {'properties': {'read_status': {'const': 'BYTES_READ_ONLY'}}},
    'then': {'properties': {'role': {'const': 'REFERENCE_ONLY'},
                            'receivers': {'const': ['validation']}}}}]
# Optional: handoffs published before 2026-10-08 carry no intake snapshot.
ATTACHMENT['properties'].update(snapshot_path=S, snapshot_sha256={"type": "string", "pattern": "^[0-9a-f]{64}$"})
MAIN = copy.deepcopy(CONTEXT)
MAIN['properties']['data']['properties']['files'] = arr(ATTACHMENT)
MAIN['properties']['data']['required'].append('files')
MAIN['properties']['rules'] = arr({"type": "string", "pattern": r'^R[0-9]{3,}: \S'})
MAIN['properties']['rule_publication'] = {'const': 'PROJECT_RULES_AGENT', 'type': 'string'}
MAIN['properties']['project_rules_ref'] = obj(path=S, sha256={'type': 'string', 'pattern': '^[0-9a-f]{64}$'})
MAIN['properties']['demo_context_review_ref'] = copy.deepcopy(MAIN['properties']['project_rules_ref'])
# CC019 structured warnings: one record per issue, published by the host from reviewed records.
MISSING_INFORMATION = obj(
    schema_version={'const': '1.0', 'type': 'string'},
    items=arr(obj(id={'type': 'string', 'pattern': '^MI[0-9]{3,}$'}, field=S,
                  status=enum('NOT_FOUND', 'SEARCH_INCOMPLETE', 'DEFERRED', 'AMBIGUOUS', 'CONFLICT'),
                  needed_at=enum('context', 'adequacy', 'prepare', 'eda', 'pk', 'index', 'human_pk', 'validation', 'clinical'),
                  impact=S, why_it_matters=S, clarification=S, resolution_status=enum('OPEN'))))
MAIN['properties']['missing_information'] = MISSING_INFORMATION
MAIN['allOf'] = [
    {'if': {'required': ['rule_publication']}, 'then': {'properties': {'rules': {'maxItems': 0}}}},
    {'if': {'required': ['project_rules_ref']}, 'then': {'required': ['rule_publication']}}]

EVIDENCE_PATH = {**S, "description": (
    "JSON pointer relative to the context object, excluding /version. "
    "Use /objective, /study/drug or /data/available/0, without a /context prefix. "
    "Every scalar leaf needs exactly one evidence record.")}
REVIEW_PATH = {**S, "description": (
    "JSON pointer relative to the reviewed object, not the response envelope. "
    "For context_review use /objective or /study/drug; for pipeline_review use "
    "/blocks/0 or /data_files/0. Do not prepend /context or /pipeline.")}

EVIDENCE = obj(path=EVIDENCE_PATH, status=enum("EXPLICIT", "PROPOSED", "NOT_FOUND"),
               source_id=TEXT, quote=TEXT, reason=S)

ATTRIBUTES = obj(species=S, matrix=S, basis=S, time_window=S, units=S, record_level=S)
CONDITIONS = enum("ALWAYS", "PD_REQUESTED", "CFR_REQUESTED", "HUMAN_VALIDATION_AVAILABLE")

INPUT = obj(file_id=S, required=BOOL, expects=ATTRIBUTES)
FILE = obj(id=S, description=S, kind=enum("DOCUMENT", "DATASET", "MODEL", "REPORT"),
           availability=enum("LOCAL_DOCUMENT", "DECLARED", "MISSING", "TO_GENERATE"),
           path=S, producer=S, role=enum("CONTEXT", "DEVELOPMENT", "VALIDATION"),
           attributes=ATTRIBUTES, required_fields=arr())
BLOCK = obj(id=S, title=S, purpose=S,
            category=enum("PLANNING", "PREPARATION", "ANALYSIS", "VALIDATION", "SYNTHESIS"),
            method=obj(name=S, origin=enum("PROPOSAL", "SUGGESTED"), reference_ids=arr()),
            instructions=arr(S, 1), inputs=arr(INPUT), outputs=arr(S, 1),
            constraints=arr(), completion_criteria=arr(S, 1), when=CONDITIONS)
PIPELINE = obj(blocks=arr(BLOCK, 1), data_files=arr(FILE, 1))

REVIEW = obj(
    decision=enum("PASS", "REVISE", "NEEDS_REVIEW"),
    reviewer=S, review_type=enum("MODEL_REVIEW", "ASSISTANT_INTERNAL_REVIEW", "EXPERT_REVIEW"),
    claims=arr(obj(path=REVIEW_PATH, verdict=enum("PRESERVED", "MISSING", "ALTERED", "UNRESOLVED"),
                   reason=S), 1),
    retention=arr(obj(source_id=S, quote=S,
                      verdict=enum("PRESERVED", "MISSING", "ALTERED", "UNRESOLVED"),
                      critical=BOOL, reason=S), 1),
    critical_errors=arr(), limitations=arr(S, 1))

# Source-side obligations are audited separately; the compact CONTEXT is unchanged.
VERDICT = enum("PRESERVED", "MISSING", "ALTERED", "UNRESOLVED")
SPAN = obj(source_id=S, unit_id=S, quote=S)
REQUIREMENT = obj(
    id=S, kind=enum("FACT", "RULE", "UNKNOWN"), statement=S,
    critical=BOOL, rationale=S, downstream_effect=S,
    selection=obj(explicit=BOOL, applicable=BOOL, technical=BOOL, material=BOOL),
    components=arr(obj(id=S, role=enum("FACT", "SCOPE", "PRECONDITION", "TRIGGER",
                                     "ACTION", "LIMITATION", "UNKNOWN"),
                       text=S, evidence=arr(SPAN, 1)), 1))
REQUIREMENTS = obj(version={"type": "string", "const": "1.0"}, items=arr(REQUIREMENT, 1))
REQUIREMENTS_REVIEW = obj(
    decision=enum("PASS", "REVISE", "NEEDS_REVIEW"), reviewer=S,
    review_type=enum("MODEL_REVIEW", "ASSISTANT_INTERNAL_REVIEW", "EXPERT_REVIEW"),
    items=arr(obj(requirement_id=S, verdict=VERDICT, reason=S), 1),
    source_units=arr(obj(unit_id=S, requirement_ids=arr(),
                         verdict=VERDICT, reason=S), 1),
    critical_errors=arr(), limitations=arr(S, 1))
TARGET_SPAN = obj(path=EVIDENCE_PATH, quote=S)
COVERAGE = obj(
    requirement_id=S, verdict=VERDICT, reason=S,
    components=arr(obj(component_id=S, verdict=VERDICT,
                       targets=arr(TARGET_SPAN), reason=S), 1))
ATOMIC_CLAIM = obj(id=S, path=EVIDENCE_PATH, quote=S, statement=S,
                   status=enum("EXPLICIT", "PROPOSED", "NOT_FOUND"),
                   evidence=arr(SPAN), verdict=VERDICT, reason=S)
CONTEXT_REVIEW = obj(**REVIEW["properties"],
    atomic_claims=arr(ATOMIC_CLAIM, 1),
    decomposition=arr(obj(path=EVIDENCE_PATH, claim_ids=arr(S, 1),
                          verdict=VERDICT, reason=S), 1),
    coverage=arr(COVERAGE, 1))

SCHEMAS = {
    "requirements": obj(request_sha256=S, requirements=REQUIREMENTS),
    "requirements_review": obj(request_sha256=S, review=REQUIREMENTS_REVIEW),
    "context": obj(request_sha256=S, context=CONTEXT, evidence=arr(EVIDENCE, 1)),
    "context_review": obj(request_sha256=S, review=CONTEXT_REVIEW),
    "pipeline": obj(request_sha256=S, pipeline=PIPELINE),
    "pipeline_review": obj(request_sha256=S, review=REVIEW),
}


def validate_schema(value, schema):
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: str(e.path))
    if errors:
        raise ValueError("; ".join(f"/{'/'.join(map(str, e.path))}: {e.message}" for e in errors[:8]))


# A/B/C is a versioned extension. Historical 1.0 inventories and 3.0 handoffs
# remain readable; new requests explicitly require the extension.
SCIENCE_BINDING = obj(
    field=enum('drug_analyte', 'species', 'study', 'experiment', 'analysis',
               'population', 'subject', 'experimental_unit', 'record_level',
               'matrix', 'exposure_basis', 'dose', 'dose_basis', 'route',
               'regimen', 'time_window', 'endpoint', 'comparator', 'pathogen',
               'mic', 'binding_fraction', 'parameter', 'value', 'units',
               'statistic', 'missingness', 'condition', 'negation', 'exception'),
    value={**S, 'description':BINDING_CONTRACT['value_definition']},
    component_ids={**arr(S, 1), 'description':BINDING_CONTRACT['component_definition']})
SCIENCE = obj(
    role=enum('FACT', 'RESULT', 'HYPOTHESIS', 'ASSUMPTION', 'METHOD',
              'IMPLICATION', 'OBJECTIVE', 'REQUIREMENT', 'OTHER', 'UNRESOLVED'),
    evidence_status=enum('OBSERVED', 'ESTIMATED', 'PREDICTED', 'SOURCE_REPORTED',
                         'ASSUMED', 'NOT_APPLICABLE', 'NOT_FOUND', 'UNRESOLVED'),
    method_refs=arr(), bindings=arr(SCIENCE_BINDING),
    adoption_relations=arr(obj(target_id=S, used_for=S, conditions=arr(), component_ids=arr(S, 1))),
    relations=arr(obj(type=enum('USES', 'TESTS', 'SUPPORTS', 'CONTRADICTS', 'INTERPRETS'),
                      target_id=S, component_ids=arr(S, 1))))
POTENTIAL_QUESTION = obj(id=S, statement=S, reason=S,
    origin={'type': 'string', 'const': 'MODEL_INFERENCE'},
    status={'type': 'string', 'const': 'PENDING_CONFIRMATION'},
    needed_at=S, impact=S, source_refs=arr(SPAN, 1))
REQUIREMENT['properties']['science'] = SCIENCE
REQUIREMENTS['properties']['version'] = enum('1.0', '1.1')
REQUIREMENTS['properties']['potential_questions'] = arr(POTENTIAL_QUESTION)
REQUIREMENTS['allOf'] = [{'if': {'properties': {'version': {'const': '1.1'}}},
    'then': {'required': ['potential_questions'], 'properties': {'items': {
        'items': {'required': ['science']}}}}}]
SCIENCE_BRANCH_CHECK = obj(id=S, verdict=VERDICT, reason=S)
SCIENCE_FINAL_CHECK = obj(id=S, faithfulness=VERDICT, completeness=VERDICT, reason=S)
CONTEXT_REVIEW['properties']['scientific_checks'] = arr(SCIENCE_FINAL_CHECK)

SCIENCE_LOCATOR = obj(component_id=S, source_id=S, unit_id=S,
                      start_char={'type': 'integer', 'minimum': 0},
                      end_char={'type': 'integer', 'minimum': 1})
SCIENCE_HANDOFF = obj(version={'type': 'string', 'const': '1.0'},
    items=arr(obj(id=S, statement=S, science=SCIENCE, source_refs=arr(SCIENCE_LOCATOR, 1))),
    potential_questions=arr(obj(id=S, statement=S, reason=S,
        origin={'type': 'string', 'const': 'MODEL_INFERENCE'},
        status={'type': 'string', 'const': 'PENDING_CONFIRMATION'},
        needed_at=S, impact=S, source_refs=arr(SCIENCE_LOCATOR, 1))),
    sources=arr(obj(id=S, file_id=S, name=S, role=S, locator=S, original_sha256=S)))
COMPACT_SCIENCE = copy.deepcopy(SCIENCE)
COMPACT_SCIENCE['properties'].pop('bindings')
COMPACT_SCIENCE['required'].remove('bindings')
for relation_name in ('relations', 'adoption_relations'):
    relation = COMPACT_SCIENCE['properties'][relation_name]['items']
    relation['properties'].pop('component_ids')
    relation['required'].remove('component_ids')
COMPACT_QUESTION = copy.deepcopy(POTENTIAL_QUESTION)
COMPACT_QUESTION['properties'].pop('source_refs')
COMPACT_QUESTION['required'].remove('source_refs')
COMPACT_SCIENCE_HANDOFF = obj(version={'type':'string', 'const':'2.0'},
    items=arr(obj(id=S, statement=S, science=COMPACT_SCIENCE)),
    potential_questions=arr(COMPACT_QUESTION))
MAIN['properties']['version'] = enum('3.0', '3.1', '3.2')
MAIN['properties']['scientific_context'] = {'oneOf':[SCIENCE_HANDOFF, COMPACT_SCIENCE_HANDOFF]}
MAIN['allOf'].extend([
    {'if': {'properties': {'version': {'const': '3.1'}}},
     'then': {'required': ['scientific_context'], 'properties': {'scientific_context':SCIENCE_HANDOFF}}},
    {'if': {'properties': {'version': {'const': '3.2'}}},
     'then': {'required': ['scientific_context'], 'properties': {'scientific_context':COMPACT_SCIENCE_HANDOFF}}},
    {'if': {'required': ['scientific_context']},
     'then': {'properties': {'version': enum('3.1', '3.2')}}}])
