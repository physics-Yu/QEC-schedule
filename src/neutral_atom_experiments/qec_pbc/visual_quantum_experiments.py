"""Independent dense ideal oracles and JSON data for quantum experiments.

These small reference calculations do not simulate physical motion or noise.
"""
from __future__ import annotations
import numpy as np
from .logical_pauli import LogicalGate, compile_logical_pauli
from .magic_injection import make_magic_injection

_M = {'I': np.eye(2), 'X': np.array([[0,1],[1,0]]),
      'Y': np.array([[0,-1j],[1j,0]]), 'Z': np.diag([1,-1]),
      'H': np.array([[1,1],[1,-1]])/np.sqrt(2),
      'S': np.diag([1,1j]), 'Sdg': np.diag([1,-1j]),
      'T': np.diag([1,np.exp(1j*np.pi/4)]), 'Tdg': np.diag([1,np.exp(-1j*np.pi/4)])}


def _gate_matrix(g, wires):
    if len(g.wires)==1:
        result=np.array([[1]],complex)
        for wire in wires:
            result=np.kron(result,_M[g.name] if wire==g.wires[0] else _M['I'])
        return result
    n=len(wires); result=np.zeros((2**n,2**n),complex)
    c,t=[wires.index(w) for w in g.wires]
    for col in range(2**n):
        bits=[(col>>(n-1-i))&1 for i in range(n)]
        phase=-1 if g.name=='CZ' and bits[c] and bits[t] else 1
        if g.name=='CX' and bits[c]: bits[t]^=1
        row=sum(b<<(n-1-i) for i,b in enumerate(bits))
        result[row,col]=phase
    return result


def _unitary(gates,wires):
    result=np.eye(2**len(wires),dtype=complex)
    for gate in gates: result=_gate_matrix(gate,wires)@result
    return result


def _pauli_matrix(p,wires):
    result=np.array([[p.sign]],complex)
    for wire in wires: result=np.kron(result,_M[dict(p.factors).get(wire,'I')])
    return result


def _complex(value):
    value=np.asarray(value)
    return {'real':value.real.tolist(),'imag':value.imag.tolist()}


def _state(vector):
    vector=np.asarray(vector)
    result={'amplitudes':_complex(vector), 'probabilities':np.abs(vector).__pow__(2).tolist(),
            'phases_rad':np.angle(vector).tolist()}
    if len(vector)==2:
        result['bloch']=[float(np.vdot(vector,_M[b]@vector).real) for b in 'XYZ']
    return result


def _ppr_experiment():
    wires=('a','b','c')
    gates=[LogicalGate(n,w) for n,w in [('H',('a',)),('CX',('a','b')),
        ('X',('b',)),('T',('b',)),('S',('a',)),('H',('a',)),('Tdg',('a',)),
        ('CZ',('b','c')),('H',('c',)),('T',('c',)),('CX',('c','a')),('Tdg',('a',))]]
    program=compile_logical_pauli(gates,wires=wires)
    original=_unitary(gates,wires)
    compiled=np.eye(8,dtype=complex)
    for r in program.rotations:
        angle=np.pi*r.quarter_turns/8
        rotation=np.cos(angle)*np.eye(8)-1j*np.sin(angle)*_pauli_matrix(r.observable,wires)
        compiled=rotation@compiled
    compiled=np.exp(1j*np.pi*program.global_phase_eighth_turns/8)*_unitary(program.residual_clifford,wires)@compiled
    error=float(np.max(np.abs(original-compiled)))
    if error>1e-12: raise AssertionError('Independent PPR unitary oracle failed')
    probes=[]
    zero=np.eye(8,dtype=complex)[:,0]
    plus=np.ones(8,dtype=complex)/np.sqrt(8)
    ghz=np.zeros(8,complex); ghz[0]=1/np.sqrt(2); ghz[7]=1j/np.sqrt(2)
    arbitrary=np.arange(1,9)+1j*np.arange(8,0,-1); arbitrary=arbitrary/np.linalg.norm(arbitrary)
    for name,psi in [('000',zero),('+++',plus),('complex GHZ',ghz),('complex arbitrary',arbitrary)]:
        left,right=original@psi,compiled@psi
        fidelity=float(abs(np.vdot(left,right))**2)
        if abs(fidelity-1)>1e-12: raise AssertionError('PPR probe mismatch')
        probes.append({'name':name,'input':_state(psi),'original_output':_state(left),
                       'compiled_output':_state(right),'fidelity':fidelity})
    if not any(r.observable.sign==-1 for r in program.rotations):
        raise AssertionError('Visual PPR experiment must exercise a negative Pauli sign')
    return {'id':'E1','title':'Exact Clifford+T to signed Pauli rotations',
        'scope':'ideal arbitrary-input unitary; not physical execution or fault-tolerance proof',
        'wire_order':list(wires),'basis_labels':[format(i,'03b') for i in range(8)],
        'input_gates':[{'name':g.name,'wires':list(g.wires)} for g in gates],
        'compiled_program':program.to_dict(),'unitary_max_abs_error':error,
        'original_unitary':_complex(original),'compiled_unitary':_complex(compiled),'probes':probes}


def _injection_experiment():
    cx=np.array([[1,0,0,0],[0,1,0,0],[0,0,0,1],[0,0,1,0]],complex)
    plus=np.ones(2,complex)/np.sqrt(2)
    arbitrary=np.array([0.4+0.2j,-0.3+0.7j]); arbitrary/=np.linalg.norm(arbitrary)
    bell=np.array([1,0,0,1j],complex)/np.sqrt(2)
    cases=[]
    for gate,sign in [('T',1),('Tdg',-1)]:
        resource=np.array([1,np.exp(sign*1j*np.pi/4)])/np.sqrt(2)
        target=np.diag([1,np.exp(sign*1j*np.pi/4)])
        correction=np.diag([1,np.exp(sign*1j*np.pi/2)])
        embedding=np.column_stack([np.kron(np.eye(2)[:,i],resource) for i in range(2)])
        evolved=cx@embedding
        kraus=[evolved.reshape(2,2,2)[:,m,:] for m in (0,1)]
        completeness=float(np.max(np.abs(sum(k.conj().T@k for k in kraus)-np.eye(2))))
        if completeness>1e-12: raise AssertionError('Injection Kraus completeness failed')
        contract=make_magic_injection(gate,'data','resource',measurement_id='m_'+gate,
            provenance='explicit ideal-vector reference experiment',quality='ideal_reference')
        for label,psi,reference in [('|+>',plus,False),('complex arbitrary',arbitrary,False),
                                    ('complex Bell with reference',bell,True)]:
            lift=lambda operator:np.kron(operator,np.eye(2)) if reference else operator
            expected=lift(target)@psi
            branches=[]
            for outcome,k in enumerate(kraus):
                raw=lift(k)@psi
                probability=float(np.vdot(raw,raw).real)
                before=raw/np.sqrt(probability)
                after=lift(correction if outcome else np.eye(2))@before
                before_fidelity=float(abs(np.vdot(expected,before))**2)
                after_fidelity=float(abs(np.vdot(expected,after))**2)
                if abs(probability-0.5)>1e-12 or abs(after_fidelity-1)>1e-12:
                    raise AssertionError('Injection branch/channel oracle failed')
                branches.append({'outcome':outcome,'probability':probability,
                    'correction':None if outcome==0 else ('S' if sign==1 else 'Sdg'),
                    'before_correction':_state(before),'after_correction':_state(after),
                    'before_correction_fidelity':before_fidelity,'after_correction_fidelity':after_fidelity,
                    'kraus':_complex(k)})
            cases.append({'gate':gate,'input_name':label,'reference_entangled':reference,
                'wire_order':['data','reference'] if reference else ['data'],
                'basis_labels':['00','01','10','11'] if reference else ['0','1'],
                'input':_state(psi),'resource':_state(resource),'expected_output':_state(expected),
                'contract':contract.to_dict(),'kraus_completeness_error':completeness,'branches':branches})
    return {'id':'E4','title':'T/Tdg resource-state injection branches',
        'scope':'ideal logical instrument; resource quality explicitly ideal_reference; not FT or a factory',
        'cases':cases}


def quantum_experiment_data():
    """Return JSON-ready verified E1/E4 experiment data; raise on oracle failure."""
    return {'schema':'qec-visual-quantum-experiments-v1','experiments':[_ppr_experiment(),_injection_experiment()]}
