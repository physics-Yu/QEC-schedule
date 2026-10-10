"""Independent T605 graph/ready/real-action concurrency refusal cases."""
from copy import deepcopy
import json
import gzip
from pathlib import Path
import unittest

from na_pipeline.validation import audit_dependency_graph,validate_hierarchical_run
from na_pipeline.validation.dag_core import DAGAudit,inspect_graph,inspect_schedule,physical_parallel_witnesses
from na_pipeline.validation.dag_source import inspect_source_projection
from na_pipeline.validation.dag_entry import validate_preinitialized_entry,inspect_mz_receiver,inspect_inventory_continuity
from na_pipeline.validation.dag_coupling import audit_css_coupling


def node(identity,reads=(),writes=(),condition=None):
    return {'id':identity,'reads':list(reads),'writes':list(writes),'condition':condition}


class GraphAndScheduleTests(unittest.TestCase):
    def graph(self,nodes,edges=()):
        audit=DAGAudit('component',{},fixture=True)
        graph=inspect_graph(audit,nodes,list(edges))
        self.assertEqual(audit.failures,[])
        return graph

    def test_published_examples(self):
        data=json.loads((Path(__file__).resolve().parents[2]/'knowledge/roles/R6/hierarchical-minimal.json').read_bytes())
        for kind in ('valid_component','rejected_component'):
            e=data[kind]; report=audit_dependency_graph(e['nodes'],e['edges'],fixture=True)
            if kind=='valid_component':
                self.assertTrue(report['passed']); self.assertFalse(report['full_program_passed'])
                self.assertEqual(report['metrics']['initial_ready'],e['expected_initial_ready'])
            else: self.assertIn(e['expected_failure'],{f['code'] for f in report['failures']})
        self.assertEqual(validate_hierarchical_run({})['failures'][0]['code'],'HIERARCHICAL_INPUT_MISSING')

    def test_cycle_not_a_ready_program(self):
        edges=[{'source':'a','target':'b','kind':'quantum'},{'source':'b','target':'a','kind':'protocol'}]
        r=audit_dependency_graph([node('a'),node('b')],edges,fixture=True)
        self.assertIn('DAG_CYCLE',{f['code'] for f in r['failures']})

    def test_duplicate_writer(self):
        r=audit_dependency_graph([node('a',writes=['m']),node('b',writes=['m'])],[],fixture=True)
        self.assertIn('DAG_RESULT_WRITER',{f['code'] for f in r['failures']})

    def test_missing_producer_and_condition_read(self):
        r=audit_dependency_graph([node('a',reads=['missing'],condition={'bit':'m','equals':1})],[],fixture=True)
        self.assertEqual({f['code'] for f in r['failures']},{'DAG_RESULT_PRODUCER_MISSING','DAG_CONDITION_READ_MISSING'})

    def test_long_graph_no_recursive_or_quadratic_closure(self):
        nodes=[node(str(i)) for i in range(5000)]
        edges=[{'source':str(i),'target':str(i+1),'kind':'quantum'} for i in range(4999)]
        graph=self.graph(nodes,edges)
        self.assertTrue(graph.precedes('0','4999')); self.assertFalse(graph.precedes('4999','0'))

    def test_H08_early_feedback_even_with_known_fake_bit(self):
        graph=self.graph([node('m',writes=['bit']),node('c',reads=['bit'],condition={'bit':'bit','equals':1})],[{'source':'m','target':'c','kind':'classical'}])
        intervals=[{'node_id':'m','start_us':0,'end_us':100,'status':'completed'},{'node_id':'c','start_us':110,'end_us':111,'status':'completed'}]
        decisions=[{'time_us':0,'ready':['m'],'selected':['m']},{'time_us':110,'ready':['c'],'selected':['c']}]
        audit=DAGAudit('component',{},fixture=True)
        inspect_schedule(audit,graph,intervals,decisions,{'bit':{'value':1,'ready_us':120}})
        self.assertIn('SCHEDULE_RESULT_NOT_READY',{f['code'] for f in audit.failures})
        self.assertIn('SCHEDULE_READY_SET',{f['code'] for f in audit.failures})

    def test_condition_false_requires_explicit_skip(self):
        graph=self.graph([node('m',writes=['bit']),node('c',reads=['bit'],condition={'bit':'bit','equals':1})],[{'source':'m','target':'c','kind':'classical'}])
        intervals=[{'node_id':'m','start_us':0,'end_us':100,'status':'completed'},{'node_id':'c','start_us':120,'end_us':120,'status':'skipped'}]
        decisions=[{'time_us':0,'ready':['m'],'selected':['m']},{'time_us':120,'ready':['c'],'selected':['c']}]
        audit=DAGAudit('component',{},fixture=True); inspect_schedule(audit,graph,intervals,decisions,{'bit':{'value':0,'ready_us':120}})
        self.assertEqual(audit.failures,[])

    def test_H03_real_physical_parallelism(self):
        graph=self.graph([node('a'),node('b')]); audit=DAGAudit('component',{},fixture=True)
        actions=[{'id':'ha','kind':'gate','t_start_us':0,'t_end_us':1},{'id':'hb','kind':'gate','t_start_us':0,'t_end_us':1}]
        witness=physical_parallel_witnesses(audit,graph,{'a':['ha'],'b':['hb']},actions,{'a':['A'],'b':['B']})
        self.assertEqual(witness[0]['overlap_us'],1); self.assertEqual(audit.unverified,[])

    def test_H02_ready_does_not_remove_shared_resource_conflict(self):
        from na_pipeline.validation.checker import Audit,_resources
        graph=self.graph([node('a'),node('b')]); self.assertEqual(graph.ready([]),['a','b'])
        actions=[{'id':i,'atoms':[i],'t_start_us':0.,'t_end_us':10.,'resources':['aod:data:row:shared']} for i in ('a','b')]
        low=Audit(); _resources(low,{'actions':actions})
        self.assertIn('RESOURCE_OVERLAP',{f['code'] for f in low.failures})

    def test_macro_overlap_with_serial_actions_not_parallel(self):
        graph=self.graph([node('a'),node('b')]); audit=DAGAudit('component',{},fixture=True)
        actions=[{'id':'ha','kind':'gate','t_start_us':0,'t_end_us':1},{'id':'hb','kind':'gate','t_start_us':1,'t_end_us':2}]
        physical_parallel_witnesses(audit,graph,{'a':['ha'],'b':['hb']},actions,{'a':['A'],'b':['B']})
        self.assertEqual(audit.unverified[0]['code'],'PHYSICAL_PARALLELISM_NOT_DEMONSTRATED')

    def test_fake_branch_is_not_completed_early(self):
        graph=self.graph([node('m',writes=['bit']),node('c',reads=['bit'])],[{'source':'m','target':'c','kind':'classical'}])
        self.assertEqual(graph.ready([],['bit']),['m'])
        self.assertEqual(graph.ready(['m']),[])
        self.assertEqual(graph.ready(['m'],['bit']),['c'])

    def test_D01_remove_only_disjoint_serial_order(self):
        ops=[{'id':'a','kind':'gate','qubits':['A'],'params':{'name':'H'},'reads':[],'writes':[],'condition':None,'after':[],'source_ids':['src:a']},
             {'id':'b','kind':'gate','qubits':['B'],'params':{'name':'X'},'reads':[],'writes':[],'condition':None,'after':['a'],'source_ids':['src:b']},
             {'id':'c','kind':'gate','qubits':['A'],'params':{'name':'Z'},'reads':[],'writes':[],'condition':None,'after':['b'],'source_ids':['src:c']}]
        mapping={o['id']:{'node_id':o['id'],'source_operation':deepcopy(o)} for o in ops}
        graph=self.graph([node(o['id']) for o in ops],[{'source':'a','target':'c','kind':'quantum'}])
        audit=DAGAudit('component',{},fixture=True); inspect_source_projection(audit,graph,ops,mapping,[])
        self.assertEqual(audit.failures,[]); self.assertEqual(audit.metrics['disjoint_source_serial_edges_removed'],2)
        bad=self.graph([node(o['id']) for o in ops]); audit=DAGAudit('component',{},fixture=True)
        inspect_source_projection(audit,bad,ops,mapping,[])
        self.assertIn('DAG_QUANTUM_ORDER',{f['code'] for f in audit.failures})

    def test_D01_explicit_protocol_order_is_not_disposable(self):
        ops=[{'id':n,'kind':'gate','qubits':[n],'params':{'name':'X'},'reads':[],'writes':[],'condition':None,'after':[],'source_ids':[n]} for n in ('a','b')]
        graph=self.graph([node('a'),node('b')]); mapping={o['id']:{'node_id':o['id'],'source_operation':o} for o in ops}
        audit=DAGAudit('component',{},fixture=True); inspect_source_projection(audit,graph,ops,mapping,[],protocol_edges=[('a','b')])
        self.assertIn('DAG_PROTOCOL_EDGE_REMOVED',{f['code'] for f in audit.failures})

    def test_H10_algorithm_H_is_not_entry_preparation(self):
        op={'id':'first_H','kind':'gate','qubits':['A'],'params':{'name':'H'},'reads':[],'writes':[],'condition':None,'after':[],'source_ids':['src']}
        graph=self.graph([]); audit=DAGAudit('component',{},fixture=True)
        inspect_source_projection(audit,graph,[op],{},[op])
        self.assertIn('DAG_INVALID_ENTRY_MIGRATION',{f['code'] for f in audit.failures})


class EntryAndGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root=Path(__file__).resolve().parents[2]
        cls.state=json.loads((root/'configs/device/preinitialized_state_fixture.json').read_bytes())
        cls.device=json.loads((root/'configs/device/preinitialized_device.json').read_bytes())

    def test_H01_encoded_entry_with_two_dimensional_anchors(self):
        report=validate_preinitialized_entry(self.state,self.device)
        self.assertTrue(report['passed'],report['failures']); self.assertFalse(report['full_program_passed'])

    def test_H06_entry_does_not_supply_magic(self):
        state=deepcopy(self.state); state['ready_magic_tokens']=[{'token_id':'free-A'}]
        report=validate_preinitialized_entry(state,self.device)
        self.assertIn('ENTRY_FREE_MAGIC_OR_RESULTS',{f['code'] for f in report['failures']})

    def test_H09_physical_zero_does_not_imply_encoded_zero(self):
        state=deepcopy(self.state); state['atoms'][0]['initial_state']={'kind':'physical_basis','basis':'Z','value':0}
        report=validate_preinitialized_entry(state,self.device)
        self.assertIn('ENTRY_PHYSICAL_ZERO_NOT_ENCODED',{f['code'] for f in report['failures']})

    def test_D04_factory_atoms_cannot_appear_later(self):
        after=deepcopy(self.state); extra=deepcopy(after['atoms'][0]); extra.update(atom_id='new-magic',qubit_id='factory/W4/d0'); after['atoms'].append(extra)
        audit=DAGAudit('fixture_component',{},fixture=True)
        inspect_inventory_continuity(audit,self.state,[after],required_qubit_ids=['factory/W4/d0'])
        self.assertEqual({f['code'] for f in audit.failures},{'INITIAL_RESOURCE_INVENTORY_INCOMPLETE','WORLD_CARRIER_INVENTORY_CHANGED'})

    def test_H07_unused_real_placer_result(self):
        from na_pipeline.validation import validate_patch_placement
        root=Path(__file__).resolve().parents[2]
        b=json.loads(gzip.decompress((root/'knowledge/roles/R6/evidence/T605/frontend-placement-inputs.json.gz').read_bytes()))
        p=deepcopy(b['placements'][0]); first=next(iter(p['placements'])); p['placements'][first]['anchor_um'][0]+=60.
        r=validate_patch_placement(p,b['device'],b['example_dag'],observation=b['observations'][0],pin=b['pin'])
        self.assertIn('PLACEMENT_OUTPUT_UNUSED',{f['code'] for f in r['failures']})

    def test_D03_global_MZ_y_is_not_patch_translated(self):
        action={'id':'m','kind':'measure','atoms':['a'],'payload':{'site_id':'x0'}}
        y=self.device['grouped_profile']['layouts']['ancilla_readout']['slots']['x0']['position_um'][1]
        geometry={'snapshots':{('m','before'):{'a':{'position_um':[80.,y]}}}}
        audit=DAGAudit('fixture_component',{},fixture=True); inspect_mz_receiver(audit,[action],geometry,self.device)
        self.assertEqual(audit.failures,[])
        geometry['snapshots'][('m','before')]['a']['position_um'][1]+=60.
        audit=DAGAudit('fixture_component',{},fixture=True); inspect_mz_receiver(audit,[action],geometry,self.device)
        self.assertIn('MZ_PATCH_Y_TRANSLATION',{f['code'] for f in audit.failures})

    def test_H04_nine_bare_CZ_are_not_this_logical_CZ(self):
        gates=[{'name':'CZ','qubits':[f'control/d{i}',f'target/d{i}']} for i in range(9)]
        report=audit_css_coupling(gates,'CZ',fixture=True)
        self.assertFalse(report['passed']); self.assertIn('COUPLING_CODE_NOT_PRESERVED',{f['code'] for f in report['failures']})

    def test_H05_target_H_CZ_H_is_correct_CX(self):
        gates=[]
        for i in range(9):
            pair=[f'control/d{i}',f'target/d{i}']; gates.extend([{'name':'H','qubits':[pair[1]]},{'name':'CZ','qubits':pair},{'name':'H','qubits':[pair[1]]}])
        report=audit_css_coupling(gates,'CX',fixture=True)
        self.assertTrue(report['passed'],report['failures'])
        report=audit_css_coupling(gates,'CZ',fixture=True)
        self.assertIn('COUPLING_LOGICAL_ACTION',{f['code'] for f in report['failures']})


if __name__=='__main__': unittest.main()
