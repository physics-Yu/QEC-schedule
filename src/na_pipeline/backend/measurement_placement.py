"""Measurement-site assignment: ZAC-style minimum-cost full matching.

The bipartite formulation is adapted from ZAC (HPCA 2025), V-B2/V-B3,
https://github.com/UCLA-VAST/ZAC/blob/e5083362f99e6915f20c2bd0eaa88b6d1cdcecac/zac/placer/vmplacer.py
This is a project implementation, not execution of ZAC's gate placer. The
cost follows this device's linear parallel-axis time, not ZAC's sqrt model.
"""
from math import isfinite, hypot

from .enola_kernel import StrategyError


def minimum_cost_assignment(costs):
    """Rectangular Hungarian assignment; one distinct column per row, n <= m."""
    n = len(costs)
    if not n:
        return []
    m = len(costs[0])
    if n > m or any(len(row) != m for row in costs):
        raise StrategyError('READOUT_CAPACITY_EXCEEDED', 'Need a distinct empty measurement site for every batch member', required=n, available=m)
    if any(not isfinite(c) or c < 0 for row in costs for c in row):
        raise StrategyError('READOUT_COST_INVALID', 'Finite nonnegative costs required')
    u, v, p, way = [0.]*(n+1), [0.]*(m+1), [0]*(m+1), [0]*(m+1)
    for i in range(1, n+1):
        p[0] = i
        j0, minimum, used = 0, [float('inf')]*(m+1), [False]*(m+1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], float('inf'), 0
            for j in range(1, m+1):
                if not used[j]:
                    cur = costs[i0-1][j-1]-u[i0]-v[j]
                    if cur < minimum[j]:
                        minimum[j], way[j] = cur, j0
                    if minimum[j] < delta:
                        delta, j1 = minimum[j], j
            for j in range(m+1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minimum[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    assignment = [None]*n
    for j in range(1, m+1):
        if p[j]:
            assignment[p[j]-1] = j-1
    return assignment


def place_measurement_batch(atoms, sites, *, speed_um_per_us):
    """Assign all atoms to empty declared sites; routing is a separate check."""
    if not isfinite(speed_um_per_us) or speed_um_per_us <= 0:
        raise StrategyError('READOUT_SPEED_INVALID', 'Positive finite linear-axis speed required')
    if len({a['atom_id'] for a in atoms}) != len(atoms):
        raise StrategyError('READOUT_QUBIT_ALIAS', 'The same atom cannot be measured twice in one simultaneous batch')
    candidates = sorted((s for s in sites if s.get('occupant') is None), key=lambda s: s['trap_id'])
    if len({s['trap_id'] for s in candidates}) != len(candidates) or len({tuple(s['position_um']) for s in candidates}) != len(candidates):
        raise StrategyError('READOUT_SITE_ALIAS', 'Measurement site identities and coordinates must be unique')
    # Round-trip to the caller's current location. Small Euclidean tie breaker
    # resolves equal axis times without presenting it as a physical duration.
    times, costs = [], []
    for a in atoms:
        times.append([2*max(abs(a['position_um'][k]-s['position_um'][k]) for k in (0, 1))/speed_um_per_us for s in candidates])
        costs.append([times[-1][j]+1e-6*hypot(a['position_um'][0]-s['position_um'][0], a['position_um'][1]-s['position_um'][1]) for j, s in enumerate(candidates)])
    assignment = minimum_cost_assignment(costs)
    return {'schema_version': 'measurement-placement/0.1', 'algorithm': 'zac_inspired_minimum_cost_full_matching',
            'solver': 'project_rectangular_hungarian', 'cost_model': 'round_trip_Linf_over_speed_plus_1e-6_euclidean_tie_break',
            'candidate_sites': candidates, 'cost_matrix': costs,
            'assignments': [{'atom_id': a['atom_id'], 'qubit_id': a['qubit_id'], 'from_um': list(a['position_um']),
                             **{k: candidates[j][k] for k in ('trap_id', 'position_um', 'bank_id', 'site_id')},
                             'direct_round_trip_estimate_us': times[i][j], 'matching_cost': costs[i][j]}
                            for i, (a, j) in enumerate(zip(atoms, assignment))],
            'total_matching_cost': sum(costs[i][j] for i, j in enumerate(assignment)),
            'routing_verified': False, 'optimal_makespan_claimed': False}
