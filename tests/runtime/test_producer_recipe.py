from copy import deepcopy
from pathlib import Path
import json
import unittest

from na_pipeline.backend.enola_kernel import StrategyError, digest
from na_pipeline.device import canonical_surface17_device
from na_pipeline.runtime.compilation_guard import CompilationGuard
from na_pipeline.runtime.producer_recipe import derive_producer_recipe

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT/'artifacts/demos/joint-factory-repaired-20261008/factory.initialize'


class ProducerRecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads((SOURCE/'physical-plan.json').read_bytes())
        cls.report = json.loads((SOURCE/'validation.json').read_bytes())
        cls.device = canonical_surface17_device()

    def test_exact_source_projection_without_compile_or_rebatch(self):
        before = digest(self.plan)
        with CompilationGuard() as guard:
            template = derive_producer_recipe(self.plan, self.report, self.device)
        self.assertEqual(before, digest(self.plan))
        self.assertEqual(guard.receipt()['violation_count'], 0)
        self.assertEqual(template.derivation['producer_operation_count'], 880)
        self.assertEqual(template.derivation['removed_data_maintenance_count'], 168)
        self.assertFalse(template.derivation['geometry_qualification_inherited'])
        self.assertFalse(any(q.startswith('live_data/') for n in template.operations for q in n['qubits']))
        for row in template.derivation['partitions']:
            self.assertEqual(row['retained_source_ids'], [s for s in row['parent_source_ids']
                if s not in template.input_boundary['removed_data_operations']])

    def test_changed_parent_bytes_rejected(self):
        changed = deepcopy(self.plan)
        changed['physical_dags'][0]['nodes'][0]['params']['basis'] = 'X'
        with self.assertRaisesRegex(StrategyError, 'PRODUCER_PARENT_QUALIFICATION'):
            derive_producer_recipe(changed, self.report, self.device)

    def test_new_factory_operation_cannot_be_silently_removed(self):
        changed = deepcopy(self.plan)
        n = deepcopy(changed['physical_dags'][0]['nodes'][0])
        n['id'] += '-unexpected'
        changed['physical_dags'][0]['nodes'].append(n)
        report = deepcopy(self.report)
        report['input_sha256']['physical_plan'] = digest(changed)
        with self.assertRaisesRegex(StrategyError, 'PRODUCER_DROPPED_FACTORY_OPERATION'):
            derive_producer_recipe(changed, report, self.device)

    def test_internal_partition_cannot_omit_a_retained_operation(self):
        changed = deepcopy(self.plan)
        changed['module_composition']['dependency_graph']['modules'][0]['source_ids'].pop(0)
        report = deepcopy(self.report)
        report['input_sha256']['physical_plan'] = digest(changed)
        with self.assertRaisesRegex(StrategyError, 'PRODUCER_PARTITION_ORDER|PRODUCER_SOURCE_COVERAGE'):
            derive_producer_recipe(changed, report, self.device)


if __name__ == '__main__':
    unittest.main()
