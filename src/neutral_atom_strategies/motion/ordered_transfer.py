"""SLM-to-SLM group transport on the shared ordered-axis discrete route family."""
from time import perf_counter
from neutral_atom_env.domain.operations import CaptureBinding, OperationType as K
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_strategies.scheduling.ordered_greedy import build_batch, empty_reconfigure, corridor_routes
from neutral_atom_strategies.motion.ordered_routes import OccupiedSLMGrid
from neutral_atom_env.hardware import get_backend
from .axis_hold_routes import transfer_annotation


class OrderedTransfer:
    def __init__(self, deadline=float('inf'), route_budget=128, motion_router='axis_hold'):
        self.motion_router=motion_router
        self.deadline=deadline; self.route_budget=route_budget; self.rejections=[]

    def move_loaded(self,p,target,label='Move supported AOD payload'):
        """Realize an externally chosen configuration, without choosing its use.

        No load/offload or measurement is inserted here. Failed route trials
        leave the caller's builder unchanged. The complete active Cartesian
        array is checked by the same physical backend as ordinary transfers.
        """
        start=p.state.aod.configuration()
        if start==target:return
        grid=OccupiedSLMGrid(p.state);backend=get_backend(p.state.hardware)
        paths=[r for r in corridor_routes(start,target,self.motion_router) if grid.allows(r)]
        paths.sort(key=lambda r:sum(backend.move_duration(p.state.aod.configured(a),b,p.state.hardware)
                                   for a,b in zip(r,r[1:])))
        for path in paths[:self.route_budget]:
            if perf_counter()>self.deadline:raise TimeoutError('Loaded AOD route deadline')
            trial=ProgramBuilder(p.origin,p.intent)
            trial.state=p.state;trial.operations=list(p.operations)
            trial.bindings=dict(p.bindings);trial.distance=p.distance
            try:
                for c in path[1:]:trial.add(K.AOD_MOVE,label,configuration=c)
                p.state=trial.state;p.operations=trial.operations
                p.bindings=trial.bindings;p.distance=trial.distance
                return
            except ValidationError as e:self.rejections.append({'code':e.violation.code,'message':str(e)})
        raise ValidationError('LOADED_ROUTE_EXHAUSTED',f'No validated route in {min(len(paths),self.route_budget)} candidates')

    def transfer_group(self,p,destinations,label='Ordered transfer'):
        destinations={q:t for q,t in destinations.items() if p.state.placement.atom_to_holder[q].holder_id!=t}
        if not destinations:return
        assignments=[]
        for q,t in sorted(destinations.items()):
            pos=p.state.world.traps[t].position
            assignments.append((q,q,q,pos.x_um,pos.y_um))
        batch=build_batch(p.state,assignments,check_interactions=False)
        unload=tuple(CaptureBinding(b.atom_id,b.cell,destinations[b.atom_id]) for b in batch.bindings)
        prepared=ProgramBuilder(p.origin,p.intent)
        prepared.state=p.state;prepared.operations=list(p.operations);prepared.bindings=dict(p.bindings);prepared.distance=p.distance
        empty_reconfigure(prepared,batch.pickup)
        prepared.add(K.AOD_LOAD,label+': load',bindings=batch.bindings)
        grid=OccupiedSLMGrid(prepared.state);backend=get_backend(p.state.hardware)
        paths=[path for path in corridor_routes(batch.pickup,batch.target,self.motion_router) if len(path)>=2 and grid.allows(path)]
        paths.sort(key=lambda path:sum(backend.move_duration(prepared.state.aod.configured(a),b,p.state.hardware) for a,b in zip(path,path[1:])))
        for path in paths[:self.route_budget]:
            if perf_counter()>self.deadline:raise TimeoutError('Ordered transfer deadline')
            trial=ProgramBuilder(p.origin,p.intent)
            trial.state=prepared.state;trial.operations=list(prepared.operations);trial.bindings=dict(prepared.bindings);trial.distance=prepared.distance
            try:
                for i,c in enumerate(path[1:],1):
                    # A disabled free destination needs no approach exemption:
                    # OFFLOAD establishes its support at the aligned endpoint.
                    # Keep a single straight departure when the backend accepts
                    # it; do not manufacture an overshoot just to label approach.
                    phase='depart' if i==1 else 'approach' if i==len(path)-1 else None
                    bindings=batch.bindings if phase=='depart' else unload if phase=='approach' else ()
                    if phase:phase,bindings=transfer_annotation(trial.state,trial.state.aod.configuration(),c,bindings,phase)
                    trial.add(K.AOD_MOVE,label,configuration=c,phase=phase,bindings=bindings)
                trial.add(K.AOD_OFFLOAD,label+': offload',bindings=unload)
                p.state=trial.state;p.operations=trial.operations;p.bindings=trial.bindings;p.distance=trial.distance
                return
            except ValidationError as e:self.rejections.append({'code':e.violation.code,'message':str(e)})
        raise ValidationError('ORDERED_TRANSFER_EXHAUSTED',f'No validated SLM transfer in {min(len(paths),self.route_budget)} finite routes; {self.rejections[-3:]}')
