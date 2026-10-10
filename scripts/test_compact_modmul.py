"""Independent arithmetic and injection-branch identities for the composed run."""
import unittest,cmath,math
from copy import deepcopy
from run_compact_modmul_demo import program,operator_matrix,read,OUT,verify

class ArithmeticTests(unittest.TestCase):
    def test_full_controlled_permutation_including_phases(self):
        p=program();self.assertEqual(len(p['truth_table']),32);self.assertLess(p['operator_max_error'],1e-12)
        self.assertEqual(p['arithmetic_gate_counts'],{'CX':24,'H':6,'T':12,'TDG':9})
        for r in p['truth_table']:
            self.assertEqual(r['y'],r['x'] if not r['control'] or r['x']==15 else 2*r['x']%15)
    def test_wrong_T_sign_changes_the_operator(self):
        p=program();t=p['arithmetic_template'];ops=[deepcopy(n['op']) for n in t['body']]
        next(o for o in ops if o['params']['name']=='TDG')['params']['name']='T'
        u=operator_matrix(ops,t['formal_qubits']);err=0
        for c in range(32):
            ctrl=c&1;x=c>>1;y=x if not ctrl or x==15 else 2*x%15
            err=max(err,max(abs(u[r][c]-int(r==(2*y+ctrl))) for r in range(32)))
        self.assertGreater(err,.1)
    def test_T_and_Tdag_both_measurement_outcomes(self):
        z=cmath.exp(1j*math.pi/4)
        for gate in ('T','TDG'):
            wanted=[1,z if gate=='T' else z.conjugate()]
            for m in (0,1):
                k=[1,z] if m==0 else [z,1]
                if gate=='T' and m==1:k[1]*=1j
                if gate=='TDG' and m==0:k[1]*=-1j
                phase=k[0]
                self.assertLess(max(abs(k[i]-phase*wanted[i]) for i in (0,1)),1e-12)
    def test_source_mutation_is_rejected_before_execution(self):
        p=read(OUT/'plan.json.gz');p['calls'][9]['gate']='CZ'
        with self.assertRaisesRegex(AssertionError,'LOGICAL_SOURCE_CHANGED'):verify(p)
    def test_factory_operand_mutation_is_rejected(self):
        p=read(OUT/'plan.json.gz');a=next(a for a in p['actions'] if isinstance(a['payload'].get('native_ref'),str) and a['atoms'])
        a['atoms'][0]='atom:q0/d0'
        with self.assertRaisesRegex(AssertionError,'FACTORY_TEMPLATE_OPERANDS_CHANGED'):verify(p)

if __name__=='__main__':unittest.main()
