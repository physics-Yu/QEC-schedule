"""Scheduler API for immutable components and per-call physical bindings."""
from copy import deepcopy
from pathlib import Path
import json

from na_pipeline.backend.enola_kernel import StrategyError, digest
from na_pipeline.qec import validate_physical_dag
from .parametric_component import CompiledComponentTemplate, ParametricComponentAdapter
from .window_binding import bind_physical_plan
from .component_binding_cache import ComponentBindingCache


def _externalize_demo_inputs(name, plan):
    """A gallery's measurement fixture is not part of a reusable logical gate.

    Recover only an exact public source, retaining complete existing modules;
    mixed modules fail explicitly instead of being silently repartitioned.
    """
    nodes=[n for d in plan['physical_dags'] for n in d['nodes']]
    fixtures=[n for n in nodes if n['id'].startswith('test-input/')]
    if not fixtures:return plan, None
    from na_pipeline.qec.component_catalog import get_component_spec
    source=get_component_spec(name)['physical_dag']
    if source is None:raise StrategyError('COMPONENT_FIXTURE_BOUNDARY','No public physical source for this demo')
    kept={n['id']:n for n in source['nodes']};removed={n['id'] for n in fixtures}
    if set(kept)|removed!={n['id'] for n in nodes}:
        raise StrategyError('COMPONENT_FIXTURE_BOUNDARY','Demo contains operations outside the exact source/input boundary')
    for n in nodes:
        if n['id'] not in kept:continue
        want=kept[n['id']]
        if any(n[k]!=want[k] for k in ('kind','qubits','params','reads','writes','condition')) or set(n['after'])-removed!=set(want['after']):
            raise StrategyError('COMPONENT_FIXTURE_BOUNDARY','Demo operation differs from the current public component')
    if {r for n in fixtures for r in n['writes']}!=set(source['external_reads']):
        raise StrategyError('COMPONENT_FIXTURE_BOUNDARY','Synthetic producers must correspond exactly to external input ports')
    value=deepcopy(plan);value['physical_dags']=[deepcopy(source)]
    graph=value['module_composition']['dependency_graph'];modules=[]
    dropped={m['id'] for m in graph['modules'] if set(m['source_ids'])<=removed}
    for module in graph['modules']:
        if module['id'] in dropped:continue
        if not set(module['source_ids'])<=kept.keys():
            raise StrategyError('COMPONENT_FIXTURE_MIXED_MODULE','Input fixture is fused into an internal module; explicit qualification needed')
        module['dependencies']=[d for d in module['dependencies'] if d not in dropped]
        modules.append(module)
    graph['modules']=modules
    graph['source_owner']={sid:owner for sid,owner in graph['source_owner'].items() if sid in kept}
    return value, {'kind':'externalize_demo_input_fixture','removed_fixture_operations':sorted(removed),
                   'external_inputs':source['external_reads'],'internal_modules_repartitioned':False}


class LogicalGateLibrary:
    """No catalog demo placement, measurement value, frame or token is replayed.

    register() imports a compiled, validated source recipe. prepare() binds
    actual ports in a live session; the caller still owns submission/advance.
    T/TDG are adaptive calls through FactoryDataInterface, not static templates.
    """
    def __init__(self, device, *, connection_directory=None, budget=None, allow_connection_planning=True):
        self.adapter = ParametricComponentAdapter(device, connection_directory=connection_directory, budget=budget)
        self._templates = {}
        directory=self.adapter.connections.directory
        self.bindings=ComponentBindingCache(device,directory.parent/'component-bindings' if directory else None)
        self.allow_connection_planning=allow_connection_planning
        self._imported_dependencies=set()

    @property
    def stats(self):
        return {'recipe_build_count':self.bindings.geometry_builds,'strategy_compile_count':0,
            'geometry_cache_hits':self.bindings.geometry_hits,'geometry_disk_hits':self.bindings.geometry_disk_hits,
            'bind_count':self.bindings.stats['bind_count'],'bind_wall_seconds':self.bindings.stats['bind_wall_seconds'],
            'module_stats':self.adapter.connections.stats,'imported_dependencies':len(self._imported_dependencies),
            'build_missing':self.allow_connection_planning}

    def register(self, name, plan, *, validation):
        if (validation.get('passed') is not True or
                validation.get('input_sha256', {}).get('physical_plan') != digest(plan) or
                validation.get('input_sha256', {}).get('device') != digest(self.adapter.device)):
            raise StrategyError('COMPONENT_QUALIFICATION_MISMATCH', 'A passed report for this exact plan and device is required')
        source_plan, boundary = _externalize_demo_inputs(name, plan)
        template = CompiledComponentTemplate(source_plan)
        template.original_plan_hash=digest(plan)
        template.input_boundary=boundary
        if name in self._templates and self._templates[name].template_id != template.template_id:
            raise StrategyError('COMPONENT_VERSION_CONFLICT', 'Register changed semantics under a new explicit version')
        self._templates[name] = template
        return self.describe(name)

    def import_component(self, name, directory):
        root = Path(directory)
        plan=json.loads((root/'physical-plan.json').read_bytes())
        result=self.register(name,plan,validation=json.loads((root/'validation.json').read_bytes()))
        for instance in plan['module_composition']['instances']:
            ref=instance.get('artifact_ref',{});filename=ref.get('file')
            if not filename or Path(filename).name!=filename:raise StrategyError('COMPONENT_DEPENDENCY_REF','A local immutable dependency filename is required')
            source=root.parent/'compiled-modules'/filename
            if str(source.resolve()) in self._imported_dependencies:continue
            if not source.exists():raise StrategyError('COMPONENT_DEPENDENCY_MISSING','Component package omits its native dependency',file=str(source))
            raw=source.read_bytes();item=json.loads(raw);key=item['body']['key']
            if digest(item['body'])!=item['hash'] or item['hash']!=instance['module_hash']:
                raise StrategyError('COMPONENT_DEPENDENCY_HASH','Native dependency hash mismatch')
            target=self.adapter.connections.directory
            if target:
                dest=target/filename
                if dest.exists() and dest.read_bytes()!=raw:raise StrategyError('COMPONENT_DEPENDENCY_COLLISION','Refusing to overwrite an immutable native dependency')
                if not dest.exists():dest.write_bytes(raw)
            else:self.adapter.connections.cache.setdefault(key,[]).append(item)
            self._imported_dependencies.add(str(source.resolve()))
        return result

    def import_directory(self,directory):
        for folder in sorted(Path(directory).iterdir()):
            if (folder/'physical-plan.json').is_file():self.import_component(folder.name,folder)
        return self.catalog()

    def import_producer_component(self, stage, directory):
        """Reuse a checked parent partition; do not inherit native qualification.

        The independent source and partition proof are checked before exposing
        the new producer name. Cache-only prepare still stops on a missing leaf.
        """
        from .producer_recipe import derive_producer_recipe
        root = Path(directory)
        plan = json.loads((root/'physical-plan.json').read_bytes())
        validation = json.loads((root/'validation.json').read_bytes())
        template = derive_producer_recipe(plan, validation, self.adapter.device)
        if plan['physical_dags'][0]['protocol_binding']['stage_id'] != stage:
            raise StrategyError('PRODUCER_STAGE', 'Requested stage differs from the frozen parent')
        self.import_component('factory.'+stage, root)
        name = 'producer.'+stage
        if name in self._templates and self._templates[name].template_id != template.template_id:
            raise StrategyError('COMPONENT_VERSION_CONFLICT', 'Independent producer recipe changed')
        self._templates[name] = template
        return {**self.describe(name), 'derivation': deepcopy(template.derivation)}

    def component_for(self,dags):
        if len(dags)!=1:raise StrategyError('COMPONENT_BATCH_ADAPTER_REQUIRED','Use an explicitly compiled joint component for multiple DAGs')
        dag=dags[0];binding=dag.get('protocol_binding')
        if binding:
            name=('producer.' if binding.get('mode')=='independent_producer' else 'factory.')+binding['stage_id']
            if name=='factory.consume_correction':
                from .component_schedule import schedule_signature
                if schedule_signature(dags)[0]!=self._get(name).signature:name+='_tdg'
            return name
        return {'MEASURE':'MEASURE_Z','RESET':'RESET_Z'}.get(dag['operation'],dag['operation'])

    def import_canonical_cz(self, transport_directory, bare_directory):
        from .canonical_cz_recipe import derive_canonical_cz_recipe
        def read(path): return json.loads(Path(path).read_bytes())
        old, bare = Path(transport_directory), Path(bare_directory)
        template = derive_canonical_cz_recipe(read(old/'physical-plan.json'), read(old/'validation.json'),
            read(old/'device.json'), read(bare/'physical-plan.json'), read(bare/'validation.json'), self.adapter.device)
        name = 'CZ_CANONICAL'
        if name in self._templates and self._templates[name].template_id != template.template_id:
            raise StrategyError('COMPONENT_VERSION_CONFLICT','Canonical CZ source changed')
        self._templates[name] = template
        return {**self.describe(name), 'derivation':deepcopy(template.derivation)}

    def _get(self, name):
        if name not in self._templates:
            raise StrategyError('COMPONENT_NOT_REGISTERED', 'Import a qualified compiled recipe first', component=name)
        return self._templates[name]

    def describe(self, name):
        template = self._get(name)
        return {'schema_version': 'LogicalGateInterface/0.1', 'component': name,
                'template_id': template.template_id, 'operands': deepcopy(template.ports),
                'inputs': list(dict.fromkeys(r for d in template.dags for r in d.get('external_reads', []))),
                'outputs': list(dict.fromkeys(r for d in template.dags for r in d['result_producers'])),
                'original_plan_hash': template.original_plan_hash,
                'input_boundary': deepcopy(template.input_boundary),
                'placement_binding': 'per invocation, full current world',
                'frame_contract': 'physical component semantics; caller owns the live logical Clifford frame'}

    def catalog(self):
        return [self.describe(name) for name in self._templates]

    def source(self, name, *, operands, invocation_id, result_bindings=None):
        dags = self._get(name).instantiate_source(operands, namespace=invocation_id, result_bindings=result_bindings)
        for dag in dags: validate_physical_dag(dag)
        return dags

    def prepare(self, name, session, *, operands, invocation_id, result_bindings=None, allow_connection_planning=None):
        dags = self.source(name, operands=operands, invocation_id=invocation_id, result_bindings=result_bindings)
        return self.prepare_dags(name,session,dags,allow_connection_planning=allow_connection_planning)

    def prepare_dags(self, name, session, dags, *, allow_connection_planning=None):
        """Bind a scheduler/controller's exact source, including its provenance/guard."""
        dags=deepcopy(dags if isinstance(dags,list) else [dags])
        for dag in dags:validate_physical_dag(dag)
        context = session.compilation_context(dags)
        world = session.snapshot()['world_state']
        template=self._get(name)
        template.bind_graph(dags)
        allow=self.allow_connection_planning if allow_connection_planning is None else allow_connection_planning
        before=self.adapter.connections.stats
        plan=self.bindings.prepare(template,dags,world,context,
            lambda canonical,clean:self.adapter.instantiate(template,clean,dags=canonical,allow_connection_planning=allow))
        after=self.adapter.connections.stats
        plan['module_composition']['counters_before']=before
        plan['module_composition']['counters_after']=after
        if plan['whole_component_binding']['cache_hit']:
            plan['module_composition']['binding_mode']='whole_component_geometry_equivalence'
            plan['module_composition']['leaf_receipt_scope']='original geometry qualification; current instance is covered by strategy_binding and whole_component_binding'
        plan['parametric_component_instance']={'schema_version':'ParametricComponentInstance/0.2',
            'component_template_id':template.template_id,'template_compile_calls':0,'internal_batch_selection_calls':0,
            'internal_module_graph_reconstruction_calls':0,'source_and_internal_partition_unchanged':True,
            'all_world_atoms_checked':len(world['atoms']),'runtime_results_epochs_tokens_cached':False,
            'whole_geometry_cache_hit':plan['whole_component_binding']['cache_hit'],
            'connection_work':{'legacy_fixed_fragment_materializations':after['leaf_compile_count']-before['leaf_compile_count'],
                'placement_candidates':after['placement_search_count']-before['placement_search_count'],
                'routing_calls':after['routing_search_count']-before['routing_search_count'],
                'checked_fragment_bindings':after['bind_count']-before['bind_count'],
                'geometry_cache_hits':after['cache_hit_count']-before['cache_hit_count']}}
        return {'schema_version': 'PreparedLogicalGate/0.1', 'component': name,
                'context': context, 'physical_plan': plan, 'atom_program': bind_physical_plan(plan, context),
                'results': [r for d in dags for r in d['result_producers']],
                'submitted': False, 'runtime_results_cached': False}
