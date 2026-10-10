"""Direction-aware SE ready-frontier selection without adding source edges.

For the Surface-17 S/Z hook ordering, NW, X-NE, shared SW, Z-NE, SE
allows the two commuting SW subsets to meet in one physical window.
Only source-ready operations are selected. A half-cycle S-SE fence remains
authoritative, so this does not move a coupling across its inserted fold.
"""


def se_direction_rank(op):
    meta = op.get('metadata', {})
    if op.get('kind') != 'gate' or op.get('params', {}).get('name') != 'CX':
        return None
    check, corner = meta.get('check_id', ''), meta.get('corner')
    if not isinstance(check, str) or check[:1] not in ('x', 'z') or meta.get('syndrome_layer') not in range(4):
        return None
    return {'NW': 0, 'SW': 2, 'SE': 4, 'NE': 1 if check.startswith('x') else 3}.get(corner)


def select_se_frontier(ready):
    ranks = [se_direction_rank(op) for op in ready]
    known = [r for r in ranks if r is not None]
    if not known:
        return ready
    target = min(known)
    return [op for op, rank in zip(ready, ranks) if rank == target]


def complete_se_candidates(operations, candidates, kernel, *, max_nodes=20000):
    """Try full matchings before greedy MIS can discard a legal capture layout.

    This bounded preselection is local to up to eight source-ready SE pairs.
    The caller must check full capture, broadcast, and routes, then send the
    selected candidate set through the pinned Enola selector for its receipt.
    Exhaustion makes no infeasibility claim and falls back to ordinary Enola.
    """
    if not operations or len(operations) > 8 or any(se_direction_rank(o) is None for o in operations):
        return
    domains = [[c for c in candidates if c['op_id'] == op['id']] for op in operations]
    visited = 0

    def walk(index, chosen):
        nonlocal visited
        visited += 1
        if visited > max_nodes:
            return
        if index == len(domains):
            yield chosen
            return
        for c in domains[index]:
            legal = True
            for other in chosen:
                kernel.calls['compatible_2D'] += 1
                if (c['aod_group'] != other['aod_group'] or set(c['pair']) & set(other['pair'])
                        or not kernel.compatible(c['vector'], other['vector'])):
                    legal = False
                    break
            if legal:
                yield from walk(index + 1, chosen + [c])

    yield from walk(0, [])


def defer_readout_basis(local, ready, groups, done):
    """Coalesce final ancilla H when other ready couplings can advance first."""
    if not any(o['kind'] == 'gate' and len(o['qubits']) == 2 for o in ready):
        return local
    delayed = set()
    for group in groups:
        members = group['members']
        if any(m.get('last_coupling_op_id') and m['last_coupling_op_id'] not in done for m in members):
            delayed.update(m['basis_change_op_id'] for m in members if m.get('basis_change_op_id'))
    return [o for o in local if o['id'] not in delayed]
