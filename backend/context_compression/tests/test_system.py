import copy
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

from ctxcomp.engine import (DEFAULT_POLICY, RESOURCE, accept, candidate, human_review,
                            init_run, load_run, make_request, prepare, verify)
from ctxcomp.io import canonical, digest, document, leaves, loads, read_json, write_json
from ctxcomp.validation import context_check, pipeline_check, review_check
from ctxcomp.providers import codex_generate, run_model
from rule_versions import rules_1_30

EXAMPLES = Path(__file__).parents[1] / "examples"
ASSETS = EXAMPLES / "current_research"
spec = importlib.util.spec_from_file_location("replay_demo", EXAMPLES / "replay_demo.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


@pytest.fixture
def completed(tmp_path):
    root = tmp_path / "研究 run"
    demo.replay(root)
    return root


@pytest.fixture
def graph_inputs():
    return (read_json(ASSETS / "pipeline.json"), read_json(ASSETS / "policy.json"),
            read_json(RESOURCE / "literature.json"), [],
            [document(ASSETS / "proposal.md", "S1", "PROPOSAL")])


@pytest.mark.parametrize("text", ['{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}'])
def test_strict_json_rejects_invalid(text):
    with pytest.raises(ValueError):
        loads(text)


def test_bom_json_supported():
    assert loads('\ufeff{"missing":"NOT_FOUND"}') == {"missing": "NOT_FOUND"}


def test_completed_run_keeps_compact_schema_and_null_scores(completed):
    result = read_json(completed / "project_plan.candidate.json")
    assert set(result) == {"context", "pipeline", "review"}
    assert set(result["context"]) == {"version", "objective", "study", "data", "rules", "checks", "uncertainties"}
    assert verify(completed)["human_review"] == "PENDING_HUMAN_REVIEW"
    assert read_json(completed / "evaluation.json")["score"] is None
    assert read_json(completed / "evaluation.json")["loss"] is None
    assert all("evidence" not in b for b in result["pipeline"]["blocks"])
    handoff = read_json(completed / 'audit/file_registry.json')
    assert handoff['status'] == 'READY_FOR_DATA_PREPARATION'
    assert handoff['context']['sha256'] == digest(result['context'])
    assert handoff['downstream']['fit_release'] == 'BLOCKED_UNTIL_DATA_QC_AND_HUMAN_REVIEW'
    main = read_json(completed / 'handoff/main.json')
    assert set(main) == set(result['context']) | {'rule_publication', 'scientific_context', 'missing_information'}
    assert main['missing_information']['schema_version'] == '1.0'
    assert all(set(w) == {'id', 'field', 'status', 'needed_at', 'impact', 'why_it_matters', 'clarification', 'resolution_status'}
               for w in main['missing_information']['items'])
    assert main['version'] == '3.2'
    assert main['objective'] == result['context']['objective']
    assert main['study'] == result['context']['study']
    assert main['rules'] == result['context']['rules'] == []
    assert main['rule_publication'] == 'PROJECT_RULES_AGENT'
    assert 'handoff_sha256' not in main
    assert list((completed / 'handoff').iterdir()) == [completed / 'handoff/main.json']


def test_unknown_remains_unknown(completed):
    context = read_json(completed / "compressed_context.json")
    assert context["study"]["regimen"] == "NOT_FOUND"
    assert context["study"]["measurements"] == "NOT_FOUND"


@pytest.mark.parametrize("target", ["inputs.json", "compressed_context.json", "project_plan.candidate.json", "handoff/main.json"])
def test_modified_inputs_or_handoffs_invalidate_review(completed, target):
    value = read_json(completed / target)
    value["tampered"] = True
    write_json(completed / target, value)
    with pytest.raises(ValueError):
        verify(completed)


def test_changed_accepted_context_detected(completed):
    state = read_json(completed / "state.json")
    path = completed / state["accepted"]["context"]["file"]
    value = read_json(path)
    value["context"]["checks"][0] = "Use PBPK"
    write_json(path, value)
    with pytest.raises(ValueError, match="changed"):
        load_run(completed)


def test_flowchart_is_bound_to_candidate(completed):
    with (completed / "pipeline.mmd").open("a", encoding="utf-8") as stream:
        stream.write("FAKE --> B3\n")
    with pytest.raises(ValueError, match="Flowchart"):
        verify(completed)


def test_stale_response_rejected_without_overwriting_output(completed):
    saved = read_json(completed / "saved_responses/context.json")
    saved["request_sha256"] = "wrong"
    before = (completed / "compressed_context.json").read_bytes()
    with pytest.raises(ValueError, match="Stale"):
        accept(completed, "context", saved)
    assert before == (completed / "compressed_context.json").read_bytes()


def test_stage_order_enforced(tmp_path):
    run = tmp_path / "new"
    init_run(run, ASSETS / "proposal.md", context_review_mode='legacy')
    with pytest.raises(ValueError, match="requirements"):
        prepare(run, "pipeline")


def test_nonempty_run_preserved(completed):
    with pytest.raises(ValueError, match="not empty"):
        init_run(completed, ASSETS / "proposal.md", context_review_mode='legacy')


@pytest.mark.parametrize("suffix", [".csv", ".xlsx", ".zip", ".json"])
def test_raw_data_are_not_ingested(tmp_path, suffix):
    path = tmp_path / ("observations" + suffix)
    path.write_text("subject,time,concentration\nprivate observation", encoding="utf-8")
    with pytest.raises(ValueError, match="Raw data"):
        document(path, "S1", "PROPOSAL")


def test_inventory_does_not_open_observation_path(tmp_path):
    inv = tmp_path / "inventory.json"
    write_json(inv, [{"id": "PK", "description": "Declared observations", "path": "Z:/unread/private.csv"}])
    run = tmp_path / "run"
    init_run(run, ASSETS / "proposal.md", inventory_path=inv, context_review_mode='legacy')
    assert load_run(run)[0]["inventory"][0]["path"] == "Z:/unread/private.csv"


def test_false_verbatim_evidence_rejected(completed):
    bundle, _ = load_run(completed)
    saved = read_json(completed / "saved_responses/context.json")
    saved["evidence"][0]["quote"] = "There were exactly 18 dogs."
    with pytest.raises(ValueError, match="verbatim"):
        context_check(saved["context"], saved["evidence"], bundle["sources"], bundle["budget"])


def test_missing_evidence_coverage_rejected(completed):
    bundle, _ = load_run(completed)
    saved = read_json(completed / "saved_responses/context.json")
    with pytest.raises(ValueError, match="Missing evidence"):
        context_check(saved["context"], saved["evidence"][1:], bundle["sources"], bundle["budget"])


def test_suggested_drug_cannot_become_project_fact(completed):
    bundle, _ = load_run(completed)
    saved = read_json(completed / "saved_responses/context.json")
    item = next(e for e in saved["evidence"] if e["path"] == "/study/drug")
    item["status"] = "PROPOSED"
    with pytest.raises(ValueError, match="project facts"):
        context_check(saved["context"], saved["evidence"], bundle["sources"], bundle["budget"])


def test_length_budget_is_enforced(completed):
    bundle, _ = load_run(completed)
    saved = read_json(completed / "saved_responses/context.json")
    with pytest.raises(ValueError, match="budget"):
        context_check(saved["context"], saved["evidence"], bundle["sources"], {"content_words": 1, "compact_characters": 2400})


def test_default_length_limits_are_disabled_but_counts_remain(tmp_path):
    text = ' '.join(['source'] * 500)
    proposal = tmp_path / 'long.md'
    proposal.write_text(text, encoding='utf-8')
    run = tmp_path / 'run'
    init_run(run, proposal, context_review_mode='legacy')
    bundle, _ = load_run(run)
    assert bundle['budget'] == {'content_words': None, 'compact_characters': None}
    context = {'version': '3.0', 'objective': text,
               'study': {key: 'NOT_FOUND' for key in ('drug','regimen','population','system','measurements','methods')},
               'data': {'available': [], 'required': []}, 'rules': [], 'checks': [], 'uncertainties': []}
    evidence = [{'path': path, 'status': 'EXPLICIT' if path == '/objective' else 'NOT_FOUND',
                 'source_id': 'S1' if path == '/objective' else '',
                 'quote': text if path == '/objective' else '', 'reason': 'Source-bound test.'}
                for path, value in leaves(context) if path != '/version']
    _, metrics = context_check(context, evidence, bundle['sources'], bundle['budget'])
    assert metrics['content_words'] > 220 and metrics['compact_characters'] > 2400
    evidence[0]['quote'] = 'This is not present in the source.'
    with pytest.raises(ValueError, match='verbatim'):
        context_check(context, evidence, bundle['sources'], bundle['budget'])


@pytest.mark.parametrize('invalid', [0, -1, True, 'unlimited', 1.5])
def test_invalid_optional_limit_is_rejected(tmp_path, invalid):
    with pytest.raises(ValueError, match='positive integers or null'):
        init_run(tmp_path / 'run', ASSETS / 'proposal.md', budget={'content_words': invalid}, context_review_mode='legacy')


def test_character_limit_can_still_be_explicitly_enabled(completed):
    bundle, _ = load_run(completed)
    saved = read_json(completed / 'saved_responses/context.json')
    with pytest.raises(ValueError, match='compact_characters budget'):
        context_check(saved['context'], saved['evidence'], bundle['sources'],
                      {'content_words': None, 'compact_characters': 1})


def test_altered_negation_cannot_have_pass_review(completed):
    bundle, _ = load_run(completed)
    review = read_json(completed / "saved_responses/context_review.json")["review"]
    review["claims"][0]["verdict"] = "ALTERED"
    with pytest.raises(ValueError, match="PASS contradicts"):
        review_check(review, read_json(completed / "compressed_context.json"), bundle["sources"], "context_review")


def test_incomplete_review_rejected(completed):
    bundle, _ = load_run(completed)
    review = read_json(completed / "saved_responses/context_review.json")["review"]
    review["claims"].pop()
    with pytest.raises(ValueError, match="every"):
        review_check(review, read_json(completed / "compressed_context.json"), bundle["sources"], "context_review")


def test_graph_auto_connections_and_independent_branches(graph_inputs):
    result = pipeline_check(*graph_inputs)
    assert any(e["from"] == "B5" and e["to"] == "B7" and e["file_id"] == "HUMAN_PK" for e in result["connections"])
    assert result["readiness"]["B9"]["status"] == "CONDITIONAL_PENDING"
    assert "HUMAN_HOLDOUT" not in result["readiness"]["B5"]["blocking_files"]
    assert result["readiness"]["B1"]["status"] == "READY_TO_START"


def test_disabled_pd_does_not_remove_pk_plan(graph_inputs):
    graph_inputs[1]["pd_requested"] = False
    result = pipeline_check(*graph_inputs)
    assert result["readiness"]["B6"]["status"] == "CONDITIONAL_PENDING"
    assert result["readiness"]["B7"]["status"] == "CONDITIONAL_PENDING"
    assert result["readiness"]["B5"]["status"] != "CONDITIONAL_PENDING"


def test_missing_pd_does_not_block_pk_when_pk_inputs_declared(graph_inputs):
    pipeline, policy, literature, inventory, sources = graph_inputs
    for fid in ("ANIMAL_RAW", "TARGET_SPEC"):
        next(f for f in pipeline["data_files"] if f["id"] == fid)["availability"] = "DECLARED"
        inventory.append({"id": fid, "description": "Only a declaration; not data QC"})
    result = pipeline_check(pipeline, policy, literature, inventory, sources)
    assert result["readiness"]["B5"]["status"] == "WAITING_UPSTREAM"
    assert result["readiness"]["B6"]["status"] == "BLOCKED_MISSING_INPUT"
    assert result["readiness"]["B2"]["status"] == "WAITING_UPSTREAM"


def test_duplicate_producer_rejected(graph_inputs):
    graph_inputs[0]["blocks"][1]["outputs"].append("CONTEXT")
    with pytest.raises(ValueError, match="multiply"):
        pipeline_check(*graph_inputs)


def test_cycle_rejected(graph_inputs):
    pipeline = graph_inputs[0]
    pipeline["blocks"][0]["inputs"].append(copy.deepcopy(pipeline["blocks"][-1]["inputs"][0]))
    with pytest.raises(ValueError, match="cycle"):
        pipeline_check(*graph_inputs)


def test_human_holdout_cannot_leak_into_scaling(graph_inputs):
    pipeline = graph_inputs[0]
    pipeline["blocks"][4]["inputs"].append(copy.deepcopy(pipeline["blocks"][8]["inputs"][1]))
    with pytest.raises(ValueError, match="Validation observations"):
        pipeline_check(*graph_inputs)


def test_total_free_mismatch_rejected(graph_inputs):
    pipeline = graph_inputs[0]
    next(f for f in pipeline["data_files"] if f["id"] == "HUMAN_PK")["attributes"]["basis"] = "total"
    next(i for i in pipeline["blocks"][6]["inputs"] if i["file_id"] == "HUMAN_PK")["expects"]["basis"] = "free"
    with pytest.raises(ValueError, match="Incompatible basis"):
        pipeline_check(*graph_inputs)


def test_pbpk_exclusion(graph_inputs):
    graph_inputs[0]["blocks"][4]["method"]["name"] = "PBPK translation"
    with pytest.raises(ValueError, match="PBPK"):
        pipeline_check(*graph_inputs)


def test_untraceable_reference_rejected(graph_inputs):
    graph_inputs[0]["blocks"][0]["method"]["reference_ids"] = ["INVENTED2026"]
    with pytest.raises(ValueError, match="unknown literature"):
        pipeline_check(*graph_inputs)


def test_declared_data_requires_inventory(graph_inputs):
    next(f for f in graph_inputs[0]["data_files"] if f["id"] == "ANIMAL_RAW")["availability"] = "DECLARED"
    with pytest.raises(ValueError, match="inventory"):
        pipeline_check(*graph_inputs)


@pytest.mark.parametrize("path", ["../outside.json", "C:/private/result.json", "/tmp/result.json", "C:relative.json"])
def test_unsafe_future_output_path_rejected(graph_inputs, path):
    next(f for f in graph_inputs[0]["data_files"] if f["id"] == "CONTEXT")["path"] = path
    with pytest.raises(ValueError, match="relative"):
        pipeline_check(*graph_inputs)


def test_fail_requires_human_reason(completed):
    with pytest.raises(ValueError, match="reason"):
        human_review(completed, "FAIL", "test reviewer", "")
    human_review(completed, "FAIL", "test reviewer", "Example test rejection")
    assert verify(completed)["human_review"] == "FAIL"


def test_pass_requires_no_fabricated_independent_scores(completed):
    human_review(completed, "PASS", "test reviewer", "Test only")
    assert verify(completed)["human_review"] == "PASS"
    assert read_json(completed / "evaluation.json")["score"] is None


def test_model_adapter_constructs_nonshell_request(monkeypatch):
    monkeypatch.setattr("ctxcomp.providers.shutil.which", lambda x: "C:/Codex/codex.exe")
    seen = {}
    def fake_run(command, prompt, cwd, diagnostics_dir=None, **kwargs):
        seen.update(command=command, kwargs={**kwargs, 'input':prompt})
        output = Path(command[command.index("--output-last-message") + 1])
        write_json(output, {"example": True})
        return subprocess.CompletedProcess(command, 0, "", "")
    monkeypatch.setattr("ctxcomp.providers.monitored_run", fake_run)
    assert codex_generate({"payload": {"schema": {"type": "object"}}, "request_sha256": "hash"}) == {"example": True}
    assert seen["command"][-1] == "-"
    assert seen["command"][seen["command"].index("--sandbox") + 1] == "read-only"
    assert "shell" not in seen["kwargs"]
    assert "Do not use tools" in seen["kwargs"]["input"]
    assert seen['kwargs']['timeout'] is None


@pytest.mark.usefixtures('rules_1_30')
def test_automatic_full_orchestration_with_mock_backend(tmp_path, completed):
    run = tmp_path / "automatic"
    init_run(run, ASSETS / "proposal.md", policy=read_json(ASSETS / "policy.json"), context_review_mode='legacy')
    calls = []
    def fake_model(req, model=None):
        stage = req["payload"]["stage"]
        calls.append(stage)
        value = read_json(completed / "saved_responses" / f"{stage}.json")
        value["request_sha256"] = req["request_sha256"]
        return value
    result = run_model(run, generator=fake_model, stop_after="pipeline_review")
    assert calls == ["attachment_plan", "requirements", "requirements_review", "context", "context_review", "pipeline", "pipeline_review"]
    assert result["status"] == "CANDIDATE_READY"
    assert verify(run)["status"] == "VALID"


def test_revise_stops_and_only_explicit_rerun_can_regenerate(tmp_path, completed):
    run = tmp_path / "revision"
    init_run(run, ASSETS / "proposal.md", policy=read_json(ASSETS / "policy.json"), context_review_mode='legacy')
    calls = []
    def fake_model(req, model=None):
        stage = req["payload"]["stage"]
        calls.append(stage)
        value = read_json(completed / "saved_responses" / f"{stage}.json")
        value["request_sha256"] = req["request_sha256"]
        if stage == "context_review" and calls.count(stage) == 1:
            value["review"]["decision"] = "REVISE"
            value["review"]["claims"][0]["verdict"] = "MISSING"
        return value
    assert run_model(run, generator=fake_model)["status"] == "REVISE"
    assert calls.count("context") == 1
    assert not (run / "compressed_context.json").exists()
    assert run_model(run, generator=fake_model)["status"] == "CONTEXT_READY"
    assert calls.count("context") == 2
    assert len(list((run / "accepted").glob("context.*.json"))) == 2


def test_unresolved_review_stops_without_publishing(tmp_path, completed):
    run = tmp_path / "unresolved"
    init_run(run, ASSETS / "proposal.md", policy=read_json(ASSETS / "policy.json"), context_review_mode='legacy')
    def fake_model(req, model=None):
        stage = req["payload"]["stage"]
        value = read_json(completed / "saved_responses" / f"{stage}.json")
        value["request_sha256"] = req["request_sha256"]
        if stage == "context_review":
            value["review"]["decision"] = "NEEDS_REVIEW"
            value["review"]["claims"][0]["verdict"] = "UNRESOLVED"
        return value
    assert run_model(run, generator=fake_model)["status"] == "NEEDS_REVIEW"
    assert not (run / "compressed_context.json").exists()
    assert not (run / "project_plan.candidate.json").exists()


def test_cli_reports_error_exit_and_no_output(tmp_path):
    result = subprocess.run([sys.executable, "-m", "ctxcomp", "verify", "--run", str(tmp_path / "absent")],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert loads(result.stderr)["status"] == "ERROR"


def test_word_ingestion_preserves_paragraph_table_order(tmp_path):
    docx = pytest.importorskip("docx")
    doc = docx.Document()
    doc.add_paragraph("Before table")
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "CL"
    table.cell(0, 1).text = "NOT_FOUND"
    doc.add_paragraph("After table")
    path = tmp_path / "proposal.docx"
    doc.save(path)
    text = document(path, "S1", "PROPOSAL")["text"]
    assert text.index("Before table") < text.index("CL | NOT_FOUND") < text.index("After table")


def test_pdf_without_text_is_not_silently_accepted(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=300, height=300)
    path = tmp_path / "scan.pdf"
    with path.open("wb") as stream:
        writer.write(stream)
    with pytest.raises(ValueError, match="OCR"):
        document(path, "S1", "PROPOSAL")


def test_pdf_text_and_page_location(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
    content = DecodedStreamObject()
    content.set_data(b'BT /F1 12 Tf 20 240 Td (No human PK for development.) Tj ET')
    page[NameObject('/Contents')] = content
    path = tmp_path / 'text.pdf'
    with path.open('wb') as stream:
        writer.write(stream)
    text = document(path, 'S1', 'PROPOSAL')['text']
    assert '[PAGE 1]' in text
    assert 'No human PK for development.' in text


def test_reviewed_handoff_matches_actual_human_decision(completed):
    human_review(completed, 'PASS', 'test reviewer', 'Test only')
    reviewed = read_json(completed / 'project_plan.reviewed.json')
    assert reviewed['review']['decision'] == 'PASS'
    reviewed['context']['objective'] = 'Changed after review'
    write_json(completed / 'project_plan.reviewed.json', reviewed)
    with pytest.raises(ValueError, match='Reviewed handoff'):
        verify(completed)


@pytest.mark.usefixtures('rules_1_30')
def test_first_revision_stops_without_retry(tmp_path, completed):
    run = tmp_path / 'never_passes'
    init_run(run, ASSETS / 'proposal.md', policy=read_json(ASSETS / 'policy.json'), context_review_mode='legacy')
    calls = []
    def fake_model(req, model=None):
        stage = req['payload']['stage']
        calls.append(stage)
        value = read_json(completed / 'saved_responses' / f'{stage}.json')
        value['request_sha256'] = req['request_sha256']
        if stage == 'context_review':
            value['review']['decision'] = 'REVISE'
            value['review']['claims'][0]['verdict'] = 'MISSING'
        return value
    assert run_model(run, generator=fake_model)['status'] == 'REVISE'
    assert len(calls) == 5  # Empty gap plan needs no attachment evidence call.
    assert not (run / 'project_plan.candidate.json').exists()


def test_envelope_evidence_paths_keep_original_response_and_audit(completed):
    bundle, _ = load_run(completed)
    saved = read_json(completed / 'saved_responses/context.json')
    original_audit, original_metrics = context_check(saved['context'], saved['evidence'], bundle['sources'], bundle['budget'])
    for item in saved['evidence']:
        item['path'] = '/context' + item['path']
    before = copy.deepcopy(saved)
    audit, metrics = context_check(saved['context'], saved['evidence'], bundle['sources'], bundle['budget'])
    assert saved == before
    assert metrics == original_metrics
    assert [item['path'] for item in audit] == [item['path'] for item in original_audit]
    assert [item['input_path'] for item in audit] == [item['path'] for item in saved['evidence']]


@pytest.mark.parametrize('pointer', [
    '/context/context/objective', '/pipeline/objective', '/context/study',
    '/context/not_a_field', '/context/data/available/9999',
    '/context/rules/00', '/context/version', '/context/study~1drug',
])
def test_evidence_prefix_compatibility_does_not_guess_targets(completed, pointer):
    bundle, _ = load_run(completed)
    saved = read_json(completed / 'saved_responses/context.json')
    saved['evidence'][0]['path'] = pointer
    with pytest.raises(ValueError, match='Unknown .* pointer'):
        context_check(saved['context'], saved['evidence'], bundle['sources'], bundle['budget'])


def test_mixed_evidence_spellings_cannot_hide_duplicate(completed):
    bundle, _ = load_run(completed)
    saved = read_json(completed / 'saved_responses/context.json')
    duplicate = copy.deepcopy(saved['evidence'][0])
    duplicate['path'] = '/context' + duplicate['path']
    saved['evidence'].append(duplicate)
    with pytest.raises(ValueError, match='Repeated evidence pointer'):
        context_check(saved['context'], saved['evidence'], bundle['sources'], bundle['budget'])


def test_prefixed_evidence_still_requires_verbatim_quote(completed):
    bundle, _ = load_run(completed)
    saved = read_json(completed / 'saved_responses/context.json')
    saved['evidence'][0]['path'] = '/context' + saved['evidence'][0]['path']
    saved['evidence'][0]['quote'] = 'Invented evidence must not pass after a path repair.'
    with pytest.raises(ValueError, match='verbatim'):
        context_check(saved['context'], saved['evidence'], bundle['sources'], bundle['budget'])


def test_prefixed_suggestion_cannot_become_project_fact(completed):
    bundle, _ = load_run(completed)
    saved = read_json(completed / 'saved_responses/context.json')
    item = next(e for e in saved['evidence'] if e['path'] == '/study/drug')
    item.update(path='/context/study/drug', status='PROPOSED')
    with pytest.raises(ValueError, match='project facts'):
        context_check(saved['context'], saved['evidence'], bundle['sources'], bundle['budget'])


@pytest.mark.parametrize('stage,root', [('context_review', 'context'), ('pipeline_review', 'pipeline')])
def test_review_prefixes_resolve_without_mutation(completed, stage, root):
    bundle, _ = load_run(completed)
    target = read_json(completed / 'saved_responses' / (root + '.json'))[root]
    review = read_json(completed / 'saved_responses' / (stage + '.json'))['review']
    for item in review['claims']:
        item['path'] = '/' + root + item['path']
    before = copy.deepcopy(review)
    assert review_check(review, target, bundle['sources'], stage) == 'PASS'
    assert review == before


@pytest.mark.parametrize('stage,root', [('context_review', 'context'), ('pipeline_review', 'pipeline')])
def test_mixed_review_spellings_cannot_hide_duplicate(completed, stage, root):
    bundle, _ = load_run(completed)
    target = read_json(completed / 'saved_responses' / (root + '.json'))[root]
    review = read_json(completed / 'saved_responses' / (stage + '.json'))['review']
    duplicate = copy.deepcopy(review['claims'][0])
    duplicate['path'] = '/' + root + duplicate['path']
    review['claims'].append(duplicate)
    with pytest.raises(ValueError, match='exactly once'):
        review_check(review, target, bundle['sources'], stage)


def test_accept_records_normalized_audit_without_rewriting_candidate(tmp_path, completed):
    run = tmp_path / 'prefixed_response'
    init_run(run, ASSETS / 'proposal.md', policy=read_json(ASSETS / 'policy.json'), context_review_mode='legacy')
    for stage in ('attachment_plan', 'attachment_evidence', 'requirements', 'requirements_review'):
        preceding = read_json(completed / 'saved_responses' / (stage + '.json'))
        preceding['request_sha256'] = prepare(run, stage)['request_sha256']
        accept(run, stage, preceding)
    saved = read_json(completed / 'saved_responses/context.json')
    saved['request_sha256'] = prepare(run, 'context')['request_sha256']
    for item in saved['evidence']:
        item['path'] = '/context' + item['path']
    original_hash = digest(saved)
    assert accept(run, 'context', saved)['status'] == 'ACCEPTED'
    _, state = load_run(run)
    accepted = read_json(run / state['accepted']['context']['file'])
    assert digest(accepted) == original_hash == digest(saved)
    audit = read_json(run / 'audit/context.json')['evidence']
    assert audit[0]['input_path'] == accepted['evidence'][0]['path']
    assert audit[0]['path'] == accepted['evidence'][0]['path'].removeprefix('/context')
    assert not (run / 'compressed_context.json').exists()


def test_exported_response_schemas_match_runtime():
    from ctxcomp.schemas import SCHEMAS
    for stage, schema in SCHEMAS.items():
        assert read_json(Path(__file__).parents[1] / 'schemas' / (stage + '.response.schema.json')) == schema
