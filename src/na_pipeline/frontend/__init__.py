"""R2 public logical frontend; no quantum-state or measurement simulator."""

from .program import (
    FrontendError,
    SynthesisRequiredError,
    build_shor15,
    iter_logical_ops,
    require_clifford_t,
    validate_logical,
)
from .postprocess import postprocess_phase
from .qasm import to_openqasm3
from .synthesis import synthesize_feedback, t_demand_for_phase
from .operator_certificate import certify_rotation
from .encoded import (
    encoded_operation_catalog, logical_block_ref, build_t000_program,
    iter_encoded_calls, validate_encoded_program, adapt_logical_program,
    make_encoded_call, make_encoded_program,
)
from .logical_dag import (build_logical_dag, build_patch_dag_example, patch_interaction_graph, patch_placement_inputs,
                          validate_logical_dag, ready_logical_nodes, logical_dag_requirements)

__all__ = [
    "FrontendError", "SynthesisRequiredError", "build_shor15",
    "iter_logical_ops", "require_clifford_t", "validate_logical",
    "postprocess_phase", "to_openqasm3", "synthesize_feedback", "t_demand_for_phase", "certify_rotation",
    "encoded_operation_catalog", "logical_block_ref", "build_t000_program",
    "iter_encoded_calls", "validate_encoded_program", "adapt_logical_program",
    "make_encoded_call", "make_encoded_program",
    "build_logical_dag", "build_patch_dag_example", "patch_interaction_graph",
    "patch_placement_inputs",
    "validate_logical_dag", "ready_logical_nodes", "logical_dag_requirements",
]
