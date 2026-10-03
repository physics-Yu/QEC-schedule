"""Canonical rotated d=3 CSS memory, with four simultaneous CNOT layers.

The directions are derived from the geometry and the pinned official Stim
generator. CNOTs are lowered explicitly as H(target), CZ, H(target), without
optimizing away H gates. This is a QEC protocol frontend, not the BSS
magic-register-elimination compiler or a noisy fault-tolerance guarantee.
"""
from dataclasses import asdict, dataclass

from neutral_atom_experiments.surface_ghz import (
    LOGICAL_X, LOGICAL_Z, X_CHECKS, Z_CHECKS)

from .ir import BitExpr, Detector, GateTask, MemoryContract, Observable, PBCProgram
from .surface import data_role, patch_roles


STIM_SOURCE_VERSION = 'v1.15.0'
STIM_SOURCE_COMMIT = '42e0b9e099180e8570407c33f87b4683cac00d81'
STIM_SOURCE_URL = (
    'https://raw.githubusercontent.com/quantumlib/Stim/'
    f'{STIM_SOURCE_COMMIT}/src/stim/gen/gen_surface_code.cc')

# These are displacements in the official generator's integer coordinates.
_DIRECTIONS = {
    'X': ((1, 1), (-1, 1), (1, -1), (-1, -1)),
    'Z': ((1, 1), (1, -1), (-1, 1), (-1, -1)),
}


@dataclass(frozen=True)
class CanonicalPhase:
    """A phase of simultaneous protocol primitives, never a hardware pulse.

    ``gate_ids`` and ``depends_on`` are protocol operation IDs. Each primitive
    has one native gate, accessible via ``native_gate_ids`` after the existing
    lower_to_physical pass. ``depends_on`` describes the shared entry frontier;
    the reset phase records the measurement frontier but each reset operation
    only depends on its own readout, permitting an actual measurement/reset
    service visit. The following phase waits for every reset.
    """
    id: str
    round_index: int | None
    layer_index: int | None
    kind: str
    gate_ids: tuple[str, ...]
    depends_on: tuple[str, ...]

    @property
    def native_gate_ids(self):
        return tuple(f'{key}__g000' for key in self.gate_ids)

    def to_dict(self):
        return dict(asdict(self), native_gate_ids=list(self.native_gate_ids))


@dataclass(frozen=True)
class CanonicalCoupling:
    round_index: int
    layer_index: int
    check_id: str
    ancilla_role: str
    data_role: str
    control_role: str
    target_role: str
    native_cz_id: str


@dataclass(frozen=True)
class CanonicalMemory:
    program: PBCProgram
    phases: tuple[CanonicalPhase, ...]
    couplings: tuple[CanonicalCoupling, ...]
    role_coordinates: tuple[tuple[str, tuple[int, int]], ...]
    source_version: str = STIM_SOURCE_VERSION
    source_commit: str = STIM_SOURCE_COMMIT
    source_url: str = STIM_SOURCE_URL

    def to_dict(self):
        return {
            'schema': 'qec-canonical-memory/1',
            'program': self.program.to_dict(),
            'phases': [phase.to_dict() for phase in self.phases],
            'couplings': [asdict(pair) for pair in self.couplings],
            'role_coordinates': {role: list(coord) for role, coord in self.role_coordinates},
            'source': {'version': self.source_version, 'commit': self.source_commit,
                       'url': self.source_url},
            'claim': 'canonical ideal CSS memory; circuit-noise distance requires independent audit',
        }


def _geometry(patch):
    # Reflect x to preserve this project's existing check/role numbering and
    # X/Z colors. The existing left-column logical X becomes the right column
    # in Stim coordinates, stabilizer-equivalent to Stim's left-column choice.
    coords = {data_role(patch, q): (5 - 2 * (q % 3), 1 + 2 * (q // 3))
              for q in range(9)}
    for kind, checks in (('X', X_CHECKS), ('Z', Z_CHECKS)):
        for index, check in enumerate(checks):
            support = tuple(coords[data_role(patch, q)] for q in check)
            x = sum(p[0] for p in support) // len(support)
            y = sum(p[1] for p in support) // len(support)
            if len(support) == 2:
                if kind == 'X':
                    y = 0 if y == 1 else 6
                else:
                    x = 0 if x == 1 else 6
            coords[f'{patch}.{kind}{index}'] = (x, y)
    return coords


def _layer_pairs(patch, coords):
    data_at = {coords[data_role(patch, q)]: data_role(patch, q) for q in range(9)}
    layers = []
    for layer in range(4):
        pairs = []
        for kind, checks in (('X', X_CHECKS), ('Z', Z_CHECKS)):
            dx, dy = _DIRECTIONS[kind][layer]
            for index, check in enumerate(checks):
                ancilla = f'{patch}.{kind}{index}'
                x, y = coords[ancilla]
                data = data_at.get((x + dx, y + dy))
                if data is None:
                    continue
                if data not in {data_role(patch, q) for q in check}:
                    raise ValueError('Geometric neighbor is outside the declared stabilizer')
                control, target = (ancilla, data) if kind == 'X' else (data, ancilla)
                pairs.append((kind, index, ancilla, data, control, target))
        wires = [wire for pair in pairs for wire in pair[2:4]]
        if len(pairs) != 6 or len(set(wires)) != len(wires):
            raise ValueError('Canonical CNOT layer must contain six disjoint pairs')
        layers.append(tuple(pairs))
    expected = {(f'{patch}.{kind}{index}', data_role(patch, q))
                for kind, checks in (('X', X_CHECKS), ('Z', Z_CHECKS))
                for index, check in enumerate(checks) for q in check}
    actual = [(pair[2], pair[3]) for layer in layers for pair in layer]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError('Four layers must cover exactly the 24 stabilizer couplings')
    return tuple(layers)


def canonical_memory_program(*, basis='Z', rounds=3, patch='A'):
    """Return a canonical memory protocol and immutable phase/coupling sidecar.

    ``rounds`` counts all syndrome rounds, r1 through rN. Opposite-basis first
    syndromes are random gauge-sector outcomes; they are not corrected. Only
    the same-basis first syndromes form preparation detectors. This differs
    deliberately from the legacy preparation-plus-storage memory_program.
    """
    if basis not in ('X', 'Z') or type(rounds) is not int or rounds < 1:
        raise ValueError('Canonical memory requires X/Z basis and positive total rounds')
    roles = patch_roles(patch)
    coords = _geometry(patch)
    layers = _layer_pairs(patch, coords)
    ancillas = tuple(role.id for role in roles if role.kind == 'syndrome_ancilla')
    data = tuple(data_role(patch, q) for q in range(9))
    x_ancillas = tuple(f'{patch}.X{i}' for i in range(4))
    operations, phases, couplings = [], [], []
    frontier = ()

    def phase(key, kind, gate_type, targets, *, round_index=None, layer_index=None,
              ids=None, dependencies=None):
        nonlocal frontier
        previous = frontier
        ids = tuple(ids) if ids is not None else tuple(f'{key}.{i}' for i in range(len(targets)))
        for index, (op_id, support) in enumerate(zip(ids, targets)):
            deps = previous if dependencies is None else dependencies[index]
            operations.append(GateTask(op_id, gate_type, tuple(support), tuple(deps)))
        phases.append(CanonicalPhase(key, round_index, layer_index, kind, ids, previous))
        frontier = ids
        return ids

    phase(f'{patch}.prepare.reset', 'initialize_reset', 'RESET',
          tuple((role.id,) for role in roles))
    if basis == 'X':
        phase(f'{patch}.prepare.plus', 'data_prepare_h', 'H', tuple((q,) for q in data))

    detectors = []
    for round_index in range(1, rounds + 1):
        base = f'{patch}.r{round_index}'
        phase(f'{base}.ancilla_h', 'ancilla_prepare_h', 'H',
              tuple((a,) for a in x_ancillas), round_index=round_index)
        for layer_index, pairs in enumerate(layers, start=1):
            layer_base = f'{base}.layer{layer_index}'
            phase(f'{layer_base}.target_h', 'cx_target_h', 'H',
                  tuple((pair[5],) for pair in pairs),
                  round_index=round_index, layer_index=layer_index)
            cz_ids = phase(f'{layer_base}.cz', 'cx_cz', 'CZ',
                           tuple((pair[4], pair[5]) for pair in pairs),
                           round_index=round_index, layer_index=layer_index)
            for pair, op_id in zip(pairs, cz_ids):
                kind, index, ancilla, data_, control, target = pair
                couplings.append(CanonicalCoupling(round_index, layer_index,
                    f'{base}.{kind}{index}', ancilla, data_, control, target,
                    f'{op_id}__g000'))
            phase(f'{layer_base}.target_restore', 'cx_target_restore', 'H',
                  tuple((pair[5],) for pair in pairs),
                  round_index=round_index, layer_index=layer_index)
        phase(f'{base}.ancilla_readout_h', 'ancilla_readout_h', 'H',
              tuple((a,) for a in x_ancillas), round_index=round_index)
        measured = phase(f'{base}.measure', 'ancilla_measure', 'MEASURE',
                         tuple((a,) for a in ancillas), round_index=round_index,
                         ids=tuple(f'{base}.{a.rsplit(".", 1)[-1]}' for a in ancillas))
        phase(f'{base}.reset', 'ancilla_reset', 'RESET',
              tuple((a,) for a in ancillas), round_index=round_index,
              dependencies=tuple((m,) for m in measured))
        for kind in (basis,) if round_index == 1 else ('X', 'Z'):
            for index in range(4):
                current = f'{base}.{kind}{index}'
                terms = (current,) if round_index == 1 else (
                    f'{patch}.r{round_index-1}.{kind}{index}', current)
                detectors.append(Detector(f'{patch}.det.r{round_index}.{kind}{index}',
                    BitExpr(terms), 'known_product_preparation' if round_index == 1 else 'temporal'))

    if basis == 'X':
        phase(f'{patch}.final.h', 'data_readout_h', 'H', tuple((q,) for q in data))
    phase(f'{patch}.final.measure', 'data_measure', 'MEASURE',
          tuple((q,) for q in data), ids=tuple(f'{patch}.final.m{q}' for q in range(9)))
    checks = X_CHECKS if basis == 'X' else Z_CHECKS
    for index, check in enumerate(checks):
        detectors.append(Detector(f'{patch}.terminal.{basis}{index}',
            BitExpr((f'{patch}.r{rounds}.{basis}{index}',
                     *(f'{patch}.final.m{q}' for q in check))), 'destructive_readout'))
    logical_support = LOGICAL_X if basis == 'X' else LOGICAL_Z
    observable = Observable(f'{patch}.logical_{basis}',
        BitExpr(tuple(f'{patch}.final.m{q}' for q in logical_support)),
        'canonical memory logical parity; noisy output requires detector-based decoder')
    program = PBCProgram(roles, tuple(operations), tuple(detectors), (observable,),
                         f'd3-canonical-memory-{basis.lower()}-{rounds}-total-rounds',
                         MemoryContract(patch, basis, rounds, observable.id,
                                        'canonical_detector_memory'))
    return CanonicalMemory(program, tuple(phases), tuple(couplings),
                           tuple((role.id, coords[role.id]) for role in roles))
