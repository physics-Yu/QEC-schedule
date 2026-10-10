"""Public logical scheduler facade; compiler plans never manufacture runtime state."""
from copy import deepcopy
from na_pipeline.qec.component_catalog import get_component_spec, instantiate_component, get_component_result_ports
from .physical_strategy import PhysicalStrategyLibrary
from .physical_dag import compile_physical_dag


class LogicalComponentCompiler:
    """Physical components accept caller bindings and the actual complete world.

    Adaptive T/TDG exposes the existing FactoryExecution protocol. A caller uses
    next_graph, this facade's compile_dags, bind_physical_plan and commit_stage.
    Lifecycle operations are handled by the controller, not fabricated motions.
    """
    def __init__(self, device, *, budget=None, enola_root=None, module_directory=None):
        self.device=deepcopy(device);self.budget=deepcopy(budget);self.enola_root=enola_root
        self.library=PhysicalStrategyLibrary(device,budget=budget,enola_root=enola_root)
        from .compiled_modules import CompiledModuleLibrary
        self.modules=CompiledModuleLibrary(device,directory=module_directory,budget=budget,enola_root=enola_root)

    def resolve_geometry(self, dag, world):
        from na_pipeline.qec.geometry_variants import resolve_geometry_variants
        return resolve_geometry_variants(dag, world)

    def build_dependencies(self, dags, world):
        """Compile missing leaf/connector variants, preserving the dependency DAG."""
        return self.modules.compose_recipe(dags,world,build_missing=True)

    def compose_recipe(self, dags, world, *, execution_context=None):
        """Pure link/bind; missing dependencies are an error, never whole-stage fallback."""
        return self.modules.compose_recipe(dags,world,execution_context=execution_context,build_missing=False)

    def describe(self, component_id):
        return get_component_spec(component_id)

    def with_frame_session(self, session):
        """Logical H is software here; compile() remains explicit physical API."""
        from na_pipeline.runtime.logical_frame import LogicalFrameSession
        return LogicalFrameSession(self, session)

    def result_ports(self, component_id):
        return get_component_result_ports(component_id)

    def instantiate(self, component_id, **bindings):
        return instantiate_component(component_id, **bindings)

    def compile_dags(self, dags, world, *, execution_context=None, cache=True):
        if cache and execution_context is not None:
            strategy=self.library.get_or_compile(dags,world)
            return self.library.bind(strategy,dags,world,execution_context=execution_context)
        return compile_physical_dag(dags,self.device,world,budget=self.budget,
                                    enola_root=self.enola_root,execution_context=execution_context)

    def compile(self, component_id, world, *, qubit_bindings=None, namespace='component',
                result_bindings=None, execution_context=None, protocol_binding=None):
        dag=self.instantiate(component_id,qubit_bindings=qubit_bindings,namespace=namespace,result_bindings=result_bindings,protocol_binding=protocol_binding)
        if dag['schema_version']!='PhysicalDAG/0.1.0':
            return dag
        dag=self.resolve_geometry(dag,world)
        self.build_dependencies(dag,world)
        return self.compose_recipe(dag,world,execution_context=execution_context)
