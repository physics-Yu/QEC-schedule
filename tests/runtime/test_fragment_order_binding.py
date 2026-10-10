"""Permutation reuse must preserve directed gates and full-scene legality."""
from copy import deepcopy
import unittest
from na_pipeline.backend import LogicalComponentCompiler
from na_pipeline.backend.enola_kernel import StrategyError
from na_pipeline.device import canonical_surface17_device,build_preinitialized_state
from na_pipeline.runtime.compilation_guard import CompilationGuard
from na_pipeline.runtime.fragment_order_binding import OrderInvariantModuleLibrary
from na_pipeline.runtime import run,make_scenario
from na_pipeline.validation.dag_physical import validate_physical_plan


class FragmentOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.device=canonical_surface17_device()
        cls.world=build_preinitialized_state(cls.device,
            {p:{'aod_group':'data','basis':'Z','value':0} for p in ('control','target')},
            {p:{'anchor_um':[100.*i,900.],'orientation':'x_vertical_z_horizontal'} for i,p in enumerate(('control','target'))},
            placement_ref={'artifact_id':'fixture:order-binding','producer':'test','fixture':True})
        cls.dag=LogicalComponentCompiler(cls.device).instantiate('CX')
        lib=OrderInvariantModuleLibrary(cls.device)
        cls.native=lib.compile_module(cls.dag,cls.world)

    def library(self):
        lib=OrderInvariantModuleLibrary(self.device)
        lib.cache[self.native['body']['key']]=[deepcopy(self.native)]
        return lib

    def reversed(self):
        dag=deepcopy(self.dag);dag['nodes'].reverse();return dag

    def test_permuted_same_batch_binds_without_native_compile(self):
        lib=self.library();dag=self.reversed()
        with CompilationGuard():plan=lib.get_or_build(dag,self.world,instance_id='reordered',build_missing=False)
        self.assertEqual(lib.stats['leaf_compile_count'],0)
        self.assertEqual(lib.order_bindings,1)
        receipt=plan['module_binding']['source_order_binding']
        self.assertFalse(receipt['batch_membership_changed'])
        self.assertFalse(receipt['native_actions_changed'])
        self.assertEqual({o['id'] for o in plan['source']['operations']},{o['id'] for o in dag['nodes']})
        self.assertEqual(plan['module_binding']['module_hash'],self.native['hash'])
        trace=run(plan['atom_program'],make_scenario(plan['atom_program']),self.device)
        self.assertTrue(validate_physical_plan(plan,self.device,trace=trace)['passed'])

    def test_direction_or_dependency_change_does_not_gain_cache_hit(self):
        for mutation in ('direction','dependency'):
            lib=self.library();dag=self.reversed()
            if mutation=='direction':dag['nodes'][0]['qubits'].reverse()
            else:dag['nodes'][0]['after']=[dag['nodes'][1]['id']]
            with self.subTest(mutation=mutation),CompilationGuard():
                with self.assertRaisesRegex(StrategyError,'MODULE_DEPENDENCY_MISSING'):
                    lib.get_or_build(dag,self.world,instance_id='bad',build_missing=False)
            self.assertEqual(lib.stats['leaf_compile_count'],0)

    def test_permutation_still_checks_full_world_spectator_conflicts(self):
        lib=self.library();plan=lib.bind_module(self.native,self.dag,self.world,instance_id='original')
        move=next(a for a in plan['atom_program']['actions'] if a['kind']=='move')
        position=move['payload']['trajectories'][0]['to_um'];world=deepcopy(self.world)
        atom=deepcopy(world['atoms'][0]);atom.update(atom_id='extra',qubit_id='extra/q',site_id='extra/q',trap_id='slm:extra',position_um=position)
        world['atoms'].append(atom);world['slm_traps'].append({'trap_id':'slm:extra','position_um':position,'zone_id':self.device['broadcast']['zone_id'],'occupant':'extra'})
        with CompilationGuard(),self.assertRaisesRegex(StrategyError,'MODULE_DEPENDENCY_MISSING'):
            lib.get_or_build(self.reversed(),world,instance_id='blocked',build_missing=False)
        self.assertEqual(lib.stats['leaf_compile_count'],0)
        self.assertEqual(lib.order_bindings,0)


if __name__=='__main__':unittest.main()
