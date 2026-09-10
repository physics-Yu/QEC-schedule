"""Turn route candidates into backend-validated movement operations."""
from itertools import islice
from neutral_atom_env.domain.models import Position2D
from neutral_atom_env.domain.operations import Operation,OperationType as K
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware import get_backend
from .planners import RouteRequest,simplify_route


def plan_transport(planner,state,target,bindings,gate_id,start_index):
    backend=get_backend(state.hardware);source=state.aod.configuration()
    target=backend.target_aod(state.aod,target).configuration()
    request=RouteRequest(source,target,state.world.grid_spacing_um,state.world.grid_origin.x_um,bindings,state.world,state.hardware)
    errors=[]
    for candidate in islice(planner.candidates(request),64):
        try:
            route=simplify_route(candidate)
            if len(route)<2 or route[0]!=source or route[-1]!=target:raise ValidationError('INVALID_ROUTE','Route must include requested start and target')
            work=state;ops=[];travel=0
            def move(config,phase=None,returning=False):
                nonlocal work,travel
                before=work.aod.configuration()
                if backend.name=='rigid':
                    t=Position2D(config.x_um[0],config.y_um[0]);fields={'target_pose':t}
                    if backend.target_aod(work.aod,t).configuration()!=config:raise ValidationError('UNSUPPORTED_DEFORMATION','Rigid route changed spacing')
                else:t=config;fields={'target_configuration':config}
                shape=lambda c:(tuple(x-c.x_um[0] for x in c.x_um),tuple(y-c.y_um[0] for y in c.y_um))
                label='Depart source' if phase=='depart' else 'Approach offload' if phase=='approach' else 'Return corridor' if returning else 'Reconfigure axes' if shape(before)!=shape(config) else 'Corridor transport'
                d=backend.move_distance(work.aod,t);duration=backend.move_duration(work.aod,t,state.hardware)
                work=backend.move(work,t,transfer=phase,bindings=bindings);travel+=d
                ops.append(Operation(f'op{start_index+len(ops):02d}',K.AOD_MOVE,label,duration,transfer_phase=phase,**fields))
            for i,config in enumerate(route[1:]):move(config,'depart' if i==0 else None)
            backend.validate_pulse(work,gate_id)
            ops.append(Operation(f'op{start_index+len(ops):02d}',K.ENTANGLING_PULSE,'CZ pulse',state.hardware.pulse_duration_us))
            for config in reversed(route[:-1]):move(config,'approach' if config==source else None,True)
            return work,ops,travel
        except ValidationError as error:errors.append(error)
    if not errors:raise ValidationError('NO_ROUTE_CANDIDATES','Planner returned no candidates')
    v=errors[0].violation
    raise ValidationError(v.code,f'Exhausted {len(errors)} planner candidates, not proof of infeasibility. First: {v.message}',atom_ids=v.atom_ids,holder_id=v.holder_id,position=v.position)
