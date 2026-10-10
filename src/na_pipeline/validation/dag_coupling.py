"""Independent encoded-Clifford coupling algebra for the fixed Surface-17 code."""
from .dag_core import DAGAudit
from .semantic_qec import REFERENCE
from .semantic_common import conjugate,multiply,span_basis,in_span


def inspect_css_coupling(audit,gates,logical_gate):
    if logical_gate not in ('CX','CZ','H','X','Z'): raise ValueError('Unsupported encoded Clifford in this algebra scope')
    qubits=[f'{block}/d{i}' for block in ('control','target') for i in range(9)]
    generators=[]
    for offset in (0,9):
        for basis,support in REFERENCE:
            mask=sum(1<<(i+offset) for i in support)
            generators.append((mask,0,0) if basis=='X' else (0,mask,0))
    span=span_basis([x|(z<<18) for x,z,p in generators])
    logical=[(sum(1<<i for i in (0,3,6)),0,0),(0,sum(1<<i for i in (0,1,2)),0),
             (sum(1<<(i+9) for i in (0,3,6)),0,0),(0,sum(1<<(i+9) for i in (0,1,2)),0)]
    def image(pauli):
        for gate in gates:
            indices=[qubits.index(q) for q in gate['qubits']]
            if gate['name']=='PERMUTE':
                dest = gate['destination_indices']
                if any(type(i) is not int for i in dest) or sorted(dest) != list(range(len(indices))):
                    raise ValueError('Invalid source permutation')
                x, z, phase = pauli
                rest = ~sum(1 << i for i in indices)
                pauli = (x & rest | sum(((x >> old) & 1) << indices[dest[j]] for j, old in enumerate(indices)),
                         z & rest | sum(((z >> old) & 1) << indices[dest[j]] for j, old in enumerate(indices)), phase)
            elif gate['name']=='CZ':
                pauli=conjugate(pauli,'H',[indices[1]])
                pauli=conjugate(pauli,'CX',indices)
                pauli=conjugate(pauli,'H',[indices[1]])
            else: pauli=conjugate(pauli,gate['name'],indices)
        return pauli
    failures=[]
    for index,g in enumerate(generators):
        x,z,p=image(g)
        if p or not in_span(x|(z<<18),span): failures.append({'stabilizer_index':index,'image_x':x,'image_z':z,'phase_i_power':p})
    if failures: audit.fail('COUPLING_CODE_NOT_PRESERVED','Claimed logical coupling does not preserve the two encoded blocks',witnesses=failures[:4])
    xc,zc,xt,zt=logical
    expected={'CX':[multiply(xc,xt),zc,xt,multiply(zc,zt)],'CZ':[multiply(xc,zt),zc,multiply(zc,xt),zt],
              'H':[zc,xc,xt,zt],'X':[xc,(*zc[:2],2),xt,zt],'Z':[(*xc[:2],2),zc,xt,zt]}[logical_gate]
    for name,start,want in zip(('XC','ZC','XT','ZT'),logical,expected):
        actual=image(start); difference=multiply(actual,want)
        if difference[2] or not in_span(difference[0]|(difference[1]<<18),span):
            audit.fail('COUPLING_LOGICAL_ACTION','Physical circuit implements a different logical gate/direction',logical_pauli=name,actual=list(actual),expected=list(want))
    audit.metrics.update(physical_data_qubits=18,stabilizer_images_checked=16,logical_pauli_images_checked=4,gate_count=len(gates),claimed_logical_gate=logical_gate)


def audit_css_coupling(gates,logical_gate,*,fixture=False):
    audit=DAGAudit('surface17_coupling_algebra',{'gates':gates,'logical_gate':logical_gate},fixture=fixture)
    audit.check('encoded_stabilizers_and_logical_action',lambda:inspect_css_coupling(audit,gates,logical_gate))
    return audit.report()
