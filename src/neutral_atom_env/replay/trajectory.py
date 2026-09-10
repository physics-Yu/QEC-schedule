"""Observer sampling of the same backend axes and motion profile as execution."""
import json
from neutral_atom_env.domain.models import Position2D
from neutral_atom_env.domain.aod import AODConfiguration


def axes_from_dict(aod):
    xs=aod.get('column_offsets_um')
    ys=aod.get('row_offsets_um')
    if xs is None:xs=[i*aod['spacing_um'] for i in range(aod['columns'])]
    if ys is None:ys=[i*aod['spacing_um'] for i in range(aod['rows'])]
    return AODConfiguration(tuple(aod['pose']['x_um']+x for x in xs),tuple(aod['pose']['y_um']+y for y in ys))


def target_axes(aod,operation):
    value=operation.get('target_configuration')
    if value is not None:return AODConfiguration(**value)
    target=operation['target_pose']
    return axes_from_dict(aod).translated(target['x_um']-aod['pose']['x_um'],target['y_um']-aod['pose']['y_um'])


def sample_aod(state,time_us):
    axes=axes_from_dict(state['aod']);runtime=state['active_plan']
    if state['aod']['is_moving'] and runtime:
        op=runtime['plan']['operations'][runtime['operation_index']]
        u=max(0,min(1,(time_us-runtime['operation_started_us'])/op['duration_us']))
        if state['hardware']['backend']=='row_column':u=u*u*(3-2*u)
        target=target_axes(state['aod'],op)
        axes=AODConfiguration(tuple(a+u*(b-a) for a,b in zip(axes.x_um,target.x_um)),
                              tuple(a+u*(b-a) for a,b in zip(axes.y_um,target.y_um)))
    return axes


def sample_positions(snapshots,time_us):
    data=[json.loads(s) if isinstance(s,str) else s for s in snapshots]
    if not data or time_us<data[0]['time_us'] or time_us>data[-1]['time_us']:
        raise ValueError('Playback time is outside the recorded interval')
    state=next(s for s in reversed(data) if s['time_us']<=time_us)
    axes=sample_aod(state,time_us)
    positions={}
    for atom,h in state['placement']['atom_to_holder'].items():
        if h['holder_type']=='static':p=state['world']['traps'][h['holder_id']]['position'];positions[atom]=Position2D(**p)
        elif h['holder_type']=='mobile':
            cell=h['holder_id']
            positions[atom]=Position2D(axes.x_um[cell['column']],axes.y_um[cell['row']])
    return positions
