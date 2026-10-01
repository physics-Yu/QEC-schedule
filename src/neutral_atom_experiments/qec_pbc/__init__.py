"""Additive, explicitly scoped QEC / Pauli-measurement compilation prototype."""
from .pauli import PauliProduct
from .ir import (Role, BitExpr, GateTask, PauliMeasurement, Detector, Observable, MemoryContract, PBCProgram)
from .lowering import CompiledPBC, lower_to_physical
from .surface import (patch_roles, stabilizers, logical_product, logical_measurement,
                      syndrome_round, memory_program, decode_ideal_memory)
from .neutral_atom import NativeQECInputs, build_native_qec_inputs, d3_role_bindings

__all__ = ['PauliProduct', 'Role', 'BitExpr', 'GateTask', 'PauliMeasurement',
           'Detector', 'Observable', 'MemoryContract', 'PBCProgram', 'CompiledPBC', 'lower_to_physical',
           'patch_roles', 'stabilizers', 'logical_product', 'logical_measurement',
           'syndrome_round', 'memory_program', 'decode_ideal_memory',
           'NativeQECInputs', 'build_native_qec_inputs', 'd3_role_bindings']
