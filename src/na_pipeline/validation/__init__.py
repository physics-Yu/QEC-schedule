"""Independent, fail-closed checks for the compile/schedule artifacts."""

from .checker import validate
from .scenario import make_scenario
from .semantic_frontend import audit_shor15
from .semantic_qec import audit_surface17
from .strategy import validate_strategy, validate_strategy_run
from .dag_core import audit_dependency_graph
from .hierarchical import validate_hierarchical_run
from .dag_entry import validate_preinitialized_entry
from .dag_logical import validate_logical_dag_source
from .dag_placement import validate_patch_placement
from .dag_physical import validate_physical_dag_source,validate_physical_plan
from .dag_coupling import audit_css_coupling
from .dag_session import validate_session_run
from .dag_resources import validate_resource_world,validate_resource_pool
from .dag_factory import validate_factory_initialize
from .dag_history import validate_session_history

__all__ = ["validate", "make_scenario", "audit_shor15", "audit_surface17", "validate_strategy", "validate_strategy_run", "audit_dependency_graph", "validate_hierarchical_run"]
__all__ += ["validate_preinitialized_entry", "validate_logical_dag_source", "validate_patch_placement"]
__all__ += ["validate_physical_dag_source", "validate_physical_plan", "audit_css_coupling"]
__all__ += ["validate_session_run", "validate_resource_world", "validate_resource_pool"]
__all__ += ["validate_factory_initialize"]
__all__ += ["validate_session_history"]
