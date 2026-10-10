"""Opaque component recipes built once from the existing immutable module library."""
from copy import deepcopy
import gzip
import json
from pathlib import Path
import time

from na_pipeline.backend.physical_strategy import PhysicalStrategyLibrary
from na_pipeline.backend.logical_components import LogicalComponentCompiler
from na_pipeline.backend.enola_kernel import StrategyError, digest
from na_pipeline.backend.strategy_template import qualify_sites
from .component_schedule import schedule_signature


class ComponentRecipeLibrary(PhysicalStrategyLibrary):
    """Build mode fills missing recipes; execution mode never calls a compiler.

    A recipe retains the complete component body and exact entry geometry.
    The inherited binder applies fresh IDs, source records, runtime conditions
    and whole-world validation. No component is split by the logical driver.
    """
    def __init__(self, device, directory, *, build_missing=False, budget=None):
        super().__init__(device, budget=budget)
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.build_missing = build_missing
        self.components = LogicalComponentCompiler(device, budget=budget,
            module_directory=self.directory / 'modules')
        self.components.modules.frontier_selector=self._reuse_batch
        index=self.directory/'schedules/index.json'
        self.schedules=json.loads(index.read_bytes()) if index.exists() else {}
        self._active_schedule=None
        self._stats.update(recipe_build_count=0, recipe_disk_hit_count=0)

    @property
    def stats(self):
        return {**super().stats, 'module_stats': self.components.modules.stats,
                'missing_variant_policy':'reuse_compiled_component_batch_partition',
                'build_missing': self.build_missing}

    def _reuse_batch(self, library, operations, world, *, build_missing):
        active=self._active_schedule
        if active is None:
            raise StrategyError('COMPONENT_SCHEDULE_MISSING','An existing complete component schedule is required; no optimizer fallback')
        schedule=active['schedule'];batch_index=active['cursor']
        if batch_index>=len(schedule['batches']):raise StrategyError('COMPONENT_SCHEDULE_EXHAUSTED','Source has more couplings than its frozen component')
        selected=[active['ids'][i] for i in schedule['batches'][batch_index]]
        if not set(selected)<={o['id'] for o in operations}:
            raise StrategyError('COMPONENT_SCHEDULE_NOT_READY','Reused batch must respect the current complete source dependencies',batch=batch_index)
        active['cursor']+=1
        by_id={o['id']:o for o in operations}
        return [by_id[s] for s in selected],{'schema_version':'ReusedComponentBatch/0.1','decision_hash':digest({'schedule':schedule['original_plan_hash'],'batch':batch_index}),
            'selected_source_ids':selected,'ready_source_ids':[o['id'] for o in operations],
            'schedule_signature':schedule['signature'],'original_component_plan_hash':schedule['original_plan_hash'],
            'batch_index':batch_index,'selection_recomputed':False,'geometry_qualification_owner':'immutable_leaf_bind_or_new_connector',
            'complete_ready_source_ids':[o['id'] for o in operations],
            'deferred_by_frozen_component_order':[o['id'] for o in operations if o['id'] not in selected]}

    def _get_or_compile(self, physical_dags, world_state):
        _, canonical, _, clean, support, identity, key = self._inputs(physical_dags, world_state)
        path = self.directory / (key + '.json.gz')
        strategy = self._cache.get(key)
        if strategy is None and path.exists():
            strategy = json.loads(gzip.decompress(path.read_bytes()))
            self._stats['recipe_disk_hit_count'] += 1
        if strategy is not None:
            body = strategy['body']
            if (digest(body) != strategy['strategy_hash'] or body['identity'] != identity
                    or body['canonical_dags'] != canonical or body['entry_geometry'] != support):
                raise StrategyError('COMPONENT_RECIPE_IDENTITY', 'Immutable recipe input/hash changed')
            qualify_sites(body['template_plan']['atom_program']['initial_state'], clean)
            self._cache[key] = strategy
            self._stats['cache_hit_count'] += 1
            return deepcopy(strategy)
        if not self.build_missing:
            raise StrategyError('COMPONENT_RECIPE_MISSING', 'Prepare this complete component before execution', key=key)
        self._stats['cache_miss_count'] += 1
        started = time.perf_counter()
        signature,_,operations=schedule_signature(canonical)
        schedule=self.schedules.get(signature)
        if schedule is None and any(o['kind']=='gate' and len(o['qubits'])==2 for o in operations):
            raise StrategyError('COMPONENT_SCHEDULE_MISSING','Import the already compiled component schedule; no deep-search fallback',signature=signature)
        def reset_schedule():
            self._active_schedule={'schedule':schedule,'ids':[o['id'] for o in operations],'cursor':0} if schedule else None
        # The same component/geometry is composed once, never searched on a hit.
        reset_schedule()
        self.components.build_dependencies(canonical, clean)
        before = self.components.modules.stats
        reset_schedule()
        template = self.components.compose_recipe(canonical, clean)
        if schedule and self._active_schedule['cursor']!=len(schedule['batches']):raise StrategyError('COMPONENT_SCHEDULE_UNUSED','Frozen component couplings were not all consumed')
        self._active_schedule=None
        for counter in ('leaf_compile_count', 'placement_search_count', 'routing_search_count'):
            if self.components.modules.stats[counter] != before[counter]:
                raise StrategyError('COMPONENT_COMPOSITION_COMPILED', 'Pure composition invoked a native compiler')
        template['atom_program']['complete'] = False
        template['atom_program']['provenance'].update(requires_strategy_binding=True, requires_runtime_binding=True)
        body = {'cache_key': key, 'identity': identity, 'entry_geometry': support,
                'canonical_dags': canonical, 'template_plan': template,
                'compilation_counters': deepcopy(template['atom_program']['stats']),
                'support_domain': {'exact_all_atom_geometry': True, 'empty_AOD_only': True,
                                   'runtime_context_results_epochs_tokens_cached': False,
                                   'logical_component_boundary': 'opaque'}}
        body_hash = digest(body)
        strategy = {'schema_version': 'CompiledPhysicalStrategy/0.1',
                    'strategy_id': 'physical-strategy:' + body_hash, 'strategy_hash': body_hash,
                    'body': body, 'build_metrics': {'compile_wall_seconds': time.perf_counter()-started},
                    'qualification': 'requires_fresh_instance_validation'}
        raw = json.dumps(strategy, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
        tmp = path.with_suffix('.tmp')
        tmp.write_bytes(gzip.compress(raw, mtime=0)); tmp.replace(path)
        self._cache[key] = strategy
        if len(self._cache)>16:
            oldest=next(iter(self._cache))
            if oldest!=key:del self._cache[oldest]
        self._stats['recipe_build_count'] += 1
        self._stats['strategy_compile_count'] += 1
        self._stats['compile_wall_seconds'] += time.perf_counter()-started
        return deepcopy(strategy)
