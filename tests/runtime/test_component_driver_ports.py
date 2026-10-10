"""Main ComponentPipeline actually calls prepare_dags and reuses geometry."""
import unittest,tempfile
from pathlib import Path
from na_pipeline.backend import LogicalComponentCompiler
from na_pipeline.qec import get_component_spec
from na_pipeline.runtime import LogicalGateLibrary,run,make_scenario
from na_pipeline.runtime.component_pipeline import ComponentPipeline
from na_pipeline.validation.dag_physical import validate_physical_plan
import test_pipeline


class ComponentDriverPortTests(unittest.TestCase):
    def test_driver_routes_actual_nodes_through_new_interface(self):
        world=test_pipeline.PipelineTests().world();device=world['device']
        compiler=LogicalComponentCompiler(device)
        spec=get_component_spec('X');binding={q['id']:'P0/'+q['local_id'] for q in spec['formal_qubits']}
        dag=compiler.instantiate('X',qubit_bindings=binding,namespace='qualified-X')
        compiler.build_dependencies(dag,world['initial_state']);plan=compiler.compose_recipe(dag,world['initial_state'])
        report=validate_physical_plan(plan,device,trace=run(plan['atom_program'],make_scenario(plan['atom_program']),device))
        with tempfile.TemporaryDirectory() as d:
            library=LogicalGateLibrary(device,connection_directory=Path(d)/'modules')
            library.register('X',plan,validation=report)
            driver=ComponentPipeline(world,Path(d)/'run',phase_bits=[0]*8,compiler=library)
            driver.step();driver.step()
            self.assertTrue(driver.status()['complete_source_path'])
            self.assertEqual(library.stats['recipe_build_count'],1)
            self.assertEqual(library.stats['geometry_cache_hits'],1)
            self.assertEqual(driver.session.export_trace()['stats']['action_count'],6)
            restored=ComponentPipeline.restore(world,Path(d)/'run',driver.checkpoint(),compiler=library)
            self.assertEqual(restored.status()['complete_source_path'],True)


if __name__=='__main__':unittest.main()
