"""The public gate API must bind live ports, retain semantics and honor guards."""
from copy import deepcopy
import unittest
from unittest.mock import patch
from na_pipeline.device import canonical_surface17_device,build_preinitialized_state
from na_pipeline.qec import get_component_spec
from na_pipeline.backend import LogicalComponentCompiler
from na_pipeline.backend.enola_kernel import StrategyError
from na_pipeline.runtime import LogicalGateLibrary,EventSession,make_scenario,run,RuntimeContractError
from na_pipeline.runtime.parametric_component import CompiledComponentTemplate
from na_pipeline.validation.dag_physical import validate_physical_plan


def world(device,anchors):
    return build_preinitialized_state(device,{p:{'aod_group':'data','basis':'Z','value':0} for p in anchors},
        {p:{'anchor_um':a,'orientation':'x_vertical_z_horizontal'} for p,a in anchors.items()},
        placement_ref={'artifact_id':'fixture:public-interface','producer':'test','fixture':True})


class ComponentInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.device=canonical_surface17_device()
        compiler=LogicalComponentCompiler(cls.device)
        source=get_component_spec('CX')['physical_dag']
        entry=world(cls.device,{'control':[0.,900.],'target':[100.,900.]})
        compiler.build_dependencies(source,entry)
        cls.plan=compiler.compose_recipe(source,entry)
        cls.validation=validate_physical_plan(cls.plan,cls.device,trace=run(cls.plan['atom_program'],make_scenario(cls.plan['atom_program']),cls.device))
        assert cls.validation['passed'],cls.validation

    def library(self):
        library=LogicalGateLibrary(self.device);library.register('CX',self.plan,validation=self.validation)
        return library

    def test_changed_plan_or_device_cannot_inherit_demo_qualification(self):
        plan=deepcopy(self.plan);plan['physical_dags'][0]['nodes'][0]['params']['name']='CZ'
        with self.assertRaises(StrategyError) as e:self.library().register('changed',plan,validation=self.validation)
        self.assertEqual(e.exception.code,'COMPONENT_QUALIFICATION_MISMATCH')

    def test_same_template_across_anchors_and_spectator_with_no_batch_search(self):
        library=self.library();template_id=library.describe('CX')['template_id']
        for i,anchors in enumerate(({'A':[0.,900.],'B':[100.,900.]},{'A':[0.,600.],'B':[0.,900.]},
                                   {'A':[0.,600.],'B':[200.,900.],'spectator':[800.,500.]})):
            session=EventSession(self.device,world(self.device,anchors),run_id='test:'+str(i))
            with (patch('na_pipeline.backend.compiled_modules.module_graph',side_effect=AssertionError('internal recompose')),
                  patch('na_pipeline.backend.frontier_store.select_frontier',side_effect=AssertionError('internal batch selection'))):
                call=library.prepare('CX',session,operands={'control':'A','target':'B'},invocation_id='call-'+str(i))
            atom=call['atom_program'];session.submit(atom,make_scenario(atom),expected_revision=call['context']['revision']);session.advance()
            self.assertEqual(call['physical_plan']['parametric_component_instance']['component_template_id'],template_id)
            pulses=[a for a in atom['actions'] if a['kind']=='gate' and a['payload'].get('name')=='CZ']
            self.assertEqual([len(a['payload']['pairs']) for a in pulses],[9])
            self.assertEqual(len(atom['initial_state']['atoms']),17*len(anchors))
            # A prepared call cannot be submitted twice or after the world moved.
            with self.assertRaises(RuntimeContractError):session.submit(atom,make_scenario(atom),expected_revision=call['context']['revision'])

    def test_operand_alias_and_semantic_change_rejected_before_geometry(self):
        library=self.library()
        with self.assertRaises(StrategyError) as e:library.source('CX',operands={'control':'A','target':'A'},invocation_id='bad')
        self.assertEqual(e.exception.code,'COMPONENT_OPERAND_ALIAS')
        template=CompiledComponentTemplate(self.plan)
        source=template.instantiate_source({'control':'A','target':'B'},namespace='test')
        source[0]['nodes'][0]['params']['name']='CZ'
        with self.assertRaises(StrategyError) as e:template.bind_graph(source)
        self.assertEqual(e.exception.code,'COMPONENT_SEMANTICS_CHANGED')

    def test_warm_component_skips_leaf_binding_but_changed_scene_is_rechecked(self):
        library=self.library();session=EventSession(self.device,world(self.device,{'A':[0.,900.],'B':[100.,900.]}),run_id='warm')
        first=library.prepare('CX',session,operands={'control':'A','target':'B'},invocation_id='first')
        with patch.object(library.adapter.connections,'compose_recipe',side_effect=AssertionError('rebound leaves')):
            second=library.prepare('CX',session,operands={'control':'A','target':'B'},invocation_id='second')
        self.assertTrue(second['physical_plan']['whole_component_binding']['cache_hit'])
        self.assertFalse({a['id'] for a in first['atom_program']['actions']}&{a['id'] for a in second['atom_program']['actions']})
        changed=EventSession(self.device,world(self.device,{'A':[0.,900.],'B':[100.,900.],'C':[800.,500.]}),run_id='new-world')
        third=library.prepare('CX',changed,operands={'control':'A','target':'B'},invocation_id='third')
        self.assertFalse(third['physical_plan']['whole_component_binding']['cache_hit'])
        self.assertEqual(third['physical_plan']['parametric_component_instance']['all_world_atoms_checked'],51)


if __name__=='__main__':unittest.main()
