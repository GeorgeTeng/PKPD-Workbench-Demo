"""Reading exports preserve exact source bytes and disclose semantic limits."""
import json
import zipfile
import pytest
from research_pipeline import reading_package as r
from research_pipeline.common import read_json
from test_cleaning_selfcheck import tiny_execution


def test_compact_package_preserves_censoring_zero_and_exact_files(tiny_execution, tmp_path):
    output, _, _, _ = tiny_execution
    target = tmp_path/'reading.zip'
    result = r.export_package(output/'preparation_execution.json', target)
    manifest = read_json(output/'normalization_manifest.json');dataset = manifest['datasets'][0]
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None
        package = json.loads(z.read('manifest.json'))
        assert result['records'] == 2 and package['record_count'] == 2
        view = z.read('tables/'+dataset['id']+'/table.md').decode()
        assert '0 ⟦CENSORED⟧' in view and 'CENS=1 flags censored Y.' in view
        assert 'mg/kg' in view and '../../manifest.json' in view
        for name,key in [('data.json','data'),('data.csv','csv'),('metadata.json','metadata_file'),('quarantine.json','quarantine')]:
            from pathlib import Path
            assert 'tables/'+dataset['id']+'/'+name not in z.namelist()
            ref=package['tables'][0]['sources'][key]
            target_source=Path(package['source_root'])/ref['path']
            assert target_source.resolve()==Path(dataset[key]['path']).resolve()
            assert r.reference(target_source)['sha256']==ref['sha256']
        assert 'scope.md' not in z.namelist() and package['fit_ready'] is False
        assert '"evidence"' not in view
    before = target.read_bytes()
    r.export_package(output/'preparation_execution.json', target, [dataset['id']])
    assert target.read_bytes() == before
    for invalid in ([], [dataset['id'],dataset['id']], ['MISSING'], ['../bad']):
        with pytest.raises(ValueError): r.export_package(output/'preparation_execution.json', target, invalid)
    assert target.read_bytes() == before


def test_notes_remove_only_literal_repetition():
    notes = ['No paired analysis. Unknown SD.', 'Unknown SD. Retain censored zero.',
             'No paired analysis. Unknown SD.']
    assert r.compact_notes(notes) == ['No paired analysis. Unknown SD.', 'Retain censored zero.']
    assert r.unique_text(['SC', 'Single SC dose']) == ['Single SC dose']
    assert r.compact_notes(['Dose 1 mM.', 'Dose 1 MM.']) == ['Dose 1 mM.', 'Dose 1 MM.']


def test_views_collapse_only_identity_fields_and_keep_units_missingness_annotations():
    dataset={'id':'T1','readiness':'PENDING','metadata':{
        'source_table':{'title':'x|y','column_map':{'raw':'Time (min)'},'notes':'Do not pair animals.'},
        'columns':[{'header':'Time (min)','unit':'min','meaning':'TIME','qualifiers':['approximate']}],
        'normalized_fields':{'time_h':{'source_header':'Time (min)','factor':1/60}}}}
    rows=[{'record_id':'R1','raw':0,'time_h':0,'value_status':{'raw':'CENSORED'},
           'qc_status':'TECHNICALLY_RETAINED','source_footnotes':{'raw':'LLOQ unknown'}},
          {'record_id':'R2','raw':None,'value_status':{'raw':'MISSING'}}]
    view=r.reading_view(dataset, rows, [], []).decode()
    assert 'Time (min)' in view and 'time_h' in view and 'min' in view
    assert 'null ⟦MISSING⟧' in view and '0 ⟦CENSORED⟧' in view
    assert 'LLOQ unknown' in view and 'Do not pair animals.' in view and 'x&#124;y' in view
    dataset['metadata']['normalized_fields']['time_h']['factor']=1
    rows=[{'record_id':'R1','raw':1.23456789012345,'time_h':1.23456789012345,'value_status':{'raw':'QUANTIFIED'},'qc_status':'TECHNICALLY_RETAINED'}]
    view=r.reading_view(dataset, rows, [], []).decode()
    assert 'identical_derived_field' not in view and view.count('1.23456789012345')==1


def test_changed_bound_export_cannot_be_packaged(tiny_execution,tmp_path):
    from pathlib import Path
    output,_,_,_=tiny_execution
    manifest=read_json(output/'normalization_manifest.json')
    Path(manifest['datasets'][0]['csv']['path']).write_text('altered')
    with pytest.raises(ValueError):
        r.export_package(output/'preparation_execution.json',tmp_path/'invalid.zip')
    assert not (tmp_path/'invalid.zip').exists()


def test_compact_view_hides_only_unflagged_bookkeeping():
    dataset = {'id':'T1', 'metadata':{'source_table':{'title':'Mean curve',
        'column_map':{'x':'Pixel x','label':'Point label','id':'Animal ID','t':'Time (h)','y':'Mean concentration'},
        'notes':'Mean curve\nDOI 10.123/example\nCalibration x=1,2 -> 0,1 linear\nNot individual data.'},
        'columns':[{'header':'Mean concentration','unit':'mg/L'}]}}
    rows = [{'record_id':'R1','x':42,'label':'P1','id':'a','t':1.234567890123,'y':0,
             'value_status':{'y':'CENSORED'}}]
    view = r.reading_view(dataset,rows,[],[{'reason':'Time origin unknown.','needed_material':'Long request'}]).decode()
    assert 'Pixel x' not in view and 'Point label' not in view and 'Animal ID' in view
    assert 'Mean concentration (mg/L)' in view and '1.234567890123' in view and '0 ⟦CENSORED⟧' in view
    assert 'Time origin unknown.' in view and 'Not individual data.' in view
    assert 'Long request' not in view and 'Calibration' not in view and '10.123' not in view
    assert '<details>' not in view and len(view)<650
    rows[0]['value_status']['x']='MISSING'
    assert 'Pixel x' in r.reading_view(dataset,rows,[],[]).decode()


def test_units_are_not_hidden_by_incidental_header_letters():
    dataset={'id':'T1','metadata':{'source_table':{'title':'Mass','column_map':{'w':'Weight'}},
                                'columns':[{'header':'Weight','unit':'g'}]}}
    assert 'Weight (g)' in r.reading_view(dataset,[{'record_id':'R1','w':20}],[],[]).decode()


def test_placeholder_legend_keeps_ambiguous_tokens_and_censored_zero_explicit():
    d={'id':'T1','metadata':{'route':'NOT_APPLICABLE','source_table':{'column_map':{'x':'X','y':'Y'}}}}
    rows=[{'record_id':'R1','x':'.','y':0,'value_status':{'x':'MISSING_OR_NOT_APPLICABLE','y':'CENSORED'}},
          {'record_id':'R2','x':'.','y':None,'value_status':{'x':'MISSING_OR_NOT_APPLICABLE','y':'MISSING'}}]
    view=r.reading_view(d,rows,[],[]).decode()
    assert 'Legend: . = missing / not applicable.' in view
    assert '. ⟦MISSING_OR_NOT_APPLICABLE⟧' not in view
    assert '0 ⟦CENSORED⟧' in view and 'null ⟦MISSING⟧' in view
    assert 'NOT_APPLICABLE' not in view
    rows[1]['value_status']['x']='SOURCE_TEXT_REQUIRES_REVIEW'
    view=r.reading_view(d,rows,[],[]).decode()
    assert '. ⟦MISSING_OR_NOT_APPLICABLE⟧' in view and 'Legend:' not in view


def test_fixed_unit_column_requires_exact_agreement_including_quarantine():
    d={'id':'T1','metadata':{'source_table':{'column_map':{'x':'Index coordinate','u':'X unit'}},
                           'columns':[{'header':'Index coordinate','unit':'ratio'}]}}
    rows=[{'record_id':'R1','x':0.1,'u':'ratio'}]
    assert 'X unit' not in r.reading_view(d,rows,[],[]).decode()
    assert 'Index coordinate (ratio)' in r.reading_view(d,rows,[],[]).decode()
    assert 'X unit' in r.reading_view(d,rows,[{'record_id':'Q1','x':1,'u':'%'}],[]).decode()
    rows[0]['source_footnotes']={'u':'Unverified unit'}
    assert 'X unit' in r.reading_view(d,rows,[],[]).decode()


def test_context_duplicate_does_not_remove_qualified_or_opposite_statement():
    assert r.compact_notes(['Single dose. No serial identity.', 'OPEN; No serial identity.'], ['Single dose.']) == ['No serial identity.']
    assert r.compact_notes(['Not a single dose. Single dose only in arm B.'], ['Single dose.']) == ['Not a single dose. Single dose only in arm B.']


def test_mapping_gate_merge_keeps_table_specific_limits():
    d={'id':'T1','metadata':{'source_table':{'column_map':{'x':'X'}}}}
    findings=[{'code':'PK_MAPPING_REQUIRED','reason':'No complete supported time/concentration mapping. Raw columns were retained.'},
              {'code':'EDA_MAPPING_GATE_UNSETTLED','reason':'Mapping or a limitation decision is required before EDA.'},
              {'code':'OTHER','reason':'Tissue units are ug/g; do not convert to mg/L.'}]
    view=r.reading_view(d,[{'record_id':'R1','x':1}],[],findings).decode()
    assert view.count('Scalar PK mapping is incomplete.')==1
    assert 'Before EDA' in view and 'explicitly authorize' in view
    assert 'Tissue units are ug/g; do not convert to mg/L.' in view
