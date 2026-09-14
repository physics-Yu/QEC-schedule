"""4A first-attempt layout contracts; no compiler or physics substitution."""
import pytest

from neutral_atom_experiments.qec_layout import build_qec_inputs, coordinates, normalize_patch_origins
from neutral_atom_env.domain.models import Position2D as P, Rectangle, StaticTrap, GridCoord, Zone, ZoneType
from neutral_atom_env.domain.operations import HardwareConfig
from neutral_atom_env.world import WorldState, AODRuntimeState
from neutral_atom_env.platform import Platform, initialize
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_strategies.motion.patch_array import PatchArrayCompiler


def legacy_platform():
    # Frozen pre-origins public platform contract, independent of the new
    # coordinate helper. Full canonical comparison protects absent/default
    # input behavior including trap names/masks and nonuniform AOD settings.
    data=[(40*b+10*(q%3),10*(q//3)) for b in range(2) for q in range(9)]
    checks=((5,5),(15,15),(15,-5),(5,25),(15,5),(5,15),(-5,5),(25,15))
    points=data+[(40*b+x,y) for b in range(2) for x,y in checks]
    traps={}
    for i,(x,y) in enumerate(points):
        for prefix,dy,enabled in (('S',0,True),('M',-200,False)):
            key=f'{prefix}{i:03d}'
            traps[key]=StaticTrap(key,GridCoord(x//5,(y+dy)//5),P(x,y+dy),enabled=enabled)
    for y in range(-115,-30,5):
        for x in range(-15,81,5):
            key=f'EZ_{x}_{-y}'
            traps[key]=StaticTrap(key,GridCoord(x//5,y//5),P(x,y),enabled=False)
    world=WorldState(Rectangle(P(-30,-240),P(180,100)),traps,(
        Zone('SZ',ZoneType.STORAGE,Rectangle(P(-20,-10),P(80,35))),
        Zone('EZ',ZoneType.ENTANGLEMENT,Rectangle(P(-20,-120),P(85,-30))),
        Zone('MZ',ZoneType.MEASUREMENT,Rectangle(P(-20,-230),P(85,-150)))),grid_spacing_um=5)
    return Platform(world,HardwareConfig(ez_neighbor_guard_enabled=False),AODRuntimeState(rows=7,columns=14,
        spacing_um=5,pose=P(-5,-5),row_offsets_um=None,
        column_offsets_um=tuple(range(0,35,5))+tuple(range(40,75,5))))


def test_absent_and_explicit_default_origins_preserve_complete_legacy_platform():
    absent={'gates':[]};explicit={'gates':[],'qec_patch_origins':[[0.0,0.0],[40.0,0.0]]}
    _,_,first,placement=build_qec_inputs(absent)
    _,_,second,_=build_qec_inputs(explicit)
    assert canonical_json(first)==canonical_json(second)==canonical_json(legacy_platform())
    assert 'qec_patch_origins' not in absent
    assert placement=={f'Q{i:03d}':f'S{i:03d}' for i in range(34)}


def test_staggered_origins_change_real_holders_and_preserve_fixed_platform():
    value={'gates':[],'qec_patch_origins':[[0,0],[45,5]],'aod_rows':8,'aod_columns':14,
        'aod_row_offsets_um':list(range(0,40,5)),
        'aod_column_offsets_um':list(range(0,35,5))+list(range(45,80,5))}
    returned,circuit,platform,placement=build_qec_inputs(value)
    state=initialize(circuit,platform,placement)
    assert returned is value
    assert state.placement.position('Q000',state.world,state.aod)==P(0,0)
    assert state.placement.position('Q009',state.world,state.aod)==P(45,5)
    assert state.placement.position('Q017',state.world,state.aod)==P(65,25)
    assert state.placement.position('Q026',state.world,state.aod)==P(50,10)
    assert state.placement.position('Q033',state.world,state.aod)==P(70,20)
    for i,point in enumerate(coordinates(value['qec_patch_origins'])):
        assert platform.world.traps[f'S{i:03d}'].position==P(*point)
        assert platform.world.traps[f'M{i:03d}'].position==P(point[0],point[1]-200)
    legacy=legacy_platform()
    assert platform.world.bounds==legacy.world.bounds and platform.world.zones==legacy.world.zones
    assert {k:v for k,v in platform.world.traps.items() if k.startswith('EZ_')}=={
        k:v for k,v in legacy.world.traps.items() if k.startswith('EZ_')}
    assert platform.hardware==legacy.hardware
    assert state.aod.rows*state.aod.columns==112
    # Only matching/alignment is tested here; actual swept transport and full
    # circuit execution belong to the separately sequenced formal matrix.
    origin,bindings=PatchArrayCompiler().bindings(state,state.atoms)
    assert origin==P(-5,-5) and len(bindings)==34
    assert len({b.cell for b in bindings})==34
    assert state.aod.configuration().x_um==tuple(-5+x for x in value['aod_column_offsets_um'])
    assert state.aod.configuration().y_um==tuple(-5+y for y in value['aod_row_offsets_um'])


def test_origin_edit_does_not_silently_resize_or_reconfigure_aod():
    _,_,platform,_=build_qec_inputs({'gates':[],'qec_patch_origins':[[0,0],[45,5]]})
    assert (platform.aod.rows,platform.aod.columns)==(7,14)
    assert platform.aod.configuration().x_um==legacy_platform().aod.configuration().x_um


@pytest.mark.parametrize('origins',[None,[],[[0,0]],[[0,0],[40,0],[80,0]],[[0],[40,0]],
    [[False,0],[40,0]],[[0,0],[42,0]],[[0,0],[float('nan'),0]],[[0,0],[float('inf'),0]]])
def test_invalid_shape_grid_or_numeric_origins_rejected(origins):
    with pytest.raises(ValueError):normalize_patch_origins(origins)


@pytest.mark.parametrize('origins',[
    [[0,0],[0,0]],[[0,0],[10,0]],
    [[0,0],[60,0]],[[0,0],[40,15]],[[0,0],[10**1000,0]],
])
def test_overlap_or_out_of_fixed_storage_domain_rejected_before_world_generation(origins):
    with pytest.raises(ValueError):build_qec_inputs({'gates':[],'qec_patch_origins':origins})


def test_first_patch_can_move_and_full_atom_footprints_define_range_boundary():
    assert normalize_patch_origins([[-15,-5],[55,10]])==((-15,-5),(55,10))
    points=coordinates([[-15,-5],[55,10]])
    assert min(x for x,y in points)==-20 and max(x for x,y in points)==80
    assert min(y for x,y in points)==-10 and max(y for x,y in points)==35
