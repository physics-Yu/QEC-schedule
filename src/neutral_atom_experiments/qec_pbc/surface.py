"""Rotated [[9,1,3]] protocol frontend, using the project's fixed convention."""
from .ir import (BitExpr, Detector, GateTask, MemoryContract, Observable, PauliMeasurement,
                 PBCProgram, Role)
from .pauli import PauliProduct
from neutral_atom_experiments.surface_ghz import X_CHECKS, Z_CHECKS, LOGICAL_X, LOGICAL_Z
from neutral_atom_experiments.surface_qec import X_ORDER, Z_ORDER, correction_table


def data_role(patch, local):
    return f'{patch}.d{local}'


def patch_roles(patch):
    if not isinstance(patch, str) or not patch:
        raise ValueError('Patch ID must be a nonempty string')
    return tuple(Role(data_role(patch, i), 'data', patch, i) for i in range(9)) + tuple(
        Role(f'{patch}.{kind}{i}', 'syndrome_ancilla', patch, i)
        for kind in ('X', 'Z') for i in range(4))


def stabilizers(patch='A'):
    return tuple(PauliProduct(tuple((data_role(patch, q), kind) for q in check))
                 for kind, checks in (('X', X_CHECKS), ('Z', Z_CHECKS)) for check in checks)


def logical_product(logical: PauliProduct):
    """Map logical patch factors to signed physical representatives (including Y)."""
    result = PauliProduct((), logical.sign)
    for patch, kind in logical.factors:
        x = PauliProduct(tuple((data_role(patch, q), 'X') for q in LOGICAL_X))
        z = PauliProduct(tuple((data_role(patch, q), 'Z') for q in LOGICAL_Z))
        if kind == 'Y':
            phase, word = x.multiply(z)
            coefficient = 1j * phase
            if coefficient not in (1, -1):
                raise ValueError('Logical Y representative must be Hermitian')
            word = PauliProduct(word.factors, int(coefficient.real))
        else:
            word = x if kind == 'X' else z
        phase, unsigned = result.multiply(word)
        if phase not in (1, -1):
            raise ValueError('Logical product must be Hermitian')
        result = PauliProduct(unsigned.factors, int(phase.real))
    return result


def logical_measurement(logical, *, result_id='logical-parity', ancilla='bus',
                        depends_on=()):
    physical = logical_product(logical)
    return PauliMeasurement(result_id, physical, ancilla, physical.support,
                            tuple(depends_on), purpose='logical_ppm')


def syndrome_round(patch='A', round_index=0, *, depends_on=()):
    """Conservative serial template. Preserve hook order; promise no FT distance.

    This first reference backend serializes complete checks (X bank then Z bank).
    It does not claim the optimized four-layer bank scheduling of prior demos.
    """
    if type(round_index) is not int or round_index < 0:
        raise ValueError('Round index must be a nonnegative integer')
    operations, previous = [], tuple(depends_on)
    for kind, checks, orders in (('X', X_CHECKS, X_ORDER), ('Z', Z_CHECKS, Z_ORDER)):
        for index, (check, order) in enumerate(zip(checks, orders)):
            key = f'{patch}.r{round_index}.{kind}{index}'
            op = PauliMeasurement(key,
                PauliProduct(tuple((data_role(patch, q), kind) for q in check)),
                f'{patch}.{kind}{index}', tuple(data_role(patch, q) for q in order),
                previous, patch=patch, round_index=round_index)
            operations.append(op)
            previous = (key,)
    return tuple(operations)


def memory_program(*, basis='Z', rounds=3, patch='A'):
    """Measurement preparation, measured-only correction, storage and full readout.

    r0 is preparation; r1..rounds are storage. The correction lookup is an
    ideal-readout baseline, not a decoder for circuit noise or delayed loss.
    """
    if basis not in ('X', 'Z') or type(rounds) is not int or rounds < 1:
        raise ValueError('Memory requires X/Z basis and at least one storage round')
    roles, ops, previous = patch_roles(patch), [], ()

    def gate(key, kind, targets, condition=()):
        nonlocal previous
        ops.append(GateTask(key, kind, tuple(targets), previous, tuple(condition)))
        previous = (key,)

    for q in range(9):
        gate(f'{patch}.prepare.reset{q}', 'RESET', (data_role(patch, q),))
        if basis == 'X':
            gate(f'{patch}.prepare.plus{q}', 'H', (data_role(patch, q),))
    prep = syndrome_round(patch, 0, depends_on=previous)
    ops.extend(prep)
    previous = (prep[-1].id,)
    for kind in ('X', 'Z'):
        for bits, targets in sorted(correction_table(kind).items()):
            condition = tuple((f'{patch}.r0.{kind}{i}', bit) for i, bit in enumerate(bits))
            for local in targets:
                pattern = ''.join(map(str, bits))
                gate(f'{patch}.prepare.correct.{kind}.{pattern}.{local}',
                     'Z' if kind == 'X' else 'X', (data_role(patch, local),), condition)
    detectors = []
    # Only checks matching the product-state basis have known first outcomes.
    for index in range(4):
        detectors.append(Detector(f'{patch}.initial.{basis}{index}',
            BitExpr((f'{patch}.r0.{basis}{index}',)), 'known_product_preparation'))
    for r in range(1, rounds + 1):
        body = syndrome_round(patch, r, depends_on=previous)
        ops.extend(body)
        previous = (body[-1].id,)
        for kind in ('X', 'Z'):
            for index in range(4):
                terms = (f'{patch}.r{r}.{kind}{index}',) if r == 1 else (
                    f'{patch}.r{r-1}.{kind}{index}', f'{patch}.r{r}.{kind}{index}')
                detectors.append(Detector(f'{patch}.det.r{r}.{kind}{index}',
                    BitExpr(terms), 'after_preparation_correction' if r == 1 else 'temporal'))
    for q in range(9):
        if basis == 'X':
            gate(f'{patch}.final.H{q}', 'H', (data_role(patch, q),))
        gate(f'{patch}.final.m{q}', 'MEASURE', (data_role(patch, q),))
    checks = X_CHECKS if basis == 'X' else Z_CHECKS
    for index, check in enumerate(checks):
        detectors.append(Detector(f'{patch}.terminal.{basis}{index}',
            BitExpr((f'{patch}.r{rounds}.{basis}{index}',
                     *(f'{patch}.final.m{q}' for q in check))), 'destructive_readout'))
    support = LOGICAL_X if basis == 'X' else LOGICAL_Z
    observable = Observable(f'{patch}.logical_{basis}',
        BitExpr(tuple(f'{patch}.final.m{q}' for q in support)),
        'raw_logical_parity; noisy output requires decoder and Pauli frame')
    return PBCProgram(roles, tuple(ops), tuple(detectors), (observable,),
                      f'd3-memory-{basis.lower()}-{rounds}-storage-rounds',
                      MemoryContract(patch, basis, rounds, observable.id))


def decode_ideal_memory(program, semantic_results):
    """Perfect-syndrome lookup baseline using the last complete measured round.

    Handles one data Pauli between ideal extraction rounds. Not valid for noisy
    readout, arbitrary multi-fault histories or errors after the closing round.
    """
    contract = program.memory_contract
    if contract is None:
        raise ValueError('Expected an explicit ideal memory decoding contract')
    last_round, patch, basis = contract.closing_round, contract.patch, contract.basis
    observable = next(o for o in program.observables if o.id == contract.observable_id)
    expected = {f'{patch}.r{last_round}.{kind}{i}' for kind in ('X', 'Z') for i in range(4)}
    available = {op.id: op for op in program.operations if isinstance(op, PauliMeasurement) and
                 op.purpose == 'syndrome' and op.patch == patch and op.round_index == last_round}
    if not expected <= available.keys():
        raise ValueError('Decoder requires a complete closing syndrome round')
    if any(available[op.id].product != op.product for op in syndrome_round(patch, last_round)):
        raise ValueError('Closing checks do not match the positive d3 code stabilizers')
    support = LOGICAL_X if basis == 'X' else LOGICAL_Z
    if observable.expression != BitExpr(tuple(f'{patch}.final.m{q}' for q in support)):
        raise ValueError('Observable does not match the declared memory basis parity')
    correction = PauliProduct(())
    for kind in ('X', 'Z'):
        bits = tuple(semantic_results[f'{patch}.r{last_round}.{kind}{i}'] for i in range(4))
        if any(type(bit) is not int or bit not in (0, 1) for bit in bits):
            raise ValueError('Decoder accepts measured integer bits only')
        locals_ = correction_table(kind)[bits]
        word = PauliProduct(tuple((data_role(patch, q), 'Z' if kind == 'X' else 'X')
                                  for q in locals_))
        _, correction = correction.multiply(word)  # global phase is irrelevant to frame action
    logical = logical_product(PauliProduct(((patch, basis),)))
    return observable.expression.evaluate(semantic_results) ^ int(
        not correction.commutes_with(logical))
