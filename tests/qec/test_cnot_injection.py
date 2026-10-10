"""Independent two-qubit branch amplitudes and the actual factory source."""
import cmath
import unittest

from na_pipeline.qec.factory import build_factory15to1_protocol, factory_stage_program
from na_pipeline.qec.program import iter_physical_ops
from na_pipeline.validation.dag_coupling import audit_css_coupling


class CnotInjectionTests(unittest.TestCase):
    def test_both_measured_branches_on_an_arbitrary_input(self):
        # Build each column of K_m = <m| CX (I tensor |A+>).
        w = cmath.exp(1j * cmath.pi / 4)
        for requested in ('T', 'TDG'):
            protocol = build_factory15to1_protocol(gate=requested)
            stage = protocol['stages']['consume']
            for outcome in (0, 1):
                target = stage['branch']['one' if outcome else 'zero']
                correction = 1
                if target == 'consume_correction':
                    correction = 1j if requested == 'T' else -1j
                want = w if requested == 'T' else w.conjugate()
                columns = []
                for data_bit in (0, 1):
                    state = [0j] * 4
                    for magic_bit, amplitude in enumerate((1, w)):
                        state[2 * data_bit + (magic_bit ^ data_bit)] = amplitude / 2**.5
                    columns.append([state[2 * bit + outcome] * (correction if bit else 1)
                                    for bit in (0, 1)])
                self.assertAlmostEqual(abs(columns[0][1]), 0.)
                self.assertAlmostEqual(abs(columns[1][0]), 0.)
                self.assertAlmostEqual(abs(columns[1][1] / columns[0][0] - want), 0.)

    def test_real_factory_uses_data_control_and_magic_Z_target(self):
        p = build_factory15to1_protocol()
        for stage_id in [f'rotate_{i:02}' for i in range(4, 15)] + ['consume']:
            ops = list(iter_physical_ops(factory_stage_program(p, stage_id)))
            stem = 'consume_cnot_' if stage_id == 'consume' else 'inject_cnot_'
            gates = [o for o in ops if stem in o['id']]
            self.assertEqual(len(gates), 9)
            self.assertTrue(all(o['params']['name'] == 'CX' for o in gates))
            control = 'live_data' if stage_id == 'consume' else 'factory0:' + p['stages'][stage_id]['rotation']['pivot']
            magic = 'factory0:W4' if stage_id == 'consume' else 'factory0:M'
            self.assertEqual([o['qubits'] for o in gates], [[f'{control}/d{i}', f'{magic}/d{i}'] for i in range(9)])
            self.assertFalse(any(o.get('metadata', {}).get('joint_check') for o in ops))
            branch = next(o for o in ops if p['stages'][stage_id]['branch']['result_id'] in o['writes'])
            self.assertEqual(len(branch['reads']), 3)
            self.assertTrue(all(r.endswith(tuple(f'_m_d{i}' for i in (0, 1, 2))) for r in branch['reads']))

    def test_CZ_pairing_positive_and_wrong_pairing_counterexamples(self):
        for mapping, expected in (([2,5,8,1,4,7,0,3,6], True), (list(range(9)), False),
                                  ([0,3,6,1,4,7,2,5,8], False)):
            gates = [{'name': 'CZ', 'qubits': [f'control/d{i}', f'target/d{j}']} for i,j in enumerate(mapping)]
            self.assertEqual(audit_css_coupling(gates, 'CZ')['passed'], expected)
