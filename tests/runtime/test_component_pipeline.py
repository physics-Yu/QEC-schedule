"""Whole-call reuse must still execute new instances and reject missing recipes."""
from pathlib import Path
import tempfile
import unittest
import json
from unittest.mock import patch

from test_pipeline import PipelineTests
from na_pipeline.runtime.component_recipe import ComponentRecipeLibrary
from na_pipeline.runtime.component_pipeline import ComponentPipeline
from na_pipeline.backend.enola_kernel import StrategyError


class ComponentPipelineTests(unittest.TestCase):
    def test_frozen_SE_batches_are_reused_without_frontier_search(self):
        from na_pipeline.device import canonical_surface17_device,build_preinitialized_state
        from na_pipeline.qec.component_catalog import get_component_spec
        from na_pipeline.runtime import EventSession,bind_physical_plan,make_scenario
        device=canonical_surface17_device();dag=get_component_spec('SE')['physical_dag']
        world=build_preinitialized_state(device,{'block':{'aod_group':'data','basis':'Z','value':0}},
            {'block':{'anchor_um':[0.,900.],'orientation':'x_vertical_z_horizontal'}},
            placement_ref={'artifact_id':'fixture:opaque-SE','producer':'test','fixture':True})
        fixture=Path(__file__).resolve().parents[1]/'fixtures/basic-se-schedule.json'
        schedules=json.loads(fixture.read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'schedules').mkdir();(root/'schedules/index.json').write_bytes(fixture.read_bytes())
            library=ComponentRecipeLibrary(device,root,build_missing=True)
            with patch('na_pipeline.backend.frontier_store.select_frontier',side_effect=AssertionError('global frontier search')):
                strategy=library.get_or_compile(dag,world)
            session=EventSession(device,world,run_id='fresh-SE-component')
            context=session.compilation_context(dag);plan=library.bind(strategy,dag,session.snapshot()['world_state'],execution_context=context)
            atom=bind_physical_plan(plan,context);session.submit(atom,make_scenario(atom));session.advance()
            pulses=[a for a in atom['actions'] if a['kind']=='gate' and a['payload'].get('name')=='CZ']
            self.assertEqual([len(a['payload']['pairs']) for a in pulses],[len(v) for v in next(iter(schedules.values()))['batches']])
            self.assertEqual(sum(len(a['payload']['pairs']) for a in pulses),24)
            self.assertEqual(library.stats['module_stats']['frontier_search_count'],0)

    def test_prepared_recipe_reused_in_fresh_complete_session_without_compiler(self):
        world=PipelineTests().world()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            build=ComponentRecipeLibrary(world['device'],root/'recipes',build_missing=True)
            warm=ComponentPipeline(world,root/'prepare',phase_bits=[0]*8,compiler=build)
            warm.step();warm.step()
            self.assertTrue(warm.status()['complete_source_path'])
            self.assertEqual(build.stats['recipe_build_count'],1)
            frozen=ComponentRecipeLibrary(world['device'],root/'recipes',build_missing=False)
            final=ComponentPipeline(world,root/'execute',phase_bits=[0]*8,compiler=frozen)
            with patch.object(frozen.components,'build_dependencies',side_effect=AssertionError('native rebuild')):
                final.step()
                resumed=ComponentPipeline.restore(world,root/'execute',final.checkpoint(),compiler=frozen)
                resumed.step()
            self.assertTrue(resumed.status()['complete_source_path'])
            self.assertEqual(resumed.session.export_trace()['stats']['action_count'],6)
            self.assertEqual(frozen.stats['recipe_build_count'],0)
            self.assertEqual(frozen.stats['bind_count'],2)
            self.assertEqual(frozen.stats['module_stats']['leaf_compile_count'],0)
            self.assertEqual(len(list((root/'execute'/'window-index').glob('*.json'))),2)

    def test_execution_does_not_silently_build_missing_component(self):
        world=PipelineTests().world()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            library=ComponentRecipeLibrary(world['device'],root/'recipes',build_missing=False)
            driver=ComponentPipeline(world,root/'run',phase_bits=[0]*8,compiler=library)
            with self.assertRaises(StrategyError) as error:driver.step()
            self.assertEqual(error.exception.code,'COMPONENT_RECIPE_MISSING')
            self.assertEqual(driver.session.now_us,0)


if __name__=='__main__':unittest.main()
