"""Real-producer smoke checks for T010; no quantum-state simulation."""
import copy
import unittest


class TwoBlockPipelineTests(unittest.TestCase):
    def test_real_modules_connect_and_reject_source_corruption(self):
        from na_pipeline.device import default_device, validate_device
        from na_pipeline.qec import build_two_block_slice, iter_physical_ops
        from na_pipeline.backend import compile_physical
        from na_pipeline.runtime import run, make_scenario
        from na_pipeline.validation import validate

        device = default_device()
        self.assertEqual(validate_device(device), [])
        physical = build_two_block_slice(rounds=1)
        self.assertEqual(len(physical['qubits']), 34)
        before = copy.deepcopy(physical)
        physical_ids = {op['id'] for op in iter_physical_ops(physical)}
        plan = compile_physical(physical, device)
        self.assertTrue(plan['complete'])
        self.assertEqual(physical, before, 'Compilation mutated its source program')
        self.assertEqual(set(plan['source_map']), physical_ids)
        self.assertTrue(all(plan['source_map'].values()))

        trace = run(plan, make_scenario(plan, value=0), device)
        self.assertFalse(trace['quantum_state_simulated'])
        self.assertFalse(trace['hardware_executed'])
        self.assertFalse(trace['loss_enabled'])
        report = validate(plan, device, trace=trace, physical_program=physical)
        self.assertTrue(report['passed'], repr({'failures': report['failures'][:5], 'unverified': report['unverified']}))

        corrupted = copy.deepcopy(plan)
        corrupted['source_map'].pop(next(iter(physical_ids)))
        rejected = validate(corrupted, device, trace=trace, physical_program=physical)
        self.assertFalse(rejected['passed'], 'Independent validation missed a dropped source mapping')

    def test_distinct_fake_inputs_keep_instance_results_separate(self):
        from na_pipeline.device import default_device
        from na_pipeline.qec import build_two_block_slice
        from na_pipeline.backend import compile_physical
        from na_pipeline.runtime import run, make_scenario
        from na_pipeline.validation import validate

        device = default_device()
        physical = build_two_block_slice(rounds=1)
        plan = compile_physical(physical, device)
        saved = copy.deepcopy(plan)
        zero = run(plan, make_scenario(plan, value=0), device)
        one = run(plan, make_scenario(plan, value=1), device)
        self.assertEqual(plan, saved, 'Runtime mutated the shared compile plan')
        self.assertTrue(zero['results'])
        self.assertEqual(set(zero['results']), set(one['results']))
        self.assertTrue(all(v['value'] == 0 for v in zero['results'].values()))
        self.assertTrue(all(v['value'] == 1 for v in one['results'].values()))
        self.assertTrue(validate(plan, device, trace=one, physical_program=physical)['passed'])


if __name__ == '__main__':
    unittest.main()
