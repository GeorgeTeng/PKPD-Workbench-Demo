"""Exact-source bindings, not a semantic accuracy benchmark."""
import copy
import pytest
from ctxcomp import scientific
from ctxcomp.schemas import SCIENCE_BINDING
from ctxcomp.rules import load_rules
from test_scientific_extraction import scientific_fixture


def test_binding_schema_and_agent_share_explicit_value_contract():
    contract=load_rules()['scientific_extraction']['binding_contract']
    assert SCIENCE_BINDING['properties']['value']['description']==contract['value_definition']
    assert contract['examples']


def test_collects_every_bad_binding_with_actionable_source_details():
    _,units,inv=scientific_fixture()
    bindings=inv['items'][2]['science']['bindings']
    bindings[0]['value']='Human: predicted exposure'
    bindings[2]['value']='4.0'
    with pytest.raises(ValueError) as error: scientific.validate_inventory(inv,units)
    assert error.value.code=='MODEL_BINDING_INVALID'
    details=error.value.validation_details
    assert details['issue_count']==2 and details['affected_item_count']==1
    first=details['issues'][0]
    assert first['item_id']=='R003' and first['field']=='species'
    assert first['path']=='/requirements/items/2/science/bindings/0/value'
    assert first['proposed_value']=='Human: predicted exposure'
    assert first['evidence'][0]['source_verified'] is True
    assert 'statement' in first['what_to_change']


def test_newline_join_cannot_create_a_source_match():
    _,units,inv=scientific_fixture()
    item=inv['items'][2]; component=item['components'][0]
    span=component['evidence'][0]
    component['evidence']=[{**span,'quote':'Human CL'},{**span,'quote':'4 L/h'}]
    item['science']['bindings']=[{'field':'parameter','value':'Human CL\n4 L/h','component_ids':['C1']}]
    with pytest.raises(ValueError) as error: scientific.validate_inventory(inv,units)
    assert error.value.validation_details['issues'][0]['reason']=='VALUE_NOT_IN_CITED_SOURCE'


def test_matching_a_fabricated_quote_cannot_pass_binding_gate():
    _,units,inv=scientific_fixture()
    item=inv['items'][2]
    item['components'][0]['evidence'][0]['quote']='Human CL was measured as 40 L/h.'
    item['science']['bindings']=[{'field':'value','value':'40','component_ids':['C1']}]
    with pytest.raises(ValueError) as error: scientific.validate_inventory(inv,units)
    assert error.value.validation_details['issues'][0]['reason']=='CITED_EVIDENCE_INVALID'


@pytest.mark.parametrize('selection',[[],['C99'],['C1','C1']])
def test_invalid_binding_component_selection_is_reported(selection):
    _,units,inv=scientific_fixture()
    inv['items'][2]['science']['bindings'][0]['component_ids']=selection
    with pytest.raises(ValueError) as error: scientific.validate_inventory(inv,units)
    assert error.value.validation_details['issues'][0]['reason']=='INVALID_COMPONENT_SELECTION'


def test_valid_exact_binding_retains_compact_statement_and_conditions():
    _,units,inv=scientific_fixture(); before=copy.deepcopy(inv)
    scientific.validate_inventory(inv,units)
    assert inv==before


def test_whitespace_value_is_not_an_evidence_binding():
    _,units,inv=scientific_fixture()
    inv['items'][2]['science']['bindings'][0]['value']=' '
    with pytest.raises(ValueError) as error: scientific.validate_inventory(inv,units)
    assert error.value.validation_details['issues'][0]['reason']=='EMPTY_VALUE'


def test_typed_binding_failure_survives_runner_and_retains_response(tmp_path, monkeypatch):
    from ctxcomp import engine
    from ctxcomp.providers import run_model
    from ctxcomp.io import read_json
    from attachment_fixture import accept_empty_search
    from ctxcomp.bindings import binding_diagnostics, BindingValidationError
    pack=load_rules(); pack['retry_policy']['binding_repair']['max_attempts']=0
    monkeypatch.setattr(engine,'load_rules',lambda:copy.deepcopy(pack))
    proposal=tmp_path/'proposal.txt'; proposal.write_text('Predict human PK.')
    run=tmp_path/'run'; engine.init_run(run,proposal); accept_empty_search(run)
    _,units,inv=scientific_fixture(); inv['items'][2]['science']['bindings'][0]['value']='rewritten value'
    details=binding_diagnostics(inv,units)
    def reject(*args,**kwargs): raise BindingValidationError(details)
    monkeypatch.setattr(engine, '_accept', reject)
    with pytest.raises(BindingValidationError):
        run_model(run, generator=lambda req,model=None:{'request_sha256':req['request_sha256'],'requirements':inv})
    stopped=read_json(run/'stopped.json')
    assert stopped['error_code']=='MODEL_BINDING_INVALID'
    assert stopped['validation_details']==details
    response=read_json(run/stopped['response'])
    assert response['requirements']==inv
    record=read_json(run/stopped['validation_record'])
    assert record['request_sha256']==response['request_sha256']==stopped['failed_request_sha256']


def spreadsheet_case():
    """A cited spreadsheet row whose note is the quote; species, sheet and header sit elsewhere in the same source."""
    import json
    from ctxcomp.bindings import binding_diagnostics
    row = lambda r, cells: {'id': f'F0004_S03R{r:06d}_U0001', 'source_id': f'F0004_S03R{r:06d}',
        'text': json.dumps({'sheet': 'Rabbit', 'cells': [{'cell': f'{c}{r}', 'row': r, 'column': i, 'value': v}
                                                          for i, (c, v) in enumerate(cells, 1)]})}
    units = [row(1, [('A', 'Study'), ('B', 'Species'), ('C', 'Dose unit')]), row(192, [('A', 'S22'), ('B', 'rabbit'), ('C', 'mg/kg')]),
             {'id': 'F0003_P0001_U0001', 'source_id': 'F0003_P0001',
              'text': 'Drug files.\nMouse: plasma and ELF PK. Use for animal PK analysis.\nRat: tissue means.'}]
    def check(value, quote, unit=units[1]):
        record = {'id': 'REQ-1', 'components': [{'id': 'C1', 'evidence': [{'source_id': unit['source_id'], 'unit_id': unit['id'], 'quote': quote}]}],
                  'science': {'bindings': [{'field': 'species', 'value': value, 'component_ids': ['C1']}]}}
        return binding_diagnostics({'items': [record]}, units)
    return units, check


def test_a_value_may_come_from_the_cited_row_sheet_header_or_line():
    units, check = spreadsheet_case()
    for value, where in [('rabbit', 'SAME_ROW_CELL'), ('Rabbit', 'SHEET_NAME'), ('Dose unit', 'COLUMN_HEADER')]:
        details = check(value, 'mg/kg')
        assert details['issue_count'] == 0 and details['outside_quote'][0]['location'] == where, value
    details = check('Mouse', 'Use for animal PK analysis.', units[2])
    assert details['issue_count'] == 0 and details['outside_quote'][0]['location'] == 'SAME_LINE'
    details = check('Rat', 'Use for animal PK analysis.', units[2])
    assert details['outside_quote'][0]['location'] == 'SAME_SOURCE_UNIT'
    assert check('mg/kg', 'mg/kg')['outside_quote'] == []


def test_a_value_absent_from_the_cited_source_still_fails():
    units, check = spreadsheet_case()
    # A header from another column, a value from no source, and a coded status are not source text of the cited cell.
    for value in ('Study', 'mouse', 'NOT_FOUND'):
        assert check(value, 'rabbit')['issues'][0]['reason'] == 'VALUE_NOT_IN_CITED_SOURCE', value
