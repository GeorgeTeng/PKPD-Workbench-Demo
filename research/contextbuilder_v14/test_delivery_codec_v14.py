import copy
import importlib.util
import json
import math
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    'codec_rag_v14', ROOT / 'rag_vnext/__init__.py',
    submodule_search_locations=[str(ROOT / 'rag_vnext')])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
from codec_rag_v14 import delivery_codec
from codec_rag_v14.rag_v1 import RagError, canonical


class DeliveryCodecV14(unittest.TestCase):
    def support(self):
        repeated = 'The source locator and experimental condition remain linked. ' * 8
        return {
            'task_view': {'prompt': repeated, 'reminders': [repeated] * 4,
                          'needs': ['dose', 'species', 'route']},
            'knowledge': {
                'sources': [
                    {'id': 'src-A', 'text': repeated, 'locator': {'page': 4, 'offset': 22},
                     'condition': {'species': 'mouse', 'dose': 3.5}},
                    {'id': 'src-B', 'text': repeated, 'locator': {'page': 4, 'offset': 22},
                     'condition': {'species': 'rat', 'dose': 3.5}},
                    {'id': 'src-C', 'text': repeated, 'locator': {'page': 4, 'offset': 22},
                     'condition': {'species': 'dog', 'dose': 3.5}},
                    {'id': 'src-D', 'text': repeated, 'locator': {'page': 4, 'offset': 22},
                     'condition': {'species': 'pig', 'dose': 3.5}},
                ],
                'numbers': [0, -1, 1.25, True, None, {'null': None}],
                'unicode': '药物浓度 — μg/mL — 日本語',
            },
            'other': {'keep': None, 'array': [1, '1', False]},
        }

    def test_project_roundtrips_task_and_knowledge_with_provenance(self):
        support = self.support()
        projected = delivery_codec.project(support)
        self.assertEqual(delivery_codec.unpack(projected['task_view']), support['task_view'])
        self.assertEqual(delivery_codec.decode_support(projected), support)
        self.assertEqual([s['id'] for s in delivery_codec.decode_support(projected)['knowledge']['sources']],
                         ['src-A', 'src-B', 'src-C', 'src-D'])
        self.assertLess(len(canonical(projected)), len(canonical(support)))

    def test_numbers_unicode_null_types_and_string_identity(self):
        original = self.support()
        decoded = delivery_codec.decode_support(delivery_codec.project(original))
        self.assertEqual(decoded, original)
        self.assertIs(type(decoded['knowledge']['numbers'][3]), bool)
        self.assertIsNone(decoded['knowledge']['numbers'][4])
        self.assertEqual(decoded['knowledge']['unicode'], original['knowledge']['unicode'])
        self.assertEqual(decoded['knowledge']['sources'][0]['text'], decoded['knowledge']['sources'][1]['text'])
        self.assertNotEqual(decoded['knowledge']['sources'][0]['id'], decoded['knowledge']['sources'][1]['id'])

    def test_nested_reserved_marker_falls_back_to_raw(self):
        support = self.support()
        support['knowledge']['raw_payload'] = {'$v': 'literal source marker'}
        projected = delivery_codec.project(support)
        self.assertEqual(projected['knowledge'], support['knowledge'])
        self.assertEqual(delivery_codec.decode_support(projected), support)

    def test_ambiguous_wrapper_markers_are_rejected(self):
        for marker_value in (
                {'knowledge_encoding': {'version': 'EXACT_SUPPORT_WIRE_1'}, 'payload': {'x': 1}},
                {'knowledge_encoding': {'version': 'not-a-codec'}, 'payload': {'x': 1}}):
            support = self.support()
            support['knowledge'] = marker_value
            with self.subTest(marker_value=marker_value), self.assertRaisesRegex(RagError, 'Ambiguous knowledge wrapper'):
                delivery_codec.project(support)

    def test_tamper_hash_and_unknown_alias_fail_closed(self):
        view = {'rows': [{'id': str(i), 'text': 'Repeated exact source condition ' * 8} for i in range(30)]}
        packed = delivery_codec.pack(view)
        self.assertIn('task_view_encoding', packed)
        changed = copy.deepcopy(packed)
        changed['task_view_encoding']['parent_sha256'] = '0' * 64
        with self.assertRaises(RagError):
            delivery_codec.unpack(changed)
        changed = copy.deepcopy(packed)
        changed['task_view_encoding']['verbatim'].clear()
        with self.assertRaises(RagError):
            delivery_codec.unpack(changed)

    def test_request_measure_uses_full_outer_json_escaping_cost(self):
        support = self.support()
        # Escaped full-message JSON adds substantial framing cost and is supplied by caller.
        def full_message_size(candidate):
            return len(json.dumps({'messages': [{'role': 'user', 'content': json.dumps(
                candidate, ensure_ascii=True, separators=(',', ':'))}]}, ensure_ascii=True).encode('utf-8'))
        chosen = delivery_codec.project_for_request(support, full_message_size)
        self.assertLessEqual(full_message_size(chosen), full_message_size(support))
        self.assertEqual(delivery_codec.decode_support(chosen), support)

    def test_project_for_request_falls_back_on_tie_or_bad_measure(self):
        support = self.support()
        self.assertEqual(delivery_codec.project_for_request(support, lambda _: 10), support)
        for invalid in ('unknown', True, -1, math.nan, math.inf, -math.inf):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                delivery_codec.project_for_request(support, lambda _: invalid)

    def test_project_for_request_measures_all_four_and_can_choose_task_only(self):
        support = self.support()
        seen = []

        def full_message_size(candidate):
            task = isinstance(candidate['task_view'], dict) and 'task_view_encoding' in candidate['task_view']
            knowledge = isinstance(candidate['knowledge'], dict) and 'knowledge_encoding' in candidate['knowledge']
            seen.append((task, knowledge))
            return {(False, False): 100, (True, False): 5,
                    (False, True): 20, (True, True): 30}[(task, knowledge)]

        chosen = delivery_codec.project_for_request(support, full_message_size)
        self.assertEqual(seen, [(False, False), (True, False), (False, True), (True, True)])
        self.assertIn('task_view_encoding', chosen['task_view'])
        self.assertNotIn('knowledge_encoding', chosen['knowledge'])
        self.assertEqual(delivery_codec.decode_support(chosen), support)


if __name__ == '__main__':
    unittest.main(verbosity=2)
