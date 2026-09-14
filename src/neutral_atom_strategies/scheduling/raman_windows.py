"""Analytic safe Raman windows within a monotone straight AOD move.

This is scheduler geometry, not a replacement for the independent pulse audit.
Distances are atom-center distances; equality at the configured limit is legal.
"""
from math import sqrt

from neutral_atom_env.domain.models import HolderType
from neutral_atom_env.hardware import get_backend
from neutral_atom_env.hardware.raman import validate_rotation


def safe_rotation_fractions(state, gate_id, target=None):
    """Return closed safe elapsed-time fractions in [0, 1].

    A quadratic gives entry/exit of each neighbor into the forbidden disk.
    Row-column cubic progress is inverted monotonically, without time sampling.
    The caller handles handoff/resource exclusion and the absolute pulse length.
    """
    gate = validate_rotation(state, gate_id, check_neighbors=False)
    q = gate.qubit_ids[0]
    point = state.placement.position(q, state.world, state.aod)
    if target is not None and state.placement.atom_to_holder[q].holder_type == HolderType.MOBILE:
        return ()
    backend = get_backend(state.hardware)
    end = backend.target_aod(state.aod, target) if target is not None else state.aod
    radius = state.hardware.raman_minimum_separation_um
    forbidden = []
    for other, atom in state.atoms.items():
        if other == q or not atom.alive:
            continue
        holder = state.placement.atom_to_holder[other]
        start = state.placement.position(other, state.world, state.aod)
        finish = end.position(holder.holder_id) if target is not None and holder.holder_type == HolderType.MOBILE else start
        dx, dy = start.x_um-point.x_um, start.y_um-point.y_um
        vx, vy = finish.x_um-start.x_um, finish.y_um-start.y_um
        a, b, c = vx*vx+vy*vy, 2*(dx*vx+dy*vy), dx*dx+dy*dy-radius*radius
        if a == 0:
            if c < -1e-9:
                return ()
            continue
        disc = b*b-4*a*c
        if disc <= 0:
            continue  # Tangency touches equality, never the forbidden interior.
        left, right = (-b-sqrt(disc))/(2*a), (-b+sqrt(disc))/(2*a)
        if right > 0 and left < 1:
            forbidden.append((max(0., left), min(1., right)))
    merged = []
    for left, right in sorted(forbidden):
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(right, merged[-1][1]))
        else:
            merged.append((left, right))
    safe, cursor = [], 0.
    for left, right in merged:
        if left > cursor:
            safe.append((cursor, left))
        cursor = max(cursor, right)
    if cursor < 1:
        safe.append((cursor, 1.))

    def elapsed(progress):
        if backend.motion_profile != 'cubic' or progress in (0., 1.):
            return progress
        low, high = 0., 1.
        for _ in range(60):
            mid = (low+high)/2
            if 3*mid*mid-2*mid*mid*mid < progress:
                low = mid
            else:
                high = mid
        return (low+high)/2

    return tuple((elapsed(left), elapsed(right)) for left, right in safe)
