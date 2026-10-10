"""Physical state permutation by transport; carrier identities never change.

The source addresses code sites. A completed transport changes which physical
carrier occupies each site, committed by an explicit non-quantum rebind action.
Shared AOD rows cannot be rotated as a rigid 2D object. Cycle routing therefore
uses an empty SLM buffer and legal single-carrier transfers, including sweeps.
"""
from copy import deepcopy
import math

from .enola_kernel import StrategyError, digest, group_route
from .geometry import in_zone


def compile_permutation(compiler, op):
    c = compiler
    qs = op['qubits']
    dest = op['params'].get('destination_indices')
    if (op['condition'] is not None or op['reads'] or op['writes'] or
            not isinstance(dest, list) or sorted(dest) != list(range(len(qs))) or
            any(type(i) is not int for i in dest) or len(qs) < 2):
        raise StrategyError('INVALID_TRANSPORT_PERMUTATION', 'Explicit unconditional bijection required')
    if 'rebind' not in c.device['operations']['action_kinds']:
        raise StrategyError('TRANSPORT_PERMUTATION_UNSUPPORTED', 'Device must declare the site-binding control extension')
    aids = [c.qatom[q] for q in qs]
    if len({q.rsplit('/', 1)[0] for q in qs}) != 1:
        raise StrategyError('PERMUTATION_PATCH_BOUNDARY', 'Only within-patch site permutations are qualified')
    if any(c.atoms[a]['carrier'] != 'SLM' or c.atoms[a]['trap_id'] != c.home[a] for a in aids):
        raise StrategyError('PERMUTATION_ENTRY', 'Permutation requires each participating atom at its committed site')
    sites = {q: c.home[a] for q, a in zip(qs, aids)}
    targets = {a: sites[qs[dest[i]]] for i, a in enumerate(aids)}
    start_index = len(c.actions)
    remaining = {i for i in range(len(qs)) if dest[i] != i}
    cycles = []
    while remaining:
        first = min(remaining); cycle = [first]; nxt = dest[first]
        while nxt != first:
            cycle.append(nxt); nxt = dest[nxt]
        remaining.difference_update(cycle); cycles.append(cycle)
    for ci, cycle in enumerate(cycles):
        head = aids[cycle[0]]
        # An explicit empty site near the patch, within the existing EZ. We
        # preflight the complete cycle before emitting any of its transfers.
        center = c.atoms[head]['position_um']
        pitch = c.device['geometry']['initial_spacing_um']
        itinerary = None
        for dx, dy in ((-.5, -.25), (.5, -.25), (-1.5, -.75), (1.5, .75), (-2.5, 1.25), (2.5, -1.25)):
            buffer = [center[0]+dx*pitch, center[1]+dy*pitch]
            if not in_zone(buffer, c.zone) or any(math.dist(a['position_um'], buffer) < 1e-7 for a in c.atoms.values()):
                continue
            moves = [(head, buffer)]
            moves += [(aids[i], c.traps[targets[aids[i]]]['position_um']) for i in reversed(cycle[1:])]
            moves += [(head, c.traps[targets[head]]['position_um'])]
            scene = deepcopy(list(c.atoms.values()))
            try:
                for aid, point in moves:
                    group_route(scene, {aid: point}, pitch)
                    next(a for a in scene if a['atom_id'] == aid)['position_um'] = list(point)
            except StrategyError:
                continue
            itinerary = moves; break
        if itinerary is None:
            raise StrategyError('PERMUTATION_ROUTE_SEARCH_EXHAUSTED', 'Bounded buffer/route search exhausted; not an infeasibility proof')
        buffer_id = 'slm:permutation-buffer:'+digest({'position_um': buffer})[:24]
        trap = {'trap_id': buffer_id, 'position_um': buffer, 'zone_id': c.device['broadcast']['zone_id'], 'occupant': None}
        if buffer_id not in c.traps:
            c.traps[buffer_id] = trap; c.initial_state['slm_traps'].append(deepcopy(trap))
        for mi, (aid, point) in enumerate(itinerary):
            tid = buffer_id if mi == 0 else targets[aid]
            c.transfer([aid], {aid: tid}, [op['id']], group_id=op['id']+f':cycle:{ci}:move:{mi}',
                       purpose='code_site_permutation')
    bindings = [{'atom_id': a, 'from_site_id': qs[i], 'to_site_id': qs[dest[i]],
                 'destination_trap_id': targets[a], 'position_um': list(c.traps[targets[a]]['position_um'])}
                for i, a in enumerate(aids)]
    commit = c.emit('rebind', aids, c.device['timings_us']['classical'], [op['id']],
                    {'site_bindings': bindings, 'quantum_effect': 'none',
                     'transport_action_ids': [a['id'] for a in c.actions[start_index:]],
                     'purpose': 'commit_code_site_permutation'})
    c.time = commit['t_end_us']
    for b in bindings:
        a = c.atoms[b['atom_id']]
        a['site_id'] = b['to_site_id']
        c.home[b['atom_id']] = b['destination_trap_id']
    c.qatom = {a.get('site_id', a['qubit_id']): a['atom_id'] for a in c.atoms.values()}
    c.finish_op(op)
