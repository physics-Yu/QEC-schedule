"""Independent static-semantic positive and mutation cases for T602."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from na_pipeline.frontend import build_shor15,postprocess_phase
from na_pipeline.qec import build_two_block_slice
from na_pipeline.validation import audit_shor15,audit_surface17


class FrontendSemanticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.program=build_shor15()
        cls.cases=[postprocess_phase([(y>>(7-i))&1 for i in range(8)],N=N,a=a) for N,a in [(15,2),(21,2),(21,3)] for y in range(256)]

    def reject(self,mutate,code):
        p=deepcopy(self.program); mutate(p)
        r=audit_shor15(p,self.cases)
        self.assertFalse(r['passed'])
        self.assertIn(code,{f['code'] for f in r['failures']},r['failures'][:5])

    def test_actual_source_and_synthesis(self):
        r=audit_shor15(self.program,self.cases)
        self.assertTrue(r['passed'],r['failures'])
        self.assertEqual(r['metrics']['controlled_inputs_checked'],96)
        self.assertEqual(r['metrics']['phase_round_identities'],2048)
        self.assertEqual(r['metrics']['all_conditions_true_t_like'],817)

    def test_independent_of_producer_checks(self):
        with patch('na_pipeline.frontend.validate_logical',side_effect=AssertionError()),patch('na_pipeline.frontend.iter_logical_ops',side_effect=AssertionError()),patch('na_pipeline.frontend.operator_certificate.certify_rotation',side_effect=AssertionError()),patch('na_pipeline.frontend.synthesis.audit_synthesis',side_effect=AssertionError()):
            self.assertTrue(audit_shor15(self.program,self.cases)['passed'])

    def test_relative_phase_error_not_hidden_by_boolean_permutation(self):
        def mutate(p):
            t=p['templates']['controlled_mul2/1']; op=deepcopy(t['body'][0]); op['op'].update(id='phase-error',qubits=['ctrl'],params={'name':'Z'})
            t['body'].insert(0,op)
        self.reject(mutate,'MODULAR_OPERATOR')

    def test_multiplier_call_binding_changed(self):
        self.reject(lambda p:next(n for n in p['body'] if n.get('id')=='round0/multiply')['bindings'].update(w0='w1'),'QPE_CONTROLLED_POWER')

    def test_feedback_angle_sign_changed(self):
        self.reject(lambda p:next(n['op'] for n in p['body'] if n['kind']=='op' and n['op']['id']=='round6/feedback_from_7')['params']['angle_pi'].update(numerator=1),'FEEDBACK_ANGLE')

    def test_measurement_bit_order_changed(self):
        self.reject(lambda p:p['bit_order']['measurement_order'].reverse(),'PHASE_BIT_ORDER')

    def test_dependency_not_just_body_order(self):
        self.reject(lambda p:next(n['op'] for n in p['body'] if n['kind']=='op' and n['op']['id']=='round7/readout_h').update(after=[]),'LOGICAL_QUBIT_ORDER')

    def test_zero_reset_semantics(self):
        self.reject(lambda p:p['body'][0]['op']['params'].update(value=1),'QPE_RESET')

    def test_synthesis_word_mutation(self):
        def mutate(p):
            ref=next(iter(p['synthesis_certificates']))
            p['templates'][ref]['body'][0]['op']['params']['name']='H'
        self.reject(mutate,'SYNTHESIS_BOUND_UNDERSTATED')

    def test_synthesis_bound_forged(self):
        self.reject(lambda p:next(iter(p['synthesis_certificates'].values())).update(operator_error_upper_bound='0'),'SYNTHESIS_BOUND_UNDERSTATED')

    def test_synthesis_matrix_enclosure_forged(self):
        self.reject(lambda p:next(iter(p['synthesis_certificates'].values()))['corrected_matrix_intervals'][0][0].update(real=['0','0']),'SYNTHESIS_MATRIX_ENCLOSURE')

    def test_global_phase_ledger_is_required(self):
        self.reject(lambda p:p.update(branch_global_phases=[]),'BRANCH_PHASE_LEDGER')

    def test_classical_phase_scope_cannot_be_coherent(self):
        self.reject(lambda p:next(n for n in p['body'] if n.get('synthesis_certificate_ref')).update(condition_scope='quantum'),'SYNTHESIS_PHASE_SCOPE')

    def test_total_t_count_from_actual_words(self):
        self.reject(lambda p:p['resource_summary'].update(total_t_like=35),'T_DEMAND_COUNT')

    def test_postprocess_factors_forged(self):
        cases=deepcopy(self.cases); next(r for r in cases if r['status']=='success')['factors']=[1,15]
        r=audit_shor15(self.program,cases)
        self.assertIn('POSTPROCESS_SEMANTICS',{f['code'] for f in r['failures']})

    def test_missing_cases_remain_unverified(self):
        r=audit_shor15(self.program,self.cases[:10])
        self.assertFalse(r['passed']); self.assertIn('POSTPROCESS_COVERAGE',{x['code'] for x in r['unverified']})

    def test_unresolved_symbolic_source_not_complete(self):
        r=audit_shor15(build_shor15(synthesize=False),self.cases)
        self.assertTrue(r['scoped_pass'],r['failures'])
        self.assertFalse(r['passed']); self.assertIn('SYNTHESIS_UNRESOLVED',{x['code'] for x in r['unverified']})


class SurfaceSemanticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.program=build_two_block_slice()

    def reject(self,mutate,code):
        p=deepcopy(self.program); mutate(p); r=audit_surface17(p)
        self.assertFalse(r['passed']); self.assertIn(code,{f['code'] for f in r['failures']},r['failures'][:6])

    def test_actual_surface17(self):
        r=audit_surface17(self.program)
        self.assertTrue(r['passed'],r['failures'])
        self.assertEqual(r['metrics']['stabilizer_rank'],8)
        self.assertEqual(r['metrics']['static_code_distance'],3)

    def test_independent_of_r3_iterator_and_definition(self):
        with patch('na_pipeline.qec.iter_physical_ops',side_effect=AssertionError()),patch('na_pipeline.qec.surface17.surface17_definition',side_effect=AssertionError()):
            self.assertTrue(audit_surface17(self.program)['passed'])

    def test_stabilizer_support_changed(self):
        self.reject(lambda p:p['metadata']['code_definition']['stabilizers'][0]['support'].pop(),'STABILIZER_REFERENCE')

    def test_syndrome_entangler_omitted(self):
        def mutate(p):
            b=p['templates']['s17.syndrome.v1']['body']; b.remove(next(n for n in b if n['op']['params'].get('name')=='CX'))
        self.reject(mutate,'SYNDROME_OBSERVABLE')

    def test_syndrome_direction_reversed(self):
        self.reject(lambda p:next(n['op'] for n in p['templates']['s17.syndrome.v1']['body'] if n['op']['params'].get('name')=='CX')['qubits'].reverse(),'SYNDROME_OBSERVABLE')

    def test_readout_before_entanglers(self):
        def mutate(p):
            b=p['templates']['s17.syndrome.v1']['body']; n=next(n for n in b if n['op']['kind']=='measure'); b.remove(n); b.insert(9,n)
        self.reject(mutate,'SYNDROME_READOUT_ORDER')

    def test_initialization_correction_missing(self):
        def mutate(p):
            b=p['templates']['s17.prepare_zero.v1']['body']; b.remove(next(n for n in b if n['op']['condition']))
        self.reject(mutate,'SIGN_FIX_SYNDROME')

    def test_initialization_correction_too_early(self):
        self.reject(lambda p:next(n['op'] for n in p['templates']['s17.prepare_zero.v1']['body'] if n['op']['condition']).update(after=[]),'INITIALIZATION_CORRECTION')

    def test_transversal_direction_reversed(self):
        def mutate(p):
            for n in p['templates']['s17.transversal_cx.v1']['body']: n['op']['qubits'].reverse()
        self.reject(mutate,'TRANSVERSAL_LOGICAL_ACTION')

    def test_bound_blocks_reversed(self):
        def mutate(p):
            n=p['body'][4]; n['bindings']={q:v.replace('control','TEMP').replace('target','control').replace('TEMP','target') for q,v in n['bindings'].items()}
        self.reject(mutate,'BLOCK_BINDING')

    def test_wrong_final_logical_parity(self):
        self.reject(lambda p:p['templates']['s17.measure_z_reset.v1']['metadata'].update(logical_z_result_parity=['m_d0']),'LOGICAL_READOUT_PARITY')

    def test_duplicate_terminal_reset(self):
        def mutate(p):
            b=p['templates']['s17.measure_z_reset.v1']['body']; resets=[n['op'] for n in b if n['op']['kind']=='reset']; resets[-1]['qubits']=resets[0]['qubits'][:]
        self.reject(mutate,'FINAL_READOUT_RESET')


if __name__=='__main__': unittest.main()
