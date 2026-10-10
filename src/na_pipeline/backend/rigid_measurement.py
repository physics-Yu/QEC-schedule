"""Place a captured constellation by translation only, without atom-site matching."""
from copy import deepcopy
from math import isfinite

from .enola_kernel import StrategyError, capture_closure, digest, group_route


def rigid_measurement_placement(world_atoms, measured_ids, traps, device, *, allow_readout_waves=False):
    from na_pipeline.device.rigid_readout import rigid_site_id, rigid_readout_capacity
    if 'rigid_readout' not in device:
        raise StrategyError('RIGID_READOUT_PROFILE_REQUIRED','Explicit finite shape-preserving receiver lattice required')
    if not measured_ids or len(set(measured_ids)) != len(measured_ids):
        raise StrategyError('READOUT_QUBIT_ALIAS', 'A nonempty set of distinct measured atoms is required')
    capacity = rigid_readout_capacity(device)
    if capacity is not None and len(measured_ids) > capacity and not allow_readout_waves:
        raise StrategyError('READOUT_CAPACITY_EXCEEDED', 'Region enlargement does not change readout-channel capacity', required=len(measured_ids), available=capacity)
    world = {a['atom_id']: a for a in world_atoms}
    if any(a not in world for a in measured_ids):
        raise StrategyError('PHYSICAL_QUBIT_UNBOUND', 'Measured atom missing from current world')
    closure = capture_closure(world_atoms, measured_ids, tolerance=device['geometry']['distance_tolerance_um'])
    movers = closure['captured_atoms']
    groups = {world[a]['aod_group'] for a in movers}
    if not set(measured_ids) <= set(movers) or len(groups) != 1:
        raise StrategyError('RIGID_CAPTURE_GROUP', 'Captured array must contain all measured atoms and belong to one AOD')
    zone = device['zones']['measurement']
    xl, xr = zone['x_range_um'];yl, yr = zone['y_range_um']
    unbounded_x=xl is None and xr is None
    if any(v is None or not isfinite(v) for v in (yl,yr)) or not unbounded_x and any(v is None or not isfinite(v) for v in (xl,xr)):
        raise StrategyError('RIGID_MZ_BOUNDS_REQUIRED', 'Declare the finite measurement rectangle before allocating an array')
    points = [world[a]['position_um'] for a in movers]
    x0,x1 = min(p[0] for p in points),max(p[0] for p in points)
    y0,y1 = min(p[1] for p in points),max(p[1] for p in points)
    pitch = device['geometry']['initial_spacing_um'];margin = pitch
    if not unbounded_x and x1-x0 > xr-xl-2*margin or y1-y0 > yr-yl-2*margin:
        raise StrategyError('RIGID_ARRAY_DOES_NOT_FIT', 'Enlarge the declared measurement region; no squeezing or row splitting', array_bounds=[x0,x1,y0,y1], zone=zone)
    # A placement decision chooses one array translation, never independent endpoints.
    offsets = ([0.,pitch,-pitch,2*pitch,-2*pitch,4*pitch,-4*pitch] if unbounded_x else
               sorted({0.,xl+margin-x0,xr-margin-x1,(xl+xr-x0-x1)/2},key=lambda x:(abs(x),x)))
    by_position = {tuple(t['position_um']): t for t in traps}
    measured = set(measured_ids)
    rejections=[];route_calls=0
    target_bottom=yl+margin
    while target_bottom+y1-y0 <= yr-margin+1e-9:
        for dx in offsets:
            dy=target_bottom-y0
            if not unbounded_x and (x0+dx < xl+margin or x1+dx > xr-margin):
                continue
            goals={a:[world[a]['position_um'][0]+dx,world[a]['position_um'][1]+dy] for a in movers}
            if any(by_position.get(tuple(p),{}).get('occupant') is not None for p in goals.values()):
                rejections.append({'translation_um':[dx,dy],'reason':'DESTINATION_OCCUPIED'});continue
            try:
                route_calls+=1
                route,route_rejections=group_route(world_atoms,goals,pitch)
            except StrategyError as exc:
                rejections.append({'translation_um':[dx,dy],'reason':exc.code,'details':exc.details});continue
            assignments=[]
            for aid in movers:
                pos=goals[aid];existing=by_position.get(tuple(pos))
                if existing and existing['zone_id']!='measurement':
                    raise StrategyError('RIGID_MZ_SITE_ZONE', 'Existing site at target coordinate is not a measurement site')
                tid=existing['trap_id'] if existing else 'slm:rigid-mz:'+digest(pos)[:16]
                try:site_id=rigid_site_id(device,pos)
                except ValueError as exc:
                    raise StrategyError('RIGID_RECEIVER_LATTICE_MISMATCH',str(exc),atom_id=aid,position_um=pos) from exc
                assignments.append({'atom_id':aid,'qubit_id':world[aid]['qubit_id'],'from_um':list(world[aid]['position_um']),
                                    'position_um':pos,'trap_id':tid,'bank_id':'rigid-mz','site_id':site_id,
                                    'measured':aid in measured})
            return {'schema_version':'measurement-placement/0.2','algorithm':'rigid_array_translation',
                    'max_parallel_readouts':capacity,
                    'captured_atoms':movers,'measured_atoms':list(measured_ids),'spectator_atoms':[a for a in movers if a not in measured],
                    'capture_closure':closure,'translation_um':[dx,dy],'shape_bounds_um':[x0,x1,y0,y1],
                    'receiver_pattern':'compile_time_static_shape_preserving_SLM',
                    'assignments':assignments,'candidate_sites':[{'trap_id':a['trap_id'],'position_um':a['position_um'],
                                                               'occupant':None,'zone_id':'measurement','bank_id':a['bank_id'],'site_id':a['site_id']} for a in assignments],
                    'candidate_rejections':rejections,'placement_route_searches':route_calls,'route_rejections':route_rejections,
                    'preflight_route':deepcopy(route),'rigid_shape_preserved':True,'optimal_makespan_claimed':False}
        target_bottom+=pitch
    raise StrategyError('RIGID_MZ_PLACEMENT_EXHAUSTED', 'No valid whole-array translation in finite candidate search; not an infeasibility proof', rejections=rejections,route_searches=route_calls)
