"""Fixed source-row services for a caller-defined QEC circuit.

The protocol owns the four interaction layers. This backend never reorders
those dependencies or compares candidate costs. It moves only caller-listed
CZ carriers, uses the hardware's declared interaction offset, and partitions
equal-displacement interactions by occupied source row. Refused row groups
have a deterministic singleton fallback under the same physical validators.
"""
from collections import defaultdict

from .qec_sparse import run_qec_sparse


def fixed_row_cz_groups(state, gates, mobile_atoms):
    mobile_atoms = frozenset(mobile_atoms)
    buckets = defaultdict(list)
    offset = state.hardware.interaction_offset
    for gate in gates:
        if gate.gate_type != 'CZ':
            raise ValueError('Fixed CZ partition accepts CZ gates only')
        mobile = [q for q in gate.qubit_ids if q in mobile_atoms]
        if len(mobile) != 1:
            raise ValueError('Each CZ needs exactly one caller-designated mobile operand')
        mobile = mobile[0]
        anchor = next(q for q in gate.qubit_ids if q != mobile)
        pm = state.placement.position(mobile, state.world, state.aod)
        pa = state.placement.position(anchor, state.world, state.aod)
        shift = (pa.x_um + offset.x_um - pm.x_um,
                 pa.y_um + offset.y_um - pm.y_um)
        buckets[(shift, pm.y_um)].append((gate.id, anchor, mobile))
    # Insertion order is the authored DAG order, independent of estimated time.
    for (shift, _), members in buckets.items():
        yield shift, tuple(members)
        if len(members) > 1:
            for member in members:
                yield shift, (member,)


def fixed_row_readout_groups(state, gates):
    buckets = defaultdict(list)
    for gate in gates:
        if gate.gate_type not in ('MEASURE', 'RESET'):
            raise ValueError('Fixed readout partition accepts measurement/reset only')
        p = state.placement.position(gate.qubit_ids[0], state.world, state.aod)
        buckets[p.y_um].append(gate)
    for members in buckets.values():
        yield tuple(members)
        if len(members) > 1:
            for gate in members:
                yield (gate,)


def run_qec_baseline(state, *, mobile_atoms, working_destinations, **kwargs):
    """Execute fixed row services using the existing physical QEC machinery."""
    mobiles = frozenset(mobile_atoms)
    if not mobiles:
        raise ValueError('Explicit mobile CZ carriers are required')
    return run_qec_sparse(state, working_destinations=working_destinations,
        cz_groups_factory=lambda state, gates: fixed_row_cz_groups(state, gates, mobiles),
        readout_groups_factory=fixed_row_readout_groups, **kwargs)
