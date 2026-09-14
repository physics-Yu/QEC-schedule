"""2D patch inputs and optional discrete parking guard, without large compiles."""
from dataclasses import replace
import json

import pytest

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import MobileCellIndex as Cell, Position2D as P
from neutral_atom_env.domain.operations import HardwareConfig, OperationType as K, TaskIntent, TaskTarget
from neutral_atom_experiments.surface_ghz import experiment_input
from neutral_atom_env.hardware import get_backend
from neutral_atom_env.hardware.ez_neighbors import reservations
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_env.program.scheduled import scheduled_program
from neutral_atom_env.simulation import Executor, operation_program
from neutral_atom_env.simulation.runtime_validation import validate_runtime
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_app.visualization.workbench import build_inputs, validate_input, preview
from test_ez_neighbors import dense_state


def patch_input(**changes):
    return {'atom_count':36,'layout':'surface_patches','compiler':'patch_greedy',
            'ez_policy':'adaptive','seed':0,'gates':[],**changes}


def test_four_physical_patches_have_native_2d_coordinates_and_ez_translation():
    value,circuit,platform,placement=build_inputs(patch_input())
    aod=platform.aod
    assert (aod.rows,aod.columns)==(6,6)
    assert aod.configuration().x_um==aod.configuration().y_um==(0,10,20,40,50,60)
    assert platform.world.grid_spacing_um==5
    assert platform.world.bounds.lower==P(-20,-140)
    assert platform.world.bounds.upper==P(160,140)
    ez={t.position for t in platform.world.traps.values() if t.id.startswith('EZ')}
    for block in range(4):
        points=[]
        for local in range(9):
            q=9*block+local
            actual=platform.world.traps[placement[f'Q{q:03d}']].position
            assert actual==P(40*(block%2)+10*(local%3),40*(block//2)+10*(local//3))
            assert P(actual.x_um,actual.y_um-100) in ez
            points.append(actual)
        assert len({p.x_um for p in points})==len({p.y_um for p in points})==3
    assert platform.hardware.ez_neighbor_guard_enabled is True
    assert not aod.active_cells


def test_surface_example_disables_only_parking_guard_explicitly_and_round_trips():
    raw=experiment_input()
    assert raw['layout']=='surface_patches' and raw['compiler']=='patch_greedy'
    assert raw['ez_neighbor_guard_enabled'] is False
    value,_,platform,_=build_inputs(raw)
    assert validate_input(json.loads(json.dumps(value)))==value
    assert platform.hardware==replace(HardwareConfig(),ez_neighbor_guard_enabled=False)
    assert len(preview(raw)['recording']['frames'][0]['atom_updates'])==36


def test_explicit_nonuniform_axes_and_legacy_shape_are_distinct():
    raw=patch_input(aod_rows=2,aod_columns=3,aod_traps=6,
                    aod_row_offsets_um=[0,40],aod_column_offsets_um=[0,20,60])
    value,_,platform,_=build_inputs(raw)
    assert platform.aod.position(Cell(1,2))==P(60,40)
    assert value['aod_column_offsets_um']==[0,20,60]
    legacy=build_inputs({'atom_count':4,'layout':'row','compiler':'greedy','ez_policy':'adaptive',
                        'gates':[],'aod_traps':4})[2]
    assert (legacy.aod.rows,legacy.aod.columns)==(1,4)
    assert legacy.aod.row_offsets_um is None and legacy.aod.column_offsets_um is None
    assert legacy.world.bounds.upper==P(75,20)
    assert legacy.hardware.ez_neighbor_guard_enabled is True


@pytest.mark.parametrize('changes', [
    {'atom_count':35},{'aod_rows':6},{'aod_rows':12,'aod_columns':12},
    {'aod_rows':6,'aod_columns':6,'aod_traps':49},
    {'aod_rows':2,'aod_columns':3,'aod_row_offsets_um':[0,0]},
    {'aod_rows':2,'aod_columns':3,'aod_column_offsets_um':[1,10,20]},
    {'aod_rows':2,'aod_columns':3,'aod_column_offsets_um':[0,20,10]},
    {'aod_rows':2,'aod_columns':3,'aod_column_offsets_um':[0,10]},
    {'aod_rows':2,'aod_columns':3,'aod_column_offsets_um':[0,True,20]},
    {'ez_neighbor_guard_enabled':0},{'ez_neighbor_guard_enabled':'false'}])
def test_shape_offsets_and_guard_reject_ambiguous_or_invalid_input(changes):
    with pytest.raises(ValueError):validate_input(patch_input(**changes))


def test_disabled_guard_still_enforces_collision_and_restores_explicit_setting():
    safe=dense_state(mobile=(2,),pose=P(5,-2.5))
    state=replace(safe,hardware=replace(safe.hardware,ez_neighbor_guard_enabled=False))
    backend=get_backend(state.hardware)
    parked=backend.move(state,P(5,0))
    assert not tuple(reservations(parked))
    assert SimulationState.restore(parked.snapshot()).snapshot()==parked.snapshot()
    with pytest.raises(ValidationError,match='EZ_NEIGHBOR_OCCUPIED'):
        replace(parked,hardware=replace(parked.hardware,ez_neighbor_guard_enabled=True))
    with pytest.raises(ValidationError,match='PATH_BLOCKED|ACTIVE_TRAP_SWEEP'):
        backend.move(state,P(0,0))
    # Missing historical field defaults to enabled rather than silently bypassing.
    old=json.loads(parked.snapshot());del old['hardware']['ez_neighbor_guard_enabled']
    with pytest.raises(ValidationError,match='EZ_NEIGHBOR_OCCUPIED'):
        SimulationState.restore(json.dumps(old))


def test_warm_runtime_cache_cannot_hide_guard_reenable_on_illegal_parking():
    safe=dense_state(mobile=(2,),pose=P(5,-2.5))
    state=replace(safe,hardware=replace(safe.hardware,ez_neighbor_guard_enabled=False))
    target=get_backend(state.hardware).target_aod(state.aod,P(5,0)).configuration()
    p=ProgramBuilder(state,TaskIntent('guard-off-parking',TaskTarget(aod_configuration=target)))
    p.add(K.AOD_MOVE,'park with guard explicitly disabled',target=P(5,0))
    plan=scheduled_program(p.finish('test-guard-off'),state)
    operation_program._runtime_prefixes.clear()
    try:
        executor=Executor(state);executor.submit(plan);executor.run();validate_runtime(state)
        assert operation_program._runtime_prefixes
        before=state.snapshot();bad=replace(state)
        object.__setattr__(bad,'hardware',replace(bad.hardware,ez_neighbor_guard_enabled=True))
        with pytest.raises(ValidationError,match='EZ_NEIGHBOR_OCCUPIED'):validate_runtime(bad)
        assert state.snapshot()==before
    finally:operation_program._runtime_prefixes.clear()
