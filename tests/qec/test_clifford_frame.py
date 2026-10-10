"""Independent matrix identities for frame pullback and coupling rewrites."""
import unittest
import numpy as np
from na_pipeline.qec.clifford_frame import CliffordFrame, realize_gate

I=np.eye(2,dtype=complex)
X=np.array([[0,1],[1,0]],dtype=complex)
Y=np.array([[0,-1j],[1j,0]],dtype=complex)
Z=np.diag([1,-1]).astype(complex)
H=np.array([[1,1],[1,-1]],dtype=complex)/2**.5
S=np.diag([1,1j]); SDG=S.conj().T
OPS=dict(I=I,X=X,Y=Y,Z=Z,H=H,S=S,SDG=SDG)
CX=np.eye(4,dtype=complex)[[0,1,3,2]]
RCX=np.eye(4,dtype=complex)[[0,3,2,1]]
CZ=np.diag([1,1,1,-1])


def matrix(frame):
    m=I
    for name in frame.word():m=OPS[name]@m
    return m


class FrameAlgebraTests(unittest.TestCase):
    def test_signed_pullback_matches_exact_matrix_conjugation(self):
        frames={CliffordFrame()};pending=list(frames)
        while pending:
            f=pending.pop()
            for gate in ('H','S'):
                n=f.prepend(gate)
                if n not in frames:frames.add(n);pending.append(n)
        self.assertEqual(len(frames),24)
        for f in frames:
            m=matrix(f)
            for p in 'XYZ':
                axis,sign=f.observable(p)
                np.testing.assert_allclose(m.conj().T@OPS[p]@m,sign*OPS[axis],atol=1e-12)

    def test_native_rewrites_and_explicit_flush_preserve_two_qubit_operator(self):
        states=[CliffordFrame(),CliffordFrame().prepend('H'),CliffordFrame().prepend('S'),CliffordFrame().prepend('X')]
        for name,g in (('CX',CX),('CZ',CZ)):
            for a in states:
                for b in states:
                    recipe,after=realize_gate(name,['A','B'],{'A':a,'B':b})
                    physical=np.eye(4,dtype=complex)
                    for p in recipe['physical_components']:
                        op=p['component_id'];blocks=p['blocks']
                        if op=='CX':m=CX if blocks==['A','B'] else RCX
                        elif op=='CZ':m=CZ
                        else:m=np.kron(OPS[op],I) if blocks==['A'] else np.kron(I,OPS[op])
                        physical=m@physical
                    actual=np.kron(matrix(after['A']),matrix(after['B']))@physical
                    expected=g@np.kron(matrix(a),matrix(b))
                    ratio=actual.flat[np.argmax(abs(expected))]/expected.flat[np.argmax(abs(expected))]
                    np.testing.assert_allclose(actual,ratio*expected,atol=1e-12)
