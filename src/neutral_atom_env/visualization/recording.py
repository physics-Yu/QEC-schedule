"""Read-only simulation observer. Static geometry once, changed atoms per event."""
from collections import Counter
from math import ceil, floor
import json
from pathlib import Path
from neutral_atom_env.replay.serializer import primitive,canonical_json
from neutral_atom_env.replay.trajectory import axes_from_dict,target_axes
from neutral_atom_env.domain.models import Position2D
from neutral_atom_env.testing.theme import VisualTheme
from .summary import operation_category,movement_mode,summarize_intervals


class VisualRecorder:
    def __init__(self,state,theme=None):
        self.theme=theme or VisualTheme.load()
        self.backend=state.hardware.backend
        world=state.world;s=world.grid_spacing_um
        def axis(lo,hi,origin):
            return [origin+i*s for i in range(ceil((lo-origin)/s),floor((hi-origin)/s)+1)]
        xs=axis(world.bounds.lower.x_um,world.bounds.upper.x_um,world.grid_origin.x_um)
        ys=axis(world.bounds.lower.y_um,world.bounds.upper.y_um,world.grid_origin.y_um)
        from neutral_atom_env.hardware.trap_spacing import minimum_trap_spacing
        self.scene=primitive({'bounds':world.bounds,'spacing_um':s,'grid_x':xs,'grid_y':ys,'slm_clearance_um':state.hardware.slm_clearance_um,'aod_minimum_spacing_um':minimum_trap_spacing(state.hardware),
            'candidates':[Position2D(x,y) for x in xs for y in ys if world.is_candidate_site(Position2D(x,y))],
            'zones':world.zones,'traps':tuple(t for _,t in sorted(world.traps.items()))})
        self.frames=[];self.operations=[];self.plans={};self._atoms={};self._operation_keys=set();self._last_plan=None
        self._initial_time=state.time_us;self._version=None;self.metrics={}
        self.observe(state)

    def observe(self,state,event=None):
        """Pass directly to EagerScheduler.run(on_event=...). Does not retain state or trace."""
        if self._version is not None and state.version<=self._version:
            raise ValueError('VisualRecorder requires increasing committed versions')
        if self.frames and state.time_us<self.frames[-1]['time']:
            raise ValueError('VisualRecorder requires monotonic simulation time')
        self._version=state.version
        runtime=state.active_plan
        if runtime:
            self._last_plan=runtime.plan
            if runtime.plan.id not in self.plans:
                from neutral_atom_env.hardware import get_backend
                from neutral_atom_env.domain.aod import motion_target
                plan=runtime.plan;axes=state.aod.configured(plan.initial_aod_configuration)
                paths={b.atom_id:[] for b in plan.bindings};loaded=set()
                for op in plan.operations:
                    if op.operation_type.value=='entangling_pulse':break
                    if op.operation_type.value=='aod_load':
                        loaded={b.atom_id for b in plan.bindings}
                        for b in plan.bindings:paths[b.atom_id].append(axes.position(b.cell))
                    elif op.operation_type.value=='aod_park':
                        loaded.difference_update(b.atom_id for b in op.transfer_bindings)
                    elif op.operation_type.value=='aod_recapture':
                        loaded.update(b.atom_id for b in op.transfer_bindings)
                    elif op.operation_type.value=='aod_move':
                        axes=get_backend(state.hardware).target_aod(axes,motion_target(op))
                        if loaded:
                            for b in plan.bindings:
                                if b.atom_id in loaded:paths[b.atom_id].append(axes.position(b.cell))
                self.plans[plan.id]=primitive({'id':plan.id,'planner_id':plan.planner_id,'paths':paths,
                    'requested':sorted(plan.requested_atom_ids),'gate_id':next(iter(plan.intent.gate_ids))})
        active=self._last_plan
        gate_id=next(iter(active.intent.gate_ids)) if active else None
        gate=state.dag.nodes[gate_id] if gate_id else None
        activity={q:('measuring' if node.gate.gate_type=='MEASURE' else 'gating')
                  for node in state.dag.nodes.values() if node.status.value=='running' for q in node.gate.qubit_ids}
        aod=primitive(state.aod)
        source_axes=state.aod.configuration()
        end_axes=target_axes(aod,primitive(runtime.plan.operations[runtime.operation_index])) if state.aod.is_moving and runtime else None
        updates=[]
        for key,atom in sorted(state.atoms.items()):
            holder=state.placement.atom_to_holder[key]
            actually_moving=holder.holder_type.value=='mobile' and state.aod.is_moving
            if actually_moving and end_axes:
                cell=holder.holder_id
                actually_moving=(abs(source_axes.x_um[cell.column]-end_axes.x_um[cell.column])>=1e-12
                                 or abs(source_axes.y_um[cell.row]-end_axes.y_um[cell.row])>=1e-12)
            value=primitive({'id':key,'holder':holder,'position':state.placement.position(key,state.world,state.aod),
                'activity':activity.get(key,'lost' if holder.holder_type.value=='lost' else
                       'moving' if actually_moving else 'idle'),
                'measured':atom.measured})
            if self._atoms.get(key)!=value:updates.append(value);self._atoms[key]=value
        aod=primitive(state.aod);movement=None
        if runtime and runtime.operation_started_us is not None:
            op=runtime.plan.operations[runtime.operation_index];value=primitive(op)
            kind=op.operation_type.value
            if kind=='aod_move':
                movement={'start':runtime.operation_started_us,'duration':op.duration_us,'target':value['target_pose'],
                    'target_axes':primitive(target_axes(aod,value)),'profile':'cubic' if self.backend=='row_column' else 'linear'}
            key=(runtime.plan.id,op.id)
            if key not in self._operation_keys:
                self._operation_keys.add(key)
                record={'operation_type':kind,'moving_atom_ids':tuple(state.placement.mobile_occupancy.values()),
                        'source_configuration':primitive(state.aod.configuration()),
                        'target_configuration':movement['target_axes'] if movement else None}
                pulse_seen=any(o.operation_type.value=='entangling_pulse' for o in runtime.plan.operations[:runtime.operation_index])
                self.operations.append({'index':len(self.operations),'label':op.label,'kind':kind,
                    'start':runtime.operation_started_us,'end':runtime.operation_started_us+op.duration_us,
                    'plan_id':runtime.plan.id,'gate_id':gate_id,'captured':sorted(b.atom_id for b in op.transfer_bindings) if kind in ('aod_park','aod_recapture') else sorted(active.captured_atom_ids),
                    'planner_id':runtime.plan.planner_id,'transfer_phase':op.transfer_phase,
                    'category':operation_category(record,pulse_seen),'mode':movement_mode(record),
                    'moving_count':len(state.placement.mobile_occupancy) if kind=='aod_move' else 0})
        counts=Counter(node.status.value for node in state.dag.nodes.values())
        ready=[g.id for g in state.dag.ready_gates()]
        self.frames.append({'time':state.time_us,'version':state.version,'atom_updates':updates,'plan_id':active.id if active else None,
            'aod':aod,'axes':primitive(axes_from_dict(aod)),'movement':movement,
            'gate_status':gate.status.value if gate else 'idle',
            'gate_label':f"{gate_id} {gate.gate.gate_type}({', '.join(gate.gate.qubit_ids)})" if gate else '未执行门操作',
            'requested':sorted(active.requested_atom_ids) if active else [],
            'ready_frontier':ready[:20],'ready_count':len(ready),'gate_counts':dict(counts),
            'gate_statuses':{k:n.status.value for k,n in list(state.dag.nodes.items())[:12]},
            'label':state.trace.records and json.loads(state.trace.records[-1]).get('label','') or 'Initial'})
        self.metrics=state.metrics()

    def payload(self):
        start=max(self._initial_time,self.metrics.get('episode_start_us') or self._initial_time)
        summary=summarize_intervals(self.operations,start,self.frames[-1]['time'],self.metrics)
        first=self.operations[0] if self.operations else {}
        # Serialization detaches caller-owned data from this recorder's internal buffers.
        return json.loads(canonical_json({'format':'neutral-atom-view/1','scene':self.scene,'frames':self.frames,
            'theme':self.theme,'backend':self.backend,'duration':self.frames[-1]['time'],'start_time':self._initial_time,
            'operations':self.operations,'plans':list(self.plans.values()),'summary':summary,'requested':self.frames[0]['requested'],
            'captured':first.get('captured',[]),'gate_label':self.frames[0]['gate_label']}))

    def write(self,path):
        from .viewer import write_html
        return write_html(self.payload(),path)

    def write_json(self,path):
        path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(canonical_json(self.payload()),encoding='utf-8')
        return path

    @classmethod
    def from_snapshots(cls,snapshots,theme=None):
        from neutral_atom_env.simulation.state import SimulationState
        iterator=iter(snapshots)
        def restore(value):return SimulationState.restore(value if isinstance(value,str) else canonical_json(value))
        recorder=cls(restore(next(iterator)),theme)
        for saved in iterator:recorder.observe(restore(saved))
        return recorder
