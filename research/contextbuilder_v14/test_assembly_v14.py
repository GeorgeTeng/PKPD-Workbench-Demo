import copy, unittest
import assembly, builder_engine as e

def fixture():
    base={'request':{'payload':{'instructions':'Do the bounded task','schema':{'properties':{'answer':{}},'required':['answer']}}}}
    task={'model_needs':['Preserve observations and method restrictions']}
    req={'assignments':[{'output_id':'answer'}], 'needs':[
        {'id':'first','needed_for':['answer'],'query':'first'},
        {'id':'second','needed_for':['answer'],'query':'second'}]}
    recalls=[]
    for i,n in enumerate(req['needs']):
        sid='source'+str(i);eid='excerpt'+str(i)
        card={'id':'method'+str(i),'conditions':['Applicable only with units established'],
              'limitations':['Do not infer identity'],'required_inputs':['raw observation'],
              'source_ids':[sid],'evidence_chunk_ids':[eid],
              'claim_support':[{'claim':'Conditional method','evidence_chunk_ids':[eid]}]}
        evidence={'id':eid,'source_id':sid,'text':'Do not join different individuals. Value 0.5 mg/L.', 'locator':'page 1'}
        recalls.append({'need_id':n['id'],'packet':{'context':{'general_methods':[card],
            'applicability_and_examples':{'evidence':[evidence],'cited_originals':{sid:{'id':sid,'sha256':'bound'}}}}}})
    return base,req,task,{'records':[{'value':0.5,'unit':'mg/L','BLQ':False}]},recalls,['source0','source1']

class AssemblyTests(unittest.TestCase):
    def test_bad_dependency_only_restricts_affected_need(self):
        args=list(fixture());args[4][0]['packet']['context']['applicability_and_examples']['evidence']=[]
        result,audit=assembly.assemble_support(*args)
        self.assertEqual([x['id'] for x in result['knowledge']['methods']],['method1'])
        self.assertFalse(result['resolutions'][0]['content_delivered'])
        self.assertTrue(result['resolutions'][1]['content_delivered'])
        self.assertEqual(result['resolutions'][1]['scientific_sufficiency'],'NOT_ASSESSED')
    def test_exact_inputs_determinism_and_conditions(self):
        args=fixture();before=copy.deepcopy(args)
        result,audit=assembly.assemble_support(*args)
        self.assertEqual(args,before)
        self.assertEqual((result,audit),assembly.assemble_support(*args))
        self.assertEqual(result['task_view'],args[3])
        for row,rec in zip(result['knowledge']['methods'],args[4]):
            self.assertEqual(row,rec['packet']['context']['general_methods'][0])
    def test_wire_budget_refuses_whole_units_not_truncates(self):
        args=fixture()
        result,audit=assembly.assemble_support(*args,final_fits=lambda p:not p['knowledge']['methods'])
        self.assertEqual(result['knowledge']['methods'],[])
        self.assertEqual(result['task_view'],args[3])
        self.assertTrue(all(not r['content_delivered'] for r in result['resolutions']))
    def test_cannot_enlarge_raw_budget(self):
        with self.assertRaises(ValueError): assembly.assemble_support(*fixture(),character_budget=64001)
    def test_declared_cycles_and_missing_targets_are_distinct(self):
        nodes={'a':{'requires':['b']},'b':{'requires':['a','missing']}}
        closed=e.close(nodes,['a'])
        self.assertEqual(closed['missing'],['missing'])
        self.assertEqual(closed['cycles'],[['a','b','a']])

if __name__=='__main__': unittest.main()
