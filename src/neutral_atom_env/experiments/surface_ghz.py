"""Independent ideal-Clifford definition/verification; no physical compiler import.

Four rotated [[9,1,3]] data patches. No syndrome measurement or fault-tolerance
claim. Run with --output DIR to save native H/CZ input and verification evidence.
"""
from itertools import combinations, product

X_CHECKS = ((0, 1, 3, 4), (4, 5, 7, 8), (1, 2), (6, 7))
Z_CHECKS = ((1, 2, 4, 5), (3, 4, 6, 7), (0, 3), (5, 8))
LOGICAL_X = (0, 3, 6)
LOGICAL_Z = (0, 1, 2)
LOGICAL_CNOTS = ((0, 1), (0, 2), (1, 3))


def mask(qubits):
    return sum(1 << q for q in qubits)


def rref(rows, n):
    rows = list(rows); pivots = []; rank = 0
    for q in range(n):
        pivot = next((k for k in range(rank, len(rows)) if rows[k] >> q & 1), None)
        if pivot is None:
            continue
        rows[rank], rows[pivot] = rows[pivot], rows[rank]
        for k in range(len(rows)):
            if k != rank and rows[k] >> q & 1:
                rows[k] ^= rows[rank]
        pivots.append(q); rank += 1
    return rows[:rank], pivots


def encoder(plus=False):
    """Systematic GF(2) encoder with eight CNOTs per patch.

    Basis rows span X checks (plus logical X for |+_L>). The listed pivots
    appear in exactly one row, so H(pivots) then CX copies prepare their
    uniform positive superposition. This is ideal encoding, not fault tolerant.
    """
    rows, pivots = ((137, 6, 148, 292, 192), (0, 1, 4, 5, 6)) if plus else (
        (29, 6, 432, 192), (0, 1, 5, 6))
    gates = [('H', (p,)) for p in pivots]
    gates += [('CX', (p, q)) for row, p in zip(rows, pivots)
              for q in range(9) if q != p and row >> q & 1]
    return gates


def abstract_circuit():
    gates = []
    for block in range(4):
        gates.extend((kind, tuple(9*block+q for q in qs), f'encode-{block}')
                     for kind, qs in encoder(block == 0))
    for a, b in LOGICAL_CNOTS:
        gates.extend(('CX', (9*a+q, 9*b+q), f'logical-cx-{a}-{b}') for q in range(9))
    return gates


def native_circuit(gates):
    native = []
    for kind, qs, stage in gates:
        expansion = [('H', (qs[1],)), ('CZ', qs), ('H', (qs[1],))] if kind == 'CX' else [(kind, qs)]
        native.extend((op, targets, stage) for op, targets in expansion)
    return native


# Pauli representation i**phase X**x Z**z. Verify signs, not only binary support.
def multiply(a, b):
    x, z, p = a; xx, zz, pp = b
    return x ^ xx, z ^ zz, (p+pp+2*((z & xx).bit_count() % 2)) % 4


def conjugate(pauli, kind, qs):
    x, z, p = pauli
    if kind == 'H':
        bit = 1 << qs[0]; a = bool(x & bit); b = bool(z & bit)
        p = (p+2*int(a and b)) % 4
        if a != b:
            x ^= bit; z ^= bit
    elif kind == 'CZ':
        a, b = (1 << q for q in qs)
        xa, xb = bool(x & a), bool(x & b)
        p = (p+2*int(xa and xb)) % 4
        if xa: z ^= b
        if xb: z ^= a
    elif kind == 'CX':
        a, b = (1 << q for q in qs)
        if x & a: x ^= b
        if z & b: z ^= a
    else:
        raise ValueError(kind)
    return x, z, p


def echelon(generators, n):
    basis = {}
    for value in generators:
        v = value
        for bit in range(2*n):
            if not ((v[0] | v[1] << n) >> bit & 1):
                continue
            if bit in basis:
                v = multiply(v, basis[bit])
            else:
                basis[bit] = v; break
        else:
            assert v == (0, 0, 0), ('inconsistent stabilizer', v)
    return basis


def contains(basis, value, n):
    v = value
    for bit in range(2*n):
        if (v[0] | v[1] << n) >> bit & 1:
            if bit not in basis: return False
            v = multiply(v, basis[bit])
    return v == (0, 0, 0)


def expected_generators():
    checks = []
    for block in range(4):
        checks.extend((mask(9*block+q for q in qs), 0, 0) for qs in X_CHECKS)
        checks.extend((0, mask(9*block+q for q in qs), 0) for qs in Z_CHECKS)
    checks.extend((0, mask(9*b+q for b in (0, other) for q in LOGICAL_Z), 0)
                  for other in (1, 2, 3))
    checks.append((mask(9*b+q for b in range(4) for q in LOGICAL_X), 0, 0))
    return checks


def verify_gate_sequence(gates):
    """Check native H/CZ workbench gates against all 36 signed GHZ checks.

    Pass gates in actual logical execution order, or sort an editor input by
    column before calling. This is independent of the physical compiler.
    """
    generators = [(0, 1 << q, 0) for q in range(36)]
    for gate in gates:
        kind = gate['gate_type']
        qubits = tuple(int(q[1:]) for q in gate['qubit_ids'])
        if kind not in {'H', 'CZ'} or any(not 0 <= q < 36 for q in qubits):
            raise ValueError('This experiment verifier accepts 36-qubit H/CZ circuits only')
        if len(qubits) != (1 if kind == 'H' else 2) or len(set(qubits)) != len(qubits):
            raise ValueError('Invalid native gate arity')
        generators = [conjugate(g, kind, qubits) for g in generators]
    basis = echelon(generators, 36)
    return all(contains(basis, g, 36) for g in expected_generators())


def verify():
    xrows, zrows = [mask(qs) for qs in X_CHECKS], [mask(qs) for qs in Z_CHECKS]
    assert all((x & z).bit_count() % 2 == 0 for x in xrows for z in zrows)
    local = [(x, 0, 0) for x in xrows]+[(0, z, 0) for z in zrows]
    basis = echelon(local, 9); assert len(basis) == 8
    lx, lz = mask(LOGICAL_X), mask(LOGICAL_Z)
    assert (lx & lz).bit_count() % 2 == 1
    assert all((lx & z).bit_count() % 2 == 0 for z in zrows)
    assert all((lz & x).bit_count() % 2 == 0 for x in xrows)
    assert not contains(basis, (lx, 0, 0), 9) and not contains(basis, (0, lz, 0), 9)
    distance = None
    # Independent exhaustive Pauli centralizer search, including mixed X/Y/Z.
    for weight in range(1, 4):
        for qs in combinations(range(9), weight):
            for kinds in product(('X', 'Y', 'Z'), repeat=weight):
                x = mask(q for q, kind in zip(qs, kinds) if kind in ('X', 'Y'))
                z = mask(q for q, kind in zip(qs, kinds) if kind in ('Z', 'Y'))
                if any(((x & zz).bit_count()+(z & xx).bit_count()) % 2 for xx, zz, _ in local):
                    continue
                # Group membership modulo overall phase suffices for distance.
                if not any(contains(basis, (x, z, p), 9) for p in range(4)):
                    distance = weight; break
            if distance is not None: break
        if distance is not None: break
    assert distance == 3
    for plus in (False, True):
        gens = [(0, 1 << q, 0) for q in range(9)]
        for kind, qs in encoder(plus):
            gens = [conjugate(g, kind, qs) for g in gens]
        prepared = echelon(gens, 9)
        assert all(contains(prepared, g, 9) for g in local)
        assert contains(prepared, (lx, 0, 0) if plus else (0, lz, 0), 9)
    abstract = abstract_circuit(); native = native_circuit(abstract)
    tables = []
    for circuit in (abstract, native):
        gens = [(0, 1 << q, 0) for q in range(36)]
        for kind, qs, _ in circuit:
            gens = [conjugate(g, kind, qs) for g in gens]
        table = echelon(gens, 36)
        assert len(table) == 36
        assert all(contains(table, g, 36) for g in expected_generators())
        tables.append(table)
    assert len(echelon(expected_generators(), 36)) == 36
    assert all(contains(tables[1], g, 36) for g in tables[0].values())
    # Removing the last logical CNOT layer must destroy the intended four-block GHZ.
    bad = [(0, 1 << q, 0) for q in range(36)]
    for kind, qs, stage in native:
        if stage != 'logical-cx-1-3': bad = [conjugate(g, kind, qs) for g in bad]
    bad_table = echelon(bad, 36)
    assert not all(contains(bad_table, g, 36) for g in expected_generators())
    return {'status': 'verified_ideal_clifford', 'data_qubits': 36, 'logical_qubits': 4,
            'code': 'rotated [[9,1,3]]', 'distance_exhaustively_verified': distance,
            'independent_target_stabilizers': 36, 'code_stabilizers': 32,
            'logical_ghz_stabilizers': 4, 'native_gates': len(native),
            'native_H': sum(k == 'H' for k, _, _ in native),
            'native_CZ': sum(k == 'CZ' for k, _, _ in native),
            'encoding_CNOT': sum(k == 'CX' and stage.startswith('encode') for k, _, stage in abstract),
            'logical_CNOT_physical_pairs': 27, 'negative_control_missing_last_layer': 'rejected',
            'fault_tolerant_preparation': False, 'measurement_or_noise_simulation': False}


def input_payload(compiler='row_greedy'):
    last = [-1]*36; gates = []; stages = []
    for i, (kind, qs, stage) in enumerate(native_circuit(abstract_circuit())):
        column = 1+max(last[q] for q in qs)
        for q in qs: last[q] = column
        gates.append({'id': f'SGHZ{i:03d}', 'gate_type': kind,
                      'qubit_ids': [f'Q{q:03d}' for q in qs], 'parameters': [], 'column': column})
        stages.append({'gate_id': gates[-1]['id'], 'stage': stage})
    return {'compiler': compiler, 'atom_count': 36, 'layout': 'row', 'seed': 0,
            'ez_policy': 'adaptive', 'aod_traps': 36, 'gates': gates,
            'ready_limit': 128, 'site_limit': 128, 'lookahead_depth': 8,
            'beam_width': 32, 'rollout_budget': 4096, 'row_candidate_budget': 4096,
            'route_expansions': 100000, 'compile_timeout_s': 3600}, stages


def experiment_input(compiler='patch_greedy'):
    """Fresh editable workbench input; all strategies receive identical gates."""
    value=input_payload(compiler)[0]
    if compiler.startswith('patch_'):
        value.update(layout='surface_patches', aod_traps=36, aod_rows=6, aod_columns=6,
            aod_column_offsets_um=[0,10,20,40,50,60], aod_row_offsets_um=[0,10,20,40,50,60],
            ez_neighbor_guard_enabled=False, row_candidate_budget=128)
    return value


def experiment_stages():
    """Gate IDs and preparation phase annotations, separate from gate schema."""
    return input_payload()[1]


def phase_columns():
    raw, stages = input_payload()
    by_id = {g['id']: g for g in raw['gates']}
    result = {}
    for item in stages:
        stage = item['stage']
        result.setdefault(stage, []).append(by_id[item['gate_id']]['column'])
    return {stage: {'first_column': min(cols), 'last_column': max(cols),
                    'native_gates': len(cols)} for stage, cols in result.items()}
