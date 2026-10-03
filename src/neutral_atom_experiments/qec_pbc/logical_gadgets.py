"""Ideal d=3 surface-code logical gadgets with explicit orientation contracts.

No syndrome rounds, detector patterns, motion or noise guarantees are inferred.
"""
from dataclasses import dataclass

from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate
from neutral_atom_experiments.surface_ghz import X_CHECKS, Z_CHECKS, LOGICAL_X, LOGICAL_Z

from .backend_contract import CouplingLayer, layer_requests, lower_coupling_layers
from .logical_pauli import LogicalGate, conjugate_pauli
from .pauli import PauliProduct


@dataclass(frozen=True)
class PatchContract:
    id: str
    data_roles: tuple[str, ...]
    x_checks: tuple[PauliProduct, ...]
    z_checks: tuple[PauliProduct, ...]
    logical_x: PauliProduct
    logical_z: PauliProduct
    orientation: str


def d3_patch(patch_id, *, orientation='standard'):
    if not isinstance(patch_id, str) or not patch_id.strip():
        raise ValueError('Patch ID must be nonempty')
    if orientation not in {'standard', 'dual'}:
        raise ValueError('Orientation must be standard or dual')
    roles = tuple(f'{patch_id}.d{i}' for i in range(9))
    obs = lambda basis, support: PauliProduct(tuple((roles[i], basis) for i in support))
    xs, zs = (X_CHECKS, Z_CHECKS) if orientation == 'standard' else (Z_CHECKS, X_CHECKS)
    lx, lz = (LOGICAL_X, LOGICAL_Z) if orientation == 'standard' else (LOGICAL_Z, LOGICAL_X)
    return PatchContract(patch_id, roles, tuple(obs('X', s) for s in xs),
        tuple(obs('Z', s) for s in zs), obs('X', lx), obs('Z', lz), orientation)


def conjugate_sequence(observable, gates):
    for gate in gates:
        observable = conjugate_pauli(observable, gate)
    return observable


@dataclass(frozen=True)
class TransversalCNOT:
    control: PatchContract
    target: PatchContract
    coupling: CouplingLayer
    gates: tuple[LogicalGate, ...]
    logical_images: tuple[tuple[str, PauliProduct], ...]
    claim: str = 'ideal codespace map; QEC, fault tolerance and physical execution unverified'

    def backend_requests(self, bindings):
        return layer_requests((self.coupling,), bindings)

    def physical_coupling(self, bindings):
        return lower_coupling_layers((self.coupling,), bindings)


def transversal_cnot(control_id, target_id, *, control_orientation='standard',
                     target_orientation='standard'):
    if control_id == target_id:
        raise ValueError('CNOT needs distinct patches')
    control = d3_patch(control_id, orientation=control_orientation)
    target = d3_patch(target_id, orientation=target_orientation)
    if control.orientation != target.orientation:
        raise ValueError('Mixed orientations require an explicitly validated data permutation')
    pairs = tuple(zip(control.data_roles, target.data_roles))
    gates = tuple(LogicalGate('CX', p) for p in pairs)
    images = tuple((name, conjugate_sequence(obs, gates)) for name, obs in (
        ('X_control', control.logical_x), ('Z_control', control.logical_z),
        ('X_target', target.logical_x), ('Z_target', target.logical_z)))
    return TransversalCNOT(control, target,
        CouplingLayer(f'{control_id}.to.{target_id}.transversal_cnot', pairs), gates, images)


@dataclass(frozen=True)
class LogicalHadamard:
    input_patch: PatchContract
    output_patch: PatchContract
    gates: tuple[LogicalGate, ...]
    logical_images: tuple[tuple[str, PauliProduct], ...]
    boundary_update: str = 'exchange X/Z boundary types; retain atom role coordinates'
    claim: str = 'orientation-changing ideal map; no rigid-AOD rotation or QEC execution'

    def physical_circuit(self, bindings):
        if (not set(self.input_patch.data_roles) <= bindings.keys()
                or len(set(bindings.values())) != len(bindings)):
            raise ValueError('Bindings require distinct physical atoms for all data roles')
        return PhysicalCircuit(tuple(PhysicalGate(f'{self.input_patch.id}.logical_h.{i}',
            'H', (bindings[role],)) for i, role in enumerate(self.input_patch.data_roles)))


def logical_hadamard(patch_id, *, orientation='standard'):
    before = d3_patch(patch_id, orientation=orientation)
    after = d3_patch(patch_id, orientation='dual' if orientation == 'standard' else 'standard')
    gates = tuple(LogicalGate('H', (q,)) for q in before.data_roles)
    images = (('X', conjugate_sequence(before.logical_x, gates)),
              ('Z', conjugate_sequence(before.logical_z, gates)))
    return LogicalHadamard(before, after, gates, images)


def transversal_cz(*args, **kwargs):
    raise ValueError('Same-orientation physical CZ is not a logical CZ shortcut; '
                     'an orientation-aware H/CNOT/H protocol is not implemented')
