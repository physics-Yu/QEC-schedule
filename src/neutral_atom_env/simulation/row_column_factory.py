"""Small reproducible backend comparisons; parameters are not lab calibrations."""
import json
from pathlib import Path
from dataclasses import replace
from neutral_atom_env.domain.models import Position2D, GridCoord
from neutral_atom_env.domain.operations import HardwareConfig
from .milestone1_factory import make_single_gate_state


def make_row_column_state(scenario='pair_compression',backend='row_column'):
    state=make_single_gate_state()
    path=Path(__file__).resolve().parents[3]/'configs/hardware/row_column.json'
    values=json.loads(path.read_text(encoding='utf-8'))
    values['mobile_pair_center']=Position2D(**values['mobile_pair_center'])
    values['backend']=backend
    hardware=HardwareConfig(**values)
    if scenario=='mobile_static':return replace(state,hardware=hardware)
    if scenario not in {'pair_compression','incidental','outer_pair_blocked'}:raise ValueError('Unknown row-column scenario')
    # Legal positive case uses adjacent tones; the former outer-column pair is a rejection case.
    positions=[Position2D(0,0),Position2D(10 if scenario=='outer_pair_blocked' else 5,0),Position2D(5 if scenario=='incidental' else 20,5),Position2D(25,5)]
    traps={key:replace(t,position=p,grid=GridCoord(round(p.x_um/5),round(p.y_um/5)))
           for (key,t),p in zip(state.world.traps.items(),positions)}
    return replace(state,world=replace(state.world,traps=traps),hardware=hardware)
