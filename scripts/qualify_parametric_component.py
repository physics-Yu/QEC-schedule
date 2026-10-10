"""One compiled CNOT at horizontal/vertical/diagonal anchors plus a spectator."""
from pathlib import Path
from copy import deepcopy
import argparse,json,shutil,sys,time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT),str(ROOT/'scripts')]
from na_pipeline.runtime.parametric_component import CompiledComponentTemplate,ParametricComponentAdapter
from na_pipeline.device import canonical_surface17_device,build_preinitialized_state
from na_pipeline.runtime import run,make_scenario
from na_pipeline.validation.dag_physical import validate_physical_plan
from na_pipeline.backend.compiled_modules import _identity
from na_pipeline.backend.enola_kernel import StrategyError
from na_pipeline.runtime.pipeline import save_artifact


def world_at(device,anchors,*,rotate=False):
    return build_preinitialized_state(device,{p:{'aod_group':'data','basis':'Z','value':0} for p in anchors},
        {p:{'anchor_um':a,'orientation':'canonical_rot90' if rotate and p=='B' else 'x_vertical_z_horizontal'} for p,a in anchors.items()},
        placement_ref={'artifact_id':'parametric-CX-anchor-qualification','producer':'R0','fixture':True})


def qualify(source,out,module_source=None):
    out.mkdir(parents=True,exist_ok=True);device=canonical_surface17_device();original=json.loads(source.read_bytes())
    template=CompiledComponentTemplate(original)
    adapter=ParametricComponentAdapter(device,connection_directory=out/'connections',budget={'max_operations':100000,'max_wall_seconds':3600})
    scenarios=[('horizontal',{'A':[0.,900.],'B':[100.,900.]}),('vertical',{'A':[0.,700.],'B':[0.,900.]}),
        ('diagonal',{'A':[0.,700.],'B':[200.,900.]}),('distant_spectator',{'A':[0.,900.],'B':[100.,900.],'C':[800.,500.]})]
    if module_source:
        first=world_at(device,scenarios[0][1]);dags=template.instantiate_source({'control':'A','target':'B'},namespace='import')
        for module in template.bind_graph(dags)['modules']:
            key=_identity(module['dag'],first,device,adapter.connections.compiler_hash)[0]
            for src in module_source.glob(key+'-*.json'):shutil.copyfile(src,out/'connections'/src.name)
    results=[]
    for name,anchors in scenarios:
        started=time.perf_counter();world=world_at(device,anchors)
        # Both prior source-graph reconstruction and internal batch optimization
        # are forbidden. Only binding/fixed-fragment motion geometry is allowed.
        with (patch('na_pipeline.backend.compiled_modules.module_graph',side_effect=AssertionError('reconstructed internal graph')),
              patch('na_pipeline.backend.frontier_store.select_frontier',side_effect=AssertionError('internal batch search'))):
            plan=adapter.instantiate(template,world,operands={'control':'A','target':'B'},namespace=name)
        trace=run(plan['atom_program'],make_scenario(plan['atom_program']),device)
        report=validate_physical_plan(plan,device,trace=trace)
        if not report['passed']:raise ValueError(report)
        actions=plan['atom_program']['actions'];cz=[a for a in actions if a['kind']=='gate' and a['payload'].get('name')=='CZ']
        hs=[a for a in actions if a['kind']=='gate' and a['payload'].get('name')=='H']
        assert len(cz)==1 and len(cz[0]['payload']['pairs'])==9
        assert sum(len(a['atoms']) for a in hs)==18
        assert all(a['t_end_us']<=cz[0]['t_start_us'] or a['t_start_us']>=cz[0]['t_end_us'] for a in hs)
        receipt=plan['parametric_component_instance']
        if name=='distant_spectator':
            assert receipt['connection_work']['legacy_fixed_fragment_materializations']==0
            assert receipt['connection_work']['routing_calls']==0
        folder=out/name;folder.mkdir(exist_ok=True)
        for file,value in [('physical-plan.json',plan),('event-trace.json',trace),('validation.json',report)]:save_artifact(folder/file,value)
        row={'case':name,'anchors':anchors,'passed':True,'component_template_id':template.template_id,
             'cz_batches':1,'cz_pairs':9,'physical_H_count':18,'receipt':receipt,'wall_seconds':time.perf_counter()-started}
        results.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
    try:adapter.instantiate(template,world_at(device,scenarios[0][1],rotate=True),operands={'control':'A','target':'B'},namespace='rotated')
    except StrategyError as e:
        if e.code!='COMPONENT_CODE_ORIENTATION_OR_SHAPE':raise
        rotation={'rejected':True,'code':e.code}
    else:raise AssertionError('code rotation silently treated as anchor translation')
    summary={'schema_version':'ParametricComponentQualification/0.1','passed':True,'cases':results,
        'same_template_across_all_anchors':True,'unexpected_code_rotation':rotation,
        'scope':'Surface17 same-code-orientation logical CX; fixed existing source and internal module partition; actual geometry/events verified',
        'runtime_or_hardware_claim':'fake event qualification; no quantum state or hardware run'}
    save_artifact(out/'acceptance.json',summary);save_artifact(out/'component-template.json',template.definition)
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--module-source',type=Path);a=p.parse_args()
    qualify(a.source,a.out,a.module_source)
