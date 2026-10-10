from pathlib import Path
from copy import deepcopy
import json
import unittest
from na_pipeline.device import canonical_surface17_device
from na_pipeline.backend.enola_kernel import StrategyError,digest
from na_pipeline.runtime.canonical_cz_recipe import derive_canonical_cz_recipe
from na_pipeline.runtime.compilation_guard import CompilationGuard

ROOT=Path(__file__).resolve().parents[2]


class CanonicalCZRecipeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        old=ROOT/'artifacts/demos/aod-held-cz-20261007/CZ';bare=ROOT/'artifacts/demos/joint-factory-repaired-20261008/CZ'
        read=lambda p:json.loads(p.read_bytes())
        cls.args=[read(old/'physical-plan.json'),read(old/'validation.json'),read(old/'device.json'),
                  read(bare/'physical-plan.json'),read(bare/'validation.json'),canonical_surface17_device()]

    def test_exact_pair_equivalence_and_carrier_restore_without_compilation(self):
        with CompilationGuard(): t=derive_canonical_cz_recipe(*self.args)
        proof=t.derivation
        self.assertEqual(proof['effective_right_partners'],proof['expected_right_partners'])
        self.assertEqual(proof['final_carrier_order'],list(range(9)))
        self.assertEqual(proof['native_CZ_pairs'],9)
        self.assertEqual(proof['added_quantum_gates'],[])
        self.assertEqual(t.ports['right']['sites']['d1'],[20.,0.])
        self.assertFalse(proof['geometry_qualification_inherited'])
        self.assertNotIn('logical_H_transversal_plus_atom_transport',str(t.__dict__))

    def test_alias_pair_is_rejected(self):
        args=deepcopy(self.args);args[3]['physical_dags'][0]['nodes'][1]['qubits'][1]='right/d2'
        args[4]['input_sha256']['physical_plan']=digest(args[3])
        with self.assertRaisesRegex(StrategyError,'CZ_ADAPTER_BIJECTION'):derive_canonical_cz_recipe(*args)


if __name__=='__main__': unittest.main()
