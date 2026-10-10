"""Sufficient continuous qualification for independent AOD array routes."""
from collections import defaultdict
from .enola_kernel import capture_closure,StrategyError


def capture_assignment(scene, chosen, tolerance):
    atoms={a['atom_id']:a for a in scene};groups=defaultdict(list)
    for c in chosen:groups[c['aod_group']].append(c)
    movers={c['mover'] for c in chosen};fixed={a for c in chosen for a in c['pair']}-movers;goals={}
    for group,cs in groups.items():
        selected={c['mover'] for c in cs};closure=set(capture_closure(scene,selected,tolerance=tolerance)['captured_atoms'])
        if closure&fixed:raise StrategyError('CAPTURE_INCLUDES_REQUIRED_SLM_PARTNER','An enabled intersection captures a required stationary partner')
        if any(atoms[a]['aod_group']!=group for a in closure):raise StrategyError('CAPTURE_CROSSES_AOD_GROUP','The other array cannot hide a coincident capture')
        axes=[{c['from_um'][k]:c['to_um'][k] for c in cs} for k in (0,1)]
        for a in closure:goals[a]=[axes[k][atoms[a]['position_um'][k]] for k in (0,1)]
    return goals


def separate_sweep_envelopes(scene,routes,tolerance):
    """Bounding rectangles include occupied and EMPTY Cartesian intersections.

    Disjoint X or Y projections imply that any time parameterization of these
    routes cannot intersect. Overlap is conservatively unqualified, not proved
    impossible. Each individual path must also pass the full-world router.
    """
    atoms={a['atom_id']:a for a in scene};bounds={}
    for group,path in routes.items():
        movers=list(path[-1]) if path else []
        points=[atoms[a]['position_um'] for a in movers]+[p for step in path for p in step.values()]
        bounds[group]=[[min(p[k] for p in points),max(p[k] for p in points)] for k in (0,1)]
    keys=list(bounds)
    for i,a in enumerate(keys):
        for b in keys[i+1:]:
            if not any(bounds[a][k][1]+tolerance<bounds[b][k][0] or bounds[b][k][1]+tolerance<bounds[a][k][0] for k in (0,1)):
                raise StrategyError('INDEPENDENT_AOD_SWEEP_NOT_QUALIFIED','Swept Cartesian envelopes overlap; simultaneous route not qualified',groups=[a,b],bounds=bounds)
    return {'schema_version':'IndependentArraySweep/0.1','bounds_um':bounds,'empty_intersections_included':True,
            'qualification':'separated_swept_rectangles_for_any_relative_timing'}


def route_arrays(compiler, scene, goals):
    from . import strategy_compile
    atoms={a['atom_id']:a for a in scene};groups=defaultdict(dict)
    for a,p in goals.items():groups[atoms[a]['aod_group']][a]=p
    c=compiler.device['concurrency']
    if len(groups)>1 and (not c['independent_aod_parallel'] or not c['independent_transfer_parallel'] or c['global_motion_lock']):
        raise StrategyError('DEVICE_INDEPENDENT_AOD_DISABLED','Device does not permit simultaneous independent arrays')
    routes={}
    for group,target in groups.items():
        compiler.route_calls+=1
        routes[group],_=strategy_compile.group_route(scene,target,compiler.device['geometry']['initial_spacing_um'])
    proof=separate_sweep_envelopes(scene,{g:p or [groups[g]] for g,p in routes.items()},compiler.device['geometry']['distance_tolerance_um']) if len(routes)>1 else None
    return routes,proof
