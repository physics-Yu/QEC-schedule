"""Signed operator certificates, without a quantum state or sampled outcomes."""
import unittest
from na_pipeline.qec.surface17 import CHECKS, FORMALS, LOGICAL_X, LOGICAL_Z
from na_pipeline.qec.factory_primitives import Circuit, css_encoder
from na_pipeline.qec import get_component_spec
from na_pipeline.validation.semantic_common import conjugate, multiply


def pauli(support, basis):
    mask=sum(1<<i for i in support)
    return (mask,0,0) if basis=='X' else (0,mask,0)


def span(generators):
    values={(0,0,0)}
    for g in generators: values|={multiply(p,g) for p in list(values)}
    return values


class NeutralCliffordTests(unittest.TestCase):
    def test_signed_S_and_inverse_restore_code_and_ancillas(self):
        index={f'D_{q}':i for i,q in enumerate(FORMALS)}
        initial=[pauli(s,b) for _,b,s,_ in CHECKS]+[(0,1<<i,0) for i in range(9,17)]
        x=pauli(LOGICAL_X,'X'); z=pauli(LOGICAL_Z,'Z')
        for sign in (1,-1):
            c=Circuit();c.clifford_phase('D',sign,'s')
            gates=[n['op'] for n in c.nodes if n['op']['kind']=='gate']
            def image(p):
                for o in gates:p=conjugate(p,o['params']['name'],[index[q] for q in o['qubits']])
                return p
            group=span([image(p) for p in initial])
            self.assertTrue(all(p in group for p in initial))
            y=multiply(x,z);y=(*y[:2],(y[2]+sign)%4)
            self.assertIn(multiply(image(x),y),group)
            self.assertIn(multiply(image(z),z),group)
            self.assertEqual(sum(o['params']['name']=='CZ' for o in gates),4)
            self.assertEqual({q.split('_')[0] for o in gates for q in o['qubits']},{'D'})

    def test_raw_encoder_arbitrary_seed_maps_both_signed_logicals(self):
        enc=css_encoder();n=int(enc['seed'][1:])
        def image(p):
            for c,t in enc['cx']:p=conjugate(p,'CX',[c,t])
            return p
        initial=[pauli([int(q[1:])],'X') for q in enc['plus_inputs']]+[pauli([int(q[1:])],'Z') for q in enc['zero_inputs']]
        group=span([pauli(s,b) for _,b,s,_ in CHECKS])
        self.assertEqual(span([image(p) for p in initial]),group)
        for axis,support in (('X',LOGICAL_X),('Z',LOGICAL_Z)):
            self.assertIn(multiply(image(pauli([n],axis)),pauli(support,axis)),group)
        self.assertEqual(len(enc['cx']),9)
        from na_pipeline.validation.raw_encoder import certify_encoder
        proof=certify_encoder(enc)
        self.assertTrue(proof['passed'])
        self.assertTrue(proof['signed_logical_maps']['Y']['signed_coset_passed'])
        broken={**enc,'cx':enc['cx'][:-1]}
        self.assertFalse(certify_encoder(broken)['passed'])

    def test_Y_depends_on_projection_and_direct_S_without_auxiliary_cycle(self):
        for name,phase in (('PREPARE_Y_PLUS','S'),('PREPARE_Y_MINUS','SDG')):
            dag=get_component_spec(name)['physical_dag']
            self.assertEqual(len(dag['qubits']),17)
            self.assertTrue(any(o.get('condition') for o in dag['nodes']))
            self.assertEqual(sum(o['kind']=='measure' for o in dag['nodes']),16)
            self.assertTrue(any(o['params'].get('name')==phase for o in dag['nodes']))
        for name in ('S','SDG'):
            spec=get_component_spec(name)
            self.assertEqual(spec['patch_spec']['resource_requirements']['scratch_patches'],[])

    def test_ZZ_geometry_selects_near_legal_boundary_and_preserves_logical_Z(self):
        from na_pipeline.qec.geometry_variants import resolve_geometry_variants,ROT180
        from na_pipeline.qec import validate_physical_dag
        dag=get_component_spec('JOINT_ZZ')['physical_dag']
        coords={f'd{i}':(i%3,i//3) for i in range(9)}
        coords.update({name:center for name,_,_,center in CHECKS})
        atoms=[]
        for q in dag['qubits']:
            name=q['id'];block,local=name.rsplit('/',1)
            p=[200.,980.] if local=='probe' else [coords[local][0]*10,900+(60 if block=='right' else 0)+coords[local][1]*10]
            atoms.append({'atom_id':'atom:'+name,'qubit_id':name,'position_um':p,'carrier':'SLM'})
        result=resolve_geometry_variants(dag,{'atoms':atoms})
        self.assertTrue(validate_physical_dag(result)['passed'])
        selection=result['geometry_variant_selection'][0]
        self.assertEqual(selection['half_turn_variants'],[True,False])
        group=span([pauli(s,b) for _,b,s,_ in CHECKS])
        for _,basis,support,_ in CHECKS:
            rotated=[int(ROT180[f'd{i}'][1:]) for i in support]
            self.assertIn(pauli(rotated,basis),group)
        self.assertIn(multiply(pauli((6,7,8),'Z'),pauli(LOGICAL_Z,'Z')),group)


if __name__=='__main__':unittest.main()
