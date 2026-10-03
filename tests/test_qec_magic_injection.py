"""Independent branch Kraus and reference-entanglement injection checks."""
import numpy as np
import pytest
from neutral_atom_experiments.qec_pbc.magic_injection import make_magic_injection


@pytest.mark.parametrize('gate,sign', [('T',1), ('Tdg',-1)])
def test_branch_instrument_and_entangled_reference(gate,sign):
    contract = make_magic_injection(gate,'data','magic',measurement_id='m0',
                                    provenance='test exact vector',quality='ideal_reference')
    phase = np.exp(sign*1j*np.pi/4)
    resource = np.array([1,phase])/np.sqrt(2)
    cx = np.array([[1,0,0,0],[0,1,0,0],[0,0,0,1],[0,0,1,0]],complex)
    # Explicit tensor embedding from the two data basis states; output indexed
    # by data, then resource. No symbolic compiler enters this calculation.
    embedding = np.column_stack([np.kron(np.eye(2)[:,i],resource) for i in range(2)])
    target = np.diag([1,phase])
    correction = np.diag([1,np.exp(sign*1j*np.pi/2)])
    kraus = [(cx@embedding).reshape(2,2,2)[:,outcome,:] for outcome in (0,1)]
    assert np.allclose(kraus[0],target/np.sqrt(2))
    assert np.allclose(kraus[1],phase*np.diag([1,phase.conjugate()])/np.sqrt(2))
    assert np.allclose(sum(k.conj().T@k for k in kraus),np.eye(2))
    rng = np.random.default_rng(180)
    # Mixed data channel and data-reference entanglement must both agree.
    psi = rng.normal(size=4)+1j*rng.normal(size=4); psi /= np.linalg.norm(psi)
    rho = np.outer(psi,psi.conj())
    output = np.zeros((4,4),complex)
    for outcome,k in enumerate(kraus):
        assert np.allclose(k.conj().T@k,np.eye(2)/2)
        corrected = (correction if outcome else np.eye(2))@k
        lifted = np.kron(corrected,np.eye(2))
        branch = lifted@rho@lifted.conj().T
        assert np.isclose(np.trace(branch),0.5)
        output += branch
    expected = np.kron(target,np.eye(2))@rho@np.kron(target.conj().T,np.eye(2))
    assert np.allclose(output,expected)
    # Also realize the same instrument in a three-qubit pure state, ordering
    # data, reference, resource, to verify measurement tensor axes.
    input3 = np.kron(psi,resource).reshape(2,2,2)
    output3 = np.empty_like(input3)
    for data in (0,1):
        for ref in (0,1):
            for magic in (0,1):
                output3[data,ref,magic^data] = input3[data,ref,magic]
    for outcome in (0,1):
        vector = output3[:,:,outcome].reshape(4)
        if outcome: vector = np.kron(correction,np.eye(2))@vector
        assert np.allclose(np.outer(vector,vector.conj())*2,expected)
    assert contract.branches[0].correction == ()
    assert contract.branches[1].correction[0].name == ('S' if sign == 1 else 'Sdg')
    assert contract.resource.consumed is True
    payload=contract.to_dict()
    assert payload['measurement']['destructive'] is True
    assert payload['branches'][1]['depends_on_measurement'] == 'm0'
    assert payload['fault_tolerant'] is False


def test_unknown_quality_and_rejections():
    contract=make_magic_injection('T','a','b',measurement_id='m',provenance='uncharacterized source')
    assert contract.resource.quality == 'unknown'
    for kwargs in ({'gate':'H'}, {'resource_wire':'a'}, {'measurement_id':''},
                   {'provenance':''}, {'quality':'perfect physical'}):
        base=dict(gate='T',data_wire='a',resource_wire='b',measurement_id='m',provenance='source')
        base.update(kwargs)
        with pytest.raises(ValueError): make_magic_injection(**base)
