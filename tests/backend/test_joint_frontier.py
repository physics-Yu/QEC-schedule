"""Cross-block frontier, source-scope, immutable choices and real readout tests."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from pathlib import Path
import json,tempfile

from na_pipeline.qec.factory_primitives import Circuit
from na_pipeline.qec.physical_dag import _program, physical_dag_from_program
from na_pipeline.backend import LogicalComponentCompiler
from na_pipeline.device import canonical_surface17_device, build_preinitialized_state
from na_pipeline.runtime import run, make_scenario
from na_pipeline.validation.dag_physical import validate_physical_plan


class JointFrontierTests(unittest.TestCase):
    def test_committed_mixed_twelve_pair_batch_is_one_pulse_in_complete_world(self):
        from na_pipeline.backend import compile_physical_dag
        fixture = json.loads((Path(__file__).parents[1] / 'fixtures/joint_batch_12_pairs.json').read_bytes())
        dag, world, device = (fixture[k] for k in ('dag', 'world', 'device'))
        self.assertEqual(len(world['atoms']), 137)  # Includes every spectator.
        self.assertEqual(fixture['provenance']['old_pulse_pairs'], [11, 1])
        plan = compile_physical_dag(dag, device, world)
        atom = plan['atom_program']
        pulses = [a for a in atom['actions'] if a['payload'].get('name') == 'CZ']
        self.assertEqual([len(a['payload']['pairs']) for a in pulses], [12])
        self.assertEqual({s['physical_op_id'] for s in pulses[0]['payload']['pair_sources']},
                         {o['id'] for o in dag['nodes']})
        # All twelve physical CX operations retain their two target H gates.
        hs = [a for a in atom['actions'] if a['payload'].get('name') == 'H']
        self.assertEqual(len(hs), 24)
        report = validate_physical_plan(plan, device, trace=run(atom, make_scenario(atom), device))
        self.assertTrue(report['passed'], report)
        self.assertFalse(report['unverified'], report)

    def test_composition_rejects_a_reserialized_committed_leaf(self):
        from na_pipeline.backend.enola_kernel import StrategyError
        c = Circuit(); c.gate('cx', 'CX', ['A_d0', 'A_d1'])
        dag, world, compiler, _ = self.setup_plan(c)
        original = compiler.modules.get_or_build

        def broken_leaf(*args, **kwargs):
            plan = deepcopy(original(*args, **kwargs))
            pulse = next(a for a in plan['atom_program']['actions'] if a['payload'].get('name') == 'CZ')
            plan['atom_program']['actions'].append(deepcopy(pulse))
            return plan

        with patch.object(compiler.modules, 'get_or_build', side_effect=broken_leaf):
            with self.assertRaisesRegex(StrategyError, 'COMMITTED_BATCH_RESERIALIZED'):
                compiler.compose_recipe(dag, world)

    def test_ordinary_frontier_keeps_direction_policy_until_batch_is_committed(self):
        from na_pipeline.backend.physical_window import PhysicalWindowCompiler
        original = PhysicalWindowCompiler.select_entangle
        observed = []

        def observe(compiler, operations):
            observed.append(compiler.closed_coupling_batch)
            return original(compiler, operations)

        c = Circuit(); c.syndrome('A', 'SE_A', rounds=1)
        with patch.object(PhysicalWindowCompiler, 'select_entangle', observe):
            _, _, _, plan = self.setup_plan(c)
        self.assertIn(False, observed)  # The open, multi-direction frontier.
        self.assertIn(True, observed)  # Its selected ready-only leaves.
        pulses = [a for a in plan['atom_program']['actions'] if a['payload'].get('name') == 'CZ']
        self.assertEqual([len(a['payload']['pairs']) for a in pulses], [6, 3, 6, 3, 6])

    def setup_plan(self, circuit, separate_arrays=False, readout_capacity=None):
        dag=physical_dag_from_program(_program(circuit,{'A':'A','B':'B'},'joint-frontier-test'),operation='MODULE_FRAGMENT')
        device=canonical_surface17_device(readout_capacity=readout_capacity)
        groups={b:'magic' if separate_arrays and b=='B' else 'data' for b in ('A','B')}
        for q in dag['qubits']:q['aod_group']=groups[q['id'].split('/')[0]]
        world=build_preinitialized_state(device,{b:{'aod_group':groups[b],'basis':'Z','value':0} for b in ('A','B')},
            {b:{'anchor_um':[100.*i,900.],'orientation':'x_vertical_z_horizontal'} for i,b in enumerate(('A','B'))},
            placement_ref={'artifact_id':'joint-test','producer':'R0','fixture':True})
        compiler=LogicalComponentCompiler(device);plan=compiler.build_dependencies(dag,world)
        atom=plan['atom_program'];report=validate_physical_plan(plan,device,trace=run(atom,make_scenario(atom),device))
        self.assertTrue(report['passed'],report)
        return dag,world,compiler,plan

    def test_two_blocks_share_SE_pulses_and_one_readout_transport(self):
        c=Circuit()
        for b in ('A','B'):c.syndrome(b,'SE_'+b,rounds=1)
        dag,world,compiler,plan=self.setup_plan(c)
        pulses=[a for a in plan['atom_program']['actions'] if a['payload'].get('name')=='CZ']
        self.assertEqual([len(a['payload']['pairs']) for a in pulses],[12,6,12,6,12])
        self.assertEqual(len(plan['measurement_placements']),1)
        self.assertEqual(len(plan['measurement_placements'][0]['measured_atoms']),16)
        self.assertEqual(len(plan['measurement_placements'][0]['source_group_ids']),2)
        before=compiler.modules.stats
        with patch('na_pipeline.backend.physical_window.PhysicalWindowCompiler.select_entangle',side_effect=AssertionError('bind must not search')):
            replay=compiler.compose_recipe(dag,world)
        self.assertEqual(compiler.modules.stats['frontier_search_count'],before['frontier_search_count'])
        self.assertEqual(replay['atom_program']['actions'],plan['atom_program']['actions'])

    def test_different_phases_can_enter_same_native_CZ_batch(self):
        c=Circuit()
        for b,phase in [('A','raw_encoding'),('B','SE')]:
            c.gate('mixed_'+b,'CX',[b+'_d0',b+'_d1'],metadata={'phase':phase})
        _,_,_,plan=self.setup_plan(c)
        pulses=[a for a in plan['atom_program']['actions'] if a['payload'].get('name')=='CZ']
        self.assertEqual([len(a['payload']['pairs']) for a in pulses],[2])
        front=plan['module_composition']['dependency_graph']['joint_frontiers'][0]
        self.assertEqual(set(front['ready_source_ids']),set(front['selected_source_ids']))

    def test_block_local_prepare_and_fold_do_not_fence_other_blocks(self):
        c=Circuit();c.prepare('A','plus','prep_A');c.gate('independent_B','X',['B_d0'])
        self.assertEqual(c.nodes[-1]['op']['after'],[])
        c=Circuit();c.clifford_phase('A',1,'phase_A');c.gate('independent_B','X',['B_d0'])
        self.assertEqual(c.nodes[-1]['op']['after'],[])
        # The within-block fold still has the complete half-cycle dependency.
        fold=[n['op'] for n in c.nodes if n['op'].get('metadata',{}).get('se_stage')=='half_cycle_fold']
        self.assertTrue(all(o['after'] for o in fold))

    def test_short_source_port_releases_before_unrelated_long_wait(self):
        c=Circuit();c.add('wait_A','wait',['A_d0'],{'duration_us':100.})
        c.gate('first_B','H',['B_d0']);c.gate('second_B','H',['B_d0'])
        _,_,_,plan=self.setup_plan(c)
        actions=plan['atom_program']['actions']
        b=[a for a in actions if a['payload'].get('name')=='H']
        self.assertEqual([a['t_start_us'] for a in b],[0.,1.])
        self.assertEqual(plan['atom_program']['stats']['duration_us'],100.)

    def test_independent_AODs_share_CZ_and_transport_only_with_sweep_certificate(self):
        c=Circuit()
        for b in ('A','B'):c.syndrome(b,'SE_'+b,rounds=1)
        _,_,_,plan=self.setup_plan(c,separate_arrays=True)
        actions=plan['atom_program']['actions'];pulses=[a for a in actions if a['payload'].get('name')=='CZ']
        self.assertEqual([len(a['payload']['pairs']) for a in pulses],[12,6,12,6,12])
        pickup=[a for a in actions if a['kind']=='pickup' and a['payload'].get('purpose')=='enola_cz_transport']
        self.assertEqual(len(pickup),10)
        self.assertEqual(len({a['t_start_us'] for a in pickup}),5)
        readouts=[a for a in actions if a['kind']=='measure']
        self.assertEqual(len(readouts),16)
        self.assertEqual(len({a['t_start_us'] for a in readouts}),1)
        self.assertTrue(all(p['independent_array_parallelism']['qualified'] for p in plan['measurement_placements']))

    def test_overlapping_swept_envelopes_are_not_treated_as_qualified(self):
        from na_pipeline.backend.independent_arrays import separate_sweep_envelopes
        from na_pipeline.backend.enola_kernel import StrategyError
        scene=[{'atom_id':'a','position_um':[0.,0.]},{'atom_id':'b','position_um':[10.,0.]}]
        with self.assertRaisesRegex(StrategyError,'INDEPENDENT_AOD_SWEEP_NOT_QUALIFIED'):
            separate_sweep_envelopes(scene,{'data':[{'a':[10.,0.]}],'magic':[{'b':[0.,0.]}]},1e-6)

    def test_independent_arrays_do_not_multiply_a_global_readout_limit(self):
        c=Circuit()
        for b in ('A','B'):c.syndrome(b,'SE_'+b,rounds=1)
        _,_,_,plan=self.setup_plan(c,separate_arrays=True,readout_capacity=8)
        reads=[a for a in plan['atom_program']['actions'] if a['kind']=='measure']
        self.assertEqual(len({a['t_start_us'] for a in reads}),2)
        self.assertTrue(all(p['independent_array_parallelism']['reason']=='INDEPENDENT_READOUT_CAPACITY' for p in plan['measurement_placements']))

    def test_lookup_index_replacement_cannot_replace_a_plan_receipt(self):
        c=Circuit();c.gate('cx','CX',['A_d0','A_d1'])
        dag,world,_,_=self.setup_plan(c)
        with tempfile.TemporaryDirectory() as folder:
            compiler=LogicalComponentCompiler(canonical_surface17_device(),module_directory=folder)
            plan=compiler.build_dependencies(dag,world)
            f=plan['module_composition']['dependency_graph']['joint_frontiers'][0]
            proof=Path(folder)/f['artifact_file'];original=proof.read_bytes()
            # The mutable acceleration index is deliberately invalidated. The
            # exact build witness already referenced by the plan remains intact.
            (Path(folder)/f['lookup_file']).write_text('{}',encoding='utf-8')
            self.assertEqual(proof.read_bytes(),original)
            self.assertEqual(json.loads(original)['hash'],f['decision_hash'])

if __name__=='__main__':unittest.main()
