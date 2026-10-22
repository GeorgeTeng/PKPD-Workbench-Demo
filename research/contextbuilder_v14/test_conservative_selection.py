import unittest
from test_assembly_v14 import fixture
import assembly_conservative as a
import builder_engine_conservative as e

class ConservativeSelectionTests(unittest.TestCase):
    def test_retained_lower_rank_unit_cannot_be_swapped_for_newly_fitting_unit(self):
        args=fixture();root=e.compile_units(args[4],args[5])['cards'][1]['root']
        result,audit=a.assemble_support(*args,retained_roots=[root],
            final_fits=lambda s:len(s['knowledge']['methods'])<=1)
        self.assertEqual([c['id'] for c in result['knowledge']['methods']],['method1'])
        self.assertIn(root,audit['selected_roots'])
    def test_spare_capacity_extends_retained_units(self):
        args=fixture();root=e.compile_units(args[4],args[5])['cards'][1]['root']
        result,audit=a.assemble_support(*args,retained_roots=[root])
        self.assertEqual(len(result['knowledge']['methods']),2)
        self.assertIn(root,audit['selected_roots'])
    def test_no_silent_drop_if_retained_content_exceeds_budget(self):
        args=fixture();root=e.compile_units(args[4],args[5])['cards'][1]['root']
        with self.assertRaises(ValueError):
            a.assemble_support(*args,retained_roots=[root],final_fits=lambda s:not s['knowledge']['methods'])
    def test_changed_permission_cannot_be_bypassed_by_retention(self):
        args=list(fixture());root=e.compile_units(args[4],args[5])['cards'][1]['root']
        args[5]=['source0']
        with self.assertRaises(ValueError):a.assemble_support(*args,retained_roots=[root])
if __name__=='__main__':unittest.main()
