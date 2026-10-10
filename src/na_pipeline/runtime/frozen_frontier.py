"""Link complete frozen component recipes, with bounded explicit qualification.

Internal module membership/order is retained. Components share one resource
schedule and one full world; independent component modules are interleaved.
"""
from copy import deepcopy
from pathlib import Path
import json

from na_pipeline.backend.enola_kernel import StrategyError, digest
from na_pipeline.backend.strategy_template import remap, geometry_world
from na_pipeline.backend.compiled_modules import _identity
from .compilation_guard import CompilationGuard
from .window_binding import bind_physical_plan


def join_recipes(recipes, dags):
    pending = []
    for i, recipe in enumerate(recipes):
        mapping = {m['id']: f'component:{i}/{m["id"]}' for m in recipe['modules']}
        pending.append(remap(deepcopy(recipe['modules']), mapping))
    modules = []
    # A stable interleave of whole existing modules, never a new gate partition.
    while any(pending):
        for sequence in pending:
            if sequence:
                modules.append(sequence.pop(0))
    owner = {s: m['id'] for m in modules for s in m['source_ids']}
    source = [n['id'] for d in dags for n in d['nodes']]
    if len(owner) != len(source) or set(owner) != set(source):
        raise StrategyError('FRONTIER_SOURCE_COVERAGE', 'Frozen recipe union must cover each source exactly once')
    seen = set()
    for module in modules:
        if not set(module['dependencies']) <= seen:
            raise StrategyError('FRONTIER_MODULE_ORDER', 'Each original module order must remain topological')
        seen.add(module['id'])
    return {'schema_version': 'CompilationDependencyDAG/0.1', 'modules': modules,
            'source_owner': owner, 'source_hashes': [digest(d) for d in dags],
            'composition_kind': 'whole_frozen_module_interleave', 'internal_batches_changed': False}


class FrozenFrontier:
    def __init__(self, library, *, qualification_directory, variant_limit=2048):
        self.library = library
        self.directory = Path(qualification_directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.variant_limit = variant_limit
        self.materializations = []
        self.runtime_guards = []

    def prepare(self, calls, session):
        dags, recipes, identities = [], [], []
        world = session.snapshot()['world_state']
        for call in calls:
            template = self.library._get(call['component'])
            actual = call['dags']
            self.library.adapter._check_ports(template, actual, world)
            recipes.append(template.bind_graph(actual))
            dags.extend(actual)
            identities.append({'component': call['component'], 'template_id': template.template_id,
                               'dag_hashes': [digest(d) for d in actual]})
        graph = join_recipes(recipes, dags)
        context = session.compilation_context(dags)
        modules = self.library.adapter.connections
        modules.recipe_graph_provider = lambda _: deepcopy(graph)
        allowed = {digest(m['dag']) for m in graph['modules']}
        compiler = modules.compile_module

        def qualified_leaf(dag, scene):
            if digest(dag) not in allowed:
                raise StrategyError('UNPLANNED_NATIVE_SOURCE', 'Only a frozen selected module may be materialized')
            clean, _ = geometry_world(scene, session.device)
            key = _identity(dag, scene, session.device, modules.compiler_hash)[0]
            identity = digest({'key': key, 'world': clean})
            if any(r['identity'] == identity for r in self.materializations):
                raise StrategyError('REPEATED_NATIVE_MATERIALIZATION', 'Stop and diagnose repeated compilation of identical geometry')
            if len(self.materializations) >= self.variant_limit:
                raise StrategyError('NATIVE_QUALIFICATION_BUDGET', 'Explicit finite native qualification limit reached')
            row = {'identity': identity, 'key': key, 'fragment_sha256': digest(dag), 'world_sha256': digest(clean),
                   'source_operations': len(dag['nodes']), 'world_atoms': len(scene['atoms']),
                   'status': 'started', 'authorization': 'T047_user_explicit_bounded_missing_fragments',
                   'internal_batch_membership_changed': False}
            self.materializations.append(row)
            path = self.directory/(f'{len(self.materializations):04d}-'+key+'.json')
            path.write_bytes((json.dumps(row, indent=2)+'\n').encode())
            try:
                result = compiler(dag, scene)
                row.update(status='qualified_native_body_built', module_hash=result['hash'])
                return result
            except BaseException as exc:
                row.update(status='failed', error=str(exc))
                raise
            finally:
                path.write_bytes((json.dumps(row, indent=2)+'\n').encode())

        modules.compile_module = qualified_leaf
        before = deepcopy(modules.stats)
        try:
            # This explicit qualification is separate from the cache-only run.
            plan = modules.compose_recipe(dags, world, execution_context=context, build_missing=True)
        finally:
            modules.compile_module = compiler
        with CompilationGuard() as guard:
            with guard.scope(frontier=identities, phase='execute_binding_after_explicit_qualification'):
                session.validate_context(context)
                atom = bind_physical_plan(plan, context)
        self.runtime_guards.append(guard.receipt())
        plan['frozen_frontier'] = {'schema_version': 'FrozenComponentFrontier/0.1', 'components': identities,
            'internal_batches_changed': False, 'qualification_before': before, 'qualification_after': modules.stats,
            'runtime_guard': guard.receipt(), 'runtime_state_cached': False}
        # The receipt becomes part of the submitted plan identity.
        with CompilationGuard():
            atom = bind_physical_plan(plan, context)
        return {'context': context, 'physical_plan': plan, 'atom_program': atom}
