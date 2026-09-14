"""Separate bounded four-patch platform; the two-patch world is unchanged."""
from math import isfinite
from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate,Position2D,Rectangle,StaticTrap,GridCoord,Zone,ZoneType
from neutral_atom_env.domain.operations import HardwareConfig
from neutral_atom_env.world import WorldState,AODRuntimeState
from neutral_atom_env.simulation.pipeline import Platform
from .qec_layout import _coordinates

DEFAULT_PATCH_ORIGINS=((0,0),(40,0),(0,40),(40,40))


def normalize_patch_origins(value):
    if not isinstance(value,(tuple,list)) or len(value)!=4:
        raise ValueError('Four-patch qec_patch_origins requires exactly four [x,y] origins')
    result=[]
    for point in value:
        if (not isinstance(point,(tuple,list)) or len(point)!=2 or
            any(type(v) not in (int,float) or not isfinite(v) or v%5 for v in point)):
            raise ValueError('Four-patch origins must be finite numeric 5 um grid coordinates')
        result.append(tuple(int(v) for v in point))
    points=_coordinates(result)
    if len(set(points))!=68:
        raise ValueError('Four-patch data and ancilla positions overlap')
    if any(not(-20<=x<=80 and -10<=y<=75) for x,y in points):
        raise ValueError('All 68 atoms must fit the four-patch SZ x=[-20,80], y=[-10,75] um')
    if any(not(-230<=y-220<=-150) for _,y in points):
        raise ValueError('Four-patch readout sites must fit MZ y=[-230,-150] um after the -220 um translation')
    return tuple(result)


def coordinates(origins=DEFAULT_PATCH_ORIGINS):
    return _coordinates(normalize_patch_origins(origins))


def build_qec_four_inputs(value):
    from neutral_atom_env.visualization.workbench import aod_shape,aod_offsets
    points=coordinates(value.get('qec_patch_origins',DEFAULT_PATCH_ORIGINS))
    shape_input={'layout':'surface_qec_ghz4'}|value
    rows,columns=aod_shape(shape_input)
    ro,co=aod_offsets(shape_input,rows,columns)
    def rect(x1,y1,x2,y2):return Rectangle(Position2D(x1,y1),Position2D(x2,y2))
    traps={}
    for i,(x,y) in enumerate(points):
        for prefix,dy,enabled in (('S',0,True),('M',-220,False)):
            key=f'{prefix}{i:03d}'
            traps[key]=StaticTrap(key,GridCoord(x//5,(y+dy)//5),Position2D(x,y+dy),enabled=enabled)
    for y in range(-115,-30,5):
        for x in range(-15,81,5):
            key=f'EZ_{x}_{-y}'
            traps[key]=StaticTrap(key,GridCoord(x//5,y//5),Position2D(x,y),enabled=False)
    world=WorldState(rect(-30,-240,180,100),traps,(
        Zone('SZ',ZoneType.STORAGE,rect(-20,-10,80,75)),
        Zone('EZ',ZoneType.ENTANGLEMENT,rect(-20,-120,85,-30)),
        Zone('MZ',ZoneType.MEASUREMENT,rect(-20,-230,85,-150))),grid_spacing_um=5)
    platform=Platform(world,HardwareConfig(ez_neighbor_guard_enabled=value.get('ez_neighbor_guard_enabled',False)),
        AODRuntimeState(rows=rows,columns=columns,spacing_um=5,pose=Position2D(-5,-5),
            row_offsets_um=None if ro==tuple(5*i for i in range(rows)) else ro,
            column_offsets_um=None if co==tuple(5*i for i in range(columns)) else co))
    circuit=PhysicalCircuit(tuple(PhysicalGate(**{k:v for k,v in g.items() if k!='column'}) for g in value['gates']))
    return value,circuit,platform,{f'Q{i:03d}':f'S{i:03d}' for i in range(68)}
