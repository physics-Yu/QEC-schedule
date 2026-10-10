"""Replicate an explicit relative factory layout without copying live state."""
from copy import deepcopy
from math import isfinite
from .errors import fail


def place_factory_lines(requirements,origins_um,*,prototype=None):
    prototype=deepcopy(prototype or {'schema_version':'FactoryLayout/0.1',
        'patch_offsets_um':{slot:[100.*i,0.] for i,slot in enumerate(('W0','W1','W2','W3','W4','M','Y'))},
        'probe_offset_um':[700.,80.],'orientation':'x_vertical_z_horizontal',
        'source':'canonical surface17 engineering layout; not experimentally calibrated'})
    if set(origins_um)!=set(requirements['factories']):fail('FLEET_LAYOUT_COVERAGE','Provide one physical origin per factory line')
    patches={};probes={}
    for fid,origin in origins_um.items():
        if len(origin)!=2 or any(type(x) not in (int,float) or not isfinite(x) for x in origin):
            fail('FLEET_LAYOUT_ORIGIN','Factory origins must be finite 2D coordinates')
        slots=requirements['factory_slots'][fid]
        if set(slots)!=set(prototype['patch_offsets_um']):fail('FLEET_LAYOUT_PORTS','Prototype must contain every physical factory patch')
        for slot,pid in slots.items():
            offset=prototype['patch_offsets_um'][slot]
            patches[pid]={'anchor_um':[origin[i]+offset[i] for i in (0,1)],'orientation':prototype['orientation']}
        probes[requirements['factories'][fid]['probe']]=[origin[i]+prototype['probe_offset_um'][i] for i in (0,1)]
    return {'schema_version':'FactoryFleetPlacement/0.1','patch_placements':patches,'nonpatch_positions':probes,
        'prototype':prototype,'requires_full_world_geometry_validation':True,'copies_runtime_state':False}
