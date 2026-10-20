"""Source-only labeling retains the original evidence and downstream label shape."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app
from research_pipeline import data_agents as da, demo_data
from ctxcomp.schemas import validate_schema


class SourceLabelTests(unittest.TestCase):
    def test_scope_keeps_all_source_units_rules_and_column_vocabulary(self):
        original = {'source_units': {'A:B2': '<LLOQ', 'A:A1': 'Time after infusion (h)',
                                    'A': 'total plasma concentration; no longitudinal animal IDs'},
                    'project_rules': [{'id': 'R1', 'text': 'Do not pool these studies.'}],
                    'label_vocabulary': {'record_category': 'individual versus summary'},
                    'requirements': [{'id': 'DR1', 'description': 'Later PTA evaluation'}],
                    'method_knowledge': {'profiles': ['PTA']}, 'pk_terminology': {'PTA': 'definition'},
                    'context_sources': {'main:/later': 'Model evaluation'}, 'instructions': 'old',
                    'item_id': 'A', 'page': 1, 'pages': 1}
        before = copy.deepcopy(original)
        scoped = demo_data.source_label_payload(original)
        self.assertEqual(original, before)
        for key in ('source_units', 'project_rules', 'label_vocabulary', 'item_id', 'page', 'pages'):
            self.assertEqual(scoped[key], original[key])
        self.assertEqual(scoped['requirements'], [])
        self.assertIsNone(scoped['method_knowledge'])
        self.assertEqual(scoped['pk_terminology'], {})
        self.assertEqual(scoped['label_scope']['requirement_matching'], 'DEFERRED')

    def test_actual_label_path_preserves_checks_and_defers_links_only_in_demo(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            main_path, inv_path, req_path = [folder/name for name in ('main.json','inventory.json','requirements.json')]
            main_path.write_text('{}'); inv_path.write_text('{}')
            needs = [{'id': 'DR1', 'rule_ids': ['R1']}]
            req = {'main': da.file_ref(main_path), 'inventory': da.file_ref(inv_path),
                   'requirements': needs, 'access': [{'item_id': 'A', 'disposition': 'REVIEW_DATA',
                       'rule_ids': ['R1'], 'requirement_ids': ['DR1'], 'context_paths': ['/later']}]}
            req_path.write_text(json.dumps(req))
            main = {'objective':'Later modeling and PTA'}
            inv = {'items':[{'id':'A','kind':'DOCUMENT','descriptor':{}}]}
            rules = [{'id':'R1','text':'Do not pool studies'}]
            source = {'A':'source document', 'main:/later':'Future PTA task'}
            label = {**dict.fromkeys(da.LABEL_FIELDS, 'NOT_FOUND'), 'item_id':'A',
                     'role':'PK_OBSERVATIONS','additional_roles':[], 'columns':[], 'stated_values':[],
                     'reason':'Source concentration.', 'evidence':[{'source':'A:L1','quote':'2 mg/L'}]}
            def invoke(run, stage, payload, schema, check, **kwargs):
                compact = os.environ['PKPD_DEMO_LIGHTWEIGHT_DATA'] == '1'
                self.assertEqual(payload['source_units'], {'A':'source document','A:L1':'Concentration 2 mg/L'})
                self.assertEqual(payload['requirements'], [] if compact else needs)
                response = {'request_sha256':'x', 'labels':[{**label,'requirement_ids':[] if compact else ['DR1']}], 'findings':[]}
                validate_schema(response, schema)
                check(response)
                bad = copy.deepcopy(response)
                bad['labels'][0]['evidence'][0]['quote'] = 'invented concentration'
                with self.assertRaises(ValueError):
                    check(bad)
                if compact:
                    bad = copy.deepcopy(response); bad['labels'][0]['requirement_ids'] = ['DR1']
                    with self.assertRaises(ValueError):
                        validate_schema(bad, schema)
                return response
            with patch.object(da,'context_input',return_value=(main,inv,rules,source)), \
                 patch.object(da,'requirement_knowledge',return_value=None), \
                 patch.object(da,'content_units',return_value=[('A:L1','Concentration 2 mg/L')]), \
                 patch.object(da,'content_cells',return_value=[]), patch.object(da,'invoke',side_effect=invoke):
                for compact in ('1','0'):
                    with patch.dict(os.environ, {'PKPD_DEMO_LIGHTWEIGHT_DATA':compact}):
                        out=folder/('labels'+compact+'.json')
                        da.label(folder,main_path,inv_path,req_path,out)
                        result=json.loads(out.read_text())
                        self.assertEqual(result['coverage'][0]['units_read'], 1)
                        self.assertEqual(result['labels'][0]['evidence'], label['evidence'])
                        self.assertFalse(result['fit_ready'])
                        self.assertEqual('label_scope' in result, compact == '1')
            self.assertEqual(json.loads(req_path.read_text()), req)


if __name__ == '__main__':
    unittest.main()
