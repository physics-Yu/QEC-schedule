"""Cache qualified whole-component geometry, never a live execution context.

An exact full-world match rebinds once, rather than replaying each leaf's full
geometry checker. New scene geometry still takes the qualified leaf path.
"""
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
import gzip,json,time
from hashlib import sha256
from na_pipeline.backend.physical_strategy import PhysicalStrategyLibrary
from na_pipeline.backend.strategy_template import canonical_dags,geometry_world,qualify_sites
from na_pipeline.backend.enola_kernel import digest,StrategyError


class ComponentBindingCache(PhysicalStrategyLibrary):
    def __init__(self,device,directory=None,capacity=32):
        super().__init__(device)
        self.directory=Path(directory) if directory else None
        if self.directory:self.directory.mkdir(parents=True,exist_ok=True)
        self.capacity=capacity;self._cache=OrderedDict();self.template_id=None
        root=Path(__file__).resolve().parents[1]
        from na_pipeline.backend.compiled_modules import native_compiler_sources
        self.code_identity=digest({'native':native_compiler_sources(),
            'binding':sha256(Path(__file__).read_bytes()).hexdigest(),
            'component_adapter':{n:sha256((root/'runtime'/n).read_bytes()).hexdigest()
                for n in ('parametric_component.py','fragment_order_binding.py')},
            'checker':{p.name:sha256(p.read_bytes()).hexdigest() for p in sorted((root/'validation').glob('*.py'))}})
        self.geometry_builds=0;self.geometry_hits=0;self.geometry_disk_hits=0

    def _inputs(self,dags,world):
        actual,canonical,mapping=canonical_dags(dags)
        clean,support=geometry_world(world,self.device)
        identity={'schema':'ComponentGeometryBinding/0.1','template_id':self.template_id,'device_hash':digest(self.device),'implementation':self.code_identity}
        key=digest({'canonical_dags':canonical,'entry_geometry':support,'identity':identity})
        return actual,canonical,mapping,clean,support,identity,key

    def prepare(self,template,dags,world,context,build):
        self.template_id=template.template_id
        _,canonical,_,clean,support,identity,key=self._inputs(dags,world)
        path=self.directory/(key+'.json.gz') if self.directory else None
        strategy=self._cache.get(key)
        if strategy is None and path and path.exists():
            strategy=json.loads(gzip.decompress(path.read_bytes()));self.geometry_disk_hits+=1
        hit=strategy is not None
        if strategy is None:
            plan=build(canonical,clean)
            # The builder uses canonical source with no session context. Its
            # result is a static geometry plan; no values/tokens enter storage.
            plan.pop('parametric_component_instance',None)
            plan['atom_program']['complete']=False
            plan['atom_program']['provenance'].update(requires_strategy_binding=True,requires_runtime_binding=True)
            body={'cache_key':key,'identity':identity,'entry_geometry':support,'canonical_dags':canonical,'template_plan':plan}
            body_hash=digest(body)
            strategy={'schema_version':'CompiledPhysicalStrategy/0.1','strategy_id':'physical-strategy:'+body_hash,
                      'strategy_hash':body_hash,'body':body,'build_metrics':{'compile_wall_seconds':0.}}
            if path:
                raw=gzip.compress(json.dumps(strategy,ensure_ascii=False,separators=(',',':')).encode(),mtime=0)
                tmp=path.with_suffix('.tmp');tmp.write_bytes(raw);tmp.replace(path)
            self.geometry_builds+=1
        else:self.geometry_hits+=1
        # Inherited binder checks body hash, all atom/site geometry and fresh
        # context, remaps every source/action/result, then finalizes once.
        result=self._bind(strategy,dags,world,execution_context=context)
        self._cache[key]=strategy;self._cache.move_to_end(key)
        while len(self._cache)>self.capacity:self._cache.popitem(last=False)
        result['whole_component_binding']={'schema_version':'ComponentGeometryBinding/0.1','cache_hit':hit,
            'template_id':template.template_id,'geometry_key':key,'full_scene_equivalence_checked':True,
            'leaf_revalidation_repeated':False if hit else True,'runtime_state_cached':False}
        return result
