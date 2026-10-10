"""Bind an existing independent 2Q batch despite caller enumeration order.

This is a lookup adapter, not a scheduler: the batch membership and native
actions are immutable. A candidate must pass the original exact identity and
full-scene binder after a bijection of independent source operations.
"""
from collections import defaultdict
from copy import deepcopy
import json

from na_pipeline.backend.compiled_modules import CompiledModuleLibrary, _identity
from na_pipeline.backend.enola_kernel import StrategyError, digest


def _features(core):
    operations=core['operations'];ports={p['site']:p for p in core['entry_ports']}
    used=[q for o in operations for q in o['qubits']]
    if (core['groups'] or len(operations)<2 or len(used)!=len(set(used)) or
            any(o['kind']!='gate' or len(o['qubits'])!=2 or o['after'] or o['reads'] or o['writes'] or o['condition'] is not None for o in operations)):
        return None
    origin=[min(p['position_um'][i] for p in ports.values()) for i in (0,1)]
    def site(q):
        p=ports[q]
        return {**p,'site':None,'position_um':[p['position_um'][i]-origin[i] for i in (0,1)]}
    rows=[digest({'kind':o['kind'],'params':o['params'],'directed_ports':[site(q) for q in o['qubits']]}) for o in operations]
    if len(rows)!=len(set(rows)):return None
    key=digest({'schema':'IndependentBatchLookup/0.1','device':core['device'],'compiler':core['compiler'],
                'coordinate_support':core['coordinate_support'],'operations':sorted(rows)})
    return key,rows


class OrderInvariantModuleLibrary(CompiledModuleLibrary):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self._order_index=None
        self.order_bindings=0

    def _index_orders(self):
        index=defaultdict(list);seen=set()
        def add(item):
            if item.get('schema_version')!='CompiledModule/0.1' or item['hash'] in seen:return
            seen.add(item['hash']);body=item['body'];features=_features(body['identity'])
            if features:index[features[0]].append((body['key'],item['hash'],features[1]))
        for variants in self.cache.values():
            for item in variants:add(item)
        if self.directory:
            for path in sorted(self.directory.glob('*.json')):
                if path.name.startswith('frontier-'):continue
                add(json.loads(path.read_bytes()))
        self._order_index=index

    def get_or_build(self,dag,world,*,instance_id,build_missing=True):
        try:return super().get_or_build(dag,world,instance_id=instance_id,build_missing=False)
        except StrategyError as exc:
            if exc.code!='MODULE_DEPENDENCY_MISSING':raise
            original=exc
        key,core,*_= _identity(dag,world,self.device,self.compiler_hash)
        features=_features(core)
        if features:
            if self._order_index is None:self._index_orders()
            wanted={v:i for i,v in enumerate(features[1])}
            for cached_key,body_hash,order in self._order_index.get(features[0],[]):
                permutation=[wanted[v] for v in order]
                if permutation==list(range(len(permutation))):continue
                reordered=deepcopy(dag)
                reordered['nodes']=[deepcopy(dag['nodes'][i]) for i in permutation]
                # Exact original key includes direction, parameters, roles,
                # device/compiler and geometry. No relaxed native identity.
                if _identity(reordered,world,self.device,self.compiler_hash)[0]!=cached_key:continue
                artifact=next((a for a in self._read(cached_key) if a['hash']==body_hash),None)
                if artifact is None:continue
                try:bound=self.bind_module(artifact,reordered,world,instance_id=instance_id)
                except StrategyError as exc:
                    original.details['rejected'].append({'module_hash':body_hash,'reason':exc.code,'lookup':'independent_operation_order'})
                    continue
                self.counters['cache_hit_count']+=1;self.order_bindings+=1
                bound['module_binding'].update(cache_hit=True,misses=[],source_order_binding={
                    'schema_version':'IndependentBatchOrderBinding/0.1','requested_key':key,'existing_key':cached_key,
                    'existing_module_hash':body_hash,'requested_indices_in_cached_order':permutation,
                    'batch_membership_changed':False,'native_actions_changed':False,'search_calls':0})
                return bound
        if not build_missing:raise original
        # Qualification callers may explicitly build; full Shor callers never
        # enter here. Invalidate the lookup index when adding a planned variant.
        result=super().get_or_build(dag,world,instance_id=instance_id,build_missing=True)
        self._order_index=None
        return result
