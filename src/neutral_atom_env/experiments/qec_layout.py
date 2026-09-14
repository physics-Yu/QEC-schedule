"""Two rotated distance-three patches, including dedicated check ancillas.

The transport footprint is a nonuniform rectangular Cartesian array. Empty
intersections remain real active traps and pass ordinary capture/sweep checks.
"""
from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate, Position2D, Rectangle, StaticTrap, GridCoord, Zone, ZoneType
from neutral_atom_env.domain.operations import HardwareConfig
from neutral_atom_env.world import WorldState, AODRuntimeState
from neutral_atom_env.simulation.pipeline import Platform
from math import isfinite


DEFAULT_PATCH_ORIGINS=((0,0),(40,0))


def _coordinates(origins):
    data=[(ox+10*(q%3),oy+10*(q//3)) for ox,oy in origins for q in range(9)]
    checks=((5,5),(15,15),(15,-5),(5,25),(15,5),(5,15),(-5,5),(25,15))
    return data+[(ox+x,oy+y) for ox,oy in origins for x,y in checks]


def normalize_patch_origins(value):
    """Normalize the raw two-origin JSON field, without changing AOD axes.

    Physical coordinates remain integer grid coordinates, so explicitly
    supplying the historical defaults preserves the old platform JSON too.
    """
    if not isinstance(value,(tuple,list)) or len(value)!=2:
        raise ValueError('qec_patch_origins must contain exactly two [x_um, y_um] origins')
    result=[]
    for origin in value:
        if not isinstance(origin,(tuple,list)) or len(origin)!=2:
            raise ValueError('Each qec_patch_origins entry must contain x_um and y_um')
        if any(type(v) not in (int,float) or (type(v) is float and not isfinite(v)) or v%5!=0 for v in origin):
            raise ValueError('Patch origins must be finite numeric coordinates on the 5 um grid')
        result.append(tuple(int(v) for v in origin))
    result=tuple(result)
    positions=_coordinates(result)
    if len(set(positions))!=len(positions):
        raise ValueError('Patch origins make physical data or ancilla atoms overlap')
    if any(not(-20<=x<=80 and -10<=y<=35) for x,y in positions):
        raise ValueError('All patch data and ancilla coordinates must fit the fixed SZ x=[-20,80], y=[-10,35] um')
    return result


def coordinates(patch_origins=DEFAULT_PATCH_ORIGINS):
    return _coordinates(normalize_patch_origins(patch_origins))


def build_qec_inputs(value):
    """Consume already validated editable input; never replace its gates."""
    positions=coordinates(value.get('qec_patch_origins',DEFAULT_PATCH_ORIGINS))
    rows=value.get('aod_rows',7);columns=value.get('aod_columns',14)
    row_offsets=tuple(value.get('aod_row_offsets_um',range(0,35,5)))
    column_offsets=tuple(value.get('aod_column_offsets_um',tuple(range(0,35,5))+tuple(range(40,75,5))))
    def rect(x1,y1,x2,y2):
        return Rectangle(Position2D(x1,y1),Position2D(x2,y2))
    # This two-patch family keeps the established finite platform. Origins
    # are validated against its SZ before any grid is generated; changing
    # layout cannot silently buy a larger routing area or unbounded trap set.
    traps={}
    for i,(x,y) in enumerate(positions):
        for prefix,dy,enabled in (('S',0,True),('M',-200,False)):
            key=f'{prefix}{i:03d}'
            traps[key]=StaticTrap(key,GridCoord(x//5,(y+dy)//5),Position2D(x,y+dy),enabled=enabled)
    for y in range(-115,-30,5):
        for x in range(-15,81,5):
            key=f'EZ_{x}_{-y}'
            traps[key]=StaticTrap(key,GridCoord(x//5,y//5),Position2D(x,y),enabled=False)
    world=WorldState(rect(-30,-240,180,100),traps,
        (Zone('SZ',ZoneType.STORAGE,rect(-20,-10,80,35)),
         Zone('EZ',ZoneType.ENTANGLEMENT,rect(-20,-120,85,-30)),
         Zone('MZ',ZoneType.MEASUREMENT,rect(-20,-230,85,-150))),grid_spacing_um=5)
    hardware=HardwareConfig(ez_neighbor_guard_enabled=value.get('ez_neighbor_guard_enabled',False))
    platform=Platform(world,hardware,AODRuntimeState(rows=rows,columns=columns,spacing_um=5,
        pose=Position2D(-5,-5),
        row_offsets_um=None if row_offsets==tuple(5*i for i in range(rows)) else row_offsets,
        column_offsets_um=None if column_offsets==tuple(5*i for i in range(columns)) else column_offsets))
    circuit=PhysicalCircuit(tuple(PhysicalGate(**{k:v for k,v in g.items() if k!='column'}) for g in value['gates']))
    placement={f'Q{i:03d}':f'S{i:03d}' for i in range(34)}
    return value,circuit,platform,placement
