"""Repeated in-memory references must encode exactly like serialized JSON."""
from research_pipeline import minimal_context_reducer as r


def test_shared_source_refs_roundtrip_without_mutation():
    source = {'path': 'C:/source/' + 'a' * 120, 'sha256': 'f' * 64}
    rows = [{'id': str(i), 'provenance': source, 'second_ref': source,
             'explicit_empty': None if i == 0 else ''} for i in range(4)]
    before = r.canonical(rows)
    encoded = r._encode(rows, '/rows', [])
    assert r.canonical(r._decode(encoded, {})) == before
    assert r.canonical(rows) == before


def test_repeated_same_record_roundtrip():
    record = {'id': 'same', 'path': 'C:/source/' + 'a' * 120, 'sha256': 'f' * 64}
    rows = [record] * 4
    before = r.canonical(rows)
    encoded = r._encode(rows, '/rows', [])
    assert r.canonical(r._decode(encoded, {})) == before
    assert r.canonical(rows) == before


def test_observation_identity_and_time_are_explicit_in_compact_rows():
    import copy
    rows=[{'record_id':'T0037_R'+str(row), 'observation_id':f'R{row}_C{col}',
           'source_row':row,'source_cell':f'{col}{row}', 'canonical_time_h':time,
           'times':[{'source_cell':'A'+str(row),'time_h':time}],
           'common_note':'A long repeated source qualification. '*8, 'value':col}
          for row,time in [(7,0.17),(16,6.0)] for col in range(11)]
    before=copy.deepcopy(rows);encoded=r._encode(rows,'/observations',[])
    assert r._decode(encoded,{})==before and rows==before
    table=encoded['record_table'] if 'record_table' in encoded else encoded['record_set']
    assert not {'record_id','observation_id','source_row','source_cell','canonical_time_h','times'} & table['defaults'].keys()
    if 'record_table' in encoded:
        for cells in table['rows']:
            values=dict(zip(table['columns'],cells))
            for key in ('record_id','source_row','canonical_time_h','times'):
                assert values[key] != {'missing_record_field':True}
    else:
        assert all(all(key in row for key in ('record_id','source_row','canonical_time_h','times')) for row in table['records'])
