"""Surface-17 circuit templates; no quantum state or sampled results."""

from .program import QECContractError, iter_physical_ops
from .surface17 import build_two_block_slice, surface17_definition
from .factory import (FactoryProtocolError, build_factory15to1_protocol,
                      bind_factory_stage, distillation_matrix, factory_stage_decision, factory_stage_program)

__all__ = ["build_two_block_slice", "iter_physical_ops", "surface17_definition", "QECContractError"]
__all__ += ["build_factory15to1_protocol", "factory_stage_program", "factory_stage_decision",
            "bind_factory_stage", "distillation_matrix", "FactoryProtocolError"]
from .logical_primitives import (LogicalPrimitiveError, build_logical_primitive,
                                 logical_primitive_capabilities, validate_primitive_contract)

__all__ += ["build_logical_primitive", "logical_primitive_capabilities",
            "validate_primitive_contract", "LogicalPrimitiveError"]
from .projection import check_projection_window

__all__ += ["check_projection_window"]
from .physical_dag import (PhysicalDAGError, build_patch_operation_spec,
                           physical_dag_from_program, build_factory_physical_dag,
                           validate_physical_dag)
from .hierarchical_binding import (physical_resource_requirements, build_physical_dag_bundle,
                                   materialize_physical_node, materialize_factory_protocol)

__all__ += ["PhysicalDAGError", "build_patch_operation_spec", "physical_dag_from_program",
            "build_factory_physical_dag", "validate_physical_dag", "physical_resource_requirements",
            "build_physical_dag_bundle", "materialize_physical_node", "materialize_factory_protocol"]
from .component_catalog import component_catalog, get_component_spec, get_component_result_ports, instantiate_component, shor_component_requirements
__all__ += ['component_catalog','get_component_spec','get_component_result_ports','instantiate_component','shor_component_requirements']
from .factory import build_factory_producer
from .factory_fleet import factory_fleet_requirements
__all__ += ['build_factory_producer','factory_fleet_requirements']
