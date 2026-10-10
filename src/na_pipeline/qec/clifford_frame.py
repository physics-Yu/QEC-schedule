"""Signed local Clifford bookkeeping; no quantum state or hardware execution.

Convention: algorithm_state = F code_state. A requested observable P is
measured as F-dagger P F. Frames belong to an execution context, never a cache.
"""
from dataclasses import dataclass
from collections import deque


_PULLBACK = {
    'H': (('Z', 1), ('Y', -1), ('X', 1)),
    'S': (('Y', -1), ('X', 1), ('Z', 1)),
    'SDG': (('Y', 1), ('X', -1), ('Z', 1)),
    'X': (('X', 1), ('Y', -1), ('Z', -1)),
    'Z': (('X', -1), ('Y', -1), ('Z', 1)),
}


@dataclass(frozen=True)
class CliffordFrame:
    images: tuple = (('X', 1), ('Y', 1), ('Z', 1))

    def observable(self, pauli):
        if pauli not in 'XYZ' or len(pauli) != 1:
            raise ValueError('FRAME_OBSERVABLE: expected X, Y or Z')
        return self.images['XYZ'.index(pauli)]

    def prepend(self, gate):
        if gate not in _PULLBACK:
            raise ValueError('FRAME_GATE_UNSUPPORTED: ' + gate)
        return CliffordFrame(tuple((self.observable(p)[0], s*self.observable(p)[1])
                                   for p,s in _PULLBACK[gate]))

    def word(self):
        # An exact finite group search, independent of circuit or timing size.
        queue = deque([(CliffordFrame(), ())]); seen = {CliffordFrame().images}
        while queue:
            frame, word = queue.popleft()
            if frame == self:
                return word
            for gate in ('H', 'S', 'SDG', 'X', 'Z'):
                nxt = frame.prepend(gate)
                if nxt.images not in seen:
                    seen.add(nxt.images); queue.append((nxt, word+(gate,)))
        raise ValueError('INVALID_CLIFFORD_FRAME')

    def record(self):
        return {'schema_version':'local-clifford-frame/0.1',
                'convention':'algorithm_state=F*code_state',
                'observable_pullback':{p:{'axis':v[0],'sign':v[1]} for p,v in zip('XYZ',self.images)},
                'word':list(self.word())}


def realize_gate(gate, blocks, frames):
    """Pure plan. Caller commits frame updates only with its live execution.

    Hardware realizations consume the existing canonical code-site binding.
    Unsupported frame conjugations are explicitly materialized and charged.
    """
    blocks = tuple(blocks)
    if not blocks or len(set(blocks)) != len(blocks) or any(b not in frames for b in blocks):
        raise ValueError('FRAME_BLOCK_BINDING')
    before = {b:frames[b] for b in blocks}; after = dict(before)
    physical = []; observation = None; materialized = []
    def flush():
        for b in blocks:
            for op in before[b].word():
                physical.append({'component_id':op,'blocks':[b],'reason':'explicit_frame_materialization'})
            if before[b] != CliffordFrame():
                materialized.append(b)
            after[b] = CliffordFrame()
    if gate == 'H':
        if len(blocks) != 1: raise ValueError('FRAME_GATE_ARITY')
        after[blocks[0]] = before[blocks[0]].prepend('H')
    elif gate == 'SE':
        if len(blocks) != 1: raise ValueError('FRAME_GATE_ARITY')
        physical.append({'component_id':'SE','blocks':list(blocks),'reason':'maintain_actual_code'})
    elif gate in ('MEASURE_Z','MEASURE_X'):
        if len(blocks) != 1: raise ValueError('FRAME_GATE_ARITY')
        axis, sign = before[blocks[0]].observable(gate[-1])
        if axis == 'Y':
            flush(); axis,sign=gate[-1],1
        observation={'requested_axis':gate[-1],'physical_axis':axis,'sign':sign,'xor_result':int(sign==-1)}
        physical.append({'component_id':'MEASURE_'+axis,'blocks':list(blocks),'reason':'observable_pullback'})
    elif gate in ('CX','CZ'):
        if len(blocks) != 2: raise ValueError('FRAME_GATE_ARITY')
        kinds = tuple('I' if before[b]==CliffordFrame() else 'H' if before[b]==CliffordFrame().prepend('H') else '?' for b in blocks)
        rewrite = {('CZ',('I','I')):('CZ',blocks), ('CZ',('H','I')):('CX',blocks[::-1]),
                   ('CZ',('I','H')):('CX',blocks), ('CX',('I','I')):('CX',blocks),
                   ('CX',('I','H')):('CZ',blocks), ('CX',('H','H')):('CX',blocks[::-1])}.get((gate,kinds))
        if rewrite is None:
            flush(); rewrite=(gate,blocks)
        physical.append({'component_id':rewrite[0],'blocks':list(rewrite[1]),'reason':'frame_conjugated_coupling'})
    else:
        if gate not in ('T','TDG','X','Z','S','SDG','RESET_Z'): raise ValueError('FRAME_GATE_UNSUPPORTED: '+gate)
        if len(blocks) != 1: raise ValueError('FRAME_GATE_ARITY')
        if gate != 'RESET_Z': flush()
        else: after[blocks[0]]=CliffordFrame()
        physical.append({'component_id':gate,'blocks':list(blocks),'reason':'canonical_physical_realization'})
    return {'schema_version':'GateRealization/0.1','requested_gate':gate,'blocks':list(blocks),
            'before':{b:f.record() for b,f in before.items()},'after':{b:f.record() for b,f in after.items()},
            'physical_components':physical,'software_only':not physical,'observable_binding':observation,
            'materialized_blocks':materialized,'code_state':'canonical_surface17_site_binding',
            'physical_materialization_policy':'existing_verified_physical_components_with_cost'}, after
