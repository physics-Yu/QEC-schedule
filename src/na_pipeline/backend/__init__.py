"""R4 public atom compilation API; see knowledge/roles/R4/interface.md."""
from .compiler import CompilationError, compile_physical
from .geometry import validate_cz_pairs, validate_motion
from .strategy import StrategyLibrary, bind_strategy
from .enola_kernel import StrategyError
from .patch_placement import place_patches, place_logical_dag, place_resource_requirements
from .logical_components import LogicalComponentCompiler
from .physical_window import compile_operation_window
from .physical_dag import compile_physical_dag
from .physical_strategy import PhysicalStrategyLibrary
from .measurement_circuit import compile_measurement_circuit, measurement_circuit_dag

__all__ = ["CompilationError", "compile_physical", "validate_motion", "validate_cz_pairs", "StrategyLibrary", "bind_strategy", "StrategyError", "place_patches", "place_logical_dag", "place_resource_requirements", "compile_operation_window", "compile_physical_dag", "PhysicalStrategyLibrary"]
__all__ += ["compile_measurement_circuit", "measurement_circuit_dag"]
__all__ += ["LogicalComponentCompiler"]
