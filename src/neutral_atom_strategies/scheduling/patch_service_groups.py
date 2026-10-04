"""Read-only, bounded Cartesian batching for native patch MZ services.

The selector keeps authored gates and local-role bundles intact. It only
proposes a source capture; the existing MZ compiler and Executor still validate
all transport, active empty traps, pulse zones, dependencies and return holders.
"""
from collections import defaultdict
from itertools import combinations
from math import hypot

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import GateStatus, HolderType
from neutral_atom_env.hardware.multi_aod import backend_for, device


def _closed_source(state, atoms, origin, bindings):
    """Check every live static atom against all enabled Cartesian crossings."""
    aod = device(state)
    axes = aod.configuration()
    columns = {binding.cell.column for binding in bindings}
    rows = {binding.cell.row for binding in bindings}
    xs = tuple(origin.x_um + axes.x_um[i] - aod.pose.x_um for i in columns)
    ys = tuple(origin.y_um + axes.y_um[i] - aod.pose.y_um for i in rows)
    tolerance = state.hardware.alignment_tolerance_um
    clearance = state.hardware.minimum_clearance_um
    captured = set()
    for atom, holder in state.placement.atom_to_holder.items():
        if holder.holder_type != HolderType.STATIC:
            continue
        point = state.world.traps[holder.holder_id].position
        # A Cartesian product's nearest point is obtained independently on
        # each axis; this also covers enabled intersections with no requested
        # atom. Off-grid nearby spectators reject the proposal as well.
        distance = hypot(min(abs(point.x_um - x) for x in xs),
                         min(abs(point.y_um - y) for y in ys))
        if distance <= tolerance:
            captured.add(atom)
        elif distance + 1e-9 < clearance:
            return False
    return captured == atoms


def select_readout_group(state, ready, atom_roles):
    """Return the largest capture-clean same-kind native service tuple.

    Supported targets are AOD_0 data d0..d8 and syndrome X0..X3/Z0..Z3.
    Data and ancillary families are considered separately. Each selected local
    role includes *all* its READY gates across patches; no bundle is split to
    satisfy capacity. Enumerating at most 511 data and 255 ancillary subsets
    per gate kind gives the exact largest gate count within this bounded
    policy. Ties preserve the caller's earliest gate order, and returned gates
    retain their IDs, explicit dependencies and identity.

    An empty tuple means there are no supported READY MEASURE/RESET gates.
    A nonempty eligible frontier with no complete fitting bundle raises
    ValidationError. No plans are compiled or live state fields changed here.
    """
    # Lazy import lets parallel_patch opt into this selector without a module
    # cycle, and reuses its actual rigid source embedding/capacity rule.
    from .parallel_patch import _bindings

    ready = tuple(ready)
    classes = defaultdict(lambda: defaultdict(list))
    for index, gate in enumerate(ready):
        if gate.gate_type not in {'MEASURE', 'RESET'}:
            continue
        node = state.dag.nodes.get(gate.id)
        if node is None or node.gate != gate:
            raise ValueError('Readout frontier must contain authored circuit gates')
        if node.status != GateStatus.READY:
            continue
        role = atom_roles.get(gate.qubit_ids[0], {})
        if role.get('aod_id', 'AOD_0') != 'AOD_0':
            continue
        family = role.get('kind')
        if family not in {'data', 'syndrome_ancilla'}:
            continue
        local = role.get('role', '').split('.')[-1]
        allowed = ({f'd{i}' for i in range(9)} if family == 'data' else
                   {f'{basis}{i}' for basis in 'XZ' for i in range(4)})
        if local not in allowed:
            raise ValidationError('PATCH_SERVICE_SCOPE',
                                  'Patch services require canonical d0..d8 or X0..X3/Z0..Z3 roles')
        classes[(gate.gate_type, family)][local].append(index)
    if not classes:
        return ()

    candidates = []
    for bundles in classes.values():
        values = tuple(bundles.values())
        for count in range(len(values), 0, -1):
            for subset in combinations(values, count):
                indices = tuple(sorted(index for bundle in subset for index in bundle))
                candidates.append(indices)
    # Native gate count, rather than class count, matters when only some
    # patches have reached a particular local role on the ready frontier.
    candidates.sort(key=lambda indices: (-len(indices), indices))
    for indices in candidates:
        gates = tuple(ready[index] for index in indices)
        atoms = {gate.qubit_ids[0] for gate in gates}
        if len(atoms) != len(gates) or len(atoms) > 128:
            continue
        try:
            if device(state).is_moving:
                continue
            origin, bindings = _bindings(state, atoms)
            # All configured axes, including disabled capacity, must stay in
            # the world/device envelope at the proposed source pose.
            backend_for(state).validate_pose(state, origin)
        except ValidationError:
            continue
        if _closed_source(state, atoms, origin, bindings):
            return gates
    raise ValidationError('PATCH_SERVICE_NO_GROUP',
                          'No complete local-role service bundle fits the idle rigid AOD with exact capture closure')
