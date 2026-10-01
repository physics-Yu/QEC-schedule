"""Bind upstream d=3 roles to the existing two-patch neutral-atom platform.

The platform, all 34 atoms (including spectators), hardware defaults and
physical validators come from qec_layout. This adapter invents no timing or
geometry. Its parity gadgets retain the lowering backend's ideal/non-FT scope.
"""
from dataclasses import asdict, dataclass, replace
from typing import Mapping

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.platform import Platform, initialize
from neutral_atom_env.quantum.stabilizer import StabilizerState
from neutral_atom_experiments.qec_layout import build_qec_inputs

from .ir import PBCProgram
from .lowering import CompiledPBC, lower_to_physical


@dataclass(frozen=True)
class NativeQECInputs:
    """Complete native inputs plus upstream semantic/provenance bindings."""
    compiled: CompiledPBC
    circuit: PhysicalCircuit
    platform: Platform
    placement: Mapping[str, str]
    seed: int

    def create_environment(self):
        """Enable the existing ideal Clifford model on all platform atoms."""
        state = initialize(self.circuit, self.platform, self.placement, seed=self.seed)
        state = replace(state, quantum_state=StabilizerState.zero(tuple(sorted(state.atoms))))
        return NeutralAtomEnv(state)


def d3_role_bindings(program: PBCProgram):
    """Bind canonical A/B patch roles; additional parity-bus roles need a mapping."""
    available = {}
    for patch, block in (('A', 0), ('B', 1)):
        available.update({f'{patch}.d{i}': f'Q{9 * block + i:03d}' for i in range(9)})
        for kind, offset in (('X', 0), ('Z', 4)):
            available.update({f'{patch}.{kind}{i}': f'Q{18 + 8 * block + offset + i:03d}'
                              for i in range(4)})
    unknown = {role.id for role in program.roles} - available.keys()
    if unknown:
        raise ValueError(f'Roles need explicit native bindings: {sorted(unknown)}')
    return {role.id: available[role.id] for role in program.roles}


def build_native_qec_inputs(program: PBCProgram, bindings: Mapping[str, str] | None = None,
                            *, seed: int = 0, require_fault_tolerant: bool = False):
    """Lower a role program and reuse qec_layout's unchanged native platform.

    Unused physical atoms remain present as spectators, subject to all ordinary
    capture, collision and pulse-pair checks. No protocol is executed here.
    """
    if type(seed) is not int or seed < 0:
        raise ValueError('Seed must be a nonnegative integer')
    compiled = lower_to_physical(program, d3_role_bindings(program) if bindings is None else bindings,
                                 require_fault_tolerant=require_fault_tolerant)
    _, circuit, platform, placement = build_qec_inputs({
        'gates': [asdict(g) for g in compiled.circuit.gates], 'seed': seed})
    if not set(dict(compiled.bindings).values()) <= placement.keys():
        raise ValueError('Native bindings must use physical atoms on the existing 34-atom platform')
    if circuit != compiled.circuit:
        raise AssertionError('Native adapter changed the caller physical circuit')
    return NativeQECInputs(compiled, circuit, platform, placement, seed)
